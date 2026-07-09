# Release Checklist

This checklist is the practical go/no-go guide before presenting `book2mp3` as a portable end-user release.

## 1. Core product checks

- `TXT`, `PDF`, and `EPUB` import work
- multiple source selection creates multiple jobs
- chapter detection clearly enables/disables chapter-per-file export
- only approved production profiles can create jobs
- active jobs and finished audiobooks are separated in the UI
- per-job ETA and combined queue ETA are visible
- metadata can be edited both before synthesis and after completion

## 2. Runtime and recovery checks

- Piper works immediately in the portable build
- XTTS remains optional and does not block normal app startup
- XTTS setup can be launched from the bundle and from inside the app
- missing/broken XTTS runtime leads to recovery or blocked state, not silent loops
- resume/restart reconciles chunk artifacts correctly
- loop detection creates a structured failure instead of endless retries

## 3. UI checks

- main window is usable on `1366x768`
- benchmark studio is scrollable and usable on `1366x768`
- XTTS profile studio is scrollable and usable on `1366x768`
- job list stays readable with many active jobs
- finished audiobooks are easy to open, inspect, retag and delete

## 4. Language checks

- UI starts in system language when supported, otherwise English
- settings allow switching between English, German, Spanish and Portuguese
- queue filter labels translate correctly
- diagnostics, XTTS setup and finished-book metadata flow are understandable in English
- German, English, Spanish and Portuguese Piper voice coverage is visible in diagnostics

## 5. Portable build checks

- bundle contains `START_HERE.md`
- bundle contains app-local Python runtime(s)
- Linux download contains Linux Piper runtime
- Windows download contains Windows Piper runtime
- downloads contain the compact multilingual Piper release voice pack
- downloads contain XTTS starter speaker profiles so `Standard XTTS` can be created automatically
- bundle contains `finalbooks/` for copied completed audiobook exports
- bundle starts through `start.sh` / `start.bat`
- users do not need to install Python manually
- bundle checker passes:

```bash
python scripts/check_portable_bundle.py /path/to/bundle
```

## 6. Release communication checks

- README matches the real product state
- GitHub Pages landing page matches the current UI and workflow names
- portable distribution docs match the real bundle layout
- GitHub Actions expose Linux and Windows downloads as workflow artifacts
- Pushes to `main` update the rolling `continuous` GitHub pre-release
- Tags named `v*` create versioned GitHub releases
- release assets include `SHA256SUMS.txt`
- XTTS is clearly described as optional
- XTTS lexicon workflow is documented and reachable from the docs
- XTTS licensing is not presented as solved
- compliance docs are shipped with the release

## 7. What is still not automatically solved

- real Windows end-to-end validation still requires a real Windows machine
- XTTS model licensing remains a separate publication constraint
- `EbookLib` remains a release/compliance concern until replaced or explicitly accepted
