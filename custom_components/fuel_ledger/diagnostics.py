"""Diagnostics download: the configuration, the inputs and the stored ledger, for bug reports.

Contains entity IDs, names, deliveries and readings as entered; no credentials.
"""

from __future__ import annotations

from typing import Any

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from . import FuelLedgerConfigEntry
from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: FuelLedgerConfigEntry) -> dict[str, Any]:
    integration = await async_get_integration(hass, DOMAIN)
    result: dict[str, Any] = {
        "versions": {DOMAIN: str(integration.version), "home_assistant": HA_VERSION},
        "data": dict(entry.data),
        "options": dict(entry.options),
        "subentries": [
            {"id": s.subentry_id, "type": s.subentry_type, "title": s.title, "data": dict(s.data)}
            for s in entry.subentries.values()
        ],
    }
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        result["loaded"] = False
        return result
    result["loaded"] = True
    power = runtime.spec.power
    keys = [
        runtime.spec.burner.key,
        runtime.spec.burner.state_key,
        power.key if power else None,
        *(t.level_key for t in runtime.spec.tanks),
    ]
    result["inputs"] = {}
    for entity_id in dict.fromkeys(k for k in keys if k):
        state = hass.states.get(entity_id)
        result["inputs"][entity_id] = {
            "state": state.state if state else None,
            "unit": state.attributes.get("unit_of_measurement") if state else None,
            "last_changed": state.last_changed.isoformat() if state else None,
        }
    ledger = runtime.ledger
    measured = ledger.measured_factor()
    result["nominal_flow"] = runtime.spec.burner.nominal_flow
    result["measured_factor"] = measured.as_dict() if measured else None
    if runtime.power is not None:
        result["components"] = {
            c.id: {"running": runtime.power.state.get(c.id), "power": runtime.power.power(c.id)}
            for c in power.components
        }
    result["ledger"] = ledger.to_dict()
    return result
