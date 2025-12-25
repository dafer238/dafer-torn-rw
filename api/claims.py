"""
Torn Ranked War Tracker - Hit Claim Manager

Manages the state of hit claims to prevent faction members
from attacking the same target simultaneously.
"""

import time
from typing import Optional
from threading import Lock

from .models import HitClaim


class ClaimManager:
    """
    Manages hit claims for coordinated attacks.
    Claims auto-expire to prevent stale locks.
    """

    def __init__(self, default_expiry: int = 120, max_claims_per_user: int = 3):
        """
        Initialize claim manager.

        Args:
            default_expiry: Default claim expiry time in seconds (2 minutes)
            max_claims_per_user: Maximum number of simultaneous claims per user
        """
        self._claims: dict[int, HitClaim] = {}  # target_id -> HitClaim
        self._lock = Lock()
        self.default_expiry = default_expiry
        self.max_claims_per_user = max_claims_per_user
        # Track previous hospital state for claim reset
        self._prev_hospital_state: dict[int, bool] = {}  # target_id -> was_in_hospital

    def update_hospital_states(self, targets: list) -> list[int]:
        """
        Update hospital states and reset claims for targets that went back to hospital.
        Returns list of target_ids whose claims were reset.
        """
        reset_claims = []
        with self._lock:
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
        """
        Attempt to claim a target.

        Returns:
            Tuple of (success, message, claim_object)
        """
        now = int(time.time())
        expiry_time = now + (expiry if expiry else self.default_expiry)

        with self._lock:
            # Clean up expired claims
            self._cleanup_expired()

            # Check if already claimed
            existing = self._claims.get(target_id)
            if existing:
                if existing.claimed_by_id == claimer_id:
                    # Same person reclaiming - extend the claim
                    existing.expires_at = expiry_time
                    return True, "Claim extended", existing
                else:
                    remaining = existing.expires_at - now
                    return (
                        False,
                        f"Already claimed by {existing.claimed_by} ({remaining}s remaining)",
                        existing,
                    )

            # Check max claims per user
            user_claims = sum(1 for c in self._claims.values() if c.claimed_by_id == claimer_id)
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

            self._claims[target_id] = claim
            return True, "Target claimed successfully", claim

    def unclaim(self, target_id: int, claimer_id: int) -> tuple[bool, str]:
        """
        Release a claim on a target.
        Only the claimer can release their own claim.

        Returns:
            Tuple of (success, message)
        """
        with self._lock:
            existing = self._claims.get(target_id)

            if not existing:
                return False, "No active claim on this target"

            if existing.claimed_by_id != claimer_id:
                return False, f"Claim belongs to {existing.claimed_by}"

            del self._claims[target_id]
            return True, "Claim released"

    def force_unclaim(self, target_id: int) -> tuple[bool, str]:
        """
        Force release a claim (admin function).
        Use sparingly - for resolving stuck claims.
        """
        with self._lock:
            if target_id in self._claims:
                del self._claims[target_id]
                return True, "Claim force released"
            return False, "No active claim on this target"

    def resolve(self, target_id: int, claimer_id: int) -> tuple[bool, str]:
        """
        Mark a claim as resolved (attack completed).
        """
        with self._lock:
            existing = self._claims.get(target_id)

            if not existing:
                return False, "No active claim on this target"

            if existing.claimed_by_id != claimer_id:
                return False, f"Claim belongs to {existing.claimed_by}"

            existing.resolved = True
            # Remove resolved claims after a short delay
            del self._claims[target_id]
            return True, "Attack resolved, claim released"

    def get_claim(self, target_id: int) -> Optional[HitClaim]:
        """Get the current claim on a target, if any."""
        with self._lock:
            self._cleanup_expired()
            return self._claims.get(target_id)

    def get_all_claims(self) -> list[HitClaim]:
        """Get all active (non-expired) claims."""
        with self._lock:
            self._cleanup_expired()
            return list(self._claims.values())

    def get_claims_by_user(self, user_id: int) -> list[HitClaim]:
        """Get all claims by a specific user."""
        with self._lock:
            self._cleanup_expired()
            return [c for c in self._claims.values() if c.claimed_by_id == user_id]

    def _cleanup_expired(self) -> int:
        """Remove expired claims. Returns count of removed."""
        now = int(time.time())
        expired = [tid for tid, claim in self._claims.items() if claim.expires_at < now]
        for tid in expired:
            del self._claims[tid]
        return len(expired)

    def stats(self) -> dict:
        """Get claim statistics."""
        with self._lock:
            self._cleanup_expired()
            return {
                "active_claims": len(self._claims),
                "default_expiry": self.default_expiry,
                "max_claims_per_user": self.max_claims_per_user,
            }


# Global claim manager instance - will be initialized with config
claim_manager: ClaimManager = None


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
