"""
Torn Ranked War Tracker - Hit Claim Manager

Simple in-memory claim storage.
Note: On Vercel serverless, claims may not sync perfectly across instances.
For production use, configure Vercel KV for shared state.
"""

import os
import time
from typing import Optional

from .models import HitClaim


class ClaimManager:
    """
    Manages hit claims for coordinated attacks.
    Claims auto-expire to prevent stale locks.
    """

    def __init__(self, default_expiry: int = 120, max_claims_per_user: int = 3):
        self.default_expiry = default_expiry
        self.max_claims_per_user = max_claims_per_user
        self._claims: dict[int, HitClaim] = {}
        self._prev_hospital_state: dict[int, bool] = {}
        
        # Check for Vercel KV
        kv_url = os.getenv("KV_REST_API_URL")
        if kv_url:
            print("ClaimManager: Vercel KV detected - using shared storage")
            self._use_kv = True
        else:
            print("ClaimManager: Using in-memory storage")
            self._use_kv = False

    def _kv_get(self, key: str):
        """Get value from Vercel KV."""
        if not self._use_kv:
            return None
        try:
            import httpx
            url = os.getenv("KV_REST_API_URL")
            token = os.getenv("KV_REST_API_TOKEN")
            resp = httpx.get(f"{url}/get/{key}", headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                data = resp.json()
                return data.get("result")
        except Exception as e:
            print(f"KV get error: {e}")
        return None

    def _kv_set(self, key: str, value: str, ex: int = None):
        """Set value in Vercel KV with optional expiry."""
        if not self._use_kv:
            return False
        try:
            import httpx
            import json
            url = os.getenv("KV_REST_API_URL")
            token = os.getenv("KV_REST_API_TOKEN")
            if ex:
                endpoint = f"{url}/set/{key}/{value}/ex/{ex}"
            else:
                endpoint = f"{url}/set/{key}/{value}"
            resp = httpx.get(endpoint, headers={"Authorization": f"Bearer {token}"})
            return resp.status_code == 200
        except Exception as e:
            print(f"KV set error: {e}")
        return False

    def _kv_del(self, key: str):
        """Delete key from Vercel KV."""
        if not self._use_kv:
            return False
        try:
            import httpx
            url = os.getenv("KV_REST_API_URL")
            token = os.getenv("KV_REST_API_TOKEN")
            resp = httpx.get(f"{url}/del/{key}", headers={"Authorization": f"Bearer {token}"})
            return resp.status_code == 200
        except Exception as e:
            print(f"KV del error: {e}")
        return False

    def _kv_keys(self, pattern: str):
        """Get keys matching pattern from Vercel KV."""
        if not self._use_kv:
            return []
        try:
            import httpx
            url = os.getenv("KV_REST_API_URL")
            token = os.getenv("KV_REST_API_TOKEN")
            resp = httpx.get(f"{url}/keys/{pattern}", headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                return resp.json().get("result", [])
        except Exception as e:
            print(f"KV keys error: {e}")
        return []

    def _claim_to_str(self, claim: HitClaim) -> str:
        """Serialize claim for KV storage."""
        import json
        return json.dumps({
            "target_id": claim.target_id,
            "target_name": claim.target_name,
            "claimed_by": claim.claimed_by,
            "claimed_by_id": claim.claimed_by_id,
            "claimed_at": claim.claimed_at,
            "expires_at": claim.expires_at,
            "resolved": claim.resolved,
        })

    def _str_to_claim(self, data: str) -> Optional[HitClaim]:
        """Deserialize claim from KV storage."""
        if not data:
            return None
        try:
            import json
            d = json.loads(data)
            return HitClaim(**d)
        except:
            return None

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
                if self._use_kv:
                    self._kv_del(f"claim:{target_id}")
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
        """Attempt to claim a target."""
        now = int(time.time())
        exp = expiry if expiry else self.default_expiry
        expiry_time = now + exp

        if self._use_kv:
            # Check existing
            existing_str = self._kv_get(f"claim:{target_id}")
            existing = self._str_to_claim(existing_str) if existing_str else None
            
            if existing and existing.expires_at > now:
                if existing.claimed_by_id == claimer_id:
                    existing.expires_at = expiry_time
                    self._kv_set(f"claim:{target_id}", self._claim_to_str(existing), ex=exp)
                    return True, "Claim extended", existing
                else:
                    remaining = existing.expires_at - now
                    return False, f"Already claimed by {existing.claimed_by} ({remaining}s)", existing

            # Check max claims
            keys = self._kv_keys("claim:*")
            user_claims = 0
            for key in keys:
                c_str = self._kv_get(key)
                c = self._str_to_claim(c_str)
                if c and c.claimed_by_id == claimer_id and c.expires_at > now:
                    user_claims += 1
            
            if user_claims >= self.max_claims_per_user:
                return False, f"Maximum {self.max_claims_per_user} claims reached", None

            # Create claim
            claim = HitClaim(
                target_id=target_id, target_name=target_name,
                claimed_by=claimer_name, claimed_by_id=claimer_id,
                claimed_at=now, expires_at=expiry_time, resolved=False,
            )
            self._kv_set(f"claim:{target_id}", self._claim_to_str(claim), ex=exp)
            return True, "Target claimed successfully", claim
        else:
            # In-memory
            self._cleanup_expired()
            existing = self._claims.get(target_id)
            
            if existing:
                if existing.claimed_by_id == claimer_id:
                    existing.expires_at = expiry_time
                    return True, "Claim extended", existing
                else:
                    remaining = existing.expires_at - now
                    return False, f"Already claimed by {existing.claimed_by} ({remaining}s)", existing

            user_claims = sum(1 for c in self._claims.values() if c.claimed_by_id == claimer_id)
            if user_claims >= self.max_claims_per_user:
                return False, f"Maximum {self.max_claims_per_user} claims reached", None

            claim = HitClaim(
                target_id=target_id, target_name=target_name,
                claimed_by=claimer_name, claimed_by_id=claimer_id,
                claimed_at=now, expires_at=expiry_time, resolved=False,
            )
            self._claims[target_id] = claim
            return True, "Target claimed successfully", claim

    def unclaim(self, target_id: int, claimer_id: int) -> tuple[bool, str]:
        """Release a claim."""
        if self._use_kv:
            existing_str = self._kv_get(f"claim:{target_id}")
            existing = self._str_to_claim(existing_str)
            if not existing:
                return False, "No active claim"
            if existing.claimed_by_id != claimer_id:
                return False, f"Claim belongs to {existing.claimed_by}"
            self._kv_del(f"claim:{target_id}")
            return True, "Claim released"
        else:
            existing = self._claims.get(target_id)
            if not existing:
                return False, "No active claim"
            if existing.claimed_by_id != claimer_id:
                return False, f"Claim belongs to {existing.claimed_by}"
            del self._claims[target_id]
            return True, "Claim released"

    def get_claim(self, target_id: int) -> Optional[HitClaim]:
        """Get claim on a target."""
        if self._use_kv:
            now = int(time.time())
            c_str = self._kv_get(f"claim:{target_id}")
            c = self._str_to_claim(c_str)
            return c if c and c.expires_at > now else None
        else:
            self._cleanup_expired()
            return self._claims.get(target_id)

    def get_all_claims(self) -> list[HitClaim]:
        """Get all active claims."""
        if self._use_kv:
            now = int(time.time())
            claims = []
            for key in self._kv_keys("claim:*"):
                c_str = self._kv_get(key)
                c = self._str_to_claim(c_str)
                if c and c.expires_at > now:
                    claims.append(c)
            return claims
        else:
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
            "storage": "kv" if self._use_kv else "memory",
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
