"""
Torn Ranked War Tracker - Hit Claim Manager

Pure in-memory claim storage for VPS deployment.
Fast, no external dependencies.
"""

import time
from typing import Optional

from .models import HitClaim


class ClaimManager:
    """
    Manages hit claims for coordinated attacks.
    Claims auto-expire to prevent stale locks.
    All data lives in memory for maximum speed.
    """

    def __init__(self, default_expiry: int = 120, max_claims_per_user: int = 3):
        self.default_expiry = default_expiry
        self.max_claims_per_user = max_claims_per_user
        self._claims: dict[int, HitClaim] = {}
        self._prev_hospital_state: dict[int, bool] = {}
        print(f"ClaimManager: in-memory (expiry={default_expiry}s, max={max_claims_per_user})")

    def update_hospital_states(self, targets: list) -> list[int]:
        """Reset claims for targets that went back to hospital."""
        reset_claims = []
        for target in targets:
            target_id = target.user_id if hasattr(target, "user_id") else target.get("user_id")
            is_in_hospital = (
                target.hospital_status != "out"
                if hasattr(target, "hospital_status")
                else target.get("hospital_status") != "out"
            )
            was_in_hospital = self._prev_hospital_state.get(target_id, False)

            if not was_in_hospital and is_in_hospital:
                if target_id in self._claims:
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
        """Attempt to claim a target."""
        now = int(time.time())
        exp = expiry if expiry else self.default_expiry
        expiry_time = now + exp

        self._cleanup_expired()

        # Check existing claim
        existing = self._claims.get(target_id)
        if existing and existing.expires_at > now:
            if existing.claimed_by_id == claimer_id:
                existing.expires_at = expiry_time
                return True, "Claim extended", existing
            else:
                remaining = existing.expires_at - now
                return False, f"Already claimed by {existing.claimed_by} ({remaining}s)", existing

        # Check max claims per user
        user_claims = sum(
            1 for c in self._claims.values() if c.claimed_by_id == claimer_id and c.expires_at > now
        )
        if user_claims >= self.max_claims_per_user:
            return False, f"Maximum {self.max_claims_per_user} claims reached", None

        # Create claim
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
        """Release a claim."""
        existing = self._claims.get(target_id)
        if not existing:
            return False, "No active claim"
        if existing.claimed_by_id != claimer_id:
            return False, f"Claim belongs to {existing.claimed_by}"
        del self._claims[target_id]
        return True, "Claim released"

    def resolve(self, target_id: int, claimer_id: int) -> tuple[bool, str]:
        """Mark a claim as resolved (attack completed)."""
        existing = self._claims.get(target_id)
        if not existing:
            return False, "No active claim"
        if existing.claimed_by_id != claimer_id:
            return False, f"Claim belongs to {existing.claimed_by}"
        existing.resolved = True
        del self._claims[target_id]
        return True, "Claim resolved"

    def get_claim(self, target_id: int) -> Optional[HitClaim]:
        """Get claim on a target."""
        self._cleanup_expired()
        return self._claims.get(target_id)

    def get_all_claims(self) -> list[HitClaim]:
        """Get all active claims."""
        self._cleanup_expired()
        return list(self._claims.values())

    def _cleanup_expired(self) -> int:
        """Remove expired claims."""
        now = int(time.time())
        expired = [tid for tid, c in self._claims.items() if c.expires_at < now]
        for tid in expired:
            del self._claims[tid]
        return len(expired)

    def stats(self) -> dict:
        """Get claim statistics."""
        return {
            "active_claims": len(self.get_all_claims()),
            "storage": "memory",
        }


# Global instance
claim_manager: Optional[ClaimManager] = None


def init_claim_manager(default_expiry: int = 120, max_claims_per_user: int = 3) -> ClaimManager:
    global claim_manager
    claim_manager = ClaimManager(default_expiry=default_expiry, max_claims_per_user=max_claims_per_user)
    return claim_manager


def get_claim_manager() -> ClaimManager:
    global claim_manager
    if claim_manager is None:
        claim_manager = ClaimManager()
    return claim_manager
