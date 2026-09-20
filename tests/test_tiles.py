"""Tests for slippy-map math and the MVT decoder."""

from __future__ import annotations

import pytest

from pycitizen.exceptions import CitizenTileError
from pycitizen.tiles import (
    decode_tile,
    lonlat_to_tile,
    tile_bounds,
    tiles_for_bbox,
)

# ---------------------------------------------------------------------------
# Slippy-map math
# ---------------------------------------------------------------------------


def test_lonlat_to_tile_nyc_z12() -> None:
    # Known-good tile covering southern Brooklyn at zoom 12.
    x, y = lonlat_to_tile(-74.008095, 40.653793, 12)
    assert (x, y) == (1205, 1540)


def test_lonlat_to_tile_origin() -> None:
    assert lonlat_to_tile(0.0, 0.0, 0) == (0, 0)
    assert lonlat_to_tile(0.0, 0.0, 1) == (1, 1)


def test_lonlat_to_tile_clamps_poles() -> None:
    x, y = lonlat_to_tile(-180.0, 89.0, 10)
    assert x == 0 and y == 0


def test_lonlat_to_tile_invalid_zoom() -> None:
    with pytest.raises(ValueError):
        lonlat_to_tile(0.0, 0.0, 30)


def test_tile_bounds_roundtrip() -> None:
    west, south, east, north = tile_bounds(1205, 1540, 12)
    # The point used above must fall inside its own tile.
    assert west <= -74.008095 < east
    assert south <= 40.653793 < north


def test_tiles_for_bbox_single() -> None:
    tiles = list(tiles_for_bbox(-74.02, 40.64, -73.99, 40.66, 12))
    assert len(tiles) >= 1
    assert all(z == 12 for z, _, _ in tiles)


def test_tiles_for_bbox_covers_corners() -> None:
    bbox = (-74.1, 40.6, -73.9, 40.75)
    tiles = set(tiles_for_bbox(*bbox, 12))
    for lon, lat in [
        (bbox[0], bbox[1]),
        (bbox[0], bbox[3]),
        (bbox[2], bbox[1]),
        (bbox[2], bbox[3]),
    ]:
        x, y = lonlat_to_tile(lon, lat, 12)
        assert (12, x, y) in tiles


def test_tiles_for_bbox_invalid() -> None:
    with pytest.raises(ValueError):
        list(tiles_for_bbox(1.0, 0.0, -1.0, 1.0, 12))


# ---------------------------------------------------------------------------
# Minimal MVT encoder for synthetic tiles
# ---------------------------------------------------------------------------


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _field(num: int, wire: int) -> bytes:
    return _varint((num << 3) | wire)


def _ld(num: int, payload: bytes) -> bytes:
    return _field(num, 2) + _varint(len(payload)) + payload


def _zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


def _value(v) -> bytes:
    if isinstance(v, str):
        return _ld(1, v.encode())
    if isinstance(v, bool):
        return _field(7, 0) + _varint(int(v))
    if isinstance(v, float):
        import struct

        return _field(3, 1) + struct.pack("<d", v)
    if isinstance(v, int):
        if v >= 0:
            return _field(5, 0) + _varint(v)
        return _field(4, 0) + _varint(v + (1 << 64))
    raise TypeError(v)


def _feature(props: dict, keys: list, values: list, point=(100, 200), fid=1) -> bytes:
    tags: list[int] = []
    for k, v in props.items():
        if k not in keys:
            keys.append(k)
        if v not in values:
            values.append(v)
        tags.extend([keys.index(k), values.index(v)])
    tags_packed = b"".join(_varint(t) for t in tags)
    # geometry: MoveTo(1) count=1, then dx, dy zigzag
    geom = _varint((1 << 3) | 1) + _varint(_zigzag(point[0])) + _varint(_zigzag(point[1]))
    geom_packed = geom  # single command stream
    out = _field(1, 0) + _varint(fid)
    out += _ld(2, tags_packed)
    out += _field(3, 0) + _varint(1)  # type=point
    out += _ld(4, geom_packed)
    return out


def encode_tile(name: str, features: list[dict], extent: int = 4096) -> bytes:
    keys: list[str] = []
    values: list = []
    feats = [_feature(p, keys, values) for p in features]
    layer = _ld(1, name.encode())
    for f in feats:
        layer += _ld(2, f)
    for k in keys:
        layer += _ld(3, k.encode())
    for v in values:
        layer += _ld(4, _value(v))
    layer += _field(5, 0) + _varint(extent)
    layer += _field(15, 0) + _varint(2)
    return _ld(3, layer)


# ---------------------------------------------------------------------------
# Decoder tests
# ---------------------------------------------------------------------------


def test_decode_real_tile(tile_bytes) -> None:
    tile = decode_tile(tile_bytes)
    assert set(tile.layers) == {"incidents"}
    layer = tile.layer("incidents")
    assert layer is not None
    assert len(layer.features) == 10
    assert layer.extent > 0
    feature = layer.features[0]
    assert feature.geom_type == 1
    assert feature.geometry[0]
    for key in ("incident_id", "title", "latitude", "longitude", "severity", "ts"):
        assert key in feature.properties


def test_decode_synthetic_tile() -> None:
    data = encode_tile(
        "incidents",
        [{"incident_id": "abc123", "title": "Fire", "severity": "red", "view_count": 7}],
    )
    tile = decode_tile(data)
    layer = tile.layer("incidents")
    assert layer is not None
    (f,) = layer.features
    assert f.feature_id == 1
    assert f.geom_type == 1
    assert f.properties == {
        "incident_id": "abc123",
        "title": "Fire",
        "severity": "red",
        "view_count": 7,
    }
    assert f.geometry == [[(100, 200)]]


def test_feature_position_projection() -> None:
    data = encode_tile("incidents", [{"incident_id": "x"}], extent=4096)
    layer = decode_tile(data).layer("incidents")
    pos = layer.features[0].position(1205, 1539, 12, extent=layer.extent)
    assert pos is not None
    west, south, east, north = tile_bounds(1205, 1539, 12)
    assert west <= pos.longitude <= east
    assert south <= pos.latitude <= north


def test_decode_garbage() -> None:
    with pytest.raises(CitizenTileError):
        decode_tile(b"\x80")  # unterminated varint


def test_decode_empty() -> None:
    tile = decode_tile(b"")
    assert tile.layers == {}
