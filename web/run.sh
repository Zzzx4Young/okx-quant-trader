#!/usr/bin/env bash
# OKX Web Dashboard — dev launcher (Phase 1 hello-world).
#
# Starts two processes:
# - uvicorn backend on 127.0.0.1:18787 (FastAPI, --reload)
# - Vite dev server on 127.0.0.1:5173 (React + TS, HMR)
#
# Vite proxies /api/* to 18787. Chromium opens http://127.0.0.1:5173/
#
# Stop both with Ctrl+C (kills Vite; uvicorn left in background if forked).
# To stop uvicorn too:  pkill -f 'uvicorn backend.app:app'

set -euo pipefail
WEB_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${OKX_WEB_PORT:-18787}"

echo "[run.sh] web dir: $WEB_DIR"
echo "[run.sh] backend port: $PORT"

# ── Backend deps ────────────────────────────────────────────────
if ! python3 -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "[run.sh] installing backend deps (fastapi, uvicorn)…"
  pip3 install -r "$WEB_DIR/backend/requirements.txt"
fi

# ── Start backend ────────────────────────────────────────────────
cd "$WEB_DIR"
nohup uvicorn backend.app:app --host 127.0.0.1 --port "$PORT" --reload \
  > /tmp/okx-web-uvicorn.log 2>&1 &
UV_PID=$!
echo "[run.sh] uvicorn pid=$UV_PID logging to /tmp/okx-web-uvicorn.log"
trap "echo '[run.sh] stopping uvicorn (pid=$UV_PID)…'; kill $UV_PID 2>/dev/null || true" EXIT

# Quick liveness check (3s grace)
sleep 2
if ! curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "[run.sh] WARNING: backend not reachable yet at :$PORT/api/health"
  echo "[run.sh] tail of uvicorn log:"
  tail -20 /tmp/okx-web-uvicorn.log || true
fi

# ── Frontend (Vite dev) ──────────────────────────────────────────
cd "$WEB_DIR/frontend"
if [ ! -d node_modules ]; then
  echo "[run.sh] first run, npm install (may take 10-30s)…"
  npm install
fi
echo "[run.sh] starting Vite dev server…"
exec npm run dev
