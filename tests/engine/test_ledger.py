"""Rules of the ledger: counters, deliveries, stock, readings and the factor."""

from __future__ import annotations

import pytest

from custom_components.fuel_ledger.engine import (
    BurnerSpec,
    InputKind,
    Ledger,
    LedgerError,
    LedgerSpec,
    Level,
    Link,
    Origin,
    TankSpec,
    nozzle_flow,
)
from custom_components.fuel_ledger.engine.calibration import SURVEY_WINDOW_S

H = 3600.0
DAY = 86400.0
FLOW = 2.0  # L/h, a round number for the tests
RUNTIME = BurnerSpec(InputKind.RUNTIME, "sensor.runtime", nominal_flow=FLOW)
TANKS = (
    TankSpec("left", "Left", 1000.0, per_cm=8.0, residue=10.0),
    TankSpec("right", "Right", 1000.0, per_cm=8.0, residue=10.0),
)


def ledger(burner: BurnerSpec = RUNTIME, **kwargs) -> Ledger:
    result = Ledger(LedgerSpec(burner=burner, **kwargs))
    result.observe(0.0, 100.0 if burner.kind is not InputKind.BURNER else False, initial=True)
    return result


def run(book: Ledger, ts: float, hours: float) -> None:
    """The run time counter rises by hours at ts."""
    book.observe(ts, book._counter.last + hours)


# --- Nozzle --------------------------------------------------------------------------------------------------------


def test_nozzle_in_gph_and_pressure():
    assert nozzle_flow(0.5) == pytest.approx(1.8927, abs=1e-4)
    # Four times the test pressure doubles the flow.
    assert nozzle_flow(0.5, 28.0, 7.0) == pytest.approx(2 * nozzle_flow(0.5))


# --- Counters ------------------------------------------------------------------------------------------------------


def test_run_time_books_litres_energy_heat_co2():
    book = ledger()
    run(book, H, 1.5)
    assert book.consumption == pytest.approx(3.0)
    assert book.nominal == pytest.approx(3.0)
    assert book.energy == pytest.approx(30.0)
    assert book.heat == pytest.approx(27.0)
    assert book.co2 == pytest.approx(3 * 2.66)
    assert book.cost == 0.0  # no price known yet


def test_first_reading_books_nothing():
    book = Ledger(LedgerSpec(burner=RUNTIME))
    book.observe(0.0, 12345.0)
    assert book.consumption == 0.0


def test_counter_follows_home_assistant_rules():
    book = ledger()
    book.observe(H, None)  # unavailable: skipped
    book.observe(2 * H, 101.0)
    assert book.runtime_h == pytest.approx(1.0)
    book.observe(3 * H, 100.5)  # a dip: held as a debt
    book.observe(4 * H, 101.5)
    assert book.runtime_h == pytest.approx(1.5)
    book.observe(5 * H, 2.0)  # a reset (a new counter): counts from 0
    assert book.runtime_h == pytest.approx(3.5)


def test_factor_applies_from_now_on():
    book = ledger()
    run(book, H, 1.0)
    book.set_factor(H, 1.25)
    run(book, 2 * H, 1.0)
    assert book.consumption == pytest.approx(2.0 + 2.5)
    assert book.nominal == pytest.approx(4.0)
    assert book.factor_origin is Origin.SET


def test_meter_is_measured():
    book = ledger(BurnerSpec(InputKind.METER, "sensor.oil_meter"))
    book.observe(H, 104.0)
    assert book.consumption == pytest.approx(4.0)
    assert book.consumption_level is Level.MEASURED
    assert book.flow is None
    assert book.measured_factor() is None


def test_burner_counts_run_time_without_prepurge():
    book = ledger(BurnerSpec(InputKind.BURNER, "binary_sensor.burner", nominal_flow=FLOW, prepurge_s=12.0))
    book.observe(100.0, True)
    assert book.flow == pytest.approx(FLOW)
    book.observe(100.0 + 612.0, False)
    assert book.runtime_h == pytest.approx(600 / H)
    assert book.starts == 1
    assert book.flow == 0.0


