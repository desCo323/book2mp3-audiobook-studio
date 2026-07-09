# GitHub Pages aktivieren

Die GitHub-Page fuer dieses Projekt liegt in `docs/`.

## Aktivierung in GitHub

1. Repository auf GitHub oeffnen
2. `Settings`
3. `Pages`
4. Unter `Build and deployment` als Source `Deploy from a branch` waehlen
5. Branch `main` waehlen
6. Ordner `/docs` waehlen
7. Speichern

Danach veroeffentlicht GitHub die Seite aus:

- `docs/index.md`
- `docs/_config.yml`
- `docs/assets/*`

## Inhalt der Seite

- Projektueberblick
- Quickstarts
- Links zur technischen Doku
- Open-Source- und Release-Hinweise
- Bedienpfade fuer Profilstudio, Lexikon, Queue und fertige Hoerbuecher

## Automatischer Release-Workflow

Zusätzlich zur GitHub-Page gibt es einen Release-Workflow:

- Datei: `.github/workflows/portable-release.yml`
- Trigger: Push auf Branches, Pull Requests, Tags `v*` oder manueller Start
- Ergebnis bei jedem Lauf: GitHub-Actions-Artefakte fuer Linux und Windows
- Ergebnis bei Push auf `main`: rolling Pre-Release `continuous` mit Linux- und Windows-Portable
- Ergebnis bei Tag `v*`: versioniertes GitHub Release mit Linux- und Windows-Portable
- zusaetzlich: `.sha256`-Dateien und `SHA256SUMS.txt`

Die Release-Artefakte sind:

- `book2mp3-linux-portable.tar.gz`
- `book2mp3-windows-portable.zip`

Die Pages-Doku und der Release-Workflow sollten inhaltlich zusammenpassen:

- gleiche Produktbeschreibung
- gleiche Aussage zu `Piper` als Standardpfad
- gleiche Aussage zu `XTTS` als optionalem Zusatzpfad
