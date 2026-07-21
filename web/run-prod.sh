#!/usr/bin/env bash
# OKX Web Dashboard — production launcher (Phase 2c).
#
# Single uvicorn on 127.0.0.1:18787:
# - serves /api/* (FastAPI routes)
# - serves frontend bundle from frontend/dist/ (StaticFiles mount)
#
# systemd service okx-web.service calls this.

set -euo pipefail

# systemd user services run with restricted PATH that does NOT include
# ~/.local/bin. uvicorn was installed via `pip3 install --user`, so its
# executable lives at $HOME/.local/bin/uvicorn. Export PATH explicitly.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

WEB_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$WEB_DIR"

# Verify build artifact exists. Bail early if missing.
if [ ! -d frontend/dist ]; then
  echo "[run-prod.sh] ERROR: frontend/dist/ missing."
  echo "[run-prod.sh] Run: cd $WEB_DIR/frontend && npm run build"
  exit 1
fi

exec uvicorn backend.app:app \
  --host "${OKX_WEB_HOST:-127.0.0.1}" \
  --port "${OKX_WEB_PORT:-18787}" \
  --no-access-log
