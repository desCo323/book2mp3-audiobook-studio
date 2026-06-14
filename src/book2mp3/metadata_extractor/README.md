# Metadata Extractor

Dieses Paket ist absichtlich als eigenständige Teilsoftware gebaut und greift die Hauptsoftware nicht direkt an.

## Ziel

Aus `PDF`, `EPUB` und `TXT` möglichst zuverlässig:

- `title`
- `author`
- optional `language`
- optional `genre`
- optional `publisher`
- optional `year`
- optionale `identifiers` wie ISBN
- optionale `subjects` / Schlagwörter
- optional `comment`

automatisch extrahieren, damit die Hauptsoftware diese Werte später in MP3-Tags übernehmen kann.

## Öffentliche Einstiegspunkte

Programmgesteuert:

```python
from pathlib import Path

from book2mp3.metadata_extractor import extract_metadata_from_source

result = extract_metadata_from_source(
    Path("/pfad/zum/buch.pdf"),
    allow_online=True,
    cache_path=Path("workspace/statistics/metadata_online_cache.json"),
)

metadata = result.guessed_metadata()
transfer = result.mp3_transfer_payload(narrator="Gewünschter Sprechername")
```

Direkt als Modul:

```bash
PYTHONPATH=src python3 -m book2mp3.metadata_extractor extract /pfad/zum/buch.pdf
PYTHONPATH=src python3 -m book2mp3.metadata_extractor extract /pfad/zum/buch.pdf --offline
PYTHONPATH=src python3 -m book2mp3.metadata_extractor evaluate /home/codex/repo/book2mp3/EBOOKS --offline
PYTHONPATH=src python3 -m book2mp3.metadata_extractor lexicon-validate
PYTHONPATH=src python3 -m book2mp3.metadata_extractor lexicon-scan /home/codex/Schreibtisch/books --suffix .epub
PYTHONPATH=src python3 -m book2mp3.metadata_extractor lexicon-rules
```

## Ergebnisformat

`extract_metadata_from_source(...)` liefert ein `MetadataExtractionResult` mit:

- `title`
- `author`
- `language`
- `genre`
- `publisher`
- `year`
- `identifiers`
- `subjects`
- `comment`
- `confidence`
- `title_source`
- `author_source`
- `candidates`
- `online_results`
- `online_errors`

`result.guessed_metadata()` liefert ein direkt MP3-taugliches Dict:

- `title`
- `album`
- `artist`
- `album_artist`
- `narrator`
- `author`
- `genre`
- `language`
- `comment`

`result.mp3_transfer_payload(...)` liefert die spätere Hauptsoftware-Übergabe:

- `core_metadata`
- `ffmetadata_tags`
- `extended_book_metadata`

## Globales Lexikon

Zusätzlich liegt unter:

- `src/book2mp3/metadata_extractor/global_book_lexicon.json`

ein globales, editierbares Autoren-/Buch-/Figurenlexikon.

Ziel des Lexikons:

- schwierige Namen zentral pflegen
- spätere UI-Autovervollständigung ermöglichen
- XTTS-Ausspracheregeln reproduzierbar aus Daten erzeugen
- lokale Bücher gegen bekannte Figuren prüfen

Programmgesteuert:

```python
from book2mp3.metadata_extractor import (
    build_pronunciation_rules,
    build_xtts_profile_patch,
    load_global_lexicon,
    scan_books_for_lexicon,
    validate_global_lexicon,
)

lexicon = load_global_lexicon()
report = validate_global_lexicon()
rules = build_pronunciation_rules(lexicon)
coverage = scan_books_for_lexicon("/home/codex/Schreibtisch/books", suffixes={".epub"})
```

CLI:

```bash
PYTHONPATH=src python3 -m book2mp3.metadata_extractor lexicon-validate
PYTHONPATH=src python3 -m book2mp3.metadata_extractor lexicon-scan /home/codex/Schreibtisch/books --suffix .epub
PYTHONPATH=src python3 -m book2mp3.metadata_extractor lexicon-rules
```

Das Lexikon ist bewusst datengetrieben:

- `book_title_aliases` steuern die Buchzuordnung
- `characters[].aliases` steuern die Buchabdeckungstests
- `characters[].spoken_as` plus `use_for_xtts=true` steuern die XTTS-Regeln
- `characters[].sources` dokumentieren, woher der Eintrag stammt

