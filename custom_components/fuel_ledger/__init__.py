"""Fuel Ledger: keeps the books for a heating fuel (stock, deliveries, consumption, energy, heat, cost, CO₂)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_AMOUNT,
    ATTR_CO2,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DEVICE_ID,
    ATTR_ENERGY,
    ATTR_HEATING_VALUE,
    ATTR_HEIGHT,
    ATTR_LEVEL_AFTER,
    ATTR_POINT,
    ATTR_PRICE,
    ATTR_PRODUCT,
    ATTR_SUPPLIER,
    ATTR_TIME,
    ATTR_TOTAL_PRICE,
    ATTR_VOLUME,
    DOMAIN,
    SERVICE_RECORD_DELIVERY,
    SERVICE_RECORD_LEVEL,
    SERVICE_SET_STOCK,
    STORAGE_VERSION,
)
from .engine import LedgerError, LedgerSpec
from .engine.power import alike
from .model import NoBurnerError, build_spec
from .runtime import FuelLedgerRuntime, store_key

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type FuelLedgerConfigEntry = ConfigEntry[FuelLedgerRuntime]

_POSITIVE = vol.All(vol.Coerce(float), vol.Range(min=0))
_TEXT = vol.All(cv.string, vol.Length(max=200))

DELIVERY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_AMOUNT): _POSITIVE,
        vol.Optional(ATTR_LEVEL_AFTER): _POSITIVE,
        vol.Optional(ATTR_TOTAL_PRICE): _POSITIVE,
        vol.Optional(ATTR_ENERGY): _POSITIVE,
        vol.Optional(ATTR_CO2): _POSITIVE,
        vol.Optional(ATTR_PRODUCT): _TEXT,
        vol.Optional(ATTR_SUPPLIER): _TEXT,
        vol.Optional(ATTR_TIME): cv.datetime,
    }
)
LEVEL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_POINT): _TEXT,
        vol.Optional(ATTR_HEIGHT): _POSITIVE,
        vol.Optional(ATTR_VOLUME): _POSITIVE,
        vol.Optional(ATTR_TIME): cv.datetime,
    }
)
STOCK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_VOLUME): _POSITIVE,
        vol.Optional(ATTR_PRICE): _POSITIVE,
        vol.Optional(ATTR_HEATING_VALUE): _POSITIVE,
        vol.Optional(ATTR_CO2): _POSITIVE,
        vol.Optional(ATTR_TIME): cv.datetime,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def record_delivery(call: ServiceCall) -> ServiceResponse:
        runtime = _runtime(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        ts = _time(runtime, call.data.get(ATTR_TIME))
        record = _book(
            lambda: runtime.ledger.record_delivery(
                ts,
                amount=call.data.get(ATTR_AMOUNT),
                level_after=call.data.get(ATTR_LEVEL_AFTER),
                total_price=call.data.get(ATTR_TOTAL_PRICE),
                energy=call.data.get(ATTR_ENERGY),
                co2=call.data.get(ATTR_CO2),
                product=call.data.get(ATTR_PRODUCT),
                supplier=call.data.get(ATTR_SUPPLIER),
            )
        )
        await runtime.async_changed()
        return {
            "amount": record["amount"],
            "rest": record["rest"],
            "level_after": record["level_after"],
            "stock": runtime.ledger.stock,
            **{f"{key}_after": value for key, value in record["after"].items()},
        }

    async def record_level(call: ServiceCall) -> ServiceResponse:
        runtime, tank_id = _tank(hass, call.data[ATTR_DEVICE_ID])
        ts = _time(runtime, call.data.get(ATTR_TIME))
        record = _book(
            lambda: runtime.ledger.record_level(
                ts,
                tank_id,
                call.data[ATTR_POINT],
                height_cm=call.data.get(ATTR_HEIGHT),
                volume=call.data.get(ATTR_VOLUME),
            )
        )
        await runtime.async_changed()
        measured = runtime.ledger.measured_factor()
        return {
            "volume": record["volume"],
            "calculated": record["calculated"],  # what the tank held by the books at that moment
            "measured_factor": measured.value if measured else None,
            "uncertainty": measured.uncertainty if measured else None,
        }

    async def set_stock(call: ServiceCall) -> ServiceResponse:
        runtime = _runtime(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        ts = _time(runtime, call.data.get(ATTR_TIME))
        record = _book(
            lambda: runtime.ledger.set_stock(
                ts,
                call.data[ATTR_VOLUME],
                price=call.data.get(ATTR_PRICE),
                heating_value=call.data.get(ATTR_HEATING_VALUE),
                co2=call.data.get(ATTR_CO2),
            )
        )
        await runtime.async_changed()
        return {"previous": record["previous"], "stock": runtime.ledger.stock}

    for name, handler, schema in (
        (SERVICE_RECORD_DELIVERY, record_delivery, DELIVERY_SCHEMA),
        (SERVICE_RECORD_LEVEL, record_level, LEVEL_SCHEMA),
        (SERVICE_SET_STOCK, set_stock, STOCK_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL)
    return True


def _runtime(hass: HomeAssistant, entry_id: str) -> FuelLedgerRuntime:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_found")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
    return entry.runtime_data


def _tank(hass: HomeAssistant, device_id: str) -> tuple[FuelLedgerRuntime, str]:
    """The ledger and the tank of a tank's device."""
    device = dr.async_get(hass).async_get(device_id)
    entry = hass.config_entries.async_get_entry(device.config_entry_id) if device is not None else None
    if device is not None and entry is not None and entry.domain == DOMAIN:
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier in entry.subentries:
                return _runtime(hass, entry.entry_id), identifier
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_a_tank")


