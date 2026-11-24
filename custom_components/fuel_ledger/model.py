"""From config entry data to the engine, and from entity states to readings. No Home Assistant imports.

The config flow writes the formats in const.py, the runtime calls build_spec() and the parse functions with them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_BASE_POWER,
    CONF_BURNER_ENTITY,
    CONF_CAPACITY,
    CONF_CO2,
    CONF_COMPONENT_KIND,
    CONF_DIAMETER,
    CONF_EFFICIENCY,
    CONF_ENTITY,
    CONF_FUEL,
    CONF_HEATING_VALUE,
    CONF_KIND,
    CONF_LENGTH,
    CONF_LEVEL_ENTITY,
    CONF_LINK,
    CONF_LOW_PERCENT,
    CONF_NOMINAL_FLOW,
    CONF_NOZZLE_GPH,
    CONF_OFF_DELAY,
    CONF_OFFSET,
    CONF_ON_DELAY,
    CONF_PER_CM,
    CONF_POWER,
    CONF_POWER_ENTITY,
    CONF_PREPURGE_S,
    CONF_PUMP_PRESSURE,
    CONF_RANGE_DAYS,
    CONF_READING_ACCURACY,
    CONF_RESIDUE,
    CONF_SHAPE,
    CONF_TABLE,
    CONF_TEST_PRESSURE,
    SUBENTRY_COMPONENT,
    SUBENTRY_TANK,
)
from .engine import (
    FUELS,
    HEATING_OIL,
    BurnerSpec,
    ComponentKind,
    ComponentSpec,
    InputKind,
    LedgerSpec,
    Link,
    PowerSpec,
    Shape,
    TankSpec,
    nozzle_flow,
)
from .engine.spec import (
    DEFAULT_LOW_PERCENT,
    DEFAULT_RANGE_DAYS,
    DEFAULT_READING_ACCURACY_CM,
    LITRES_PER_US_GALLON,
)

INVALID_STATES = {"unavailable", "unknown", "none", ""}

# Hours per unit of a run time counter, litres per unit of a meter, cm per unit of a level sensor. Every unit Home
# Assistant knows for these device classes (a test checks them against its converters).
HOURS = {"h": 1.0, "min": 1 / 60, "s": 1 / 3600, "ms": 1 / 3.6e6, "d": 24.0}
LITRES = {
    "L": 1.0,
    "mL": 0.001,
    "m³": 1000.0,
    "gal": LITRES_PER_US_GALLON,
    "fl. oz.": LITRES_PER_US_GALLON / 128,
    "ft³": 28.316846592,
    "CCF": 2831.6846592,
    "MCF": 28316.846592,
}
CENTIMETRES = {"cm": 1.0, "mm": 0.1, "m": 100.0, "in": 2.54, "ft": 30.48, "yd": 91.44}
WATTS = {"W": 1.0, "kW": 1000.0, "mW": 0.001, "MW": 1e6, "GW": 1e9, "TW": 1e12, "BTU/h": 0.29307107017222}
PERCENT = "%"


@dataclass(frozen=True)
class Subentry:
    """The parts of a config subentry the model needs, without Home Assistant."""

    subentry_id: str
    subentry_type: str
    title: str
    data: Mapping[str, Any]


def input_kind(domain: str, unit: str | None, device_class: str | None = None) -> InputKind | None:
    """How an entity can be read as the input, or None if it cannot."""
    if domain == "binary_sensor":
        return InputKind.BURNER
    if domain != "sensor":
        return None
    if unit in HOURS or (unit is None and device_class == "duration"):
        return InputKind.RUNTIME
    if unit in LITRES:
        return InputKind.METER
    if unit in WATTS:
        return InputKind.POWER
    return None


def build_spec(options: Mapping[str, Any], subentries: Iterable[Any]) -> LedgerSpec:
    """The ledger's spec from the entry's options and its subentries. KeyError/ValueError if incomplete."""
    subentries = list(subentries)
    kind = InputKind(options[CONF_KIND])
    power = power_spec(options, subentries)
    if kind is InputKind.POWER and (power is None or power.burner is None):
        raise ValueError("the power input needs a burner among the components")
    nominal: float | None = None
    if kind is not InputKind.METER:
        if options.get(CONF_NOMINAL_FLOW):
            nominal = float(options[CONF_NOMINAL_FLOW])
        else:
            nominal = nozzle_flow(
                float(options[CONF_NOZZLE_GPH]), options.get(CONF_PUMP_PRESSURE), options.get(CONF_TEST_PRESSURE)
            )
        if nominal <= 0:
            raise ValueError("nominal flow must be positive")
    burner = BurnerSpec(
        kind=kind,
        key=options[CONF_ENTITY],
        nominal_flow=nominal,
        prepurge_s=float(options.get(CONF_PREPURGE_S) or 0.0) if kind.counts_itself else 0.0,
        state_key=options[CONF_ENTITY] if kind is InputKind.BURNER else options.get(CONF_BURNER_ENTITY),
    )
    tanks = tuple(tank_spec(s.subentry_id, s.title, s.data) for s in subentries if s.subentry_type == SUBENTRY_TANK)
    return LedgerSpec(
        burner=burner,
        fuel=FUELS.get(options.get(CONF_FUEL) or HEATING_OIL.key, HEATING_OIL),
        tanks=tanks,
        link=Link(options.get(CONF_LINK) or Link.SUCTION),
        power=power,
        efficiency=_optional(options.get(CONF_EFFICIENCY)),
        heating_value=_optional(options.get(CONF_HEATING_VALUE)),
        co2=_optional(options.get(CONF_CO2)),
        range_days=float(options.get(CONF_RANGE_DAYS) or DEFAULT_RANGE_DAYS),
        reading_accuracy_cm=float(options.get(CONF_READING_ACCURACY) or DEFAULT_READING_ACCURACY_CM),
        low_percent=float(options.get(CONF_LOW_PERCENT) or DEFAULT_LOW_PERCENT),
    )


def tank_spec(tank_id: str, name: str, data: Mapping[str, Any]) -> TankSpec:
    return TankSpec(
        id=tank_id,
        name=name,
        capacity=float(data[CONF_CAPACITY]),
        shape=Shape(data.get(CONF_SHAPE) or Shape.LINEAR),
        per_cm=_optional(data.get(CONF_PER_CM)),
        diameter_cm=_optional(data.get(CONF_DIAMETER)),
        length_cm=_optional(data.get(CONF_LENGTH)),
        table=tuple((float(cm), float(litres)) for cm, litres in data.get(CONF_TABLE) or ()),
        offset_cm=float(data.get(CONF_OFFSET) or 0.0),
        residue=float(data.get(CONF_RESIDUE) or 0.0),
        level_key=data.get(CONF_LEVEL_ENTITY),
    )


def power_spec(options: Mapping[str, Any], subentries: Iterable[Any]) -> PowerSpec | None:
    """The power meter with its components: the input itself, or a meter next to another input."""
    key = options[CONF_ENTITY] if options.get(CONF_KIND) == InputKind.POWER else options.get(CONF_POWER_ENTITY)
    if not key:
        return None
    components = tuple(
        ComponentSpec(
            id=s.subentry_id,
            name=s.title,
            kind=ComponentKind(s.data[CONF_COMPONENT_KIND]),
            power=float(s.data[CONF_POWER]),
            on_delay_s=_optional(s.data.get(CONF_ON_DELAY)),
            off_delay_s=_optional(s.data.get(CONF_OFF_DELAY)),
        )
        for s in subentries
        if s.subentry_type == SUBENTRY_COMPONENT
    )
    return PowerSpec(key=key, base=float(options.get(CONF_BASE_POWER) or 0.0), components=components)


def parse_power(state: str | None, attributes: Mapping[str, Any]) -> float | None:
    """Watts from a power sensor; a sensor without a unit is read in W."""
    value = _number(state) if state is not None else None
    if value is None:
        return None
    factor = WATTS.get(attributes.get("unit_of_measurement") or "W")
    return None if factor is None else value * factor


def _optional(value: Any) -> float | None:
    return None if value in (None, "") else float(value)


def _number(state: str) -> float | None:
    if state is None or state.lower() in INVALID_STATES:
        return None
    try:
        value = float(state)
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def parse_input(kind: InputKind, state: str | None, attributes: Mapping[str, Any]) -> float | bool | None:
    """The input's state as hours (run time), litres (meter) or on/off (burner); None if unavailable or unreadable.

    A counter without a unit is read in hours or litres.
    """
    if state is None:
        return None
    if kind is InputKind.BURNER:
        if state == "on":
            return True
        return False if state == "off" else None
    value = _number(state)
    if value is None:
        return None
    unit = attributes.get("unit_of_measurement")
    table = HOURS if kind is InputKind.RUNTIME else LITRES
    if unit is None:
        return value
    factor = table.get(unit)
    return None if factor is None else value * factor


def parse_burner(state: str | None) -> bool | None:
    if state == "on":
        return True
    return False if state == "off" else None


def parse_level(tank: TankSpec, state: str | None, attributes: Mapping[str, Any]) -> float | None:
    """Litres in a tank from its level sensor: a height (cm, mm, in …), a volume (L, gal …) or a percentage."""
    value = _number(state) if state is not None else None
    if value is None:
        return None
    unit = attributes.get("unit_of_measurement")
    if unit in LITRES:
        return max(value * LITRES[unit], 0.0)
    if unit == PERCENT:
        return max(tank.capacity * value / 100, 0.0)
    if unit in CENTIMETRES and tank.converts_height:
        return tank.volume(value * CENTIMETRES[unit])
    return None
