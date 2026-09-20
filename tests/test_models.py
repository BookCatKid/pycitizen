"""Tests for model parsing and enums."""

from __future__ import annotations

from datetime import UTC, datetime

from pycitizen.models import (
    ChatHistory,
    Incident,
    IncidentMarker,
    LifecycleState,
    NewsItem,
    SafetyStatus,
    Severity,
    _parse_ts,
)


def test_severity_from_wire_strings() -> None:
    assert Severity.from_value("red") is Severity.MAJOR_ACTIVE
    assert Severity.from_value("Yellow") is Severity.ACTIVE
    assert Severity.from_value("grey") is Severity.INACTIVE
    assert Severity.from_value("bogus") is Severity.UNKNOWN
    assert Severity.from_value(None) is Severity.UNKNOWN


def test_severity_from_numeric_level() -> None:
    assert Severity.from_value(3) is Severity.MAJOR_ACTIVE
    assert Severity.from_value(2) is Severity.ACTIVE
    assert Severity.from_value(0) is Severity.INACTIVE


def test_severity_flags() -> None:
    assert Severity.MAJOR_ACTIVE.ranking == 3
    assert Severity.MAJOR_ACTIVE.is_active
    assert not Severity.INACTIVE.is_active
    assert Severity.ACTIVE.value == "yellow"


def test_lifecycle_from_wire() -> None:
    assert LifecycleState.from_value("REPORTED") is LifecycleState.REPORTED
    assert LifecycleState.from_value("resolved") is LifecycleState.RESOLVED
    assert LifecycleState.from_value("???") is LifecycleState.UNKNOWN


def test_lifecycle_is_open() -> None:
    assert LifecycleState.REPORTED.is_open
    assert LifecycleState.DEVELOPING.is_open
    assert not LifecycleState.RESOLVED.is_open
    assert not LifecycleState.INACTIVE.is_open


def test_parse_ts_epoch_seconds() -> None:
    dt = _parse_ts(1758238291.0)
    assert dt == datetime.fromtimestamp(1758238291.0, tz=UTC)


def test_parse_ts_epoch_millis() -> None:
    assert _parse_ts(1758238291000) == _parse_ts(1758238291.0)


def test_parse_ts_iso_and_app_format() -> None:
    assert _parse_ts("2025-09-19T22:53:23+00:00") is not None
    assert _parse_ts("2025-09-19 22:53:23+00") is not None
    assert _parse_ts("2025-09-19 22:53:23+00:00") is not None


def test_parse_ts_junk() -> None:
    assert _parse_ts("not a date") is None
    assert _parse_ts(None) is None
    assert _parse_ts({}) is None


def test_incident_from_v3(incident_v3_payload) -> None:
    inc = Incident.from_dict(incident_v3_payload)
    assert inc.incident_id == "-P1vrxK35R7YgOyBYNo2"
    assert inc.title == "Report of Vehicle Collision"
    assert inc.position is not None
    assert abs(inc.position.latitude - 40.653793) < 1e-6
    assert inc.severity is Severity.ACTIVE
    assert inc.lifecycle_state is LifecycleState.REPORTED
    assert inc.is_active
    assert inc.timestamp is not None
    assert inc.service_area == "nyc"
    assert inc.raw is incident_v3_payload


def test_incident_from_v1(incident_v1_payload) -> None:
    inc = Incident.from_dict(incident_v1_payload)
    assert inc.incident_id == "-P1vrxK35R7YgOyBYNo2"
    assert inc.city_code == "nyc"
    assert len(inc.updates) == 2
    # updates sorted chronologically
    assert inc.updates[0].text == "Reported at 6:53 PM"
    assert inc.stats is not None
    assert inc.stats.views == 120
    assert inc.stats.comments == 9
    assert inc.stats.confirmations == 2.0


def test_incident_position_fallbacks() -> None:
    # ll array fallback
    inc = Incident.from_dict({"key": "a", "ll": [40.1, -74.2]})
    assert inc.position is not None and inc.position.latitude == 40.1
    # no coordinates anywhere
    inc = Incident.from_dict({"key": "a"})
    assert inc.position is None


def test_incident_missing_id() -> None:
    assert Incident.from_dict({}).incident_id == ""


def test_marker_from_properties(marker_props) -> None:
    m = IncidentMarker.from_properties(marker_props, tile=(12, 1205, 1539))
    assert m is not None
    assert m.incident_id == "-P1vrxK35R7YgOyBYNo2"
    assert m.position is not None
    assert m.severity is Severity.ACTIVE
    assert m.lifecycle_state is LifecycleState.REPORTED
    assert m.is_active
    assert m.categories == ["Accident", "Traffic"]
    assert m.comment_count == 3
    assert m.score == 0.85
    assert m.tile == (12, 1205, 1539)


def test_marker_requires_id() -> None:
    assert IncidentMarker.from_properties({"title": "no id"}) is None


def test_marker_fallback_position() -> None:
    from pycitizen.models import Position

    m = IncidentMarker.from_properties(
        {"incident_id": "x"}, fallback_position=Position(1.0, 2.0)
    )
    assert m is not None and m.position == Position(1.0, 2.0)


def test_news_item() -> None:
    item = NewsItem.from_dict(
        {"bucket": "top", "incident": {"incidentId": "i1", "title": "T"}}
    )
    assert item is not None
    assert item.bucket == "top"
    assert item.incident.incident_id == "i1"
    assert NewsItem.from_dict({"bucket": "top"}) is None


def test_chat_history() -> None:
    h = ChatHistory.from_dict(
        {
            "messages": [
                {
                    "id": "m1",
                    "userId": "u1",
                    "userName": "alice",
                    "message": "hello",
                    "createdAt": "2025-09-19 22:53:23+00:00",
                    "likes": 2,
                    "isNearby": True,
                }
            ],
            "pagination": {"hasMore": True, "id": "cursor123"},
        }
    )
    assert len(h.messages) == 1
    assert h.messages[0].user_name == "alice"
    assert h.messages[0].created is not None
    assert h.has_more
    assert h.cursor == "cursor123"


def test_safety_status() -> None:
    s = SafetyStatus.from_dict(
        {
            "inServiceArea": True,
            "serviceAreaCode": "nyc",
            "serviceAreaName": "New York City",
            "locationName": "Sunset Park",
            "pastXHourIncidentsInServiceArea": 14,
        }
    )
    assert s.in_service_area
    assert s.service_area_code == "nyc"
    assert s.past_hour_incidents == 14
