"""Explore Citizen's other public tile layers.

Beyond live incidents, the same unauthenticated tile infrastructure serves
historical incidents, registered offenders, OSM place labels, and the
MapLibre style documents themselves.

Usage: python examples/map_layers.py [--bbox W S E N]
"""

from __future__ import annotations

import argparse
import asyncio

from pycitizen import CitizenClient
from pycitizen.const import TILE_STYLE_ALL_LAYERS, TILE_STYLE_DARK

BBOX = (-74.05, 40.62, -73.97, 40.69)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bbox", nargs=4, type=float, default=BBOX,
                        metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    args = parser.parse_args()
    bbox = tuple(args.bbox)

    async with CitizenClient() as client:
        # Historical incidents (past-window layer)
        hist = await client.get_historical_incidents(bbox)
        print(f"== {len(hist)} historical incidents")
        for h in hist[:10]:
            print(f"  {h.incident_id}  {h.title}  frame={h.time_frame} "
                  f"views={h.view_count}")

        # Offender registry markers
        offenders = await client.get_offender_markers(bbox)
        print(f"\n== {len(offenders)} offender markers")
        for o in offenders[:10]:
            pos = f"{o.position.latitude:.4f},{o.position.longitude:.4f}" if o.position else "?"
            print(f"  {o.offender_id}  {o.display_name}  ({pos})  charges={o.charges}")

        # OSM place labels
        places = await client.get_places(bbox)
        print(f"\n== {len(places)} place labels")
        for p in places[:10]:
            print(f"  {p.name} ({p.type}, z={p.z_order})")

        # The app's own map styles
        for name in (TILE_STYLE_DARK, TILE_STYLE_ALL_LAYERS):
            style = await client.get_tile_style(name)
            sources = list(style.get("sources", {}))
            print(f"\n== style '{name}': {len(sources)} sources -> {sources}")


if __name__ == "__main__":
    asyncio.run(main())
