# Architecture

Fuel Ledger keeps the books of one fuel store per config entry: counters for the Energy dashboard, the content of
each tank, and the events that change them. It never controls anything; every input is an existing entity.

## Layers

```
custom_components/fuel_ledger/
  engine/         plain Python, no Home Assistant: every call carries its time
    spec.py       input kinds, levels, origins, fuel profile, nozzle flow, LedgerSpec
    tank.py       tank shapes: height ↔ volume
    stock.py      several tanks: which one the burner draws from, how a delivery fills them, readings
    power.py      components behind one power meter: which of them run (Disaggregator)
    calibration.py  surveys of readings and the measured factor
    ledger.py     counters, events, stock, levels, storage
  model.py        options and subentries → LedgerSpec; parsing of input states
  runtime.py      feeds the ledger from Home Assistant: state changes, the 5-minute timer, storage
  __init__.py     setup, actions, repair notes
  config_flow.py  first setup, options menu, subentry flows for tanks and components
  sensor.py, binary_sensor.py, number.py, button.py   entities, written by the runtime
```

The engine runs the same live, in tests and over recorded history: time is an argument, never `now()`.

## Inputs

| Kind | Entity | Counted by |
|---|---|---|
| `meter` | cumulative litres or m³ | the counter's increase, booked as measured litres |
| `runtime` | cumulative hours, minutes or seconds | the counter's increase × nominal flow × factor |
| `burner` | binary sensor | on-time minus prepurge per start, booked at each change and each interval |
| `power` | power in W | the burner component of the `Disaggregator`, then like `burner` |

Counters follow Home Assistant's `total_increasing` rules (`_Counter`): a drop below 90 % is a reset, a smaller drop
is a debt the next increases pay off. A reading back at its old value after a drop to 0 is a glitch, not a reset.

A power meter may also sit next to a `runtime` or `meter` input: it then only drives the component sensors and the
burner state for the flow rate.

## Power disaggregation

`Disaggregator` holds every combination of components (up to 8) with its expected power: base load plus their typical
powers, without combinations of burner and preheater. Each measurement picks the closest combination (fewer
components on a tie). A change of a component is confirmed after its delay (pumps 60 s on, 120 s off; the burner
stops at once) and dated to when it began. Unavailable reports every component as unknown; the next measurement is
taken as found (`initial`), not as a switch.

## Counters and values

`consumption`, `nominal` (litres at factor 1), `energy`, `heat`, `cost`, `co2`, `runtime_h` and `starts` only grow, by
what is booked at the values that apply at that moment: factor, heating value, price, CO₂ factor, efficiency. A new
value never rebooks the past.

## Events and the stock

Corrections (`set_stock`), deliveries, readings and the last measurement of the level sensors are events with a
time, a sequence number and the consumption at that time. The consumption at a moment in the past is interpolated
from checkpoints (every interval for 2 days, hourly for 400 days). The stock is recomputed from the events in
`(time, seq)` order: each event sets or changes the tank volumes, and the consumption between events is drawn with
`stock.draw`. So an event dated back simply lands in its place.

- **Draw**: tanks without dimensions in proportion to their content. With dimensions, the highest surfaces (height
  above the floor, `offset_cm` included) are lowered first: a water-filling level found by bisection. Content above a
  tank's geometric top goes first.
- **Fill**: the lowest surfaces first, each up to its capacity.
- **Reading**: connected at the bottom, all tanks to the same height (without dimensions: the same share of capacity).
  On a T-piece, only that tank, unless the others are only *assumed* (after a total was spread): then the total stays
  and the unread tanks share the rest.
- **Delivery**: the rest before is the stock then (or level after − amount); price, heating value and CO₂ are blended
  by volume. The amount at entry is kept, so the values per litre survive a reading dated back before it.

## The days before the setup

At the first start (no stored state), a background task reads the recorded states of the input (or of the power
meter) for the days the recorder keeps, at most 30, and replays them through a ledger of their own
(`engine/history.py`), closing an interval every hour. Its checkpoints, counted back so that the setup is 0, are
prepended to the live ones (`Ledger.seed`). Counters are not touched; the range has its window at once, and events
can be dated back to the first recorded hour. Consumption before the setup is negative on this scale, which the
stock calculation takes as it is.

## Measured factor

`calibration.surveys` groups readings into surveys: every current tank read within 2 hours, a tank read again after
the burner ran starts the next survey. Two surveys at the same points give `measured / nominal`, with deliveries
in between added by their entered amount. The pair with the largest nominal consumption wins; the uncertainty
comes from the reading accuracy and the litres per cm at each reading.

## Levels

Each result states `measured`, `calculated` or `estimated` (`spec.Level`), the worst of its inputs: the consumption
(meter, measured factor, or default factor), the heating value and CO₂ (delivery or set, or default), the efficiency
(set or default), the stock (all level sensors or calculated). `basis_<input>` gives the origin of each input.

## Storage

The ledger is stored per entry (`Store`, key `fuel_ledger.<entry_id>`): counters, the counter state of the input,
checkpoints and all events. It is saved after every event, every 5 minutes (delayed) and on stop. On load, the stock
is recomputed from the events; events of tanks that no longer exist are left out. The options and subentries form
the `LedgerSpec`; any change reloads the entry, the stored state carries over.

## Repairs

- `components_alike_<entry>`: two components within 5 W or 10 % of each other. Not fixable by itself; it disappears
  when the powers are changed.
- A power input without a burner component does not load (`ConfigEntryError`, translated).
