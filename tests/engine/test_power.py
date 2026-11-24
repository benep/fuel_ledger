"""Components behind one power meter."""

from __future__ import annotations

import pytest

from custom_components.fuel_ledger.engine.power import (
    Change,
    ComponentKind,
    ComponentSpec,
    Disaggregator,
    PowerSpec,
    alike,
)

BURNER = ComponentSpec("burner", "Burner", ComponentKind.BURNER, 180.0)
PREHEATER = ComponentSpec("pre", "Preheater", ComponentKind.PREHEATER, 80.0)
CIRCUIT = ComponentSpec("circuit", "Circuit pump", ComponentKind.CIRCUIT_PUMP, 45.0, on_delay_s=90, off_delay_s=240)
HOT_WATER = ComponentSpec("hw", "Hot water pump", ComponentKind.HOT_WATER_PUMP, 70.0, on_delay_s=120, off_delay_s=60)
FULL = PowerSpec("sensor.power", base=4.0, components=(BURNER, PREHEATER, CIRCUIT, HOT_WATER))


def test_only_the_burner_is_a_threshold():
    power = Disaggregator(PowerSpec("sensor.power", components=(BURNER,)))
    power.update(0.0, 5.0)
    assert power.state == {"burner": False}
    assert power.update(10.0, 150.0) == [Change("burner", True, 10.0)]
    assert power.update(20.0, 60.0) == [Change("burner", False, 20.0)]


def test_combinations():
    power = Disaggregator(FULL)
    for watts, running in [
        (4.0, set()),
        (49.0, {"circuit"}),
        (129.0, {"pre", "circuit"}),
        (74.0, {"hw"}),
        (154.0, {"pre", "hw"}),
        (184.0, {"burner"}),
        (229.0, {"burner", "circuit"}),
        (254.0, {"burner", "hw"}),
    ]:
        power.update(0.0, watts)
        assert {k for k, on in power.raw.items() if on} == running, watts


def test_preheater_never_runs_with_the_burner():
    power = Disaggregator(FULL)
    power.update(0.0, 4 + 180 + 80)
    assert power.raw["pre"] is False


def test_delays_confirm_a_change_from_when_it_began():
    power = Disaggregator(FULL)
    power.update(0.0, 4.0)
    assert power.update(100.0, 254.0) == [Change("burner", True, 100.0)]  # the hot water pump has to wait
    assert power.state["hw"] is False
    assert power.next_due() == 220.0
    assert power.update(200.0, 184.0) == []  # a peak: the pump is not confirmed, and its wait starts over
    assert power.next_due() is None
    power.update(300.0, 254.0)
    assert power.tick(419.0) == []
    assert power.tick(420.0) == [Change("hw", True, 300.0)]


def test_power_of_each_component():
    power = Disaggregator(FULL)
    power.update(0.0, 234.0)  # burner and circuit pump: the burner takes the rest
    assert power.power("circuit") == 45.0
    assert power.power("burner") == pytest.approx(185.0)
    assert power.power("hw") == 0.0
    power.update(10.0, 52.0)  # the pump alone takes what is above the base load
    assert power.power("circuit") == pytest.approx(48.0)


def test_unavailable_meter_reports_unknown_and_then_the_state_as_found():
    power = Disaggregator(FULL)
    power.update(0.0, 184.0)
    changes = power.update(10.0, None)
    assert Change("burner", None, 10.0) in changes
    assert all(c.on is None for c in changes)
    assert power.state["burner"] is None
    assert power.power("burner") is None
    # Back: the burner is taken as found, not as a start (it may have run all along).
    assert Change("burner", True, 20.0, initial=True) in power.update(20.0, 184.0)
    assert power.update(30.0, None)[0].on is None
    assert power.update(40.0, None) == []  # nothing new to report


def test_the_first_measurement_reports_each_component_as_found():
    power = Disaggregator(FULL)
    changes = power.update(0.0, 49.0)
    assert Change("circuit", True, 0.0, initial=True) in changes
    assert Change("burner", False, 0.0, initial=True) in changes


def test_the_burner_stops_at_once_even_with_an_off_delay():
    burner = ComponentSpec("burner", "Burner", ComponentKind.BURNER, 180.0, on_delay_s=5, off_delay_s=60)
    assert burner.delays == (5, 0.0)


CIRCULATION = ComponentSpec("circ", "Circulation pump", ComponentKind.CIRCULATION_PUMP, 25.0)


def test_a_circulation_pump_is_one_more_component():
    power = Disaggregator(PowerSpec("sensor.power", base=4.0, components=(BURNER, CIRCUIT, CIRCULATION)))
    for watts, running in [
        (29.0, {"circ"}),
        (49.0, {"circuit"}),
        (74.0, {"circuit", "circ"}),
        (209.0, {"burner", "circ"}),
        (254.0, {"burner", "circuit", "circ"}),
    ]:
        power.update(0.0, watts)
        assert {k for k, on in power.raw.items() if on} == running, watts
    assert CIRCULATION.delays == (60.0, 120.0)


def test_components_too_alike_to_tell_apart():
    assert alike(FULL) == []
    twin = ComponentSpec("circ", "Circulation pump", ComponentKind.CIRCULATION_PUMP, 42.0)
    assert alike(PowerSpec("sensor.power", components=(BURNER, CIRCUIT, twin))) == [(CIRCUIT, twin)]
    small = ComponentSpec("small", "Small", ComponentKind.OTHER, 2.0)
    tiny = ComponentSpec("tiny", "Tiny", ComponentKind.OTHER, 6.0)
    assert alike(PowerSpec("sensor.power", components=(small, tiny))) == [(small, tiny)]  # within 5 W
