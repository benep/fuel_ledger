"""Components behind one power meter."""

from __future__ import annotations

import pytest

from custom_components.fuel_ledger.engine.power import (
    Change,
    ComponentKind,
    ComponentSpec,
    Disaggregator,
    PowerSpec,
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


def test_unavailable_meter():
    power = Disaggregator(FULL)
    power.update(0.0, 184.0)
    assert power.update(10.0, None) == []
    assert power.state["burner"] is None
    assert power.power("burner") is None
