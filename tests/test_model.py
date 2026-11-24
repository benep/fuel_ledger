"""Units and states: the tables of the model against Home Assistant's converters."""

from __future__ import annotations

import pytest
from homeassistant.util.unit_conversion import DistanceConverter, DurationConverter, PowerConverter, VolumeConverter

from custom_components.fuel_ledger.engine import InputKind, TankSpec
from custom_components.fuel_ledger.model import (
    CENTIMETRES,
    HOURS,
    LITRES,
    WATTS,
    input_kind,
    parse_input,
    parse_level,
    parse_power,
)


@pytest.mark.parametrize(
    ("table", "converter", "unit"),
    [
        (HOURS, DurationConverter, "h"),
        (LITRES, VolumeConverter, "L"),
        (CENTIMETRES, DistanceConverter, "cm"),
        (WATTS, PowerConverter, "W"),
    ],
)
def test_unit_tables_agree_with_home_assistant(table, converter, unit):
    for source, factor in table.items():
        assert converter.convert(1.0, source, unit) == pytest.approx(factor, rel=1e-9), source


def test_input_kind():
    assert input_kind("binary_sensor", None) is InputKind.BURNER
    assert input_kind("sensor", "h") is InputKind.RUNTIME
    assert input_kind("sensor", None, "duration") is InputKind.RUNTIME
    assert input_kind("sensor", "m³") is InputKind.METER
    assert input_kind("sensor", "W") is InputKind.POWER
    assert input_kind("sensor", "°C") is None
    assert input_kind("switch", None) is None


def test_parse_input():
    assert parse_input(InputKind.RUNTIME, "90", {"unit_of_measurement": "min"}) == 1.5
    assert parse_input(InputKind.RUNTIME, "2", {}) == 2.0
    assert parse_input(InputKind.METER, "0.004", {"unit_of_measurement": "m³"}) == pytest.approx(4.0)
    assert parse_input(InputKind.METER, "4", {"unit_of_measurement": "W"}) is None
    assert parse_input(InputKind.RUNTIME, "unavailable", {}) is None
    assert parse_input(InputKind.BURNER, "on", {}) is True
    assert parse_input(InputKind.BURNER, "unknown", {}) is None


def test_parse_level():
    tank = TankSpec("t", "T", 1000.0, per_cm=7.0)
    assert parse_level(tank, "500", {"unit_of_measurement": "mm"}) == pytest.approx(350.0)
    assert parse_level(tank, "25", {"unit_of_measurement": "%"}) == pytest.approx(250.0)
    assert parse_level(tank, "100", {"unit_of_measurement": "gal"}) == pytest.approx(378.54, abs=0.01)
    assert parse_level(TankSpec("t", "T", 1000.0), "50", {"unit_of_measurement": "cm"}) is None


def test_parse_power():
    assert parse_power("0.25", {"unit_of_measurement": "kW"}) == 250.0
    assert parse_power("120", {}) == 120.0
    assert parse_power("unavailable", {"unit_of_measurement": "W"}) is None
