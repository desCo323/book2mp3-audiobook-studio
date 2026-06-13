# book2mp3 Audiobook Studio

Lokale Desktop-Software fuer die kontrollierte Erzeugung von MP3-Hoerbuechern aus `TXT`, `PDF` und `EPUB`.

![Workflow](assets/workflow-overview.svg)

## Was die Software macht

- analysiert Dokumente und erkennt Kapitelstrukturen
- verarbeitet Texte in wiederaufnahmefaehigen Chunks
- nutzt lokale TTS-Backends wie Piper und optional XTTS
- erzeugt Kapiteldateien, Zeitteile oder Gesamtdateien
- speichert Profile, Benchmark-Ergebnisse und Export-Metadaten

## Schnellstart

- [Projektbeschreibung](project-description.md)
- [Quickstart aus dem Quellcode](quickstart-source.md)
- [Quickstart: Erstes Hoerbuch erzeugen](quickstart-first-audiobook.md)
- [Quickstart: Portable Version](quickstart-portable.md)
- [GitHub Pages aktivieren](github-pages.md)

## Wichtige technische Doku

- [Architecture](architecture.md)
- [User Guide](user-guide.md)
- [Portable Distribution](portable-distribution.md)
- [Open-Source- und Release-Check](open-source-compliance.md)

## Release-Status

Der Quellcode ist veroeffentlichbar. Fuer eine saubere oeffentliche Bundle-Verteilung muessen aber weiterhin Lizenz- und Paketierungsregeln beachtet werden, besonders bei:

- `EbookLib`
- `XTTS-v2`
- `FFmpeg`
- gebuendelten Piper-Stimmen

Details: [Open-Source- und Release-Check](open-source-compliance.md)
