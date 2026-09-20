"""Tests for the extended public surface: extra tiles, users, social, trends."""

from __future__ import annotations

from pycitizen.models import (
    HistoricalIncident,
    ImpactStatistics,
    NeighborhoodBoundary,
    NeighborhoodDetails,
    NeighborhoodFeed,
    OffenderMarker,
    PlaceMarker,
    Position,
    PublicUser,
    SocialPresence,
)

BBOX = (-74.05, 40.62, -73.97, 40.69)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_historical_incident() -> None:
    h = HistoricalIncident.from_properties(
        {
            "incident_id": "h1",
            "title": "Old Fire",
            "latitude": 40.6,
            "longitude": -74.0,
            "incident_time_frame": "past_24h",
            "incident_score": 0.4,
            "view_count": 10,
            "is_paywalled": True,
            "updated_at": 1758238291.0,
        }
    )
    assert h is not None
    assert h.incident_id == "h1"
    assert h.time_frame == "past_24h"
    assert h.is_paywalled is True
    assert h.updated_at is not None


def test_offender_marker() -> None:
    o = OffenderMarker.from_properties(
        {
            "offender_id": "o1",
            "first_name": "John",
            "last_name": "Doe",
            "latitude": 40.6,
            "longitude": -74.0,
            "charges": ["assault", "theft"],
            "show_full_name": True,
        }
    )
    assert o is not None
    assert o.display_name == "John Doe"
    assert o.charges == ["assault", "theft"]


def test_offender_display_name_partial() -> None:
    o = OffenderMarker.from_properties(
        {"offender_id": "o2", "last_name": "Smith", "show_full_name": False}
    )
    assert o is not None and o.display_name == "Smith"


def test_place_marker() -> None:
    p = PlaceMarker.from_properties(
        {"id": 42, "name": "Sunset Park", "type": "neighbourhood", "z_order": 5},
        fallback_position=Position(40.65, -74.0),
    )
    assert p.place_id == "42"
    assert p.name == "Sunset Park"
    assert p.position == Position(40.65, -74.0)


def test_public_user() -> None:
    u = PublicUser.from_dict(
        {"id": "u1", "username": "alice", "avatarThumbURL": "https://x", "private": False}
    )
    assert u.user_id == "u1" and u.username == "alice" and u.is_private is False


def test_impact_statistics() -> None:
    s = ImpactStatistics.from_dict(
        {
            "usersWithPremium": {"numUsers": 174109, "subtitle": "People"},
            "agentImpactInPastWeek": {"numCallsAnswered": 70},
            "missingPeopleAndPetsFound": {"numFound": 12},
        }
    )
    assert s.users_with_premium == 174109
    assert s.calls_answered_past_week == 70
    assert s.missing_found == 12


def test_social_presence() -> None:
    p = SocialPresence.from_dict(
        {
            "incidentId": "i1",
            "friendPresence": {"aware": ["u1"], "notification": [], "view": ["u2", "u3"]},
        }
    )
    assert p.incident_id == "i1"
    assert p.aware == ["u1"] and p.view == ["u2", "u3"]


def test_neighborhood_models() -> None:
    b = NeighborhoodBoundary.from_dict(
        {"type": "MultiPolygon", "coordinates": [[[[1.0, 2.0]]]]}
    )
    assert b.type == "MultiPolygon" and b.coordinates
    d = NeighborhoodDetails.from_dict(
        {"name": "Sunset Park", "crimeLevel": "moderate", "statsLookbackPeriodInDays": 30}
    )
    assert d.name == "Sunset Park" and d.stats_lookback_days == 30
    f = NeighborhoodFeed.from_dict(
        {"neighborhoodId": "n1", "neighborhoodName": "Sunset Park", "graphStats": {"a": 1}}
    )
    assert f.neighborhood_id == "n1" and f.graph_stats == {"a": 1}


# ---------------------------------------------------------------------------
# Client endpoints
# ---------------------------------------------------------------------------


