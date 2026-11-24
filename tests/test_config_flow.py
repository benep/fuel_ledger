"""Config flow, options flow and the tank subentry flow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fuel_ledger.const import (
    CONF_BURNER_ENTITY,
    CONF_CAPACITY,
    CONF_COMPONENT_KIND,
    CONF_DIAMETER,
    CONF_EFFICIENCY,
    CONF_ENTITY,
    CONF_INITIAL_FACTOR,
    CONF_INITIAL_STOCK,
    CONF_KIND,
    CONF_LENGTH,
    CONF_LEVEL_ENTITY,
    CONF_LINK,
    CONF_NOZZLE_GPH,
    CONF_PER_CM,
    CONF_POWER,
    CONF_POWER_ENTITY,
    CONF_RESIDUE,
    CONF_SHAPE,
    CONF_TABLE,
    DOMAIN,
    SUBENTRY_COMPONENT,
    SUBENTRY_TANK,
)

COMPONENT = Path(__file__).parents[1] / "custom_components" / DOMAIN
ACCURACY = "accuracy"
RUNTIME = "sensor.burner_runtime"
BURNER = "binary_sensor.burner"
METER = "sensor.oil_meter"
POWER = "sensor.boiler_power"


@pytest.fixture(autouse=True)
def inputs(hass: HomeAssistant) -> None:
    hass.states.async_set(RUNTIME, "12345", {"unit_of_measurement": "h", "state_class": "total_increasing"})
    hass.states.async_set(BURNER, "off")
    hass.states.async_set(METER, "1.0", {"unit_of_measurement": "m³", "state_class": "total_increasing"})
    hass.states.async_set(POWER, "50", {"unit_of_measurement": "W", "state_class": "measurement"})
    hass.states.async_set("sensor.level_cm", "50", {"unit_of_measurement": "cm"})
    hass.states.async_set("sensor.temperature", "20", {"unit_of_measurement": "°C"})


async def start(hass: HomeAssistant, name: str = "Heating oil") -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": name})
    assert result["step_id"] == "burner"
    return result["flow_id"]


async def test_first_setup_with_run_time_and_two_tanks(hass: HomeAssistant):
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_ENTITY: RUNTIME})
    assert result["step_id"] == "nozzle"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NOZZLE_GPH: 0.5, "factor": 1.25, ACCURACY: {CONF_BURNER_ENTITY: BURNER}}
    )
    assert result["step_id"] == "tanks"
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {"tank_count": 2, CONF_CAPACITY: 1000, "stock": 1500, ACCURACY: {CONF_PER_CM: 8.0, CONF_RESIDUE: 10}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.options[CONF_KIND] == "runtime"
    assert entry.options[CONF_NOZZLE_GPH] == 0.5
    assert entry.options[CONF_BURNER_ENTITY] == BURNER
    assert entry.data == {CONF_INITIAL_STOCK: 1500, CONF_INITIAL_FACTOR: 1.25}
    tanks = [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TANK]
    assert sorted(t.title for t in tanks) == ["Tank 1", "Tank 2"]
    assert tanks[0].data == {CONF_CAPACITY: 1000, CONF_SHAPE: "linear", CONF_PER_CM: 8.0, CONF_RESIDUE: 10}
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.heating_oil_stock").state) == 1500


async def test_meter_skips_the_nozzle_and_no_tanks(hass: HomeAssistant):
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_ENTITY: METER})
    assert result["step_id"] == "tanks"
    result = await hass.config_entries.flow.async_configure(flow_id, {"tank_count": 1})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].options[CONF_KIND] == "meter"
    assert not result["result"].subentries


@pytest.mark.parametrize(
    ("entity", "error"),
    [("sensor.temperature", "not_an_input"), ("sensor.nope", "entity_not_found")],
)
async def test_burner_errors(hass: HomeAssistant, entity: str, error: str):
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_ENTITY: entity})
    assert result["errors"] == {CONF_ENTITY: error}


async def test_run_time_must_be_a_counter(hass: HomeAssistant):
    hass.states.async_set("sensor.hours_today", "3", {"unit_of_measurement": "h", "state_class": "measurement"})
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_ENTITY: "sensor.hours_today"})
    assert result["errors"] == {CONF_ENTITY: "not_cumulative"}


async def test_nozzle_or_throughput_is_required(hass: HomeAssistant):
    flow_id = await start(hass)
    await hass.config_entries.flow.async_configure(flow_id, {CONF_ENTITY: BURNER})
    result = await hass.config_entries.flow.async_configure(flow_id, {})
    assert result["errors"] == {CONF_NOZZLE_GPH: "nozzle_required"}
    result = await hass.config_entries.flow.async_configure(flow_id, {ACCURACY: {"nominal_flow": 2.0}})
    assert result["step_id"] == "tanks"


def entry_with(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Heating oil",
        options={CONF_ENTITY: RUNTIME, CONF_KIND: "runtime", CONF_NOZZLE_GPH: 0.5, **options},
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_fuel_and_nozzle(hass: HomeAssistant):
    entry = entry_with(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "fuel"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_EFFICIENCY: 90})
    assert result["errors"] == {CONF_EFFICIENCY: "efficiency_range"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_EFFICIENCY: 0.933})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EFFICIENCY] == 0.933
    assert entry.options[CONF_NOZZLE_GPH] == 0.5

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "burner"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_ENTITY: RUNTIME})
    assert result["step_id"] == "nozzle"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NOZZLE_GPH: 0.55, ACCURACY: {"pump_pressure": 10}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["pump_pressure"] == 10
    assert entry.options[CONF_EFFICIENCY] == 0.933
    await hass.async_block_till_done()


async def test_tank_subentry_shapes(hass: HomeAssistant):
    entry = entry_with(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    async def add(user_input: dict) -> dict:
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TANK), context={"source": SOURCE_USER}
        )
        return await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)

    result = await add({"name": "Steel", CONF_CAPACITY: 3000, CONF_SHAPE: "horizontal_cylinder"})
    assert result["step_id"] == "cylinder"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_DIAMETER: 125, CONF_LENGTH: 250}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await add({"name": "Table", CONF_CAPACITY: 1500, CONF_SHAPE: "table"})
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {CONF_TABLE: "10"})
    assert result["errors"] == {CONF_TABLE: "invalid_table"}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {CONF_TABLE: "10: 95\n20: 200"})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await add(
        {"name": "Sensor", CONF_CAPACITY: 1000, CONF_SHAPE: "linear", ACCURACY: {CONF_LEVEL_ENTITY: "sensor.level_cm"}}
    )
    assert result["errors"] == {ACCURACY: "level_needs_dimensions"}

    tanks = {s.title: s for s in entry.subentries.values()}
    assert tanks["Steel"].data == {
        CONF_CAPACITY: 3000,
        CONF_SHAPE: "horizontal_cylinder",
        CONF_DIAMETER: 125,
        CONF_LENGTH: 250,
    }
    assert tanks["Table"].data[CONF_TABLE] == [[10.0, 95.0], [20.0, 200.0]]

    # Reconfiguring keeps the ID and shows the stored values.
    steel = tanks["Steel"]
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TANK), context={"source": SOURCE_RECONFIGURE, "subentry_id": steel.subentry_id}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Steel tank", CONF_CAPACITY: 3000, CONF_SHAPE: "horizontal_cylinder"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_DIAMETER: 125, CONF_LENGTH: 260}
    )
    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[steel.subentry_id].title == "Steel tank"
    assert entry.subentries[steel.subentry_id].data[CONF_LENGTH] == 260
    await hass.async_block_till_done()


def test_translations_have_the_same_keys():
    def keys(data, prefix=""):
        if isinstance(data, dict):
            return {k for key, value in data.items() for k in keys(value, f"{prefix}{key}.")}
        return {prefix}

    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    assert json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")) == strings
    assert keys(json.loads((COMPONENT / "translations" / "de.json").read_text(encoding="utf-8"))) == keys(strings)


def test_every_action_field_is_translated():
    from homeassistant.util.yaml import load_yaml

    services = load_yaml(str(COMPONENT / "services.yaml"))
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))["services"]
    assert set(services) == set(strings)
    for name, service in services.items():
        assert set(service["fields"]) == set(strings[name]["fields"]), name


async def test_power_alone_with_its_components(hass: HomeAssistant):
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_ENTITY: POWER})
    assert result["step_id"] == "components"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"burner_power": 180, ACCURACY: {"base_power": 4, "circuit_pump_power": 45}}
    )
    assert result["step_id"] == "nozzle"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NOZZLE_GPH: 0.5, ACCURACY: {"prepurge_s": 11}}
    )
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"tank_count": 2, CONF_CAPACITY: 1000, CONF_LINK: "bottom"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.options[CONF_KIND] == "power"
    assert entry.options["base_power"] == 4
    assert entry.options["prepurge_s"] == 11
    assert entry.options[CONF_LINK] == "bottom"
    components = {s.title: s.data for s in entry.subentries.values() if s.subentry_type == SUBENTRY_COMPONENT}
    assert components == {
        "Burner": {CONF_COMPONENT_KIND: "burner", CONF_POWER: 180},
        "Heating circuit pump": {CONF_COMPONENT_KIND: "circuit_pump", CONF_POWER: 45},
    }
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.burner").state == "off"
    assert hass.states.get("binary_sensor.heating_circuit_pump").state == "on"  # 50 W: nearest to 4 + 45


async def test_run_time_with_a_power_meter_beside_it(hass: HomeAssistant):
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ENTITY: RUNTIME, ACCURACY: {CONF_POWER_ENTITY: "sensor.temperature"}}
    )
    assert result["errors"] == {ACCURACY: "not_power"}
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ENTITY: RUNTIME, ACCURACY: {CONF_POWER_ENTITY: POWER}}
    )
    assert result["step_id"] == "components"
    result = await hass.config_entries.flow.async_configure(flow_id, {ACCURACY: {"hot_water_pump_power": 70}})
    assert result["step_id"] == "nozzle"
    await hass.config_entries.flow.async_configure(flow_id, {CONF_NOZZLE_GPH: 0.5})
    result = await hass.config_entries.flow.async_configure(flow_id, {"tank_count": 0})
    entry = result["result"]
    assert entry.options[CONF_POWER_ENTITY] == POWER
    assert [s.title for s in entry.subentries.values()] == ["Hot water pump"]


async def test_component_subentry(hass: HomeAssistant):
    entry = entry_with(hass, **{CONF_POWER_ENTITY: POWER})
    assert await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_COMPONENT), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Pump", CONF_COMPONENT_KIND: "circuit_pump", CONF_POWER: 45, ACCURACY: {"on_delay_s": 90}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    pump = next(s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_COMPONENT)
    assert pump.data == {CONF_COMPONENT_KIND: "circuit_pump", CONF_POWER: 45, "on_delay_s": 90}
    await hass.async_block_till_done()
