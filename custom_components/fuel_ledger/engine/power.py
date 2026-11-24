"""Components behind one power meter: which of them run, and what each draws.

Many heating systems have a single power meter in front of the boiler (a smart plug, a DIN rail meter). Each
component draws a typical power: the burner, the oil preheater, the pumps. The measured power is the base load plus
the components that run, so the combination whose typical powers come closest to the measurement is the one that
runs. With only the burner known, this is a threshold halfway between base load and burner.

- The preheater warms the oil before the burner starts; it is not counted while the burner runs.
- Each component confirms a change only after its delay: a pump has to show for a minute before it counts as running,
  so the short peak of the ignition is not taken for a pump. A confirmed change counts from when it began.
- The power of a running component is its typical power; what the measurement has above or below the sum goes to the
  burner while it runs (its draw varies most), else to the only running component, else in proportion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations


class ComponentKind(StrEnum):
    BURNER = "burner"
    PREHEATER = "preheater"
    CIRCUIT_PUMP = "circuit_pump"
    HOT_WATER_PUMP = "hot_water_pump"
    OTHER = "other"


# Seconds a change has to last before it counts: (on, off).
DEFAULT_DELAYS: dict[ComponentKind, tuple[float, float]] = {
    ComponentKind.BURNER: (0.0, 0.0),
    ComponentKind.PREHEATER: (0.0, 0.0),
    ComponentKind.CIRCUIT_PUMP: (60.0, 120.0),
    ComponentKind.HOT_WATER_PUMP: (60.0, 120.0),
    ComponentKind.OTHER: (0.0, 0.0),
}
MAX_COMPONENTS = 8


@dataclass(frozen=True)
class ComponentSpec:
    id: str
    name: str
    kind: ComponentKind
    power: float  # W, typical
    on_delay_s: float | None = None
    off_delay_s: float | None = None

    @property
    def delays(self) -> tuple[float, float]:
        on, off = DEFAULT_DELAYS[self.kind]
        return (
            on if self.on_delay_s is None else self.on_delay_s,
            off if self.off_delay_s is None else self.off_delay_s,
        )


@dataclass(frozen=True)
class PowerSpec:
    key: str  # the power sensor
    base: float = 0.0  # W drawn all the time (the boiler's control)
    components: tuple[ComponentSpec, ...] = ()

    @property
    def burner(self) -> ComponentSpec | None:
        return next((c for c in self.components if c.kind is ComponentKind.BURNER), None)


@dataclass(frozen=True)
class Change:
    component: str
    on: bool
    time: float  # when the change began


class Disaggregator:
    def __init__(self, spec: PowerSpec) -> None:
        self.spec = spec
        self.watts: float | None = None
        self.raw: dict[str, bool] = {}  # the best combination for the last measurement
        self.state: dict[str, bool | None] = {c.id: None for c in spec.components}  # confirmed
        self._since: dict[str, float] = {}  # when raw last changed
        self._combinations = self._all_combinations()

    def update(self, ts: float, watts: float | None) -> list[Change]:
        """A new measurement; None while the meter is unavailable (every component unknown)."""
        self.watts = watts
        if watts is None:
            self.raw = {}
            self._since = {}
            self.state = dict.fromkeys(self.state)
            return []
        running = self._match(watts)
        for component in self.spec.components:
            on = component.id in running
            if self.raw.get(component.id) != on:
                self.raw[component.id] = on
                self._since[component.id] = ts
        return self.tick(ts)

    def tick(self, ts: float) -> list[Change]:
        """Confirm the changes whose delay has passed."""
        changes: list[Change] = []
        for component in self.spec.components:
            raw = self.raw.get(component.id)
            if raw is None or raw == self.state[component.id]:
                continue
            since = self._since[component.id]
            if self.state[component.id] is None:
                self.state[component.id] = raw  # the first measurement: no change to confirm
                continue
            on_delay, off_delay = component.delays
            if ts - since >= (on_delay if raw else off_delay):
                self.state[component.id] = raw
                changes.append(Change(component.id, raw, since))
        return changes

    def next_due(self) -> float | None:
        """When the next pending change is confirmed, if one is pending."""
        due: list[float] = []
        for component in self.spec.components:
            raw = self.raw.get(component.id)
            if raw is None or raw == self.state[component.id] or self.state[component.id] is None:
                continue
            on_delay, off_delay = component.delays
            due.append(self._since[component.id] + (on_delay if raw else off_delay))
        return min(due) if due else None

    def power(self, component_id: str) -> float | None:
        """The power of a component right now, from the last measurement."""
        if self.watts is None:
            return None
        running = [c for c in self.spec.components if self.raw.get(c.id)]
        if not any(c.id == component_id for c in running):
            return 0.0
        rest = self.watts - self.spec.base - sum(c.power for c in running)
        component = next(c for c in running if c.id == component_id)
        burner = next((c for c in running if c.kind is ComponentKind.BURNER), None)
        if burner is not None:
            share = 1.0 if component is burner else 0.0
        elif len(running) == 1:
            share = 1.0
        else:
            total = sum(c.power for c in running)
            share = component.power / total if total else 1 / len(running)
        return max(component.power + rest * share, 0.0)

    def _all_combinations(self) -> list[tuple[float, int, frozenset[str]]]:
        """(expected watts, size, component IDs) of every combination that can run together."""
        components = self.spec.components[:MAX_COMPONENTS]
        result = []
        for size in range(len(components) + 1):
            for combo in combinations(components, size):
                kinds = [c.kind for c in combo]
                if ComponentKind.BURNER in kinds and ComponentKind.PREHEATER in kinds:
                    continue
                result.append((self.spec.base + sum(c.power for c in combo), size, frozenset(c.id for c in combo)))
        return result

    def _match(self, watts: float) -> frozenset[str]:
        """The combination closest to the measurement; of equally close ones, the one with fewer components."""
        return min(self._combinations, key=lambda c: (abs(watts - c[0]), c[1]))[2]
