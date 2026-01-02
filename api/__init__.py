"""
Torn Ranked War Tracker API Package
"""

from .models import (
    PlayerStatus,
    HitClaim,
    WarStatus,
    ClaimRequest,
    ClaimResponse,
    OnlineStatus,
    HospitalStatus,
    FactionInfo,
)

from .cache import hospital_cache, player_cache, faction_cache, rate_limiter, yata_cache, Cache

from .claims import claim_manager, ClaimManager, init_claim_manager, get_claim_manager

from .torn_client import TornClient, TornAPIError, get_client, init_client

from .yata_client import (
    fetch_battle_stats_estimates,
    fetch_single_battle_stats_estimate,
    YATAError,
    format_battle_stats,
)

__all__ = [
    # Models
    "PlayerStatus",
    "HitClaim",
    "WarStatus",
    "ClaimRequest",
    "ClaimResponse",
    "OnlineStatus",
    "HospitalStatus",
    "FactionInfo",
    # Cache
    "hospital_cache",
    "player_cache",
    "faction_cache",
    "rate_limiter",
    "yata_cache",
    "Cache",
    # Claims
    "claim_manager",
    "ClaimManager",
    "init_claim_manager",
    "get_claim_manager",
    # Client
    "TornClient",
    "TornAPIError",
    "get_client",
    "init_client",
    # YATA Client
    "fetch_battle_stats_estimates",
    "fetch_single_battle_stats_estimate",
    "YATAError",
    "format_battle_stats",
]