def test_burner_running_is_booked_at_each_interval_and_prepurge_only_once():
    book = ledger(BurnerSpec(InputKind.BURNER, "binary_sensor.burner", nominal_flow=FLOW, prepurge_s=12.0))
    book.observe(0.0, True)
    book.close_interval(6.0)  # still in the prepurge
    book.close_interval(300.0)
    assert book.runtime_h == pytest.approx(288 / H)
    book.observe(600.0, False)
    assert book.runtime_h == pytest.approx(588 / H)


def test_burner_found_running_at_start_counts_from_then_without_a_start():
    book = Ledger(LedgerSpec(burner=BurnerSpec(InputKind.BURNER, "b", nominal_flow=FLOW, prepurge_s=12.0)))
    book.observe(0.0, True, initial=True)
    book.observe(H, False)
    assert book.runtime_h == pytest.approx(1.0)
    assert book.starts == 0


def test_burner_unavailable_stops_counting():
    book = ledger(BurnerSpec(InputKind.BURNER, "b", nominal_flow=FLOW))
    book.observe(0.0, True)
    book.observe(H, None)
    book.close_interval(2 * H)
    assert book.runtime_h == pytest.approx(1.0)


def test_flow_of_a_run_time_counter_needs_the_burner_state():
    assert ledger().flow is None
    book = ledger(BurnerSpec(InputKind.RUNTIME, "r", nominal_flow=FLOW, state_key="binary_sensor.burner"))
    book.set_factor(0.0, 1.5)
    book.burner_state(1.0, True)
    assert book.flow == pytest.approx(3.0)
    book.burner_state(2.0, False)
    assert book.flow == 0.0
    assert book.consumption == 0.0  # the state alone books nothing


# --- Deliveries ----------------------------------------------------------------------------------------------------


def test_delivery_blends_price_heating_value_and_co2_with_the_rest():
    """300 L at 9.9 kWh/L and 1.10 €/L, then 1200 L at 10.08 kWh/L for 1260 €: 1.06 €/L and 10.044 kWh/L."""
    book = ledger(tanks=TANKS)
    book.set_stock(0.0, 300.0, price=1.10, heating_value=9.9, co2=2.6)
    record = book.record_delivery(0.0, amount=1200.0, total_price=1260.0, energy=12096.0, co2=3204.0)
    assert book.stock == pytest.approx(1500.0)
    assert book.price == pytest.approx(1.06)
    assert book.heating_value == pytest.approx(10.044)
    assert book.co2_factor == pytest.approx((300 * 2.6 + 3204.0) / 1500)
    assert book.price_per_kwh == pytest.approx(book.price / book.heating_value)
    assert record["rest"] == pytest.approx(300.0)
    assert record["before"]["price"] == 1.10
    assert book.price_origin is Origin.DELIVERY


def test_delivery_values_apply_to_what_is_booked_after_it():
    book = ledger()
    book.set_stock(0.0, 100.0, price=1.0)
    run(book, H, 1.0)  # 2 L at 1 €/L
    book.record_delivery(H, amount=100.0, total_price=300.0)  # 98 L at 1, 100 L at 3 → 2.0101…
    run(book, 2 * H, 1.0)
    assert book.cost == pytest.approx(2.0 + 2.0 * (98 * 1 + 100 * 3) / 198)


def test_first_delivery_takes_its_values():
    book = ledger()
    book.record_delivery(0.0, level_after=1250.0)
    assert book.stock == 1250.0
    assert book.price is None
    book.record_delivery(0.0, amount=500.0, level_after=1700.0, total_price=600.0)
    assert book.price == pytest.approx(1.2)  # the first known price is not blended with an unknown one