async def test_get_tile_style(client_factory) -> None:
    client = client_factory(
        {"v1/tile/style/citizen-app-dark-20220303.json": {"version": 8, "sources": {}}}
    )
    style = await client.get_tile_style("citizen-app-dark-20220303")
    assert style["version"] == 8
    _, path, _ = client._session.requests[0]
    assert path == "v1/tile/style/citizen-app-dark-20220303.json"


async def test_get_public_users(client_factory) -> None:
    client = client_factory(
        {"v1/users/batch_public": {"results": [{"id": "u1", "username": "alice"}]}}
    )
    users = await client.get_public_users(["u1", "u1", "u2"])
    assert users[0].username == "alice"
    _, _, params = client._session.requests[0]
    assert params["ids"] == "u1,u2"


async def test_check_username(client_factory) -> None:
    client = client_factory(
        {"v1/users/check_username": {"allowed": False, "reason": "taken"}}
    )
    check = await client.check_username("alice")
    assert check.allowed is False and check.reason == "taken"


async def test_get_social_presence(client_factory) -> None:
    client = client_factory(
        {
            "v1/incidents/social/batch": [
                {
                    "incidentId": "i1",
                    "friendPresence": {"aware": [], "notification": [], "view": []},
                }
            ]
        }
    )
    presence = await client.get_social_presence(["i1"])
    assert presence[0].incident_id == "i1"
    _, _, params = client._session.requests[0]
    assert params["incident_ids"] == "i1"


async def test_get_impact_statistics(client_factory) -> None:
    client = client_factory(
        {"v1/protect/impact_statistics": {"usersWithPremium": {"numUsers": 100}}}
    )
    stats = await client.get_impact_statistics()
    assert stats.users_with_premium == 100


async def test_get_neighborhood_details(client_factory) -> None:
    client = client_factory(
        {"v1/trends/neighborhoods/n1/details": {"name": "Sunset Park", "crimeLevel": "low"}}
    )
    details = await client.get_neighborhood_details("n1")
    assert details.name == "Sunset Park"


async def test_get_neighborhood_incidents(client_factory, incident_v1_payload) -> None:
    client = client_factory(
        {"v1/trends/neighborhoods/n1/incidents": [incident_v1_payload]}
    )
    incidents = await client.get_neighborhood_incidents("n1", category="fire", lookback_days=7)
    assert incidents[0].incident_id == incident_v1_payload["key"]
    _, _, params = client._session.requests[0]
    assert params["category"] == "fire" and params["lookback"] == 7


async def test_get_neighborhood_boundary(client_factory) -> None:
    client = client_factory(
        {"v1/trends/neighborhoods/n1/boundary": {"type": "Polygon", "coordinates": [[[0, 0]]]}}
    )
    boundary = await client.get_neighborhood_boundary("n1")
    assert boundary.type == "Polygon"


async def test_get_neighborhood_graph(client_factory) -> None:
    client = client_factory(
        {"v1/trends/neighborhoods/n1/graph": {"stats": {"fire": {"points": []}}}}
    )
    graph = await client.get_neighborhood_graph("n1", category="fire")
    assert "stats" in graph


async def test_get_neighborhood_feed(client_factory) -> None:
    client = client_factory(
        {"v1/trends/shs_feed": {"neighborhoodId": "n1", "neighborhoodName": "Sunset Park"}}
    )
    feed = await client.get_neighborhood_feed(40.65, -74.0)
    assert feed.neighborhood_name == "Sunset Park"
    _, _, params = client._session.requests[0]
    assert params == {"lat": 40.65, "long": -74.0}


async def test_historical_and_offender_tiles(client_factory, tile_bytes) -> None:
    # Reuse the real incident tile fixture for the historical endpoint path.
    client = client_factory(
        {
            "v1/tile/historical_incidents/*": tile_bytes,
            "v1/tile/offenders/*": b"",  # empty tile -> no features
        }
    )
    hist = await client.get_historical_incidents(BBOX, zoom=12, clip_to_bbox=False)
    assert len(hist) == 10  # fixture decoded under the historical parser
    offenders = await client.get_offender_markers(BBOX, zoom=12)
    assert offenders == []
