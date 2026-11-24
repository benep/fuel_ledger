"""Tank shapes: from height to volume."""

from __future__ import annotations

import math

import pytest

from custom_components.fuel_ledger.engine import Shape, TankSpec, format_table, parse_table


def test_linear_with_offset():
    tank = TankSpec("t", "T", 1000.0, per_cm=8.0, offset_cm=1.5)
    assert tank.volume(41.5) == pytest.approx(320.0)
    assert tank.volume(1.0) == 0.0
    assert tank.litres_per_cm(50.0) == pytest.approx(8.0)


def test_horizontal_cylinder():
    tank = TankSpec("t", "T", 0.0, Shape.HORIZONTAL_CYLINDER, diameter_cm=100.0, length_cm=200.0)
    full = math.pi * 50**2 * 200 / 1000
    assert tank.volume(100.0) == pytest.approx(full)
    assert tank.volume(150.0) == pytest.approx(full)
    assert tank.volume(50.0) == pytest.approx(full / 2)
    assert tank.volume(25.0) < full / 4  # less at the bottom than linear
    # Steepest in the middle.
    assert tank.litres_per_cm(50.0) > tank.litres_per_cm(10.0)


def test_table_interpolates_and_extrapolates():
    tank = TankSpec("t", "T", 1000.0, Shape.TABLE, table=((10.0, 50.0), (20.0, 150.0)))
    assert tank.volume(5.0) == pytest.approx(25.0)  # from 0 cm / 0 L
    assert tank.volume(15.0) == pytest.approx(100.0)
    assert tank.volume(30.0) == pytest.approx(250.0)


def test_tank_without_dimensions():
    tank = TankSpec("t", "T", 1000.0)
    assert not tank.converts_height
    assert tank.litres_per_cm(10.0) == 0.0
    with pytest.raises(ValueError):
        tank.volume(10.0)


def test_parse_table():
    assert parse_table("20: 150\n10 = 50;30 250,5") == ((10.0, 50.0), (20.0, 150.0), (30.0, 250.5))
    assert format_table(((10.0, 50.0), (20.5, 150.0))) == "10: 50\n20.5: 150"
    for bad in ("", "10", "10: 5\n10: 6", "-1: 4", "a: b"):
        with pytest.raises(ValueError):
            parse_table(bad)


def test_a_table_needs_more_litres_the_higher():
    assert parse_table("10: 50\n20: 150") == ((10.0, 50.0), (20.0, 150.0))
    with pytest.raises(ValueError):
        parse_table("10: 150\n20: 50")
