"""Mapbox Vector Tile (MVT) decoding and slippy-map tile math.

Implements a minimal, dependency-free protobuf wire reader sufficient to
decode the Tile spec (https://github.com/mapbox/vector-tile-spec), plus
Web-Mercator tile helpers used to cover a bounding box with tile requests.

The Citizen ``incidents`` layer carries explicit ``latitude``/``longitude``
properties on every feature, so geometry decoding is only needed for
features that omit them; both paths are supported.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .exceptions import CitizenTileError
from .models import Position

__all__ = [
    "VectorTile",
    "VectorTileFeature",
    "VectorTileLayer",
    "decode_tile",
    "lonlat_to_tile",
    "tile_bounds",
    "tiles_for_bbox",
]

MAX_ZOOM = 22
WEB_MERCATOR_MAX_LAT = 85.05112878


# ---------------------------------------------------------------------------
# Slippy-map tile math
# ---------------------------------------------------------------------------


def lonlat_to_tile(longitude: float, latitude: float, zoom: int) -> tuple[int, int]:
    """Convert a lon/lat to slippy-map tile x/y at ``zoom``."""
    if not 0 <= zoom <= MAX_ZOOM:
        raise ValueError(f"zoom must be 0..{MAX_ZOOM}")
    lat = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, latitude))
    n = 1 << zoom
    x = int((longitude + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tile_bounds(x: int, y: int, zoom: int) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) lon/lat bounds of a tile."""
    n = 1 << zoom

    def lon(tx: int) -> float:
        return tx / n * 360.0 - 180.0

    def lat(ty: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))

    return lon(x), lat(y + 1), lon(x + 1), lat(y)


def tiles_for_bbox(
    west: float, south: float, east: float, north: float, zoom: int
) -> Iterator[tuple[int, int, int]]:
    """Yield (z, x, y) tiles covering a lon/lat bounding box at ``zoom``.

    Longitudes are clamped to [-180, 180]; boxes crossing the antimeridian
    should be split by the caller.
    """
    west = max(-180.0, min(180.0, west))
    east = max(-180.0, min(180.0, east))
    south = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, south))
    north = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, north))
    if west > east or south > north:
        raise ValueError("invalid bounding box")
    x_min, y_max = lonlat_to_tile(west, south, zoom)
    x_max, y_min = lonlat_to_tile(east, north, zoom)
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            yield (zoom, x, y)


# ---------------------------------------------------------------------------
# Minimal protobuf wire reader
# ---------------------------------------------------------------------------

_WIRE_VARINT = 0
_WIRE_FIXED64 = 1
_WIRE_LENGTH = 2
_WIRE_FIXED32 = 5


class _Reader:
    """Tiny protobuf wire-format cursor."""

    __slots__ = ("buf", "end", "pos")

    def __init__(self, buf: bytes, pos: int = 0, end: int | None = None) -> None:
        self.buf = buf
        self.pos = pos
        self.end = len(buf) if end is None else end

    def eof(self) -> bool:
        return self.pos >= self.end

    def varint(self) -> int:
        result = 0
        shift = 0
        while True:
            if self.pos >= self.end:
                raise CitizenTileError("truncated varint")
            b = self.buf[self.pos]
            self.pos += 1
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result
            shift += 7
            if shift > 70:
                raise CitizenTileError("varint too long")

    def tag(self) -> tuple[int, int]:
        key = self.varint()
        return key >> 3, key & 0x7

    def fixed32(self) -> bytes:
        if self.pos + 4 > self.end:
            raise CitizenTileError("truncated fixed32")
        out = self.buf[self.pos : self.pos + 4]
        self.pos += 4
        return out

    def fixed64(self) -> bytes:
        if self.pos + 8 > self.end:
            raise CitizenTileError("truncated fixed64")
        out = self.buf[self.pos : self.pos + 8]
        self.pos += 8
        return out

    def bytes(self) -> bytes:
        length = self.varint()
        if self.pos + length > self.end:
            raise CitizenTileError("truncated length-delimited field")
        out = self.buf[self.pos : self.pos + length]
        self.pos += length
        return out

    def packed_varints(self) -> list[int]:
        sub = _Reader(self.bytes())
        out = []
        while not sub.eof():
            out.append(sub.varint())
        return out

    def skip(self, wire: int) -> None:
        if wire == _WIRE_VARINT:
            self.varint()
        elif wire == _WIRE_FIXED64:
            self.fixed64()
        elif wire == _WIRE_LENGTH:
            self.bytes()
        elif wire == _WIRE_FIXED32:
            self.fixed32()
        else:
            raise CitizenTileError(f"unsupported wire type {wire}")


