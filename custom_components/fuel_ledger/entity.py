"""The devices of an entry and the base of its entities, updated by the runtime."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from . import texts
from .const import CONF_COMPONENT_KIND, DOMAIN
from .runtime import FuelLedgerRuntime

# Shown below the model wherever Home Assistant lists devices. Device registry fields are not translated, so the
# model comes from the translations when the device is set up (texts.py).
MANUFACTURER = "Fuel Ledger"


def main_device(entry: ConfigEntry, models: dict[str, str]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        model=models[texts.HEATING_OIL],
        manufacturer=MANUFACTURER,
        entry_type=DeviceEntryType.SERVICE,
    )


def tank_device(entry: ConfigEntry, subentry: ConfigSubentry, models: dict[str, str]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, subentry.subentry_id)},
        name=subentry.title,
        model=models[texts.TANK],
        manufacturer=MANUFACTURER,
        entry_type=DeviceEntryType.SERVICE,
    )


class FuelLedgerEntity(Entity):
    """Written by the runtime after every interval and every event."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _follows_power = False  # also written after every measurement of the power meter

    def __init__(self, runtime: FuelLedgerRuntime, owner_id: str, key: str, device: DeviceInfo) -> None:
        self.runtime = runtime
        self._attr_unique_id = f"{owner_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = device

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.async_add_listener(self.async_write_ha_state, power=self._follows_power))


def component_device(subentry: ConfigSubentry, models: dict[str, str]) -> DeviceInfo:
    """A component behind the power meter: the burner, a pump. Its model is its kind."""
    kind = subentry.data.get(CONF_COMPONENT_KIND, "other")
    return DeviceInfo(
        identifiers={(DOMAIN, subentry.subentry_id)},
        name=subentry.title,
        model=models.get(f"component_{kind}", kind),
        manufacturer=MANUFACTURER,
        entry_type=DeviceEntryType.SERVICE,
    )
