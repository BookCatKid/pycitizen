"""pycitizen - async Python SDK for Citizen's public incident API.

Reverse-engineered from Citizen Android 0.1308.0 (sp0n.citizen). Only
endpoints verified reachable without authentication are implemented.

Quick start::

    import asyncio
    from pycitizen import CitizenClient, IncidentFeed

    NYC = (-74.02, 40.70, -73.93, 40.80)  # west, south, east, north

    async def main() -> None:
        async with CitizenClient() as client:
            markers = await client.get_incident_markers(NYC)
            for m in markers:
                print(m.incident_id, m.title, m.severity.value)

    asyncio.run(main())
"""

from __future__ import annotations

from .client import BBox, CitizenClient
from .const import API_BASE_URL, DEFAULT_TILE_ZOOM, WEBSOCKET_URL
from .exceptions import (
    CitizenAuthError,
    CitizenConnectionError,
    CitizenError,
    CitizenNotFoundError,
    CitizenParseError,
    CitizenRateLimitError,
    CitizenResponseError,
    CitizenTileError,
    CitizenTimeoutError,
)
from .feed import FeedState, FeedUpdate, IncidentFeed, TrackedIncident
from .models import (
    ChatHistory,
    ChatMessage,
    HistoricalIncident,
    ImpactStatistics,
    Incident,
    IncidentContent,
    IncidentMarker,
    IncidentStats,
    IncidentUpdate,
    LifecycleState,
    NamedLocation,
    NeighborhoodBoundary,
    NeighborhoodDetails,
    NeighborhoodFeed,
    NewsBriefing,
    NewsItem,
    OffenderMarker,
    PlaceMarker,
    Position,
    PublicUser,
    SafetyStatus,
    Severity,
    SocialPresence,
    UsernameCheck,
)
from .ratelimit import RateLimiter, RetryPolicy
from .tiles import (
    VectorTile,
    VectorTileFeature,
    VectorTileLayer,
    decode_tile,
    lonlat_to_tile,
    tile_bounds,
    tiles_for_bbox,
)

__version__ = "0.1.0"

__all__ = [
    "API_BASE_URL",
    "DEFAULT_TILE_ZOOM",
    "WEBSOCKET_URL",
    "BBox",
    "ChatHistory",
    "ChatMessage",
    "CitizenAuthError",
    "CitizenClient",
    "CitizenConnectionError",
    "CitizenError",
    "CitizenNotFoundError",
    "CitizenParseError",
    "CitizenRateLimitError",
    "CitizenResponseError",
    "CitizenTileError",
    "CitizenTimeoutError",
    "FeedState",
    "FeedUpdate",
    "HistoricalIncident",
    "ImpactStatistics",
    "Incident",
    "IncidentContent",
    "IncidentFeed",
    "IncidentMarker",
    "IncidentStats",
    "IncidentUpdate",
    "LifecycleState",
    "NamedLocation",
    "NeighborhoodBoundary",
    "NeighborhoodDetails",
    "NeighborhoodFeed",
    "NewsBriefing",
    "NewsItem",
    "OffenderMarker",
    "PlaceMarker",
    "Position",
    "PublicUser",
    "RateLimiter",
    "RetryPolicy",
    "SafetyStatus",
    "Severity",
    "SocialPresence",
    "TrackedIncident",
    "UsernameCheck",
    "VectorTile",
    "VectorTileFeature",
    "VectorTileLayer",
    "__version__",
    "decode_tile",
    "lonlat_to_tile",
    "tile_bounds",
    "tiles_for_bbox",
]
