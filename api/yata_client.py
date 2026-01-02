"""
YATA API Client - Battle Stats Estimation

Integrates with YATA (https://yata.yt/) to get battle stats estimates for target players.
Uses YATA's machine learning models to provide more accurate estimates than level-based calculations.

YATA requires a Torn API key to fetch target estimates.
"""

from typing import Optional, Dict
import httpx


YATA_API_BASE = "https://yata.yt/api/v1"


class YATAError(Exception):
    """Exception raised for YATA API errors."""

    def __init__(self, message: str, code: Optional[int] = None):
        self.message = message
        self.code = code
        super().__init__(self.message)


async def fetch_battle_stats_estimates(
    target_ids: list[int], torn_api_key: str, timeout: float = 30.0
) -> Dict[int, Dict]:
    """
    Fetch battle stats estimates from YATA for multiple targets.

    Args:
        target_ids: List of player IDs to get estimates for
        torn_api_key: Valid Torn API key (YATA uses it to fetch player data)
        timeout: Request timeout in seconds

    Returns:
        Dict mapping player_id -> estimate data:
        {
            "total": int,           # Total battle stats estimate
            "strength": int,        # Strength estimate
            "defense": int,         # Defense estimate
            "speed": int,           # Speed estimate
            "dexterity": int,       # Dexterity estimate
            "total_formatted": str, # Human readable total (e.g., "150M")
        }

    Raises:
        YATAError: If YATA API returns an error
        httpx.HTTPError: If request fails
    """
    if not target_ids:
        return {}

    results = {}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # YATA targets estimate endpoint
            # POST with target IDs
            response = await client.post(
                f"{YATA_API_BASE}/targets/estimate/",
                params={"key": torn_api_key},
                json={"targets": target_ids},
            )

            if response.status_code != 200:
                raise YATAError(
                    f"YATA API returned status {response.status_code}", code=response.status_code
                )

            data = response.json()

            # Check for YATA errors
            if "error" in data:
                error_msg = data["error"].get("error", "Unknown YATA error")
                error_code = data["error"].get("code")
                raise YATAError(error_msg, code=error_code)

            # Parse response - YATA returns dict of target_id -> stats
            # Format may be: {"targets": {id: {...}, ...}}
            targets_data = data.get("targets", {})

            for target_id_str, estimate in targets_data.items():
                try:
                    target_id = int(target_id_str)

                    # YATA provides total battle stats estimate
                    total = estimate.get("total", 0)

                    # Individual stats (if available)
                    strength = estimate.get("strength", 0)
                    defense = estimate.get("defense", 0)
                    speed = estimate.get("speed", 0)
                    dexterity = estimate.get("dexterity", 0)

                    # Format for display
                    if total >= 1_000_000_000:
                        formatted = f"{total / 1_000_000_000:.1f}B"
                    elif total >= 1_000_000:
                        formatted = f"{total / 1_000_000:.0f}M"
                    elif total >= 1_000:
                        formatted = f"{total / 1_000:.0f}K"
                    else:
                        formatted = str(total) if total else "?"

                    results[target_id] = {
                        "total": total,
                        "strength": strength,
                        "defense": defense,
                        "speed": speed,
                        "dexterity": dexterity,
                        "total_formatted": formatted,
                    }

                except (ValueError, KeyError) as e:
                    print(f"Error parsing YATA estimate for {target_id_str}: {e}")
                    continue

            return results

    except httpx.HTTPError as e:
        print(f"HTTP error fetching YATA estimates: {e}")
        raise


async def fetch_single_battle_stats_estimate(
    target_id: int, torn_api_key: str, timeout: float = 30.0
) -> Optional[Dict]:
    """
    Fetch battle stats estimate from YATA for a single target.

    Args:
        target_id: Player ID to get estimate for
        torn_api_key: Valid Torn API key
        timeout: Request timeout in seconds

    Returns:
        Estimate data dict or None if error
    """
    try:
        results = await fetch_battle_stats_estimates([target_id], torn_api_key, timeout)
        return results.get(target_id)
    except (YATAError, httpx.HTTPError) as e:
        print(f"Error fetching YATA estimate for {target_id}: {e}")
        return None


def format_battle_stats(total: int) -> str:
    """
    Format battle stats number for display.

    Args:
        total: Total battle stats

    Returns:
        Formatted string (e.g., "150M", "2.5B")
    """
    if total >= 1_000_000_000:
        return f"{total / 1_000_000_000:.1f}B"
    elif total >= 1_000_000:
        return f"{total / 1_000_000:.0f}M"
    elif total >= 1_000:
        return f"{total / 1_000:.0f}K"
    else:
        return str(total) if total else "?"
