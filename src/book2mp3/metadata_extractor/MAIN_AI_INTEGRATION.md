# Main AI Integration Guide

Diese Datei ist die direkte Einbauanleitung für eine andere AI, die `book2mp3` um die neue Metadaten-Teilsoftware erweitern soll.

Wichtig:

- Diese Teilsoftware wurde absichtlich isoliert unter `src/book2mp3/metadata_extractor/` gebaut.
- Die Hauptsoftware wurde dabei nicht verändert.
- Die Integrations-AI soll die bestehende Metadatenlogik auf diese Teilsoftware umstellen, statt parallele neue Heuristiken in der Hauptsoftware zu duplizieren.

## Ziel

Die Hauptsoftware soll für `PDF`, `EPUB` und `TXT` automatisch möglichst zuverlässige Buchmetadaten finden und sie später in die fertigen MP3s übernehmen.

Mindestens übernehmen:

- `title`
- `author`
- `genre`
- `language`
- `comment`

Wenn möglich zusätzlich übernehmen:

- `publisher`
- `year`
- `subject`
- `isbn`
- weitere `identifiers`

## Einstiegspunkte

Benutze nur diese öffentlichen APIs:

```python
from pathlib import Path

from book2mp3.metadata_extractor import extract_metadata_from_source
```

Hauptaufruf:

```python
result = extract_metadata_from_source(
    source_path,
    allow_online=True,
    cache_path=paths.workspace / "statistics" / "metadata_online_cache.json",
)
```

Direkte Ergebniszugriffe:

```python
result.guessed_metadata()
result.extended_book_metadata()
result.mp3_transfer_payload(narrator="")
result.to_dict()
```

## Was Zurückkommt

### `result.guessed_metadata()`

Das ist der kompatible Payload für die heutige `AudiobookMetadata`-Struktur:

```python
{
    "title": ...,
    "album": ...,
    "artist": ...,
    "album_artist": ...,
    "narrator": ...,
    "author": ...,
    "genre": ...,
    "language": ...,
    "comment": ...,
}
```

### `result.extended_book_metadata()`

Das ist die erweiterte Buchsicht:

```python
{
    "publisher": ...,
    "year": ...,
    "identifiers": [...],
    "subjects": [...],
    "confidence": ...,
    "title_source": ...,
    "author_source": ...,
    "source_path": ...,
}
```

### `result.mp3_transfer_payload()`

Das ist die empfohlene Brücke in den MP3-Export:

```python
{
    "core_metadata": {...},
    "ffmetadata_tags": {...},
    "extended_book_metadata": {...},
}
```

## Minimaler Einbau

Wenn nur der bestehende Vorschlags-Flow ersetzt werden soll:

1. In `service.py` die bisherige Dateinamen-Logik nicht mehr direkt verwenden.
2. Stattdessen `extract_metadata_from_source(...)` aufrufen.
3. `result.guessed_metadata()` als bisherigen Vorschlag zurückgeben.
4. `result.confidence`, `title_source`, `author_source`, `candidates`, `online_results`, `online_errors` an UI/API weiterreichen.

Empfohlener Ersatz für die bisherige Vorschlagsfunktion:

```python
from pathlib import Path

from book2mp3.metadata_extractor import extract_metadata_from_source


def suggest_book_metadata(paths, source_path: str | Path) -> dict:
    result = extract_metadata_from_source(
        source_path,
        allow_online=True,
        cache_path=paths.workspace / "statistics" / "metadata_online_cache.json",
    )
    return {
        "guessed": result.guessed_metadata(),
        "confidence": result.confidence,
        "title_source": result.title_source,
        "author_source": result.author_source,
        "candidates": [item.to_dict() for item in result.candidates],
        "online_results": result.online_results,
        "online_errors": result.online_errors,
        "extended_book_metadata": result.extended_book_metadata(),
        "mp3_transfer": result.mp3_transfer_payload(),
    }
```

## Voller Einbau In Die Hauptsoftware

### 1. Metadatenvorschlag in `Book2Mp3Service`

Die aktuelle Metadatenvorschlagsroute soll auf das neue Modul umgestellt werden.

Empfehlung:

- Ersetze reine Dateinamenvorschläge.
- Lasse das neue Modul für `metadata_suggestions(...)` die Wahrheit liefern.

### 2. UI-Vorschlag

Bei Metadatenvorschlag im UI:

- `result.guessed_metadata()` in die Standardfelder schreiben
- `result.confidence` anzeigen
- `result.title_source` und `result.author_source` als Diagnose anzeigen
- bei niedriger Confidence die Kandidatenliste anzeigen

Empfohlene Confidence-Regeln:

- `>= 0.80`: automatisch vorbefüllen
- `0.55 - 0.79`: vorbefüllen, aber sichtbar als unsicher markieren
- `< 0.55`: nicht blind übernehmen, Kandidaten anzeigen

### 3. Job-Erstellung

