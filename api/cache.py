"""
Torn Ranked War Tracker - Caching Layer

In-memory cache with TTL support for API responses.
Designed for fast access and smart polling optimization.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional, TypeVar, Generic
from threading import Lock

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
    Simple in-memory cache with TTL support.
    Thread-safe for concurrent access in async context.
    """

    def __init__(self, default_ttl: float = 2.0):
        """
        Initialize cache.

        Args:
            default_ttl: Default time-to-live in seconds (2s for aggressive polling)
        """
        self._store: dict[str, CacheEntry] = {}
        self._lock = Lock()
        self.default_ttl = default_ttl

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
            expired = [k for k, v in self._store.items() if v.is_expired]
            for key in expired:
                del self._store[key]
            return len(expired)

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
            }


# Global cache instances for different data types
# Shorter TTL for hospital data (we want freshness)
hospital_cache = Cache(default_ttl=2.0)

# Slightly longer TTL for player info (doesn't change as fast)
player_cache = Cache(default_ttl=10.0)

# Claims cache - managed differently, but using same mechanism
claims_cache = Cache(default_ttl=300.0)  # 5 min TTL for claims

# Faction data cache
faction_cache = Cache(default_ttl=60.0)  # 1 min for faction info


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
