"""Counters for the Energy dashboard, the stock and its range, prices and the values of the fuel in the tanks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfMass,
    UnitOfPower,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import FuelLedgerConfigEntry
from .const import (
    ATTR_BASIS,
    ATTR_LEVEL,
    ATTR_ORIGIN,
    ATTR_UNCERTAINTY,
    KEY_CO2,
    KEY_CO2_FACTOR,
    KEY_COMPONENT_POWER,
    KEY_CONSUMPTION,
    KEY_COST,
    KEY_EMPTY,
    KEY_ENERGY,
    KEY_FILL,
    KEY_FLOW,
    KEY_HEAT,
    KEY_HEATING_VALUE,
    KEY_LAST_DELIVERY,
    KEY_MEASURED_FACTOR,
    KEY_PRICE,
    KEY_PRICE_ENERGY,
    KEY_RANGE,
    KEY_RUNTIME,
    KEY_STOCK,
    KEY_TANK_CONTENT,
    KEY_TANK_LEVEL,
    KEY_TANK_READING,
    SUBENTRY_COMPONENT,
    SUBENTRY_TANK,
)
from .engine import InputKind, Ledger, LedgerSpec
from .entity import FuelLedgerEntity, component_device, main_device, tank_device
from .runtime import FuelLedgerRuntime
from .texts import async_texts

Value = float | datetime | None


@dataclass(frozen=True, kw_only=True)
class FuelSensorDescription(SensorEntityDescription):
    value: Callable[[FuelLedgerRuntime], Value]
    attributes: Callable[[Ledger], dict[str, Any]] | None = None
    exists: Callable[[LedgerSpec], bool] = lambda spec: True
    unit: Callable[[str], str] | None = None  # from the currency, for prices and costs


def _level(level: Any) -> dict[str, Any]:
    return {ATTR_LEVEL: None if level is None else str(level)}


def _empty(runtime: FuelLedgerRuntime) -> datetime | None:
    now = runtime.now()
    days = runtime.ledger.range_days(now)
    return None if days is None else dt_util.utc_from_timestamp(now) + timedelta(days=days)


def _last_delivery(runtime: FuelLedgerRuntime) -> datetime | None:
    deliveries = runtime.ledger.deliveries
    return dt_util.utc_from_timestamp(deliveries[-1]["time"]) if deliveries else None


def _delivery_attributes(ledger: Ledger) -> dict[str, Any]:
    if not ledger.deliveries:
        return {}
    last = ledger.deliveries[-1]
    keys = ("amount", "rest", "level_after", "total_price", "energy", "co2", "product", "supplier")
    return {key: last.get(key) for key in keys}


def _measured(runtime: FuelLedgerRuntime) -> float | None:
    measured = runtime.ledger.measured_factor()
    return None if measured is None else measured.value


def _measured_attributes(ledger: Ledger) -> dict[str, Any]:
    measured = ledger.measured_factor()
    if measured is None:
        return {}
    return {
        ATTR_UNCERTAINTY: round(measured.uncertainty, 4),
        "start": dt_util.utc_from_timestamp(measured.start).isoformat(),
        "end": dt_util.utc_from_timestamp(measured.end).isoformat(),
        "litres_at_factor_1": round(measured.nominal, 1),
        "litres_measured": round(measured.measured, 1),
    }


def _counter(key: str, value: Callable[[Ledger], float], level: str, **kwargs: Any) -> FuelSensorDescription:
    return FuelSensorDescription(
        key=key,
        translation_key=key,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda r: value(r.ledger),
        attributes=lambda ledger: {**_level(getattr(ledger, level)), ATTR_BASIS: ledger.basis()},
        **kwargs,
    )


SENSORS: tuple[FuelSensorDescription, ...] = (
    _counter(
        KEY_CONSUMPTION,
        lambda ledger: ledger.consumption,
        "consumption_level",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=2,
    ),
    _counter(
        KEY_ENERGY,
        lambda ledger: ledger.energy,
        "energy_level",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    _counter(
        KEY_HEAT,
        lambda ledger: ledger.heat,
        "heat_level",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    _counter(
        KEY_CO2,
        lambda ledger: ledger.co2,
        "co2_level",
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=1,
    ),
    FuelSensorDescription(
        key=KEY_COST,
        translation_key=KEY_COST,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value=lambda r: r.ledger.cost,
        attributes=lambda ledger: _level(ledger.cost_level),
        unit=lambda currency: currency,
    ),
    FuelSensorDescription(
        key=KEY_RUNTIME,
        translation_key=KEY_RUNTIME,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=2,
        value=lambda r: r.ledger.runtime_h,
        exists=lambda spec: spec.burner.kind.counts_itself,
    ),
    FuelSensorDescription(
        key=KEY_FLOW,
        translation_key=KEY_FLOW,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_HOUR,
        suggested_display_precision=2,
        value=lambda r: r.ledger.flow,
        exists=lambda spec: spec.burner.kind is not InputKind.METER and spec.knows_burner_state,
    ),
    FuelSensorDescription(
        key=KEY_STOCK,
        translation_key=KEY_STOCK,
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_display_precision=0,
        value=lambda r: r.ledger.stock,
        attributes=lambda ledger: _level(ledger.stock_level),
    ),
    FuelSensorDescription(
        key=KEY_FILL,
        translation_key=KEY_FILL,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value=lambda r: r.ledger.fill_percent,
        attributes=lambda ledger: _level(ledger.stock_level),
        exists=lambda spec: bool(spec.capacity),
    ),
    FuelSensorDescription(
        key=KEY_RANGE,
        translation_key=KEY_RANGE,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.DAYS,
        suggested_display_precision=0,
        value=lambda r: r.ledger.range_days(r.now()),
        attributes=lambda ledger: _level(ledger.range_level(ledger.time or 0.0)),
    ),
    FuelSensorDescription(
        key=KEY_EMPTY,
        translation_key=KEY_EMPTY,
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_empty,
        attributes=lambda ledger: _level(ledger.range_level(ledger.time or 0.0)),
    ),
    FuelSensorDescription(
        key=KEY_PRICE,
        translation_key=KEY_PRICE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value=lambda r: r.ledger.price,
        attributes=lambda ledger: {ATTR_ORIGIN: str(ledger.price_origin)},
        unit=lambda currency: f"{currency}/{UnitOfVolume.LITERS}",
    ),
    FuelSensorDescription(
        key=KEY_PRICE_ENERGY,
        translation_key=KEY_PRICE_ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        value=lambda r: r.ledger.price_per_kwh,
        # The Energy dashboard checks the unit of a price entity: currency per kWh, exactly.
        unit=lambda currency: f"{currency}/{UnitOfEnergy.KILO_WATT_HOUR}",
    ),
    FuelSensorDescription(
        key=KEY_HEATING_VALUE,
        translation_key=KEY_HEATING_VALUE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=f"{UnitOfEnergy.KILO_WATT_HOUR}/{UnitOfVolume.LITERS}",
        suggested_display_precision=3,
        value=lambda r: r.ledger.current_heating_value,
        attributes=lambda ledger: {ATTR_ORIGIN: ledger.basis()["heating_value"]},
    ),
    FuelSensorDescription(
        key=KEY_CO2_FACTOR,
        translation_key=KEY_CO2_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=f"{UnitOfMass.KILOGRAMS}/{UnitOfVolume.LITERS}",
        suggested_display_precision=3,
        value=lambda r: r.ledger.current_co2,
        attributes=lambda ledger: {ATTR_ORIGIN: str(ledger.co2_origin)},
    ),
    FuelSensorDescription(
        key=KEY_MEASURED_FACTOR,
        translation_key=KEY_MEASURED_FACTOR,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=3,
        value=_measured,
        attributes=_measured_attributes,
        exists=lambda spec: spec.burner.kind is not InputKind.METER,
    ),
    FuelSensorDescription(
        key=KEY_LAST_DELIVERY,
        translation_key=KEY_LAST_DELIVERY,
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_last_delivery,
        attributes=_delivery_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: FuelLedgerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    models = await async_texts(hass)
    device = main_device(entry, models)
    currency = hass.config.currency
    async_add_entities(
        FuelSensor(runtime, entry.entry_id, description, device, currency)
        for description in SENSORS
        if description.exists(runtime.spec)
    )
    for subentry in entry.subentries.values():
        entities: list[SensorEntity] = []
        if subentry.subentry_type == SUBENTRY_TANK:
            tank = tank_device(entry, subentry, models)
            entities = [
                TankContentSensor(runtime, subentry.subentry_id, tank),
                TankReadingSensor(runtime, subentry.subentry_id, tank),
            ]
            spec = runtime.spec.tank(subentry.subentry_id)
            if spec is not None and spec.converts_height:
                entities.append(TankLevelSensor(runtime, subentry.subentry_id, tank))
        elif subentry.subentry_type == SUBENTRY_COMPONENT and runtime.power is not None:
            entities = [ComponentPowerSensor(runtime, subentry.subentry_id, component_device(subentry, models))]
        if entities:
            async_add_entities(entities, config_subentry_id=subentry.subentry_id)


class FuelSensor(FuelLedgerEntity, SensorEntity):
    entity_description: FuelSensorDescription

    def __init__(
        self,
        runtime: FuelLedgerRuntime,
        owner_id: str,
        description: FuelSensorDescription,
        device: Any,
        currency: str,
    ) -> None:
        super().__init__(runtime, owner_id, description.key, device)
        self.entity_description = description
        if description.unit is not None:
            self._attr_native_unit_of_measurement = description.unit(currency)

    @property
    def native_value(self) -> Value:
        return self.entity_description.value(self.runtime)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attributes = self.entity_description.attributes
        return attributes(self.runtime.ledger) if attributes else None


class TankReadingSensor(FuelLedgerEntity, SensorEntity):
    """The last dipstick reading of a tank, in litres, with its height, point and time."""

    _attr_device_class = SensorDeviceClass.VOLUME_STORAGE
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_suggested_display_precision = 0

    def __init__(self, runtime: FuelLedgerRuntime, tank_id: str, device: Any) -> None:
        super().__init__(runtime, tank_id, KEY_TANK_READING, device)
        self._tank_id = tank_id

    def _last(self) -> dict[str, Any] | None:
        return next((r for r in reversed(self.runtime.ledger.readings) if r["tank"] == self._tank_id), None)

    @property
    def native_value(self) -> float | None:
        last = self._last()
        return None if last is None else last["volume"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._last()
        if last is None:
            return {}
        return {
            "height_cm": last["height_cm"],
            "point": last["point"],
            "time": dt_util.utc_from_timestamp(last["time"]).isoformat(),
        }


class TankContentSensor(FuelLedgerEntity, SensorEntity):
    """Litres in a tank now: measured by its level sensor, else from its last reading minus what the burner drew."""

    _attr_device_class = SensorDeviceClass.VOLUME_STORAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_suggested_display_precision = 0

    def __init__(self, runtime: FuelLedgerRuntime, tank_id: str, device: Any) -> None:
        super().__init__(runtime, tank_id, KEY_TANK_CONTENT, device)
        self._tank_id = tank_id

    @property
    def native_value(self) -> float | None:
        return self.runtime.ledger.tank_volume(self._tank_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return _level(self.runtime.ledger.stock_level)


class TankLevelSensor(FuelLedgerEntity, SensorEntity):
    """Height of the surface above the floor, as a reading from the floor would show it now."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.CENTIMETERS
    _attr_suggested_display_precision = 1

    def __init__(self, runtime: FuelLedgerRuntime, tank_id: str, device: Any) -> None:
        super().__init__(runtime, tank_id, KEY_TANK_LEVEL, device)
        self._tank_id = tank_id

    @property
    def native_value(self) -> float | None:
        return self.runtime.ledger.tank_height(self._tank_id)


class ComponentPowerSensor(FuelLedgerEntity, SensorEntity):
    """What a component behind the power meter draws: its typical power, the burner also the rest."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 0
    _follows_power = True

    def __init__(self, runtime: FuelLedgerRuntime, component_id: str, device: Any) -> None:
        super().__init__(runtime, component_id, KEY_COMPONENT_POWER, device)
        self._component_id = component_id

    @property
    def native_value(self) -> float | None:
        return self.runtime.component_power(self._component_id)
