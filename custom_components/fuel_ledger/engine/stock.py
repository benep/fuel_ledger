"""Where the fuel goes in several tanks: which tank the burner draws from, and how a delivery fills them.

Tanks are connected in one of two ways:

- **At the bottom** (battery tanks with a connecting pipe): communicating vessels, the surfaces stand at the same
  height. A reading of one tank tells the others.
- **On the suction side only** (each tank its own suction pipe, joined by a T-piece): each tank keeps its own level.
  At the small flow of a burner, the pipe whose surface stands higher delivers: the burner draws from the fuller tank
  until both surfaces stand at the same height, then from both. Heights are measured from the floor, so a tank
  standing higher (on a base, on wood) counts with its surface, not its content.

Both come down to the same rule: what the burner draws lowers the highest surfaces first. A delivery is assumed to
fill the lowest surfaces first; with tanks joined only on the suction side, how a delivery spreads is not known, so
readings after a delivery correct it. Tanks without dimensions are drawn from in proportion to their content and
filled in proportion to their free space.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum

from .tank import TankSpec

ITERATIONS = 60


class Link(StrEnum):
    BOTTOM = "bottom"
    SUCTION = "suction"


Volumes = dict[str, float]


def _dimensions(tanks: Sequence[TankSpec]) -> bool:
    return bool(tanks) and all(t.converts_height for t in tanks)


def draw(tanks: Sequence[TankSpec], volumes: Mapping[str, float], litres: float) -> Volumes:
    """The volumes after the burner drew litres. Never below 0."""
    result = {t.id: max(volumes[t.id], 0.0) for t in tanks}
    total = sum(result.values())
    if litres <= 0:
        return result
    if litres >= total:
        return dict.fromkeys(result, 0.0)
    if not _dimensions(tanks):
        left = (total - litres) / total
        return {k: v * left for k, v in result.items()}

    def removed(level: float) -> float:
        return sum(max(result[t.id] - t.volume(level), 0.0) for t in tanks)

    low, high = 0.0, max(t.height(result[t.id]) for t in tanks)
    for _ in range(ITERATIONS):
        mid = (low + high) / 2
        if removed(mid) > litres:
            low = mid
        else:
            high = mid
    return {t.id: min(result[t.id], t.volume(high)) for t in tanks}


def fill(tanks: Sequence[TankSpec], volumes: Mapping[str, float], litres: float) -> Volumes:
    """The volumes after litres were added: lowest surfaces first, each tank up to its capacity; what does not fit
    any more is spread in proportion to the capacities (the capacity was set too low)."""
    result = {t.id: max(volumes.get(t.id, 0.0), 0.0) for t in tanks}
    if litres <= 0:
        return result
    if len(tanks) == 1:
        return {tanks[0].id: result[tanks[0].id] + litres}
    free = {t.id: max(t.capacity - result[t.id], 0.0) for t in tanks}
    room = sum(free.values())
    if litres >= room:
        rest = litres - room
        capacity = sum(t.capacity for t in tanks) or 1.0
        return {t.id: result[t.id] + free[t.id] + rest * t.capacity / capacity for t in tanks}
    if not _dimensions(tanks):
        return {k: v + litres * free[k] / room for k, v in result.items()}

    def added(level: float) -> float:
        return sum(max(min(t.volume(level), t.capacity) - result[t.id], 0.0) for t in tanks)

    low = min(t.height(result[t.id]) for t in tanks)
    high = max(t.height(t.capacity) for t in tanks)
    for _ in range(ITERATIONS):
        mid = (low + high) / 2
        if added(mid) < litres:
            low = mid
        else:
            high = mid
    return {t.id: max(result[t.id], min(t.volume(high), t.capacity)) for t in tanks}


def reading(
    tanks: Sequence[TankSpec],
    volumes: Mapping[str, float] | None,
    link: Link,
    tank_id: str,
    volume: float,
    assumed: frozenset[str] = frozenset(),
) -> tuple[Volumes, frozenset[str]]:
    """The volumes after a reading of one tank, and which tanks are still only assumed.

    Connected at the bottom, the others stand at the same height. Otherwise the others keep their content, unless
    it was only assumed (a total set or delivered, spread by assumption): then the total stays, and the tanks not
    read yet share what the reading leaves of it.
    """
    tank = next(t for t in tanks if t.id == tank_id)
    if link is Link.BOTTOM and _dimensions(tanks):
        level = tank.height(volume)
        return {t.id: volume if t.id == tank_id else t.volume(level) for t in tanks}, frozenset()
    result = dict(volumes or {})
    others = [t for t in tanks if t.id != tank_id and t.id in assumed]
    if others and all(t.id in result for t in tanks):
        known = sum(result[t.id] for t in tanks if t.id != tank_id and t.id not in assumed)
        left = max(sum(result.values()) - volume - known, 0.0)
        result.update(fill(others, {}, left))
    result[tank_id] = volume
    return result, assumed - {tank_id}


def scale(tanks: Sequence[TankSpec], volumes: Mapping[str, float], total: float) -> Volumes:
    """Volumes with another total, in the same proportion (the rest before a delivery, corrected)."""
    current = sum(volumes.values())
    if current <= 0:
        return fill(tanks, {}, total)
    return {k: v * total / current for k, v in volumes.items()}
