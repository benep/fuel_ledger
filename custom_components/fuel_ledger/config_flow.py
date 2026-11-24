"""Config flow: the fuel store with its burner, its options, and the tanks as subentries.

Every form asks for the minimum first; everything that makes the books more accurate sits in a collapsed section.
Section fields are stored flat with the keys from const.py. Reconfiguring a tank keeps its ID, so its readings stay.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import probatio as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_UNIT_OF_MEASUREMENT, CONF_NAME, PERCENTAGE
from homeassistant.core import HomeAssistant, callback, split_entity_id
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
from homeassistant.util.ulid import ulid_now

from . import texts
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
    CONF_INITIAL_FACTOR,
    CONF_INITIAL_STOCK,
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
    DOMAIN,
    SUBENTRY_COMPONENT,
    SUBENTRY_TANK,
)
from .engine import HEATING_OIL, ComponentKind, InputKind, Link, Shape, format_table, parse_table
from .engine.spec import (
    DEFAULT_LOW_PERCENT,
    DEFAULT_RANGE_DAYS,
    DEFAULT_READING_ACCURACY_CM,
)
from .model import CENTIMETRES, LITRES, WATTS, input_kind
from .texts import async_texts

SECTION_ACCURACY = "accuracy"

# Form-only keys of the first setup.
CONF_TANK_COUNT = "tank_count"
CONF_FACTOR = "factor"
CONF_STOCK = "stock"

STEP_BURNER = "burner"
STEP_FUEL = "fuel"
STEP_STOCK = "stock"
STEP_POWER = "power"

ERROR_ENTITY_NOT_FOUND = "entity_not_found"
ERROR_NOT_AN_INPUT = "not_an_input"
ERROR_NOT_CUMULATIVE = "not_cumulative"
ERROR_NOT_POSITIVE = "not_positive"
ERROR_NAME_REQUIRED = "name_required"
ERROR_NOZZLE_REQUIRED = "nozzle_required"
ERROR_NOT_A_LEVEL = "not_a_level"
ERROR_LEVEL_NEEDS_DIMENSIONS = "level_needs_dimensions"
ERROR_INVALID_TABLE = "invalid_table"
ERROR_EFFICIENCY = "efficiency_range"
ERROR_TOO_MANY_TANKS = "too_many_tanks"
ERROR_NOT_POWER = "not_power"
ERROR_BURNER_REQUIRED = "burner_required"

MAX_TANKS = 10


# --- Selectors ---------------------------------------------------------------------------------------------------


def _entity(domain: str | list[str]) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domain))


def _number(unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _select(options: tuple[str, ...], translation_key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[str(o) for o in options], translation_key=translation_key, mode=SelectSelectorMode.DROPDOWN
        )
    )


def _accuracy(fields: dict[vol.Marker, Any]) -> section:
    return section(vol.Schema(fields), {"collapsed": True})


def _strip_empty(data: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v not in (None, "", {})}


def _subentry(subentry_type: str, title: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """A subentry of the first setup, with its ID given: Home Assistant takes it as it is."""
    return {
        "subentry_type": subentry_type,
        "subentry_id": ulid_now(),
        "title": title,
        "data": dict(data),
        "unique_id": None,
    }


# --- Checks ------------------------------------------------------------------------------------------------------


def _state_info(hass: HomeAssistant, entity_id_or_uuid: str) -> tuple[str, str | None, str | None, str | None] | None:
    """Entity ID, unit, device class and state class, from the state or else from the registry."""
    registry = er.async_get(hass)
    entity_id = er.async_resolve_entity_id(registry, entity_id_or_uuid)
    if entity_id is None:
        return None
    state = hass.states.get(entity_id)
    entry = registry.async_get(entity_id)
    if state is None and entry is None:
        return None
    attributes: Mapping[str, Any] = state.attributes if state else {}
    unit = attributes.get(ATTR_UNIT_OF_MEASUREMENT, entry.unit_of_measurement if entry else None)
    device_class = attributes.get(
        ATTR_DEVICE_CLASS, (entry.device_class or entry.original_device_class) if entry else None
    )
    state_class = attributes.get("state_class", (entry.capabilities or {}).get("state_class") if entry else None)
    return entity_id, unit, device_class, state_class


class _Checker:
    """Collects form errors. Fields inside a section report their error on the section, as core does."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.errors: dict[str, str] = {}

    def error(self, field: str, error: str) -> None:
        self.errors.setdefault(field, error)

    def name(self, value: str | None, field: str = CONF_NAME) -> str:
        name = (value or "").strip()
        if not name:
            self.error(field, ERROR_NAME_REQUIRED)
        return name

    def positive(self, value: float | None, field: str, *, zero: bool = False) -> float | None:
        if value is None:
            return None
        if value < 0 or (value == 0 and not zero):
            self.error(field, ERROR_NOT_POSITIVE)
            return None
        return float(value)

    def input(self, value: str | None, field: str) -> tuple[str, InputKind] | None:
        """The burner's input: entity ID and how it is read."""
        info = _state_info(self.hass, value) if value else None
        if info is None:
            self.error(field, ERROR_ENTITY_NOT_FOUND)
            return None
        entity_id, unit, device_class, state_class = info
        kind = input_kind(split_entity_id(entity_id)[0], unit, device_class)
        if kind is None:
            self.error(field, ERROR_NOT_AN_INPUT)
            return None
        if not kind.counts_itself and state_class == "measurement":
            self.error(field, ERROR_NOT_CUMULATIVE)
            return None
        return entity_id, kind

    def entity(self, value: str | None, domain: str, field: str) -> str | None:
        if not value:
            return None
        info = _state_info(self.hass, value)
        if info is None or split_entity_id(info[0])[0] != domain:
            self.error(field, ERROR_ENTITY_NOT_FOUND)
            return None
        return info[0]

    def power(self, value: str | None, field: str) -> str | None:
        """A power meter of the heating: a sensor in W or kW."""
        if not value:
            return None
        info = _state_info(self.hass, value)
        if info is None or split_entity_id(info[0])[0] != "sensor":
            self.error(field, ERROR_ENTITY_NOT_FOUND)
            return None
        if info[1] not in WATTS:
            self.error(field, ERROR_NOT_POWER)
            return None
        return info[0]

    def level(self, value: str | None, field: str, converts_height: bool) -> str | None:
        """A level sensor: a height, a volume or a percentage."""
        if not value:
            return None
        info = _state_info(self.hass, value)
        if info is None or split_entity_id(info[0])[0] != "sensor":
            self.error(field, ERROR_ENTITY_NOT_FOUND)
            return None
        unit = info[1]
        if unit in CENTIMETRES:
            if not converts_height:
                self.error(field, ERROR_LEVEL_NEEDS_DIMENSIONS)
                return None
        elif unit not in LITRES and unit != PERCENTAGE:
            self.error(field, ERROR_NOT_A_LEVEL)
            return None
        return info[0]


