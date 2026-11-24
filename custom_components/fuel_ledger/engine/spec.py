"""What the ledger is told about the heating: the fuel, how its consumption is read, and its tanks.

Everything here is fixed while an entry is loaded; changing it reloads the entry, and the ledger continues from its
stored state with the new spec. Nothing in it applies retroactively: a new nozzle or efficiency counts from then on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .power import PowerSpec
from .stock import Link
from .tank import TankSpec

LITRES_PER_US_GALLON = 3.785411784
# Nozzles are rated at 100 psi, about 7 bar, unless the manufacturer says otherwise.
DEFAULT_TEST_PRESSURE_BAR = 7.0
DEFAULT_EFFICIENCY = 0.9
DEFAULT_RANGE_DAYS = 7.0
DEFAULT_READING_ACCURACY_CM = 0.5
DEFAULT_LOW_PERCENT = 20.0


class InputKind(StrEnum):
    """How the consumption is read."""

    RUNTIME = "runtime"  # a cumulative burner run time (h, min, s): run time × nozzle × factor
    METER = "meter"  # a cumulative volume (oil meter): measured, taken as it is
    BURNER = "burner"  # a binary sensor, on while the burner runs: the ledger counts the run time itself
    POWER = "power"  # the power of the heating: the burner is recognised in it (power.py), then as BURNER

    @property
    def counts_itself(self) -> bool:
        """The ledger counts the run time from on and off, rather than taking it from a counter."""
        return self in (InputKind.BURNER, InputKind.POWER)


class Level(StrEnum):
    """How a result is obtained, from best to worst."""

    MEASURED = "measured"
    CALCULATED = "calculated"
    ESTIMATED = "estimated"


LEVEL_ORDER = (Level.MEASURED, Level.CALCULATED, Level.ESTIMATED)


def worst(*levels: Level) -> Level:
    return max(levels, key=LEVEL_ORDER.index)


class Origin(StrEnum):
    """Where a value of the fuel or the burner comes from."""

    DEFAULT = "default"  # the fuel profile's standard value
    SET = "set"  # entered by the user (setup, options, a stock correction or the number entity)
    DELIVERY = "delivery"  # from the invoice of a delivery, blended with what was left in the tanks
    MEASURED = "measured"  # the correction factor, taken over from dipstick readings


@dataclass(frozen=True)
class FuelProfile:
    """The fuel. Heating oil first; LPG, pellets and wood follow with their own profiles."""

    key: str
    heating_value: float  # kWh per litre, net calorific value (Hi)
    co2: float  # kg CO₂ per litre


# Heating oil EL: 10.0 kWh/L (Hi) and 0.266 kg CO₂ per kWh.
HEATING_OIL = FuelProfile("heating_oil", heating_value=10.0, co2=2.66)
FUELS = {HEATING_OIL.key: HEATING_OIL}


def nozzle_flow(gph: float, pump_pressure: float | None = None, test_pressure: float | None = None) -> float:
    """Litres per hour through a nozzle rated in US gallons per hour at the test pressure.

    The flow grows with the square root of the pressure: a pump set above the test pressure burns more.
    """
    flow = gph * LITRES_PER_US_GALLON
    if pump_pressure:
        flow *= math.sqrt(pump_pressure / (test_pressure or DEFAULT_TEST_PRESSURE_BAR))
    return flow


@dataclass(frozen=True)
class BurnerSpec:
    kind: InputKind
    key: str  # entity of the input
    nominal_flow: float | None = None  # L/h at factor 1; None for a meter
    prepurge_s: float = 0.0  # burner input only: seconds after each start without oil
    state_key: str | None = None  # binary sensor on while the burner runs, for the flow rate (also for RUNTIME)


@dataclass(frozen=True)
class LedgerSpec:
    burner: BurnerSpec
    fuel: FuelProfile = HEATING_OIL
    tanks: tuple[TankSpec, ...] = ()
    link: Link = Link.SUCTION  # how several tanks are connected
    power: PowerSpec | None = None  # a power meter with the components behind it
    efficiency: float | None = None  # None: DEFAULT_EFFICIENCY
    heating_value: float | None = None  # None: the fuel's; used for fuel of unknown origin
    co2: float | None = None  # None: the fuel's
    range_days: float = DEFAULT_RANGE_DAYS
    reading_accuracy_cm: float = DEFAULT_READING_ACCURACY_CM
    low_percent: float = DEFAULT_LOW_PERCENT

    @property
    def capacity(self) -> float | None:
        return sum(t.capacity for t in self.tanks) if self.tanks else None

    @property
    def residue(self) -> float:
        return sum(t.residue for t in self.tanks)

    @property
    def default_heating_value(self) -> float:
        return self.heating_value or self.fuel.heating_value

    @property
    def default_co2(self) -> float:
        return self.co2 if self.co2 is not None else self.fuel.co2

    @property
    def boiler_efficiency(self) -> float:
        return self.efficiency or DEFAULT_EFFICIENCY

    @property
    def measured_stock(self) -> bool:
        """Every tank has a level sensor: the stock is measured, not calculated."""
        return bool(self.tanks) and all(t.level_key for t in self.tanks)

    @property
    def knows_burner_state(self) -> bool:
        """Whether the ledger learns when the burner runs: from the input itself, its binary sensor, or the burner
        recognised in a power meter."""
        return (
            self.burner.kind.counts_itself
            or bool(self.burner.state_key)
            or (self.power is not None and self.power.burner is not None)
        )

    def tank(self, tank_id: str) -> TankSpec | None:
        return next((t for t in self.tanks if t.id == tank_id), None)
