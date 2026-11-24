"""Constants shared by the config flow, the model and the runtime.

The keys below are the stored format of the config entry and its subentries. Changing one needs a migration.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "fuel_ledger"

INTERVAL: Final = timedelta(minutes=5)
STORAGE_VERSION: Final = 1
STORAGE_SAVE_DELAY: Final = 30  # seconds; events are saved at once, and everything on shutdown

# Main entry, in options so it can change without removing the entry: the burner and the fuel.
CONF_FUEL: Final = "fuel"  # engine FUELS key
CONF_ENTITY: Final = "entity_id"  # the input: run time counter, oil meter or burner on/off
CONF_KIND: Final = "kind"  # engine.InputKind value, from the input's domain and unit
CONF_NOZZLE_GPH: Final = "nozzle_gph"
CONF_NOMINAL_FLOW: Final = "nominal_flow"  # L/h, replaces the nozzle
CONF_PUMP_PRESSURE: Final = "pump_pressure"  # bar
CONF_TEST_PRESSURE: Final = "test_pressure"  # bar, the pressure the nozzle is rated at
CONF_PREPURGE_S: Final = "prepurge_s"  # burner input only
CONF_BURNER_ENTITY: Final = "burner_entity_id"  # run time input: on while the burner runs, for the flow rate
CONF_EFFICIENCY: Final = "efficiency"  # 0…1
CONF_HEATING_VALUE: Final = "heating_value"  # kWh/L, for fuel of unknown origin
CONF_CO2: Final = "co2"  # kg/L, for fuel of unknown origin
CONF_LOW_PERCENT: Final = "low_percent"
CONF_RANGE_DAYS: Final = "range_days"
CONF_READING_ACCURACY: Final = "reading_accuracy_cm"

# Main entry, in data: chosen in the first setup and applied once, when the ledger starts empty.
CONF_INITIAL_STOCK: Final = "initial_stock"  # litres
CONF_INITIAL_FACTOR: Final = "initial_factor"

# Subentry types
SUBENTRY_TANK: Final = "tank"

# Tank subentry (the name is its title)
CONF_CAPACITY: Final = "capacity"  # litres
CONF_SHAPE: Final = "shape"  # engine.Shape value
CONF_PER_CM: Final = "per_cm"  # linear: litres per cm
CONF_DIAMETER: Final = "diameter_cm"
CONF_LENGTH: Final = "length_cm"
CONF_TABLE: Final = "table"  # list of [cm, litres]
CONF_OFFSET: Final = "offset_cm"
CONF_RESIDUE: Final = "residue"  # litres
CONF_LEVEL_ENTITY: Final = "level_entity_id"

# Entity keys: unique ID suffix and translation key (strings.json: entity.<platform>.<key>)
KEY_CONSUMPTION: Final = "consumption"
KEY_ENERGY: Final = "energy"
KEY_HEAT: Final = "heat"
KEY_COST: Final = "cost"
KEY_CO2: Final = "co2"
KEY_FLOW: Final = "flow"
KEY_RUNTIME: Final = "runtime"
KEY_STOCK: Final = "stock"
KEY_FILL: Final = "fill"
KEY_RANGE: Final = "range"
KEY_EMPTY: Final = "empty"
KEY_LOW: Final = "low"
KEY_PRICE: Final = "price"
KEY_PRICE_ENERGY: Final = "price_energy"
KEY_HEATING_VALUE: Final = "heating_value"
KEY_CO2_FACTOR: Final = "co2_factor"
KEY_FACTOR: Final = "factor"
KEY_MEASURED_FACTOR: Final = "measured_factor"
KEY_APPLY_FACTOR: Final = "apply_measured_factor"
KEY_LAST_DELIVERY: Final = "last_delivery"
KEY_TANK_READING: Final = "last_reading"
KEY_TANK_CONTENT: Final = "content"

# State attributes
ATTR_LEVEL: Final = "level"  # engine.Level value
ATTR_BASIS: Final = "basis"  # dict quantity -> where it comes from
ATTR_ORIGIN: Final = "origin"  # engine.Origin value of a price, heating value or factor
ATTR_UNCERTAINTY: Final = "uncertainty"

# Services
SERVICE_RECORD_DELIVERY: Final = "record_delivery"
SERVICE_RECORD_LEVEL: Final = "record_level"
SERVICE_SET_STOCK: Final = "set_stock"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_DEVICE_ID: Final = "device_id"
ATTR_TIME: Final = "time"
ATTR_AMOUNT: Final = "amount"
ATTR_LEVEL_AFTER: Final = "level_after"
ATTR_TOTAL_PRICE: Final = "total_price"
ATTR_ENERGY: Final = "energy"
ATTR_CO2: Final = "co2"
ATTR_PRODUCT: Final = "product"
ATTR_SUPPLIER: Final = "supplier"
ATTR_HEIGHT: Final = "level"  # cm
ATTR_VOLUME: Final = "volume"  # litres
ATTR_POINT: Final = "point"
ATTR_PRICE: Final = "price"  # per litre
ATTR_HEATING_VALUE: Final = "heating_value"  # kWh per litre

# Main entry, in options: how several tanks are connected (engine.Link value).
CONF_LINK: Final = "link"
# Main entry, in options: a power meter of the heating, and what it draws all the time (W). With the input kind
# "power" it is the input itself.
CONF_POWER_ENTITY: Final = "power_entity_id"
CONF_BASE_POWER: Final = "base_power"

# Subentry type and data of a component behind the power meter (the name is its title)
SUBENTRY_COMPONENT: Final = "component"
CONF_COMPONENT_KIND: Final = "component_kind"  # engine.ComponentKind value
CONF_POWER: Final = "power"  # W, typical
CONF_ON_DELAY: Final = "on_delay_s"
CONF_OFF_DELAY: Final = "off_delay_s"

# Entity keys of components and tanks
KEY_RUNNING: Final = "running"
KEY_COMPONENT_POWER: Final = "power"
KEY_TANK_LEVEL: Final = "level"
