"""
Torn Ranked War Tracker - Main FastAPI Application

Provides REST API endpoints for:
- War status and target tracking
- Hit claiming/unclaiming
- Health/status checks
- TornStats integration for battle stats
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api import (
    PlayerStatus,
    WarStatus,
    ClaimRequest,
    ClaimResponse,
    HospitalStatus,
    init_claim_manager,
    get_claim_manager,
    rate_limiter,
    TornAPIError,
    hospital_cache,
    TornClient,
    fetch_battle_stats_estimates,
    YATAError,
    yata_cache,
)
from api.leaderboards import (
    get_leaderboards,
    update_user_stats_from_api_call,
    Leaderboards,
)
from api.faction_overview import (
    store_faction_member_profile,
    get_all_faction_profiles,
    FactionMemberProfile,
)


# Load environment variables
load_dotenv()


def get_api_keys() -> list[str]:
    """Get API keys from environment."""
    keys = []

    # Primary key
    primary_key = os.getenv("TORN_API_KEY")
    if primary_key and primary_key != "your_api_key_here":
        keys.append(primary_key)

    # Additional keys (comma-separated)
    additional = os.getenv("TORN_API_KEYS", "")
    if additional:
        keys.extend([k.strip() for k in additional.split(",") if k.strip()])

    return keys


def get_enemy_faction_ids() -> list[int]:
    """Get enemy faction IDs from environment."""
    ids_str = os.getenv("ENEMY_FACTION_IDS", "")
    if not ids_str:
        return []

    try:
        return [int(fid.strip()) for fid in ids_str.split(",") if fid.strip()]
    except ValueError:
        return []


def get_max_claims_per_user() -> int:
    """Get maximum claims per user from environment."""
    try:
        return int(os.getenv("MAX_CLAIMS_PER_USER", "3"))
    except ValueError:
        return 3


def get_claim_expiry() -> int:
    """Get claim expiry time from environment."""
    try:
        return int(os.getenv("CLAIM_EXPIRY", "120"))
    except ValueError:
        return 120


def get_allowed_faction_id() -> int | None:
    """Get the faction ID that is allowed to use this tracker."""
    faction_id = os.getenv("FACTION_ID")
    if not faction_id:
        return None
    try:
        return int(faction_id)
    except ValueError:
        return None


def get_leadership_whitelist() -> list[int]:
    """Get list of player IDs allowed to access faction overview."""
    whitelist_str = os.getenv("LEADERSHIP_WHITELIST", "")
    if not whitelist_str:
        return []
    try:
        return [int(pid.strip()) for pid in whitelist_str.split(",") if pid.strip()]
    except ValueError:
        return []


def get_drug_cd_max() -> int:
    """Get max drug cooldown in minutes from environment."""
    try:
        return int(os.getenv("DRUG_CD_MAX", "480"))  # Default 8 hours
    except ValueError:
        return 480


def get_med_cd_max() -> int:
    """Get max medical cooldown in minutes from environment."""
    try:
        return int(os.getenv("MED_CD_MAX", "360"))  # Default 6 hours
    except ValueError:
        return 360


def get_booster_cd_max() -> int:
    """Get max booster cooldown in minutes from environment."""
    try:
        return int(os.getenv("BOOSTER_CD_MAX", "2880"))  # Default 48 hours
    except ValueError:
        return 2880


async def validate_faction_membership(
    api_key: str, allowed_faction_id: int
) -> tuple[bool, str, int | None]:
    """Validate that the API key belongs to a member of the allowed faction.

    Returns:
        (is_valid, error_message, player_id)
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.torn.com/user/",
                params={
                    "selections": "profile",
                    "key": api_key,
                },
            )
            data = response.json()

            if "error" in data:
                error = data["error"]
                if error.get("code") == 2:
                    return False, "Invalid API key", None
                return False, error.get("error", "API error"), None

            player_id = data.get("player_id")
            faction_data = data.get("faction", {})
            user_faction_id = faction_data.get("faction_id")

            if user_faction_id != allowed_faction_id:
                return (
                    False,
                    f"Access denied: You must be a member of faction {allowed_faction_id} to use this tracker",
                    player_id,
                )

            return True, "", player_id

    except httpx.HTTPError as e:
        return False, f"Connection error: {str(e)}", None