def test_delivery_with_level_after_and_amount_corrects_the_rest():
    book = ledger()
    book.set_stock(0.0, 300.0, price=1.0)
    record = book.record_delivery(0.0, amount=1000.0, level_after=1200.0, total_price=2000.0)
    assert record["rest"] == pytest.approx(200.0)
    assert book.price == pytest.approx((200 * 1 + 2000) / 1200)


def test_delivery_from_the_level_after_alone():
    book = ledger()
    book.set_stock(0.0, 300.0)
    record = book.record_delivery(0.0, level_after=1300.0, total_price=1500.0)
    assert record["amount"] == pytest.approx(1000.0)
    assert record["amount_entered"] is False
    assert book.price == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("kwargs", "key"),
    [
        ({}, "amount_or_level"),
        ({"amount": 0.0}, "not_positive"),
        ({"level_after": 100.0}, "level_below_stock"),
    ],
)
def test_delivery_errors(kwargs, key):
    book = ledger()
    book.set_stock(0.0, 300.0)
    with pytest.raises(LedgerError) as err:
        book.record_delivery(0.0, **kwargs)
    assert err.value.key == key


def test_delivery_amount_needs_a_known_stock():
    with pytest.raises(LedgerError, match="stock_unknown"):
        ledger().record_delivery(0.0, amount=1000.0)


def test_totals_need_an_amount():
    with pytest.raises(LedgerError, match="amount_needed"):
        ledger().record_delivery(0.0, level_after=1000.0, total_price=1000.0)


def test_delivery_dated_back_uses_the_stock_of_then():
    book = ledger()
    book.set_stock(0.0, 500.0)
    for hour in range(1, 11):
        run(book, hour * H, 1.0)
        book.close_interval(hour * H)
    # 10 h × 2 L/h since the stock was set; the delivery was at 5 h, entered at 10 h.
    record = book.record_delivery(5 * H, amount=1000.0)
    assert record["rest"] == pytest.approx(490.0)
    assert book.stock == pytest.approx(1490.0 - 10.0)


def test_an_event_dated_back_before_another_is_calculated_in_order():
    book = ledger()
    for hour in range(1, 4):
        run(book, hour * H, 1.0)  # 2 L an hour
        book.close_interval(hour * H)
    book.set_stock(2 * H, 500.0)
    record = book.record_delivery(H, amount=10.0, level_after=110.0)  # entered later, dated before the stock was set
    assert record["rest"] == pytest.approx(100.0)
    assert book.stock == pytest.approx(498.0)  # the later correction still decides
    with pytest.raises(LedgerError, match="in_future"):
        book.record_delivery(4 * H, amount=10.0)
    with pytest.raises(LedgerError, match="too_early"):
        book._at(-H)


# --- Stock, range ------------------------------------------------------------------------------------------------


def test_stock_fill_usable_and_low():
    book = ledger(tanks=TANKS, low_percent=20.0)
    assert book.stock is None and book.fill_percent is None and book.low is None
    book.set_stock(0.0, 1250.0)
    run(book, H, 10.0)
    assert book.stock == pytest.approx(1230.0)
    assert book.usable == pytest.approx(1210.0)
    assert book.fill_percent == pytest.approx(61.5)
    assert book.low is False
    book.set_stock(H, 400.0)
    assert book.low is True
    book.set_stock(H, 0.0)
    run(book, 2 * H, 1.0)
    assert book.stock == 0.0  # never negative


def test_measured_stock_replaces_the_calculation_and_the_calculation_continues():
    tanks = tuple(TankSpec(t.id, t.name, t.capacity, per_cm=8.0, level_key=f"sensor.{t.id}") for t in TANKS)
    book = ledger(tanks=tanks)
    book.measure_stock(0.0, {"left": 300.0, "right": 500.0})
    assert book.stock == 800.0 and book.stock_level is Level.MEASURED
    run(book, H, 5.0)
    book.measure_stock(H, None)  # a sensor is gone
    assert book.stock == pytest.approx(790.0)
    assert book.tank_volume("right") == pytest.approx(490.0)  # drawn from the fuller one
    assert book.stock_level is Level.ESTIMATED