# --- The burner, shared by the first setup and the options -------------------------------------------------------


def _nozzle_schema(kind: InputKind) -> vol.Schema:
    fields: dict[vol.Marker, Any] = {
        vol.Optional(CONF_NOMINAL_FLOW): _number("L/h"),
        vol.Optional(CONF_PUMP_PRESSURE): _number("bar"),
        vol.Optional(CONF_TEST_PRESSURE): _number("bar"),
    }
    if kind is InputKind.RUNTIME:
        fields[vol.Optional(CONF_BURNER_ENTITY)] = _entity("binary_sensor")
    if kind.counts_itself:
        fields[vol.Optional(CONF_PREPURGE_S)] = _number("s")
    return vol.Schema(
        {vol.Optional(CONF_NOZZLE_GPH): _number("GPH"), vol.Optional(SECTION_ACCURACY): _accuracy(fields)}
    )


def _check_nozzle(check: _Checker, user_input: Mapping[str, Any], kind: InputKind) -> dict[str, Any]:
    """The burner options of the nozzle form; a nozzle or a nominal flow is required."""
    more = user_input.get(SECTION_ACCURACY) or {}
    nozzle = check.positive(user_input.get(CONF_NOZZLE_GPH), CONF_NOZZLE_GPH)
    flow = check.positive(more.get(CONF_NOMINAL_FLOW), SECTION_ACCURACY)
    if nozzle is None and flow is None and not check.errors:
        check.error(CONF_NOZZLE_GPH, ERROR_NOZZLE_REQUIRED)
    options = {
        CONF_NOZZLE_GPH: nozzle,
        CONF_NOMINAL_FLOW: flow,
        CONF_PUMP_PRESSURE: check.positive(more.get(CONF_PUMP_PRESSURE), SECTION_ACCURACY),
        CONF_TEST_PRESSURE: check.positive(more.get(CONF_TEST_PRESSURE), SECTION_ACCURACY),
    }
    if kind is InputKind.RUNTIME:
        options[CONF_BURNER_ENTITY] = check.entity(more.get(CONF_BURNER_ENTITY), "binary_sensor", SECTION_ACCURACY)
    if kind.counts_itself:
        options[CONF_PREPURGE_S] = check.positive(more.get(CONF_PREPURGE_S), SECTION_ACCURACY, zero=True)
    return _strip_empty(options)


