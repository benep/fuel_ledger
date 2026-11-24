# Genauer machen

Schon mit dem Minimum, etwas, das meldet, wann der Brenner läuft, und der Düse, liefert die Einrichtung eine
brauchbare Schätzung. Jede weitere Angabe macht sie genauer. Keine davon ist nötig, und du kannst sie jederzeit
ergänzen, ohne dass die Zähler neu anfangen.

!!! abstract "Kurz gesagt: was am meisten hilft"

    | Angabe | Bringt | Wo |
    |---|---|---|
    | **Zwei Peilungen** | Den gemessenen Faktor: den Verbrauch von *geschätzt* zu *berechnet* | [Peilungen](deliveries-and-readings.md#peilungen-mit-dem-peilstab) |
    | **Lieferungen mit Rechnung** | Den richtigen Preis, Heizwert und CO₂ | [Lieferungen](deliveries-and-readings.md#lieferungen) |
    | **Pumpendruck** | Einen besseren Start, bevor der Faktor gemessen ist | Optionen → Brenner und Düse |
    | **Tanks mit ihrer Größe** | Vorrat je Tank, Füllgrad, Peilungen in cm | Seite der Integration → Tank hinzufügen / Tank bearbeiten |
    | **Füllstandssensoren** | Den Vorrat *gemessen* statt gerechnet | Tank bearbeiten → Genauer |
    | **Wirkungsgrad des Kessels** | Die Wärme *berechnet* statt geschätzt | Optionen → Brennstoff und Kessel |
    | **Ölzähler** | Den Verbrauch *gemessen* | Optionen → Brenner und Düse |

    Das Attribut **Stufe** jedes Sensors sagt, wo er steht, die Attribute **Grundlage**, woher seine Eingänge kommen.

So änderst du die Optionen: **Einstellungen → Geräte & Dienste → Fuel Ledger**, das Zahnrad :material-cog: des
Eintrags.

## Der Korrekturfaktor

Der größte Schritt. Die Düse allein liegt oft 10 bis 30 % daneben. Zwei Peilungen aller Tanks, ein paar Wochen
auseinander, messen, wie weit: [Der gemessene Faktor](deliveries-and-readings.md#der-gemessene-faktor). Bis dahin
bringt ihn der Pumpendruck näher heran: Eine Düse, die für 7 bar angegeben ist, sprüht bei 10 bar etwa 20 % mehr.

Der Faktor ist die Zahlen-Entität **Korrekturfaktor**. Ein neuer Wert gilt ab dem Moment, in dem er gesetzt wird.

## Lieferungen mit Rechnung

Die Rechnung nennt den Preis, und oft den Energiegehalt und das CO₂ des Öls (in Deutschland muss sie das). Damit sind
Kosten, Energie und CO₂ *berechnet*, nicht geschätzt, und sie folgen jeder Lieferung. Ohne den Energiegehalt nimmt
Fuel Ledger 10,0 kWh pro Liter an (den Heizwert von Heizöl).

??? question "Heizwert oder Brennwert?"

    Rechnungen nennen den **Heizwert** (etwa 10 kWh/L), und der ist hier voreingestellt. Willst du mit einer
    Gasrechnung vergleichen, die den **Brennwert** verwendet, trag unter **Brennstoff und Kessel** etwa 10,6 kWh/L
    ein. So oder so: Setze ihn nur einmal, eine Änderung gilt ab dann.

## Tanks anderer Form

Tanks mit senkrechten Wänden (Batterietanks aus Kunststoff, die meisten Kellertanks) brauchen nur die **Liter pro
cm**: ihre Grundfläche in m² × 10, oder das Fassungsvermögen geteilt durch die Höhe. Zwei weitere Formen, gewählt in **Tank
hinzufügen** oder **Tank bearbeiten**:

| Form | Fragt nach |
|---|---|
| **Liegender Stahltank** | Innendurchmesser und Innenlänge in cm. Die Liter pro cm ändern sich mit der Höhe, Fuel Ledger weiß, wie. |
| **Peiltabelle des Herstellers** | Ein Paar pro Zeile, Höhe in cm und Liter, z. B. `10: 95`. Dazwischen wird interpoliert. |

Unter **Genauer** im Tank:

- **Leer bei**: der Messwert in cm bei leerem Tank, wenn du ab dem Boden misst.
- **Bodenrest**: Liter am Boden, die der Brenner nicht ansaugen kann. Dort endet die Reichweite.
- **Füllstandssensor**: siehe unten.

## Füllstandssensoren

Ein Sensor für den Füllstand (Ultraschall, Radar, Druck) in cm, L oder %, gewählt in **Tank bearbeiten**. Hat **jeder**
Tank einen, ist der Vorrat *gemessen*: Jede Messung ersetzt die Rechnung. Solange einer nicht verfügbar ist, rechnet
Fuel Ledger ab der letzten Messung mit dem berechneten Verbrauch weiter.

## Der Wirkungsgrad des Kessels

Wärme = Energie im Öl × Wirkungsgrad. Ohne Wert nimmt Fuel Ledger 90 %. Die Abgasmessung des Schornsteinfegers zeigt
die Verluste: Wirkungsgrad ≈ 100 % − Abgasverlust. Trag ihn unter **Brennstoff und Kessel** ein, z. B. 0,92.

## Eine Leistungsmessung

Eine Leistungsmessung vor dem Kessel zeigt jede Komponente für sich: den Brenner, die Ölvorwärmung und die Pumpen,
jeweils als Binärsensor und als Leistungssensor. Mit einem Laufzeitzähler als Eingang ergibt sie außerdem einen
Live-Durchfluss. Ergänze sie unter **Brenner und Düse → Genauer**, dann die Komponenten auf der Seite der Integration
mit **Komponente hinzufügen**.

- **Verzögerungen**: Eine Pumpe muss sich 60 s zeigen, bevor sie als laufend gilt, und 120 s weg sein, bevor sie als
  stehend gilt. Schaltet deine anders (eine Warmwasserpumpe, die nach dem Laden noch ein paar Minuten nachläuft),
  setze **Läuft nach** und **Steht nach** in **Komponente bearbeiten**.
- **Grundlast**: was die Regelung dauernd zieht, unter **Leistungsmessung** in den Optionen.

## Ein Ölzähler

Ein Ölzähler misst die Liter, die der Brenner verbraucht. Als Eingang ersetzt er Laufzeit, Düse und Faktor: Der
Verbrauch ist *gemessen*. Wähle ihn unter **Brenner und Düse**; die Zähler laufen weiter, nichts fängt neu an.
