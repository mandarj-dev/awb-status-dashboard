#!/usr/bin/env bash
# Run the dashboard on Mac/Linux:  bash run.sh      (on a server, use install-on-server.sh instead)
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
[ -z "$PY" ] && { echo "[FAIL] Python 3 is not installed. Install it from https://www.python.org/downloads/"; exit 1; }
exec "$PY" start.py "$@"
