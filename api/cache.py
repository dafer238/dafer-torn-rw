"""
Torn Ranked War Tracker - Caching Layer

Hybrid cache: in-memory for short-TTL data, SQLite-backed for long-lived data.
Designed to minimize RAM usage on small VPS instances while keeping
short-TTL lookups fast.
"""

import os
import pickle
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Optional, TypeVar, Generic
from threading import Lock

# Disk cache directory (next to the project root)
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """Single cache entry with metadata."""

    value: T
    created_at: float
    ttl: float
    hits: int = 0

    @property
    def age(self) -> float:
        """How old is this entry in seconds."""
        return time.time() - self.created_at

    @property
    def is_expired(self) -> bool:
        """Check if entry has exceeded its TTL."""
        return self.age > self.ttl

    @property
    def remaining_ttl(self) -> float:
        """Seconds until expiration."""
        return max(0, self.ttl - self.age)


class Cache:
    """
    In-memory cache with TTL support and max size limit.
    Thread-safe for concurrent access in async context.
    Use for short-TTL, high-frequency data only.
    """

    def __init__(self, default_ttl: float = 2.0, max_entries: int = 500):
        """
        Initialize cache.

        Args:
            default_ttl: Default time-to-live in seconds (2s for aggressive polling)
            max_entries: Maximum entries before evicting oldest
        """
        self._store: dict[str, CacheEntry] = {}
        self._lock = Lock()
        self.default_ttl = default_ttl
        self.max_entries = max_entries

        # Stats
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache if exists and not expired.

        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            entry = self._store.get(key)

            if entry is None:
                self.misses += 1
                return None

            if entry.is_expired:
                del self._store[key]
                self.misses += 1
                return None

            entry.hits += 1
            self.hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """
        Store value in cache.

        Args:
            key: Cache key
            value: Value to store
            ttl: Time-to-live in seconds (uses default if not specified)
        """
        with self._lock:
            # Evict expired entries if at max capacity
            if len(self._store) >= self.max_entries:
                self._evict_expired_locked()
            # If still at max, evict oldest entries
            if len(self._store) >= self.max_entries:
                self._evict_oldest_locked(len(self._store) - self.max_entries + 1)
            self._store[key] = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl=ttl if ttl is not None else self.default_ttl,
            )

    def delete(self, key: str) -> bool:
        """Remove key from cache."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def get_entry(self, key: str) -> Optional[CacheEntry]:
        """Get full cache entry with metadata."""
        with self._lock:
            entry = self._store.get(key)
            if entry and not entry.is_expired:
                return entry
            return None

    def get_or_none_with_age(self, key: str) -> tuple[Optional[Any], float]:
        """
        Get value and its age. Returns (value, age_seconds).
        Useful for showing "data is X seconds old" in UI.
        """
        with self._lock:
            entry = self._store.get(key)

            if entry is None:
                return None, 0.0

            if entry.is_expired:
                del self._store[key]
                return None, 0.0

            entry.hits += 1
            self.hits += 1
            return entry.value, entry.age

    def clear(self) -> int:
        """Clear all entries. Returns count of cleared entries."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count of removed entries."""
        with self._lock:
            return self._evict_expired_locked()

    def _evict_expired_locked(self) -> int:
        """Remove expired entries (must hold lock)."""
        expired = [k for k, v in self._store.items() if v.is_expired]
        for key in expired:
            del self._store[key]
        return len(expired)

    def _evict_oldest_locked(self, count: int):
        """Remove oldest entries (must hold lock)."""
        if count <= 0:
            return
        sorted_keys = sorted(
            self._store.keys(), key=lambda k: self._store[k].created_at
        )
        for key in sorted_keys[:count]:
            del self._store[key]

    def stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            total_requests = self.hits + self.misses
            return {
                "entries": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": self.hits / total_requests if total_requests > 0 else 0,
                "default_ttl": self.default_ttl,
                "storage": "memory",
            }


