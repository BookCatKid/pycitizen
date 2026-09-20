"""Tests for CitizenClient: endpoint paths, params, errors, retries, batching."""

from __future__ import annotations

from datetime import UTC, datetime

import aiohttp
import pytest

from pycitizen import (
    CitizenAuthError,
    CitizenClient,
    CitizenConnectionError,
    CitizenNotFoundError,
    CitizenRateLimitError,
    CitizenResponseError,
    CitizenTimeoutError,
    RateLimiter,
    RetryPolicy,
    Severity,
)
from pycitizen.const import HEADER_ACCESS_TOKEN

from .conftest import INCIDENT_ID, FakeResponse, FakeSession

BBOX = (-74.05, 40.62, -73.97, 40.69)


async def test_health(client_factory) -> None:
    client = client_factory({"healthz": FakeResponse(200, b"OK")})
    assert await client.health() is True
    await client.close()


async def test_get_incident_v3(client_factory, incident_v3_payload) -> None:
    client = client_factory({f"v3/incident/{INCIDENT_ID}": incident_v3_payload})
    inc = await client.get_incident(INCIDENT_ID)
    assert inc.incident_id == INCIDENT_ID
    assert inc.severity is Severity.ACTIVE
    method, path, _ = client._session.requests[0]
    assert method == "GET" and path == f"v3/incident/{INCIDENT_ID}"


async def test_get_incident_v1_params(client_factory, incident_v1_payload) -> None:
    client = client_factory({f"v1/incident/{INCIDENT_ID}": incident_v1_payload})
    await client.get_incident_v1(INCIDENT_ID)
    _, _, params = client._session.requests[0]
    assert params["with_stats"] == "true" and params["with_facepile"] == "true"


async def test_get_incidents_batch_chunking(client_factory, incident_v1_payload) -> None:
    calls: list[str] = []

    def handler(method, path, params, headers):
        calls.append(params["incident_ids"])
        return [incident_v1_payload]

    client = client_factory({"v1/incidents/batch": handler})
    ids = [f"id{i}" for i in range(120)]
    out = await client.get_incidents(ids)
    assert len(calls) == 3  # 50 + 50 + 20
    assert len(calls[0].split(",")) == 50
    assert len(calls[2].split(",")) == 20
    assert len(out) == 3


async def test_get_incidents_dedupes_ids(client_factory, incident_v1_payload) -> None:
    client = client_factory({"v1/incidents/batch": [incident_v1_payload]})
    await client.get_incidents(["a", "a", "b"])
    _, _, params = client._session.requests[0]
    assert params["incident_ids"] == "a,b"


async def test_get_related_incidents(client_factory) -> None:
    client = client_factory(
        {f"v1/incidents/{INCIDENT_ID}/related_incidents": {"relatedIncidents": ["r1", "r2"]}}
    )
    assert await client.get_related_incidents(INCIDENT_ID) == ["r1", "r2"]


async def test_get_incident_content_list(client_factory) -> None:
    client = client_factory(
        {
            f"v1/incidents/{INCIDENT_ID}/content": [
                {"type": "WEB", "url": "https://news.example/a", "title": "News"}
            ]
        }
    )
    content = await client.get_incident_content(INCIDENT_ID)
    assert len(content) == 1 and content[0].type == "WEB"


async def test_get_incident_content_dict_of_lists(client_factory) -> None:
    client = client_factory(
        {
            f"v1/incidents/{INCIDENT_ID}/content": {
                "web": [{"type": "WEB", "url": "https://x"}],
                "images": [{"type": "IMAGE", "url": "https://y"}],
            }
        }
    )
    content = await client.get_incident_content(INCIDENT_ID)
    assert {c.type for c in content} == {"WEB", "IMAGE"}


async def test_get_news_feed(client_factory) -> None:
    client = client_factory(
        {"v2/news/feed": {"news": [{"bucket": "top", "incident": {"incidentId": "n1"}}]}}
    )
    items = await client.get_news_feed("nyc")
    assert len(items) == 1 and items[0].incident.incident_id == "n1"
    _, _, params = client._session.requests[0]
    assert params == {"code": "nyc"}


