"""Discover live incidents near a point and hydrate full details.

Demonstrates the core unauthenticated incident feed:
  status -> service areas -> tile markers -> v3 detail -> v1 batch ->
  related -> content -> map sources -> chat history.

Usage: python examples/nearby_incidents.py [lat lon] [--bbox W S E N]
"""

from __future__ import annotations

import argparse
import asyncio

from pycitizen import CitizenClient

DEFAULT_BBOX = (-74.02, 40.68, -73.95, 40.74)  # south Brooklyn / lower Manhattan


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bbox", nargs=4, type=float, default=DEFAULT_BBOX,
                        metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--zoom", type=int, default=12)
    parser.add_argument("--details", type=int, default=3, help="incidents to hydrate")
    args = parser.parse_args()
    bbox = tuple(args.bbox)

    async with CitizenClient() as client:
        # 1. Where are we? (service-area + reverse geocode, both public)
        lat = (bbox[1] + bbox[3]) / 2
        lon = (bbox[0] + bbox[2]) / 2
        status = await client.get_status(lat, lon)
        loc = await client.get_location_name(lat, lon)
        print(f"== Area: {loc.location_name} ({status.service_area_code}) "
              f"in_service_area={status.in_service_area} "
              f"past_hour_incidents={status.past_hour_incidents}")

        areas = await client.get_service_areas(bbox)
        print(f"== Service areas in bbox: {areas}")

        # 2. Live incident markers from vector tiles
        markers = await client.get_incident_markers(bbox, zoom=args.zoom)
        print(f"\n== {len(markers)} live incident markers")
        for m in markers[:15]:
            pos = f"{m.position.latitude:.4f},{m.position.longitude:.4f}" if m.position else "?"
            print(f"  [{m.severity.value:7}] [{m.lifecycle_state.value:10}] "
                  f"{m.incident_id}  {m.title}  ({pos})")

        if not markers:
            return

        # 3. Full detail on the first few (v3)
        print("\n== Incident details (v3)")
        for m in markers[: args.details]:
            inc = await client.get_incident(m.incident_id)
            print(f"  {inc.incident_id}: {inc.title}")
            print(f"    location={inc.location}  neighborhood={inc.neighborhood}")
            print(f"    ts={inc.timestamp}  lifecycle={inc.lifecycle_state.value} "
                  f"confirmed={inc.confirmed}")

        # 4. Batch hydration (v1 shape, one request)
        batch = await client.get_incidents([m.incident_id for m in markers[:5]])
        print(f"\n== Batch fetch: {len(batch)} incidents in one request")
        for inc in batch:
            views = inc.stats.views if inc.stats else None
            print(f"  {inc.incident_id}: {inc.title} (views={views}, "
                  f"updates={len(inc.updates)})")

        # 5. Related incidents + content + map sources + chat for one incident
        first = markers[0].incident_id
        related = await client.get_related_incidents(first)
        print(f"\n== {first} related: {related[:5]}")

        content = await client.get_incident_content(first)
        print(f"== content items: {len(content)}")
        for c in content[:5]:
            print(f"  {c.type}: {c.url}")

        sources = await client.get_incident_map_sources(first)
        print(f"== map_sources keys: {list(sources)[:8]}")

        history = await client.get_chat_history(first, limit=5)
        print(f"== chat: {len(history.messages)} messages, has_more={history.has_more}")
        for msg in history.messages:
            print(f"  {msg.user_name}: {msg.message}")


if __name__ == "__main__":
    asyncio.run(main())
