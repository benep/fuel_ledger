"""The correction factor from dipstick readings.

Between two readings, the tanks lost what the burner drew from them. The ledger knows the burner's consumption at
factor 1 (run time × nozzle) between the same moments, so the factor is their ratio:

    k = (litres before + delivered − litres after) / consumption at factor 1

- A reading belongs to a survey: all tanks, read one after the other within SURVEY_WINDOW_S. With several tanks on
  one suction line it is only their sum that the burner empties, so only complete surveys count. A tank read again
  after the burner ran starts the next survey; read again without, the second reading corrects the first.
- Two surveys are compared only if every tank was read at the same point both times: readings from another side of
  a tank are not comparable (the floor slopes, a tank stands on something).
- A delivery in between counts with its amount, if the amount was entered; one without makes the pair unusable.
- Of all usable pairs, the one with the most burner consumption in between wins: the reading errors weigh least.
- The uncertainty comes from the reading accuracy in cm, converted to litres at each reading's height.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .tank import TankSpec

SURVEY_WINDOW_S = 2 * 3600.0


@dataclass(frozen=True)
class MeasuredFactor:
    value: float
    uncertainty: float  # ± in the same unit as the factor
    start: float  # time of the first survey
    end: float  # time of the second survey
    nominal: float  # litres at factor 1 between them
    measured: float  # litres the tanks lost between them, deliveries included

    def as_dict(self) -> dict[str, float]:
        return {
            "value": self.value,
            "uncertainty": self.uncertainty,
            "start": self.start,
            "end": self.end,
            "nominal": self.nominal,
            "measured": self.measured,
        }


@dataclass(frozen=True)
class _Survey:
    time: float
    volume: float
    nominal: float
    points: tuple[tuple[str, str], ...]  # (tank, point), sorted
    variance: float  # litres²


def surveys(tanks: Sequence[TankSpec], readings: Sequence[Mapping[str, Any]], accuracy_cm: float) -> list[_Survey]:
    """Complete surveys of the current tanks, in time order. Readings of tanks removed since are left out."""
    by_id = {t.id: t for t in tanks}
    result: list[_Survey] = []
    group: dict[str, Mapping[str, Any]] = {}
    start: float | None = None

    def close() -> None:
        if group and set(by_id) <= set(group):
            chosen = [group[tank_id] for tank_id in by_id]
            variance = 0.0
            for reading in chosen:
                tank = by_id[reading["tank"]]
                height = reading.get("height_cm")
                if height is None and tank.converts_height:
                    height = tank.height(reading["volume"])  # read in litres: the height it stands for
                per_cm = tank.litres_per_cm(height) if height is not None else (tank.per_cm or 0.0)
                variance += (accuracy_cm * per_cm) ** 2
            result.append(
                _Survey(
                    time=max(r["time"] for r in chosen),
                    volume=sum(r["volume"] for r in chosen),
                    nominal=max(r["nominal"] for r in chosen),
                    points=tuple(sorted((r["tank"], r["point"]) for r in chosen)),
                    variance=variance,
                )
            )

    for reading in sorted(readings, key=lambda r: r["time"]):
        if reading["tank"] not in by_id:
            continue
        again = group.get(reading["tank"])
        if (
            start is None
            or reading["time"] - start > SURVEY_WINDOW_S
            or (again is not None and reading["nominal"] > again["nominal"])
        ):
            close()
            group, start = {}, reading["time"]
        group[reading["tank"]] = reading  # without consumption in between, a second reading corrects the first
    close()
    return result


def measure(
    tanks: Sequence[TankSpec],
    readings: Sequence[Mapping[str, Any]],
    deliveries: Sequence[Mapping[str, Any]],
    accuracy_cm: float,
) -> MeasuredFactor | None:
    """The factor from the best pair of surveys, or None if there is none."""
    found = surveys(tanks, readings, accuracy_cm)
    best: MeasuredFactor | None = None
    for i, first in enumerate(found):
        for second in found[i + 1 :]:
            nominal = second.nominal - first.nominal
            if first.points != second.points or nominal <= 0:
                continue
            between = [d for d in deliveries if first.time < d["time"] <= second.time]
            if any(not d.get("amount_entered") for d in between):
                continue
            measured = first.volume + sum(d["amount"] for d in between) - second.volume
            if measured <= 0:
                continue
            if best is None or nominal > best.nominal:
                best = MeasuredFactor(
                    value=measured / nominal,
                    uncertainty=math.sqrt(first.variance + second.variance) / nominal,
                    start=first.time,
                    end=second.time,
                    nominal=nominal,
                    measured=measured,
                )
    return best
