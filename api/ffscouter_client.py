"""
FF Scouter API Client - Battle Stats Estimation

Integrates with FFScouter (https://ffscouter.com/) to get battle stats estimates
and fair fight scores for target players. Uses crowd-sourced fair fight data
to provide accurate stat estimates.

FFScouter requires a registered API key (Torn API key registered with FFScouter).
"""

from typing import Optional, Dict
import httpx


FFSCOUTER_API_BASE = "https://ffscouter.com/api/v1"

# Max targets per request (API limit is 205)
MAX_TARGETS_PER_REQUEST = 205


class FFScouterError(Exception):
    """Exception raised for FFScouter API errors."""

    def __init__(self, message: str, code: Optional[int] = None):
        self.message = message
        self.code = code
        super().__init__(self.message)


async def fetch_ffscouter_estimates(
    target_ids: list[int],
    ffscouter_api_key: str,
    timeout: float = 30.0,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[int, Dict]:
    """
    Fetch battle stats estimates from FFScouter for multiple targets.
    Supports up to 205 targets in a single request (batched efficiently).

    Args:
        target_ids: List of player IDs to get estimates for
        ffscouter_api_key: FFScouter API key (Torn API key registered with FFScouter)
        timeout: Request timeout in seconds
        http_client: Shared httpx.AsyncClient (if None, creates its own)

    Returns:
        Dict mapping player_id -> estimate data:
        {
            "total": int,               # Total battle stats estimate
            "total_formatted": str,      # Human readable (e.g., "2.99b")
            "fair_fight": float | None,  # Fair fight score (e.g., 5.39)
            "timestamp": int | None,     # When estimate was last updated
            "source": "ffscouter",       # Source identifier
        }

    Raises:
        FFScouterError: If FFScouter API returns an error
        httpx.HTTPError: If request fails
    """
    if not target_ids:
        return {}

    results = {}
    _own_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout)

    try:
        # Batch targets into groups of MAX_TARGETS_PER_REQUEST
        for i in range(0, len(target_ids), MAX_TARGETS_PER_REQUEST):
            batch = target_ids[i : i + MAX_TARGETS_PER_REQUEST]
            targets_str = ",".join(str(tid) for tid in batch)

            try:
                response = await client.get(
                    f"{FFSCOUTER_API_BASE}/get-stats",
                    params={
                        "key": ffscouter_api_key,
                        "targets": targets_str,
                    },
                )

                if response.status_code != 200:
                    data = response.json()
                    if "error" in data:
                        error_msg = data.get("error", "Unknown FFScouter error")
                        error_code = data.get("code")
                        print(f"FFScouter API error (code {error_code}): {error_msg}")
                        raise FFScouterError(error_msg, code=error_code)
                    print(f"FFScouter API returned status {response.status_code}")
                    continue

                data = response.json()

                # Response is a list of player objects
                if isinstance(data, list):
                    for entry in data:
                        player_id = entry.get("player_id")
                        if not player_id:
                            continue

                        bs_estimate = entry.get("bs_estimate")
                        fair_fight = entry.get("fair_fight")
                        bs_human = entry.get("bs_estimate_human")
                        last_updated = entry.get("last_updated")

                        # Skip if no estimate available
                        if bs_estimate is None:
                            continue

                        results[int(player_id)] = {
                            "total": int(bs_estimate) if bs_estimate else 0,
                            "total_formatted": bs_human or format_battle_stats(int(bs_estimate) if bs_estimate else 0),
                            "fair_fight": float(fair_fight) if fair_fight is not None else None,
                            "timestamp": last_updated,
                            "source": "ffscouter",
                        }
                elif isinstance(data, dict) and "error" in data:
                    error_msg = data.get("error", "Unknown FFScouter error")
                    error_code = data.get("code")
                    print(f"FFScouter error: {error_msg}")
                    raise FFScouterError(error_msg, code=error_code)

            except (ValueError, KeyError) as e:
                print(f"Error parsing FFScouter response: {e}")
                continue

        return results

    except httpx.HTTPError as e:
        print(f"HTTP error fetching FFScouter estimates: {e}")
        raise
    finally:
        if _own_client:
            await client.aclose()


async def check_ffscouter_key(
    api_key: str,
    timeout: float = 10.0,
    http_client: Optional[httpx.AsyncClient] = None,
) -> bool:
    """
    Check if an API key is registered with FFScouter.

    Args:
        api_key: FFScouter API key to check
        timeout: Request timeout in seconds
        http_client: Shared httpx.AsyncClient

    Returns:
        True if the key is registered and valid
    """
    _own_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout)

    try:
        response = await client.get(
            f"{FFSCOUTER_API_BASE}/check-key",
            params={"key": api_key},
        )

        if response.status_code != 200:
            return False

        data = response.json()
        return data.get("is_registered", False)

    except Exception as e:
        print(f"Error checking FFScouter key: {e}")
        return False
    finally:
        if _own_client:
            await client.aclose()


def format_battle_stats(total: int) -> str:
    """
    Format battle stats number for display.

    Args:
        total: Total battle stats

    Returns:
        Formatted string (e.g., "150M", "2.5B")
    """
    if total >= 1_000_000_000:
        return f"{total / 1_000_000_000:.2f}b"
    elif total >= 1_000_000:
        return f"{total / 1_000_000:.1f}m"
    elif total >= 1_000:
        return f"{total / 1_000:.0f}k"
    else:
        return str(total) if total else "?"
