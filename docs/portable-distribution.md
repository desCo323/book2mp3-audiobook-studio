# Portable Distribution

This document defines what the real end-user bundle must look like.

## Requirement

The user must get a folder or zip archive that works without:

- installing Python
- installing pip packages
- installing local build tools
- manually configuring TTS runtimes

The application must be startable directly with:

- `start.sh` on Linux
- `start.bat` on Windows

## Required bundle layout

```text
book2mp3/
  start.sh
  start.bat
  src/
  runtime/
  voices/
  workspace/
  THIRD_PARTY_NOTICES.md
  python/
    linux/
      bin/python3
      ...
    windows/
      python.exe
      ...
```

## Runtime strategy

### Windows

Use the official Python embeddable package from Python.org for Windows bundles.

Current official Python sources indicate that Windows embeddable packages are published as part of Python releases.

### Linux

Use a redistributable standalone Python build for Linux bundles.

The practical target is a relocatable app-local Python folder inside the bundle. The launcher then runs that local interpreter instead of requiring system Python.

### GUI deployment

For the desktop app itself, Qt currently documents `pyside6-deploy` as the official deployment path for PySide6 desktop applications.

## Current repo status

This repository now includes:

- `start.sh`
- `start.bat`
- `scripts/check_portable_bundle.py`

These launchers already target the final portable structure and intentionally fail if the bundle-local Python runtime is missing.

Portable releases should also preserve:

- `THIRD_PARTY_NOTICES.md`
- voice `MODEL_CARD` files
- upstream runtime license files where available

For development only, they can fall back to a system Python when `BOOK2MP3_ALLOW_SYSTEM_PYTHON=1` is set.

## Validation

To verify that a built release folder has the expected structure:

```bash
python scripts/check_portable_bundle.py /path/to/bundle
```

## Sources

- Qt for Python deployment docs: https://doc.qt.io/qtforpython-6.8/deployment/deployment-pyside6-deploy.html
- Python Windows embeddable distribution docs: https://docs.python.org/3.10/using/windows.html
- Python Windows release pages listing embeddable packages: https://www.python.org/downloads/windows/
