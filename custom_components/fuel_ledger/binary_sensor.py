"""Low stock, and whether each component behind the power meter runs."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FuelLedgerConfigEntry
from .const import CONF_COMPONENT_KIND, KEY_LOW, KEY_RUNNING, SUBENTRY_COMPONENT
from .engine import ComponentKind
from .entity import FuelLedgerEntity, component_device, main_device
from .runtime import FuelLedgerRuntime
from .texts import async_texts


async def async_setup_entry(
    hass: HomeAssistant, entry: FuelLedgerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    models = await async_texts(hass)
    if runtime.spec.capacity:  # without tanks there is no capacity to compare with
        async_add_entities([LowStockSensor(runtime, entry.entry_id, KEY_LOW, main_device(entry, models))])
    if runtime.power is None:
        return
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_COMPONENT:
            async_add_entities(
                [
                    ComponentRunningSensor(
                        runtime, subentry.subentry_id, component_device(subentry, models), subentry.data
                    )
                ],
                config_subentry_id=subentry.subentry_id,
            )


class LowStockSensor(FuelLedgerEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        return self.runtime.ledger.low

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"threshold_percent": self.runtime.spec.low_percent}


class ComponentRunningSensor(FuelLedgerEntity, BinarySensorEntity):
    """On while the component runs, as recognised in the power. Named after its device: the component itself."""

    _attr_name = None

    def __init__(self, runtime: FuelLedgerRuntime, component_id: str, device: Any, data: Any) -> None:
        super().__init__(runtime, component_id, KEY_RUNNING, device)
        self._component_id = component_id
        kind = ComponentKind(data.get(CONF_COMPONENT_KIND, ComponentKind.OTHER))
        self._attr_device_class = BinarySensorDeviceClass.RUNNING
        self._attr_translation_key = f"running_{kind.value}"  # only for the icon; the name is the device's

    @property
    def is_on(self) -> bool | None:
        return self.runtime.component_running(self._component_id)