async def test_get_news_briefing(client_factory) -> None:
    client = client_factory(
        {
            "v2/incidents/news_briefing": {
                "briefingId": "b1",
                "title": "Morning Briefing",
                "incidents": [{"incidentId": "i1"}],
            }
        }
    )
    briefing = await client.get_news_briefing("nyc")
    assert briefing.title == "Morning Briefing"
    assert briefing.incidents[0].incident_id == "i1"
    _, _, params = client._session.requests[0]
    assert params["service_area"] == "nyc"


async def test_get_status(client_factory) -> None:
    client = client_factory(
        {"v1/homescreen/status": {"inServiceArea": True, "serviceAreaCode": "nyc"}}
    )
    status = await client.get_status(40.65, -74.0)
    assert status.in_service_area and status.service_area_code == "nyc"
    _, _, params = client._session.requests[0]
    assert params == {"lat": 40.65, "long": -74.0}


async def test_get_service_areas(client_factory) -> None:
    client = client_factory({"v1/homescreen/mapExplore": {"serviceAreas": ["nyc", "jc"]}})
    assert await client.get_service_areas(BBOX) == ["nyc", "jc"]
    _, _, params = client._session.requests[0]
    assert params["lowerLongitude"] == BBOX[0]
    assert params["upperLatitude"] == BBOX[3]


async def test_get_chat_history(client_factory) -> None:
    client = client_factory(
        {
            "v4/incident_chat/history": {
                "messages": [{"id": "m1", "message": "hi"}],
                "pagination": {"hasMore": False, "id": None},
            }
        }
    )
    history = await client.get_chat_history(INCIDENT_ID, limit=25)
    assert len(history.messages) == 1
    _, path, params = client._session.requests[0]
    assert path == "v4/incident_chat/history"
    assert params["incident_id"] == INCIDENT_ID and params["limit"] == 25
    assert "include_deleted" not in params  # None params stripped


async def test_get_location_name(client_factory) -> None:
    client = client_factory(
        {"v1/safety/location_name": {"locationName": "Sunset Park", "address": "123 St"}}
    )
    loc = await client.get_location_name(40.65, -74.0)
    assert loc.location_name == "Sunset Park"


# ---------------------------------------------------------------------------
# Incident markers via tiles
# ---------------------------------------------------------------------------


async def test_get_incident_markers(client_factory, tile_bytes) -> None:
    client = client_factory({"v1/tile/incidents/*": tile_bytes})
    markers = await client.get_incident_markers(BBOX, zoom=12)
    # The real fixture covers a different bbox; markers outside BBOX are clipped.
    assert isinstance(markers, list)
    # Every request was a tile request.
    for _, path, _ in client._session.requests:
        assert path.startswith("v1/tile/incidents/")


async def test_get_incident_markers_no_clip(client_factory, tile_bytes) -> None:
    client = client_factory({"v1/tile/incidents/*": tile_bytes})
    markers = await client.get_incident_markers(BBOX, zoom=12, clip_to_bbox=False)
    assert len(markers) == 10  # all real fixture features survive dedup


async def test_get_incident_markers_tile_404(client_factory) -> None:
    client = client_factory({})  # default route -> 404
    assert await client.get_incident_markers(BBOX, zoom=12) == []


async def test_get_incident_markers_filter_params(client_factory, tile_bytes) -> None:
    """App-matched tile query params are passed through to every tile."""
    client = client_factory({"v1/tile/incidents/*": tile_bytes})
    await client.get_incident_markers(
        BBOX,
        zoom=12,
        categories=["fire_related", "collision"],
        created_gte=datetime(2026, 9, 19, tzinfo=UTC),
        created_lte="2026-09-20T00:00:00+00:00",
        limit=200,
        active_definition="state_based",
        with_lifecycle_state=True,
    )
    _, _, params = client._session.requests[0]
    assert params["incident_category"] == ["fire_related", "collision"]
    assert params["incident_created_at_gte"] == "2026-09-19T00:00:00+00:00"
    assert params["incident_created_at_lte"] == "2026-09-20T00:00:00+00:00"
    assert params["limit"] == 200
    assert params["active_definition"] == "state_based"
    assert params["with_lifecycle_state"] == "true"


