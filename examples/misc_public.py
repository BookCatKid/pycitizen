"""Remaining public endpoints: users, usernames, social, stats, settings.

Usage: python examples/misc_public.py
"""

from __future__ import annotations

import asyncio

from pycitizen import CitizenClient


async def main() -> None:
    async with CitizenClient() as client:
        # Health + anonymous remote config
        print("health:", await client.health())
        settings = await client.get_variable_settings()
        print(f"variable_settings_anonymous: {len(settings)} keys")

        # Public user lookups
        users = await client.get_public_users(["nonexistent_user_id"])
        print(f"batch_public: {len(users)} users resolved")

        check = await client.check_username("definitely_not_taken_987654")
        print(f"check_username: allowed={check.allowed} reason={check.reason}")

        # Citizen Protect marketing stats
        stats = await client.get_impact_statistics()
        print(f"impact: premium_users={stats.users_with_premium} "
              f"calls_week={stats.calls_answered_past_week} "
              f"missing_found={stats.missing_found}")

        # Friend presence (public endpoint, empty without auth)
        presence = await client.get_social_presence(["-P1vrxK35R7YgOyBYNo2"])
        for p in presence:
            print(f"social_presence {p.incident_id}: aware={len(p.aware)} "
                  f"view={len(p.view)}")

        # Location search + full safety location record
        results = await client.search_locations("Sunset Park", latitude=40.65,
                                                longitude=-74.0)
        n = len(results) if isinstance(results, list) else len(results or {})
        print(f"location_search results: {n}")
        location = await client.get_location(40.65, -74.0)
        keys = list(location)[:10] if isinstance(location, dict) else type(location)
        print(f"safety/location keys: {keys}")


if __name__ == "__main__":
    asyncio.run(main())
