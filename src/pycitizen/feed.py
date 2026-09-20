"""Incident feed tracker: deduplication, change detection, lifecycle tracking.

``IncidentFeed`` is the polling primitive a Home Assistant integration (or
any long-running consumer) would wrap in a coordinator. Each ``update()``
fetches the incident markers currently inside a bounding box, diffs them
against the tracked set, and returns exactly what changed.

An incident that disappears from the tiles is retained for
``expire_after`` seconds (marked via :attr:`TrackedIncident.state`) so
short-lived flapping does not produce remove/add noise; incident data is
often still retrievable via the detail endpoints after it leaves the map.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .const import DEFAULT_TILE_ZOOM
from .models import IncidentMarker, LifecycleState

if TYPE_CHECKING:
    from .client import BBox, CitizenClient

__all__ = ["FeedState", "FeedUpdate", "IncidentFeed", "TrackedIncident"]

#: Marker fields participating in change detection.
_TRACKED_FIELDS = (
    "title",
    "category",
    "subcategory",
    "severity",
    "level",
    "lifecycle_state",
    "recency_tier",
    "timestamp",
    "comment_count",
    "share_count",
    "view_count",
    "has_vod",
)


def _marker_fingerprint(marker: IncidentMarker) -> str:
    """Stable hash of the fields that constitute a meaningful change."""
    payload: dict[str, Any] = {}
    for name in _TRACKED_FIELDS:
        value = getattr(marker, name, None)
        if isinstance(value, enum.Enum):
            value = value.value
        elif isinstance(value, datetime):
            value = value.isoformat()
        payload[name] = value
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class FeedState(enum.Enum):
    """Tracking state of an incident in the feed."""

    NEW = "new"  #: seen for the first time in the latest update
    ACTIVE = "active"  #: present in the latest update
    UPDATED = "updated"  #: present, but tracked fields changed
    STALE = "stale"  #: absent from tiles but within the retention window
    REMOVED = "removed"  #: absent past the retention window (or feed cleared)


@dataclass(slots=True)
class TrackedIncident:
    """An incident marker plus its observation history."""

    marker: IncidentMarker
    first_seen: datetime
    last_seen: datetime
    state: FeedState = FeedState.NEW
    fingerprint: str = ""
    #: Ordered (timestamp, lifecycle_state) transitions observed.
    lifecycle_history: list[tuple[datetime, LifecycleState]] = field(default_factory=list)

    @property
    def incident_id(self) -> str:
        return self.marker.incident_id

    def observe(self, marker: IncidentMarker, now: datetime) -> bool:
        """Fold a new observation in; returns True if tracked fields changed."""
        changed = _marker_fingerprint(marker) != self.fingerprint
        if changed:
            self.fingerprint = _marker_fingerprint(marker)
            self.state = FeedState.UPDATED
            if marker.lifecycle_state != self.marker.lifecycle_state:
                self.lifecycle_history.append((now, marker.lifecycle_state))
        else:
            self.state = FeedState.ACTIVE
        self.marker = marker
        self.last_seen = now
        return changed


@dataclass(slots=True)
class FeedUpdate:
    """Result of one feed refresh."""

    #: Incidents seen for the first time.
    added: list[TrackedIncident] = field(default_factory=list)
    #: Incidents whose tracked fields changed since last update.
    updated: list[TrackedIncident] = field(default_factory=list)
    #: Incidents that expired out of the feed since last update.
    removed: list[TrackedIncident] = field(default_factory=list)
    #: Monotonic sequence number of this update.
    sequence: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


class IncidentFeed:
    """Polls Citizen incident tiles for a bbox and tracks the incident set.

    Parameters
    ----------
    client:
        A :class:`~pycitizen.CitizenClient` instance.
    bbox:
        ``(west, south, east, north)`` lon/lat bounds to watch.
    zoom:
        Tile zoom for discovery (default 12).
    active_only:
        If True, markers that are inactive (lifecycle resolved/inactive or
        grey severity) are not tracked.
    expire_after:
        Seconds to keep an incident after it disappears from the tiles.
    """

    def __init__(
        self,
        client: CitizenClient,
        bbox: BBox,
        *,
        zoom: int = DEFAULT_TILE_ZOOM,
        active_only: bool = False,
        expire_after: float = 900.0,
    ) -> None:
        self._client = client
        self.bbox = bbox
        self.zoom = zoom
        self.active_only = active_only
        self.expire_after = expire_after
        self._incidents: dict[str, TrackedIncident] = {}
        self._sequence = 0
        self._last_update: datetime | None = None

    @property
    def incidents(self) -> dict[str, TrackedIncident]:
        """All tracked incidents, keyed by incident id."""
        return self._incidents

    @property
    def last_update(self) -> datetime | None:
        return self._last_update

    def active_incidents(self) -> list[TrackedIncident]:
        """Tracked incidents currently reported by the tiles."""
        active = (FeedState.ACTIVE, FeedState.UPDATED, FeedState.NEW)
        return [t for t in self._incidents.values() if t.state in active]

    async def update(self) -> FeedUpdate:
        """Fetch the current markers and diff against the tracked set."""
        markers = await self._client.get_incident_markers(
            self.bbox, zoom=self.zoom, clip_to_bbox=True
        )
        now = datetime.now(UTC)
        self._sequence += 1

        diff = FeedUpdate(sequence=self._sequence, timestamp=now)
        seen_ids: set[str] = set()

        for marker in markers:
            if self.active_only and not marker.is_active:
                continue
            seen_ids.add(marker.incident_id)
            tracked = self._incidents.get(marker.incident_id)
            if tracked is None:
                tracked = TrackedIncident(
                    marker=marker,
                    first_seen=now,
                    last_seen=now,
                    state=FeedState.NEW,
                    fingerprint=_marker_fingerprint(marker),
                    lifecycle_history=[(now, marker.lifecycle_state)],
                )
                self._incidents[marker.incident_id] = tracked
                diff.added.append(tracked)
            else:
                if tracked.observe(marker, now):
                    diff.updated.append(tracked)

        # Mark unseen incidents stale, then expire them.
        for incident_id, tracked in list(self._incidents.items()):
            if incident_id in seen_ids:
                continue
            tracked.state = FeedState.STALE
            if self._should_expire(tracked, now):
                tracked.state = FeedState.REMOVED
                del self._incidents[incident_id]
                diff.removed.append(tracked)

        self._last_update = now
        return diff

    def _should_expire(self, tracked: TrackedIncident, now: datetime) -> bool:
        return (now - tracked.last_seen).total_seconds() >= self.expire_after

    def clear(self) -> None:
        """Drop all tracked state."""
        self._incidents.clear()
        self._last_update = None
