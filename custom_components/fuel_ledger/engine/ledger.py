"""The books of one fuel store: consumption, energy, heat, cost and CO₂ as counters, the stock in each tank, and
the events that change them (stock corrections, deliveries, dipstick readings, a new correction factor).

Every call carries its time, so the same ledger runs live and replays the past (backfill, simulation).

- **Counters** only grow by what is booked from now on, at the values that apply now: a new factor, heating value,
  price or efficiency never changes what was booked before. That keeps the Energy dashboard from jumping.
- **The stock** is calculated from the events in time order: the content of each tank after the last one, minus what
  the burner drew since (stock.py decides from which tank). An event may be dated back, e.g. a reading entered the
  day after: the consumption at its moment is interpolated from the checkpoints the ledger keeps, and the stock is
  calculated again from there. Price, heating value and CO₂ of the fuel in the tanks follow from the same events;
  their new values count for what is booked from then on.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .calibration import MeasuredFactor, measure
from .spec import InputKind, LedgerSpec, Level, Origin, worst
from .stock import Link, Volumes, draw, fill, reading, scale
from .tank import TankSpec

# Home Assistant's rule for total_increasing: a drop below 90 % of the reading before is a new cycle from 0.
RESET_FRACTION = 0.9
HOUR_S = 3600.0
DAY_S = 86400.0
CHECKPOINTS_FINE_S = 2 * DAY_S  # every interval; older ones are thinned to one per hour
CHECKPOINTS_KEEP_S = 400 * DAY_S
MIN_RANGE_HISTORY_S = DAY_S  # the range needs at least a day of consumption
POOL = "_"  # the one store of an entry without tanks

KIND_CORRECTION = "correction"
KIND_DELIVERY = "delivery"
KIND_READING = "reading"
KIND_MEASUREMENT = "measurement"


class LedgerError(Exception):
    """An event the ledger cannot book. The key is the translation key of the error, the placeholders fill it."""

    def __init__(self, key: str, **placeholders: Any) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = {k: str(v) for k, v in placeholders.items()}


class _Counter:
    """Follows a cumulative reading and returns its increases, by Home Assistant's rules for total_increasing:

    - An increase counts in full.
    - A drop below RESET_FRACTION of the reading before is a reset: the new reading counts in full, from 0, and a
      debt is forgotten.
    - A smaller drop is a dip; it is kept as a debt the next increases pay off first.
    - Unavailable (None) or negative: skipped, the next valid reading is compared with the last valid one.

    One exception to Home Assistant: a device that reports 0 for a moment after a restart and then its old reading
    again. As long as a reset has not counted anything yet, a reading back at or above the one before the reset
    only counts what it is above it.
    """

    __slots__ = ("debt", "key", "last", "reset_from")

    def __init__(self, key: str) -> None:
        self.key = key
        self.last: float | None = None
        self.debt = 0.0
        self.reset_from: float | None = None  # the reading before a reset that has not counted anything yet

    def update(self, value: float | None) -> float:
        if value is None or value < 0:
            return 0.0
        last, self.last = self.last, float(value)
        if last is None:
            return 0.0
        if self.reset_from is not None and self.last >= self.reset_from:
            increase, self.reset_from = self.last - self.reset_from, None  # only a glitch: back where it was
        elif self.last < last * RESET_FRACTION:
            # Back to 0: remember from where, in case it is only a glitch. Anything above 0 counts at once.
            self.reset_from = (self.reset_from or last) if self.last == 0 else None
            self.debt = 0.0
            increase = self.last
        elif self.last < last:
            self.debt += last - self.last
            return 0.0
        else:
            increase = self.last - last
            if increase > 0:
                self.reset_from = None  # counting from 0 for real
        paid = min(increase, self.debt)
        self.debt -= paid
        return increase - paid

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "last": self.last, "debt": self.debt, "reset_from": self.reset_from}

    def restore(self, stored: Mapping[str, Any]) -> None:
        if stored.get("key") != self.key:
            return  # another input since: it starts over from its next reading
        self.last = None if stored.get("last") is None else float(stored["last"])
        self.debt = float(stored.get("debt") or 0.0)
        self.reset_from = None if stored.get("reset_from") is None else float(stored["reset_from"])


@dataclass
class _Stock:
    """The tanks after a run of events: their contents at a consumption, and the values of the fuel in them."""

    consumption: float = float("-inf")  # of the last event; before the setup it is below 0 (history.py)
    volumes: Volumes | None = None  # None: unknown; a tank missing: unknown so far
    price: float | None = None
    price_origin: Origin = Origin.DEFAULT
    heating_value: float | None = None
    heating_value_origin: Origin = Origin.DEFAULT
    co2: float | None = None
    co2_origin: Origin = Origin.DEFAULT
    last_event: dict[str, Any] = field(default_factory=dict)
    assumed: frozenset[str] = frozenset()  # tanks whose content is spread by assumption, not read


class Ledger:
    def __init__(self, spec: LedgerSpec) -> None:
        self.spec = spec
        self.time: float | None = None  # the latest moment the ledger was told about
        # Counters
        self.consumption = 0.0  # litres, at the factor of their time (measured for a meter)
        self.nominal = 0.0  # litres at factor 1: run time × nozzle; for a meter the same as the consumption
        self.runtime_h = 0.0  # burner hours booked (not for a meter)
        self.starts = 0  # burner input only
        self.energy = 0.0  # kWh in the fuel
        self.heat = 0.0  # kWh of heat
        self.cost = 0.0  # in the currency of Home Assistant
        self.co2 = 0.0  # kg
        self.factor = 1.0
        self.factor_origin = Origin.DEFAULT
        # Inputs
        self._counter = _Counter(spec.burner.key)
        self.running = False  # the burner runs, as far as known
        self._on_since: float | None = None  # burner input: counting from here
        self._prepurge_left = 0.0
        self._burner_known = True  # False after unavailable: the next "on" is not a start
        # History
        self.checkpoints: list[list[float]] = []  # [time, consumption, nominal]
        self._pruned_hour: int | None = None
        self.deliveries: list[dict[str, Any]] = []
        self.readings: list[dict[str, Any]] = []
        self.corrections: list[dict[str, Any]] = []
        self.measurement: dict[str, Any] | None = None  # the latest of the level sensors
        self.factor_changes: list[dict[str, Any]] = []
        self._seq = 0
        self._state = _Stock()
        self._sensors_ok = False  # the level sensors reported all tanks at the last interval
        self.restored = False

    # --- Inputs ------------------------------------------------------------------------------------------------

    def observe(self, ts: float, value: float | bool | None, *, initial: bool = False) -> None:
        """A reading of the input: hours (run time), litres (meter), or on/off (burner, power). None when unavailable.

        Initial: the state found at the start, not a change. A burner found running is counted from now, without a
        start and its prepurge: it started while Home Assistant was not looking.
        """
        self._advance(ts)
        kind = self.spec.burner.kind
        if kind.counts_itself:
            self._burner(ts, None if value is None else bool(value), initial=initial)
            return
        increase = self._counter.update(None if value is None or isinstance(value, bool) else float(value))
        if increase <= 0:
            return
        if kind is InputKind.METER:
            self._book(increase, increase)
        else:
            self._book_hours(increase)

    def burner_state(self, ts: float, on: bool | None) -> None:
        """The burner's on/off state, for the flow rate, when the consumption comes from a counter."""
        self._advance(ts)
        if self.spec.burner.kind.counts_itself:
            self._burner(ts, on, initial=False)
        else:
            self.running = bool(on)

    def settle(self, ts: float) -> None:
        """Book a running burner up to now (before saving, at each interval)."""
        self._advance(ts)
        if self._on_since is not None:
            self._run_until(ts)

    def close_interval(self, ts: float) -> None:
        self.settle(ts)
        if not self.checkpoints or ts > self.checkpoints[-1][0]:
            self.checkpoints.append([ts, self.consumption, self.nominal])
        hour = int(ts // HOUR_S)
        if hour != self._pruned_hour:
            self._pruned_hour = hour
            self._prune(ts)

    def seed(self, points: list[list[float]]) -> int:
        """Checkpoints from before the first one, counted back from the start (history.past_checkpoints): the
        consumption before the setup, for the range and for events dated before it. Counters stay as they are.
        Returns how many were taken."""
        first = self.checkpoints[0][0] if self.checkpoints else self.time
        earlier = [list(map(float, p)) for p in points if first is None or p[0] < first]
        self.checkpoints = earlier + self.checkpoints
        return len(earlier)

    def measure_stock(self, ts: float, volumes: Mapping[str, float] | None) -> None:
        """The contents of all tanks by their level sensors, or None if one is unavailable. A measurement replaces
        the calculated stock; without one, the calculation continues from the last measurement."""
        self._advance(ts)
        self._sensors_ok = volumes is not None
        if volumes is None:
            return
        self.measurement = {
            "kind": KIND_MEASUREMENT,
            "time": ts,
            "seq": self._next_seq(),
            "consumption": self.consumption,
            "volumes": {k: max(float(v), 0.0) for k, v in volumes.items()},
        }
        self._replay()

    # --- Events ------------------------------------------------------------------------------------------------

    def record_delivery(
        self,
        ts: float,
        *,
        amount: float | None = None,
        level_after: float | None = None,
        total_price: float | None = None,
        energy: float | None = None,
        co2: float | None = None,
        product: str | None = None,
        supplier: str | None = None,
    ) -> dict[str, Any]:
        """A delivery: fills the tanks and blends price, heating value and CO₂ with what was left.

        Amount or stock after the delivery, at least one. With both, the rest before is stock after − amount.
        Totals as on the invoice (price incl. tax, energy content in kWh, CO₂ in kg); per litre is worked out here.
        A total left out keeps the value as it was.
        """
        if amount is None and level_after is None:
            raise LedgerError("amount_or_level")
        if (amount is not None and amount <= 0) or (level_after is not None and level_after < 0):
            raise LedgerError("not_positive")
        if amount is not None and level_after is not None and level_after < amount:
            raise LedgerError("level_below_amount")
        self._check_time(ts)
        consumption, _ = self._at(ts)
        before = self._state_at(ts, consumption)
        rest = _total(self.spec, before.volumes)
        if amount is None:
            assert level_after is not None
            if rest is not None and level_after - max(rest, 0.0) <= 0:
                raise LedgerError("level_below_stock", stock=round(rest))
        elif level_after is None and rest is None:
            raise LedgerError("stock_unknown")
        if amount is None and rest is None and any(v is not None for v in (total_price, energy, co2)):
            raise LedgerError("amount_needed")
        record = {
            "kind": KIND_DELIVERY,
            "time": ts,
            "seq": self._next_seq(),
            "recorded": self.time,
            "consumption": consumption,
            "amount": amount,
            "amount_entered": amount is not None,
            # The amount as it looked when entered: the per-litre values of the invoice stay with it if a reading
            # dated back makes the rest before look as large as the stock after.
            "amount_at_entry": amount if amount is not None else None if rest is None else level_after - rest,
            "level_after": level_after,
            "level_after_entered": level_after is not None,
            "total_price": total_price,
            "energy": energy,
            "co2": co2,
            "product": product,
            "supplier": supplier,
        }
        self.deliveries.append(record)
        self._replay()
        return record

    def set_stock(
        self,
        ts: float,
        volume: float,
        *,
        price: float | None = None,
        heating_value: float | None = None,
        co2: float | None = None,
    ) -> dict[str, Any]:
        """Set the stock without a delivery, e.g. to start with what is in the tanks, optionally with the values of
        that fuel (per litre). Values left out stay as they are. The tanks are filled from the bottom up."""
        if volume < 0 or any(v is not None and v <= 0 for v in (price, heating_value, co2)):
            raise LedgerError("not_positive")
        self._check_time(ts)
        consumption, _ = self._at(ts)
        record = {
            "kind": KIND_CORRECTION,
            "time": ts,
            "seq": self._next_seq(),
            "recorded": self.time,
            "consumption": consumption,
            "volume": volume,
            "price": price,
            "heating_value": heating_value,
            "co2": co2,
            "previous": _total(self.spec, self._state_at(ts, consumption).volumes),
        }
        self.corrections.append(record)
        self._replay()
        return record

    def record_level(
        self,
        ts: float,
        tank_id: str,
        point: str,
        *,
        height_cm: float | None = None,
        volume: float | None = None,
    ) -> dict[str, Any]:
        """A dipstick reading of one tank, in cm or in litres, at a measuring point.

        It sets the content of the tank at that moment (connected at the bottom: of all tanks), and the stock is
        calculated from there. Kept with the consumption of that moment, it also gives the measured factor.
        """
        tank = self.spec.tank(tank_id)
        if tank is None:
            raise LedgerError("tank_not_found")
        if (height_cm is None) == (volume is None):
            raise LedgerError("height_or_volume")
        if (height_cm is not None and height_cm < 0) or (volume is not None and volume < 0):
            raise LedgerError("not_positive")
        point = (point or "").strip()
        if not point:
            raise LedgerError("point_required")
        if height_cm is not None:
            if not tank.converts_height:
                raise LedgerError("tank_without_dimensions", tank=tank.name)
            volume = tank.volume(height_cm)
        self._check_time(ts)
        consumption, nominal = self._at(ts)
        record = {
            "kind": KIND_READING,
            "time": ts,
            "seq": self._next_seq(),
            "recorded": self.time,
            "tank": tank_id,
            "point": point,
            "height_cm": height_cm,
            "volume": volume,
            "consumption": consumption,
            "nominal": nominal,
            "calculated": _tank_volume(self._state_at(ts, consumption).volumes, tank_id),
        }
        index = bisect_right([r["time"] for r in self.readings], ts)
        self.readings.insert(index, record)
        self._replay()
        return record

    def set_factor(self, ts: float, value: float, origin: Origin = Origin.SET) -> None:
        """A new correction factor, from now on. What was booked stays."""
        if value <= 0:
            raise LedgerError("not_positive")
        self.settle(ts)
        self.factor = value
        self.factor_origin = origin
        self.factor_changes.append(
            {
                "time": ts,
                "value": value,
                "origin": str(origin),
                "consumption": self.consumption,
                "nominal": self.nominal,
            }
        )

    # --- Results -----------------------------------------------------------------------------------------------

    @property
    def price(self) -> float | None:
        """Per litre; None: unknown, no cost is booked."""
        return self._state.price

    @property
    def price_origin(self) -> Origin:
        return self._state.price_origin

    @property
    def heating_value(self) -> float | None:
        """kWh per litre from an event; None: the spec's default."""
        return self._state.heating_value

    @property
    def heating_value_origin(self) -> Origin:
        return self._state.heating_value_origin

    @property
    def co2_factor(self) -> float | None:
        return self._state.co2

    @property
    def co2_origin(self) -> Origin:
        return self._state.co2_origin

    @property
    def current_heating_value(self) -> float:
        value = self._state.heating_value
        return value if value is not None else self.spec.default_heating_value

    @property
    def current_co2(self) -> float:
        value = self._state.co2
        return value if value is not None else self.spec.default_co2

    @property
    def price_per_kwh(self) -> float | None:
        return None if self.price is None else self.price / self.current_heating_value

    @property
    def flow(self) -> float | None:
        """Litres per hour right now, while the burner runs; None if the ledger cannot tell (a meter, or a run time
        counter without the burner's state)."""
        burner = self.spec.burner
        if burner.kind is InputKind.METER or (burner.kind is InputKind.RUNTIME and not self.spec.knows_burner_state):
            return None
        if not self.running:
            return 0.0
        return (burner.nominal_flow or 0.0) * self.factor

    @property
    def tank_volumes(self) -> Volumes | None:
        """Litres in each tank now; None while not every tank is known."""
        state = self._state
        if not _complete(self.spec, state.volumes):
            return None
        assert state.volumes is not None
        return draw(_tanks(self.spec), state.volumes, self.consumption - state.consumption)

    def tank_volume(self, tank_id: str) -> float | None:
        volumes = self.tank_volumes
        return None if volumes is None else volumes.get(tank_id)

    def tank_height(self, tank_id: str) -> float | None:
        """Height of the surface in a tank above the floor, as a reading from the floor would show it."""
        tank, volume = self.spec.tank(tank_id), self.tank_volume(tank_id)
        if tank is None or volume is None or not tank.converts_height:
            return None
        return tank.height(volume)

    @property
    def stock(self) -> float | None:
        """Litres in all tanks, never below 0."""
        volumes = self.tank_volumes
        return None if volumes is None else sum(volumes.values())

    @property
    def usable(self) -> float | None:
        volumes = self.tank_volumes
        if volumes is None:
            return None
        if not self.spec.tanks:
            return volumes[POOL]
        return sum(max(volumes[t.id] - t.residue, 0.0) for t in self.spec.tanks)

    @property
    def fill_percent(self) -> float | None:
        capacity, stock = self.spec.capacity, self.stock
        if not capacity or stock is None:
            return None
        return stock / capacity * 100

    @property
    def low(self) -> bool | None:
        capacity, usable = self.spec.capacity, self.usable
        if not capacity or usable is None:
            return None
        return usable <= capacity * self.spec.low_percent / 100

    def daily_use(self, ts: float) -> float | None:
        """Litres per day over the range window, or over what the ledger has of it (at least a day)."""
        if not self.checkpoints:
            return None
        start = max(ts - self.spec.range_days * DAY_S, self.checkpoints[0][0])
        if ts - start < MIN_RANGE_HISTORY_S:
            return None
        consumption, _ = self._at(start)
        return (self.consumption - consumption) / ((ts - start) / DAY_S)

    def range_days(self, ts: float) -> float | None:
        usable, use = self.usable, self.daily_use(ts)
        if usable is None or not use or use <= 0:
            return None
        return usable / use

    def measured_factor(self) -> MeasuredFactor | None:
        if self.spec.burner.kind is InputKind.METER:
            return None
        return measure(self.spec.tanks, self.readings, self.deliveries, self.spec.reading_accuracy_cm)

    # How each result is obtained (spec.Level), and from what.

    @property
    def consumption_level(self) -> Level:
        if self.spec.burner.kind is InputKind.METER:
            return Level.MEASURED
        return Level.CALCULATED if self.factor_origin is Origin.MEASURED else Level.ESTIMATED

    @property
    def energy_level(self) -> Level:
        known = self.heating_value_origin is not Origin.DEFAULT or self.spec.heating_value is not None
        return worst(self.consumption_level, Level.CALCULATED if known else Level.ESTIMATED)

    @property
    def heat_level(self) -> Level:
        return worst(self.energy_level, Level.CALCULATED if self.spec.efficiency else Level.ESTIMATED)

    @property
    def co2_level(self) -> Level:
        known = self.co2_origin is not Origin.DEFAULT or self.spec.co2 is not None
        return worst(self.consumption_level, Level.CALCULATED if known else Level.ESTIMATED)

    @property
    def cost_level(self) -> Level | None:
        """The price is what the invoices say: the cost is as good as the consumption, once a price is known."""
        return None if self.price is None else self.consumption_level

    def range_level(self, ts: float) -> Level | None:
        stock = self.stock_level
        return None if stock is None or self.daily_use(ts) is None else worst(stock, self.consumption_level)

    @property
    def stock_level(self) -> Level | None:
        if self.stock is None:
            return None
        measured = self._sensors_ok and self._state.last_event.get("kind") == KIND_MEASUREMENT
        return Level.MEASURED if measured else self.consumption_level

    def basis(self) -> dict[str, str]:
        result = {"consumption": str(self.spec.burner.kind)}
        if self.spec.burner.kind is not InputKind.METER:
            result["factor"] = str(self.factor_origin)
        result["heating_value"] = str(
            Origin.SET
            if self.heating_value_origin is Origin.DEFAULT and self.spec.heating_value is not None
            else self.heating_value_origin
        )
        result["efficiency"] = str(Origin.SET if self.spec.efficiency else Origin.DEFAULT)
        return result

    # --- Storage -----------------------------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "consumption": self.consumption,
            "nominal": self.nominal,
            "runtime_h": self.runtime_h,
            "starts": self.starts,
            "energy": self.energy,
            "heat": self.heat,
            "cost": self.cost,
            "co2": self.co2,
            "factor": self.factor,
            "factor_origin": str(self.factor_origin),
            "counter": self._counter.to_dict(),
            "checkpoints": self.checkpoints,
            "deliveries": self.deliveries,
            "readings": self.readings,
            "corrections": self.corrections,
            "measurement": self.measurement,
            "factor_changes": self.factor_changes,
            "seq": self._seq,
        }

    @classmethod
    def from_dict(cls, spec: LedgerSpec, data: Mapping[str, Any]) -> Ledger:
        ledger = cls(spec)
        ledger.time = data.get("time")
        for key in ("consumption", "nominal", "runtime_h", "energy", "heat", "cost", "co2"):
            setattr(ledger, key, float(data.get(key) or 0.0))
        ledger.starts = int(data.get("starts") or 0)
        ledger.factor = float(data.get("factor") or 1.0)
        ledger.factor_origin = Origin(data.get("factor_origin") or Origin.DEFAULT)
        if isinstance(counter := data.get("counter"), Mapping):
            ledger._counter.restore(counter)
        ledger.checkpoints = [list(map(float, p)) for p in data.get("checkpoints") or []]
        ledger.deliveries = list(data.get("deliveries") or [])
        ledger.readings = list(data.get("readings") or [])
        ledger.corrections = list(data.get("corrections") or [])
        ledger.measurement = data.get("measurement")
        ledger.factor_changes = list(data.get("factor_changes") or [])
        ledger._seq = int(data.get("seq") or 0)
        ledger._replay()
        ledger.restored = True
        return ledger

    # --- Internals ---------------------------------------------------------------------------------------------

    def _advance(self, ts: float) -> None:
        if self.time is None or ts > self.time:
            self.time = ts

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _burner(self, ts: float, on: bool | None, *, initial: bool) -> None:
        # After unavailable the burner may have started long ago: like a burner found running at the start.
        initial = initial or not self._burner_known
        self._burner_known = on is not None
        if on and self._on_since is None:
            self._on_since = ts
            if initial:
                self._prepurge_left = 0.0
            else:
                self.starts += 1
                self._prepurge_left = self.spec.burner.prepurge_s
        elif not on and self._on_since is not None:
            # Off, or unavailable: what ran until now counts, nothing after.
            self._run_until(ts)
            self._on_since = None
        self.running = bool(on)

    def _run_until(self, ts: float) -> None:
        assert self._on_since is not None
        seconds = max(ts - self._on_since, 0.0)
        purge = min(seconds, self._prepurge_left)
        self._prepurge_left -= purge
        self._on_since = ts
        if seconds - purge > 0:
            self._book_hours((seconds - purge) / HOUR_S)

    def _book_hours(self, hours: float) -> None:
        self.runtime_h += hours
        nominal = hours * (self.spec.burner.nominal_flow or 0.0)
        self._book(nominal, nominal * self.factor)

    def _book(self, nominal: float, litres: float) -> None:
        self.nominal += nominal
        self.consumption += litres
        energy = litres * self.current_heating_value
        self.energy += energy
        self.heat += energy * self.spec.boiler_efficiency
        if self.price is not None:
            self.cost += litres * self.price
        self.co2 += litres * self.current_co2

    def _at(self, ts: float) -> tuple[float, float]:
        """Consumption and nominal at a moment, interpolated between checkpoints."""
        if self.time is None or ts >= self.time:
            return self.consumption, self.nominal
        points = [*self.checkpoints]
        if not points or points[-1][0] < self.time:
            points.append([self.time, self.consumption, self.nominal])
        if ts < points[0][0]:
            raise LedgerError("too_early")
        i = bisect_right([p[0] for p in points], ts) - 1
        if i >= len(points) - 1:
            return points[-1][1], points[-1][2]
        (t0, c0, n0), (t1, c1, n1) = points[i], points[i + 1]
        share = (ts - t0) / (t1 - t0) if t1 > t0 else 1.0
        return c0 + (c1 - c0) * share, n0 + (n1 - n0) * share

    def _check_time(self, ts: float) -> None:
        if self.time is not None and ts > self.time:
            raise LedgerError("in_future")

    def _events(self) -> list[dict[str, Any]]:
        events = [*self.corrections, *self.deliveries, *self.readings]
        # The last measurement only counts while the tanks have their level sensors: once they are gone, the
        # readings and deliveries since decide again.
        if self.measurement is not None and self.spec.measured_stock:
            events.append(self.measurement)
        return sorted(events, key=lambda e: (e["time"], e["seq"]))

    def _run(self, until: float | None = None) -> _Stock:
        """The tanks after the events up to a moment (all of them without one)."""
        state = _Stock()
        tanks = _tanks(self.spec)
        for event in self._events():
            if until is not None and event["time"] > until:
                break
            if _complete(self.spec, state.volumes) and event["consumption"] > state.consumption:
                assert state.volumes is not None
                state.volumes = draw(tanks, state.volumes, event["consumption"] - state.consumption)
            state.consumption = max(state.consumption, event["consumption"])
            _apply(self.spec, state, event)
        return state

    def _state_at(self, ts: float, consumption: float) -> _Stock:
        """The tanks at a moment, before an event there is booked."""
        state = self._run(ts)
        if _complete(self.spec, state.volumes) and consumption > state.consumption:
            assert state.volumes is not None
            state.volumes = draw(_tanks(self.spec), state.volumes, consumption - state.consumption)
            state.consumption = consumption
        return state

    def _replay(self) -> None:
        self._state = self._run()

    def _prune(self, ts: float) -> None:
        fine, keep = ts - CHECKPOINTS_FINE_S, ts - CHECKPOINTS_KEEP_S
        kept: list[list[float]] = []
        last_hour: int | None = None
        for point in self.checkpoints:
            if point[0] < keep:
                continue
            if point[0] < fine:
                hour = int(point[0] // HOUR_S)
                if hour == last_hour:
                    continue
                last_hour = hour
            kept.append(point)
        self.checkpoints = kept


def _tanks(spec: LedgerSpec) -> tuple[TankSpec, ...]:
    """The tanks, or one pool of unlimited size for an entry without tanks."""
    return spec.tanks or (TankSpec(POOL, POOL, float("inf")),)


def _complete(spec: LedgerSpec, volumes: Volumes | None) -> bool:
    return volumes is not None and all(t.id in volumes for t in _tanks(spec))


def _total(spec: LedgerSpec, volumes: Volumes | None) -> float | None:
    if not _complete(spec, volumes):
        return None
    assert volumes is not None
    return sum(volumes[t.id] for t in _tanks(spec))


def _tank_volume(volumes: Volumes | None, tank_id: str) -> float | None:
    return None if volumes is None else volumes.get(tank_id)


def _blend(old: float | None, new: float | None, rest: float | None, amount: float | None) -> float | None:
    if new is None:
        return old
    if old is None or not rest or not amount:
        return new
    return (rest * old + amount * new) / (rest + amount)


def _values(state: _Stock, spec: LedgerSpec) -> dict[str, float | None]:
    return {
        "price": state.price,
        "heating_value": state.heating_value if state.heating_value is not None else spec.default_heating_value,
        "co2": state.co2 if state.co2 is not None else spec.default_co2,
    }


def _apply(spec: LedgerSpec, state: _Stock, event: dict[str, Any]) -> None:
    """One event on the tanks; a delivery also notes what it found and left (rest, amount, values)."""
    tanks = _tanks(spec)
    kind = event["kind"]
    state.last_event = event
    if kind == KIND_MEASUREMENT:
        state.volumes = {t.id: event["volumes"][t.id] for t in tanks if t.id in event["volumes"]}
        state.assumed = frozenset()
    elif kind == KIND_READING:
        state.volumes, state.assumed = reading(
            tanks, state.volumes, spec.link, event["tank"], event["volume"], state.assumed
        )
    elif kind == KIND_CORRECTION:
        state.volumes = fill(tanks, {}, event["volume"])
        state.assumed = _spread(spec)
        for key in ("price", "heating_value", "co2"):
            if event.get(key) is not None:
                setattr(state, key, event[key])
                setattr(state, f"{key}_origin", Origin.SET)
    elif kind == KIND_DELIVERY:
        _deliver(spec, state, event)


def _deliver(spec: LedgerSpec, state: _Stock, event: dict[str, Any]) -> None:
    tanks = _tanks(spec)
    calculated = _total(spec, state.volumes)
    amount = event["amount"] if event.get("amount_entered") else None
    level_after = event["level_after"] if event.get("level_after_entered") else None
    rest: float | None
    if amount is not None and level_after is not None:
        rest = max(level_after - amount, 0.0)
        volumes = scale(tanks, state.volumes, rest) if calculated is not None else fill(tanks, {}, rest)
    elif amount is not None:
        rest = max(calculated, 0.0) if calculated is not None else None
        volumes = state.volumes if calculated is not None else {}
        level_after = (rest or 0.0) + amount
    else:
        assert level_after is not None
        rest = max(calculated, 0.0) if calculated is not None else None
        amount = max(level_after - rest, 0.0) if rest is not None else None
        volumes = state.volumes if rest is not None else {}
    before = _values(state, spec)
    weight = amount or event.get("amount_at_entry")  # never 0: a total on the invoice is for a real amount

    def per_litre(total: float | None) -> float | None:
        return None if total is None or not weight else total / weight

    price, heating_value, co2 = per_litre(event["total_price"]), per_litre(event["energy"]), per_litre(event["co2"])
    if price is not None:
        state.price, state.price_origin = _blend(state.price, price, rest, weight), Origin.DELIVERY
    if heating_value is not None:
        old = state.heating_value if state.heating_value is not None else spec.default_heating_value
        state.heating_value, state.heating_value_origin = _blend(old, heating_value, rest, weight), Origin.DELIVERY
    if co2 is not None:
        old = state.co2 if state.co2 is not None else spec.default_co2
        state.co2, state.co2_origin = _blend(old, co2, rest, weight), Origin.DELIVERY
    if amount is not None and volumes is not None:
        state.volumes = fill(tanks, volumes, amount)
    else:
        state.volumes = fill(tanks, {}, level_after or 0.0)
    state.assumed = _spread(spec)
    event.update(
        rest=rest,
        rest_calculated=calculated,
        amount=amount,
        level_after=level_after,
        before=before,
        after=_values(state, spec),
    )


def _spread(spec: LedgerSpec) -> frozenset[str]:
    """The tanks whose content is only assumed after a total was spread over them: on a T-piece, nobody knows how a
    total divides; connected at the bottom, it divides by height."""
    if spec.link is Link.BOTTOM or len(spec.tanks) < 2:
        return frozenset()
    return frozenset(t.id for t in spec.tanks)
