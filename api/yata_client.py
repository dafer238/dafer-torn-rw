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
            "type": str,            # Build type: "Balanced", "Offensive", or "Defensive"
            "skewness": int,        # How skewed the build is (0-100)
            "timestamp": int,       # Timestamp of the estimate
            "score": int,           # YATA score
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
            # YATA battle stats endpoint: GET /api/v1/bs/<target_id>?key=<api_key>
            # We need to make individual requests for each target
            for target_id in target_ids:
                try:
                    response = await client.get(
                        f"{YATA_API_BASE}/bs/{target_id}",
                        params={"key": torn_api_key},
                    )

                    if response.status_code != 200:
                        print(f"YATA API returned status {response.status_code} for target {target_id}")
                        continue

                    data = response.json()

                    # Check for YATA errors
                    if "error" in data:
                        error_msg = data["error"].get("error", "Unknown YATA error")
                        print(f"YATA error for target {target_id}: {error_msg}")
                        continue

                    # Parse response - YATA returns {"<target_id>": {"total": ..., "type": ..., "skewness": ..., "timestamp": ..., "score": ..., "version": ...}}
                    target_id_str = str(target_id)
                    if target_id_str in data:
                        estimate = data[target_id_str]
                        
                        # YATA provides total battle stats estimate
                        total = estimate.get("total", 0)
                        build_type = estimate.get("type", "Unknown")  # String: "Balanced", "Offensive", or "Defensive"
                        skewness = estimate.get("skewness", 0)  # Integer 0-100
                        timestamp = estimate.get("timestamp", 0)
                        score = estimate.get("score", 0)

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
                            "type": build_type,
                            "skewness": skewness,
                            "timestamp": timestamp,
                            "score": score,
                            "total_formatted": formatted,
                        }

                except (ValueError, KeyError) as e:
                    print(f"Error parsing YATA estimate for {target_id}: {e}")
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
