"""
Faction Overview API

Stores and retrieves faction member profile data for leadership view.
Only accessible to whitelisted leadership IDs.
Pure in-memory storage for VPS deployment.
"""

import time
from typing import List

from pydantic import BaseModel


# In-memory store: player_id -> FactionMemberProfile dict
_faction_profiles: dict[int, dict] = {}


class FactionMemberProfile(BaseModel):
    """Profile data for a faction member."""

    player_id: int
    name: str
    level: int
    status: str
    status_until: int  # Unix timestamp
    last_action: int  # Unix timestamp

    # Current stats
    life_current: int
    life_maximum: int
    energy_current: int
    energy_maximum: int
    nerve_current: int
    nerve_maximum: int
    happy_current: int
    happy_maximum: int

    # Cooldowns (seconds remaining)
    drug_cooldown: int
    medical_cooldown: int
    booster_cooldown: int

    # Hospital/jail
    hospital_timestamp: int
    jail_timestamp: int

    # Travel
    travel_destination: str
    travel_timestamp: int

    # Last updated
    last_updated: int  # Unix timestamp


async def store_faction_member_profile(player_id: int, torn_api_data: dict):
    """
    Store faction member profile data in memory.

    Args:
        player_id: The player's Torn ID
        torn_api_data: Full response from Torn API user endpoint
    """
    try:
        status_data = torn_api_data.get("status", {})
        status_state = status_data.get("state", "Unknown")
        status_until = status_data.get("until", 0)

        life_data = torn_api_data.get("life", {})
        energy_data = torn_api_data.get("energy", {})
        nerve_data = torn_api_data.get("nerve", {})
        happy_data = torn_api_data.get("happy", {})

        cooldowns = torn_api_data.get("cooldowns", {})
        drug_cd = cooldowns.get("drug", 0)
        medical_cd = cooldowns.get("medical", 0)
        booster_cd = cooldowns.get("booster", 0)

        states = torn_api_data.get("states", {})
        hospital_ts = states.get("hospital_timestamp", 0) or 0
        jail_ts = states.get("jail_timestamp", 0) or 0

        travel = torn_api_data.get("travel", {})
        travel_dest = travel.get("destination", "")
        travel_ts = travel.get("timestamp", 0) or 0

        profile = FactionMemberProfile(
            player_id=player_id,
            name=torn_api_data.get("name", "Unknown"),
            level=torn_api_data.get("level", 0),
            status=status_state,
            status_until=status_until,
            last_action=torn_api_data.get("last_action", {}).get("timestamp", 0) or 0,
            life_current=life_data.get("current", 0),
            life_maximum=life_data.get("maximum", 0),
            energy_current=energy_data.get("current", 0),
            energy_maximum=energy_data.get("maximum", 0),
            nerve_current=nerve_data.get("current", 0),
            nerve_maximum=nerve_data.get("maximum", 0),
            happy_current=happy_data.get("current", 0),
            happy_maximum=happy_data.get("maximum", 0),
            drug_cooldown=drug_cd,
            medical_cooldown=medical_cd,
            booster_cooldown=booster_cd,
            hospital_timestamp=hospital_ts,
            jail_timestamp=jail_ts,
            travel_destination=travel_dest,
            travel_timestamp=travel_ts,
            last_updated=int(time.time()),
        )

        _faction_profiles[player_id] = profile.model_dump()

    except Exception as e:
        print(f"Error storing faction profile for {player_id}: {e}")


async def get_all_faction_profiles() -> List[FactionMemberProfile]:
    """
    Get all stored faction member profiles.
    Returns list of profiles sorted by last action (most recent first).
    """
    try:
        profiles = []
        for profile_data in _faction_profiles.values():
            try:
                profile = FactionMemberProfile(**profile_data)
                profiles.append(profile)
            except Exception as e:
                print(f"Error parsing profile: {e}")

        profiles.sort(key=lambda p: p.last_action, reverse=True)
        return profiles

    except Exception as e:
        print(f"Error fetching faction profiles: {e}")
        return []
