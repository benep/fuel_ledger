"""The consumption before the setup, replayed from recorded states."""

from __future__ import annotations

import pytest

from custom_components.fuel_ledger.engine import BurnerSpec, InputKind, Ledger, LedgerSpec, TankSpec
from custom_components.fuel_ledger.engine.history import past_checkpoints
from custom_components.fuel_ledger.engine.power import ComponentKind, ComponentSpec, PowerSpec

H = 3600.0
DAY = 86400.0
FLOW = 2.0
RUNTIME = LedgerSpec(burner=BurnerSpec(InputKind.RUNTIME, "sensor.runtime", nominal_flow=FLOW))


def test_a_run_time_counter_gives_the_consumption_of_each_hour_counted_back():
    samples = [(0.0, "sensor.runtime", 100.0), (2 * H, "sensor.runtime", 101.0), (5 * H, "sensor.runtime", 102.5)]
    points = past_checkpoints(RUNTIME, 1.25, samples, 6 * H)
    assert points[-1] == [6 * H, 0.0, 0.0]
    assert points[0][0] == 0.0
    assert points[0][1] == pytest.approx(-2.5 * FLOW * 1.25)
    assert points[0][2] == pytest.approx(-2.5 * FLOW)
    assert [p[0] for p in points] == [h * H for h in range(7)]


def test_a_power_meter_is_replayed_through_its_components():
    burner = ComponentSpec("burner", "Burner", ComponentKind.BURNER, 180.0)
    spec = LedgerSpec(
        burner=BurnerSpec(InputKind.POWER, "sensor.power", nominal_flow=FLOW),
        power=PowerSpec("sensor.power", base=4.0, components=(burner,)),
    )
    samples = [(0.0, "sensor.power", 4.0), (H, "sensor.power", 184.0), (2.5 * H, "sensor.power", 4.0)]
    points = past_checkpoints(spec, 1.0, samples, 3 * H)
    assert points[0][1] == pytest.approx(-1.5 * FLOW)


def test_nothing_recorded_gives_nothing():
    assert past_checkpoints(RUNTIME, 1.0, [], 3 * H) == []


def test_seeded_checkpoints_give_the_range_at_once_and_allow_events_before_the_setup():
    tanks = (TankSpec("t", "T", 2000.0, per_cm=10.0),)
    spec = LedgerSpec(burner=RUNTIME.burner, tanks=tanks, range_days=7.0)
    samples = [(d * DAY, "sensor.runtime", 100.0 + 5 * d) for d in range(8)]  # 10 L a day for a week
    book = Ledger(spec)
    book.observe(7 * DAY, 135.0, initial=True)
    book.close_interval(7 * DAY)
    assert book.range_days(7 * DAY) is None
    book.seed(past_checkpoints(spec, 1.0, samples, 7 * DAY))
    book.set_stock(DAY, 800.0)  # read the day after the week began
    assert book.daily_use(7 * DAY) == pytest.approx(10.0)
    assert book.stock == pytest.approx(800.0 - 60.0)
    record = book.record_delivery(2 * DAY, amount=500.0)  # before the setup
    assert record["consumption"] == pytest.approx(-50.0)
    assert record["rest"] == pytest.approx(790.0)
    assert book.range_days(7 * DAY) == pytest.approx((800.0 + 500.0 - 60.0) / 10.0)
    assert book.consumption == 0.0  # no counter moved
