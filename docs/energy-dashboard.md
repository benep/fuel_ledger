# Energy dashboard

!!! abstract "In short"

    - **Gas tab → Add gas source**: Fuel Ledger's **Energy** (kWh), with **Use an entity tracking the total costs**:
      its **Cost**.
    - **With Heat Ledger**: its **Heat** instead of Energy, so the rooms add up to it.
    - **A card for the heating** on your own dashboard: burner, pumps, stock and range.

The tab is called *Gas*, even for oil. That does not matter.

## Set it up

Go to **Settings → Dashboards → Energy**, tab **Gas**, and click **Add gas source**.

<div class="steps" markdown>

1. **Gas consumption**: choose **Heating oil Energy** (kWh), the energy in the oil the burner used.
2. **Cost tracking**: choose **Use an entity tracking the total costs** and then **Heating oil Cost**. It is the price of
   each delivery, blended with what was left, times every litre burnt: it stays right across deliveries.
3. Save.

</div>

??? question "Why not the consumption in litres, or the price per kWh?"

    - **Litres** work as well: the gas tab takes **Heating oil Consumption**, and the price as **Price per litre**.
      But the gas tab only combines sources and devices of the same kind of unit, and every other heat counter
      (Heat Ledger, a heat pump) counts kWh.
    - **Price per kWh** (*Use an entity with current price*) also works and changes with every delivery. The cost
      entity is exact even for the hour a delivery comes in, so it is the better choice.

## With Heat Ledger

[Heat Ledger](https://benep.github.io/heat_ledger/) splits the heat between your rooms. It needs a source that counts
**heat**: choose Fuel Ledger's **Heating oil Heat** there, as heat (not energy input, no factor). Heat is the energy
of the oil times the efficiency of the boiler (90 % unless you enter yours under **Fuel and boiler**).

In the gas tab, use **Heating oil Heat** as the source then, with **Heating oil Cost** as its cost, and the rooms of
Heat Ledger as individual devices. Their sum fits the source.

## A card for the heating

A dashboard card with the burner, the pumps, the stock and the range, from standard cards. Replace the entity IDs with
yours (**Settings → Devices & services → Entities**, search for *Heating oil*).

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: binary_sensor.burner
    name: Burner
  - type: glance
    entities:
      - entity: binary_sensor.heating_circuit_pump
        name: Circuit
      - entity: binary_sensor.hot_water_pump
        name: Hot water
      - entity: sensor.heating_oil_stock
        name: Stock
      - entity: sensor.heating_oil_range
        name: Range
  - type: gauge
    entity: sensor.heating_oil_fill_level
    severity:
      red: 0
      yellow: 15
      green: 30
```

The burner and the pumps are only there with a power meter; with a binary sensor for the burner, use that one.
**Heating oil Flow rate** shows the litres per hour while the burner runs.
