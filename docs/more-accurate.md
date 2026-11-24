# More accurate

The setup gives a useful estimate with the minimum: something that tells when the burner runs, and the nozzle. Every
detail you add makes it more accurate. None of them is needed, and you can add them at any time without the counters
starting over.

!!! abstract "In short: what helps most"

    | Detail | Brings | Where |
    |---|---|---|
    | **Two dipstick readings** | The measured factor: the consumption from *estimated* to *calculated* | [Readings](deliveries-and-readings.md#readings-with-a-dipstick) |
    | **Deliveries with the invoice** | The right price, heating value and CO₂ | [Deliveries](deliveries-and-readings.md#deliveries) |
    | **Pump pressure** | A better start before the factor is measured | Options → Burner and nozzle |
    | **Tanks with their size** | Stock per tank, fill level, readings in cm | Integration page → Add tank / Edit tank |
    | **Level sensors** | The stock *measured* instead of calculated | Edit tank → More accurate |
    | **Boiler efficiency** | The heat *calculated* instead of estimated | Options → Fuel and boiler |
    | **Oil meter** | The consumption *measured* | Options → Burner and nozzle |

    The attribute **Level** of each sensor says where it stands, **Basis** where its inputs come from.

To change the options: **Settings → Devices & services → Fuel Ledger**, the gear icon :material-cog: of the entry.

## The correction factor

The biggest step. The nozzle alone is often 10 to 30 % off. Two readings of all tanks, some weeks apart, measure
how far: [The measured factor](deliveries-and-readings.md#the-measured-factor). Until then, the pump pressure brings
it closer: a nozzle rated at 7 bar sprays about 20 % more at 10 bar.

The factor is the number entity **Correction factor**. A new value counts from the moment it is set.

## Deliveries with the invoice

The invoice tells the price, and often the energy content and the CO₂ of the oil (in Germany it has to). With them,
cost, energy and CO₂ are *calculated*, not estimated, and they follow each delivery. Without the energy content,
Fuel Ledger assumes 10.0 kWh per litre (the net calorific value of heating oil).

??? question "Net or gross calorific value?"

    Invoices give the **net** calorific value (about 10 kWh/L, *Heizwert*), which is the default here. If you want to
    compare with a gas bill, which uses the **gross** value (*Brennwert*), enter about 10.6 kWh/L under **Fuel and
    boiler**. Either way, set it only once: a change counts from then on.

## Tanks of another shape

Tanks with upright walls (plastic battery tanks, most cellar tanks) only need the **litres per cm**: their base area
in m² × 10, or the capacity divided by the height. Two more shapes, chosen in **Add tank** or **Edit tank**:

| Shape | Asks for |
|---|---|
| **Steel tank on its side** | Inner diameter and inner length in cm. The litres per cm change with the height, Fuel Ledger knows how. |
| **Table of the manufacturer** | One pair per line, height in cm and litres, e.g. `10: 95`. Between them it is interpolated. |

Under **More accurate** in the tank:

- **Empty at**: the reading in cm when the tank is empty, if you measure from the floor.
- **Residue**: litres at the bottom the burner cannot draw. The range ends there.
- **Level sensor**: see below.

## Level sensors

A sensor of the fill level (ultrasonic, radar, pressure) in cm, L or %, chosen in **Edit tank**. With one on **every**
tank, the stock is *measured*: each measurement replaces the calculation. While one is unavailable, Fuel Ledger
continues from the last measurement with the calculated consumption.

## The efficiency of the boiler

Heat = energy in the oil × efficiency. Without a value, Fuel Ledger takes 90 %. The flue gas measurement of the
chimney sweep shows the losses: efficiency ≈ 100 % − flue gas loss. Enter it under **Fuel and boiler**, e.g. 0.92.

## A power meter

A power meter in front of the boiler shows each component on its own: the burner, the oil preheater and the pumps,
each as a binary sensor and a power sensor. With a run time counter as input, it also gives a live flow rate. Add it
under **Burner and nozzle → More accurate**, then the components on the integration page with **Add component**.

- **Delays**: a pump has to show for 60 s before it counts as running, and be gone for 120 s before it counts as
  stopped. If yours switches differently (a hot water pump that runs on a few minutes after charging), set
  **Running after** and **Stopped after** in **Edit component**.
- **Base load**: what the control draws all the time, under **Power meter** in the options.

## An oil meter

An oil meter measures the litres the burner uses. As input, it replaces the run time, the nozzle and the factor:
the consumption is *measured*. Choose it under **Burner and nozzle**; the counters continue, nothing starts over.
