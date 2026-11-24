"""The Home Assistant layer: setup, sensors, actions, factor, restart."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.fuel_ledger.const import (
    CONF_BASE_POWER,
    CONF_BURNER_ENTITY,
    CONF_CAPACITY,
    CONF_COMPONENT_KIND,
    CONF_ENTITY,
    CONF_INITIAL_FACTOR,
    CONF_INITIAL_STOCK,
    CONF_KIND,
    CONF_LEVEL_ENTITY,
    CONF_NOZZLE_GPH,
    CONF_OFF_DELAY,
    CONF_ON_DELAY,
    CONF_PER_CM,
    CONF_POWER,
    CONF_POWER_ENTITY,
    CONF_PREPURGE_S,
    CONF_RESIDUE,
    DOMAIN,
    SUBENTRY_COMPONENT,
    SUBENTRY_TANK,
)

RUNTIME = "sensor.burner_runtime"
BURNER = "binary_sensor.burner"
METER = "sensor.oil_meter"
GPH = 0.5
FLOW = GPH * 3.785411784


def tank(tank_id: str, title: str, **data) -> dict:
    return {
        "subentry_id": tank_id,
        "subentry_type": SUBENTRY_TANK,
        "title": title,
        "unique_id": None,
        "data": {CONF_CAPACITY: 1000.0, CONF_PER_CM: 8.0, CONF_RESIDUE: 10.0, **data},
    }


TANKS = [tank("left", "Left"), tank("right", "Right")]


@pytest.fixture(autouse=True)
def start_time(freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-17 16:00:30+00:00")


async def setup(hass: HomeAssistant, options: dict, data: dict | None = None, subentries=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Heating oil", data=data or {}, options=options, subentries_data=subentries or []
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def runtime_options(**extra) -> dict:
    return {CONF_ENTITY: RUNTIME, CONF_KIND: "runtime", CONF_NOZZLE_GPH: GPH, **extra}


def value(hass: HomeAssistant, entity_id: str) -> float:
    return float(hass.states.get(entity_id).state)


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: int = 5) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_run_time_counter_books_consumption_energy_and_stock(hass: HomeAssistant, freezer):
    hass.states.async_set(RUNTIME, "12345.55", {"unit_of_measurement": "h", "state_class": "total_increasing"})
    await setup(hass, runtime_options(), {CONF_INITIAL_STOCK: 1500.0, CONF_INITIAL_FACTOR: 1.25}, TANKS)
    hass.states.async_set(RUNTIME, "12346.55", {"unit_of_measurement": "h"})
    await tick(hass, freezer)

    assert value(hass, "sensor.heating_oil_consumption") == pytest.approx(FLOW * 1.25, abs=0.01)
    assert value(hass, "sensor.heating_oil_energy") == pytest.approx(FLOW * 1.25 * 10, abs=0.1)
    assert value(hass, "sensor.heating_oil_heat") == pytest.approx(FLOW * 1.25 * 9, abs=0.1)
    assert value(hass, "sensor.heating_oil_stock") == pytest.approx(1500 - FLOW * 1.25, abs=0.01)
    assert value(hass, "sensor.heating_oil_fill_level") == pytest.approx((1500 - FLOW * 1.25) / 20, abs=0.01)
    assert value(hass, "number.heating_oil_correction_factor") == 1.25
    state = hass.states.get("sensor.heating_oil_consumption")
    assert state.attributes["level"] == "estimated"
    assert state.attributes["basis"]["factor"] == "set"
    assert state.attributes["device_class"] == "gas"
    assert hass.states.get("binary_sensor.heating_oil_low_stock").state == "off"
    assert hass.states.get("sensor.heating_oil_price_per_litre").state == "unknown"
    # No burner state: no flow rate.
    assert hass.states.get("sensor.heating_oil_flow_rate") is None


async def test_delivery_set_stock_and_price_for_the_energy_dashboard(hass: HomeAssistant, freezer):
    hass.states.async_set(RUNTIME, "100", {"unit_of_measurement": "h"})
    entry = await setup(hass, runtime_options(), subentries=TANKS)
    await hass.services.async_call(
        DOMAIN,
        "set_stock",
        {"config_entry_id": entry.entry_id, "volume": 300, "price": 1.10, "heating_value": 9.9},
        blocking=True,
    )
    response = await hass.services.async_call(
        DOMAIN,
        "record_delivery",
        {
            "config_entry_id": entry.entry_id,
            "amount": 1200,
            "total_price": 1260.0,
            "energy": 12096.0,
            "co2": 3204.0,
            "product": "HEL",
        },
        blocking=True,
        return_response=True,
    )
    assert response["rest"] == pytest.approx(300.0)
    assert response["price_after"] == pytest.approx(1.06)
    assert value(hass, "sensor.heating_oil_stock") == pytest.approx(1500.0)
    assert value(hass, "sensor.heating_oil_price_per_litre") == pytest.approx(1.06)
    price = hass.states.get("sensor.heating_oil_price_per_kwh")
    assert price.attributes["unit_of_measurement"] == "EUR/kWh"
    assert float(price.state) == pytest.approx(1.06 / 10.044, abs=1e-3)
    last = hass.states.get("sensor.heating_oil_last_delivery")
    assert last.attributes["product"] == "HEL"

    hass.states.async_set(RUNTIME, "101", {"unit_of_measurement": "h"})
    await tick(hass, freezer)
    assert value(hass, "sensor.heating_oil_cost") == pytest.approx(FLOW * 1.06, abs=0.01)


async def test_action_errors_are_translated(hass: HomeAssistant):
    hass.states.async_set(RUNTIME, "100", {"unit_of_measurement": "h"})
    entry = await setup(hass, runtime_options())
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "record_delivery", {"config_entry_id": entry.entry_id, "amount": 1000}, blocking=True
        )
    assert err.value.translation_key == "stock_unknown"
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "set_stock", {"config_entry_id": "nope", "volume": 1}, blocking=True)
    assert err.value.translation_key == "entry_not_found"


async def test_readings_give_the_measured_factor_and_the_button_applies_it(hass: HomeAssistant, freezer):
    hass.states.async_set(RUNTIME, "100", {"unit_of_measurement": "h"})
    entry = await setup(hass, runtime_options(), subentries=TANKS)
    devices = dr.async_get(hass)
    left = devices.async_get_device_by_identifier((DOMAIN, "left"), entry.entry_id).id
    right = devices.async_get_device_by_identifier((DOMAIN, "right"), entry.entry_id).id
    assert hass.states.get("button.heating_oil_apply_measured_factor").state == "unavailable"

    async def survey(left_cm: float, right_cm: float) -> dict:
        await hass.services.async_call(
            DOMAIN, "record_level", {"device_id": left, "level": left_cm, "point": "front"}, blocking=True
        )
        return await hass.services.async_call(
            DOMAIN,
            "record_level",
            {"device_id": right, "level": right_cm, "point": "front"},
            blocking=True,
            return_response=True,
        )

    await survey(40.0, 110.0)
    assert value(hass, "sensor.left_last_reading") == pytest.approx(320.0)
    hass.states.async_set(RUNTIME, "150", {"unit_of_measurement": "h"})  # 50 h: 94.6 L at factor 1
    await tick(hass, freezer)
    response = await survey(33.0, 104.0)  # 13 cm, 104 L
    assert response["measured_factor"] == pytest.approx(104 / (50 * FLOW), abs=1e-3)
    assert value(hass, "sensor.heating_oil_measured_factor") == pytest.approx(104 / (50 * FLOW), abs=1e-3)

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.heating_oil_apply_measured_factor"}, blocking=True
    )
    factor = hass.states.get("number.heating_oil_correction_factor")
    assert float(factor.state) == pytest.approx(104 / (50 * FLOW), abs=1e-3)
    assert factor.attributes["origin"] == "measured"
    assert hass.states.get("sensor.heating_oil_consumption").attributes["level"] == "calculated"

    with pytest.raises(ServiceValidationError) as err:
        main = devices.async_get_device_by_identifier((DOMAIN, entry.entry_id), entry.entry_id).id
        await hass.services.async_call(
            DOMAIN, "record_level", {"device_id": main, "level": 1, "point": "front"}, blocking=True
        )
    assert err.value.translation_key == "not_a_tank"


async def test_factor_entity_applies_from_now_on(hass: HomeAssistant, freezer):
    hass.states.async_set(RUNTIME, "100", {"unit_of_measurement": "h"})
    await setup(hass, runtime_options())
    hass.states.async_set(RUNTIME, "101", {"unit_of_measurement": "h"})
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.heating_oil_correction_factor", "value": 1.5}, blocking=True
    )
    hass.states.async_set(RUNTIME, "102", {"unit_of_measurement": "h"})
    await tick(hass, freezer)
    assert value(hass, "sensor.heating_oil_consumption") == pytest.approx(FLOW * 2.5, abs=0.01)


async def test_restart_keeps_the_books(hass: HomeAssistant, freezer):
    hass.states.async_set(RUNTIME, "100", {"unit_of_measurement": "h"})
    entry = await setup(hass, runtime_options(), {CONF_INITIAL_STOCK: 500.0})
    hass.states.async_set(RUNTIME, "101", {"unit_of_measurement": "h"})
    await tick(hass, freezer)
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.states.async_set(RUNTIME, "102", {"unit_of_measurement": "h"})  # ran while unloaded
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer)
    assert value(hass, "sensor.heating_oil_consumption") == pytest.approx(FLOW * 2, abs=0.01)
    assert value(hass, "sensor.heating_oil_stock") == pytest.approx(500 - FLOW * 2, abs=0.01)


async def test_burner_input_counts_run_time_and_flow(hass: HomeAssistant, freezer):
    hass.states.async_set(BURNER, "off")
    await setup(hass, {CONF_ENTITY: BURNER, CONF_KIND: "burner", CONF_NOZZLE_GPH: GPH, CONF_PREPURGE_S: 30})
    hass.states.async_set(BURNER, "on")
    await hass.async_block_till_done()
    assert value(hass, "sensor.heating_oil_flow_rate") == pytest.approx(FLOW, abs=0.01)
    freezer.tick(timedelta(minutes=10, seconds=30))
    hass.states.async_set(BURNER, "off")
    await tick(hass, freezer)
    assert value(hass, "sensor.heating_oil_burner_run_time") == pytest.approx(10 / 60, abs=1e-3)
    assert value(hass, "sensor.heating_oil_flow_rate") == 0.0


async def test_run_time_with_burner_state_gives_a_flow_rate(hass: HomeAssistant):
    hass.states.async_set(RUNTIME, "100", {"unit_of_measurement": "h"})
    hass.states.async_set(BURNER, "on")
    await setup(hass, runtime_options(**{CONF_BURNER_ENTITY: BURNER}))
    assert value(hass, "sensor.heating_oil_flow_rate") == pytest.approx(FLOW, abs=0.01)
    hass.states.async_set(BURNER, "off")
    await hass.async_block_till_done()
    assert value(hass, "sensor.heating_oil_flow_rate") == 0.0


async def test_meter_has_no_factor(hass: HomeAssistant, freezer):
    hass.states.async_set(METER, "1.000", {"unit_of_measurement": "m³"})
    await setup(hass, {CONF_ENTITY: METER, CONF_KIND: "meter"})
    hass.states.async_set(METER, "1.004", {"unit_of_measurement": "m³"})
    await tick(hass, freezer)
    assert value(hass, "sensor.heating_oil_consumption") == pytest.approx(4.0, abs=0.01)
    assert hass.states.get("sensor.heating_oil_consumption").attributes["level"] == "measured"
    assert hass.states.get("number.heating_oil_correction_factor") is None
    assert hass.states.get("button.heating_oil_apply_measured_factor") is None


async def test_level_sensors_measure_the_stock(hass: HomeAssistant, freezer):
    hass.states.async_set(RUNTIME, "100", {"unit_of_measurement": "h"})
    hass.states.async_set("sensor.left_level", "50", {"unit_of_measurement": "cm"})
    hass.states.async_set("sensor.right_level", "40", {"unit_of_measurement": "%"})
    tanks = [
        tank("left", "Left", **{CONF_LEVEL_ENTITY: "sensor.left_level"}),
        tank("right", "Right", **{CONF_LEVEL_ENTITY: "sensor.right_level"}),
    ]
    await setup(hass, runtime_options(), subentries=tanks)
    assert value(hass, "sensor.heating_oil_stock") == pytest.approx(400 + 400)
    assert hass.states.get("sensor.heating_oil_stock").attributes["level"] == "measured"
    assert value(hass, "sensor.left_content") == pytest.approx(400)


async def test_entities_and_devices(hass: HomeAssistant):
    hass.states.async_set(RUNTIME, "100", {"unit_of_measurement": "h"})
    entry = await setup(hass, runtime_options(), subentries=TANKS)
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {e.unique_id for e in entities} >= {f"{entry.entry_id}_consumption", "left_last_reading"}
    tank_device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "left"), entry.entry_id)
    assert tank_device.model == "Tank"
    assert entry.state is ConfigEntryState.LOADED


POWER = "sensor.heating_power"


def component(component_id: str, title: str, kind: str, watts: float, **data) -> dict:
    return {
        "subentry_id": component_id,
        "subentry_type": SUBENTRY_COMPONENT,
        "title": title,
        "unique_id": None,
        "data": {CONF_COMPONENT_KIND: kind, CONF_POWER: watts, **data},
    }


COMPONENTS = [
    component("burner", "Burner", "burner", 180.0),
    component("circuit", "Circuit pump", "circuit_pump", 45.0, **{CONF_ON_DELAY: 60, CONF_OFF_DELAY: 240}),
]


async def test_power_input_counts_the_burner_and_confirms_a_pump_later(hass: HomeAssistant, freezer):
    hass.states.async_set(POWER, "4", {"unit_of_measurement": "W"})
    await setup(
        hass,
        {CONF_ENTITY: POWER, CONF_KIND: "power", CONF_NOZZLE_GPH: GPH, CONF_BASE_POWER: 4.0},
        subentries=COMPONENTS,
    )
    assert hass.states.get("binary_sensor.circuit_pump").state == "off"
    hass.states.async_set(POWER, "50", {"unit_of_measurement": "W"})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.circuit_pump").state == "off"  # not yet confirmed
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.circuit_pump").state == "on"
    assert value(hass, "sensor.circuit_pump_power") == pytest.approx(46.0)

    hass.states.async_set(POWER, "230", {"unit_of_measurement": "W"})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.burner").state == "on"
    assert value(hass, "sensor.heating_oil_flow_rate") == pytest.approx(FLOW, abs=0.01)
    freezer.tick(timedelta(minutes=30))
    hass.states.async_set(POWER, "49", {"unit_of_measurement": "W"})
    await tick(hass, freezer)
    assert value(hass, "sensor.heating_oil_burner_run_time") == pytest.approx(0.5, abs=1e-3)
    assert value(hass, "sensor.heating_oil_consumption") == pytest.approx(FLOW / 2, abs=0.01)
    assert value(hass, "sensor.burner_power") == 0.0


async def test_run_time_with_a_power_meter_takes_the_flow_from_the_burner_in_it(hass: HomeAssistant):
    hass.states.async_set(RUNTIME, "100", {"unit_of_measurement": "h"})
    hass.states.async_set(POWER, "184", {"unit_of_measurement": "W"})
    await setup(hass, runtime_options(**{CONF_POWER_ENTITY: POWER, CONF_BASE_POWER: 4.0}), subentries=COMPONENTS)
    assert value(hass, "sensor.heating_oil_flow_rate") == pytest.approx(FLOW, abs=0.01)
    hass.states.async_set(POWER, "4", {"unit_of_measurement": "W"})
    await hass.async_block_till_done()
    assert value(hass, "sensor.heating_oil_flow_rate") == 0.0
    assert value(hass, "sensor.heating_oil_consumption") == 0.0  # the counter books, not the power


async def test_tanks_on_a_t_piece_each_with_their_content(hass: HomeAssistant, freezer):
    hass.states.async_set(RUNTIME, "100", {"unit_of_measurement": "h"})
    entry = await setup(hass, runtime_options(), subentries=TANKS)
    devices = dr.async_get(hass)
    for tank_id, level in (("left", 40.0), ("right", 110.0)):
        device = devices.async_get_device_by_identifier((DOMAIN, tank_id), entry.entry_id).id
        await hass.services.async_call(
            DOMAIN, "record_level", {"device_id": device, "level": level, "point": "front"}, blocking=True
        )
    assert value(hass, "sensor.heating_oil_stock") == pytest.approx(1200.0)
    hass.states.async_set(RUNTIME, "110", {"unit_of_measurement": "h"})
    await tick(hass, freezer)
    assert value(hass, "sensor.left_content") == pytest.approx(320.0)
    assert value(hass, "sensor.right_content") == pytest.approx(880.0 - 10 * FLOW, abs=0.01)
    assert value(hass, "sensor.left_level") == pytest.approx(40.0)


async def test_power_meter_unavailable_stops_the_burner_and_its_return_is_no_start(hass: HomeAssistant, freezer):
    hass.states.async_set(POWER, "184", {"unit_of_measurement": "W"})
    await setup(
        hass,
        {CONF_ENTITY: POWER, CONF_KIND: "power", CONF_NOZZLE_GPH: GPH, CONF_BASE_POWER: 4.0},
        subentries=COMPONENTS,
    )
    freezer.tick(timedelta(minutes=6))
    hass.states.async_set(POWER, "unavailable")
    await tick(hass, freezer, minutes=60)  # an hour without the meter: nothing is booked for it
    assert value(hass, "sensor.heating_oil_burner_run_time") == pytest.approx(0.1, abs=1e-3)
    assert hass.states.get("binary_sensor.burner").state == "unknown"
    hass.states.async_set(POWER, "184", {"unit_of_measurement": "W"})
    await tick(hass, freezer, minutes=6)
    assert value(hass, "sensor.heating_oil_burner_run_time") == pytest.approx(0.2, abs=1e-3)
    assert hass.states.get("binary_sensor.burner").state == "on"


async def test_components_too_alike_raise_a_repair_note(hass: HomeAssistant):
    hass.states.async_set(POWER, "4", {"unit_of_measurement": "W"})
    twin = component("circ", "Circulation pump", "circulation_pump", 43.0)
    entry = await setup(
        hass,
        {CONF_ENTITY: POWER, CONF_KIND: "power", CONF_NOZZLE_GPH: GPH, CONF_BASE_POWER: 4.0},
        subentries=[*COMPONENTS, twin],
    )
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"components_alike_{entry.entry_id}")
    assert issue is not None
    assert "Circulation pump (43 W)" in issue.translation_placeholders["pairs"]
    assert hass.states.get("binary_sensor.circulation_pump") is not None


async def test_power_input_without_a_burner_does_not_load(hass: HomeAssistant):
    hass.states.async_set(POWER, "4", {"unit_of_measurement": "W"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Heating oil",
        options={CONF_ENTITY: POWER, CONF_KIND: "power", CONF_NOZZLE_GPH: GPH},
        subentries_data=COMPONENTS[1:],
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert "no component is the burner" in (entry.reason or "")
