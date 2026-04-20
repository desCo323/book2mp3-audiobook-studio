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
  export PYTHONHOME="$APP_ROOT/python/linux"
  export PYTHONNOUSERSITE=1
  export PYTHONPATH="$APP_ROOT:$APP_ROOT/python/linux/lib/python3.13/site-packages${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"
fi

if [ -d "$APP_ROOT/python/linux/lib" ]; then
  export LD_LIBRARY_PATH="$APP_ROOT/python/linux/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

exec "$PYTHON_BIN" -m book2mp3.main "$@"