# --- Several tanks -----------------------------------------------------------------------------------------------


def test_t_piece_draws_from_the_higher_surface_until_both_stand_level():
    book = ledger(tanks=TANKS)
    book.record_level(0.0, "left", "front", height_cm=40.0)  # 320 L
    book.record_level(0.0, "right", "front", height_cm=110.0)  # 880 L
    assert book.stock == pytest.approx(1200.0)
    run(book, H, 100.0)  # 200 L: all from the right
    assert book.tank_volume("left") == pytest.approx(320.0)
    assert book.tank_volume("right") == pytest.approx(680.0)
    run(book, 2 * H, 200.0)  # 400 L: 360 L until the right is down to 40 cm too, then 20 L from each
    assert book.tank_height("left") == pytest.approx(book.tank_height("right"))
    assert book.tank_volume("left") == pytest.approx(300.0)
    assert book.stock == pytest.approx(1200.0 - 600.0)


def test_a_tank_standing_higher_counts_with_its_surface():
    tanks = (TANKS[0], TankSpec("right", "Right", 1000.0, per_cm=8.0, offset_cm=10.0))
    book = ledger(tanks=tanks)
    book.record_level(0.0, "left", "front", height_cm=50.0)  # 400 L, surface at 50 cm
    book.record_level(0.0, "right", "front", height_cm=50.0)  # 320 L, but its surface is as high
    run(book, H, 8.0)  # 16 L: from both, as both surfaces stand at 50 cm
    assert book.tank_volume("left") == pytest.approx(392.0)
    assert book.tank_volume("right") == pytest.approx(312.0)


def test_connected_at_the_bottom_one_reading_tells_all():
    book = ledger(tanks=TANKS, link=Link.BOTTOM)
    book.record_level(0.0, "left", "front", height_cm=50.0)
    assert book.tank_volume("right") == pytest.approx(400.0)
    assert book.stock == pytest.approx(800.0)


def test_a_reading_corrects_its_tank_and_a_reading_dated_back_too():
    book = ledger(tanks=TANKS)
    book.set_stock(0.0, 1000.0)  # filled from the bottom: 500 L each
    for hour in range(1, 6):
        run(book, hour * H, 5.0)  # 10 L an hour, from both
        book.close_interval(hour * H)
    assert book.tank_volume("left") == pytest.approx(475.0)
    record = book.record_level(2 * H, "left", "front", volume=600.0)  # read two hours ago, entered now
    assert record["calculated"] == pytest.approx(490.0)
    # From then on the left was higher: the 30 L since came from it alone.
    assert book.tank_volume("left") == pytest.approx(570.0)
    assert book.tank_volume("right") == pytest.approx(380.0)  # the total was set: the right gets the rest


def test_a_delivery_fills_the_lower_surface_first():
    book = ledger(tanks=TANKS)
    book.record_level(0.0, "left", "front", volume=100.0)
    book.record_level(0.0, "right", "front", volume=300.0)
    book.record_delivery(0.0, amount=400.0)
    assert book.tank_volume("left") == pytest.approx(400.0)
    assert book.tank_volume("right") == pytest.approx(400.0)
    book.record_delivery(0.0, amount=1500.0)  # more than fits: up to the capacity
    assert book.tank_volume("left") == pytest.approx(1150.0)
    assert book.stock == pytest.approx(2300.0)


def test_range_from_the_consumption_of_the_window():
    book = ledger(tanks=TANKS, range_days=7.0)
    book.set_stock(0.0, 1000.0)
    book.close_interval(0.0)
    assert book.range_days(0.0) is None
    for day in range(1, 11):
        run(book, day * DAY, 5.0)  # 10 L a day
        book.close_interval(day * DAY)
    assert book.daily_use(10 * DAY) == pytest.approx(10.0)
    assert book.range_days(10 * DAY) == pytest.approx((1000 - 100 - 20) / 10)


