#!/bin/bash
# The browser checks of CI: smoke.mjs, then scenarios.mjs (SHOTS=<folder> keeps screenshots of the steps).
#   check.sh [--port N]
# Exit code 0 only when both passed.
DIR="$(dirname "$0")"
exec "$DIR/serve.sh" "$@" -- bash -c 'node tests/ui/smoke.mjs && node tests/ui/scenarios.mjs'
