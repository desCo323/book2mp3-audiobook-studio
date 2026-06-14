# book2mp3 Audiobook Studio

Lokale Hörbuch-Produktion aus `TXT`, `PDF` und `EPUB` mit wiederaufnahmefähigen Aufträgen, Profilen, Benchmarking und sauberem MP3-Export.

![Workflow](assets/workflow-overview.svg)

> `book2mp3` ist kein Ein-Klick-Gimmick, sondern eine Produktionsoberfläche für längere Buchprojekte.  
> Die Software trennt bewusst zwischen Quelle, Analyse, Profilen, Testreihen, Queue und Export.

## Warum dieses Projekt

Viele TTS-Tools scheitern genau dort, wo echte Buchprojekte anfangen:

- lange Läufe brechen mittendrin ab
- Teilergebnisse gehen verloren
- Kapitel werden nicht sauber behandelt
- Stimme, Geschwindigkeit und Chunk-Größe lassen sich nicht reproduzierbar vergleichen

`book2mp3` löst das mit einer mehrstufigen Produktionslogik statt mit einem einzigen fragilen Gesamtdurchlauf.

## Produktüberblick

<table>
  <tr>
    <td width="33%">
      <h3>Wiederaufnahmefähig</h3>
      <p>Jobs, Kapitel und Chunks bleiben als Artefakte erhalten. Fehler lassen sich gezielt erneut anstellen.</p>
    </td>
    <td width="33%">
      <h3>Profilbasiert</h3>
      <p>Nur freigegebene Produktionsprofile gehen in echte Aufträge. Test- und Produktionslogik bleiben getrennt.</p>
    </td>
    <td width="33%">
      <h3>Offline zuerst</h3>
      <p>Piper läuft lokal, XTTS optional ebenfalls lokal. Queue, CLI und API sind für lokale Nutzung ausgelegt.</p>
    </td>
  </tr>
</table>

## So arbeitet die Software

![Pipeline](assets/processing-pipeline.svg)

## Drei Betriebsmodi

![Modi](assets/modes-overview.svg)

### GUI-Modus

Für den normalen Arbeitsfluss:

- `Neuer Auftrag`
- `Aufträge`
- `Fertige Bücher`
- `Produktionsprofile`
- `Benchmark-Studio`
- `XTTS-Profile`
- `Diagnose`

### XTTS-Lexikon-Workflow

Für XTTS-Namen und Autoren:

1. Autor im Hauptfenster oder bei `Fertige Bücher` eintragen
2. `Benchmark-Studio` öffnen
3. `Lexikon` klicken
4. XTTS-Aussprache-Regeln prüfen oder ergänzen
5. Preview hören und erst danach das Profil für Produktion nutzen

### CLI-Modus

Für Skripte und Batch-Läufe:

```bash
book2mp3-cli profiles
book2mp3-cli diagnostics
book2mp3-cli create /pfad/zum/buch.txt --profile-id roman_deutsch_standard
book2mp3-cli run-next
```

### API-Modus

Für lokale Integrationen:

```bash
book2mp3-cli serve --host 127.0.0.1 --port 8765
```

Danach sind Jobs, Profile, Diagnose und Quellenanalyse über die lokale REST-API ansprechbar.

## Screenshots

### Hauptfenster

![Hauptfenster](assets/screenshot-main-window.png)

### Auftragszentrale

![Auftragszentrale](assets/screenshot-jobs.png)

### XTTS-Profile

![XTTS-Profile](assets/screenshot-xtts-profiles.png)

### Benchmark-Studio

![Benchmark-Studio](assets/screenshot-benchmark-studio.png)

## Wichtige Funktionen

- Import von `TXT`, `PDF` und `EPUB`
- automatische Kapitelanalyse mit klarer Rückmeldung
- Ausgabe als Gesamtdatei, Kapiteldateien oder Zeitteile
- lokale Piper-Stimmen und optionaler XTTS-Pfad
- XTTS-Aussprache-Lexikon mit Autoren-, Figuren- und Namensvorschlägen
- Benchmarking von Varianten, Geschwindigkeit und Chunk-Größen
- Queue, Prioritäten und Wiederaufnahme
- `Fertige Bücher` für Öffnen, Metadatenpflege und Aufräumen
- `manifest.json` und `chapters.json` für nachvollziehbare Exporte
- lokaler GUI-, CLI- und API-Betrieb mit gemeinsamem Kern

## Schnellstart

- [Projektbeschreibung](project-description.md)
- [Quickstart aus dem Quellcode](quickstart-source.md)
- [Quickstart: Erstes Hörbuch erzeugen](quickstart-first-audiobook.md)
- [Quickstart: Portable Version](quickstart-portable.md)

## Technische und rechtliche Hinweise

- [Architecture](architecture.md)
- [User Guide](user-guide.md)
- [Portable Distribution](portable-distribution.md)
- [Open-Source- und Release-Check](open-source-compliance.md)
- [GitHub Pages aktivieren](github-pages.md)

## Veröffentlichungsstatus

Der Quellcode ist veröffentlichbar. Für ein öffentliches Release-Bundle müssen aber weiterhin die Lizenzen und Beipackpflichten der Drittkomponenten beachtet werden, besonders bei:

- `EbookLib`
- `XTTS-v2`
- `FFmpeg`
- gebündelten Piper-Stimmen

Details: [Open-Source- und Release-Check](open-source-compliance.md)
