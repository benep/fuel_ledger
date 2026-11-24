"""The correction factor of the nozzle: a change counts from now on, what was booked stays."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FuelLedgerConfigEntry
from .const import ATTR_ORIGIN, KEY_FACTOR
from .engine import InputKind, Origin
from .entity import FuelLedgerEntity, main_device
from .texts import async_texts


async def async_setup_entry(
    hass: HomeAssistant, entry: FuelLedgerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.spec.burner.kind is InputKind.METER:
        return  # a meter measures: there is nothing to correct
    device = main_device(entry, await async_texts(hass))
    async_add_entities([FactorNumber(runtime, entry.entry_id, KEY_FACTOR, device)])


class FactorNumber(FuelLedgerEntity, NumberEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.3
    _attr_native_max_value = 3.0
    _attr_native_step = 0.001

    @property
    def native_value(self) -> float:
        return self.runtime.ledger.factor

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_ORIGIN: str(self.runtime.ledger.factor_origin)}

    async def async_set_native_value(self, value: float) -> None:
        if value == self.runtime.ledger.factor:
            return
        self.runtime.ledger.set_factor(self.runtime.now(), value, Origin.SET)
        await self.runtime.async_changed()
