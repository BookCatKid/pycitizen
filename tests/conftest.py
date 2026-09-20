"""Offline test fixtures: a fake aiohttp session + canned payloads.

No test in this suite touches the network. ``FakeSession`` implements the
slice of the aiohttp API the client uses (request() -> async context
manager -> response with .status/.read()/.headers).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pycitizen import CitizenClient, RateLimiter, RetryPolicy

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    """Minimal stand-in for aiohttp.ClientResponse."""

    def __init__(
        self,
        status: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


RouteValue = Any
RouteHandler = Callable[[str, str, dict[str, Any], dict[str, str]], RouteValue]


class FakeSession:
    """Records requests and replays canned responses.

    ``routes`` maps a URL path (e.g. ``"v3/incident/abc"``) or
    ``"METHOD path"`` to one of:
      - dict/list -> 200 JSON response
      - bytes     -> 200 binary response
      - FakeResponse -> returned verbatim
      - Exception instance/class -> raised from request()
      - callable(method, path, params, headers) -> any of the above
    Prefix match: a route ending in ``"*"`` matches any path prefix.
    """

    def __init__(self, routes: dict[str, RouteValue] | None = None) -> None:
        self.routes = routes or {}
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.closed = False

    def _lookup(self, method: str, path: str) -> RouteValue:
        for key in (f"{method} {path}", path):
            if key in self.routes:
                return self.routes[key]
        for key, value in self.routes.items():
            if key.endswith("*"):
                prefix = key[:-1]
                if " " in prefix:
                    m, p = prefix.split(" ", 1)
                    if method == m and path.startswith(p):
                        return value
                elif path.startswith(prefix):
                    return value
        return FakeResponse(404, b'{"error":"not found"}')

    def request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> FakeResponse:
        path = url.split("data.sp0n.io/")[-1].lstrip("/")
        self.requests.append((method, path, params or {}))
        result = self._lookup(method, path)
        if callable(result):
            result = result(method, path, params or {}, headers or {})
        if isinstance(result, type) and issubclass(result, Exception):
            raise result()
        if isinstance(result, Exception):
            raise result
        if isinstance(result, FakeResponse):
            return result
        if isinstance(result, bytes):
            return FakeResponse(200, result, {"Content-Type": "application/x-protobuf"})
        return FakeResponse(200, json.dumps(result).encode(), {"Content-Type": "application/json"})

    async def close(self) -> None:
        self.closed = True


def make_client(routes: dict[str, RouteValue], **kwargs: Any) -> CitizenClient:
    """Client wired to a FakeSession with no rate limiting delays."""
    session = FakeSession(routes)
    kwargs.setdefault("rate_limiter", RateLimiter(rate=10_000, burst=10_000))
    kwargs.setdefault("retry_policy", RetryPolicy(max_attempts=3, backoff_base=0.001))
    return CitizenClient(session=session, **kwargs)


@pytest.fixture
def client_factory():
    return make_client


@pytest.fixture
def tile_bytes() -> bytes:
    return (FIXTURES / "incidents_tile.pbf").read_bytes()


# ---------------------------------------------------------------------------
# Canned payloads (shapes verified against the live API)
# ---------------------------------------------------------------------------

INCIDENT_ID = "-P1vrxK35R7YgOyBYNo2"


@pytest.fixture
def incident_v3_payload() -> dict[str, Any]:
    return {
        "incidentId": INCIDENT_ID,
        "title": "Report of Vehicle Collision",
        "position": {"latitude": 40.653793, "longitude": -74.008095},
        "location": "123 45th St, Brooklyn",
        "address": "123 45th St",
        "neighborhood": "Sunset Park, Brooklyn",
        "category": "Accident",
        "categories": ["Accident"],
        "subcategory": "Vehicle Collision",
        "level": 2,
        "severity": "yellow",
        "lifecycleState": "REPORTED",
        "ts": 1758238291.0,
        "cs": 1758238003.0,
        "confirmed": True,
        "hasVod": False,
        "isPaywalled": False,
        "chatBlocked": False,
        "deleted": False,
        "serviceArea": "nyc",
        "homescreenMapThumbnail": "https://assets.citizen.com/t.png",
        "locationDetails": {"city": "New York"},
    }


@pytest.fixture
def incident_v1_payload() -> dict[str, Any]:
    return {
        "key": INCIDENT_ID,
        "title": "Report of Vehicle Collision",
        "latitude": 40.653793,
        "longitude": -74.008095,
        "ll": [40.653793, -74.008095],
        "location": "123 45th St, Brooklyn",
        "neighborhood": "Sunset Park, Brooklyn",
        "cityCode": "nyc",
        "categories": ["Accident"],
        "subcategory": "Vehicle Collision",
        "severity": "yellow",
        "level": 2,
        "ts": 1758238291.0,
        "cs": 1758238003.0,
        "closed": False,
        "hasVod": False,
        "updates": {
            "u1": {"text": "Units on scene", "ts": 1758238400.0, "uid": "u1"},
            "u2": {"text": "Reported at 6:53 PM", "ts": 1758238300.0, "uid": "u2"},
        },
        "stats": {
            "views": 120,
            "shares": 4,
            "chats": 9,
            "nconfirmed": 2.0,
            "usersNotifiedUnique": 500,
        },
    }


@pytest.fixture
def marker_props() -> dict[str, Any]:
    """A single incident feature's properties as decoded from a tile."""
    return {
        "incident_id": INCIDENT_ID,
        "title": "Report of Vehicle Collision",
        "latitude": 40.653793,
        "longitude": -74.008095,
        "category": "Accident",
        "categories": ["Accident", "Traffic"],
        "subcategory": "Vehicle Collision",
        "severity": "yellow",
        "level": 2,
        "lifecycle_state": "reported",
        "recency_tier": 1,
        "ts": 1758238291.0,
        "cs": 1758238003.0,
        "incident_score": 0.85,
        "comment_count": 3,
        "share_count": 1,
        "view_count": 42,
        "has_vod": False,
        "is_paywalled": False,
        "unverified_community_alert": False,
        "unverified_igl_incident": False,
    }
