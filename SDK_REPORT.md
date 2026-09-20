# pycitizen — SDK Report

Async-first, standalone Python SDK for Citizen's public incident API.
Built from the reverse-engineering of Citizen Android `0.1308.0`
(`sp0n.citizen`, build 1140); see `research/CITIZEN_API_REPORT.md` for the full
investigation. Version: **0.1.0**.

## Supported features

### Geographic discovery (vector tiles)

- `get_incident_markers(bbox, zoom=12, clip_to_bbox=True, categories=…,
  created_gte/lte=…, limit=…, active_definition=…, with_lifecycle_state=…)` —
  optional server-side filters mirroring the app's tile-URL params
  (`incident_category`, `incident_created_at_gte/lte`, `limit`,
  `active_definition`, `with_lifecycle_state`) — covers a
  bounding box with slippy-map tiles, fetches
  `GET /v1/tile/incidents/{x}/{y}/{z}.pbf` concurrently, decodes the MVT
  `incidents` layer, deduplicates markers across tile edges, and clips to
  the requested bbox. Missing (404) or transiently failing tiles degrade
  to partial coverage instead of failing the whole call.
- `get_historical_incidents(bbox, zoom)` — `historical_incidents` tile
  layer (past-window incidents: id, title, position, time_frame, score,
  engagement counts).
- `get_offender_markers(bbox, zoom)` — `offenders` tile layer
  (registry markers: id, names, address, charges, image, position).
- `get_places(bbox, zoom)` — `places` tile layer (OSM town/suburb/
  neighbourhood labels, position projected from tile geometry).
- `get_tile_style(name)` — the app's MapLibre style documents
  (`citizen-app-dark-20220303`, `citizen-app-light-20250512`,
  `citizen-incidents-offenders-wildfire-evac-all`) — also the discovery
  source for the tile endpoints above.
- `pycitizen.tiles` — dependency-free protobuf wire reader + MVT decoder
  (layers, features, properties, point/line/polygon geometry), plus
  `lonlat_to_tile`, `tile_bounds`, `tiles_for_bbox` helpers.
- `get_status(lat, lon)` — service-area info (`v1/homescreen/status`).
- `get_service_areas(bbox)` — service-area codes (`v1/homescreen/mapExplore`,
  `lower*/upper*` lon/lat params).

### Incident detail

- `get_incident(id)` → `v3/incident/{id}` (primary)
- `get_incident_v1(id)` → `v1/incident/{id}?with_stats&with_facepile`
- `get_incident_v2(id)` → `v2/incident/{id}?with_stats`
- `get_incidents(ids)` → `v1/incidents/batch`, deduped, chunked at 50 IDs
- `get_related_incidents(id)` → related/merged incident IDs
- `get_incident_content(id)` → web/image/stream attachments
- `get_incident_map_sources(id)` → raw map-source overlay data

### News & auxiliary

- `get_news_feed(code)` → `v2/news/feed` curated items (bucket + incident)
- `get_news_briefing(code)` → `v2/incidents/news_briefing`
- `get_chat_history(id, limit, before_chat_id, include_deleted, version=4)`
  → paginated read-only chat history
- `get_location_name(lat, lon)`, `search_locations(q, ...)`,
  `get_location(lat, lon)` — Citizen's own geocoding/safety endpoints
- `get_neighborhood_details(id)` → typed `NeighborhoodDetails`
- `get_neighborhood_incidents(id, category, lookback_days)` → `list[Incident]`
- `get_neighborhood_boundary(id)` → `NeighborhoodBoundary` (GeoJSON)
- `get_neighborhood_graph(id, category)` → raw time-series dict
- `get_neighborhood_feed(lat, lon)` → `NeighborhoodFeed` (shs_feed)
- `get_public_users(ids)` → `v1/users/batch_public` public profiles
- `check_username(name)` → availability `{allowed, reason}`
- `get_social_presence(ids)` → friend presence (lists empty w/o auth)
- `get_impact_statistics()` → `v1/protect/impact_statistics`
- `get_variable_settings()`, `health()`
- `client.get_json(path, params)` — escape hatch for unwrapped endpoints

### Feed tracking (`IncidentFeed`)

- Polls the tile endpoints for a bbox and diffs each update:
  `FeedUpdate(added, updated, removed)`.
- Deduplication by `incident_id`; change detection via a SHA-256
  fingerprint over tracked fields (title, categories, severity, level,
  lifecycle_state, recency_tier, timestamps, engagement counts, has_vod) —
  unrelated field churn cannot trigger false updates.
- Lifecycle tracking: `TrackedIncident.lifecycle_history` records every
  observed `reported → verified → developing → resolved/inactive`
  transition with timestamps; `first_seen`/`last_seen` retained.
- Graceful disappearance handling: incidents absent from tiles become
  `STALE` and are only `REMOVED` after `expire_after` seconds (default
  900), eliminating flap noise; a reappearing incident reactivates in
  place rather than re-adding.
- `active_only=True` filters to currently-active markers.

### Plumbing

- `aiohttp`-only runtime dependency; injectable `ClientSession` (HA-ready).
- Token-bucket `RateLimiter` (default 5 req/s, burst 5, 4 concurrent).
- `RetryPolicy`: 3 attempts, exponential backoff + jitter, honors
  `Retry-After`, retries 429/5xx and connection/timeouts.
