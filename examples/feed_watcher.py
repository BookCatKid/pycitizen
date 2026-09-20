"""Watch an area for incident changes using IncidentFeed.

Demonstrates deduplication, change detection and lifecycle tracking —
the primitive a Home Assistant DataUpdateCoordinator would wrap.

Usage: python examples/feed_watcher.py [--interval 60] [--cycles 5]
"""

from __future__ import annotations

import argparse
import asyncio

from pycitizen import CitizenClient, IncidentFeed

BBOX = (-74.02, 40.68, -73.95, 40.74)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=60.0)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--expire", type=float, default=300.0)
    args = parser.parse_args()

    async with CitizenClient() as client:
        feed = IncidentFeed(client, BBOX, expire_after=args.expire)
        for cycle in range(1, args.cycles + 1):
            diff = await feed.update()
            print(f"--- cycle {cycle} (seq={diff.sequence}) "
                  f"tracking={len(feed.incidents)} active={len(feed.active_incidents())}")
            for t in diff.added:
                print(f"  + NEW     {t.marker.incident_id} {t.marker.title}")
            for t in diff.updated:
                hist = " -> ".join(s.value for _, s in t.lifecycle_history)
                print(f"  ~ UPDATED {t.marker.incident_id} {t.marker.title}  [{hist}]")
            for t in diff.removed:
                print(f"  - REMOVED {t.marker.incident_id} {t.marker.title}")
            if not diff.changed:
                print("  (no changes)")
            if cycle < args.cycles:
                await asyncio.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
