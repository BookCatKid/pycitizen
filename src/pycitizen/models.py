"""Data models for the Citizen incident API.

Field names and shapes are derived from the app's DTO classes
(``sp0n.citizen.data.incident.dto.*``) and from verified live responses.
Parsers are deliberately tolerant: Citizen's API omits null fields and has
evolved across v1/v2/v3 payloads, so every ``from_dict`` accepts partial
data and keeps the original payload in ``raw`` for forward compatibility.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "ChatHistory",
    "ChatMessage",
    "HistoricalIncident",
    "ImpactStatistics",
    "Incident",
    "IncidentContent",
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
    "SafetyStatus",
    "Severity",
    "SocialPresence",
    "UsernameCheck",
]


def _parse_ts(value: Any) -> datetime | None:
    """Parse a Citizen timestamp into an aware UTC datetime.

    Handles epoch seconds, epoch milliseconds, ISO-8601 strings and the
    app's ``"YYYY-MM-DD HH:MM:SS+TZ"`` format. Returns ``None`` for
    missing or unparseable values.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e12:  # milliseconds
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.replace(".", "", 1).lstrip("-").isdigit():
            return _parse_ts(float(text))
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v is not None]


class Severity(enum.Enum):
    """Incident severity, matching the app's SeverityLevelDTO.

    The enum ``value`` is the wire string (``"red"``, ``"yellow"``, ...).
    ``ranking`` mirrors the app's ordering: higher means more severe.
    ``is_active`` mirrors the app's ``active`` flag.
    """

    MAJOR_ACTIVE = "red"
    ACTIVE = "yellow"
    GOOD_NEWS = "green"
    INACTIVE = "grey"
    UNKNOWN = "unknown"

    @property
    def serialized(self) -> str:
        return self.value

    @property
    def ranking(self) -> int:
        return {
            Severity.MAJOR_ACTIVE: 3,
            Severity.ACTIVE: 2,
            Severity.GOOD_NEWS: 1,
            Severity.INACTIVE: 0,
            Severity.UNKNOWN: -1,
        }[self]

    @property
    def is_active(self) -> bool:
        return self in (Severity.MAJOR_ACTIVE, Severity.ACTIVE, Severity.GOOD_NEWS)

    @classmethod
    def from_value(cls, value: Any) -> Severity:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            for member in cls:
                if member.value == normalized or member.name.lower() == normalized:
                    return member
        # Numeric level fallback (v3 incidents carry an int "level").
        if isinstance(value, (int, float)):
            if value >= 3:
                return cls.MAJOR_ACTIVE
            if value == 2:
                return cls.ACTIVE
            if value == 1:
                return cls.GOOD_NEWS
            if value == 0:
                return cls.INACTIVE
        return cls.UNKNOWN


class LifecycleState(enum.Enum):
    """Incident lifecycle, matching the app's IncidentLifecycleStateDTO."""

    REPORTED = "reported"
    VERIFIED = "verified"
    DEVELOPING = "developing"
    RESOLVED = "resolved"
    INACTIVE = "inactive"
    ARCHIVED = "archived"
    UNKNOWN = "unknown"

    @property
    def is_open(self) -> bool:
        """True while the incident is still being worked/reported on."""
        return self in {
            LifecycleState.REPORTED,
            LifecycleState.VERIFIED,
            LifecycleState.DEVELOPING,
        }

    @classmethod
    def from_value(cls, value: Any) -> LifecycleState:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value.strip().lower())
            except ValueError:
                pass
        return cls.UNKNOWN


@dataclass(slots=True, frozen=True)
class Position:
    """A geographic coordinate."""

    latitude: float
    longitude: float


@dataclass(slots=True)
class IncidentStats:
    """Engagement counters (IncidentStatsDTO)."""

    views: int | None = None
    shares: int | None = None
    comments: int | None = None
    hearts: int | None = None
    whoas: int | None = None
    angers: int | None = None
    thanks: int | None = None
    clips_count: int | None = None
    streams_count: int | None = None
    stream_views: int | None = None
    confirmations: float | None = None
    users_notified: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> IncidentStats | None:
        if not isinstance(data, dict):
            return None
        return cls(
            views=_int(data.get("views")),
            shares=_int(data.get("shares")),
            comments=_int(data.get("chats") or data.get("comments")),
            hearts=_int(data.get("hearts")),
            whoas=_int(data.get("whoas")),
            angers=_int(data.get("angers")),
            thanks=_int(data.get("thanks")),
            clips_count=_int(data.get("clipsCount")),
            streams_count=_int(data.get("streamsCount")),
            stream_views=_int(data.get("streamViews")),
            confirmations=_float(data.get("nconfirmed")),
            users_notified=_int(data.get("usersNotifiedUnique")),
        )