async def test_get_incident_markers_no_params_by_default(
    client_factory, tile_bytes
) -> None:
    client = client_factory({"v1/tile/incidents/*": tile_bytes})
    await client.get_incident_markers(BBOX, zoom=12)
    assert client._session.requests[0][2] == {}


# ---------------------------------------------------------------------------
# Errors / retries / headers
# ---------------------------------------------------------------------------


async def test_auth_error(client_factory) -> None:
    client = client_factory({"v3/incident/x": FakeResponse(401, b"{}")})
    with pytest.raises(CitizenAuthError):
        await client.get_incident("x")


async def test_not_found(client_factory) -> None:
    client = client_factory({"v3/incident/x": FakeResponse(404, b"{}")})
    with pytest.raises(CitizenNotFoundError):
        await client.get_incident("x")


async def test_server_error_no_retry_left(client_factory) -> None:
    client = client_factory(
        {"v3/incident/x": FakeResponse(500, b"oops")},
        retry_policy=RetryPolicy(max_attempts=2, backoff_base=0.001),
    )
    with pytest.raises(CitizenResponseError) as exc:
        await client.get_incident("x")
    assert exc.value.status == 500
    assert len(client._session.requests) == 2  # retried once


async def test_retry_recovers(client_factory, incident_v3_payload) -> None:
    state = {"n": 0}

    def handler(method, path, params, headers):
        state["n"] += 1
        if state["n"] < 3:
            return FakeResponse(503, b"busy", {"Retry-After": "0.01"})
        return incident_v3_payload

    client = client_factory(
        {"v3/incident/x": handler},
        retry_policy=RetryPolicy(max_attempts=4, backoff_base=0.001),
    )
    inc = await client.get_incident("x")
    assert inc.incident_id == "-P1vrxK35R7YgOyBYNo2"
    assert state["n"] == 3


async def test_rate_limit_error(client_factory) -> None:
    client = client_factory(
        {"v3/incident/x": FakeResponse(429, b"", {"Retry-After": "0.001"})},
        retry_policy=RetryPolicy(max_attempts=2, backoff_base=0.001),
    )
    with pytest.raises(CitizenRateLimitError):
        await client.get_incident("x")


async def test_connection_error(client_factory) -> None:
    client = client_factory(
        {"v3/incident/x": aiohttp.ClientConnectionError("boom")},
        retry_policy=RetryPolicy(max_attempts=2, backoff_base=0.001),
    )
    with pytest.raises(CitizenConnectionError):
        await client.get_incident("x")


async def test_timeout_error(client_factory) -> None:
    client = client_factory(
        {"v3/incident/x": TimeoutError()},
        retry_policy=RetryPolicy(max_attempts=1, backoff_base=0.001),
    )
    with pytest.raises(CitizenTimeoutError):
        await client.get_incident("x")


async def test_access_token_header() -> None:
    session = FakeSession({"healthz": FakeResponse(200, b"OK")})
    client = CitizenClient(
        session=session,
        access_token="tok123",
        rate_limiter=RateLimiter(rate=10_000, burst=10_000),
    )
    await client.health()
    # FakeSession captured headers via request(); re-check via last call.
    # (headers are passed to request(); assert through a wrapped call)
    assert client._request_headers()[HEADER_ACCESS_TOKEN] == "tok123"


async def test_context_manager_closes_owned_session() -> None:
    async with CitizenClient(rate_limiter=RateLimiter(rate=10_000, burst=10_000)) as c:
        assert not c.closed
    assert c.closed


async def test_injected_session_not_closed() -> None:
    session = FakeSession({})
    client = CitizenClient(session=session)
    await client.close()
    assert not session.closed  # injected session stays open
