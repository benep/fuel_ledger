# Questions

## Getting started

??? question "My heating has no sensor at all. What is the cheapest way?"

    A smart plug that measures power, between the boiler and its socket. Choose its power sensor as the input: Fuel
    Ledger finds the burner in it, and the pumps if you tell their power. Ask an electrician if the boiler is wired
    in without a plug.

??? question "Where do I find the nozzle?"

    It is stamped on the nozzle itself (e.g. *0.50 GPH 60° S*) and written in the maintenance record of the burner,
    often with the pump pressure. The first number is the throughput in US gallons per hour, the one Fuel Ledger asks
    for.

??? question "Why is the range empty?"

    Most often the stock is unknown: tell Fuel Ledger what is in the tanks with **Set stock** or a reading of each
    tank. The range also needs at least a day of consumption. At the first start, Fuel Ledger reads the days the
    recorder of Home Assistant still has (10 by default), so that is usually there at once; without them it waits a
    day. It uses up to the last 7 days (**Stock and range** in the options).

??? question "Why is the stock unknown although I read one tank?"

    With several tanks on a T-piece, each tank keeps its own content, so each has to be known once: read every tank,
    or set the total with **Set stock**.

## The numbers

??? question "How accurate is the consumption?"

    With the nozzle alone, often 10 to 30 % off. With a measured factor from two readings some weeks apart, a few
    percent, depending on how much was used in between and how exactly you read. With an oil meter, it is measured.
    The attribute **Level** says which of these applies.

??? question "The consumption seems too high (or too low). What can I do?"

    Read all tanks now, and again in a few weeks at the same points. The measured factor then shows how far off it is,
    and the button **Apply measured factor** corrects it from then on. If you know the pump pressure, enter it
    meanwhile: it is the most common reason for a nozzle to burn more than stamped on it.

??? question "Why does the burner have a power sensor, and why does it vary?"

    With a power meter, each component gets a sensor for its power. The pumps show their typical power; what the
    measurement has above or below goes to the burner while it runs, as its draw varies most.

??? question "A pump shows as running although it is not."

    Its typical power may be close to another one's, or to the burner's variation. Compare with the history of the
    power meter and set a more exact power in **Edit component**. If two components draw almost the same, Fuel Ledger
    raises a repair note: it cannot tell them apart.

??? question "Why did my energy not jump when I changed the heating value?"

    On purpose. A new heating value, price, factor or efficiency counts from the moment it is set. What was counted
    stays, so the Energy dashboard never jumps.

??? question "Can I see the heat per room?"

    Not with Fuel Ledger alone. Its sister integration [Heat Ledger](https://benep.github.io/heat_ledger/) splits the
    **Heat** of Fuel Ledger between your rooms and your hot water, with your thermostats.
    [Energy dashboard](energy-dashboard.md#with-heat-ledger) shows how to connect them.

## Changing things

??? question "I entered a wrong reading or delivery."

    It cannot be deleted yet. Enter a new reading or **Set stock** with the right value: the latest event decides the
    stock from its moment on.

??? question "I replaced the run time counter (or the smart plug)."

    Choose the new one under **Burner and nozzle**. Fuel Ledger counts it from its next reading; what was counted
    stays. A counter that starts again from 0 is noticed by itself.

??? question "Can I add a tank later?"

    Yes, with **Add tank** on the integration page. Its content is unknown until you read it or set the stock again.

??? question "How do I remove Fuel Ledger?"

    **Settings → Devices & services → Fuel Ledger**, the three dots, **Delete**. Its sensors and devices disappear,
    their history stays. Remove its entries from the Energy dashboard by hand, it keeps them and reports them as
    missing. Then remove Fuel Ledger in the Marketplace: open it there and choose **Uninstall**.

## Help

??? question "Something is wrong. What should I send?"

    [Open an issue](https://github.com/benep/fuel_ledger/issues) and attach the **diagnostics**: on the integration
    page, the three dots, **Download diagnostics**. It contains your setup, the current state of the entities Fuel
    Ledger reads and its books (deliveries, readings, counters), nothing else.
