"""Take over the factor measured from dipstick readings: a suggestion, applied by a click, from now on."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FuelLedgerConfigEntry
from .const import DOMAIN, KEY_APPLY_FACTOR
from .engine import InputKind, Origin
from .entity import FuelLedgerEntity, main_device
from .texts import async_texts


async def async_setup_entry(
    hass: HomeAssistant, entry: FuelLedgerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if runtime.spec.burner.kind is InputKind.METER:
        return
    device = main_device(entry, await async_texts(hass))
    async_add_entities([ApplyFactorButton(runtime, entry.entry_id, KEY_APPLY_FACTOR, device)])


class ApplyFactorButton(FuelLedgerEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def available(self) -> bool:
        return self.runtime.ledger.measured_factor() is not None

    async def async_press(self) -> None:
        measured = self.runtime.ledger.measured_factor()
        if measured is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_measured_factor")
        self.runtime.ledger.set_factor(self.runtime.now(), round(measured.value, 3), Origin.MEASURED)
        await self.runtime.async_changed()
