"""Feeds the ledger from Home Assistant: input states, the power meter, the 5-minute timer, the events and the
stored state."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_utc_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_INITIAL_FACTOR,
    CONF_INITIAL_STOCK,
    DOMAIN,
    INTERVAL,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
)
from .engine import Disaggregator, InputKind, Ledger, LedgerSpec, Origin
from .engine.history import past_checkpoints
from .engine.power import Change
from .model import parse_burner, parse_input, parse_level, parse_power

_LOGGER = logging.getLogger(__name__)

STORE_KEY_LEDGER = "ledger"
PAST_DAYS = 30  # at most this far back, if the recorder keeps it


def store_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}"


class FuelLedgerRuntime:
    """Owns the ledger of one config entry while it is loaded."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, spec: LedgerSpec) -> None:
        self.hass = hass
        self.entry = entry
        self.spec = spec
        self.ledger = Ledger(spec)
        self.power = Disaggregator(spec.power) if spec.power else None
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, store_key(entry.entry_id))
        self._listeners: list[CALLBACK_TYPE] = []
        self._power_listeners: list[CALLBACK_TYPE] = []
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self._due: CALLBACK_TYPE | None = None
        burner = spec.power.burner if spec.power else None
        self._burner_component = burner.id if burner else None

    # --- Lifecycle ---------------------------------------------------------------------------------------------

    async def async_start(self) -> None:
        """Restore the stored state, take the current readings and start listening."""
        stored = await self._store.async_load()
        if stored and isinstance(stored.get(STORE_KEY_LEDGER), dict):
            try:
                self.ledger = Ledger.from_dict(self.spec, stored[STORE_KEY_LEDGER])
            except (KeyError, TypeError, ValueError, AttributeError, IndexError):
                _LOGGER.warning("Stored state of %s is unreadable, starting over", self.entry.title, exc_info=True)
        now = self._now()
        if not self.ledger.restored:
            self._apply_initial(now)
            if "recorder" in self.hass.config.components:
                self.entry.async_create_background_task(
                    self.hass, self._async_read_past(now), f"{DOMAIN} past of {self.entry.title}"
                )
        burner = self.spec.burner
        if self.power is not None:
            self.power.update(now, self._read_power())  # the first measurement confirms at once
        if burner.kind is InputKind.POWER:
            self.ledger.observe(now, self._burner_running(), initial=True)
        else:
            self.ledger.observe(now, self._read_input(), initial=True)
        if burner.kind is InputKind.RUNTIME:
            self.ledger.burner_state(now, self._flow_state())
        self._measure(now)
        self.ledger.close_interval(now)

        watched = {burner.key}
        if burner.state_key:
            watched.add(burner.state_key)
        if self.spec.power:
            watched.add(self.spec.power.key)
        self._unsubscribe.append(async_track_state_change_event(self.hass, sorted(watched), self._on_state))
        minutes = int(INTERVAL.total_seconds() // 60)
        self._unsubscribe.append(
            async_track_utc_time_change(self.hass, self._on_interval, minute=f"/{minutes}", second=0)
        )
        self._unsubscribe.append(self.hass.bus.async_listen(EVENT_HOMEASSISTANT_STOP, self._on_stop))

    @callback
    def cancel(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        if self._due is not None:
            self._due()
            self._due = None

    async def async_stop(self) -> None:
        self.cancel()
        await self.async_save()

    async def async_save(self) -> None:
        self.ledger.settle(self._now())
        await self._store.async_save(self._data())

    # --- Sensors -----------------------------------------------------------------------------------------------

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE, *, power: bool = False) -> Callable[[], None]:
        """Call update after every interval and every event; with power, also after every measurement of the power
        meter (only the components follow it, the meter may report every second). Returns the remover."""
        listeners = self._power_listeners if power else self._listeners
        listeners.append(update)
        return lambda: listeners.remove(update)

    @callback
    def async_update_listeners(self) -> None:
        for update in [*self._listeners, *self._power_listeners]:
            update()

    @callback
    def _update_power_listeners(self) -> None:
        for update in list(self._power_listeners):
            update()

    async def async_changed(self) -> None:
        """After an event (delivery, reading, factor): save at once and update the sensors."""
        await self._store.async_save(self._data())
        self.async_update_listeners()

    def now(self) -> float:
        return self._now()

    def component_running(self, component_id: str) -> bool | None:
        return None if self.power is None else self.power.state.get(component_id)

    def component_power(self, component_id: str) -> float | None:
        return None if self.power is None else self.power.power(component_id)

    def tank_volume(self, tank_id: str) -> float | None:
        """Litres in a tank by its level sensor, or None without one or while it is unavailable."""
        tank = self.spec.tank(tank_id)
        if tank is None or not tank.level_key:
            return None
        state = self.hass.states.get(tank.level_key)
        return parse_level(tank, state.state, state.attributes) if state else None

    # --- Internals ---------------------------------------------------------------------------------------------

    def _now(self) -> float:
        return dt_util.utcnow().timestamp()

    def _apply_initial(self, now: float) -> None:
        """What the first setup asked for, once, into an empty ledger."""
        data = self.entry.data
        if (factor := data.get(CONF_INITIAL_FACTOR)) and self.spec.burner.kind is not InputKind.METER:
            self.ledger.factor = float(factor)
            self.ledger.factor_origin = Origin.SET if float(factor) != 1.0 else Origin.DEFAULT
        if (stock := data.get(CONF_INITIAL_STOCK)) is not None:
            self.ledger.set_stock(now, float(stock))

    def _read_input(self) -> float | bool | None:
        state = self.hass.states.get(self.spec.burner.key)
        if state is None:
            return None
        return parse_input(self.spec.burner.kind, state.state, state.attributes)

    def _read_power(self) -> float | None:
        assert self.spec.power is not None
        state = self.hass.states.get(self.spec.power.key)
        return parse_power(state.state, state.attributes) if state else None

    def _burner_running(self) -> bool | None:
        return self.component_running(self._burner_component) if self._burner_component else None

    def _flow_state(self) -> bool | None:
        """For the flow rate of a run time counter: the burner's binary sensor, else the burner in the power."""
        key = self.spec.burner.state_key
        if key:
            state = self.hass.states.get(key)
            return parse_burner(state.state if state else None)
        return self._burner_running()

    def _measure(self, now: float) -> None:
        if not self.spec.measured_stock:
            return
        volumes = {t.id: self.tank_volume(t.id) for t in self.spec.tanks}
        complete = all(v is not None for v in volumes.values())
        self.ledger.measure_stock(now, volumes if complete else None)  # type: ignore[arg-type]

    async def _async_read_past(self, end: float) -> None:
        """Once, at the first start: the consumption of the days the recorder still has, as checkpoints before the
        setup. Gives the range at once and lets deliveries and readings be dated before the setup."""
        from homeassistant.components.recorder import get_instance, history

        instance = get_instance(self.hass)
        stop = dt_util.utc_from_timestamp(end)
        begin = stop - timedelta(days=min(instance.keep_days, PAST_DAYS))
        if (oldest := instance.states_manager.oldest_ts) is not None:
            begin = max(begin, dt_util.utc_from_timestamp(oldest))
        if begin >= stop:
            return
        spec = self.spec
        keys = [spec.power.key] if spec.burner.kind is InputKind.POWER and spec.power else [spec.burner.key]

        def read() -> dict[str, list[State]]:
            return history.get_significant_states(self.hass, begin, stop, keys, None, True, False, False, False)

        try:
            await instance.async_block_till_done()
            states = await instance.async_add_executor_job(read)
        except Exception:
            _LOGGER.warning("%s: the recorded states could not be read", self.entry.title, exc_info=True)
            return
        samples: list[tuple[float, str, float | bool | None]] = []
        for key, items in states.items():
            for state in items:
                value = (
                    parse_power(state.state, state.attributes)
                    if spec.power and key == spec.power.key
                    else parse_input(spec.burner.kind, state.state, state.attributes)
                )
                samples.append((max(state.last_updated.timestamp(), begin.timestamp()), key, value))
        points = await self.hass.async_add_executor_job(past_checkpoints, spec, self.ledger.factor, samples, end)
        if taken := self.ledger.seed(points):
            _LOGGER.debug("%s: %d hours of consumption before the setup", self.entry.title, taken)
            await self.async_changed()

    def _data(self) -> dict[str, Any]:
        return {STORE_KEY_LEDGER: self.ledger.to_dict()}

    def _apply_changes(self, changes: list[Change]) -> None:
        """Confirmed changes of the components; the burner's goes to the ledger, from when it began."""
        burner = self.spec.burner
        for change in changes:
            if change.component != self._burner_component:
                continue
            if burner.kind is InputKind.POWER:
                self.ledger.observe(change.time, change.on, initial=change.initial)
            elif burner.kind is InputKind.RUNTIME and not burner.state_key:
                self.ledger.burner_state(change.time, change.on)
        self._schedule()
        if changes:
            self.async_update_listeners()

    def _schedule(self) -> None:
        """A timer for the next pending confirmation, so a pump is confirmed even without a new measurement."""
        if self._due is not None:
            self._due()
            self._due = None
        due = self.power.next_due() if self.power is not None else None
        if due is not None:
            self._due = async_track_point_in_utc_time(self.hass, self._on_due, dt_util.utc_from_timestamp(due))

    @callback
    def _on_due(self, moment: datetime) -> None:
        self._due = None
        assert self.power is not None
        self._apply_changes(self.power.tick(max(moment.timestamp(), self._now())))

    @callback
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        now = self._now()
        entity_id = event.data["entity_id"]
        new = event.data["new_state"]
        burner = self.spec.burner
        if self.power is not None and self.spec.power and entity_id == self.spec.power.key:
            watts = parse_power(new.state, new.attributes) if new else None
            self._apply_changes(self.power.update(now, watts))  # a confirmed change updates all
            self._update_power_listeners()  # the power of each component follows every measurement
            if burner.kind is InputKind.POWER:
                return
        if entity_id == burner.key:
            value = parse_input(burner.kind, new.state, new.attributes) if new else None
            self.ledger.observe(now, value)
        if entity_id == burner.state_key and burner.kind is not InputKind.BURNER:
            self.ledger.burner_state(now, parse_burner(new.state if new else None))
        if entity_id == burner.state_key:
            self.async_update_listeners()  # the flow rate follows the burner at once

    @callback
    def _on_interval(self, _now: Any) -> None:
        now = self._now()
        self._measure(now)
        self.ledger.close_interval(now)
        self.async_update_listeners()
        self._store.async_delay_save(self._data, STORAGE_SAVE_DELAY)

    async def _on_stop(self, _event: Event) -> None:
        await self.async_save()
