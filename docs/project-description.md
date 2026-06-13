# Projektbeschreibung

`book2mp3 Audiobook Studio` ist eine lokale Desktop-Software zur schrittweisen Umwandlung von `TXT`, `PDF` und `EPUB` in MP3-Hoerbuecher.

![Workflow-Überblick](assets/workflow-overview.svg)

## Ziel

Die Software soll lange Textquellen nicht in einem fragilen Einzeldurchlauf, sondern in kontrollierbaren Arbeitsschritten verarbeiten:

1. Datei importieren
2. Text extrahieren
3. Kapitel erkennen
4. Text in stabile Chunks zerlegen
5. Stimme oder Sprecherprofil waehlen
6. Vorschauen, Benchmarks und Tuning durchfuehren
7. Audio stufenweise erzeugen
8. Kapiteldateien oder Gesamtdatei exportieren

## Kernfunktionen

- lokale Verarbeitung ohne Cloud-Zwang
- wiederaufnahmefaehige Auftraege mit Queue und Statusverwaltung
- Produktionsprofile mit Freigabestatus `draft`, `tested`, `approved`, `archived`
- Benchmark-Studio fuer Stimmenvergleich, Geschwindigkeitsmessung und Chunk-Tuning
- optionaler XTTS-Pfad fuer Sprecherprofile
- echte Kapitel-/Chunk-Artefakte mit Retry und Exportkontrolle
- `manifest.json` und `chapters.json` fuer nachvollziehbare Exporte
- CLI und lokale API fuer headless Nutzung

## Zielgruppen

- Anwender, die offline Hoerbuecher aus eigenen Dokumenten erzeugen wollen
- Nutzer mit langen Buchprojekten, die Wiederaufnahme und Fehlerkontrolle brauchen
- Power-User, die Profile, Queue und TTS-Backends reproduzierbar steuern wollen

## Architekturbild

- `src/book2mp3/`: Kernlogik, GUI, CLI, API
- `workspace/`: Jobs, Profile, Logs, Vorschauen
- `voices/`: lokale Piper-Stimmen
- `runtime/`: lokale TTS-Runtimes
- `docs/`: Benutzer-, Release- und Compliance-Dokumentation

## Produktstatus

Die Software ist deutlich ueber den Prototypstatus hinaus, aber fuer eine saubere oeffentliche Release-Verteilung gelten noch Lizenz- und Paketierungsbedingungen. Der aktuelle Stand dazu ist in [Open-Source- und Release-Check](open-source-compliance.md) dokumentiert.
