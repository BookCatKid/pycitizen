"""News feeds, briefings, and neighborhood trend data.

All endpoints demonstrated here are unauthenticated.

Usage: python examples/news_and_trends.py [--code nyc]
"""

from __future__ import annotations

import argparse
import asyncio

from pycitizen import CitizenClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", default="nyc", help="service area code")
    parser.add_argument("--neighborhood", default=None, help="neighborhood id")
    args = parser.parse_args()

    async with CitizenClient() as client:
        # Curated news feed
        items = await client.get_news_feed(args.code)
        print(f"== {len(items)} news feed items for '{args.code}'")
        for item in items[:10]:
            inc = item.incident
            print(f"  [{item.bucket or '-':12}] {inc.incident_id}  {inc.title}")

        # Generated briefing (404s when none exists for the area)
        try:
            briefing = await client.get_news_briefing(args.code)
            print(f"\n== Briefing: {briefing.title} - {briefing.subtitle} "
                  f"({len(briefing.incidents)} incidents)")
        except Exception as exc:
            print(f"\n== No briefing for '{args.code}' ({type(exc).__name__})")

        # Neighborhood trends. shs_feed resolves a coordinate to an internal
        # neighborhood id; it is currently empty in tested areas, so fall back
        # to a guessed id -- the endpoints respond 200 (empty for unknown ids).
        feed = await client.get_neighborhood_feed(40.65, -74.0)
        nid = args.neighborhood or feed.neighborhood_id or "nyc-sunset-park"
        print(f"\n== Neighborhood feed @40.65,-74.0: "
              f"{feed.neighborhood_name} (id={nid})")
        details = await client.get_neighborhood_details(nid)
        print(f"== details: {details.name} crime_level={details.crime_level} "
              f"lookback={details.stats_lookback_days}d stats={len(details.stats)}")

        incidents = await client.get_neighborhood_incidents(nid, lookback_days=30)
        print(f"== trend incidents (30d): {len(incidents)}")
        for inc in incidents[:5]:
            print(f"  {inc.incident_id}  {inc.title}")

        boundary = await client.get_neighborhood_boundary(nid)
        print(f"== boundary: type={boundary.type} "
              f"rings={len(boundary.coordinates)}")

        graph = await client.get_neighborhood_graph(nid)
        stats_keys = list(graph.get("stats", {}))[:8]
        print(f"== graph categories: {stats_keys}")


if __name__ == "__main__":
    asyncio.run(main())
