"""A tank: from the height of the fuel to its volume.

Heights are measured from the floor the tank stands on, as a dipstick or a ruler at the outside wall reads them. The
offset is the height at which the tank is empty (its bottom, or what it stands on); readings below it count as empty.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from enum import StrEnum


class Shape(StrEnum):
    LINEAR = "linear"  # upright walls (battery tank, cuboid): litres per cm
    HORIZONTAL_CYLINDER = "horizontal_cylinder"  # a steel tank on its side
    TABLE = "table"  # the manufacturer's table of cm and litres


@dataclass(frozen=True)
class TankSpec:
    id: str
    name: str
    capacity: float  # litres
    shape: Shape = Shape.LINEAR
    per_cm: float | None = None  # linear: litres per cm
    diameter_cm: float | None = None  # horizontal cylinder
    length_cm: float | None = None  # horizontal cylinder
    table: tuple[tuple[float, float], ...] = ()  # (cm, litres), sorted by cm
    offset_cm: float = 0.0
    residue: float = 0.0  # litres the burner cannot draw
    level_key: str | None = None  # a level sensor, optional

    @property
    def converts_height(self) -> bool:
        """Whether a height in cm can be converted to litres."""
        if self.shape is Shape.LINEAR:
            return bool(self.per_cm)
        if self.shape is Shape.HORIZONTAL_CYLINDER:
            return bool(self.diameter_cm and self.length_cm)
        return len(self.table) >= 1

    def volume(self, height_cm: float) -> float:
        """Litres at a height. ValueError if the tank has no dimensions for it."""
        if not self.converts_height:
            raise ValueError(f"tank {self.name} has no dimensions to convert a height")
        h = max(height_cm - self.offset_cm, 0.0)
        if self.shape is Shape.LINEAR:
            assert self.per_cm is not None
            return h * self.per_cm
        if self.shape is Shape.HORIZONTAL_CYLINDER:
            assert self.diameter_cm is not None and self.length_cm is not None
            return _segment_area(self.diameter_cm / 2, min(h, self.diameter_cm)) * self.length_cm / 1000
        return _interpolate(self.table, h)

    def litres_per_cm(self, height_cm: float) -> float:
        """How many litres one cm more makes at this height: the uncertainty of a reading in litres per cm."""
        if not self.converts_height:
            return 0.0
        return max(self.volume(height_cm + 0.5) - self.volume(height_cm - 0.5), 0.0)

    def height(self, volume: float) -> float:
        """The height of the fuel's surface above the floor at a volume: the inverse of volume(), offset included.
        ValueError if the tank has no dimensions for it."""
        if not self.converts_height:
            raise ValueError(f"tank {self.name} has no dimensions to convert a volume")
        if volume <= 0:
            return self.offset_cm
        if self.shape is Shape.LINEAR:
            assert self.per_cm is not None
            return self.offset_cm + volume / self.per_cm
        low, high = self.offset_cm, self.offset_cm + 1.0
        while self.volume(high) < volume:
            if high - self.offset_cm > 1e5 or self.volume(high) <= self.volume(low):
                return high  # a full cylinder or a flat table: no height gives more
            low, high = high, self.offset_cm + 2 * (high - self.offset_cm)
        for _ in range(60):
            mid = (low + high) / 2
            if self.volume(mid) < volume:
                low = mid
            else:
                high = mid
        return high


def _segment_area(r: float, h: float) -> float:
    """Area in cm² of a circle of radius r filled to height h."""
    if h <= 0:
        return 0.0
    if h >= 2 * r:
        return math.pi * r * r
    return r * r * math.acos((r - h) / r) - (r - h) * math.sqrt(2 * r * h - h * h)


def _interpolate(table: tuple[tuple[float, float], ...], h: float) -> float:
    """Linear between the points; from 0 cm/0 L to the first, beyond the last on the slope of the last two."""
    points = ((0.0, 0.0), *table) if table[0][0] > 0 else table
    heights = [p[0] for p in points]
    i = bisect_right(heights, h) - 1
    if i < 0:
        return 0.0
    if i >= len(points) - 1:
        if len(points) < 2:
            return points[-1][1]
        (h0, v0), (h1, v1) = points[-2], points[-1]
    else:
        (h0, v0), (h1, v1) = points[i], points[i + 1]
    if h1 == h0:
        return v1
    return max(v0 + (v1 - v0) * (h - h0) / (h1 - h0), 0.0)


def parse_table(text: str) -> tuple[tuple[float, float], ...]:
    """Pairs of cm and litres, one per line or separated by ';': "10: 95", "10 = 95" or "10 95". ValueError if a
    line has no two numbers, a number is negative, or the heights are not all different."""
    pairs: list[tuple[float, float]] = []
    for raw in text.replace(";", "\n").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.replace(":", " ").replace("=", " ").replace(",", ".").split()
        if len(parts) != 2:
            raise ValueError(line)
        cm, litres = float(parts[0]), float(parts[1])
        if cm < 0 or litres < 0:
            raise ValueError(line)
        pairs.append((cm, litres))
    pairs.sort()
    if not pairs or len({cm for cm, _ in pairs}) != len(pairs):
        raise ValueError(text)
    return tuple(pairs)


def format_table(table: tuple[tuple[float, float], ...]) -> str:
    return "\n".join(f"{_number(cm)}: {_number(litres)}" for cm, litres in table)


def _number(value: float) -> str:
    return f"{value:g}"
