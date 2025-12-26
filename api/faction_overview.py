"""
Faction Overview API

Stores and retrieves faction member profile data for leadership view.
Only accessible to whitelisted leadership IDs.
"""

import os
import time
from typing import List

from pydantic import BaseModel


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
    Store faction member profile data in Redis.
    Called whenever a user makes an API request with their key.

    Args:
        player_id: The player's Torn ID
        torn_api_data: Full response from Torn API user endpoint
    """
    # Check if KV is available
    kv_url = os.getenv("KV_REST_API_URL")
    if not kv_url:
        print("Warning: KV not configured, cannot store faction profiles")
        return

    try:
        import httpx

        # Extract status info
        status_data = torn_api_data.get("status", {})
        status_state = status_data.get("state", "Unknown")
        status_until = status_data.get("until", 0)

        # Extract life/energy/nerve/happy
        life_data = torn_api_data.get("life", {})
        energy_data = torn_api_data.get("energy", {})
        nerve_data = torn_api_data.get("nerve", {})
        happy_data = torn_api_data.get("happy", {})

        # Extract cooldowns
        cooldowns = torn_api_data.get("cooldowns", {})
        drug_cd = cooldowns.get("drug", 0)
        medical_cd = cooldowns.get("medical", 0)
        booster_cd = cooldowns.get("booster", 0)

        # Extract hospital/jail
        states = torn_api_data.get("states", {})
        hospital_ts = states.get("hospital_timestamp", 0) or 0
        jail_ts = states.get("jail_timestamp", 0) or 0

        # Extract travel
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

        # Store in Vercel KV with 1 hour expiry (will refresh when user is active)
        key = f"faction_profile:{player_id}"
        token = os.getenv("KV_REST_API_TOKEN")

        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.get(
                f"{kv_url}/set/{key}/{profile.model_dump_json()}/ex/3600",
                headers={"Authorization": f"Bearer {token}"},
            )

    except Exception as e:
        # Don't fail the main request if profile storage fails
        print(f"Error storing faction profile for {player_id}: {e}")


async def get_all_faction_profiles() -> List[FactionMemberProfile]:
    """
    Get all stored faction member profiles.
    Returns list of profiles sorted by last action (most recent first).
    """
    kv_url = os.getenv("KV_REST_API_URL")
    if not kv_url:
        return []

    try:
        import httpx

        token = os.getenv("KV_REST_API_TOKEN")

        # Get all profile keys
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{kv_url}/keys/faction_profile:*", headers={"Authorization": f"Bearer {token}"}
            )

            if response.status_code != 200:
                return []

            keys = response.json().get("result", [])
            if not keys:
                return []

            # Fetch all profiles
            profiles = []
            for key in keys:
                try:
                    resp = await client.get(
                        f"{kv_url}/get/{key}", headers={"Authorization": f"Bearer {token}"}
                    )
                    if resp.status_code == 200:
                        data = resp.json().get("result")
                        if data:
                            profile = FactionMemberProfile.model_validate_json(data)
                            profiles.append(profile)
                except Exception as e:
                    print(f"Error parsing profile {key}: {e}")

            # Sort by last action (most recent first)
            profiles.sort(key=lambda p: p.last_action, reverse=True)

            return profiles

    except Exception as e:
        print(f"Error fetching faction profiles: {e}")
        return []