## Interne Strategie

Die Extraktion ist mehrstufig:

1. Pfad-/Dateinamen-Heuristiken
2. Elternordner-/Großelternordner-Hinweise
3. EPUB-Container-Metadaten (`dc:title`, `dc:creator`, Sprache, Subjects)
4. PDF-Info-Metadaten
5. Frontmatter-Analyse aus PDF/TXT
6. Konsens-Boost über mehrere Kandidaten
7. PDF-Sidecar-Analyse über benachbarte `.txt`-Dateien im selben Ordner
8. optionale Online-Anreicherung über `Open Library` und `Google Books`

Wichtige Designregel:

- Offline-Signale werden zuerst gesammelt.
- Online-Daten dürfen fehlende Felder ergänzen oder bei starker Übereinstimmung bestätigen.
- Online-Daten dürfen schwache Offline-Felder verbessern, aber nicht blind überschreiben.

## Einbau Für Die Haupt-AI

Wenn die Haupt-AI diese Teilsoftware später einbindet, dann in genau dieser Reihenfolge:

1. `extract_metadata_from_source(source_path, allow_online=True, cache_path=...)` aufrufen.
2. `result.confidence` prüfen.
3. Bei hoher Confidence (`>= 0.80`) `result.guessed_metadata()` direkt als Vorschlag übernehmen.
4. Bei mittlerer Confidence (`0.55 - 0.79`) die Felder als editierbaren Vorschlag anzeigen.
5. Bei niedriger Confidence (`< 0.55`) die Kandidatenliste `result.candidates` als Diagnose/Review anzeigen.

Empfohlene Integration in die Hauptsoftware:

```python
from pathlib import Path

from book2mp3.metadata_extractor import extract_metadata_from_source

def suggest_book_metadata(source_path: str | Path, cache_path: Path):
    result = extract_metadata_from_source(
        source_path,
        allow_online=True,
        cache_path=cache_path,
    )
    transfer = result.mp3_transfer_payload()
    return {
        "guessed": result.guessed_metadata(),
        "transfer": transfer,
        "confidence": result.confidence,
        "title_source": result.title_source,
        "author_source": result.author_source,
        "candidates": [item.to_dict() for item in result.candidates],
        "online_results": result.online_results,
        "online_errors": result.online_errors,
    }
```

Wenn die Hauptsoftware die MP3-Tags schreibt, sollte sie mindestens diese Felder übernehmen:

- `title`
- `album`
- `author`
- `genre`
- `language`
- `comment`

Wenn FFmpeg- oder ID3-Tags erweitert werden können, zusätzlich aus `transfer["ffmetadata_tags"]`:

- `publisher`
- `date` / `year`
- `subject`
- `isbn`
- `artist`
- `album_artist`
- `description`

## Was Die Haupt-AI Nicht Tun Soll

- Nicht direkt nur den Dateinamen nehmen, wenn dieses Modul verfügbar ist.
- Nicht Online-Treffer ungeprüft über gute Container-Metadaten legen.
- Nicht bei jeder UI-Aktualisierung Online-Suchen auslösen.
- Nicht dieselben Online-Suchen ohne Cache wiederholen.

## Evaluationsmodus

Für große Bestände ist der eingebaute Evaluator gedacht:

```bash
PYTHONPATH=src python3 -m book2mp3.metadata_extractor evaluate /home/codex/repo/book2mp3/EBOOKS --offline
PYTHONPATH=src python3 -m book2mp3.metadata_extractor evaluate /home/codex/repo/book2mp3/EBOOKS --offline --suffix .epub
```

Der Evaluator erzeugt:

- echte Dateitests gegen den Korpus
- zusätzliche Dateinamen-Regressionsfälle
- insgesamt deutlich über 2000 Testfälle auf Basis des vorhandenen Bestands

## Standgrenzen

Besonders schwierig bleiben:

- fachliche Springer-PDFs mit Herausgeberblöcken vor dem eigentlichen Titel
- OCR-/Shop-TXT-Dateien mit langen Werbetexten vor den bibliografischen Daten
- gemischte Mehrautoren-/Herausgeberfälle
- fehlerhafte oder mojibake-haltige Quelldaten

Trotzdem ist das Modul so gebaut, dass es bei schwachen Quellen nicht still rät, sondern Confidence und Kandidaten offenlegt.
