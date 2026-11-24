# Häufige Fragen

## Erste Schritte

??? question "Meine Heizung hat überhaupt keinen Sensor. Was ist der günstigste Weg?"

    Eine Messsteckdose, die Leistung misst, zwischen Kessel und Steckdose. Wähle ihren Leistungssensor als Eingang:
    Fuel Ledger findet den Brenner darin, und die Pumpen, wenn du ihre Leistung angibst. Ist der Kessel ohne Stecker
    fest angeschlossen, frag einen Elektriker.

??? question "Wo finde ich die Düse?"

    Sie ist auf der Düse selbst aufgedruckt (z. B. *0.50 GPH 60° S*) und steht im Wartungsprotokoll des Brenners,
    oft zusammen mit dem Pumpendruck. Die erste Zahl ist der Durchsatz in US-Gallonen pro Stunde, nach dem Fuel Ledger
    fragt.

??? question "Warum ist die Reichweite leer?"

    Meistens ist der Vorrat noch unbekannt: Sag Fuel Ledger mit **Vorrat setzen** oder einer Peilung jedes Tanks, was
    in den Tanks ist. Außerdem braucht die Reichweite mindestens einen Tag Verbrauch. Beim ersten Start liest Fuel
    Ledger die Tage, die der Recorder von Home Assistant noch hat (standardmäßig 10), deshalb ist der meist sofort da;
    ohne sie wartet es einen Tag. Sie nutzt bis zu den letzten 7 Tagen (**Vorrat und Reichweite** in den Optionen).

??? question "Warum ist der Vorrat unbekannt, obwohl ich einen Tank gepeilt habe?"

    Bei mehreren Tanks an einem T-Stück behält jeder Tank seinen eigenen Inhalt, also muss jeder einmal bekannt sein:
    Peil jeden Tank, oder setze die Summe mit **Vorrat setzen**.

## Die Zahlen

??? question "Wie genau ist der Verbrauch?"

    Mit der Düse allein oft 10 bis 30 % daneben. Mit einem gemessenen Faktor aus zwei Peilungen, ein paar Wochen
    auseinander, ein paar Prozent, je nachdem, wie viel dazwischen verbraucht wurde und wie genau du peilst. Mit einem
    Ölzähler ist er gemessen. Das Attribut **Stufe** sagt, was davon zutrifft.

??? question "Der Verbrauch scheint zu hoch (oder zu niedrig). Was kann ich tun?"

    Peil jetzt alle Tanks, und in ein paar Wochen noch einmal an denselben Stellen. Der gemessene Faktor zeigt dann,
    wie weit er danebenliegt, und der Knopf **Gemessenen Faktor übernehmen** korrigiert ihn ab dann. Kennst du den
    Pumpendruck, trag ihn bis dahin ein: Er ist der häufigste Grund, warum eine Düse mehr verbrennt, als aufgedruckt
    ist.

??? question "Warum hat der Brenner einen Leistungssensor, und warum schwankt er?"

    Mit einer Leistungsmessung bekommt jede Komponente einen Sensor für ihre Leistung. Die Pumpen zeigen ihre typische
    Leistung; was die Messung darüber oder darunter liegt, geht an den Brenner, solange er läuft, weil sein Bedarf am
    meisten schwankt.

??? question "Eine Pumpe erscheint als laufend, obwohl sie steht."

    Ihre typische Leistung liegt vielleicht nahe an der einer anderen, oder an der Schwankung des Brenners. Vergleiche
    mit dem Verlauf der Leistungsmessung und setze in **Komponente bearbeiten** eine genauere Leistung. Ziehen zwei
    Komponenten fast gleich viel, meldet Fuel Ledger das unter Reparaturen: Es kann sie nicht unterscheiden.

??? question "Warum ist meine Energie nicht gesprungen, als ich den Heizwert geändert habe?"

    Mit Absicht. Ein neuer Heizwert, Preis, Faktor oder Wirkungsgrad gilt ab dem Moment, in dem er gesetzt wird. Was
    gezählt wurde, bleibt, also springt das Energie-Dashboard nie.

## Änderungen

??? question "Ich habe eine falsche Peilung oder Lieferung eingetragen."

    Löschen lässt sie sich noch nicht. Trag eine neue Peilung ein oder **Vorrat setzen** mit dem richtigen Wert: Das
    jüngste Ereignis bestimmt den Vorrat ab seinem Zeitpunkt.

??? question "Ich habe den Laufzeitzähler (oder die Messsteckdose) ersetzt."

    Wähle den neuen unter **Brenner und Düse**. Fuel Ledger zählt ihn ab seinem nächsten Wert; was gezählt wurde,
    bleibt. Einen Zähler, der wieder bei 0 anfängt, bemerkt es von selbst.

??? question "Kann ich später einen Tank ergänzen?"

    Ja, mit **Tank hinzufügen** auf der Seite der Integration. Sein Inhalt ist unbekannt, bis du ihn peilst oder den
    Vorrat neu setzt.

??? question "Wie entferne ich Fuel Ledger?"

    **Einstellungen → Geräte & Dienste → Fuel Ledger**, die drei Punkte, **Löschen**. Seine Sensoren und Geräte
    verschwinden, ihr Verlauf bleibt. Die Einträge im Energie-Dashboard entfernst du von Hand, es behält sie und meldet
    sie als fehlend. Danach Fuel Ledger im Marketplace entfernen: dort öffnen und **Deinstallieren** wählen.

## Hilfe

??? question "Etwas stimmt nicht. Was soll ich schicken?"

    [Eröffne ein Issue](https://github.com/benep/fuel_ledger/issues) und hänge die **Diagnosedaten** an: auf der Seite
    der Integration die drei Punkte, **Diagnosedaten herunterladen**. Sie enthalten deine Einrichtung, den aktuellen
    Zustand der Entitäten, die Fuel Ledger liest, und seine Bücher (Lieferungen, Peilungen, Zähler), sonst nichts.