class DiskCache:
    """
    SQLite-backed cache with TTL support.
    For long-lived data that shouldn't consume RAM.
    Uses pickle for serialization, WAL mode for performance.
    """

    def __init__(self, name: str, default_ttl: float = 60.0):
        os.makedirs(CACHE_DIR, exist_ok=True)
        db_path = os.path.join(CACHE_DIR, f"{name}.db")
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value BLOB NOT NULL,
                expire_at REAL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_expire ON cache(expire_at)"
        )
        self._conn.commit()
        self._lock = Lock()
        self.default_ttl = default_ttl
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if exists and not expired."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT value, expire_at FROM cache WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            if row is None:
                self.misses += 1
                return None
            value_blob, expire_at = row
            if expire_at is not None and time.time() > expire_at:
                self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                self._conn.commit()
                self.misses += 1
                return None
            self.hits += 1
            return pickle.loads(value_blob)

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store value in cache with optional TTL."""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        expire_at = time.time() + effective_ttl if effective_ttl else None
        value_blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, expire_at) VALUES (?, ?, ?)",
                (key, value_blob, expire_at),
            )
            self._conn.commit()

    def delete(self, key: str) -> bool:
        """Remove key from cache."""
        with self._lock:
            cursor = self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._conn.commit()
            return cursor.rowcount > 0

    def clear(self) -> int:
        """Clear all entries."""
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) FROM cache")
            count = cursor.fetchone()[0]
            self._conn.execute("DELETE FROM cache")
            self._conn.execute("VACUUM")
            self._conn.commit()
            return count

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM cache WHERE expire_at IS NOT NULL AND expire_at < ?",
                (time.time(),),
            )
            self._conn.commit()
            removed = cursor.rowcount
            # Reclaim space after large cleanups
            if removed > 50:
                self._conn.execute("VACUUM")
                self._conn.commit()
            return removed

    def keys(self) -> list[str]:
        """Get all non-expired keys."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT key FROM cache WHERE expire_at IS NULL OR expire_at > ?",
                (time.time(),),
            )
            return [row[0] for row in cursor.fetchall()]

    def stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM cache WHERE expire_at IS NULL OR expire_at > ?",
                (time.time(),),
            )
            count = cursor.fetchone()[0]
        total_requests = self.hits + self.misses
        return {
            "entries": count,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hits / total_requests if total_requests > 0 else 0,
            "default_ttl": self.default_ttl,
            "storage": "disk",
        }

    def close(self):
        """Close database connection."""
        try:
            self._conn.close()
        except Exception:
            pass


# Global cache instances for different data types
# Short-TTL, high-frequency: in-memory with strict size limits
hospital_cache = Cache(default_ttl=2.0, max_entries=200)
player_cache = Cache(default_ttl=10.0, max_entries=500)
claims_cache = Cache(default_ttl=300.0, max_entries=100)
faction_cache = Cache(default_ttl=60.0, max_entries=50)


class RateLimiter:
    """
    Track API request rate to stay under Torn's 100/min limit.
    """

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: list[float] = []
        self._lock = Lock()

    def can_request(self) -> bool:
        """Check if we can make another request without exceeding limit."""
        self._cleanup()
        with self._lock:
            return len(self.requests) < self.max_requests

    def record_request(self) -> None:
        """Record that a request was made."""
        with self._lock:
            self.requests.append(time.time())

    def _cleanup(self) -> None:
        """Remove requests older than the window."""
        cutoff = time.time() - self.window_seconds
        with self._lock:
            self.requests = [t for t in self.requests if t > cutoff]

    def requests_remaining(self) -> int:
        """How many more requests can we make this minute."""
        self._cleanup()
        with self._lock:
            return max(0, self.max_requests - len(self.requests))

    def wait_time(self) -> float:
        """Seconds to wait before next request is safe."""
        self._cleanup()
        with self._lock:
            if len(self.requests) < self.max_requests:
                return 0.0
            # Wait until oldest request falls out of window
            oldest = min(self.requests)
            return max(0, oldest + self.window_seconds - time.time())


# Global rate limiter instance
rate_limiter = RateLimiter(max_requests=90, window_seconds=60)  # Leave 10 buffer

# Long-TTL, large data: disk-backed (SQLite)
# YATA estimates cached for 7 days - no RAM impact
yata_cache = DiskCache("yata", default_ttl=604800)