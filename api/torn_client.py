"""
Torn Ranked War Tracker - Torn API Client

Async HTTP client for interacting with Torn's API.
Handles rate limiting, key rotation, and error handling.
"""

import asyncio
import time
from typing import Optional
import httpx

from .models import PlayerStatus, HospitalStatus, OnlineStatus, FactionInfo, HitClaim
from .cache import hospital_cache, player_cache, faction_cache, rate_limiter


TORN_API_BASE = "https://api.torn.com"


def estimate_battle_stats(level: int) -> tuple[int, str]:
    """
    Estimate total battle stats based on level.
    Returns (estimated_total, formatted_string).

    This is a simplified version of YATA's estimation algorithm.
    Higher level = more stats (exponential growth).
    """
    if level <= 0:
        return 0, "?"

    # Base calculation from level
    # Exponential growth: stats roughly double every 10 levels above 50
    if level < 15:
        base = level * 50_000  # ~750k at level 15
    elif level < 30:
        base = 750_000 + (level - 15) * 200_000  # ~3.75M at level 30
    elif level < 50:
        base = 3_750_000 + (level - 30) * 500_000  # ~13.75M at level 50
    elif level < 75:
        base = 13_750_000 + (level - 50) * 2_000_000  # ~63.75M at level 75
    else:
        base = 63_750_000 + (level - 75) * 10_000_000  # ~313M+ at level 100

    total = int(base)

    # Format for display
    if total >= 1_000_000_000:
        formatted = f"{total / 1_000_000_000:.1f}B"
    elif total >= 1_000_000:
        formatted = f"{total / 1_000_000:.0f}M"
    elif total >= 1_000:
        formatted = f"{total / 1_000:.0f}K"
    else:
        formatted = str(total)

    return total, formatted


