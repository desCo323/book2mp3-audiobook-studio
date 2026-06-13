#!/usr/bin/env sh
set -eu

APP_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="$APP_ROOT/python/linux/bin/python3"
USE_BUNDLED_PYTHON=1

if [ ! -x "$PYTHON_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="${PYTHON:-python3}"
    USE_BUNDLED_PYTHON=0
    echo "Portable Python runtime not found at:"
    echo "  $APP_ROOT/python/linux/bin/python3"
    echo "Falling back to system Python for this local checkout."
  else
    echo "Portable Python runtime not found at:"
    echo "  $PYTHON_BIN"
    echo
    echo "This launcher expects src/ itself to be the portable app folder."
    echo "A finished src bundle must include python/linux/ inside src/."
    echo "No usable system python3 was found for fallback."
    echo
    exit 1
  fi
fi

export BOOK2MP3_APP_ROOT="$APP_ROOT"
if [ "$USE_BUNDLED_PYTHON" = "1" ]; then
  PYTHON_EXTRA_PATHS="$APP_ROOT"
  for candidate in \
    "$APP_ROOT"/python/linux/lib/python*/dist-packages \
    "$APP_ROOT"/python/linux/lib/python*/site-packages \
    "$APP_ROOT"/python/linux/local/lib/python*/dist-packages
  do
    if [ -d "$candidate" ]; then
      PYTHON_EXTRA_PATHS="${PYTHON_EXTRA_PATHS}:$candidate"
    fi
  done
  export PYTHONHOME="$APP_ROOT/python/linux"
  export PYTHONNOUSERSITE=1
  export PYTHONPATH="${PYTHON_EXTRA_PATHS}${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"
fi

if [ -d "$APP_ROOT/python/linux/lib" ]; then
  export LD_LIBRARY_PATH="$APP_ROOT/python/linux/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

if [ "${1:-}" = "--install-xtts" ]; then
  XTTS_SETUP_SCRIPT=""
  for candidate in "$APP_ROOT/scripts/setup_xtts_runtime.py" "$APP_ROOT/../scripts/setup_xtts_runtime.py"
  do
    if [ -f "$candidate" ]; then
      XTTS_SETUP_SCRIPT="$candidate"
      break
    fi
  done
  if [ -z "$XTTS_SETUP_SCRIPT" ]; then
    echo "XTTS-Setup-Skript nicht gefunden."
    exit 1
  fi
  XTTS_RUNTIME_ROOT="$APP_ROOT/runtime/xtts/linux"
  if [ ! -d "$APP_ROOT/runtime" ] && [ -d "$APP_ROOT/../runtime" ]; then
    XTTS_RUNTIME_ROOT="$APP_ROOT/../runtime/xtts/linux"
  fi
  echo "Starte optionalen XTTS-Setup unter:"
  echo "  $XTTS_RUNTIME_ROOT"
  exec "$PYTHON_BIN" "$XTTS_SETUP_SCRIPT" "$XTTS_RUNTIME_ROOT" --bootstrap-linux-standalone --torch-variant auto
fi

exec "$PYTHON_BIN" -m book2mp3.main "$@"