@dataclass(slots=True)
class IncidentUpdate:
    """A chronological text/audio update on an incident (IncidentUpdateDTO)."""

    text: str | None = None
    timestamp: datetime | None = None
    uid: str | None = None
    radio_clips: list[dict[str, Any]] = field(default_factory=list)
    author: dict[str, Any] | None = None
    pinned: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IncidentUpdate:
        clips = data.get("source") or data.get("radioClips")
        return cls(
            text=data.get("text"),
            timestamp=_parse_ts(data.get("ts")),
            uid=data.get("uid") or data.get("id"),
            radio_clips=clips if isinstance(clips, list) else [],
            author=data.get("author") if isinstance(data.get("author"), dict) else None,
            pinned=data.get("pinned") if isinstance(data.get("pinned"), bool) else None,
            raw=data,
        )


@dataclass(slots=True)
class IncidentMarker:
    """A lightweight incident marker decoded from a vector tile.

    This is the cheapest incident representation - one tile fetch yields
    markers for every incident in a tile without per-incident requests.
    """

    incident_id: str
    title: str | None = None
    position: Position | None = None
    category: str | None = None
    categories: list[str] = field(default_factory=list)
    subcategory: str | None = None
    severity: Severity = Severity.UNKNOWN
    level: int | None = None
    lifecycle_state: LifecycleState = LifecycleState.UNKNOWN
    recency_tier: int | None = None
    timestamp: datetime | None = None
    created: datetime | None = None
    score: float | None = None
    comment_count: int | None = None
    share_count: int | None = None
    view_count: int | None = None
    has_vod: bool | None = None
    is_paywalled: bool | None = None
    unverified_community_alert: bool | None = None
    unverified_igl_incident: bool | None = None
    #: Tile coordinates (z/x/y) this marker was decoded from.
    tile: tuple[int, int, int] | None = None
    #: All decoded feature properties, for forward compatibility.
    properties: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_active(self) -> bool:
        """Best-effort active check from tile metadata."""
        if self.lifecycle_state is not LifecycleState.UNKNOWN:
            return self.lifecycle_state.is_open
        return self.severity.is_active

    @classmethod
    def from_properties(
        cls,
        props: dict[str, Any],
        *,
        tile: tuple[int, int, int] | None = None,
        fallback_position: Position | None = None,
    ) -> IncidentMarker | None:
        incident_id = props.get("incident_id")
        if incident_id is None:
            return None
        lat = _float(props.get("latitude"))
        lon = _float(props.get("longitude"))
        position = Position(lat, lon) if lat is not None and lon is not None else fallback_position
        return cls(
            incident_id=str(incident_id),
            title=props.get("title"),
            position=position,
            category=props.get("category"),
            categories=_str_list(props.get("categories")),
            subcategory=props.get("subcategory"),
            severity=Severity.from_value(props.get("severity")),
            level=_int(props.get("level")),
            lifecycle_state=LifecycleState.from_value(props.get("lifecycle_state")),
            recency_tier=_int(props.get("recency_tier")),
            timestamp=_parse_ts(props.get("ts")),
            created=_parse_ts(props.get("cs")),
            score=_float(props.get("incident_score")),
            comment_count=_int(props.get("comment_count")),
            share_count=_int(props.get("share_count")),
            view_count=_int(props.get("view_count")),
            has_vod=props.get("has_vod") if isinstance(props.get("has_vod"), bool) else None,
            is_paywalled=(
                props.get("is_paywalled") if isinstance(props.get("is_paywalled"), bool) else None
            ),
            unverified_community_alert=(
                props.get("unverified_community_alert")
                if isinstance(props.get("unverified_community_alert"), bool)
                else None
            ),
            unverified_igl_incident=(
                props.get("unverified_igl_incident")
                if isinstance(props.get("unverified_igl_incident"), bool)
                else None
            ),
            tile=tile,
            properties=dict(props),
        )


