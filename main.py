"""
Torn Ranked War Tracker - Main FastAPI Application

Provides REST API endpoints for:
- War status and target tracking
- Hit claiming/unclaiming
- Health/status checks
"""

import os
import time
from contextlib import asynccontextmanager

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

        # Enrich targets with claim info
        claims = claim_mgr.get_all_claims()
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


@app.post("/api/claim", response_model=ClaimResponse)
async def claim_target(request: ClaimRequest):
    """
    Claim a target for attacking.
    Prevents other faction members from attacking the same person.
    """
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
