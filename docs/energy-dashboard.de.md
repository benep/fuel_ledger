# Energie-Dashboard

!!! abstract "Kurz gesagt"

    - **Reiter Gas → Gaszähler hinzufügen**: die **Energie** von Fuel Ledger (kWh), mit **Eine Entität verwenden, die
      die Gesamtkosten erfasst**: seine **Kosten**.
    - **Mit Heat Ledger**: seine **Wärme** statt der Energie, damit die Räume darin aufgehen.
    - **Eine Karte für die Heizung** auf deinem eigenen Dashboard: Brenner, Pumpen, Vorrat und Reichweite.

Der Reiter heißt *Gas*, auch für Öl. Das spielt keine Rolle.

## Einrichten

Gehe zu **Einstellungen → Dashboards → Energie**, Reiter **Gas**, und klicke auf **Gaszähler hinzufügen**.

<div class="steps" markdown>

1. **Gasverbrauch**: Wähle **Heizöl Energie** (kWh), die Energie im Öl, das der Brenner verbraucht hat.
2. **Kostenerfassung**: Wähle **Eine Entität verwenden, die die Gesamtkosten erfasst** und dann **Heizöl Kosten**.
   Das ist der Preis jeder Lieferung, gemischt mit dem, was noch da war, mal jedem verbrannten Liter: Er bleibt über
   Lieferungen hinweg richtig.
3. Speichern.

</div>

??? question "Warum nicht den Verbrauch in Litern, oder den Preis pro kWh?"

    - **Liter** gehen auch: Der Gas-Reiter nimmt **Heizöl Verbrauch**, und den Preis als **Preis pro Liter**. Aber der
      Gas-Reiter kombiniert nur Quellen und Geräte mit derselben Art von Einheit, und jeder andere Wärmezähler (Heat
      Ledger, eine Wärmepumpe) zählt kWh.
    - **Preis pro kWh** (*Eine Entität mit dem aktuellen Preis verwenden*) geht auch und ändert sich mit jeder
      Lieferung. Die Entität mit den Kosten stimmt auch für die Stunde, in der eine Lieferung eintrifft, und ist
      deshalb die bessere Wahl.

## Mit Heat Ledger

[Heat Ledger](https://benep.github.io/heat_ledger/) teilt die Wärme auf deine Räume auf. Es braucht eine Quelle, die
**Wärme** zählt: Wähle dort **Heizöl Wärme** von Fuel Ledger, als Wärme (nicht als Energieeinsatz, kein Faktor). Wärme
ist die Energie des Öls mal dem Wirkungsgrad des Kessels (90 %, wenn du deinen nicht unter **Brennstoff und Kessel**
einträgst).

Im Gas-Reiter nimmst du dann **Heizöl Wärme** als Quelle, mit **Heizöl Kosten** als Kosten, und die Räume von Heat
Ledger als einzelne Geräte. Ihre Summe passt zur Quelle.

## Eine Karte für die Heizung

Eine Dashboard-Karte mit Brenner, Pumpen, Vorrat und Reichweite, aus Standardkarten. Ersetze die Entitäts-IDs durch
deine (**Einstellungen → Geräte & Dienste → Entitäten**, suche nach *Heizöl*).

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: binary_sensor.burner
    name: Brenner
  - type: glance
    entities:
      - entity: binary_sensor.heating_circuit_pump
        name: Heizkreis
      - entity: binary_sensor.hot_water_pump
        name: Warmwasser
      - entity: sensor.heating_oil_stock
        name: Vorrat
      - entity: sensor.heating_oil_range
        name: Reichweite
  - type: gauge
    entity: sensor.heating_oil_fill_level
    severity:
      red: 0
      yellow: 15
      green: 30
```

Brenner und Pumpen gibt es nur mit Leistungsmessung; mit einem Binärsensor für den Brenner nimm diesen.
**Heizöl Durchfluss** zeigt die Liter pro Stunde, solange der Brenner läuft.