@dataclass(slots=True)
class Incident:
    """A full incident detail (unifies v1/v2/v3 response shapes)."""

    incident_id: str
    title: str | None = None
    position: Position | None = None
    location: str | None = None
    address: str | None = None
    neighborhood: str | None = None
    city_code: str | None = None
    category: str | None = None
    categories: list[str] = field(default_factory=list)
    subcategory: str | None = None
    severity: Severity = Severity.UNKNOWN
    level: int | None = None
    lifecycle_state: LifecycleState = LifecycleState.UNKNOWN
    timestamp: datetime | None = None
    created: datetime | None = None
    closed: bool | None = None
    confirmed: bool | None = None
    recency_tier: int | None = None
    has_vod: bool | None = None
    is_paywalled: bool | None = None
    chat_blocked: bool | None = None
    deleted: bool | None = None
    unverified_igl_incident: bool | None = None
    stats: IncidentStats | None = None
    updates: list[IncidentUpdate] = field(default_factory=list)
    map_thumbnail: str | None = None
    service_area: str | None = None
    location_details: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_active(self) -> bool:
        """Best-effort active check."""
        if self.lifecycle_state is not LifecycleState.UNKNOWN:
            return self.lifecycle_state.is_open
        if self.closed is not None:
            return not self.closed
        return self.severity.is_active

    @staticmethod
    def _position_from(data: dict[str, Any]) -> Position | None:
        pos = data.get("position")
        if isinstance(pos, dict):
            lat, lon = _float(pos.get("latitude")), _float(pos.get("longitude"))
            if lat is not None and lon is not None:
                return Position(lat, lon)
        lat, lon = _float(data.get("latitude")), _float(data.get("longitude"))
        if lat is not None and lon is not None:
            return Position(lat, lon)
        ll = data.get("ll") or data.get("latLon")
        if isinstance(ll, (list, tuple)) and len(ll) >= 2:
            lat, lon = _float(ll[0]), _float(ll[1])
            if lat is not None and lon is not None:
                return Position(lat, lon)
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Incident:
        incident_id = (
            data.get("incidentId") or data.get("key") or data.get("id") or data.get("incident_id")
        )
        updates_raw = data.get("updates")
        updates: list[IncidentUpdate] = []
        if isinstance(updates_raw, dict):
            updates = [
                IncidentUpdate.from_dict(u) for u in updates_raw.values() if isinstance(u, dict)
            ]
            updates.sort(key=lambda u: u.timestamp or datetime.min.replace(tzinfo=UTC))
        elif isinstance(updates_raw, list):
            updates = [IncidentUpdate.from_dict(u) for u in updates_raw if isinstance(u, dict)]

        severity = Severity.from_value(data.get("severity"))
        if severity is Severity.UNKNOWN:
            status = data.get("status")
            if isinstance(status, dict):
                severity = Severity.from_value(status.get("level"))
        if severity is Severity.UNKNOWN and data.get("level") is not None:
            severity = Severity.from_value(data.get("level"))

        return cls(
            incident_id=str(incident_id) if incident_id is not None else "",
            title=data.get("title"),
            position=cls._position_from(data),
            location=data.get("location"),
            address=data.get("address"),
            neighborhood=data.get("neighborhood"),
            city_code=data.get("cityCode"),
            category=data.get("category"),
            categories=_str_list(data.get("categories")),
            subcategory=data.get("subcategory"),
            severity=severity,
            level=_int(data.get("level")),
            lifecycle_state=LifecycleState.from_value(
                data.get("lifecycleState") or data.get("lifecycle_state")
            ),
            timestamp=_parse_ts(
                data.get("ts") or data.get("expandedAtMs") or data.get("createdAt")
            ),
            created=_parse_ts(data.get("cs")),
            closed=data.get("closed") if isinstance(data.get("closed"), bool) else None,
            confirmed=data.get("confirmed") if isinstance(data.get("confirmed"), bool) else None,
            recency_tier=_int(data.get("recencyTier")),
            has_vod=data.get("hasVod") if isinstance(data.get("hasVod"), bool) else None,
            is_paywalled=(
                data.get("isPaywalled") if isinstance(data.get("isPaywalled"), bool) else None
            ),
            chat_blocked=(
                data.get("chatBlocked") if isinstance(data.get("chatBlocked"), bool) else None
            ),
            deleted=data.get("deleted") if isinstance(data.get("deleted"), bool) else None,
            unverified_igl_incident=(
                data.get("unverifiedIGLIncident")
                if isinstance(data.get("unverifiedIGLIncident"), bool)
                else None
            ),
            stats=IncidentStats.from_dict(data.get("stats")),
            updates=updates,
            map_thumbnail=data.get("homescreenMapThumbnail") or data.get("mapThumbnail"),
            service_area=data.get("serviceArea"),
            location_details=(
                data.get("locationDetails")
                if isinstance(data.get("locationDetails"), dict)
                else None
            ),
            raw=data,
        )