def test_checkpoints_are_thinned():
    book = ledger()
    for i in range(1, 3 * 288 + 1):  # three days of 5-minute intervals
        book.close_interval(i * 300.0)
    old = [p for p in book.checkpoints if p[0] < 3 * DAY - 2 * DAY]
    assert len(old) == 24  # one per hour
    assert len(book.checkpoints) == 24 + 2 * 288 + 1


# --- Readings and the measured factor ----------------------------------------------------------------------------


def survey(book: Ledger, ts: float, left: float, right: float, point: str = "front") -> None:
    book.record_level(ts, "left", point, height_cm=left)
    book.record_level(ts, "right", point, height_cm=right)


def test_factor_from_two_surveys():
    book = ledger(tanks=TANKS)
    survey(book, 0.0, 40.0, 110.0)  # 1200 L
    run(book, 50 * H, 50.0)  # 100 L at factor 1
    book.close_interval(50 * H)
    survey(book, 50 * H, 33.0, 103.0)  # 14 cm less: 112 L
    measured = book.measured_factor()
    assert measured is not None
    assert measured.value == pytest.approx(1.12)
    assert measured.measured == pytest.approx(112.0)
    # 4 readings of ±0.5 cm at 8 L/cm
    assert measured.uncertainty == pytest.approx((4 * 4.0**2) ** 0.5 / 100)


def test_factor_needs_the_same_points_and_complete_surveys():
    book = ledger(tanks=TANKS)
    survey(book, 0.0, 40.0, 110.0)
    run(book, 10 * H, 10.0)
    book.record_level(10 * H, "left", "front", height_cm=50.0)  # one tank only
    assert book.measured_factor() is None
    run(book, 20 * H, 10.0)
    survey(book, 20 * H, 50.0, 110.0, point="side")
    assert book.measured_factor() is None


def test_readings_of_a_survey_may_be_minutes_apart():
    book = ledger(tanks=TANKS)
    book.record_level(0.0, "left", "front", height_cm=40.0)
    book.record_level(0.0, "right", "front", height_cm=110.0)
    run(book, 10 * H, 10.0)
    book.close_interval(10 * H)
    book.record_level(10 * H, "left", "front", height_cm=38.0)
    run(book, 10 * H + 600, 0.1)
    book.close_interval(10 * H + 600)
    book.record_level(10 * H + 600, "right", "front", height_cm=108.0)
    assert book.measured_factor() is not None
    assert SURVEY_WINDOW_S > 600


def test_factor_counts_a_delivery_with_its_amount():
    book = ledger(tanks=TANKS)
    survey(book, 0.0, 20.0, 20.0)  # 320 L
    run(book, 10 * H, 10.0)  # 20 L nominal
    book.close_interval(10 * H)
    book.record_delivery(10 * H, amount=700.0, level_after=1000.0)
    survey(book, 10 * H, 62.0, 62.0)  # 992 L
    measured = book.measured_factor()
    assert measured is not None
    assert measured.value == pytest.approx((320 + 700 - 992) / 20)


def test_factor_skips_a_delivery_without_amount():
    book = ledger(tanks=TANKS)
    survey(book, 0.0, 20.0, 20.0)
    run(book, 10 * H, 10.0)
    book.close_interval(10 * H)
    book.record_delivery(10 * H, level_after=1000.0)
    survey(book, 10 * H, 62.0, 62.0)
    assert book.measured_factor() is None


