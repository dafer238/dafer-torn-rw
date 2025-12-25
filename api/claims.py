"""
Torn Ranked War Tracker - Hit Claim Manager

Manages the state of hit claims to prevent faction members
from attacking the same target simultaneously.

Uses PostgreSQL (Vercel Postgres) when available for shared state,
falls back to in-memory storage for local development.
"""

import os
import time
from typing import Optional

from .models import HitClaim


class ClaimManager:
    """
    Manages hit claims for coordinated attacks.
    Claims auto-expire to prevent stale locks.
    
    Uses PostgreSQL when POSTGRES_URL is configured,
    otherwise falls back to in-memory storage.
    """

    def __init__(self, default_expiry: int = 120, max_claims_per_user: int = 3):
        """
        Initialize claim manager.

        Args:
            default_expiry: Default claim expiry time in seconds (2 minutes)
            max_claims_per_user: Maximum number of simultaneous claims per user
        """
        self.default_expiry = default_expiry
        self.max_claims_per_user = max_claims_per_user
        
        # Try to initialize PostgreSQL
        self._db_url = None
        self._use_db = False
        self._init_db()
        
        # Fallback in-memory storage (for local dev or if DB unavailable)
        self._claims: dict[int, HitClaim] = {}
        self._prev_hospital_state: dict[int, bool] = {}
        
        if self._use_db:
            print("ClaimManager: Using PostgreSQL for shared state")
        else:
            print("ClaimManager: Using in-memory storage (local mode)")

    def _init_db(self):
        """Initialize PostgreSQL connection if configured."""
        # Vercel Postgres provides these env vars
        self._db_url = os.getenv("POSTGRES_URL")
        
        if not self._db_url:
            return
            
        try:
            import psycopg2
            
            # Create table if not exists
            conn = psycopg2.connect(self._db_url)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    target_id INTEGER PRIMARY KEY,
                    target_name TEXT NOT NULL,
                    claimed_by TEXT NOT NULL,
                    claimed_by_id INTEGER NOT NULL,
                    claimed_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    resolved BOOLEAN DEFAULT FALSE
                )
            """)
            conn.commit()
            cur.close()
            conn.close()
            self._use_db = True
        except Exception as e:
            print(f"PostgreSQL init failed: {e}, falling back to in-memory")
            self._use_db = False

    def _get_conn(self):
        """Get a new database connection."""
        import psycopg2
        return psycopg2.connect(self._db_url)

    def _db_cleanup_expired(self):
        """Remove expired claims from database."""
        if not self._use_db:
            return
        try:
            now = int(time.time())
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM claims WHERE expires_at < %s", (now,))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"DB cleanup error: {e}")

    def _db_get_claim(self, target_id: int) -> Optional[HitClaim]:
        """Get claim from database."""
        if not self._use_db:
            return None
        try:
            self._db_cleanup_expired()
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT target_id, target_name, claimed_by, claimed_by_id, claimed_at, expires_at, resolved "
                "FROM claims WHERE target_id = %s",
                (target_id,)
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            
            if row:
                return HitClaim(
                    target_id=row[0],
                    target_name=row[1],
                    claimed_by=row[2],
                    claimed_by_id=row[3],
                    claimed_at=row[4],
                    expires_at=row[5],
                    resolved=row[6],
                )
            return None
        except Exception as e:
            print(f"DB get error: {e}")
            return None

    def _db_set_claim(self, claim: HitClaim) -> bool:
        """Insert or update claim in database."""
        if not self._use_db:
            return False
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO claims (target_id, target_name, claimed_by, claimed_by_id, claimed_at, expires_at, resolved)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (target_id) DO UPDATE SET
                    target_name = EXCLUDED.target_name,
                    claimed_by = EXCLUDED.claimed_by,
                    claimed_by_id = EXCLUDED.claimed_by_id,
                    claimed_at = EXCLUDED.claimed_at,
                    expires_at = EXCLUDED.expires_at,
                    resolved = EXCLUDED.resolved
            """, (
                claim.target_id,
                claim.target_name,
                claim.claimed_by,
                claim.claimed_by_id,
                claim.claimed_at,
                claim.expires_at,
                claim.resolved,
            ))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print(f"DB set error: {e}")
            return False

    def _db_del_claim(self, target_id: int) -> bool:
        """Delete claim from database."""
        if not self._use_db:
            return False
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM claims WHERE target_id = %s", (target_id,))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print(f"DB del error: {e}")
            return False

    def _db_get_all_claims(self) -> list[HitClaim]:
        """Get all non-expired claims from database."""
        if not self._use_db:
            return []
        try:
            self._db_cleanup_expired()
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT target_id, target_name, claimed_by, claimed_by_id, claimed_at, expires_at, resolved "
                "FROM claims"
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            
            return [
                HitClaim(
                    target_id=row[0],
                    target_name=row[1],
                    claimed_by=row[2],
                    claimed_by_id=row[3],
                    claimed_at=row[4],
                    expires_at=row[5],
                    resolved=row[6],
                )
                for row in rows
            ]
        except Exception as e:
            print(f"DB get_all error: {e}")
            return []

    def update_hospital_states(self, targets: list) -> list[int]:
        """
        Update hospital states and reset claims for targets that went back to hospital.
        Returns list of target_ids whose claims were reset.
        """
        reset_claims = []
        
        for target in targets:
            target_id = target.user_id if hasattr(target, "user_id") else target.get("user_id")
            is_in_hospital = (
                target.hospital_status != "out"
                if hasattr(target, "hospital_status")
                else target.get("hospital_status") != "out"
            )

            was_in_hospital = self._prev_hospital_state.get(target_id, False)

            # If target was OUT and is now IN hospital, reset their claim
            if not was_in_hospital and is_in_hospital:
                if self._use_db:
                    if self._db_get_claim(target_id):
                        self._db_del_claim(target_id)
                        reset_claims.append(target_id)
                elif target_id in self._claims:
                    del self._claims[target_id]
                    reset_claims.append(target_id)

            self._prev_hospital_state[target_id] = is_in_hospital

        return reset_claims

    def claim(
        self,
        target_id: int,
        target_name: str,
        claimer_id: int,
        claimer_name: str,
        expiry: Optional[int] = None,
    ) -> tuple[bool, str, Optional[HitClaim]]:
        """
        Attempt to claim a target.

        Returns:
            Tuple of (success, message, claim_object)
        """
        now = int(time.time())
        expiry_time = now + (expiry if expiry else self.default_expiry)

        if self._use_db:
            return self._claim_db(target_id, target_name, claimer_id, claimer_name, now, expiry_time)
        else:
            return self._claim_memory(target_id, target_name, claimer_id, claimer_name, now, expiry_time)

    def _claim_db(
        self, target_id: int, target_name: str, claimer_id: int, claimer_name: str, now: int, expiry_time: int
    ) -> tuple[bool, str, Optional[HitClaim]]:
        """Claim using PostgreSQL."""
        # Check existing claim
        existing = self._db_get_claim(target_id)
        if existing:
            if existing.claimed_by_id == claimer_id:
                # Same person reclaiming - extend
                existing.expires_at = expiry_time
                self._db_set_claim(existing)
                return True, "Claim extended", existing
            else:
                remaining = existing.expires_at - now
                return (
                    False,
                    f"Already claimed by {existing.claimed_by} ({remaining}s remaining)",
                    existing,
                )

        # Check max claims per user
        all_claims = self._db_get_all_claims()
        user_claims = sum(1 for c in all_claims if c.claimed_by_id == claimer_id)
        if user_claims >= self.max_claims_per_user:
            return (
                False,
                f"Maximum {self.max_claims_per_user} claims reached",
                None,
            )

        # Create new claim
        claim = HitClaim(
            target_id=target_id,
            target_name=target_name,
            claimed_by=claimer_name,
            claimed_by_id=claimer_id,
            claimed_at=now,
            expires_at=expiry_time,
            resolved=False,
        )

        self._db_set_claim(claim)
        return True, "Target claimed successfully", claim

    def _claim_memory(
        self, target_id: int, target_name: str, claimer_id: int, claimer_name: str, now: int, expiry_time: int
    ) -> tuple[bool, str, Optional[HitClaim]]:
        """Claim using in-memory storage."""
        # Clean up expired
        self._cleanup_expired()

        existing = self._claims.get(target_id)
        if existing:
            if existing.claimed_by_id == claimer_id:
                existing.expires_at = expiry_time
                return True, "Claim extended", existing
            else:
                remaining = existing.expires_at - now
                return (
                    False,
                    f"Already claimed by {existing.claimed_by} ({remaining}s remaining)",
                    existing,
                )

        user_claims = sum(1 for c in self._claims.values() if c.claimed_by_id == claimer_id)
        if user_claims >= self.max_claims_per_user:
            return (
                False,
                f"Maximum {self.max_claims_per_user} claims reached",
                None,
            )

        claim = HitClaim(
            target_id=target_id,
            target_name=target_name,
            claimed_by=claimer_name,
            claimed_by_id=claimer_id,
            claimed_at=now,
            expires_at=expiry_time,
            resolved=False,
        )

        self._claims[target_id] = claim
        return True, "Target claimed successfully", claim

    def unclaim(self, target_id: int, claimer_id: int) -> tuple[bool, str]:
        """
        Release a claim on a target.
        Only the claimer can release their own claim.
        """
        if self._use_db:
            existing = self._db_get_claim(target_id)
            if not existing:
                return False, "No active claim on this target"
            if existing.claimed_by_id != claimer_id:
                return False, f"Claim belongs to {existing.claimed_by}"
            self._db_del_claim(target_id)
            return True, "Claim released"
        else:
            existing = self._claims.get(target_id)
            if not existing:
                return False, "No active claim on this target"
            if existing.claimed_by_id != claimer_id:
                return False, f"Claim belongs to {existing.claimed_by}"
            del self._claims[target_id]
            return True, "Claim released"

    def force_unclaim(self, target_id: int) -> tuple[bool, str]:
        """Force release a claim (admin function)."""
        if self._use_db:
            if self._db_get_claim(target_id):
                self._db_del_claim(target_id)
                return True, "Claim force released"
            return False, "No active claim on this target"
        else:
            if target_id in self._claims:
                del self._claims[target_id]
                return True, "Claim force released"
            return False, "No active claim on this target"

    def resolve(self, target_id: int, claimer_id: int) -> tuple[bool, str]:
        """Mark a claim as resolved (attack completed)."""
        if self._use_db:
            existing = self._db_get_claim(target_id)
            if not existing:
                return False, "No active claim on this target"
            if existing.claimed_by_id != claimer_id:
                return False, f"Claim belongs to {existing.claimed_by}"
            self._db_del_claim(target_id)
            return True, "Attack resolved, claim released"
        else:
            existing = self._claims.get(target_id)
            if not existing:
                return False, "No active claim on this target"
            if existing.claimed_by_id != claimer_id:
                return False, f"Claim belongs to {existing.claimed_by}"
            del self._claims[target_id]
            return True, "Attack resolved, claim released"

    def get_claim(self, target_id: int) -> Optional[HitClaim]:
        """Get the current claim on a target, if any."""
        if self._use_db:
            return self._db_get_claim(target_id)
        else:
            self._cleanup_expired()
            return self._claims.get(target_id)

    def get_all_claims(self) -> list[HitClaim]:
        """Get all active (non-expired) claims."""
        if self._use_db:
            return self._db_get_all_claims()
        else:
            self._cleanup_expired()
            return list(self._claims.values())

    def get_claims_by_user(self, user_id: int) -> list[HitClaim]:
        """Get all claims by a specific user."""
        all_claims = self.get_all_claims()
        return [c for c in all_claims if c.claimed_by_id == user_id]

    def _cleanup_expired(self) -> int:
        """Remove expired claims (in-memory only)."""
        now = int(time.time())
        expired = [tid for tid, claim in self._claims.items() if claim.expires_at < now]
        for tid in expired:
            del self._claims[tid]
        return len(expired)

    def stats(self) -> dict:
        """Get claim statistics."""
        all_claims = self.get_all_claims()
        return {
            "active_claims": len(all_claims),
            "default_expiry": self.default_expiry,
            "max_claims_per_user": self.max_claims_per_user,
            "storage": "postgres" if self._use_db else "memory",
        }


# Global claim manager instance
claim_manager: Optional[ClaimManager] = None


def init_claim_manager(default_expiry: int = 120, max_claims_per_user: int = 3) -> ClaimManager:
    """Initialize the global claim manager with configuration."""
    global claim_manager
    claim_manager = ClaimManager(
        default_expiry=default_expiry, max_claims_per_user=max_claims_per_user
    )
    return claim_manager


def get_claim_manager() -> ClaimManager:
    """Get the global claim manager, initializing with defaults if needed."""
    global claim_manager
    if claim_manager is None:
        claim_manager = ClaimManager()
    return claim_manager
