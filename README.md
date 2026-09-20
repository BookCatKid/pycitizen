# pycitizen

[![CI](https://github.com/BookCatKid/pycitizen/actions/workflows/ci.yml/badge.svg)](https://github.com/BookCatKid/pycitizen/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pycitizen.svg)](https://pypi.org/project/pycitizen/)
[![Python](https://img.shields.io/pypi/pyversions/pycitizen.svg)](https://pypi.org/project/pycitizen/)
[![License](https://img.shields.io/pypi/l/pycitizen.svg)](https://github.com/BookCatKid/pycitizen/blob/main/LICENSE)
[![Typed](https://img.shields.io/badge/typed-mypy%20strict-blue.svg)](https://mypy-lang.org/)

Async-first Python SDK for [Citizen](https://citizen.com)'s **public, unauthenticated** incident API — geographic incident discovery via vector tiles, incident details, batch retrieval, related incidents, news feeds, and read-only chat history.

Reverse-engineered from Citizen Android `0.1308.0` (`sp0n.citizen`, build 1140). Every endpoint implemented here was verified reachable without an access token.

> **Status: experimental.** Unofficial SDK, not affiliated with Citizen. The endpoints are undocumented and may change or become restricted at any time. Use politely — keep request rates low, cache aggressively, and honor the rate limiter defaults.

## Features

- **Geographic discovery** — fetch every incident in a bounding box with one request per covering Mapbox vector tile (`/v1/tile/incidents/{x}/{y}/{z}.pbf`), decoded by a built-in dependency-free MVT parser.
- **Incident details** — v1/v2/v3 detail endpoints unified into one `Incident` model; batch retrieval for up to 50 IDs per request.
- **News** — curated news feed and news briefings per service area.
- **Auxiliary** — service-area lookup, safety status, reverse geocoding, place search, incident content/map sources, read-only chat history, neighborhood trends (raw).
- **`IncidentFeed`** — polling tracker with deduplication, field-level change detection, lifecycle-transition history, and graceful stale/removed handling. Designed to wrap in a `DataUpdateCoordinator` (e.g. Home Assistant).
- **Async-first** — `aiohttp`, injectable sessions, token-bucket rate limiting, bounded concurrency, retries with exponential backoff honoring `Retry-After`.
- **Fully typed** — `py.typed`, dataclass models, enum severity/lifecycle values matching the app's own DTOs.

## Installation

```bash
pip install pycitizen
```

Requires Python 3.11+. Only runtime dependency is `aiohttp`.

## Quick start

```python
import asyncio
from pycitizen import CitizenClient

# (west, south, east, north) — e.g. Manhattan
BBOX = (-74.02, 40.70, -73.93, 40.80)

async def main() -> None:
    async with CitizenClient() as client:
        # 1. Discover every incident marker in the bbox via vector tiles
        markers = await client.get_incident_markers(BBOX)
        for m in markers:
            print(m.incident_id, m.title, m.severity.value, m.timestamp)

        # 2. Hydrate full details (batch or single)
        incidents = await client.get_incidents([m.incident_id for m in markers])
        for inc in incidents:
            print(inc.title, inc.location, inc.lifecycle_state.value)

asyncio.run(main())
```

## Tracking a feed

```python
from pycitizen import CitizenClient, IncidentFeed, FeedState

async with CitizenClient() as client:
    feed = IncidentFeed(client, BBOX, expire_after=900)

    while True:
        diff = await feed.update()
        for t in diff.added:
            print("NEW:", t.marker.title)
        for t in diff.updated:
            print("UPDATED:", t.marker.title, "->", t.marker.lifecycle_state.value)
        for t in diff.removed:
            print("GONE:", t.marker.title)
        await asyncio.sleep(60)
```

`TrackedIncident` retains `first_seen`, `last_seen`, and a `lifecycle_history` of `(timestamp, LifecycleState)` transitions (`reported → verified → developing → resolved/inactive`).

## API surface

| Method | Endpoint | Notes |
|---|---|---|
| `health()` | `GET /healthz` | reachability check |
| `get_variable_settings()` | `GET /v1/variable_settings_anonymous` | remote config flags |
| `get_status(lat, lon)` | `GET /v1/homescreen/status` | service-area info for a point |
| `get_service_areas(bbox)` | `GET /v1/homescreen/mapExplore` | service-area codes for a bbox |
| `get_incident_markers(bbox, zoom=12, categories=…, created_gte/lte=…, limit=…, active_definition=…)` | `GET /v1/tile/incidents/{x}/{y}/{z}.pbf` | the discovery workhorse; optional filters mirror the app's tile-URL params |
| `get_historical_incidents(bbox, zoom)` | `GET /v1/tile/historical_incidents/{x}/{y}/{z}.pbf` | past-window incidents |
| `get_offender_markers(bbox, zoom)` | `GET /v1/tile/offenders/{x}/{y}/{z}.pbf` | offender registry layer |
| `get_places(bbox, zoom)` | `GET /v1/tile/places/{x}/{y}/{z}.pbf` | OSM place labels |
| `get_tile_style(name)` | `GET /v1/tile/style/{name}.json` | MapLibre style docs |
| `get_incident(id)` | `GET /v3/incident/{id}` | primary detail |
| `get_incident_v1/v2(id)` | `GET /v{1,2}/incident/{id}` | richer/alternate shapes |
| `get_incidents(ids)` | `GET /v1/incidents/batch` | chunked at 50 IDs |
| `get_related_incidents(id)` | `GET /v1/incidents/{id}/related_incidents` | merged/related IDs |
| `get_incident_content(id)` | `GET /v1/incidents/{id}/content` | links/images/streams |
| `get_incident_map_sources(id)` | `GET /v1/incidents/{id}/map_sources` | raw |
| `get_news_feed(code)` | `GET /v2/news/feed` | curated feed |
| `get_news_briefing(code)` | `GET /v2/incidents/news_briefing` | generated briefings |
| `get_chat_history(id, ...)` | `GET /v4/incident_chat/history` | read-only, paginated |
| `get_location_name(lat, lon)` | `GET /v1/safety/location_name` | reverse geocode |
| `search_locations(q, ...)` | `GET /v1/safety/location_search` | place search |
| `get_location(lat, lon)` | `GET /v1/safety/location` | safety location record |
| `get_public_users(ids)` | `GET /v1/users/batch_public` | public profiles |
| `check_username(name)` | `GET /v1/users/check_username` | availability check |
| `get_social_presence(ids)` | `GET /v1/incidents/social/batch` | friend presence (empty w/o auth) |
| `get_impact_statistics()` | `GET /v1/protect/impact_statistics` | Protect marketing stats |
| `get_neighborhood_details(id)` | `GET /v1/trends/neighborhoods/{id}/details` | crime-level summary |
| `get_neighborhood_incidents(id)` | `GET /v1/trends/neighborhoods/{id}/incidents` | typed `Incident` list |
| `get_neighborhood_boundary(id)` | `GET /v1/trends/neighborhoods/{id}/boundary` | GeoJSON geometry |
| `get_neighborhood_graph(id)` | `GET /v1/trends/neighborhoods/{id}/graph` | category time series |
| `get_neighborhood_feed(lat, lon)` | `GET /v1/trends/shs_feed` | neighborhood for a point |

`client.get_json(path, params)` is a low-level escape hatch for anything not wrapped.

## Examples

Runnable live demos of the whole public surface — see [`examples/`](examples/README.md):

```bash
python examples/nearby_incidents.py    # the full incident pipeline
python examples/feed_watcher.py        # IncidentFeed diffing
python examples/map_layers.py          # historical / offender / place tiles
python examples/news_and_trends.py     # news + neighborhood trends
python examples/misc_public.py         # users, usernames, stats, settings
```

## What this SDK does *not* do

- **No authentication flows.** Citizen's private endpoints (homescreen feed/mapIncidents, search, friends, variable_settings, user endpoints) return `401` without a user token obtained via phone-OTP sign-in. Not implemented.
- **No WebSocket.** `wss://data.sp0n.io/websocket` only carries chat and Protect subscription traffic — not the incident feed — and rejects unauthenticated method calls (`auth required`).
- **No push notifications.** Alerts arrive via FCM tied to a registered device token; there is no public push channel.
- **No mutations.** Posting incidents, comments, likes, follows — all auth-gated and out of scope.

Real-time updates = **poll the tiles**. They are the same source the app's map consumes.

## Configuration

```python
from pycitizen import CitizenClient, RateLimiter, RetryPolicy

client = CitizenClient(
    rate_limiter=RateLimiter(rate=2.0, burst=2, max_concurrent=2),
    retry_policy=RetryPolicy(max_attempts=4),
    timeout=15.0,
)
```

Inject an existing session (e.g. Home Assistant's shared one) with `CitizenClient(session=session)`; `close()` then becomes a no-op.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # fully offline test suite
ruff check src tests   # lint
mypy            # strict type check (8 modules, zero errors)
python -m build # sdist + wheel
```

The test suite never touches the network: HTTP is stubbed and the vector-tile path is exercised against a real tile captured from the live API (`tests/fixtures/incidents_tile.pbf`).

## License

MIT — see [LICENSE](LICENSE).
