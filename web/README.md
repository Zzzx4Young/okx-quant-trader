# OKX Web Dashboard (v1.3.0 · live OKX V5 metrics)

Stack: **FastAPI + httpx(SOCKS) + React 18 + Vite 5 + TypeScript + Mantine v7**.

## Current status (v1.3.0 — 2026-07-22)

| Phase | Status |
|---|---|
| Phase 1 hello-world (2026-07-21) | ✅ shipped |
| v1 LOCKED — Portfolio + Cron + Query (2026-07-22) | ✅ shipped |
| v1.2.0 Mantine UI 重构 (2026-07-22) | ✅ shipped |
| v1.3.0 OKX V5 实时指标 (2026-07-22) | ✅ shipped (this version) |

## What v1.3 adds over v1

- `/api/portfolio` returns **`risk_metrics` block** (live OKX V5 + 60s cache):
  - `equity_usd`, `gross_notional_usd`, `gross_leverage`
  - `inst_concentration` (top symbol %), `strategy_concentration` (top strategy %)
  - `min_liq_distance_pct` (worst-case mark-to-liq distance)
- `/api/cron` drift now has **`drift_status: on_time / early / late`** — no more
  "✓ Within threshold" lie when runner used fallback (e.g. last_run 20:02,
  boundary 21:00 → status = "early", badge = EARLY).
- Frontend: **Mantine v7** sidebar layout + Risk Metrics card on Portfolio page.
- Backend arch: was zero-side-effect file-reads-only (v1 LOCKED) → now also
  reads OKX V5 GET endpoints (read-only, with 60s file cache). Nixil approved
  2026-07-22. See `okx/docs/WEB_DASHBOARD_DESIGN.md §10`.

## Layout

```
okx/web/
├── .gitignore
├── README.md                       # this file
├── run.sh                          # dev launcher (two processes)
├── run-prod.sh                     # prod launcher (single uvicorn, sources .env)
├── backend/
│   ├── app.py                      # FastAPI app · 4 endpoints · OKX V5 client
│   └── requirements.txt            # fastapi · uvicorn[standard] · httpx[socks]
└── frontend/
    ├── package.json                # react 18 · vite 5 · ts 5 · @mantine/* · recharts · dayjs
    ├── vite.config.ts
    ├── tsconfig.json
    ├── tsconfig.node.json
    ├── index.html
    ├── dist/                       # built bundle (mounted by uvicorn in prod)
    └── src/
        ├── main.tsx                # MantineProvider + theme + Notifications
        ├── App.tsx                 # AppShell sidebar · 3 pages
        ├── index.css               # minimal reset (Mantine owns styling)
        └── pages/
            ├── Portfolio.tsx       # stat cards · Cumulative PnL chart · active/closed tables · risk_metrics
            ├── Cron.tsx            # drift card (3-state) · heartbeat · sync activity chart · health probe
            └── Query.tsx           # 自然语言查询 (Phase 2a stub / Phase 2b LLM)
```

## Endpoints

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/health` | JSON liveness; version, llm config, paths check |
| GET | `/api/portfolio` | Local portfolio.json + OKX V5 risk_metrics (60s cache) |
| GET | `/api/cron` | heartbeat + last workflow + recent syncs + drift (3-state) |
| POST | `/api/query` | Phase 2a keyword stub; Phase 2b LLM via api.minimaxi.com |

## Run

### Dev (two processes, hot reload)

```bash
bash okx/web/run.sh
```

- uvicorn on `127.0.0.1:18787` (auto-reload)
- Vite on `127.0.0.1:5173` (HMR for React)
- Vite proxies `/api/*` to 18787

### Prod (single uvicorn, systemd)

```bash
systemctl --user start okx-web.service
```

- `run-prod.sh` sources `../.env` then exec uvicorn on `127.0.0.1:18787`
- Single port serves `/api/*` + React bundle from `frontend/dist/`
- systemd drop-in at `~/.config/systemd/user/okx-web.service.d/proxy.conf`
  mirrors `openclaw-gateway` proxy pattern (SOCKS5 to V2RayN)

## Required environment

`.env` (sourced by `run-prod.sh`):

```
OKX_TRADING_MODE=demo                    # demo | live
OKX_DEMO_API_KEY=***
OKX_DEMO_API_SECRET=***
OKX_DEMO_PASSPHRASE=***
# Optional — Phase 2b LLM:
OKX_WEB_LLM_API_KEY=***                  # enables real LLM at POST /api/query
```

The OKX V5 API requires the **`x-simulated-trading: 1` header in demo mode**
(handled automatically by `_okx_creds()` based on `OKX_TRADING_MODE`).

## Required Python packages

`backend/requirements.txt`:
- `fastapi>=0.110`
- `uvicorn[standard]>=0.27`
- `httpx[socks]>=0.27` — `[socks]` extra installs `socksio` for SOCKS5 proxy

Without `[socks]`, OKX calls fail with "Using SOCKS proxy, but the 'socksio'
package is not installed".

## OKX V5 API contract (v1.3 references)

| Endpoint | Used for |
|---|---|
| `GET /api/v5/account/balance?ccy=USDT` | `equity_usd` (totalEq) |
| `GET /api/v5/account/positions?instType=SWAP` | notional + liq_px per position |

Auth: HMAC-SHA256 base64(`timestamp + method + path + body`), where `timestamp`
is `YYYY-MM-DDTHH:mm:ss.SSSZ` **with `Z` suffix** (NOT `+00:00`).

Strategy field is NOT returned by OKX — joined from local `portfolio.json`
inside backend (`strategy_by_inst` map).

## Known issues (post-v1.3 backlog)

- [ ] Phase 3: SSE real-time push (cron sub-agent results)
- [ ] Phase 3: SQLite historical snapshots (replace file polling)
- [ ] Code-split Mantine vendor chunk (currently 721KB JS, 207KB gz)
- [ ] Test coverage for OKX V5 auth + retry logic (currently zero tests for backend)