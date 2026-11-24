# Fuel Ledger

A Home Assistant custom integration that keeps the books for your heating fuel: consumption estimated from burner
run time (or taken from a meter), tank stock and range, deliveries with blended price, heating value and CO₂, and
calibration from dipstick readings. It provides energy, price and flow entities for the Energy dashboard.

Heating oil comes first; the design is fuel-agnostic so LPG, pellets and wood can follow.

Status: first version, not released yet.

Sister project: Heat Ledger, which splits the heat into per-radiator energy and can use the heat of Fuel Ledger as
its source.

## What you need

One of these, from best to roughest:

- **Oil meter:** a cumulative volume (L, m³). Measured, nothing is calculated.
- **Burner run time:** a cumulative counter in hours, minutes or seconds, from the boiler or a smart plug script.
- **Burner on/off:** a binary sensor. Fuel Ledger counts the run time itself, minus a prepurge per start. A power
  sensor works through a Threshold helper.

With run time or on/off, the nozzle (in GPH, as stamped on it) gives the consumption:
`L/h = GPH × 3.785 × √(pump pressure / test pressure) × correction factor`. Everything else is optional and makes
the books more accurate: pump pressure, tanks with their dimensions, deliveries with their invoice, dipstick
readings, level sensors.

## Setup

Settings → Devices & services → Add integration → Fuel Ledger. Three steps: the consumption input, the nozzle, the
tanks (several of the same size at once, e.g. battery tanks). More tanks, also steel tanks on their side or tanks
with a manufacturer's table, are added later on the integration page. Burner, fuel (heating value, CO₂, boiler
efficiency) and the stock settings are in the options.

## Actions

| Action | What it does |
|---|---|
| `fuel_ledger.record_delivery` | Amount and/or stock after the delivery, with the totals of the invoice (gross price, energy content in kWh, CO₂ in kg). Sets the stock and blends price, heating value and CO₂ with what was left in the tanks, weighted by volume. |
| `fuel_ledger.record_level` | A dipstick reading of one tank (cm or litres) at a measuring point. Two complete readings of all tanks at the same points, with the burner running in between, give the measured correction factor. |
| `fuel_ledger.set_stock` | Corrects the stock without a delivery, optionally with price, heating value and CO₂ of the oil in the tanks. Use it to start. |

A delivery may be dated back: the stock before it is taken at that moment. Its values apply from the moment it is
entered; nothing that was already counted changes.

## Entities

| Entity | For |
|---|---|
| Consumption (L), Energy (kWh), Heat (kWh), CO₂ (kg), Cost | Counters (`total_increasing`). Energy and consumption for the gas section of the Energy dashboard, heat for Heat Ledger. |
| Price per kWh, Price per litre | The blended price; enter *Price per kWh* as the price entity of the Energy dashboard. |
| Flow rate (L/h) | Live view of the Energy dashboard; needs the burner's on/off state. |
| Stock, Fill level, Range, Empty on, Low stock | The tanks. The range is calculated from the consumption of the last 7 days. |
| Correction factor, Measured factor, Apply measured factor | The factor is applied from now on. The measured one comes from dipstick readings, with its uncertainty, and is taken over with the button. |
| Heating value, CO₂ factor, Last delivery, per tank Last reading and Content | Diagnostics. |

Every counter states in its `level` attribute how it is obtained: `measured`, `calculated` or `estimated`, and in
`basis` where its inputs come from.

**Nothing applies retroactively.** A new factor, heating value, price or efficiency counts from the moment it
changes, so the counters of the Energy dashboard never jump.

## Development

```sh
pip install -r requirements_test.txt
pytest
```

## License

MIT
