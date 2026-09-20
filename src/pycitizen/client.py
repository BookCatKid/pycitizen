"""Async client for Citizen's public (unauthenticated) incident API.

All endpoints implemented here were verified reachable without an access
token against Citizen Android 0.1308.0 (see the accompanying report).
Endpoints that returned 401 in testing - homescreen feed/mapIncidents,
search, friends, variable_settings, WebSocket subscriptions - are
intentionally not implemented.

The client owns its aiohttp session unless one is injected (e.g. a Home
Assistant shared session). Rate limiting is applied to every request.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    BATCH_INCIDENT_CHUNK_SIZE,
    DEFAULT_TILE_ZOOM,
    DEFAULT_USER_AGENT,
    ENDPOINT_CHAT_HISTORY_V1,
    ENDPOINT_CHAT_HISTORY_V4,
    ENDPOINT_CHECK_USERNAME,
    ENDPOINT_HEALTH,
    ENDPOINT_HISTORICAL_TILE,
    ENDPOINT_IMPACT_STATISTICS,
    ENDPOINT_INCIDENT_CONTENT,
    ENDPOINT_INCIDENT_MAP_SOURCES,
    ENDPOINT_INCIDENT_RELATED,
    ENDPOINT_INCIDENT_TILE,
    ENDPOINT_INCIDENT_V1,
    ENDPOINT_INCIDENT_V2,
    ENDPOINT_INCIDENT_V3,
    ENDPOINT_INCIDENTS_BATCH,
    ENDPOINT_LOCATION,
    ENDPOINT_LOCATION_NAME,
    ENDPOINT_LOCATION_SEARCH,
    ENDPOINT_MAP_EXPLORE,
    ENDPOINT_NEIGHBORHOOD_BOUNDARY,
    ENDPOINT_NEIGHBORHOOD_DETAILS,
    ENDPOINT_NEIGHBORHOOD_GRAPH,
    ENDPOINT_NEIGHBORHOOD_INCIDENTS,
    ENDPOINT_NEWS_BRIEFING,
    ENDPOINT_NEWS_FEED,
    ENDPOINT_OFFENDER_TILE,
    ENDPOINT_PLACES_TILE,
    ENDPOINT_SOCIAL_BATCH,
    ENDPOINT_STATUS,
    ENDPOINT_TILE_STYLE,
    ENDPOINT_TRENDS_FEED,
    ENDPOINT_USERS_BATCH_PUBLIC,
    ENDPOINT_VARIABLE_SETTINGS,
    HEADER_ACCESS_TOKEN,
    INCIDENTS_LAYER_NAME,
    OFFENDERS_LAYER_NAME,
    PLACES_LAYER_NAME,
)
from .exceptions import (
    CitizenAuthError,
    CitizenConnectionError,
    CitizenNotFoundError,
    CitizenParseError,
    CitizenRateLimitError,
    CitizenResponseError,
    CitizenTimeoutError,
)
from .models import (
    ChatHistory,
    HistoricalIncident,
    ImpactStatistics,
    Incident,
    IncidentContent,
    IncidentMarker,
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
    SocialPresence,
    UsernameCheck,
)
from .ratelimit import RateLimiter, RetryPolicy
from .tiles import decode_tile, tiles_for_bbox

__all__ = ["CitizenClient"]

BBox = tuple[float, float, float, float]  # (west, south, east, north)


class CitizenClient:
    """Async client for Citizen's public incident endpoints.

    Parameters
    ----------
    session:
        Optional externally-managed ``aiohttp.ClientSession``. When
        omitted, the client creates (and owns) its own session.
    base_url:
        API host override (testing/staging).
    access_token:
        Optional Citizen user token, sent as ``x-access-token``. Not
        required for any endpoint exposed by this SDK.
    timeout:
        Per-request total timeout in seconds.
    rate_limiter / retry_policy:
        Override the default token-bucket limiter (5 req/s, burst 5,
        4 concurrent) or retry policy (3 attempts, exponential backoff,
        honors Retry-After).
    user_agent / headers:
        Extra/override request headers.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        *,
        base_url: str = API_BASE_URL,
        access_token: str | None = None,
        timeout: float = 10.0,
        rate_limiter: RateLimiter | None = None,
        retry_policy: RetryPolicy | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._session = session
        self._owns_session = session is None
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._limiter = rate_limiter or RateLimiter()
        self._retry = retry_policy or RetryPolicy()
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        if headers:
            self._headers.update(headers)

    async def __aenter__(self) -> CitizenClient:
        await self._ensure_session()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the internally-managed session (a no-op for injected ones)."""
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    @property
    def closed(self) -> bool:
        return self._session is None or self._session.closed

    def _request_headers(self) -> dict[str, str]:
        headers = dict(self._headers)
        if self._access_token:
            headers[HEADER_ACCESS_TOKEN] = self._access_token
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, bytes, str]:
        """Perform a rate-limited, retried request.

        Returns ``(status, body, content_type)``. Raises a typed
        ``CitizenError`` subclass on failure.
        """
        session = await self._ensure_session()
        url = f"{self._base_url}/{path.lstrip('/')}"
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}

        last_error: Exception | None = None
        last_status: int | None = None
        for attempt in range(self._retry.max_attempts):
            try:
                await self._limiter.acquire()
                try:
                    resp_ctx = session.request(
                        method,
                        url,
                        params=clean_params,
                        headers=self._request_headers(),
                    )
                    async with resp_ctx as resp:
                        status = resp.status
                        body = await resp.read()
                        content_type = resp.headers.get("Content-Type", "")
                finally:
                    self._limiter.release()

                if status in self._retry.retry_statuses and attempt < self._retry.max_attempts - 1:
                    last_status = status
                    retry_after = None
                    try:
                        retry_after = float(resp.headers.get("Retry-After", "")) or None
                    except (TypeError, ValueError):
                        retry_after = None
                    await asyncio.sleep(
                        self._retry.delay_for(attempt, retry_after=retry_after)
                    )
                    continue

                if status in (401, 403):
                    raise CitizenAuthError(
                        f"{method} {url} requires authentication", status=status
                    )
                if status == 404:
                    raise CitizenNotFoundError(f"{method} {url} not found", status=status)
                if status == 429:
                    raise CitizenRateLimitError(f"{method} {url} rate limited")
                if not 200 <= status < 300:
                    raise CitizenResponseError(
                        f"{method} {url} returned HTTP {status}", status=status
                    )
                return status, body, content_type

            except (CitizenAuthError, CitizenNotFoundError, CitizenResponseError):
                raise
            except TimeoutError as exc:
                last_error = CitizenTimeoutError(f"{method} {url} timed out")
                last_error.__cause__ = exc
            except aiohttp.ClientError as exc:
                last_error = CitizenConnectionError(f"{method} {url} failed: {exc}")
                last_error.__cause__ = exc

            if attempt < self._retry.max_attempts - 1:
                await asyncio.sleep(self._retry.delay_for(attempt))

        if last_error is not None:
            raise last_error
        if last_status == 429:
            raise CitizenRateLimitError(f"{method} {url} rate limited")
        if last_status is not None:
            raise CitizenResponseError(
                f"{method} {url} returned HTTP {last_status}", status=last_status
            )
        raise CitizenConnectionError(f"{method} {url} failed") from last_error

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Low-level GET returning decoded JSON (escape hatch)."""
        _, body, _ = await self._request("GET", path, params=params)
        if not body.strip():
            return None  # several open endpoints return 200 with empty bodies
        try:
            return json.loads(body)
        except ValueError as exc:
            raise CitizenParseError(f"GET {path} returned invalid JSON") from exc

    async def _get_bytes(
        self, path: str, params: dict[str, Any] | None = None
    ) -> bytes:
        _, body, _ = await self._request("GET", path, params=params)
        return body

    # ------------------------------------------------------------------
    # Health / settings
    # ------------------------------------------------------------------

    async def health(self) -> bool:
        """True if the API host responds (GET /healthz)."""
        status, _, _ = await self._request("GET", ENDPOINT_HEALTH)
        return 200 <= status < 300

    async def get_variable_settings(self) -> dict[str, Any]:
        """Anonymous remote config flags (v1/variable_settings_anonymous)."""
        data = await self.get_json(ENDPOINT_VARIABLE_SETTINGS)
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # Geographic discovery
    # ------------------------------------------------------------------

    async def get_status(self, latitude: float, longitude: float) -> SafetyStatus:
        """Service-area status for a coordinate (v1/homescreen/status)."""
        data = await self.get_json(
            ENDPOINT_STATUS, params={"lat": latitude, "long": longitude}
        )
        return SafetyStatus.from_dict(data if isinstance(data, dict) else {})

    async def get_service_areas(self, bbox: BBox) -> list[str]:
        """Service-area codes overlapping a bbox (v1/homescreen/mapExplore)."""
        west, south, east, north = bbox
        data = await self.get_json(
            ENDPOINT_MAP_EXPLORE,
            params={
                "lowerLongitude": west,
                "lowerLatitude": south,
                "upperLongitude": east,
                "upperLatitude": north,
            },
        )
        areas: list[str] = []
        candidates: Any = data
        if isinstance(data, dict):
            for key in ("serviceAreas", "service_areas", "areas", "codes"):
                if isinstance(data.get(key), list):
                    candidates = data[key]
                    break
            else:
                candidates = next(
                    (v for v in data.values() if isinstance(v, list)), []
                )
        if isinstance(candidates, list):
            areas = [str(a) for a in candidates if a is not None]
        return areas

    async def _tile_features(
        self,
        endpoint_template: str,
        layer_name: str,
        bbox: BBox,
        zoom: int,
        params: dict[str, Any] | None = None,
    ) -> list[tuple[dict[str, Any], Position | None, tuple[int, int, int]]]:
        """Fetch and decode every feature of ``layer_name`` in a bbox.

        Returns ``(properties, fallback_position, (z, x, y))`` triples.
        Missing tiles (404) are treated as empty.
        """
        west, south, east, north = bbox
        tiles = list(tiles_for_bbox(west, south, east, north, zoom))

        async def fetch(
            z: int, x: int, y: int
        ) -> list[tuple[dict[str, Any], Position | None, tuple[int, int, int]]]:
            try:
                data = await self._get_bytes(
                    endpoint_template.format(x=x, y=y, z=z), params=params
                )
            except CitizenNotFoundError:
                return []  # tiles with no coverage may 404; treat as empty
            except (CitizenTimeoutError, CitizenConnectionError):
                return []  # transient tile failure -> partial coverage, retried next poll
            layer = decode_tile(data).layer(layer_name)
            if layer is None:
                return []
            return [
                (f.properties, f.position(x, y, z, extent=layer.extent), (z, x, y))
                for f in layer.features
            ]

        results = await asyncio.gather(*(fetch(z, x, y) for z, x, y in tiles))
        return [item for result in results for item in result]

    @staticmethod
    def _clip(
        items: list[Any], bbox: BBox
    ) -> list[Any]:
        west, south, east, north = bbox
        return [
            item
            for item in items
            if item.position is None
            or (
                west <= item.position.longitude <= east
                and south <= item.position.latitude <= north
            )
        ]

    async def get_incident_markers(
        self,
        bbox: BBox,
        *,
        zoom: int = DEFAULT_TILE_ZOOM,
        clip_to_bbox: bool = True,
        categories: list[str] | None = None,
        created_gte: datetime | str | None = None,
        created_lte: datetime | str | None = None,
        limit: int | None = None,
        active_definition: str | None = None,
        with_lifecycle_state: bool | None = None,
    ) -> list[IncidentMarker]:
        """Fetch all live incident markers in a bbox via vector tiles.

        One request per covering tile (concurrency-bounded). Markers are
        deduplicated across tile edges and, when ``clip_to_bbox`` is set,
        filtered to the requested bounding box. Sorted newest-first.

        Optional filters mirror the query parameters the official app
        appends to the tile URL (verified functional server-side):
        ``incident_category`` (repeatable), ``incident_created_at_gte/lte``
        (ISO-8601, from ``datetime`` or string), ``limit`` (per-tile cap),
        ``active_definition`` (the app sends ``"state_based"``) and
        ``with_lifecycle_state`` (the app sends ``"true"``).
        """
        params: dict[str, Any] = {}
        if categories:
            params["incident_category"] = list(categories)
        if created_gte is not None:
            params["incident_created_at_gte"] = _iso(created_gte)
        if created_lte is not None:
            params["incident_created_at_lte"] = _iso(created_lte)
        if limit is not None:
            params["limit"] = limit
        if active_definition is not None:
            params["active_definition"] = active_definition
        if with_lifecycle_state is not None:
            params["with_lifecycle_state"] = (
                "true" if with_lifecycle_state else "false"
            )
        features = await self._tile_features(
            ENDPOINT_INCIDENT_TILE,
            INCIDENTS_LAYER_NAME,
            bbox,
            zoom,
            params=params or None,
        )
        seen: dict[str, IncidentMarker] = {}
        for props, fallback, tile_coords in features:
            marker = IncidentMarker.from_properties(
                props, tile=tile_coords, fallback_position=fallback
            )
            if marker is not None:
                seen.setdefault(marker.incident_id, marker)
        out = list(seen.values())
        if clip_to_bbox:
            out = self._clip(out, bbox)
        out.sort(key=lambda m: m.timestamp or m.created or _EPOCH, reverse=True)
        return out

    async def get_historical_incidents(
        self,
        bbox: BBox,
        *,
        zoom: int = DEFAULT_TILE_ZOOM,
        clip_to_bbox: bool = True,
    ) -> list[HistoricalIncident]:
        """Fetch historical (past-window) incidents in a bbox.

        Uses the ``historical_incidents`` tile layer the app renders for
        older incidents. Deduplicated across tile edges.
        """
        features = await self._tile_features(
            ENDPOINT_HISTORICAL_TILE, INCIDENTS_LAYER_NAME, bbox, zoom
        )
        seen: dict[str, HistoricalIncident] = {}
        for props, fallback, tile_coords in features:
            item = HistoricalIncident.from_properties(
                props, tile=tile_coords, fallback_position=fallback
            )
            if item is not None:
                seen.setdefault(item.incident_id, item)
        out = list(seen.values())
        if clip_to_bbox:
            out = self._clip(out, bbox)
        out.sort(key=lambda h: h.updated_at or _EPOCH, reverse=True)
        return out

    async def get_offender_markers(
        self,
        bbox: BBox,
        *,
        zoom: int = DEFAULT_TILE_ZOOM,
        clip_to_bbox: bool = True,
    ) -> list[OffenderMarker]:
        """Fetch registered-offender map markers in a bbox."""
        features = await self._tile_features(
            ENDPOINT_OFFENDER_TILE, OFFENDERS_LAYER_NAME, bbox, zoom
        )
        seen: dict[str, OffenderMarker] = {}
        for props, fallback, tile_coords in features:
            item = OffenderMarker.from_properties(
                props, tile=tile_coords, fallback_position=fallback
            )
            if item is not None:
                seen.setdefault(item.offender_id, item)
        out = list(seen.values())
        if clip_to_bbox:
            out = self._clip(out, bbox)
        return out

    async def get_places(
        self,
        bbox: BBox,
        *,
        zoom: int = DEFAULT_TILE_ZOOM,
        clip_to_bbox: bool = True,
    ) -> list[PlaceMarker]:
        """Fetch OSM place labels (town/suburb/neighbourhood) in a bbox."""
        features = await self._tile_features(
            ENDPOINT_PLACES_TILE, PLACES_LAYER_NAME, bbox, zoom
        )
        seen: set[tuple[str | None, str | None]] = set()
        out: list[PlaceMarker] = []
        for props, fallback, _tile_coords in features:
            place = PlaceMarker.from_properties(props, fallback_position=fallback)
            key = (place.name, place.type)
            if key not in seen:
                seen.add(key)
                out.append(place)
        if clip_to_bbox:
            out = self._clip(out, bbox)
        out.sort(key=lambda p: p.z_order or 0)
        return out

    async def get_tile_style(self, name: str) -> dict[str, Any]:
        """Fetch a MapLibre style document (e.g. ``citizen-app-dark-20220303``).

        Style names are defined in the app as ``pycitizen.const.TILE_STYLE_*``.
        """
        data = await self.get_json(ENDPOINT_TILE_STYLE.format(name=name))
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # Incidents
    # ------------------------------------------------------------------

    async def get_incident(self, incident_id: str) -> Incident:
        """Incident detail via the v3 endpoint (v3/incident/{id})."""
        data = await self.get_json(ENDPOINT_INCIDENT_V3.format(incident_id=incident_id))
        return Incident.from_dict(data if isinstance(data, dict) else {})

    async def get_incident_v1(self, incident_id: str) -> Incident:
        """Incident detail via v1 (richer: updates, stats, facepile)."""
        data = await self.get_json(
            ENDPOINT_INCIDENT_V1.format(incident_id=incident_id),
            params={"with_stats": "true", "with_facepile": "true"},
        )
        return Incident.from_dict(data if isinstance(data, dict) else {})

    async def get_incident_v2(self, incident_id: str) -> Incident:
        """Incident detail via the v2 endpoint."""
        data = await self.get_json(
            ENDPOINT_INCIDENT_V2.format(incident_id=incident_id),
            params={"with_stats": "true"},
        )
        return Incident.from_dict(data if isinstance(data, dict) else {})

    async def get_incidents(self, incident_ids: Iterable[str]) -> list[Incident]:
        """Batch incident detail (v1/incidents/batch), chunked at 50 IDs."""
        ids = [str(i) for i in dict.fromkeys(incident_ids)]
        out: list[Incident] = []
        for i in range(0, len(ids), BATCH_INCIDENT_CHUNK_SIZE):
            chunk = ids[i : i + BATCH_INCIDENT_CHUNK_SIZE]
            data = await self.get_json(
                ENDPOINT_INCIDENTS_BATCH,
                params={
                    "incident_ids": ",".join(chunk),
                    "with_stats": "true",
                    "with_facepile": "true",
                    "with_radio_clips": "true",
                },
            )
            if isinstance(data, list):
                out.extend(Incident.from_dict(d) for d in data if isinstance(d, dict))
            elif isinstance(data, dict):
                for key in ("incidents", "results"):
                    if isinstance(data.get(key), list):
                        out.extend(
                            Incident.from_dict(d) for d in data[key] if isinstance(d, dict)
                        )
                        break
        return out

    async def get_related_incidents(self, incident_id: str) -> list[str]:
        """IDs of related/merged incidents."""
        data = await self.get_json(
            ENDPOINT_INCIDENT_RELATED.format(incident_id=incident_id)
        )
        related = data.get("relatedIncidents") if isinstance(data, dict) else None
        return [str(r) for r in related or [] if r is not None]

    async def get_incident_content(self, incident_id: str) -> list[IncidentContent]:
        """Community/third-party content attached to an incident."""
        data = await self.get_json(
            ENDPOINT_INCIDENT_CONTENT.format(incident_id=incident_id),
            params={"with_stats": "true", "blocked": "false"},
        )
        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = [d for d in data if isinstance(d, dict)]
        elif isinstance(data, dict):
            for value in data.values():
                if isinstance(value, list):
                    items.extend(d for d in value if isinstance(d, dict))
                elif isinstance(value, dict):
                    items.append(value)
        return [IncidentContent.from_dict(i) for i in items]

    async def get_incident_map_sources(self, incident_id: str) -> dict[str, Any]:
        """Map source overlays for an incident (shape varies; returned raw)."""
        data = await self.get_json(
            ENDPOINT_INCIDENT_MAP_SOURCES.format(incident_id=incident_id)
        )
        return data if isinstance(data, dict) else {"sources": data}

    # ------------------------------------------------------------------
    # News
    # ------------------------------------------------------------------

    async def get_news_feed(self, service_area_code: str | None = None) -> list[NewsItem]:
        """Curated news feed for a service area (v2/news/feed)."""
        params = {"code": service_area_code} if service_area_code else None
        data = await self.get_json(ENDPOINT_NEWS_FEED, params=params)
        items = data.get("news") if isinstance(data, dict) else data
        return [
            item
            for entry in items or []
            if isinstance(entry, dict) and (item := NewsItem.from_dict(entry)) is not None
        ]

    async def get_news_briefing(self, service_area_code: str) -> NewsBriefing:
        """Latest generated news briefing for a service area."""
        data = await self.get_json(
            ENDPOINT_NEWS_BRIEFING, params={"service_area": service_area_code}
        )
        return NewsBriefing.from_dict(data if isinstance(data, dict) else {})

    # ------------------------------------------------------------------
    # Chat history (read-only)
    # ------------------------------------------------------------------

    async def get_chat_history(
        self,
        incident_id: str,
        *,
        limit: int | None = None,
        before_chat_id: str | None = None,
        include_deleted: bool = False,
        version: int = 4,
    ) -> ChatHistory:
        """One page of incident chat history (v4 by default, v1 fallback)."""
        endpoint = ENDPOINT_CHAT_HISTORY_V4 if version == 4 else ENDPOINT_CHAT_HISTORY_V1
        data = await self.get_json(
            endpoint,
            params={
                "incident_id": incident_id,
                "limit": limit,
                "before_chat_id": before_chat_id,
                "include_deleted": "true" if include_deleted else None,
            },
        )
        return ChatHistory.from_dict(data if isinstance(data, dict) else {})

    # ------------------------------------------------------------------
    # Location helpers
    # ------------------------------------------------------------------

    async def get_location_name(self, latitude: float, longitude: float) -> NamedLocation:
        """Reverse-geocode a coordinate to a Citizen location name."""
        data = await self.get_json(
            ENDPOINT_LOCATION_NAME,
            params={"lat": str(latitude), "long": str(longitude)},
        )
        return NamedLocation.from_dict(data if isinstance(data, dict) else {})

    async def search_locations(
        self,
        query: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        service_area_code: str | None = None,
    ) -> Any:
        """Place search (v1/safety/location_search); returns raw JSON."""
        return await self.get_json(
            ENDPOINT_LOCATION_SEARCH,
            params={
                "q": query,
                "lat": latitude,
                "long": longitude,
                "code": service_area_code,
            },
        )

    async def get_location(self, latitude: float, longitude: float) -> Any:
        """Full safety location record for a coordinate (raw JSON)."""
        return await self.get_json(
            ENDPOINT_LOCATION, params={"lat": latitude, "long": longitude}
        )

    # ------------------------------------------------------------------
    # Users & social (public surface)
    # ------------------------------------------------------------------

    async def get_public_users(self, user_ids: Iterable[str]) -> list[PublicUser]:
        """Public profile records for user IDs (v1/users/batch_public)."""
        ids = [str(i) for i in dict.fromkeys(user_ids)]
        data = await self.get_json(
            ENDPOINT_USERS_BATCH_PUBLIC, params={"ids": ",".join(ids)}
        )
        results = data.get("results") if isinstance(data, dict) else data
        return [PublicUser.from_dict(u) for u in results or [] if isinstance(u, dict)]

    async def check_username(self, username: str) -> UsernameCheck:
        """Check whether a username is available (v1/users/check_username)."""
        data = await self.get_json(ENDPOINT_CHECK_USERNAME, params={"username": username})
        return UsernameCheck.from_dict(data if isinstance(data, dict) else {})

    async def get_social_presence(
        self, incident_ids: Iterable[str], *, include: str | None = None
    ) -> list[SocialPresence]:
        """Friend presence for incidents (v1/incidents/social/batch).

        The endpoint is public but ``aware``/``notification``/``view`` lists
        are only populated for an authenticated user's friends.
        """
        ids = [str(i) for i in dict.fromkeys(incident_ids)]
        data = await self.get_json(
            ENDPOINT_SOCIAL_BATCH,
            params={"incident_ids": ",".join(ids), "include": include},
        )
        items = data if isinstance(data, list) else []
        return [SocialPresence.from_dict(i) for i in items if isinstance(i, dict)]

    async def get_impact_statistics(self) -> ImpactStatistics:
        """Citizen Protect marketing/impact stats (v1/protect/impact_statistics)."""
        data = await self.get_json(ENDPOINT_IMPACT_STATISTICS)
        return ImpactStatistics.from_dict(data if isinstance(data, dict) else {})

    # ------------------------------------------------------------------
    # Neighborhood trends
    # ------------------------------------------------------------------

    async def get_neighborhood_details(self, neighborhood_id: str) -> NeighborhoodDetails:
        """Neighborhood crime-level summary (v1/trends/neighborhoods/{id}/details)."""
        data = await self.get_json(
            ENDPOINT_NEIGHBORHOOD_DETAILS.format(neighborhood_id=neighborhood_id)
        )
        return NeighborhoodDetails.from_dict(data if isinstance(data, dict) else {})

    async def get_neighborhood_incidents(
        self,
        neighborhood_id: str,
        *,
        category: str | None = None,
        lookback_days: int | None = None,
    ) -> list[Incident]:
        """Incidents in a neighborhood trend view (List<IncidentDTO>)."""
        data = await self.get_json(
            ENDPOINT_NEIGHBORHOOD_INCIDENTS.format(neighborhood_id=neighborhood_id),
            params={"category": category, "lookback": lookback_days},
        )
        items = data if isinstance(data, list) else []
        return [Incident.from_dict(i) for i in items if isinstance(i, dict)]

    async def get_neighborhood_boundary(self, neighborhood_id: str) -> NeighborhoodBoundary:
        """GeoJSON boundary geometry for a neighborhood."""
        data = await self.get_json(
            ENDPOINT_NEIGHBORHOOD_BOUNDARY.format(neighborhood_id=neighborhood_id)
        )
        return NeighborhoodBoundary.from_dict(data if isinstance(data, dict) else {})

    async def get_neighborhood_graph(
        self, neighborhood_id: str, *, category: str | None = None
    ) -> dict[str, Any]:
        """Time-series stats per category (raw; shape: {source, stats})."""
        data = await self.get_json(
            ENDPOINT_NEIGHBORHOOD_GRAPH.format(neighborhood_id=neighborhood_id),
            params={"category": category},
        )
        return data if isinstance(data, dict) else {}

    async def get_neighborhood_feed(
        self, latitude: float, longitude: float
    ) -> NeighborhoodFeed:
        """Trend feed entry for a coordinate (v1/trends/shs_feed)."""
        data = await self.get_json(
            ENDPOINT_TRENDS_FEED, params={"lat": latitude, "long": longitude}
        )
        return NeighborhoodFeed.from_dict(data if isinstance(data, dict) else {})


_EPOCH = datetime.fromtimestamp(0, tz=UTC)


def _iso(value: datetime | str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return value