@dataclass(slots=True)
class IncidentContent:
    """A piece of third-party/community content on an incident.

    The wire type is a list of content maps (web links, images, streams).
    """

    type: str | None = None
    url: str | None = None
    title: str | None = None
    thumbnail: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IncidentContent:
        return cls(
            type=data.get("type"),
            url=data.get("url") or data.get("link"),
            title=data.get("title") or data.get("name"),
            thumbnail=data.get("thumbnail") or data.get("image"),
            raw=data,
        )


@dataclass(slots=True)
class NewsItem:
    """An entry in the v2 news feed (IncidentAndBucketDTO)."""

    incident: Incident
    bucket: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NewsItem | None:
        incident = data.get("incident")
        if not isinstance(incident, dict):
            return None
        return cls(incident=Incident.from_dict(incident), bucket=data.get("bucket"))


@dataclass(slots=True)
class NewsBriefing:
    """A curated news briefing (NewsBriefingResponseDTO)."""

    briefing_id: str | None = None
    title: str | None = None
    subtitle: str | None = None
    incidents: list[Incident] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NewsBriefing:
        incidents = [
            Incident.from_dict(i)
            for i in data.get("incidents") or []
            if isinstance(i, dict)
        ]
        return cls(
            briefing_id=data.get("briefingId"),
            title=data.get("title"),
            subtitle=data.get("subtitle"),
            incidents=incidents,
        )


@dataclass(slots=True)
class ChatMessage:
    """An incident chat message (ChatDTO)."""

    message_id: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    message: str | None = None
    created: datetime | None = None
    likes: int | None = None
    is_nearby: bool | None = None
    is_deleted: bool | None = None
    parent_comment_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatMessage:
        return cls(
            message_id=data.get("id"),
            user_id=data.get("userId"),
            user_name=data.get("userName"),
            message=data.get("message") or data.get("messageRaw"),
            created=_parse_ts(data.get("createdAt") or data.get("cs")),
            likes=_int(data.get("likes")),
            is_nearby=data.get("isNearby") if isinstance(data.get("isNearby"), bool) else None,
            is_deleted=data.get("isDeleted") if isinstance(data.get("isDeleted"), bool) else None,
            parent_comment_id=data.get("parentCommentId"),
            raw=data,
        )


@dataclass(slots=True)
class ChatHistory:
    """A page of incident chat history (CommentsDTO + PaginationDTO)."""

    messages: list[ChatMessage] = field(default_factory=list)
    has_more: bool = False
    cursor: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatHistory:
        pagination = data.get("pagination") or {}
        return cls(
            messages=[
                ChatMessage.from_dict(m)
                for m in data.get("messages") or []
                if isinstance(m, dict)
            ],
            has_more=bool(pagination.get("hasMore")),
            cursor=pagination.get("id"),
        )


@dataclass(slots=True)
class SafetyStatus:
    """Service-area status for a coordinate (SafetyHomeStatusResponseDTO, v1)."""

    in_service_area: bool = False
    service_area_code: str | None = None
    service_area_name: str | None = None
    location_name: str | None = None
    past_hour_incidents: int | None = None
    nearby: dict[str, Any] | None = None
    sonar: dict[str, Any] | None = None
    map: dict[str, Any] | None = None
    offender: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SafetyStatus:
        return cls(
            in_service_area=bool(data.get("inServiceArea")),
            service_area_code=data.get("serviceAreaCode"),
            service_area_name=data.get("serviceAreaName"),
            location_name=data.get("locationName"),
            past_hour_incidents=_int(data.get("pastXHourIncidentsInServiceArea")),
            nearby=data.get("nearby") if isinstance(data.get("nearby"), dict) else None,
            sonar=data.get("sonar") if isinstance(data.get("sonar"), dict) else None,
            map=data.get("map") if isinstance(data.get("map"), dict) else None,
            offender=data.get("offender") if isinstance(data.get("offender"), dict) else None,
            raw=data,
        )


@dataclass(slots=True)
class NamedLocation:
    """A reverse-geocoded location (LocationNameDTO)."""

    location_name: str
    address: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NamedLocation:
        return cls(location_name=data.get("locationName") or "", address=data.get("address"))

