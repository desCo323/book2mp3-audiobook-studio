#!/usr/bin/env sh
set -eu

APP_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="$APP_ROOT/python/linux/bin/python3"
USE_BUNDLED_PYTHON=1

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Portable Python runtime not found at:"
  echo "  $PYTHON_BIN"
  echo
  echo "This launcher is for the self-contained desktop bundle."
  echo "A finished release must include python/linux/ inside the app folder."
  echo "For development only, you can set BOOK2MP3_ALLOW_SYSTEM_PYTHON=1."
  echo
  if [ "${BOOK2MP3_ALLOW_SYSTEM_PYTHON:-0}" = "1" ]; then
    PYTHON_BIN="${PYTHON:-python3}"
    USE_BUNDLED_PYTHON=0
  else
    exit 1
  fi
fi

export BOOK2MP3_APP_ROOT="$APP_ROOT"
if [ "$USE_BUNDLED_PYTHON" = "1" ]; then
  export PYTHONHOME="$APP_ROOT/python/linux"
  export PYTHONNOUSERSITE=1
  export PYTHONPATH="$APP_ROOT/src:$APP_ROOT/python/linux/lib/python3.13/site-packages${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$APP_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
fi

if [ -d "$APP_ROOT/python/linux/lib" ]; then
  export LD_LIBRARY_PATH="$APP_ROOT/python/linux/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

exec "$PYTHON_BIN" -m book2mp3.main "$@"