- Typed error hierarchy: `CitizenError` → `CitizenConnectionError`,
  `CitizenTimeoutError`, `CitizenResponseError(status)` →
  `CitizenAuthError` (401/403), `CitizenNotFoundError` (404),
  `CitizenRateLimitError` (429); `CitizenParseError`/`CitizenTileError`.
- Optional `access_token` → `x-access-token` header for future use.
- Fully typed (`py.typed`), dataclass models, enums matching the app's
  DTO values, every model keeps the raw payload for forward compat.

## Verified API behavior (live, read-only)

Smoke-tested against `https://data.sp0n.io` on 2026-09-19:

| Call | Result |
|---|---|
| `health()` | 200 OK |
| `get_status(40.65, -74.0)` | `inServiceArea=true`, `serviceAreaCode=nyc`, `locationName="Sunset Park"` |
| `get_incident_markers(bbox)` | 68+ live markers, deduped across tiles; real titles/categories/severities/lifecycle states |
| `get_historical_incidents(bbox)` | 3 past-window incidents (time_frame, engagement counts) |
| `get_offender_markers(bbox)` | 112 registry markers with names/positions |
| `get_places(bbox)` | 17 neighborhood labels |
| `get_tile_style(name)` | full MapLibre styles incl. `cal-fire-*` sources |
| `get_incident(id)` (v3) | full detail incl. neighborhood, position, updates w/ radio clips |
| `get_incidents(ids)` (batch) | stats + update timelines (e.g. 290k views, 15 updates) |
| `get_related_incidents(id)` | related/merged IDs |
| `get_chat_history(id)` | real messages, `hasMore` pagination |
| `get_news_feed("nyc")` | 16 curated items with buckets |
| `get_news_briefing("nyc")` | 404 (none published — handled) |
| `get_neighborhood_*` | 200, currently empty payloads (endpoint verified) |
| `get_public_users(ids)` | 200 `{"results":[]}` |
| `check_username(name)` | 200 `{allowed, reason}` |
| `get_social_presence(ids)` | 200, presence lists empty without auth |
| `get_impact_statistics()` | real stats (174k premium users, 70 calls/week) |
| `IncidentFeed.update()` ×2 | markers tracked, second cycle zero-change diff |

All of the above with **no access token and no app-specific headers** —
a plain `pycitizen` User-Agent. See `examples/` for runnable proof of
every row.

## Test results

`pytest`: **98 passed, 0 failed** (~0.3s, fully offline).

- `test_tiles.py` — slippy math, real captured tile decode (10 features),
  synthetic-tile round-trip, geometry→lon/lat projection, malformed input.
- `test_models.py` — wire-shape parsing, enum mapping, timestamp formats.
- `test_client.py` — endpoint paths/params, batching/chunking, error
  mapping, retries, `Retry-After`, token header, session ownership.
- `test_feed.py` — add/update/remove diffs, stale→expire, reactivation,
  lifecycle history, fingerprint stability.
- `test_ratelimit.py` — burst, sustained rate, concurrency cap, backoff.
- `test_extended.py` — historical/offender/place tile models, users,
  usernames, social presence, impact stats, neighborhood trends.

`ruff check`: clean. `python -m build`: sdist + wheel OK
(`pycitizen-0.1.0`).

## Limitations & caveats

- **Private API, no stability guarantee.** Endpoints can change or be
  gated without notice; there is no versioning contract or deprecation
  policy.
- **Tile freshness is the only "real-time" channel.** The app refreshes
  incident data via tile refetches and status reloads; there is no public
  WebSocket/SSE/push channel for incidents. `IncidentFeed` is a poller.
  Traced map-refresh mechanics (`research/CITIZEN_API_REPORT.md` §8.1.1):
  the app has **no tile poll timer** — it re-sets the `all_incidents`
  source's `tiles` URL on camera-move end and filter changes, and relies
  on the tiles' `Cache-Control: public, max-age=60` expiry for idle
  freshness. `incidentPollingInterval` (15 s) is broadcast-session
  polling, not map polling.
- **Auth-gated endpoints excluded.** Homescreen feed/mapIncidents,
  `v1/search`, friends, `variable_settings`, user endpoints, and all
  mutations require a user token (phone-OTP). The WebSocket returns
  `auth required` unauthenticated.
- **Unverified response shapes** are returned raw (`map_sources`,
  `search_locations`, `get_location`, `neighborhood_graph`) rather than
  parsed into wrong models.
- **Geographic edge cases:** bboxes crossing the antimeridian must be
  split by the caller; tile coverage is clamped to Web-Mercator latitude.
- **`mapExplore` response parsing is heuristic** — it returns any list of
  strings found in the payload (observed as service-area codes).
- **Trend endpoints return 200 with empty bodies** for all tested
  neighborhood ids — real ids are issued by `shs_feed`, itself empty in
  tested areas. Typed parsers are in place for when data appears.
- **`social/batch` presence lists are empty without auth** — friends are
  an authenticated concept; the endpoint itself is public.
- **Tile resilience:** a transiently failing tile yields partial coverage
  rather than failing `get_*_markers` (tiles are re-fetched every poll).
- **Chat `createdAt` format** inferred from `DateDeserializer` in the
  app; both ISO strings and epoch numerics are accepted.
