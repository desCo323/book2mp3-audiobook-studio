#!/usr/bin/env sh
set -eu

APP_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHONPATH_ENTRY="$APP_ROOT/src"
if [ -d "$APP_ROOT/book2mp3" ]; then
  PYTHONPATH_ENTRY="$APP_ROOT"
fi
USE_BUNDLED_PYTHON=1
PYTHON_RUNTIME_ROOT=""

for candidate in "$APP_ROOT/python/linux" "$APP_ROOT/src/python/linux"
do
  if [ -x "$candidate/bin/python3" ]; then
    PYTHON_RUNTIME_ROOT="$candidate"
    break
  fi
done

PYTHON_BIN="${PYTHON_RUNTIME_ROOT:+$PYTHON_RUNTIME_ROOT/bin/python3}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Portable Python runtime not found."
  echo "Checked these locations:"
  echo "  $APP_ROOT/python/linux/bin/python3"
  echo "  $APP_ROOT/src/python/linux/bin/python3"
  echo
  echo "This launcher supports both the finished bundle layout and the current source checkout."
  echo "A finished release must include python/linux/ inside the app folder."
  echo "The current repository layout expects src/python/linux/."
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
RUN_TIMESTAMP="$(date +%Y%m%dT%H%M%S 2>/dev/null || printf 'run')"
LAUNCHER_STARTED_AT_NS="$(date +%s%N 2>/dev/null || printf '%s000000000' "$(date +%s)")"
export BOOK2MP3_LAUNCHER_STARTED_AT_NS="$LAUNCHER_STARTED_AT_NS"
export BOOK2MP3_PERF_LOG="${BOOK2MP3_PERF_LOG:-1}"
export BOOK2MP3_PERF_RUN_ID="${BOOK2MP3_PERF_RUN_ID:-${RUN_TIMESTAMP}-$$}"
export BOOK2MP3_PERF_LOG_FILE="${BOOK2MP3_PERF_LOG_FILE:-$APP_ROOT/workspace/logs/performance.jsonl}"
if [ "$USE_BUNDLED_PYTHON" = "1" ]; then
  PYTHON_EXTRA_PATHS="$PYTHONPATH_ENTRY"
  for candidate in \
    "$PYTHON_RUNTIME_ROOT"/lib/python*/dist-packages \
    "$PYTHON_RUNTIME_ROOT"/lib/python*/site-packages \
    "$PYTHON_RUNTIME_ROOT"/local/lib/python*/dist-packages
  do
    if [ -d "$candidate" ]; then
      PYTHON_EXTRA_PATHS="${PYTHON_EXTRA_PATHS}:$candidate"
    fi
  done
  export PYTHONHOME="$PYTHON_RUNTIME_ROOT"
  export PYTHONNOUSERSITE=1
  export PYTHONPATH="${PYTHON_EXTRA_PATHS}${PYTHONPATH:+:$PYTHONPATH}"
else
  export PYTHONPATH="$PYTHONPATH_ENTRY${PYTHONPATH:+:$PYTHONPATH}"
fi

if [ -n "$PYTHON_RUNTIME_ROOT" ] && [ -d "$PYTHON_RUNTIME_ROOT/lib" ]; then
  export LD_LIBRARY_PATH="$PYTHON_RUNTIME_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

exec "$PYTHON_BIN" -m book2mp3.main "$@"