Wenn ein Job angelegt wird, soll die Hauptsoftware mindestens diese Felder aus `core_metadata` in `AudiobookMetadata` schreiben:

- `title`
- `album`
- `artist`
- `album_artist`
- `narrator`
- `author`
- `genre`
- `language`
- `comment`

### 4. MP3-Tagging

Beim finalen Tag-Schritt zusätzlich `ffmetadata_tags` verwenden.

Heute kann die Hauptsoftware bereits ein allgemeines Metadaten-Dict an FFmpeg geben. Nutze dafür:

```python
transfer = result.mp3_transfer_payload(narrator=resolved_narrator)
ffmetadata_tags = transfer["ffmetadata_tags"]
```

Mindestens diese FFmpeg-Tags übernehmen:

- `title`
- `album`
- `artist`
- `album_artist`
- `author`
- `genre`
- `language`
- `comment`
- `description`
- `publisher`
- `date`
- `year`
- `subject`
- `isbn`

Wenn die aktuelle Modellstruktur noch nicht alle Felder dauerhaft speichert:

- `core_metadata` in `AudiobookMetadata`
- `extended_book_metadata` zusätzlich in `manifest.json` oder separater Job-Metadatenstruktur persistieren

## Empfohlenes Mapping

### In die bestehende `AudiobookMetadata`

```python
core = result.mp3_transfer_payload(narrator=narrator)["core_metadata"]
```

Direktes Mapping:

- `title -> title`
- `album -> album`
- `artist -> artist`
- `album_artist -> album_artist`
- `narrator -> narrator`
- `author -> author`
- `genre -> genre`
- `language -> language`
- `comment -> comment`

### In FFmpeg / MP3 Export

```python
tags = result.mp3_transfer_payload(narrator=narrator)["ffmetadata_tags"]
```

Diese Tags sind für den Audio-Export gedacht, nicht zwingend für die UI-Form.

## Online-Verhalten

`allow_online=True` ist sinnvoll für:

- Vorschlag auf Knopfdruck
- Finalisierung
- hochwertige Importläufe

`allow_online=False` ist sinnvoll für:

- Offline-Modus
- Smoke-Tests
- reproduzierbare Regressionstests

Wichtig:

- Online-Treffer dürfen gute EPUB-Container-Metadaten nicht blind überschreiben.
- Das Modul handhabt das intern bereits defensiv.
- Die Hauptsoftware soll Online-Fehler nicht als Hard-Failure behandeln.

## Cache

Nutze immer einen persistenten Cachepfad:

```python
paths.workspace / "statistics" / "metadata_online_cache.json"
```

Nicht bei jedem UI-Refresh neue Online-Suchen auslösen.

## Nicht Tun

- Nicht parallel eigene neue Dateinamen-Heuristiken in `service.py` oder `main_window.py` bauen.
- Nicht wieder direkt nur `guess_metadata_from_filename(...)` nutzen, wenn das neue Modul verfügbar ist.
- Nicht `online_results[0]` blind übernehmen.
- Nicht Confidence ignorieren.
- Nicht die Hauptsoftware so ändern, dass Metadatensuche bei jeder Kleinigkeit automatisch das Netz nutzt.

## Tests Nach Einbau

Nach Integration in die Hauptsoftware mindestens diese Läufe erneut ausführen:

```bash
PYTHONPATH=src python3 -m book2mp3.metadata_extractor evaluate /home/codex/repo/book2mp3/EBOOKS --offline
PYTHONPATH=src python3 -m book2mp3.metadata_extractor evaluate /home/codex/repo/book2mp3/EBOOKS --offline --suffix .epub
```

Zusätzlich UI/CLI/API-Smokes anpassen, sobald die Hauptsoftware wirklich umgestellt wurde.

## Bekannte Stärken

- EPUB rekursiv über den Bestand sehr stark
- viele PDFs werden über Frontmatter plus Sidecar-TXT deutlich besser erkannt
- ISBN/Publisher/Jahr können bei EPUB und Online-Treffern übernommen werden

## Bekannte Schwächen

- manche Fach-PDFs mit mehreren Herausgebern
- OCR-/Shop-TXT mit viel Werbetext
- einzelne Fanfic-Dateinamen mit ungewöhnlichen Alias-Trennungen

Diese Fälle sind kein Grund, das Modul zu umgehen. Nutze stattdessen Confidence und Kandidatenliste.

## Kurzform Für Die Integrations-AI

Wenn du nur eine schnelle präzise Einbauanweisung brauchst:

1. Importiere `extract_metadata_from_source`.
2. Ersetze den bisherigen Vorschlagsweg durch dieses Modul.
3. Verwende `result.guessed_metadata()` für bestehende Kernfelder.
4. Verwende `result.mp3_transfer_payload()` für MP3-Tags.
5. Persistiere `extended_book_metadata` zusätzlich, wenn du mehr als die alte Kernstruktur behalten willst.