def _nozzle_form_values(options: Mapping[str, Any]) -> dict[str, Any]:
    return _strip_empty(
        {
            CONF_NOZZLE_GPH: options.get(CONF_NOZZLE_GPH),
            SECTION_ACCURACY: _strip_empty(
                {
                    key: options.get(key)
                    for key in (
                        CONF_NOMINAL_FLOW,
                        CONF_PUMP_PRESSURE,
                        CONF_TEST_PRESSURE,
                        CONF_BURNER_ENTITY,
                        CONF_PREPURGE_S,
                    )
                }
            ),
        }
    )


def _burner_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ENTITY): _entity(["sensor", "binary_sensor"]),
            vol.Optional(SECTION_ACCURACY): _accuracy({vol.Optional(CONF_POWER_ENTITY): _entity("sensor")}),
        }
    )


def _check_burner(check: _Checker, user_input: Mapping[str, Any]) -> tuple[str, InputKind, str | None] | None:
    """The input, how it is read, and a power meter beside it (the input itself if it is one)."""
    found = check.input(user_input.get(CONF_ENTITY), CONF_ENTITY)
    meter = check.power((user_input.get(SECTION_ACCURACY) or {}).get(CONF_POWER_ENTITY), SECTION_ACCURACY)
    if found is None or check.errors:
        return None
    entity_id, kind = found
    return entity_id, kind, entity_id if kind is InputKind.POWER else meter


# Form-only keys of the components step: the typical power of each kind, in W.
COMPONENT_FIELDS = {
    ComponentKind.PREHEATER: "preheater_power",
    ComponentKind.CIRCUIT_PUMP: "circuit_pump_power",
    ComponentKind.HOT_WATER_PUMP: "hot_water_pump_power",
}
CONF_BURNER_POWER = "burner_power"


def _components_schema(burner_required: bool) -> vol.Schema:
    burner = vol.Required(CONF_BURNER_POWER) if burner_required else vol.Optional(CONF_BURNER_POWER)
    fields: dict[vol.Marker, Any] = {vol.Optional(CONF_BASE_POWER): _number("W")}
    fields.update({vol.Optional(key): _number("W") for key in COMPONENT_FIELDS.values()})
    return vol.Schema({burner: _number("W"), vol.Optional(SECTION_ACCURACY): _accuracy(fields)})


_BURNER_KEYS = (
    CONF_ENTITY,
    CONF_KIND,
    CONF_POWER_ENTITY,
    CONF_NOZZLE_GPH,
    CONF_NOMINAL_FLOW,
    CONF_PUMP_PRESSURE,
    CONF_TEST_PRESSURE,
    CONF_BURNER_ENTITY,
    CONF_PREPURGE_S,
)


# --- Main entry --------------------------------------------------------------------------------------------------