def test_reading_errors():
    book = ledger(tanks=(*TANKS, TankSpec("bare", "Bare", 500.0)))
    with pytest.raises(LedgerError, match="tank_not_found"):
        book.record_level(0.0, "nope", "front", volume=1.0)
    with pytest.raises(LedgerError, match="height_or_volume"):
        book.record_level(0.0, "left", "front")
    with pytest.raises(LedgerError, match="point_required"):
        book.record_level(0.0, "left", " ", volume=1.0)
    with pytest.raises(LedgerError, match="tank_without_dimensions"):
        book.record_level(0.0, "bare", "front", height_cm=10.0)


# --- Levels and storage ------------------------------------------------------------------------------------------


def test_levels_follow_the_inputs():
    book = ledger()
    assert book.consumption_level is Level.ESTIMATED
    assert book.basis() == {
        "consumption": "runtime",
        "factor": "default",
        "heating_value": "default",
        "efficiency": "default",
    }
    book.set_factor(0.0, 1.1, Origin.MEASURED)
    book.record_delivery(0.0, level_after=1000.0)
    book.record_delivery(0.0, amount=100.0, energy=1004.0)
    assert book.consumption_level is Level.CALCULATED
    assert book.energy_level is Level.CALCULATED
    assert book.heat_level is Level.ESTIMATED  # the efficiency is the default


def test_round_trip():
    book = ledger(tanks=TANKS)
    book.set_stock(0.0, 1500.0, price=1.06)
    run(book, H, 3.0)
    book.close_interval(H)
    survey(book, H, 50.0, 120.0)
    book.set_factor(H, 1.25)
    copy = Ledger.from_dict(book.spec, book.to_dict())
    assert copy.to_dict() == book.to_dict()
    assert copy.restored
    run(copy, 2 * H, 1.0)  # the counter continues from the stored reading
    assert copy.runtime_h == pytest.approx(4.0)


def test_a_new_input_starts_over():
    book = ledger()
    run(book, H, 1.0)
    other = Ledger.from_dict(LedgerSpec(burner=BurnerSpec(InputKind.RUNTIME, "sensor.other", FLOW)), book.to_dict())
    other.observe(2 * H, 500.0)
    assert other.runtime_h == pytest.approx(1.0)  # the first reading of the new input is its baseline


def test_a_tank_read_again_after_the_burner_ran_starts_the_next_survey():
    book = ledger(tanks=TANKS)
    survey(book, 0.0, 40.0, 110.0)
    book.close_interval(60.0)
    survey(book, 60.0, 40.5, 110.0)  # read again at once: corrects the first
    run(book, 600.0, 5.0)
    book.close_interval(600.0)
    survey(book, 600.0, 39.5, 108.5)  # ten minutes later, 10 L at factor 1
    measured = book.measured_factor()
    assert measured is not None
    assert measured.measured == pytest.approx((1.0 + 1.5) * 8.0)
    assert measured.nominal == pytest.approx(10.0)


def test_after_a_total_a_reading_of_one_tank_keeps_the_total():
    book = ledger(tanks=TANKS)
    book.set_stock(0.0, 1150.0)  # spread by assumption
    book.record_level(0.0, "left", "front", volume=320.0)
    assert book.stock == pytest.approx(1150.0)
    assert book.tank_volume("right") == pytest.approx(830.0)
    book.record_level(0.0, "right", "front", volume=800.0)  # both read now: the total follows the readings
    assert book.stock == pytest.approx(1120.0)
    book.record_level(0.0, "left", "front", volume=300.0)
    assert book.tank_volume("right") == pytest.approx(800.0)


def test_after_a_delivery_on_a_t_piece_the_readings_divide_it():
    book = ledger(tanks=TANKS)
    book.set_stock(0.0, 250.0)
    book.record_delivery(0.0, amount=1000.0)
    book.record_level(0.0, "left", "front", height_cm=40.0)
    assert book.tank_volume("right") == pytest.approx(930.0)
    book.record_level(0.0, "right", "front", height_cm=110.0)
    assert book.stock == pytest.approx(1200.0)
