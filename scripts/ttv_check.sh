#!/usr/bin/env bash
# ==============================================================================
# Time-to-value check: fresh clone -> first event visible through the API.
#
# Follows the README "Manual Setup" path for the server and SDK in a clean
# temporary directory with a fresh virtualenv, then emits one event and polls
# the REST API until it is stored. Prints the time spent in each step.
#
# Usage:
#   scripts/ttv_check.sh [REPO_URL_OR_PATH] [--with-ui] [--cold]
#
# Defaults to cloning the current local checkout (HEAD). Pass the GitHub URL to
# measure what a new user experiences. --with-ui also times `npm ci` and
# `npm run build` for the dashboard.
#
# By default pip and npm reuse the machine's package caches, so results depend
# on what earlier runs downloaded. --cold disables the pip cache and gives npm
# an empty cache in the temporary directory, so every package is downloaded,
# as on a new machine (OS-level DNS/TLS caches and bandwidth still vary).
# ==============================================================================
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_UI=0
COLD=0
for arg in "$@"; do
  case "$arg" in
    --with-ui) WITH_UI=1 ;;
    --cold) COLD=1 ;;
    *) SRC="$arg" ;;
  esac
done

PYTHON="${PYTHON:-python3}"
WORK="$(mktemp -d -t agentscope-ttv-XXXXXX)"
PORT="$("$PYTHON" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" 2>/dev/null || true; fi
  rm -rf "$WORK"
}
trap cleanup EXIT

now() { "$PYTHON" -c 'import time; print(time.monotonic())'; }
T0="$(now)"; LAST="$T0"
step() {
  local t; t="$(now)"
  printf "%-34s %6.1fs\n" "$1" "$("$PYTHON" -c "print($t - $LAST)")"
  LAST="$t"
}

if [ "$COLD" -eq 1 ]; then
  export PIP_NO_CACHE_DIR=1
  export npm_config_cache="$WORK/npm-cache"
  CACHES="cold (pip cache disabled, empty npm cache)"
else
  CACHES="warm (machine pip/npm caches)"
fi

echo "Source: $SRC"
echo "Workdir: $WORK"
echo "Caches: $CACHES"
echo

git clone --quiet --depth 1 "file://$SRC" "$WORK/repo" 2>/dev/null || git clone --quiet --depth 1 "$SRC" "$WORK/repo"
step "git clone"

"$PYTHON" -m venv "$WORK/venv"
# shellcheck disable=SC1091
source "$WORK/venv/bin/activate"
step "create virtualenv"

pip install --quiet --disable-pip-version-check -r "$WORK/repo/packages/server/requirements.txt"
step "pip install server"

pip install --quiet --disable-pip-version-check -e "$WORK/repo/packages/sdk"
step "pip install SDK"

# exec, so SERVER_PID is uvicorn itself and the cleanup trap stops it.
(cd "$WORK/repo/packages/server" && \
  DATABASE_URL="sqlite+aiosqlite:///$WORK/ttv.db" \
  exec python -m uvicorn main:app --host 127.0.0.1 --port "$PORT" --log-level warning \
  >"$WORK/server.log" 2>&1) &
SERVER_PID=$!
python - "$PORT" <<'PY'
import sys, time, urllib.request
port = sys.argv[1]
for _ in range(200):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
        sys.exit(0)
    except OSError:
        time.sleep(0.1)
sys.exit("server did not start")
PY
step "start server"

python - "$PORT" <<'PY'
import json, sys, time, urllib.request
from agentscope_trace.decorators import configure, get_global_client, trace
port = int(sys.argv[1])
configure(host="127.0.0.1", port=port, session_name="time-to-value")

@trace(name="first_step")
def first_step():
    return "hello"

first_step()
client = get_global_client()
for _ in range(200):
    if client.session_id:
        try:
            url = f"http://127.0.0.1:{port}/api/sessions/{client.session_id}/events"
            if json.load(urllib.request.urlopen(url, timeout=2))["events"]:
                break
        except OSError:
            pass
    time.sleep(0.05)
else:
    sys.exit("first event never arrived")
client.stop()
PY
step "first event stored"

if [ "$WITH_UI" -eq 1 ]; then
  (cd "$WORK/repo/packages/ui" && (npm ci --silent --no-audit --no-fund || npm install --silent --legacy-peer-deps --no-audit --no-fund) >/dev/null 2>&1)
  step "npm ci (dashboard)"
  (cd "$WORK/repo/packages/ui" && npm run build --silent >/dev/null 2>&1)
  step "npm run build (dashboard)"
fi

echo
printf "%-34s %6.1fs\n" "TOTAL" "$("$PYTHON" -c "print($(now) - $T0)")"
