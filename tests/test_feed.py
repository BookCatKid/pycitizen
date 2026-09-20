"""Tests for IncidentFeed: dedup, change detection, lifecycle tracking."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

from pycitizen.feed import FeedState, IncidentFeed, _marker_fingerprint
from pycitizen.models import IncidentMarker, LifecycleState, Position, Severity

BBOX = (-74.05, 40.62, -73.97, 40.69)


def make_marker(
    incident_id: str = "inc1",
    *,
    title: str = "Report of Fire",
    lifecycle: str = "reported",
    severity: str = "yellow",
    comments: int = 0,
    ts: float = 1758238291.0,
) -> IncidentMarker:
    return IncidentMarker.from_properties(
        {
            "incident_id": incident_id,
            "title": title,
            "latitude": 40.65,
            "longitude": -74.0,
            "severity": severity,
            "lifecycle_state": lifecycle,
            "comment_count": comments,
            "ts": ts,
        }
    )


class StubClient:
    """Minimal stand-in for CitizenClient (feed only calls one method)."""

    def __init__(self, pages: list[list[IncidentMarker]]) -> None:
        self.pages = list(pages)
        self.calls = 0
        self.last_bbox = None

    async def get_incident_markers(self, bbox, *, zoom=12, clip_to_bbox=True):
        self.calls += 1
        self.last_bbox = bbox
        if self.pages:
            return self.pages.pop(0)
        return []


async def test_first_update_all_added() -> None:
    feed = IncidentFeed(StubClient([[make_marker("a"), make_marker("b")]]), BBOX)
    diff = await feed.update()
    assert {t.incident_id for t in diff.added} == {"a", "b"}
    assert not diff.updated and not diff.removed
    assert diff.changed
    assert len(feed.incidents) == 2


async def test_no_change_no_events() -> None:
    client = StubClient([[make_marker("a")], [make_marker("a")]])
    feed = IncidentFeed(client, BBOX)
    await feed.update()
    diff = await feed.update()
    assert not diff.changed
    assert feed.incidents["a"].state is FeedState.ACTIVE


async def test_field_change_detected() -> None:
    m1 = make_marker("a", comments=1)
    m2 = make_marker("a", comments=5)
    feed = IncidentFeed(StubClient([[m1], [m2]]), BBOX)
    await feed.update()
    diff = await feed.update()
    assert [t.incident_id for t in diff.updated] == ["a"]
    assert feed.incidents["a"].state is FeedState.UPDATED


async def test_title_change_detected() -> None:
    feed = IncidentFeed(
        StubClient([[make_marker("a", title="Fire")], [make_marker("a", title="Big Fire")]]),
        BBOX,
    )
    await feed.update()
    diff = await feed.update()
    assert len(diff.updated) == 1


async def test_lifecycle_transition_recorded() -> None:
    feed = IncidentFeed(
        StubClient(
            [
                [make_marker("a", lifecycle="reported")],
                [make_marker("a", lifecycle="verified")],
                [make_marker("a", lifecycle="resolved")],
            ]
        ),
        BBOX,
    )
    await feed.update()
    await feed.update()
    await feed.update()
    history = feed.incidents["a"].lifecycle_history
    states = [s for _, s in history]
    assert states == [
        LifecycleState.REPORTED,
        LifecycleState.VERIFIED,
        LifecycleState.RESOLVED,
    ]


async def test_disappearance_marks_stale_then_removed() -> None:
    client = StubClient([[make_marker("a")], [], []])
    feed = IncidentFeed(client, BBOX, expire_after=60)
    await feed.update()
    diff = await feed.update()
    assert not diff.removed
    assert feed.incidents["a"].state is FeedState.STALE
    # Simulate time passing beyond expire_after.
    feed.incidents["a"].last_seen = datetime.now(UTC) - timedelta(seconds=120)
    diff = await feed.update()
    assert [t.incident_id for t in diff.removed] == ["a"]
    assert "a" not in feed.incidents


async def test_reappearing_incident_reactivates() -> None:
    m = make_marker("a")
    feed = IncidentFeed(StubClient([[m], [], [m]]), BBOX, expire_after=600)
    await feed.update()
    await feed.update()  # stale
    diff = await feed.update()  # back
    assert "a" in feed.incidents
    assert feed.incidents["a"].state is FeedState.ACTIVE
    assert not diff.added  # not re-added, just observed again


async def test_active_only_filters() -> None:
    feed = IncidentFeed(
        StubClient([[make_marker("a", lifecycle="resolved", severity="grey")]]),
        BBOX,
        active_only=True,
    )
    diff = await feed.update()
    assert not diff.added and not feed.incidents


async def test_sequence_and_last_update() -> None:
    feed = IncidentFeed(StubClient([[], []]), BBOX)
    assert feed.last_update is None
    await feed.update()
    assert feed.last_update is not None
    await feed.update()
    assert feed.incidents == {}


async def test_fingerprint_ignores_untracked_fields() -> None:
    m1 = make_marker("a")
    m2 = dataclasses.replace(m1, score=99.0)  # score not tracked
    assert _marker_fingerprint(m1) == _marker_fingerprint(m2)


async def test_clear() -> None:
    feed = IncidentFeed(StubClient([[make_marker("a")]]), BBOX)
    await feed.update()
    feed.clear()
    assert feed.incidents == {} and feed.last_update is None


def test_marker_position_type() -> None:
    m = make_marker("x")
    assert isinstance(m.position, Position)
    assert m.severity is Severity.ACTIVE