class TornAPIError(Exception):
    """Custom exception for Torn API errors."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Torn API Error {code}: {message}")


class TornClient:
    """
    Async client for Torn API with caching and rate limiting.
    """

    def __init__(self, api_keys: list[str]):
        """
        Initialize with one or more API keys.
        Multiple keys allow for higher effective polling rates.
        """
        self.api_keys = api_keys
        self.current_key_index = 0
        self.client = httpx.AsyncClient(timeout=10.0)
        self.api_calls_remaining = 100  # Track API calls remaining

        # Track per-key rate limiting
        self.key_requests: dict[str, list[float]] = {k: [] for k in api_keys}

    def _get_next_key(self) -> str:
        """Rotate through available API keys."""
        key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return key

    def _get_best_key(self) -> str:
        """Get the key with the fewest recent requests."""
        now = time.time()
        cutoff = now - 60

        best_key = self.api_keys[0]
        min_requests = float("inf")

        for key in self.api_keys:
            # Clean up old requests
            self.key_requests[key] = [t for t in self.key_requests[key] if t > cutoff]
            count = len(self.key_requests[key])

            if count < min_requests:
                min_requests = count
                best_key = key

        return best_key

    async def _request(
        self,
        endpoint: str,
        selections: list[str],
        id_value: Optional[int] = None,
        use_cache: bool = True,
        cache_ttl: float = 2.0,
    ) -> dict:
        """
        Make a request to Torn API with caching and rate limiting.

        Args:
            endpoint: API endpoint (user, faction, torn, etc.)
            selections: List of selections to request
            id_value: Optional ID for the request
            use_cache: Whether to use cached response
            cache_ttl: Cache time-to-live in seconds
        """
        # Build cache key
        selections_str = ",".join(sorted(selections))
        cache_key = f"{endpoint}:{id_value}:{selections_str}"

        # Check cache first
        if use_cache:
            cached = hospital_cache.get(cache_key)
            if cached is not None:
                return cached

        # Check rate limit
        if not rate_limiter.can_request():
            wait_time = rate_limiter.wait_time()
            if wait_time > 0:
                await asyncio.sleep(wait_time)

        # Get best API key
        api_key = self._get_best_key()

        # Build URL
        id_part = f"/{id_value}" if id_value else ""
        url = f"{TORN_API_BASE}/{endpoint}{id_part}"

        params = {"selections": selections_str, "key": api_key}

        try:
            # Record the request
            rate_limiter.record_request()
            self.key_requests[api_key].append(time.time())

            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            # Update API calls remaining from response headers
            # Torn API uses 'X-RateLimit-Remaining' header
            remaining = response.headers.get("X-RateLimit-Remaining") or response.headers.get(
                "x-ratelimit-remaining"
            )
            if remaining:
                try:
                    self.api_calls_remaining = int(remaining)
                except (ValueError, TypeError):
                    pass

            # Check for Torn API errors
            if "error" in data:
                error = data["error"]
                raise TornAPIError(error.get("code", 0), error.get("error", "Unknown error"))

            # Cache the response
            if use_cache:
                hospital_cache.set(cache_key, data, ttl=cache_ttl)

            return data

        except httpx.HTTPError as e:
            raise TornAPIError(0, f"HTTP Error: {str(e)}")

    async def get_faction_members(self, faction_id: int) -> dict:
        """
        Get all members of a faction with basic info.
        Uses 'basic' selection for member list.
        """
        cache_key = f"faction_members:{faction_id}"
        cached = faction_cache.get(cache_key)
        if cached:
            return cached

        data = await self._request("faction", ["basic"], id_value=faction_id, use_cache=False)

        # Short cache TTL (2s) to detect status changes quickly (hospitalizations, etc.)
        faction_cache.set(cache_key, data, ttl=2.0)
        return data

    async def get_player_status(self, user_id: int) -> dict:
        """Get a single player's status including hospital info."""
        return await self._request(
            "user", ["profile", "timestamp"], id_value=user_id, cache_ttl=2.0
        )

    async def get_multiple_players_status(self, user_ids: list[int]) -> list[PlayerStatus]:
        """
        Get status for multiple players efficiently.
        Uses concurrent requests with rate limiting.
        """
        # Batch requests, respecting rate limits
        results = []
        batch_size = min(10, rate_limiter.requests_remaining())

        for i in range(0, len(user_ids), batch_size):
            batch = user_ids[i : i + batch_size]

            # Concurrent requests for this batch
            tasks = [self.get_player_status(uid) for uid in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for uid, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    # Log error but continue
                    continue

                player_status = self._parse_player_status(uid, result)
                results.append(player_status)

            # Small delay between batches
            if i + batch_size < len(user_ids):
                await asyncio.sleep(0.1)

        return results

    async def get_enemy_faction_hospital_status(self, faction_id: int) -> list[PlayerStatus]:
        """
        Get hospital status for all members of enemy faction.
        This is the main polling function for war tracking.
        """
        now = int(time.time())

        # First get faction members
        faction_data = await self.get_faction_members(faction_id)
        members = faction_data.get("members", {})

        results = []

        for user_id_str, member_data in members.items():
            user_id = int(user_id_str)

            # Parse member data into PlayerStatus
            status = member_data.get("status", {})
            status_state = status.get("state", "")
            hospital_until = status.get("until", 0) or 0

            hospital_remaining = max(0, hospital_until - now) if hospital_until else 0

            # Determine hospital status
            if status_state == "Hospital" and hospital_until and hospital_until > now:
                if hospital_remaining <= 30:
                    hosp_status = HospitalStatus.ABOUT_TO_EXIT
                else:
                    hosp_status = HospitalStatus.IN_HOSPITAL
            else:
                hosp_status = HospitalStatus.OUT

            # Detect traveling
            is_traveling = status_state in ("Traveling", "Abroad")
            travel_destination = ""
            travel_until = None
            if is_traveling:
                travel_destination = status.get("description", "")
                travel_until = status.get("until", 0) if status.get("until") else None

            # Infer online status from last action
            last_action = member_data.get("last_action", {})
            last_action_ts = last_action.get("timestamp", 0)
            last_action_relative = last_action.get("relative", "Unknown")

            online_status = self._infer_online_status(last_action_ts, now)

            # Check for medding (player left hospital early)
            medding = self._detect_medding(user_id, hospital_until)

            # Estimate battle stats from level
            level = member_data.get("level", 0)
            est_stats, est_stats_fmt = estimate_battle_stats(level)

            player = PlayerStatus(
                user_id=user_id,
                name=member_data.get("name", "Unknown"),
                level=level,
                hospital_until=hospital_until
                if hospital_until and hosp_status != HospitalStatus.OUT
                else None,
                hospital_remaining=hospital_remaining if hosp_status != HospitalStatus.OUT else 0,
                hospital_status=hosp_status,
                hospital_reason=status.get("description", "")
                if hosp_status != HospitalStatus.OUT
                else "",
                traveling=is_traveling,
                travel_destination=travel_destination,
                travel_until=travel_until,
                last_action_ts=last_action_ts if last_action_ts else None,
                last_action_relative=last_action_relative,
                estimated_online=online_status,
                medding=medding,
                estimated_stats=est_stats,
                estimated_stats_formatted=est_stats_fmt,
                last_updated=now,
            )

            results.append(player)

        return results

    def _parse_player_status(self, user_id: int, data: dict) -> PlayerStatus:
        """Parse raw API response into PlayerStatus model."""
        now = int(time.time())

        status = data.get("status", {})
        hospital_until = status.get("until", 0) or 0

        hospital_remaining = max(0, hospital_until - now) if hospital_until else 0

        if hospital_until and hospital_until > now:
            if hospital_remaining <= 30:
                hosp_status = HospitalStatus.ABOUT_TO_EXIT
            else:
                hosp_status = HospitalStatus.IN_HOSPITAL
        else:
            hosp_status = HospitalStatus.OUT

        last_action = data.get("last_action", {})
        last_action_ts = last_action.get("timestamp", 0)
        online_status = self._infer_online_status(last_action_ts, now)

        return PlayerStatus(
            user_id=user_id,
            name=data.get("name", "Unknown"),
            level=data.get("level", 0),
            hospital_until=hospital_until if hospital_until else None,
            hospital_remaining=hospital_remaining,
            hospital_status=hosp_status,
            hospital_reason=status.get("description", ""),
            last_action_ts=last_action_ts if last_action_ts else None,
            last_action_relative=last_action.get("relative", "Unknown"),
            estimated_online=online_status,
            last_updated=now,
        )

    def _infer_online_status(self, last_action_ts: int, now: int) -> OnlineStatus:
        """Infer online status from last action timestamp."""
        if not last_action_ts:
            return OnlineStatus.UNKNOWN

        seconds_ago = now - last_action_ts

        if seconds_ago < 120:  # 2 minutes
            return OnlineStatus.ONLINE
        elif seconds_ago < 300:  # 5 minutes
            return OnlineStatus.IDLE
        else:
            return OnlineStatus.OFFLINE

    def _detect_medding(self, user_id: int, current_hospital_until: int) -> bool:
        """
        Detect if player is medding out (left hospital early).
        Compares current hospital_until with previously cached value.
        """
        cache_key = f"prev_hospital:{user_id}"
        prev_hospital = player_cache.get(cache_key)

        # Store current value for next comparison
        player_cache.set(cache_key, current_hospital_until, ttl=60.0)

        if prev_hospital is None:
            return False

        now = int(time.time())

        # If they were in hospital (prev > now) but now they're out (current <= now)
        # and the previous time was significantly in the future, they med'd out
        if prev_hospital > now and (current_hospital_until == 0 or current_hospital_until <= now):
            # They left early
            time_saved = prev_hospital - now
            if time_saved > 60:  # At least 1 minute early
                return True

        return False

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton client instance (initialized in main.py)
_client: Optional[TornClient] = None


def get_client() -> TornClient:
    """Get the global Torn client instance."""
    if _client is None:
        raise RuntimeError("TornClient not initialized. Call init_client first.")
    return _client


def init_client(api_keys: list[str]) -> TornClient:
    """Initialize the global Torn client."""
    global _client
    _client = TornClient(api_keys)
    return _client