@dataclass(slots=True)
class HistoricalIncident:
    """A past incident from the ``historical_incidents`` tile layer.

    Slimmer than a live marker: no severity/lifecycle/category, but adds
    ``time_frame`` (the window the incident belongs to).
    """

    incident_id: str
    title: str | None = None
    position: Position | None = None
    time_frame: str | None = None
    score: float | None = None
    comment_count: int | None = None
    share_count: int | None = None
    view_count: int | None = None
    is_paywalled: bool | None = None
    updated_at: datetime | None = None
    tile: tuple[int, int, int] | None = None
    properties: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_properties(
        cls,
        props: dict[str, Any],
        *,
        tile: tuple[int, int, int] | None = None,
        fallback_position: Position | None = None,
    ) -> HistoricalIncident | None:
        incident_id = props.get("incident_id")
        if incident_id is None:
            return None
        lat = _float(props.get("latitude"))
        lon = _float(props.get("longitude"))
        position = Position(lat, lon) if lat is not None and lon is not None else fallback_position
        return cls(
            incident_id=str(incident_id),
            title=props.get("title"),
            position=position,
            time_frame=props.get("incident_time_frame"),
            score=_float(props.get("incident_score")),
            comment_count=_int(props.get("comment_count")),
            share_count=_int(props.get("share_count")),
            view_count=_int(props.get("view_count")),
            is_paywalled=(
                props.get("is_paywalled") if isinstance(props.get("is_paywalled"), bool) else None
            ),
            updated_at=_parse_ts(props.get("updated_at")),
            tile=tile,
            properties=dict(props),
        )


@dataclass(slots=True)
class OffenderMarker:
    """A registered-offender map marker from the ``offenders`` tile layer."""

    offender_id: str
    position: Position | None = None
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    address: str | None = None
    charges: list[str] = field(default_factory=list)
    image_url: str | None = None
    show_full_name: bool | None = None
    updated_at: datetime | None = None
    tile: tuple[int, int, int] | None = None
    properties: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def display_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        name = " ".join(p for p in parts if p)
        return name or "Unknown"

    @classmethod
    def from_properties(
        cls,
        props: dict[str, Any],
        *,
        tile: tuple[int, int, int] | None = None,
        fallback_position: Position | None = None,
    ) -> OffenderMarker | None:
        offender_id = props.get("offender_id")
        if offender_id is None:
            return None
        lat = _float(props.get("latitude"))
        lon = _float(props.get("longitude"))
        position = Position(lat, lon) if lat is not None and lon is not None else fallback_position
        return cls(
            offender_id=str(offender_id),
            position=position,
            first_name=props.get("first_name"),
            middle_name=props.get("middle_name"),
            last_name=props.get("last_name"),
            address=props.get("address"),
            charges=_str_list(props.get("charges")),
            image_url=props.get("image_url"),
            show_full_name=(
                props.get("show_full_name")
                if isinstance(props.get("show_full_name"), bool)
                else None
            ),
            updated_at=_parse_ts(props.get("updated_at")),
            tile=tile,
            properties=dict(props),
        )


@dataclass(slots=True)
class PlaceMarker:
    """An OSM place label from the ``places`` tile layer."""

    place_id: str | None = None
    name: str | None = None
    type: str | None = None
    z_order: int | None = None
    position: Position | None = None
    properties: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_properties(
        cls,
        props: dict[str, Any],
        *,
        fallback_position: Position | None = None,
    ) -> PlaceMarker:
        return cls(
            place_id=str(props["id"]) if props.get("id") is not None else None,
            name=props.get("name"),
            type=props.get("type"),
            z_order=_int(props.get("z_order")),
            position=fallback_position,
            properties=dict(props),
        )


