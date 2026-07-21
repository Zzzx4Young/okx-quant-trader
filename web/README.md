# OKX Web Dashboard (Phase 1 — hello-world)

Stack: **FastAPI + React 18 + Vite 5 + TypeScript**.

Phase 1 scope: stack validation only. Real Portfolio/Cron pages + AI query are Phase 2.

## Layout

```
okx/web/
├── .gitignore
├── README.md
├── run.sh                       # dev launcher (two processes)
├── backend/
│   ├── app.py                   # /api/health, /api/portfolio
│   └── requirements.txt         # fastapi, uvicorn[standard]
└── frontend/
    ├── package.json             # react 18, vite 5, ts 5
    ├── vite.config.ts           # proxy /api → 127.0.0.1:18787
    ├── tsconfig.json
    ├── tsconfig.node.json
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx              # fetches /api/health + /api/portfolio
        └── index.css
```

## Run (dev)

```bash
bash okx/web/run.sh
```

This starts:
- **uvicorn** on `127.0.0.1:18787` (auto-reload)
- **Vite dev server** on `127.0.0.1:5173` (HMR for React)

Chromium opens `http://127.0.0.1:5173/`. Vite transparently proxies `/api/*` to 18787.

## Endpoints

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/health` | JSON liveness, including STATE_DIR exists check |
| GET | `/api/portfolio` | Reads `okx/state/portfolio.json`; 503 on race |

Both endpoints are GET only — v1 is fully read-only by design.

## Phase 1 acceptance

- Chromium at `http://127.0.0.1:5173/` shows:
  1. Health card with `service: okx-web, phase: 1-hello-world`
  2. Portfolio table with the 1 BTC-USDT-SWAP position currently in demo
  3. EXTERNAL_WEB_SYNC row visually marked (orange background)
  4. Last-fetch timestamp updates every 10s

## Phase 2 preview

- Portfolio full page (top cards: equity / leverage / uPnL)
- Cron drift monitoring (per `effb148` P0 lesson)
- AI natural-language query (`POST /api/query` using LangChain / OpenAI function call)
- systemd unit `~/.config/systemd/user/okx-web.service` + drop-in for proxy env
- SQLite historical snapshot for v2/v3 charts

See `okx/docs/WEB_DASHBOARD_DESIGN.md` for the locked design.
