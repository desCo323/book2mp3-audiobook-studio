# Anforderungen `book2mp3` V1

## Zielbild

`book2mp3` ist eine lokal betriebene Hörbuch-Produktionssoftware für `TXT`, `PDF` und `EPUB`.
Sie soll aus langen Texten wiederaufnahmefähige, verwaltbare und qualitativ nachvollziehbare
MP3-Hörbücher erzeugen.

Die Software muss denselben Kern über drei Zugänge nutzbar machen:

- Desktop-GUI für geführtes Arbeiten
- CLI für Headless-Automatisierung
- lokale REST-API für Dienstbetrieb und Integrationen

## Kernanforderungen

### 1. Auftragsmodell

- Jeder Auftrag ist persistent und liegt vollständig in einem eigenen Arbeitsordner.
- Jeder Auftrag ist in Stufen organisiert:
  `Import -> Extraktion -> Bereinigung -> Chunking -> Vorschau/Modellauswahl -> Synthese -> Assemblierung -> Metadaten -> Export`.
- Jede Stufe muss separat sichtbar, prüfbar und erneut ausführbar sein.
- Unterbrechungen dürfen nur den aktuell laufenden Teilschritt betreffen; abgeschlossene Artefakte bleiben erhalten.
- Aufträge müssen priorisierbar, warteschlangenfähig, löschbar und wiederaufnehmbar sein.

### 2. Textverarbeitung

- `TXT`, `PDF` und `EPUB` werden importiert.
- Extrahierter Text wird normalisiert und als Artefakt gespeichert.
- Text wird in stabile Chunks zerlegt; die Chunk-Dateien bleiben sichtbar.
- Die Zerlegung muss reproduzierbar sein.
- Für `EPUB` müssen Kapitelstrukturen auslesbar bleiben.
- Für `PDF` und `TXT` sind heuristische Kapitelmarker vorzusehen; falls nicht möglich, bleibt mindestens eine stabile Abschnittsstruktur erhalten.

### 3. Stimmen, Modelle und Vergleich

- `Piper` ist der robuste lokale Standardpfad.
- `XTTS` ist der optionale Qualitäts- und Profilpfad.
- Nutzer müssen Stimmen/Modelle anhand realer Vorschauen vergleichen können.
- Nutzbare Kombinationen aus Stimme, Backend und Sprechparametern müssen speicherbar sein.
- Die Software soll Empfehlungen für sinnvolle Startwerte geben.
- Modell- und Stimmprofile müssen für spätere Aufträge wiederverwendbar sein.

### 4. Audioerzeugung

- Synthese erfolgt chunk-basiert.
- Bereits fertige Chunks werden beim Wiederaufnehmen übersprungen.
- Fehlerhafte Chunks müssen selektiv zurücksetzbar und erneut ausführbar sein.
- Der Export unterstützt:
  - einzelne Segmentdateien
  - zeitbasierte Teile
  - eine Gesamtdatei
- Die Exportartefakte müssen durch Manifestdateien beschrieben werden.

### 5. Metadaten und Exportqualität

- Exportierte MP3-Dateien müssen saubere ID3-Metadaten erhalten.
- Pflichtfelder:
  `title`, `album`, `artist/narrator`, `genre`, `language`, `comment`, `track`.
- Jeder Export erzeugt zusätzlich:
  - `manifest.json`
  - `chapters.json`
- Die Metadaten müssen so geschrieben werden, dass Standard-Player Hörbuchdateien konsistent einordnen.

### 6. Headless und Integration

- Alle Kernfunktionen müssen ohne GUI nutzbar sein.
- CLI und API verwenden denselben Kern wie die Desktop-Anwendung.
- Die lokale API läuft standardmäßig nur auf `127.0.0.1`.
- Die API dient v1 als lokaler Automatisierungs- und Dienstzugang, nicht als öffentlicher Mehrnutzer-Dienst.

## Bedienkonzept

### GUI

- Die GUI bleibt desktop-first.
- Die primäre Struktur ist:
  - neuer Auftrag
  - Auftragsdetails
  - Warteschlange
  - Stimmen/Modelle
  - Laufzeit/Diagnose
- Der Auftragseinstieg ist geführt.
- Detailansichten zeigen Artefakte, Stufenstatus, Logs und Exporte klar getrennt.
- Begriffe müssen konsistent deutschsprachig und produktnah sein.

### CLI

- Die CLI muss mindestens folgende Fälle abdecken:
  - Auftrag anlegen
  - Jobs auflisten
  - Job inspizieren
  - Job ausführen
  - nächsten Queue-Job ausführen
  - Job erneut einreihen
  - Chunks für Retry zurücksetzen
  - lokale API starten

### API

- Die lokale API muss mindestens folgende Endpunkte bereitstellen:
  - `GET /health`
  - `GET /jobs`
  - `POST /jobs`
  - `GET /jobs/{id}`
  - `POST /jobs/{id}/enqueue`
  - `POST /jobs/{id}/run`
  - `POST /jobs/{id}/retry`
  - `GET /voices`
  - `GET /presets`

## Nichtziele für V1

- Kein Cloud-TTS als Kernfunktion
- Kein öffentlicher Netzwerkbetrieb
- Kein Multi-User-Rechtesystem
- Kein monolithischer Ein-Klick-Job ohne sichtbare Zwischenstufen

## Qualität und Tests

- Für Kernlogik, CLI und API sind automatisierte Tests Pflicht.
- UI-Smoke-Tests decken die wichtigsten Arbeitswege ab.
- Exporttests müssen erzeugte MP3-Dateien und Manifestdaten validieren.
- Dokumentation ist Teil der Definition of Done.

## Migrations- und Kompatibilitätsvorgaben

- Bestehende `state.json`-Aufträge müssen weiter lesbar bleiben.
- Die bestehende GUI darf durch die Einführung von CLI und API nicht unbrauchbar werden.
- Das Referenzverzeichnis `ebooksp/` bleibt erhalten.