def _zigzag(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def _signed64(n: int) -> int:
    return n - (1 << 64) if n >= 1 << 63 else n


# ---------------------------------------------------------------------------
# Vector tile model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class VectorTileFeature:
    """One decoded feature: id, geometry type, properties, geometry.

    ``geometry`` is a list of point lists in tile coordinates
    (0..extent, y down). For the Citizen incidents layer every feature is
    a single point; real lon/lat come from the feature properties or via
    :meth:`position`.
    """

    feature_id: int | None
    geom_type: int  # 1=point, 2=linestring, 3=polygon
    properties: dict[str, Any] = field(default_factory=dict)
    geometry: list[list[tuple[int, int]]] = field(default_factory=list)

    def position(
        self, x: int, y: int, zoom: int, extent: int = 4096
    ) -> Position | None:
        """Project the first point of this feature to lon/lat."""
        if not self.geometry or not self.geometry[0]:
            return None
        px, py = self.geometry[0][0]
        west, south, east, north = tile_bounds(x, y, zoom)
        lon = west + (east - west) * (px / extent)
        lat = north - (north - south) * (py / extent)
        return Position(latitude=lat, longitude=lon)


@dataclass(slots=True)
class VectorTileLayer:
    """A decoded tile layer."""

    name: str
    version: int = 1
    extent: int = 4096
    features: list[VectorTileFeature] = field(default_factory=list)


@dataclass(slots=True)
class VectorTile:
    """A decoded vector tile: name -> layer."""

    layers: dict[str, VectorTileLayer] = field(default_factory=dict)

    def layer(self, name: str) -> VectorTileLayer | None:
        return self.layers.get(name)


def _decode_value(buf: bytes) -> Any:
    r = _Reader(buf)
    value: Any = None
    while not r.eof():
        field_no, wire = r.tag()
        if field_no == 1:
            value = r.bytes().decode("utf-8", errors="replace")
        elif field_no == 2:
            value = struct.unpack("<f", r.fixed32())[0]
        elif field_no == 3:
            value = struct.unpack("<d", r.fixed64())[0]
        elif field_no == 4:
            value = _signed64(r.varint())
        elif field_no == 5:
            value = r.varint()
        elif field_no == 6:
            value = _zigzag(r.varint())
        elif field_no == 7:
            value = bool(r.varint())
        else:
            r.skip(wire)
    return value


def _decode_geometry(r: _Reader) -> list[list[tuple[int, int]]]:
    """Decode a packed geometry field into lists of (x, y) tile coords."""
    commands = r.packed_varints()
    geoms: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] = []
    x = y = 0
    i = 0
    while i < len(commands):
        cmd = commands[i] & 0x7
        count = commands[i] >> 3
        i += 1
        if cmd in (1, 2):  # MoveTo / LineTo
            for _ in range(count):
                if i + 1 >= len(commands):
                    raise CitizenTileError("truncated geometry parameters")
                x += _zigzag(commands[i])
                y += _zigzag(commands[i + 1])
                i += 2
                if cmd == 1 and current:
                    geoms.append(current)
                    current = []
                current.append((x, y))
        elif cmd == 7:  # ClosePath
            if current:
                geoms.append(current)
                current = []
        else:
            raise CitizenTileError(f"unknown geometry command {cmd}")
    if current:
        geoms.append(current)
    return geoms


def _decode_feature(buf: bytes, keys: list[str], values: list[Any]) -> VectorTileFeature:
    r = _Reader(buf)
    feature_id: int | None = None
    geom_type = 0
    tag_indices: list[int] = []
    geometry: list[list[tuple[int, int]]] = []
    while not r.eof():
        field_no, wire = r.tag()
        if field_no == 1:
            feature_id = r.varint()
        elif field_no == 2:
            tag_indices = r.packed_varints()
        elif field_no == 3:
            geom_type = r.varint()
        elif field_no == 4:
            geometry = _decode_geometry(r)
        else:
            r.skip(wire)
    props: dict[str, Any] = {}
    for i in range(0, len(tag_indices) - 1, 2):
        ki, vi = tag_indices[i], tag_indices[i + 1]
        if ki < len(keys) and vi < len(values):
            props[keys[ki]] = values[vi]
    return VectorTileFeature(
        feature_id=feature_id, geom_type=geom_type, properties=props, geometry=geometry
    )


def _decode_layer(buf: bytes) -> VectorTileLayer:
    r = _Reader(buf)
    name = ""
    version = 1
    extent = 4096
    keys: list[str] = []
    values: list[Any] = []
    feature_bufs: list[bytes] = []
    while not r.eof():
        field_no, wire = r.tag()
        if field_no == 1:
            name = r.bytes().decode("utf-8", errors="replace")
        elif field_no == 2:
            feature_bufs.append(r.bytes())
        elif field_no == 3:
            keys.append(r.bytes().decode("utf-8", errors="replace"))
        elif field_no == 4:
            values.append(_decode_value(r.bytes()))
        elif field_no == 5:
            extent = r.varint()
        elif field_no == 15:
            version = r.varint()
        else:
            r.skip(wire)
    return VectorTileLayer(
        name=name,
        version=version,
        extent=extent,
        features=[_decode_feature(fb, keys, values) for fb in feature_bufs],
    )


def decode_tile(data: bytes) -> VectorTile:
    """Decode a raw MVT payload into a :class:`VectorTile`."""
    r = _Reader(data)
    tile = VectorTile()
    try:
        while not r.eof():
            field_no, wire = r.tag()
            if field_no == 3 and wire == _WIRE_LENGTH:
                layer = _decode_layer(r.bytes())
                tile.layers[layer.name] = layer
            else:
                r.skip(wire)
    except CitizenTileError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise CitizenTileError(f"failed to decode vector tile: {exc}") from exc
    return tile
