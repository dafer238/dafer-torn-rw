"""
Leaderboard tracking for faction members.
Tracks xanax usage, overdoses, gym gains, and hospital time.
Disk-backed storage via DiskCache to minimize RAM usage.
"""

import time
from typing import Optional
from pydantic import BaseModel
import httpx

from .cache import DiskCache


class UserStats(BaseModel):
    """User statistics snapshot."""

    player_id: int
    player_name: str
    timestamp: int

    # Personal stats
    xanax_taken: int = 0
    overdoses: int = 0


class LeaderboardEntry(BaseModel):
    """Single entry in a leaderboard."""

    player_id: int
    player_name: str
    value: float
    rank: int


class Leaderboards(BaseModel):
    """All leaderboard data."""

    # Xanax leaderboards
    xanax_week: list[LeaderboardEntry] = []
    xanax_month: list[LeaderboardEntry] = []
    xanax_year: list[LeaderboardEntry] = []

    # Overdose leaderboards
    overdoses_week: list[LeaderboardEntry] = []
    overdoses_month: list[LeaderboardEntry] = []
    overdoses_year: list[LeaderboardEntry] = []

    last_updated: int = 0


# Disk-backed storage for stats (minimizes RAM, persists across restarts)
_stats_disk = DiskCache("leaderboard_stats", default_ttl=365 * 24 * 3600)  # 1 year TTL

# Lightweight in-memory set for quick "has player" checks
# This is rebuilt from disk on first leaderboard calculation
_known_player_ids: set[int] = set()

leaderboards_cache: Optional[Leaderboards] = None
leaderboards_last_updated: float = 0
LEADERBOARDS_UPDATE_INTERVAL = 3600  # 1 hour


async def fetch_user_stats(api_key: str, player_id: Optional[int] = None, http_client=None) -> Optional[UserStats]:
    """Fetch user stats from Torn API."""
    try:
        _own_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=10.0)
        try:
            response = await client.get(
                "https://api.torn.com/user/",
                params={
                    "selections": "profile,personalstats,gym",
                    "key": api_key,
                },
            )
            data = response.json()

            if "error" in data:
                print(f"API error: {data['error']}")
                return None

            pid = player_id or data.get("player_id")
            name = data.get("name", "Unknown")

            pstats = data.get("personalstats", {})
            xanax_taken = pstats.get("xantaken", 0)
            overdoses = pstats.get("overdosed", 0)

            return UserStats(
                player_id=pid,
                player_name=name,
                timestamp=int(time.time()),
                xanax_taken=xanax_taken,
                overdoses=overdoses,
            )
        finally:
            if _own_client:
                await client.aclose()

    except Exception as e:
        print(f"Error fetching user stats: {e}")
        return None


async def store_user_stats(stats: UserStats):
    """Store user stats to disk. Also append to history."""
    pid = stats.player_id
    stats_dict = stats.model_dump()

    # Store latest stats
    _stats_disk.set(f"current:{pid}", stats_dict)

    # Append to history
    history = _stats_disk.get(f"history:{pid}") or []
    history.append(stats_dict)
    # Cap history at 1000 entries per player
    if len(history) > 1000:
        history = history[-1000:]
    _stats_disk.set(f"history:{pid}", history)

    # Track player ID
    _known_player_ids.add(pid)
    player_ids = _stats_disk.get("_player_ids") or set()
    player_ids.add(pid)
    _stats_disk.set("_player_ids", player_ids)


def has_player_stats(player_id: int) -> bool:
    """Check if we have stats for a player (fast in-memory check)."""
    if player_id in _known_player_ids:
        return True
    # Fallback to disk check
    if _stats_disk.get(f"current:{player_id}") is not None:
        _known_player_ids.add(player_id)
        return True
    return False


async def load_stats_from_storage() -> dict[int, list[UserStats]]:
    """Load all user stats history from disk."""
    result = {}
    player_ids = _stats_disk.get("_player_ids") or set()
    for pid in player_ids:
        history_dicts = _stats_disk.get(f"history:{pid}")
        if history_dicts:
            try:
                result[pid] = [UserStats(**d) for d in history_dicts]
            except Exception as e:
                print(f"Error loading stats for player {pid}: {e}")
    return result


def calculate_delta(current: int, past: int) -> int:
    """Calculate delta between current and past values."""
    return max(0, current - past)


def calculate_percentage_gain(current: int, past: int) -> float:
    """Calculate percentage gain."""
    if past == 0:
        return 0.0
    return ((current - past) / past) * 100


