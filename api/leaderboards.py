"""
Leaderboard tracking for faction members.
Tracks xanax usage, overdoses, gym gains, and hospital time.
"""

import os
import time
from typing import Optional
from pydantic import BaseModel
import httpx


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


# In-memory cache for stats and leaderboards
stats_cache: dict[int, UserStats] = {}  # player_id -> latest stats
leaderboards_cache: Optional[Leaderboards] = None
leaderboards_last_updated: float = 0
LEADERBOARDS_UPDATE_INTERVAL = 3600  # 1 hour


def get_kv_client():
    """Get Upstash Redis client if configured."""
    url = os.getenv("KV_REST_API_URL")
    token = os.getenv("KV_REST_API_TOKEN")
    
    if not url or not token:
        return None
    
    return {"url": url, "token": token}


async def fetch_user_stats(api_key: str, player_id: Optional[int] = None) -> Optional[UserStats]:
    """Fetch user stats from Torn API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
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
            
            # Debug: print what we got
            print(f"API response keys: {list(data.keys())}")
            
            # Personal stats
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
            
    except Exception as e:
        print(f"Error fetching user stats: {e}")
        return None


async def store_user_stats(stats: UserStats):
    """Store user stats in Redis and local cache."""
    # Update local cache
    stats_cache[stats.player_id] = stats
    
    # Store in Redis if available
    kv = get_kv_client()
    if not kv:
        return
    
    try:
        # Store latest stats
        key = f"stats:{stats.player_id}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{kv['url']}/set/{key}",
                headers={"Authorization": f"Bearer {kv['token']}"},
                json=stats.model_dump(),
            )
            
            # Also store in historical list with timestamp
            history_key = f"stats_history:{stats.player_id}"
            await client.post(
                f"{kv['url']}/lpush/{history_key}",
                headers={"Authorization": f"Bearer {kv['token']}"},
                json=[stats.model_dump()],
            )
            
            # Keep only last 365 days of history (trim list)
            await client.post(
                f"{kv['url']}/ltrim/{history_key}/0/8760",  # 24 per day * 365 days
                headers={"Authorization": f"Bearer {kv['token']}"},
            )
            
    except Exception as e:
        print(f"Error storing stats in Redis: {e}")


async def load_stats_from_redis() -> dict[int, list[UserStats]]:
    """Load all user stats history from Redis."""
    kv = get_kv_client()
    if not kv:
        return {}
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get all stats keys
            response = await client.get(
                f"{kv['url']}/keys/stats:*",
                headers={"Authorization": f"Bearer {kv['token']}"},
            )
            
            if response.status_code != 200:
                return {}
            
            keys_data = response.json()
            keys = keys_data.get("result", [])
            
            all_stats: dict[int, list[UserStats]] = {}
            
            # Load history for each player
            for key in keys:
                if not key.startswith("stats:"):
                    continue
                    
                player_id = int(key.split(":")[1])
                history_key = f"stats_history:{player_id}"
                
                history_response = await client.get(
                    f"{kv['url']}/lrange/{history_key}/0/-1",
                    headers={"Authorization": f"Bearer {kv['token']}"},
                )
                
                if history_response.status_code == 200:
                    history_data = history_response.json()
                    history = history_data.get("result", [])
                    all_stats[player_id] = [UserStats(**item) for item in history if isinstance(item, dict)]
            
            return all_stats
            
    except Exception as e:
        print(f"Error loading stats from Redis: {e}")
        return {}


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
    
    print(f"Calculating leaderboards... Local cache has {len(stats_cache)} players")
    
    # Load all stats from Redis
    all_stats = await load_stats_from_redis()
    
    # If no Redis data, use local cache
    if not all_stats:
        print("No Redis data, using local cache")
        all_stats = {pid: [stats] for pid, stats in stats_cache.items()}
    else:
        print(f"Loaded {len(all_stats)} players from Redis")
    
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
    
    print(f"Getting leaderboards... (force_refresh={force_refresh}, cache_age={now - leaderboards_last_updated:.0f}s)")
    
    if (
        force_refresh
        or leaderboards_cache is None
        or (now - leaderboards_last_updated) > LEADERBOARDS_UPDATE_INTERVAL
    ):
        print("Recalculating leaderboards...")
        leaderboards_cache = await calculate_leaderboards()
        leaderboards_last_updated = now
        print(f"Leaderboards calculated with {len(stats_cache)} players in cache")
    else:
        print(f"Using cached leaderboards (age: {now - leaderboards_last_updated:.0f}s)")
    
    return leaderboards_cache


async def update_user_stats_from_api_call(api_key: str, player_id: int):
    """Update user stats when they make an API call (passive collection)."""
    print(f"Collecting stats for player {player_id}...")
    stats = await fetch_user_stats(api_key, player_id)
    if stats:
        print(f"Stats collected for {stats.player_name}: xanax={stats.xanax_taken}, overdoses={stats.overdoses}")
        await store_user_stats(stats)
    else:
        print(f"Failed to fetch stats for player {player_id}")