class FuelLedgerConfigFlow(ConfigFlow, domain=DOMAIN):
    """The first setup, guided: name, burner, nozzle, tanks. Everything else later, in the options and the tanks."""

    VERSION = 1
    MINOR_VERSION = 1

    _name: str
    _input: tuple[str, InputKind]
    _meter: str | None = None
    _base: float | None = None
    _components: list[dict[str, Any]]
    _burner: dict[str, Any]
    _factor: float | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FuelLedgerOptionsFlow:
        return FuelLedgerOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TANK: TankSubentryFlow, SUBENTRY_COMPONENT: ComponentSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        check = _Checker(self.hass)
        if user_input is not None:
            self._name = check.name(user_input.get(CONF_NAME))
            if not check.errors:
                return await self.async_step_burner()
        schema = vol.Schema({vol.Required(CONF_NAME): TextSelector()})
        suggested = (
            user_input if user_input is not None else {CONF_NAME: (await async_texts(self.hass))[texts.HEATING_OIL]}
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=check.errors,
            last_step=False,
        )

    async def async_step_burner(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        check = _Checker(self.hass)
        if user_input is not None and (found := _check_burner(check, user_input)):
            entity_id, kind, self._meter = found
            self._input = (entity_id, kind)
            self._components = []
            if self._meter:
                return await self.async_step_components()
            return await self._after_components()
        return self.async_show_form(
            step_id="burner",
            data_schema=self.add_suggested_values_to_schema(_burner_schema(), user_input),
            errors=check.errors,
            last_step=False,
        )

    async def _after_components(self) -> ConfigFlowResult:
        if self._input[1] is InputKind.METER:
            self._burner = {}
            return await self.async_step_tanks()
        return await self.async_step_nozzle()

    async def async_step_components(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """What runs behind the power meter, each with its typical power: the burner, and if known the rest."""
        check = _Checker(self.hass)
        required = self._input[1] is InputKind.POWER
        if user_input is not None:
            more = user_input.get(SECTION_ACCURACY) or {}
            powers = {ComponentKind.BURNER: check.positive(user_input.get(CONF_BURNER_POWER), CONF_BURNER_POWER)}
            for kind, key in COMPONENT_FIELDS.items():
                powers[kind] = check.positive(more.get(key), SECTION_ACCURACY)
            self._base = check.positive(more.get(CONF_BASE_POWER), SECTION_ACCURACY, zero=True)
            if required and powers[ComponentKind.BURNER] is None and not check.errors:
                check.error(CONF_BURNER_POWER, ERROR_BURNER_REQUIRED)
            if not check.errors:
                names = await async_texts(self.hass)
                self._components = [
                    _subentry(
                        SUBENTRY_COMPONENT,
                        names[f"component_{kind}"],
                        {CONF_COMPONENT_KIND: str(kind), CONF_POWER: power},
                    )
                    for kind, power in powers.items()
                    if power is not None
                ]
                return await self._after_components()
        return self.async_show_form(
            step_id="components",
            data_schema=self.add_suggested_values_to_schema(_components_schema(required), user_input),
            errors=check.errors,
            last_step=False,
        )

    async def async_step_nozzle(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        check = _Checker(self.hass)
        kind = self._input[1]
        schema = _nozzle_schema(kind)
        # The starting factor: later it is a number entity, changed from then on.
        schema = schema.extend({vol.Optional(CONF_FACTOR): _number()})
        if user_input is not None:
            burner = _check_nozzle(check, user_input, kind)
            factor = check.positive(user_input.get(CONF_FACTOR), CONF_FACTOR)
            if not check.errors:
                self._burner, self._factor = burner, factor
                return await self.async_step_tanks()
        return self.async_show_form(
            step_id="nozzle",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=check.errors,
            last_step=False,
        )

    async def async_step_tanks(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        check = _Checker(self.hass)
        if user_input is not None:
            more = user_input.get(SECTION_ACCURACY) or {}
            count = int(check.positive(user_input.get(CONF_TANK_COUNT), CONF_TANK_COUNT, zero=True) or 0)
            capacity = check.positive(user_input.get(CONF_CAPACITY), CONF_CAPACITY)
            stock = check.positive(user_input.get(CONF_STOCK), CONF_STOCK, zero=True)
            per_cm = check.positive(more.get(CONF_PER_CM), SECTION_ACCURACY)
            residue = check.positive(more.get(CONF_RESIDUE), SECTION_ACCURACY, zero=True)
            if count > MAX_TANKS:
                check.error(CONF_TANK_COUNT, ERROR_TOO_MANY_TANKS)
            if not check.errors:
                entity_id, kind = self._input
                options = {CONF_FUEL: HEATING_OIL.key, CONF_ENTITY: entity_id, CONF_KIND: str(kind), **self._burner}
                options[CONF_LINK] = user_input.get(CONF_LINK) or str(Link.SUCTION)
                if self._meter and kind is not InputKind.POWER:
                    options[CONF_POWER_ENTITY] = self._meter
                if self._base is not None:
                    options[CONF_BASE_POWER] = self._base
                data: dict[str, Any] = {}
                if stock is not None:
                    data[CONF_INITIAL_STOCK] = stock
                if self._factor is not None:
                    data[CONF_INITIAL_FACTOR] = self._factor
                tanks = []
                if capacity is not None and count:
                    name = (await async_texts(self.hass))[texts.TANK]
                    tank = _strip_empty(
                        {
                            CONF_CAPACITY: capacity,
                            CONF_SHAPE: str(Shape.LINEAR),
                            CONF_PER_CM: per_cm,
                            CONF_RESIDUE: residue,
                        }
                    )
                    tanks = [
                        _subentry(SUBENTRY_TANK, name if count == 1 else f"{name} {i}", tank)
                        for i in range(1, count + 1)
                    ]
                return self.async_create_entry(
                    title=self._name, data=data, options=options, subentries=[*tanks, *self._components]
                )
        schema = vol.Schema(
            {
                vol.Optional(CONF_TANK_COUNT, default=1): _number(),
                vol.Optional(CONF_CAPACITY): _number("L"),
                vol.Optional(CONF_LINK, default=str(Link.SUCTION)): _select(tuple(Link), "link"),
                vol.Optional(CONF_STOCK): _number("L"),
                vol.Optional(SECTION_ACCURACY): _accuracy(
                    {vol.Optional(CONF_PER_CM): _number("L/cm"), vol.Optional(CONF_RESIDUE): _number("L")}
                ),
            }
        )
        return self.async_show_form(
            step_id="tanks",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=check.errors,
            last_step=True,
        )


class FuelLedgerOptionsFlow(OptionsFlow):
    """The burner, the fuel and the stock. Saving reloads the entry; the ledger continues with the new values."""

    _input: tuple[str, InputKind]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = [STEP_BURNER, STEP_FUEL, STEP_STOCK]
        entry = self.config_entry.options
        if entry.get(CONF_POWER_ENTITY) or entry.get(CONF_KIND) == InputKind.POWER:
            options.insert(1, STEP_POWER)
        return self.async_show_menu(step_id="init", menu_options=options)

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """What the heating draws all the time; the components are entries of their own."""
        check = _Checker(self.hass)
        if user_input is not None:
            base = check.positive(user_input.get(CONF_BASE_POWER), CONF_BASE_POWER, zero=True)
            if not check.errors:
                return self._save({CONF_BASE_POWER: base}, (CONF_BASE_POWER,))
        schema = vol.Schema({vol.Optional(CONF_BASE_POWER): _number("W")})
        suggested = (
            user_input if user_input is not None else {CONF_BASE_POWER: self.config_entry.options.get(CONF_BASE_POWER)}
        )
        return self.async_show_form(
            step_id=STEP_POWER,
            data_schema=self.add_suggested_values_to_schema(schema, _strip_empty(suggested)),
            errors=check.errors,
        )

    def _save(self, changes: Mapping[str, Any], keys: tuple[str, ...]) -> ConfigFlowResult:
        options = {k: v for k, v in self.config_entry.options.items() if k not in keys}
        options.update(_strip_empty(changes))
        return self.async_create_entry(data=options)

    async def async_step_burner(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        check = _Checker(self.hass)
        if user_input is not None and (found := _check_burner(check, user_input)):
            entity_id, kind, meter = found
            if kind is InputKind.POWER and not self._has_burner_component():
                check.error(CONF_ENTITY, ERROR_BURNER_REQUIRED)
            else:
                self._input = (entity_id, kind)
                self._meter = meter if kind is not InputKind.POWER else None
                if kind is InputKind.METER:
                    return self._save(self._input_options(), _BURNER_KEYS)
                return await self.async_step_nozzle()
        stored = self.config_entry.options
        suggested = (
            user_input
            if user_input is not None
            else _strip_empty(
                {
                    CONF_ENTITY: stored.get(CONF_ENTITY),
                    SECTION_ACCURACY: _strip_empty({CONF_POWER_ENTITY: stored.get(CONF_POWER_ENTITY)}),
                }
            )
        )
        return self.async_show_form(
            step_id=STEP_BURNER,
            data_schema=self.add_suggested_values_to_schema(_burner_schema(), suggested),
            errors=check.errors,
            last_step=False,
        )

    _meter: str | None = None

    def _has_burner_component(self) -> bool:
        return any(
            s.subentry_type == SUBENTRY_COMPONENT and s.data.get(CONF_COMPONENT_KIND) == ComponentKind.BURNER
            for s in self.config_entry.subentries.values()
        )

    def _input_options(self) -> dict[str, Any]:
        entity_id, kind = self._input
        return {CONF_ENTITY: entity_id, CONF_KIND: str(kind), CONF_POWER_ENTITY: self._meter}

    async def async_step_nozzle(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        check = _Checker(self.hass)
        kind = self._input[1]
        if user_input is not None:
            burner = _check_nozzle(check, user_input, kind)
            if not check.errors:
                return self._save({**self._input_options(), **burner}, _BURNER_KEYS)
        suggested = user_input if user_input is not None else _nozzle_form_values(self.config_entry.options)
        return self.async_show_form(
            step_id="nozzle",
            data_schema=self.add_suggested_values_to_schema(_nozzle_schema(kind), suggested),
            errors=check.errors,
        )

    async def async_step_fuel(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        check = _Checker(self.hass)
        keys = (CONF_EFFICIENCY, CONF_HEATING_VALUE, CONF_CO2)
        if user_input is not None:
            efficiency = check.positive(user_input.get(CONF_EFFICIENCY), CONF_EFFICIENCY)
            if efficiency is not None and efficiency > 1.2:
                check.error(CONF_EFFICIENCY, ERROR_EFFICIENCY)
            values = {
                CONF_EFFICIENCY: efficiency,
                CONF_HEATING_VALUE: check.positive(user_input.get(CONF_HEATING_VALUE), CONF_HEATING_VALUE),
                CONF_CO2: check.positive(user_input.get(CONF_CO2), CONF_CO2),
            }
            if not check.errors:
                return self._save(values, keys)
        schema = vol.Schema(
            {
                vol.Optional(CONF_EFFICIENCY): _number(),
                vol.Optional(CONF_HEATING_VALUE): _number("kWh/L"),
                vol.Optional(CONF_CO2): _number("kg/L"),
            }
        )
        suggested = user_input if user_input is not None else {k: self.config_entry.options.get(k) for k in keys}
        return self.async_show_form(
            step_id=STEP_FUEL,
            data_schema=self.add_suggested_values_to_schema(schema, _strip_empty(suggested)),
            errors=check.errors,
        )

    async def async_step_stock(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        check = _Checker(self.hass)
        keys = (CONF_LOW_PERCENT, CONF_RANGE_DAYS, CONF_READING_ACCURACY)
        if user_input is not None:
            values: dict[str, Any] = {key: check.positive(user_input.get(key), key) for key in keys}
            values[CONF_LINK] = user_input.get(CONF_LINK) or str(Link.SUCTION)
            if not check.errors:
                return self._save(values, (*keys, CONF_LINK))
        schema = vol.Schema(
            {
                vol.Optional(CONF_LINK, default=str(Link.SUCTION)): _select(tuple(Link), "link"),
                vol.Optional(CONF_LOW_PERCENT, default=DEFAULT_LOW_PERCENT): _number("%"),
                vol.Optional(CONF_RANGE_DAYS, default=DEFAULT_RANGE_DAYS): _number("d"),
                vol.Optional(CONF_READING_ACCURACY, default=DEFAULT_READING_ACCURACY_CM): _number("cm"),
            }
        )
        suggested = (
            user_input if user_input is not None else {k: self.config_entry.options.get(k) for k in (*keys, CONF_LINK)}
        )
        return self.async_show_form(
            step_id=STEP_STOCK,
            data_schema=self.add_suggested_values_to_schema(schema, _strip_empty(suggested)),
            errors=check.errors,
        )


# --- Tanks -------------------------------------------------------------------------------------------------------


class TankSubentryFlow(ConfigSubentryFlow):
    """A tank: capacity and shape, with what makes it more accurate: dimensions, offset, residue, a level sensor.

    A shape other than upright walls asks for its dimensions in a second step.
    """

    _title: str
    _data: dict[str, Any]
    _level: str | None = None

    @property
    def _reconfiguring(self) -> bool:
        return self.source == SOURCE_RECONFIGURE

    def _stored(self) -> Mapping[str, Any]:
        return self._get_reconfigure_subentry().data if self._reconfiguring else {}

    def _finish(self, data: dict[str, Any]) -> SubentryFlowResult:
        if self._reconfiguring:
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), title=self._title, data=data
            )
        return self.async_create_entry(title=self._title, data=data)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_tank(user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_tank(user_input)

    async def async_step_tank(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        check = _Checker(self.hass)
        if user_input is not None:
            more = user_input.get(SECTION_ACCURACY) or {}
            self._title = check.name(user_input.get(CONF_NAME))
            shape = Shape(user_input.get(CONF_SHAPE) or Shape.LINEAR)
            per_cm = check.positive(more.get(CONF_PER_CM), SECTION_ACCURACY)
            data = {
                CONF_CAPACITY: check.positive(user_input.get(CONF_CAPACITY), CONF_CAPACITY),
                CONF_SHAPE: str(shape),
                CONF_PER_CM: per_cm if shape is Shape.LINEAR else None,
                CONF_OFFSET: check.positive(more.get(CONF_OFFSET), SECTION_ACCURACY, zero=True),
                CONF_RESIDUE: check.positive(more.get(CONF_RESIDUE), SECTION_ACCURACY, zero=True),
            }
            # Heights can be converted if the shape gets its dimensions: linear here, the others in the next step.
            converts = shape is not Shape.LINEAR or per_cm is not None
            self._level = check.level(more.get(CONF_LEVEL_ENTITY), SECTION_ACCURACY, converts)
            if not check.errors:
                self._data = _strip_empty(data)
                if shape is Shape.HORIZONTAL_CYLINDER:
                    return await self.async_step_cylinder()
                if shape is Shape.TABLE:
                    return await self.async_step_table()
                return self._finish(self._with_level(self._data))

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_CAPACITY): _number("L"),
                vol.Required(CONF_SHAPE, default=str(Shape.LINEAR)): _select(tuple(Shape), "shape"),
                vol.Optional(SECTION_ACCURACY): _accuracy(
                    {
                        vol.Optional(CONF_PER_CM): _number("L/cm"),
                        vol.Optional(CONF_OFFSET): _number("cm"),
                        vol.Optional(CONF_RESIDUE): _number("L"),
                        vol.Optional(CONF_LEVEL_ENTITY): _entity("sensor"),
                    }
                ),
            }
        )
        if user_input is None and self._reconfiguring:
            stored = self._stored()
            user_input = _strip_empty(
                {
                    CONF_NAME: self._get_reconfigure_subentry().title,
                    CONF_CAPACITY: stored.get(CONF_CAPACITY),
                    CONF_SHAPE: stored.get(CONF_SHAPE),
                    SECTION_ACCURACY: _strip_empty(
                        {k: stored.get(k) for k in (CONF_PER_CM, CONF_OFFSET, CONF_RESIDUE, CONF_LEVEL_ENTITY)}
                    ),
                }
            )
        return self.async_show_form(
            step_id="tank",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=check.errors,
        )

    def _with_level(self, data: dict[str, Any]) -> dict[str, Any]:
        return {**data, CONF_LEVEL_ENTITY: self._level} if self._level else data

    async def async_step_cylinder(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        check = _Checker(self.hass)
        if user_input is not None:
            diameter = check.positive(user_input.get(CONF_DIAMETER), CONF_DIAMETER)
            length = check.positive(user_input.get(CONF_LENGTH), CONF_LENGTH)
            if not check.errors:
                return self._finish(self._with_level({**self._data, CONF_DIAMETER: diameter, CONF_LENGTH: length}))
        schema = vol.Schema({vol.Required(CONF_DIAMETER): _number("cm"), vol.Required(CONF_LENGTH): _number("cm")})
        stored = self._stored()
        suggested = (
            user_input
            if user_input is not None
            else _strip_empty({k: stored.get(k) for k in (CONF_DIAMETER, CONF_LENGTH)})
        )
        return self.async_show_form(
            step_id="cylinder",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=check.errors,
        )

    async def async_step_table(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        check = _Checker(self.hass)
        if user_input is not None:
            try:
                table = parse_table(user_input.get(CONF_TABLE) or "")
            except ValueError:
                check.error(CONF_TABLE, ERROR_INVALID_TABLE)
            else:
                return self._finish(self._with_level({**self._data, CONF_TABLE: [list(p) for p in table]}))
        schema = vol.Schema({vol.Required(CONF_TABLE): TextSelector(TextSelectorConfig(multiline=True))})
        stored = self._stored().get(CONF_TABLE)
        suggested = (
            user_input
            if user_input is not None
            else ({CONF_TABLE: format_table(tuple((float(a), float(b)) for a, b in stored))} if stored else {})
        )
        return self.async_show_form(
            step_id="table",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=check.errors,
        )


# --- Components behind the power meter ---------------------------------------------------------------------------


class ComponentSubentryFlow(ConfigSubentryFlow):
    """A component behind the power meter: what it is, its typical power, and how long a change has to last."""

    @property
    def _reconfiguring(self) -> bool:
        return self.source == SOURCE_RECONFIGURE

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_component(user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self.async_step_component(user_input)

    async def async_step_component(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        check = _Checker(self.hass)
        if user_input is not None:
            more = user_input.get(SECTION_ACCURACY) or {}
            title = check.name(user_input.get(CONF_NAME))
            data = _strip_empty(
                {
                    CONF_COMPONENT_KIND: user_input.get(CONF_COMPONENT_KIND) or str(ComponentKind.OTHER),
                    CONF_POWER: check.positive(user_input.get(CONF_POWER), CONF_POWER),
                    CONF_ON_DELAY: check.positive(more.get(CONF_ON_DELAY), SECTION_ACCURACY, zero=True),
                    CONF_OFF_DELAY: check.positive(more.get(CONF_OFF_DELAY), SECTION_ACCURACY, zero=True),
                }
            )
            if not check.errors:
                if self._reconfiguring:
                    return self.async_update_and_abort(
                        self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data
                    )
                return self.async_create_entry(title=title, data=data)
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_COMPONENT_KIND, default=str(ComponentKind.CIRCUIT_PUMP)): _select(
                    tuple(ComponentKind), "component_kind"
                ),
                vol.Required(CONF_POWER): _number("W"),
                vol.Optional(SECTION_ACCURACY): _accuracy(
                    {vol.Optional(CONF_ON_DELAY): _number("s"), vol.Optional(CONF_OFF_DELAY): _number("s")}
                ),
            }
        )
        if user_input is None and self._reconfiguring:
            subentry = self._get_reconfigure_subentry()
            stored = subentry.data
            user_input = _strip_empty(
                {
                    CONF_NAME: subentry.title,
                    CONF_COMPONENT_KIND: stored.get(CONF_COMPONENT_KIND),
                    CONF_POWER: stored.get(CONF_POWER),
                    SECTION_ACCURACY: _strip_empty({k: stored.get(k) for k in (CONF_ON_DELAY, CONF_OFF_DELAY)}),
                }
            )
        return self.async_show_form(
            step_id="component",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=check.errors,
        )
