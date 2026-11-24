"""At the first start, the recorded days before the setup give the range at once."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.fuel_ledger.const import (
    CONF_CAPACITY,
    CONF_ENTITY,
    CONF_KIND,
    CONF_NOZZLE_GPH,
    CONF_PER_CM,
    DOMAIN,
    SUBENTRY_TANK,
)

RUNTIME = "sensor.burner_runtime"
START = datetime(2026, 1, 1, tzinfo=UTC)
FLOW = 0.5 * 3.785411784


@pytest.fixture
def mock_recorder_before_hass(async_test_recorder: Any) -> None:
    """The recorder's database has to be prepared before Home Assistant is; tests asking for recorder_mock get it."""


async def background(hass: HomeAssistant) -> None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if tasks := list(entry._background_tasks):
            await asyncio.gather(*tasks)
    await hass.async_block_till_done()


async def test_the_recorded_days_give_the_range_at_once(
    recorder_mock: Recorder, hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    for day in range(4):  # 2 h of burner a day
        freezer.move_to(START + timedelta(days=day))
        hass.states.async_set(RUNTIME, str(100 + 2 * day), {"unit_of_measurement": "h"})
        await hass.async_block_till_done()
    freezer.move_to(START + timedelta(days=3, minutes=1))
    await async_wait_recording_done(hass)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Heating oil",
        data={"initial_stock": 900.0},
        options={CONF_ENTITY: RUNTIME, CONF_KIND: "runtime", CONF_NOZZLE_GPH: 0.5},
        subentries_data=[
            {
                "subentry_id": "tank",
                "subentry_type": SUBENTRY_TANK,
                "title": "Tank",
                "unique_id": None,
                "data": {CONF_CAPACITY: 1000.0, CONF_PER_CM: 8.0},
            }
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await background(hass)

    daily = 2 * FLOW
    assert float(hass.states.get("sensor.heating_oil_range").state) == pytest.approx(900 / daily, abs=0.5)
    assert float(hass.states.get("sensor.heating_oil_consumption").state) == 0.0  # no counter moved
    # The day the tanks run empty is a local date, so it does not move with every recalculation.
    days = float(hass.states.get("sensor.heating_oil_range").state)
    empty = dt_util.as_local(dt_util.utcnow() + timedelta(days=days)).date()
    assert hass.states.get("sensor.heating_oil_empty_on").state == empty.isoformat()
