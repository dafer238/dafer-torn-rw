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

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Header
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

    yield

    # Shutdown - nothing to clean up since clients are per-request


# Simple cache for claims to reduce Redis queries
claims_cache = {"data": None, "timestamp": 0}
CLAIMS_CACHE_TTL = 2  # Cache claims for 2 seconds


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
    x_api_key: str = Header(None, alias="X-API-Key", description="User's Torn API key"),
):
    """
    Get current war status with all target information.
    This is the main endpoint polled by the frontend.
    Each user must provide their own API key via X-API-Key header.
    """
    now = int(time.time())
    claim_mgr = get_claim_manager()

    # Validate API key
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required. Set X-API-Key header.")

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
            api_calls_remaining=100,  # Each user has their own limit
        )

        return response

    finally:
        # Clean up the temporary client
        await client.close()


@app.get("/api/me")
async def get_my_status(x_api_key: str = Header(None)):
    """
    Get current user's status including health, cooldowns, energy, chain, etc.
    Requires user's API key.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

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


@app.post("/api/claim", response_model=ClaimResponse)
async def claim_target(request: ClaimRequest):
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
    success, message, claim = claim_mgr.claim(
        target_id=request.target_id,
        target_name=target_name,
        claimer_id=request.claimer_id,
        claimer_name=request.claimer_name,
    )

    return ClaimResponse(success=success, message=message, claim=claim)


@app.delete("/api/claim/{target_id}")
async def unclaim_target(
    target_id: int, claimer_id: int = Query(..., description="ID of the user releasing the claim")
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
