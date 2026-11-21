#!/bin/bash
# Starts Verbaliox's server the way CI does (.github/workflows/ci.yml), runs a command against it, stops it.
#   serve.sh [--port N] [--keep-data] -- <command...>
# The command gets BASE=http://127.0.0.1:N and TOKEN=smoke. Data and models live in temporary folders
# (VERBALIOX_DATA_DIR / VERBALIOX_MODELS_DIR), seeded with the demo recordings of tests/ui/seed.py; the
# real data folder is never touched. Exit code: the command's.
set -u
PORT=8797
KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --keep-data) KEEP=1; shift ;;
    --) shift; break ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) break ;;
  esac
done
[ $# -gt 0 ] || { echo "serve.sh: no command (see --help)" >&2; exit 2; }
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT"
export VERBALIOX_TOKEN=smoke VERBALIOX_SKIP_MIGRATION=1 PYTHONPATH=tests/stubs
export VERBALIOX_DATA_DIR="$(mktemp -d)" VERBALIOX_MODELS_DIR="$(mktemp -d)"
LOG="$VERBALIOX_DATA_DIR/server.log"
python tests/ui/seed.py >/dev/null 2>&1
python -m uvicorn app.main:app --port "$PORT" >"$LOG" 2>&1 &
PID=$!
for _ in $(seq 1 40); do curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 1; done
BASE="http://127.0.0.1:$PORT" TOKEN=smoke "$@"
RC=$?
kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null
if [ "$RC" -ne 0 ]; then echo "--- server log (last 40 lines): $LOG"; tail -40 "$LOG"; fi
[ "$KEEP" = 1 ] && echo "data kept in $VERBALIOX_DATA_DIR" || rm -rf "$VERBALIOX_DATA_DIR" "$VERBALIOX_MODELS_DIR"
exit "$RC"