async def calculate_leaderboards() -> Leaderboards:
    """Calculate all leaderboards from stored stats."""
    now = int(time.time())
    week_ago = now - (7 * 24 * 3600)
    month_ago = now - (30 * 24 * 3600)
    year_ago = now - (365 * 24 * 3600)

    player_ids = _stats_disk.get("_player_ids") or set()

    print(f"Calculating leaderboards... Disk has {len(player_ids)} players")

    # Load all stats from disk
    all_stats = await load_stats_from_storage()

    # If no storage data, use current stats from disk
    if not all_stats:
        print("No history data, using current stats")
        for pid in player_ids:
            current_dict = _stats_disk.get(f"current:{pid}")
            if current_dict:
                try:
                    all_stats[pid] = [UserStats(**current_dict)]
                except Exception:
                    pass
    else:
        print(f"Loaded {len(all_stats)} players from storage")

    if not all_stats:
        print("WARNING: No stats data available at all!")
        return Leaderboards(last_updated=now)

    # Calculate deltas for each player
    player_deltas: dict[int, dict] = {}

    for player_id, history in all_stats.items():
        if not history:
            continue

        # Sort by timestamp (newest first)
        history.sort(key=lambda x: x.timestamp, reverse=True)
        current = history[0]

        # Find snapshots for each time period
        week_snapshot = next((s for s in history if s.timestamp <= week_ago), history[-1])
        month_snapshot = next((s for s in history if s.timestamp <= month_ago), history[-1])
        year_snapshot = next((s for s in history if s.timestamp <= year_ago), history[-1])

        # Calculate deltas, but show lifetime totals if no historical data exists
        # (This happens when we just started tracking or for new users)
        week_delta_xanax = calculate_delta(current.xanax_taken, week_snapshot.xanax_taken)
        month_delta_xanax = calculate_delta(current.xanax_taken, month_snapshot.xanax_taken)
        year_delta_xanax = calculate_delta(current.xanax_taken, year_snapshot.xanax_taken)

        week_delta_od = calculate_delta(current.overdoses, week_snapshot.overdoses)
        month_delta_od = calculate_delta(current.overdoses, month_snapshot.overdoses)
        year_delta_od = calculate_delta(current.overdoses, year_snapshot.overdoses)

        # If we only have one snapshot (no history), show lifetime totals everywhere
        if len(history) == 1:
            # Show lifetime totals in all time periods until we have real history
            week_delta_xanax = current.xanax_taken
            month_delta_xanax = current.xanax_taken
            year_delta_xanax = current.xanax_taken

            week_delta_od = current.overdoses
            month_delta_od = current.overdoses
            year_delta_od = current.overdoses

        player_deltas[player_id] = {
            "name": current.player_name,
            "xanax_week": week_delta_xanax,
            "xanax_month": month_delta_xanax,
            "xanax_year": year_delta_xanax,
            "overdoses_week": week_delta_od,
            "overdoses_month": month_delta_od,
            "overdoses_year": year_delta_od,
        }

    # Create leaderboard entries
    def make_leaderboard(stat_key: str, limit: int = 10) -> list[LeaderboardEntry]:
        entries = [
            LeaderboardEntry(
                player_id=pid,
                player_name=data["name"],
                value=data[stat_key],
                rank=0,
            )
            for pid, data in player_deltas.items()
            if data[stat_key] > 0
        ]
        # Sort descending
        entries.sort(key=lambda x: x.value, reverse=True)
        # Assign ranks
        for i, entry in enumerate(entries[:limit]):
            entry.rank = i + 1
        return entries[:limit]

    return Leaderboards(
        xanax_week=make_leaderboard("xanax_week"),
        xanax_month=make_leaderboard("xanax_month"),
        xanax_year=make_leaderboard("xanax_year"),
        overdoses_week=make_leaderboard("overdoses_week"),
        overdoses_month=make_leaderboard("overdoses_month"),
        overdoses_year=make_leaderboard("overdoses_year"),
        last_updated=now,
    )


async def get_leaderboards(force_refresh: bool = False) -> Leaderboards:
    """Get cached leaderboards or recalculate if stale."""
    global leaderboards_cache, leaderboards_last_updated

    now = time.time()

    print(
        f"Getting leaderboards... (force_refresh={force_refresh}, cache_age={now - leaderboards_last_updated:.0f}s)"
    )

    if (
        force_refresh
        or leaderboards_cache is None
        or (now - leaderboards_last_updated) > LEADERBOARDS_UPDATE_INTERVAL
    ):
        print("Recalculating leaderboards...")
        leaderboards_cache = await calculate_leaderboards()
        leaderboards_last_updated = now
        print(f"Leaderboards calculated with {len(_known_player_ids)} players on disk")
    else:
        print(f"Using cached leaderboards (age: {now - leaderboards_last_updated:.0f}s)")

    return leaderboards_cache


async def update_user_stats_from_api_call(api_key: str, player_id: int, http_client=None):
    """Update user stats when they make an API call (passive collection)."""
    print(f"Collecting stats for player {player_id}...")
    stats = await fetch_user_stats(api_key, player_id, http_client=http_client)
    if stats:
        print(
            f"Stats collected for {stats.player_name}: xanax={stats.xanax_taken}, overdoses={stats.overdoses}"
        )
        await store_user_stats(stats)
    else:
        print(f"Failed to fetch stats for player {player_id}")