def _time(runtime: FuelLedgerRuntime, moment: datetime | None) -> float:
    """A moment of an action as a timestamp; without a time zone it is local time. Left out: now.

    The ledger is brought up to now first, so an event of now is not in its future.
    """
    now = runtime.now()
    runtime.ledger.settle(now)
    if moment is None:
        return now
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_util.get_default_time_zone())
    return min(moment.timestamp(), now)


def _book(event: Any) -> dict[str, Any]:
    try:
        return event()
    except LedgerError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key=err.key, translation_placeholders=err.placeholders
        ) from err


async def async_setup_entry(hass: HomeAssistant, entry: FuelLedgerConfigEntry) -> bool:
    try:
        spec = build_spec(entry.options, entry.subentries.values())
    except NoBurnerError as err:
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="no_burner") from err
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigEntryError(f"Invalid configuration: {err}") from err
    _check_components(hass, entry, spec)

    runtime = FuelLedgerRuntime(hass, entry, spec)
    await runtime.async_start()
    entry.runtime_data = runtime
    entry.async_on_unload(runtime.cancel)
    # Options and subentries define the spec: any change rebuilds it. The state is saved on unload.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FuelLedgerConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: FuelLedgerConfigEntry) -> None:
    await Store(hass, STORAGE_VERSION, store_key(entry.entry_id)).async_remove()
    ir.async_delete_issue(hass, DOMAIN, _alike_issue(entry.entry_id))


def _alike_issue(entry_id: str) -> str:
    return f"components_alike_{entry_id}"


def _check_components(hass: HomeAssistant, entry: FuelLedgerConfigEntry, spec: LedgerSpec) -> None:
    """A repair note while two components behind the power meter draw so alike that it cannot tell them apart."""
    pairs = alike(spec.power) if spec.power else []
    if not pairs:
        ir.async_delete_issue(hass, DOMAIN, _alike_issue(entry.entry_id))
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        _alike_issue(entry.entry_id),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="components_alike",
        translation_placeholders={
            "entry": entry.title,
            "pairs": ", ".join(f"{a.name} ({a.power:g} W) / {b.name} ({b.power:g} W)" for a, b in pairs),
        },
    )


async def _async_reload(hass: HomeAssistant, entry: FuelLedgerConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