async def check_faction_access(x_api_key: str = Header(None, alias="X-API-Key")) -> tuple[str, int]:
    """Dependency to validate faction membership. Returns (api_key, player_id)."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required. Set X-API-Key header.")

    allowed_faction_id = get_allowed_faction_id()

    # If no faction restriction is configured, allow all
    if allowed_faction_id is None:
        # Still need to get player_id for claims - do a quick validation
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.torn.com/user/",
                    params={"selections": "profile", "key": x_api_key},
                )
                data = response.json()
                if "error" in data:
                    raise HTTPException(status_code=401, detail="Invalid API key")
                player_id = data.get("player_id", 0)
                return x_api_key, player_id
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Failed to validate API key")

    # Check cache first
    now = time.time()
    for player_id, (cached_faction_id, timestamp) in list(faction_validation_cache.items()):
        if (now - timestamp) < FACTION_CACHE_TTL and cached_faction_id == allowed_faction_id:
            # Found in cache - but need to verify this is the right API key
            # We'll do a quick validation
            pass

    # Validate faction membership
    is_valid, error_msg, player_id = await validate_faction_membership(
        x_api_key, allowed_faction_id
    )

    if not is_valid:
        raise HTTPException(status_code=403, detail=error_msg)

    # Cache the validation
    if player_id:
        faction_validation_cache[player_id] = (allowed_faction_id, now)

    # Passively collect user stats for leaderboards (throttled to once per hour per user)
    if player_id:
        last_update = stats_collection_cache.get(player_id, 0)
        if (now - last_update) >= STATS_COLLECTION_INTERVAL:
            stats_collection_cache[player_id] = now
            asyncio.create_task(update_user_stats_from_api_call(x_api_key, player_id))

    return x_api_key, player_id or 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    # Startup
    # Note: API keys are now provided per-request by users
    print("Torn War Tracker starting - users will provide their own API keys")

    # Initialize claim manager with config
    max_claims = get_max_claims_per_user()
    claim_expiry = get_claim_expiry()
    init_claim_manager(default_expiry=claim_expiry, max_claims_per_user=max_claims)
    print(f"Claim manager: max {max_claims} claims/user, {claim_expiry}s expiry")

    # Check faction restriction
    allowed_faction = get_allowed_faction_id()
    if allowed_faction:
        print(
            f"Faction restriction enabled: Only faction {allowed_faction} members can use this tracker"
        )
    else:
        print("No faction restriction - all users with valid API keys can access")

    yield

    # Shutdown - nothing to clean up since clients are per-request


# Simple cache for claims to reduce Redis queries
claims_cache = {"data": None, "timestamp": 0}
CLAIMS_CACHE_TTL = 2  # Cache claims for 2 seconds

# Cache for faction validation (player_id -> faction_id mapping)
faction_validation_cache: dict[int, tuple[int, float]] = {}  # player_id -> (faction_id, timestamp)
FACTION_CACHE_TTL = 300  # Cache faction membership for 5 minutes

# Cache for stats collection throttling (player_id -> last_update_timestamp)
stats_collection_cache: dict[int, float] = {}
STATS_COLLECTION_INTERVAL = 3600  # Only collect stats once per hour per user

# Cache for faction overview (reduces Upstash reads)
faction_overview_cache = {"data": None, "timestamp": 0}
FACTION_OVERVIEW_CACHE_TTL = 30  # Cache faction overview for 30 seconds

# API key pool for distributing YATA requests
api_key_pool: list[str] = []
api_key_pool_lock = asyncio.Lock()
API_KEY_POOL_MAX_SIZE = 20
API_KEY_POOL_TTL = 3600
api_key_last_seen: dict[str, float] = {}


async def add_api_key_to_pool(api_key: str):
    """
    Add an API key to the pool for distributing YATA requests.
    Keys are rotated to spread load across all active users.
    """
    async with api_key_pool_lock:
        now = time.time()

        # Clean up expired keys
        expired_keys = [
            k for k, last_seen in api_key_last_seen.items() if (now - last_seen) > API_KEY_POOL_TTL
        ]
        for k in expired_keys:
            if k in api_key_pool:
                api_key_pool.remove(k)
            del api_key_last_seen[k]

        # Add or update key
        api_key_last_seen[api_key] = now
        if api_key not in api_key_pool:
            api_key_pool.append(api_key)
            # Keep pool size manageable
            if len(api_key_pool) > API_KEY_POOL_MAX_SIZE:
                oldest_key = min(api_key_last_seen.keys(), key=lambda k: api_key_last_seen[k])
                api_key_pool.remove(oldest_key)
                del api_key_last_seen[oldest_key]


async def get_api_keys_for_yata(count: int) -> list[str]:
    """
    Get API keys from the pool for making YATA requests.
    Returns up to 'count' keys, rotating through the pool.
    """
    async with api_key_pool_lock:
        if not api_key_pool:
            return []

        # Rotate through pool to distribute load
        # Return keys in round-robin fashion
        result = []
        for i in range(min(count, len(api_key_pool))):
            idx = i % len(api_key_pool)
            result.append(api_key_pool[idx])

        return result


async def get_yata_estimate_from_redis(target_id: int) -> Optional[dict]:
    """Get YATA estimate from Redis/KV."""
    kv_url = os.getenv("KV_REST_API_URL")
    kv_token = os.getenv("KV_REST_API_TOKEN")

    if not kv_url or not kv_token:
        return None

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{kv_url}/get/yata_{target_id}", headers={"Authorization": f"Bearer {kv_token}"}
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("result")
    except Exception as e:
        print(f"Error reading YATA from Redis for {target_id}: {e}")

    return None


async def save_yata_estimate_to_redis(target_id: int, estimate: dict):
    """Save YATA estimate to Redis/KV without expiration."""
    kv_url = os.getenv("KV_REST_API_URL")
    kv_token = os.getenv("KV_REST_API_TOKEN")

    if not kv_url or not kv_token:
        return

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Store without expiration (remove /ex/... part)
            await client.post(
                f"{kv_url}/set/yata_{target_id}",
                headers={"Authorization": f"Bearer {kv_token}"},
                json=estimate,
            )
    except Exception as e:
        print(f"Error saving YATA to Redis for {target_id}: {e}")


async def enrich_targets_with_yata_estimates(targets: list[PlayerStatus], api_key: str):
    """
    Enrich target players with YATA battle stats estimates.
    Uses Redis for shared persistence across instances.
    Runs in background to avoid blocking page load.
    """
    if not targets:
        return

    # Add this key to the pool
    await add_api_key_to_pool(api_key)

    # Check cache (both in-memory and Redis)
    targets_to_fetch = []
    for target in targets:
        # Check in-memory cache first (fastest)
        cache_key = f"yata_estimate_{target.user_id}"
        cached = yata_cache.get(cache_key)

        if cached:
            # Use in-memory cached estimate
            target.yata_estimated_stats = cached.get("total")
            target.yata_estimated_stats_formatted = cached.get("total_formatted")
            target.yata_build_type = cached.get("type")
            target.yata_skewness = cached.get("skewness")
            target.yata_timestamp = cached.get("timestamp")
            target.yata_score = cached.get("score")
        else:
            # Check Redis (shared across instances)
            redis_data = await get_yata_estimate_from_redis(target.user_id)
            if redis_data:
                target.yata_estimated_stats = redis_data.get("total")
                target.yata_estimated_stats_formatted = redis_data.get("total_formatted")
                target.yata_build_type = redis_data.get("type")
                target.yata_skewness = redis_data.get("skewness")
                target.yata_timestamp = redis_data.get("timestamp")
                target.yata_score = redis_data.get("score")
                # Also cache in memory
                yata_cache.set(cache_key, redis_data, ttl=604800)
            else:
                targets_to_fetch.append(target)

    # Fetch missing estimates in background (don't block)
    if targets_to_fetch:
        asyncio.create_task(fetch_and_cache_yata_estimates(targets_to_fetch, api_key))


async def fetch_and_cache_yata_estimates(targets: list[PlayerStatus], api_key: str):
    """Background task to fetch YATA estimates."""
    try:
        available_keys = await get_api_keys_for_yata(len(targets))
        if not available_keys:
            available_keys = [api_key]

        for i, target in enumerate(targets):
            key_to_use = available_keys[i % len(available_keys)]

            try:
                result = await fetch_battle_stats_estimates([target.user_id], key_to_use)
                if target.user_id in result:
                    estimate = result[target.user_id]

                    # Save to Redis (no expiration)
                    await save_yata_estimate_to_redis(target.user_id, estimate)

                    # Cache in memory
                    cache_key = f"yata_estimate_{target.user_id}"
                    yata_cache.set(cache_key, estimate, ttl=604800)

            except Exception as e:
                print(f"Error fetching YATA for {target.user_id}: {e}")
                continue

    except Exception as e:
        print(f"Background YATA fetch error: {e}")


# Create FastAPI app
app = FastAPI(
    title="Torn Ranked War Tracker",
    description="Real-time situational awareness for Torn ranked wars",
    version="1.0.0",
    lifespan=lifespan,
)


# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": int(time.time()),
        "rate_limit_remaining": rate_limiter.requests_remaining(),
        "cache_stats": hospital_cache.stats(),
    }


@app.get("/api/config")
async def get_config():
    """Get public configuration values."""
    return {
        "enemy_faction_ids": get_enemy_faction_ids(),
        "max_claims_per_user": get_max_claims_per_user(),
        "claim_expiry": get_claim_expiry(),
    }


@app.get("/api/status", response_model=WarStatus)
async def get_war_status(
    force_refresh: bool = Query(False, description="Force refresh from Torn API"),
    auth: tuple[str, int] = Depends(check_faction_access),
):
    """
    Get current war status with all target information.
    This is the main endpoint polled by the frontend.
    Each user must provide their own API key via X-API-Key header.
    """
    x_api_key, player_id = auth
    now = int(time.time())
    claim_mgr = get_claim_manager()

    # Create a temporary client with user's API key
    client = TornClient([x_api_key])

    try:
        # Get enemy faction IDs
        enemy_faction_ids = get_enemy_faction_ids()
        if not enemy_faction_ids:
            return WarStatus(
                targets=[],
                last_updated=now,
                cache_age_seconds=0,
                next_refresh_in=2.0,
                api_calls_remaining=100,  # User's own limit
                max_claims_per_user=claim_mgr.max_claims_per_user,
            )

        # Fetch targets from all enemy factions
        all_targets: list[PlayerStatus] = []

        for faction_id in enemy_faction_ids:
            try:
                targets = await client.get_enemy_faction_hospital_status(faction_id)
                all_targets.extend(targets)
            except TornAPIError as e:
                if e.code == 2:  # Invalid API key
                    raise HTTPException(status_code=401, detail="Invalid API key")
                print(f"Error fetching faction {faction_id}: {e}")
                continue

        # Update hospital states and reset claims for those who went back to hospital
        claim_mgr.update_hospital_states(all_targets)

        # Fetch YATA battle stats estimates (cached for 7 days)
        # Only fetch if we have targets
        if all_targets:
            await enrich_targets_with_yata_estimates(all_targets, x_api_key)

        # Get claims with caching to reduce Redis queries
        now_ms = time.time()
        if claims_cache["data"] is None or (now_ms - claims_cache["timestamp"]) > CLAIMS_CACHE_TTL:
            claims = claim_mgr.get_all_claims()
            claims_cache["data"] = claims
            claims_cache["timestamp"] = now_ms
        else:
            claims = claims_cache["data"]

        # Enrich targets with claim info
        claims_by_target = {c.target_id: c for c in claims}

        for target in all_targets:
            claim = claims_by_target.get(target.user_id)
            if claim:
                target.claimed_by = claim.claimed_by
                target.claimed_by_id = claim.claimed_by_id
                target.claimed_at = claim.claimed_at
                target.claim_expires = claim.expires_at

        # Sort targets: about to exit first, then by hospital remaining time
        all_targets.sort(
            key=lambda t: (
                0
                if t.hospital_status == HospitalStatus.ABOUT_TO_EXIT
                else 1
                if t.hospital_status == HospitalStatus.IN_HOSPITAL
                else 2,
                t.hospital_remaining if t.hospital_remaining else float("inf"),
                -1 if t.estimated_online == "online" else 0,
            )
        )

        # Build response
        in_hospital = sum(1 for t in all_targets if t.hospital_status != HospitalStatus.OUT)
        claimed = sum(1 for t in all_targets if t.claimed_by)
        traveling = sum(1 for t in all_targets if t.traveling)

        # Get actual API calls remaining from client
        api_calls_left = (
            int(client.api_calls_remaining)
            if hasattr(client, "api_calls_remaining") and client.api_calls_remaining is not None
            else 100
        )

        response = WarStatus(
            targets=all_targets,
            active_claims=claims,
            total_targets=len(all_targets),
            in_hospital=in_hospital,
            out_of_hospital=len(all_targets) - in_hospital,
            claimed=claimed,
            traveling=traveling,
            max_claims_per_user=claim_mgr.max_claims_per_user,
            last_updated=now,
            cache_age_seconds=0,
            next_refresh_in=2.0,
            api_calls_remaining=api_calls_left,
        )

        return response

    finally:
        # Clean up the temporary client
        await client.close()


@app.get("/api/me")
async def get_my_status(auth: tuple[str, int] = Depends(check_faction_access)):
    """
    Get current user's status including health, cooldowns, energy, chain, etc.
    Requires user's API key.
    """
    x_api_key, player_id = auth

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Fetch user data and faction chain in parallel
            user_task = client.get(
                "https://api.torn.com/user/",
                params={
                    "selections": "profile,bars,cooldowns,travel",
                    "key": x_api_key,
                },
            )
            faction_task = client.get(
                "https://api.torn.com/faction/",
                params={
                    "selections": "chain",
                    "key": x_api_key,
                },
            )

            user_response, faction_response = await asyncio.gather(
                user_task, faction_task, return_exceptions=True
            )

            # Process user data
            if isinstance(user_response, Exception):
                raise HTTPException(status_code=502, detail="Failed to fetch user data")

            data = user_response.json()

            if "error" in data:
                error = data["error"]
                raise HTTPException(
                    status_code=401 if error.get("code") == 2 else 400,
                    detail=error.get("error", "API error"),
                )

            # Parse the response
            now = int(time.time())

            # Health
            life = data.get("life", {})
            health_current = life.get("current", 0)
            health_max = life.get("maximum", 100)

            # Energy
            energy = data.get("energy", {})
            energy_current = energy.get("current", 0)
            energy_max = energy.get("maximum", 100)

            # Nerve
            nerve = data.get("nerve", {})
            nerve_current = nerve.get("current", 0)
            nerve_max = nerve.get("maximum", 50)

            # Happy
            happy = data.get("happy", {})
            happy_current = happy.get("current", 0)
            happy_max = happy.get("maximum", 1000)

            # Cooldowns
            cooldowns = data.get("cooldowns", {})
            drug_cd = cooldowns.get("drug", 0)
            medical_cd = cooldowns.get("medical", 0)
            booster_cd = cooldowns.get("booster", 0)

            # Travel status
            travel = data.get("travel", {})
            is_traveling = travel.get("time_left", 0) > 0
            travel_destination = travel.get("destination", "")
            travel_time_left = travel.get("time_left", 0)

            # Status (hospital, jail, etc.)
            status = data.get("status", {})
            status_state = status.get("state", "Okay")
            status_until = status.get("until", 0)

            # Chain data
            chain_data = {"current": 0, "timeout": 0, "max": 0, "modifier": 1}
            if not isinstance(faction_response, Exception):
                faction_data = faction_response.json()
                if "chain" in faction_data:
                    chain = faction_data["chain"]
                    chain_data = {
                        "current": chain.get("current", 0),
                        "timeout": chain.get("timeout", 0),
                        "max": chain.get("max", 0),
                        "modifier": chain.get("modifier", 1),
                        "cooldown": chain.get("cooldown", 0),
                    }

            # Store faction member profile for leadership view (async, non-blocking)
            asyncio.create_task(store_faction_member_profile(player_id, data))

            return {
                "name": data.get("name", "Unknown"),
                "player_id": data.get("player_id", 0),
                "level": data.get("level", 0),
                "health": {
                    "current": health_current,
                    "max": health_max,
                    "percent": round(health_current / health_max * 100) if health_max > 0 else 0,
                },
                "energy": {
                    "current": energy_current,
                    "max": energy_max,
                    "percent": round(energy_current / energy_max * 100) if energy_max > 0 else 0,
                },
                "nerve": {
                    "current": nerve_current,
                    "max": nerve_max,
                    "percent": round(nerve_current / nerve_max * 100) if nerve_max > 0 else 0,
                },
                "happy": {
                    "current": happy_current,
                    "max": happy_max,
                    "percent": round(happy_current / happy_max * 100) if happy_max > 0 else 0,
                },
                "cooldowns": {
                    "drug": drug_cd,
                    "medical": medical_cd,
                    "booster": booster_cd,
                },
                "travel": {
                    "traveling": is_traveling,
                    "destination": travel_destination,
                    "time_left": travel_time_left,
                },
                "status": {
                    "state": status_state,
                    "until": status_until,
                },
                "chain": chain_data,
                "timestamp": now,
            }

    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Connection error: {str(e)}")


@app.get("/api/faction-overview", response_model=List[FactionMemberProfile])
async def get_faction_overview(auth: tuple[str, int] = Depends(check_faction_access)):
    """
    Get overview of all faction members who have used the tracker.
    Only accessible to whitelisted leadership IDs.
    Cached for 30 seconds to reduce Upstash operations.
    """
    x_api_key, player_id = auth

    # Check if player is in leadership whitelist
    whitelist = get_leadership_whitelist()
    if not whitelist:
        raise HTTPException(
            status_code=403,
            detail="Faction overview is disabled (no leadership whitelist configured)",
        )

    if player_id not in whitelist:
        raise HTTPException(
            status_code=403, detail="Access denied: You are not authorized to view faction overview"
        )

    # Check cache first to reduce Upstash operations
    now_ms = time.time()
    if (
        faction_overview_cache["data"] is not None
        and (now_ms - faction_overview_cache["timestamp"]) < FACTION_OVERVIEW_CACHE_TTL
    ):
        return faction_overview_cache["data"]

    # Get all stored faction profiles from Upstash
    profiles = await get_all_faction_profiles()

    # Update cache
    faction_overview_cache["data"] = profiles
    faction_overview_cache["timestamp"] = now_ms

    return profiles


@app.get("/api/faction-config")
async def get_faction_config(auth: tuple[str, int] = Depends(check_faction_access)):
    """
    Get faction overview configuration values (CD max times in seconds).
    Only accessible to whitelisted leadership IDs.
    """
    x_api_key, player_id = auth

    # Check if player is in leadership whitelist
    whitelist = get_leadership_whitelist()
    if not whitelist:
        raise HTTPException(
            status_code=403,
            detail="Faction overview is disabled (no leadership whitelist configured)",
        )

    if player_id not in whitelist:
        raise HTTPException(
            status_code=403, detail="Access denied: You are not authorized to view faction config"
        )

    return {
        "drug_cd_max": get_drug_cd_max() * 60,  # Convert minutes to seconds
        "med_cd_max": get_med_cd_max() * 60,
        "booster_cd_max": get_booster_cd_max() * 60,
    }


@app.post("/api/claim", response_model=ClaimResponse)
async def claim_target(
    request: ClaimRequest, auth: tuple[str, int] = Depends(check_faction_access)
):
    """
    Claim a target for attacking.
    Prevents other faction members from attacking the same person.
    """
    # Invalidate claims cache so next status fetch gets fresh data
    claims_cache["data"] = None

    # Get target name from current status if available
    target_name = f"Player {request.target_id}"

    try:
        cached = hospital_cache.get("war_status")
        if cached:
            for target in cached.get("targets", []):
                if target.get("user_id") == request.target_id:
                    target_name = target.get("name", target_name)
                    break
    except Exception:
        pass

    claim_mgr = get_claim_manager()
    x_api_key, player_id = auth
    # Fetch user name from Torn API (or cache)
    user_name = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.torn.com/user/",
                params={"selections": "profile", "key": x_api_key},
            )
            data = response.json()
            user_name = data.get("name", "Unknown")
    except Exception:
        user_name = "Unknown"

    success, message, claim = claim_mgr.claim(
        target_id=request.target_id,
        target_name=target_name,
        claimer_id=player_id,
        claimer_name=user_name,
    )

    return ClaimResponse(success=success, message=message, claim=claim)


@app.delete("/api/claim/{target_id}")
async def unclaim_target(
    target_id: int,
    claimer_id: int = Query(..., description="ID of the user releasing the claim"),
    auth: tuple[str, int] = Depends(check_faction_access),
):
    """Release a claim on a target."""
    # Invalidate claims cache
    claims_cache["data"] = None

    claim_mgr = get_claim_manager()
    success, message = claim_mgr.unclaim(target_id, claimer_id)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"success": True, "message": message}


@app.post("/api/claim/{target_id}/resolve")
async def resolve_claim(
    target_id: int, claimer_id: int = Query(..., description="ID of the user who made the attack")
):
    """Mark a claim as resolved (attack completed)."""
    claim_mgr = get_claim_manager()
    success, message = claim_mgr.resolve(target_id, claimer_id)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"success": True, "message": message}


@app.get("/api/claims")
async def get_all_claims():
    """Get all active claims."""
    claim_mgr = get_claim_manager()
    claims = claim_mgr.get_all_claims()
    return {"claims": [c.model_dump() for c in claims], "count": len(claims)}


@app.get("/api/stats")
async def get_stats():
    """Get application statistics."""
    claim_mgr = get_claim_manager()
    return {
        "rate_limiter": {
            "requests_remaining": rate_limiter.requests_remaining(),
            "wait_time": rate_limiter.wait_time(),
        },
        "cache": hospital_cache.stats(),
        "claims": claim_mgr.stats(),
        "timestamp": int(time.time()),
    }


@app.get("/api/leaderboards", response_model=Leaderboards)
async def get_leaderboards_endpoint(
    force_refresh: bool = Query(False, description="Force recalculation of leaderboards"),
    auth: tuple[str, int] = Depends(check_faction_access),
):
    """
    Get faction leaderboards for xanax, overdoses, gym gains, and hospital time.
    Leaderboards are cached and updated every hour.
    """
    api_key, player_id = auth

    # On first request, ensure we have stats for this user
    # Check if we have any stats for this player
    from api.leaderboards import stats_cache, update_user_stats_from_api_call

    if player_id not in stats_cache:
        print(
            f"First leaderboard request for player {player_id}, collecting stats synchronously..."
        )
        # Collect stats synchronously on first request
        await update_user_stats_from_api_call(api_key, player_id)
        # Force refresh to include the new data
        force_refresh = True

    return await get_leaderboards(force_refresh=force_refresh)


# TornStats cache (in-memory, keyed by faction ID) - DISABLED, using estimation instead
# tornstats_cache: dict[int, dict] = {}
# tornstats_cache_time: dict[int, float] = {}
# TORNSTATS_CACHE_TTL = 300  # 5 minutes - stats don't change often


def estimate_battle_stats(
    level: int,
    age_days: int = 0,
    xanax: int = 0,
    refills: int = 0,
    stat_enhancers: int = 0,
    cans: int = 0,
) -> int:
    """
    Estimate total battle stats based on publicly available information.
    This is a simplified version of YATA's estimation algorithm.

    Factors considered:
    - Level: Higher level = more stats
    - Age: Older accounts have had more time to train
    - Xanax: Energy boost for training
    - Refills: Energy refills for training
    - Stat enhancers: Direct stat boosts
    - Cans: Additional energy
    """
    # Base stats from level (rough approximation)
    # Level 100 players typically have between 100M - 10B+ stats
    # This is a very rough estimate

    if level <= 0:
        return 0

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

    # Adjustments based on other factors
    # Each xanax = roughly 250 energy = ~2.5M potential stat gain over time
    xanax_bonus = xanax * 100_000 if xanax else 0

    # Each refill = 150 energy = ~1.5M potential stat gain
    refill_bonus = refills * 75_000 if refills else 0

    # Stat enhancers provide direct boosts
    enhancer_bonus = stat_enhancers * 50_000 if stat_enhancers else 0

    # Cans = energy drinks
    cans_bonus = cans * 25_000 if cans else 0

    total = base + xanax_bonus + refill_bonus + enhancer_bonus + cans_bonus

    return int(total)


def format_estimated_stats(total: int) -> str:
    """Format stats for display."""
    if total <= 0:
        return "?"
    if total >= 1_000_000_000_000:
        return f"{total / 1_000_000_000_000:.1f}T"
    if total >= 1_000_000_000:
        return f"{total / 1_000_000_000:.1f}B"
    if total >= 1_000_000:
        return f"{total / 1_000_000:.1f}M"
    if total >= 1_000:
        return f"{total / 1_000:.1f}K"
    return str(total)


@app.get("/api/tornstats/{faction_id}")
async def get_tornstats(
    faction_id: int,
    x_api_key: str = Header(None, alias="X-API-Key", description="User's Torn API key"),
):
    """
    Get estimated battle stats from TornStats for a faction.
    Uses your Torn API key (same one you use on TornStats website).
    Fetches from your faction's shared spy database.
    Results are cached for 5 minutes.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    now = time.time()

    # Check cache
    if faction_id in tornstats_cache:
        cache_age = now - tornstats_cache_time.get(faction_id, 0)
        if cache_age < TORNSTATS_CACHE_TTL:
            return {"stats": tornstats_cache[faction_id], "cached": True, "cache_age": cache_age}

    # Fetch from TornStats spies endpoint (your faction's shared spy database)
    # This endpoint returns all spies your faction has shared
    url = f"https://www.tornstats.com/api/v2/{x_api_key}/spies"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)

            print(f"TornStats spies response status: {response.status_code}")

            raw_data = response.json()
            print(
                f"TornStats spies response keys: {raw_data.keys() if isinstance(raw_data, dict) else 'not a dict'}"
            )

            if response.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid API key for TornStats")

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"TornStats API error: {response.status_code}",
                )

            # Check for TornStats errors
            if raw_data.get("status") == False:
                error_msg = raw_data.get("message", "Unknown TornStats error")
                raise HTTPException(status_code=400, detail=error_msg)

            # TornStats spies endpoint returns: {"status": true, "spies": [...]}
            spies_list = raw_data.get("spies", [])

            print(f"TornStats found {len(spies_list)} spies in database")

            # Debug: Print first spy to see structure
            if spies_list:
                print(f"Sample spy data: {spies_list[0]}")

            # Transform to dict keyed by player_id
            stats_by_id = {}
            for spy in spies_list:
                try:
                    # TornStats format: player_id is a string
                    player_id = spy.get("player_id") or spy.get("playerId")
                    if not player_id:
                        continue

                    user_id = int(player_id)

                    stats_by_id[user_id] = {
                        "total": spy.get("total", 0) or 0,
                        "strength": spy.get("strength", 0) or 0,
                        "speed": spy.get("speed", 0) or 0,
                        "dexterity": spy.get("dexterity", 0) or 0,
                        "defense": spy.get("defense", 0) or 0,
                        "timestamp": spy.get("timestamp", 0) or 0,
                        "name": spy.get("player_name") or spy.get("playerName") or "",
                    }
                except (ValueError, TypeError) as e:
                    print(f"Error parsing spy: {e}")
                    continue

            # Count how many have non-zero stats
            non_zero = sum(1 for s in stats_by_id.values() if s.get("total", 0) > 0)
            print(f"Spies with stats: {non_zero}/{len(stats_by_id)}")

            # Cache the result
            tornstats_cache[faction_id] = stats_by_id
            tornstats_cache_time[faction_id] = now

            return {
                "stats": stats_by_id,
                "cached": False,
                "cache_age": 0,
                "total_spies": len(stats_by_id),
            }

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="TornStats request timed out")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"TornStats connection error: {str(e)}")
    except Exception as e:
        print(f"TornStats unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing TornStats data: {str(e)}")


# Serve static frontend files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def serve_frontend():
        """Serve the main frontend page."""
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="Frontend not found")

    @app.get("/favicon.ico")
    async def serve_favicon():
        """Serve favicon."""
        favicon_path = os.path.join(static_dir, "favicon.svg")
        if os.path.exists(favicon_path):
            return FileResponse(favicon_path, media_type="image/svg+xml")
        raise HTTPException(status_code=404, detail="Favicon not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
