"""Constants derived from the Citizen Android app (sp0n.citizen 0.1308.0).

All values were extracted from the decompiled APK. See the accompanying
reverse-engineering report for provenance details.
"""

from __future__ import annotations

from typing import Final

#: Base URL for all data endpoints (BuildConfigInfo.dataUrl).
API_BASE_URL: Final = "https://data.sp0n.io"

#: Base URL for static assets (BuildConfigInfo.assetsUrl).
ASSETS_BASE_URL: Final = "https://assets.citizen.com"

#: WebSocket endpoint used by chat / Protect features. Exposed for
#: documentation purposes only - it requires authentication and is not
#: used by this SDK.
WEBSOCKET_URL: Final = "wss://data.sp0n.io/websocket"

#: App user-agent prefix (R.string.app_prefix -> "Vigilante").
APP_USER_AGENT_PREFIX: Final = "Vigilante"

#: Header carrying the user's access token (NetworkingModule.addAuthHeaders).
HEADER_ACCESS_TOKEN: Final = "x-access-token"

#: Default User-Agent sent by this SDK.
DEFAULT_USER_AGENT: Final = "pycitizen/0.1.0 (+https://github.com/pycitizen/pycitizen)"

#: Endpoint paths (relative to API_BASE_URL).
ENDPOINT_HEALTH: Final = "healthz"
ENDPOINT_VARIABLE_SETTINGS: Final = "v1/variable_settings_anonymous"
ENDPOINT_STATUS: Final = "v1/homescreen/status"
ENDPOINT_MAP_EXPLORE: Final = "v1/homescreen/mapExplore"
ENDPOINT_INCIDENT_V1: Final = "v1/incident/{incident_id}"
ENDPOINT_INCIDENT_V2: Final = "v2/incident/{incident_id}"
ENDPOINT_INCIDENT_V3: Final = "v3/incident/{incident_id}"
ENDPOINT_INCIDENTS_BATCH: Final = "v1/incidents/batch"
ENDPOINT_INCIDENT_CONTENT: Final = "v1/incidents/{incident_id}/content"
ENDPOINT_INCIDENT_RELATED: Final = "v1/incidents/{incident_id}/related_incidents"
ENDPOINT_INCIDENT_MAP_SOURCES: Final = "v1/incidents/{incident_id}/map_sources"
ENDPOINT_NEWS_FEED: Final = "v2/news/feed"
ENDPOINT_NEWS_BRIEFING: Final = "v2/incidents/news_briefing"
ENDPOINT_CHAT_HISTORY_V1: Final = "v1/incident_chat/history"
ENDPOINT_CHAT_HISTORY_V4: Final = "v4/incident_chat/history"
ENDPOINT_LOCATION: Final = "v1/safety/location"
ENDPOINT_LOCATION_NAME: Final = "v1/safety/location_name"
ENDPOINT_LOCATION_SEARCH: Final = "v1/safety/location_search"
ENDPOINT_NEIGHBORHOOD_DETAILS: Final = "v1/trends/neighborhoods/{neighborhood_id}/details"
ENDPOINT_NEIGHBORHOOD_INCIDENTS: Final = "v1/trends/neighborhoods/{neighborhood_id}/incidents"
ENDPOINT_NEIGHBORHOOD_BOUNDARY: Final = "v1/trends/neighborhoods/{neighborhood_id}/boundary"
ENDPOINT_NEIGHBORHOOD_GRAPH: Final = "v1/trends/neighborhoods/{neighborhood_id}/graph"
ENDPOINT_TRENDS_FEED: Final = "v1/trends/shs_feed"
ENDPOINT_INCIDENT_TILE: Final = "v1/tile/incidents/{x}/{y}/{z}.pbf"
ENDPOINT_HISTORICAL_TILE: Final = "v1/tile/historical_incidents/{x}/{y}/{z}.pbf"
ENDPOINT_OFFENDER_TILE: Final = "v1/tile/offenders/{x}/{y}/{z}.pbf"
ENDPOINT_PLACES_TILE: Final = "v1/tile/places/{x}/{y}/{z}.pbf"
ENDPOINT_TILE_STYLE: Final = "v1/tile/style/{name}.json"
ENDPOINT_USERS_BATCH_PUBLIC: Final = "v1/users/batch_public"
ENDPOINT_CHECK_USERNAME: Final = "v1/users/check_username"
ENDPOINT_IMPACT_STATISTICS: Final = "v1/protect/impact_statistics"
ENDPOINT_SOCIAL_BATCH: Final = "v1/incidents/social/batch"

#: Map style documents the app ships with (MapTheme defaults).
TILE_STYLE_DARK: Final = "citizen-app-dark-20220303"
TILE_STYLE_LIGHT: Final = "citizen-app-light-20250512"
TILE_STYLE_ALL_LAYERS: Final = "citizen-incidents-offenders-wildfire-evac-all"

#: Maximum number of incident IDs accepted by the batch endpoint in one call.
#: The app joins IDs with commas; the server comfortably accepts ~50.
BATCH_INCIDENT_CHUNK_SIZE: Final = 50

#: Default tile zoom used for incident discovery. Zoom 12 covers a large
#: metro area in a handful of tiles; the app typically renders 10-15.
DEFAULT_TILE_ZOOM: Final = 12

#: MVT layer names inside the public vector tiles.
INCIDENTS_LAYER_NAME: Final = "incidents"
OFFENDERS_LAYER_NAME: Final = "offenders"
PLACES_LAYER_NAME: Final = "places"
