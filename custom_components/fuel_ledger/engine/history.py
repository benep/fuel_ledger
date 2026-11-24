"""The consumption before the setup, from the recorded states of the input: the same ledger, replayed.

At the first start, the ledger has no past: the range would wait a day for consumption, and a delivery or reading
from before the setup could not be dated. The recorder still has the states of the input for its last days. Replayed
through a ledger of their own (and the power meter through its disaggregator), they give the consumption at every
hour before the setup. Only these checkpoints are taken over, counted back from the setup: no counter changes.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from .ledger import HOUR_S, Ledger
from .power import Change, Disaggregator
from .spec import InputKind, LedgerSpec

Sample = tuple[float, str, float | bool | None]  # time, entity, parsed value


def past_checkpoints(spec: LedgerSpec, factor: float, samples: Iterable[Sample], end: float) -> list[list[float]]:
    """[time, consumption, nominal] each hour up to end, counted back from end (end itself is 0, earlier ones less).

    Samples: the parsed states of the input (and of the power meter for a power input), the first of each the state
    it had at the beginning. Empty if there is nothing to replay.
    """
    kind = spec.burner.kind
    ledger = Ledger(spec)
    ledger.factor = factor
    power = Disaggregator(spec.power) if kind is InputKind.POWER and spec.power else None
    burner = spec.power.burner.id if power is not None and spec.power and spec.power.burner else None
    seen: set[str] = set()
    next_close: float | None = None

    def apply(changes: list[Change]) -> None:
        for change in changes:
            if change.component == burner:
                ledger.observe(change.time, change.on, initial=change.initial)

    def until(ts: float) -> None:
        nonlocal next_close
        while True:
            due = power.next_due() if power is not None else None
            # A reading at the full hour belongs to it: the hour is closed after the readings of its moment.
            step = next_close if next_close is not None and next_close < ts else None
            if due is not None and due <= ts and (step is None or due <= step):
                apply(power.tick(due))  # type: ignore[union-attr]
            elif step is not None:
                ledger.close_interval(step)
                next_close = step + HOUR_S
            else:
                return

    for ts, key, value in sorted(samples, key=lambda s: s[0]):
        if next_close is None:
            ledger.close_interval(ts)
            next_close = math.floor(ts / HOUR_S) * HOUR_S + HOUR_S
        until(min(ts, end))
        if ts > end:
            break
        first = key not in seen
        seen.add(key)
        if power is not None and spec.power and key == spec.power.key:
            apply(power.update(ts, value if isinstance(value, float) else None))
        elif key == spec.burner.key and kind is not InputKind.POWER:
            ledger.observe(ts, value, initial=first)
    if next_close is None:
        return []
    until(end)
    ledger.close_interval(end)
    consumption, nominal = ledger.consumption, ledger.nominal
    return [[t, c - consumption, n - nominal] for t, c, n in ledger.checkpoints]
