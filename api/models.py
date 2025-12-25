"""
Torn Ranked War Tracker - Data Models

Pydantic models for player status, hit claims, and API responses.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class OnlineStatus(str, Enum):
    """Inferred online status based on last action timestamp."""

    ONLINE = "online"  # Last action < 2 minutes
    IDLE = "idle"  # Last action 2-5 minutes
    OFFLINE = "offline"  # Last action > 5 minutes
    UNKNOWN = "unknown"


class HospitalStatus(str, Enum):
    """Current hospital status of a player."""

    IN_HOSPITAL = "in_hospital"
    OUT = "out"
    ABOUT_TO_EXIT = "about_to_exit"  # < 30 seconds remaining


class PlayerStatus(BaseModel):
    """
    Represents the current inferred state of a target player.
    Combines Torn API data with derived/calculated fields.
    """

    user_id: int
    name: str
    level: int = 0

    # Hospital info
    hospital_until: Optional[int] = None  # Unix timestamp when leaving hospital
    hospital_remaining: int = 0  # Seconds remaining (calculated)
    hospital_status: HospitalStatus = HospitalStatus.OUT
    hospital_reason: str = ""  # Why they're in hospital

    # Travel status
    traveling: bool = False
    travel_destination: str = ""
    travel_until: Optional[int] = None

    # Online inference
    last_action_ts: Optional[int] = None  # Unix timestamp of last action
    last_action_relative: str = ""  # "2 minutes ago" etc
    estimated_online: OnlineStatus = OnlineStatus.UNKNOWN

    # Medding detection (heuristic)
    medding: bool = False  # True if suspected medding out
    previous_hospital_until: Optional[int] = None  # For med detection

    # Estimated battle stats (based on level)
    estimated_stats: int = 0  # Estimated total battle stats
    estimated_stats_formatted: str = ""  # Human readable (e.g., "150M")

    # Claim info (from our system, not Torn)
    claimed_by: Optional[str] = None  # Username who claimed
    claimed_by_id: Optional[int] = None  # User ID who claimed
    claimed_at: Optional[int] = None  # Unix timestamp
    claim_expires: Optional[int] = None  # When claim auto-expires

    # Metadata
    last_updated: int = 0  # When we last fetched this data

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 1234567,
                "name": "TargetPlayer",
                "level": 75,
                "hospital_until": 1703500000,
                "hospital_remaining": 45,
                "hospital_status": "about_to_exit",
                "hospital_reason": "Attacked by SomePlayer",
                "last_action_ts": 1703499900,
                "last_action_relative": "2 minutes ago",
                "estimated_online": "online",
                "medding": False,
                "claimed_by": None,
                "claimed_at": None,
                "last_updated": 1703499955,
            }
        }


class HitClaim(BaseModel):
    """
    Internal coordination object for tracking who is attacking whom.
    This is NOT from Torn API - it's our own state management.
    """

    target_id: int
    target_name: str
    claimed_by: str  # Username
    claimed_by_id: int  # User ID
    claimed_at: int  # Unix timestamp
    expires_at: int  # Auto-expire timestamp
    resolved: bool = False  # True if attack completed

    class Config:
        json_schema_extra = {
            "example": {
                "target_id": 1234567,
                "target_name": "TargetPlayer",
                "claimed_by": "Attacker",
                "claimed_by_id": 7654321,
                "claimed_at": 1703499900,
                "expires_at": 1703500020,
                "resolved": False,
            }
        }


class FactionInfo(BaseModel):
    """Basic faction information."""

    faction_id: int
    faction_name: str
    faction_tag: str = ""


class WarStatus(BaseModel):
    """
    Overall war status response combining all target data.
    This is the main response from /api/status endpoint.
    """

    # War info
    our_faction: Optional[FactionInfo] = None
    enemy_faction: Optional[FactionInfo] = None
    war_id: Optional[int] = None

    # Targets
    targets: list[PlayerStatus] = Field(default_factory=list)

    # Active claims
    active_claims: list[HitClaim] = Field(default_factory=list)

    # Stats
    total_targets: int = 0
    in_hospital: int = 0
    out_of_hospital: int = 0
    claimed: int = 0
    traveling: int = 0

    # Config
    max_claims_per_user: int = 3

    # Metadata
    last_updated: int = 0
    cache_age_seconds: float = 0.0  # How old is this cached data
    next_refresh_in: float = 0.0  # Seconds until next API poll

    # Rate limit info
    api_calls_remaining: int = 100  # Estimated calls left this minute


class ClaimRequest(BaseModel):
    """Request body for claiming a target."""

    target_id: int
    claimer_name: str
    claimer_id: int


class ClaimResponse(BaseModel):
    """Response for claim/unclaim operations."""

    success: bool
    message: str
    claim: Optional[HitClaim] = None


class ApiKeyInfo(BaseModel):
    """Information about an API key's owner and access."""

    key_id: str  # Last 4 chars only for identification
    owner_id: int
    owner_name: str
    access_level: int
    last_used: Optional[int] = None
    requests_this_minute: int = 0