@dataclass(slots=True)
class PublicUser:
    """A public user profile (UserResponseDTO / PublicUserProfile)."""

    user_id: str | None = None
    username: str | None = None
    full_name: str | None = None
    short_name: str | None = None
    avatar_url: str | None = None
    avatar_thumb_url: str | None = None
    location: str | None = None
    mission: str | None = None
    joined: datetime | None = None
    is_private: bool | None = None
    total_friend_count: int | None = None
    total_streams: int | None = None
    total_stream_views: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PublicUser:
        return cls(
            user_id=data.get("id") or data.get("userId"),
            username=data.get("username"),
            full_name=data.get("fullName"),
            short_name=data.get("shortName"),
            avatar_url=data.get("avatarURL") or data.get("avatarUrl"),
            avatar_thumb_url=data.get("avatarThumbURL") or data.get("avatarThumbUrl"),
            location=data.get("location"),
            mission=data.get("mission"),
            joined=_parse_ts(data.get("joined")),
            is_private=data.get("private") if isinstance(data.get("private"), bool) else None,
            total_friend_count=_int(data.get("totalFriendCount")),
            total_streams=_int(data.get("totalStreams")),
            total_stream_views=_int(data.get("totalStreamViews")),
            raw=data,
        )


@dataclass(slots=True)
class UsernameCheck:
    """Result of ``GET /v1/users/check_username``."""

    allowed: bool = False
    reason: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsernameCheck:
        return cls(allowed=bool(data.get("allowed")), reason=data.get("reason"))


@dataclass(slots=True)
class ImpactStatistics:
    """Citizen Protect marketing stats (PremiumImpactStatisticsDTO)."""

    users_with_premium: int | None = None
    users_with_premium_subtitle: str | None = None
    calls_answered_past_week: int | None = None
    missing_found: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImpactStatistics:
        premium = data.get("usersWithPremium") or {}
        calls = data.get("agentImpactInPastWeek") or {}
        missing = data.get("missingPeopleAndPetsFound") or {}
        return cls(
            users_with_premium=_int(premium.get("numUsers")),
            users_with_premium_subtitle=premium.get("subtitle"),
            calls_answered_past_week=_int(calls.get("numCallsAnswered")),
            missing_found=_int(missing.get("numFound")),
            raw=data,
        )


@dataclass(slots=True)
class SocialPresence:
    """Friend-awareness data for an incident (IncidentFriendPresenceResponseDTO).

    Requires friends to populate - unauthenticated responses contain empty
    lists - but the endpoint itself is public.
    """

    incident_id: str | None = None
    aware: list[str] = field(default_factory=list)
    notification: list[str] = field(default_factory=list)
    view: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SocialPresence:
        presence = data.get("friendPresence") or {}
        return cls(
            incident_id=data.get("incidentId"),
            aware=_str_list(presence.get("aware")),
            notification=_str_list(presence.get("notification")),
            view=_str_list(presence.get("view")),
        )


@dataclass(slots=True)
class NeighborhoodBoundary:
    """Neighborhood boundary GeoJSON geometry (NeighborhoodBoundaryDTO)."""

    type: str | None = None
    coordinates: list[Any] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NeighborhoodBoundary:
        raw_geometry = data.get("geometry")
        geometry = raw_geometry if isinstance(raw_geometry, dict) else data
        return cls(
            type=geometry.get("type"),
            coordinates=geometry.get("coordinates") or [],
            raw=data,
        )


@dataclass(slots=True)
class NeighborhoodDetails:
    """Neighborhood crime-level summary (NeighborhoodDetailsDTO)."""

    name: str | None = None
    crime_level: str | None = None
    comparison_copy: str | None = None
    source: str | None = None
    last_updated: str | None = None
    stats_lookback_days: int | None = None
    stats: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NeighborhoodDetails:
        raw_stats = data.get("stats")
        return cls(
            name=data.get("name"),
            crime_level=data.get("crimeLevel"),
            comparison_copy=data.get("comparisonCopy"),
            source=data.get("source"),
            last_updated=data.get("lastUpdated"),
            stats_lookback_days=_int(data.get("statsLookbackPeriodInDays")),
            stats=(
                [s for s in raw_stats if isinstance(s, dict)]
                if isinstance(raw_stats, list)
                else []
            ),
            raw=data,
        )


@dataclass(slots=True)
class NeighborhoodFeed:
    """Trend feed entry for a location (NeighborhoodFeedDataDTO, shs_feed)."""

    neighborhood_id: str | None = None
    neighborhood_name: str | None = None
    key: str | None = None
    source: str | None = None
    last_updated: str | None = None
    graph_stats: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NeighborhoodFeed:
        return cls(
            neighborhood_id=data.get("neighborhoodId"),
            neighborhood_name=data.get("neighborhoodName"),
            key=data.get("key"),
            source=data.get("source"),
            last_updated=data.get("lastUpdated"),
            graph_stats=(
                data.get("graphStats") if isinstance(data.get("graphStats"), dict) else None
            ),
            raw=data,
        )
