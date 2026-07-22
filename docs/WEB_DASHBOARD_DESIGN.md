# OKX Web Dashboard — 技术选型与架构设计

> **Version**: v1 (LOCKED 2026-07-21 23:56)
> **作者**: 小野 (Xiao Ye)
> **日期**: 2026-07-21
> **状态**: v1 LOCKED. Q1=A / Q2=A / Q3=A1 (port 18787) / Frontend=React+Vite+TS / AI scope = Phase 2 add-on
> **目标读者**: Nixil + 未来接手的同事/AI

---

## 0. v1 LOCKED 状态(决策记录)

| 决策项 | 值 | 锁定时间 | 决策依据 |
|---|---|---|---|
| Q1 读写权限 | **A: 全只读**(只 GET,无 POST/PUT) | 2026-07-21 23:25 | OKX 数据展示,7-15 footgun 教训,零爆炸半径优先 |
| Q2 v1 范围 | **A: Portfolio + Cron 优先** | 2026-07-21 23:25 | 最高价值密度的两页;Strategy + Analytics → v2 |
| Q3 端口 + bind | **A1: bind 127.0.0.1:18787** | 2026-07-21 23:30 | WSL2 mirrored mode loopback forwarding 已验证(18789 案);交易数据应紧 |
| 前端栈 | **React + Vite + TypeScript** | 2026-07-21 23:54 | 用户定位本项目为"AI 应用工程师成长第一里程碑";React + Vite 工具链代价转为学习投资 |
| 原 Jinja2 + HTMX 方案 | **否决** | 2026-07-21 23:54 | 见上方"前端栈" |
| AI 微功能 | **Phase 2 待加入**:"自然语言查询持仓"(LangChain / OpenAI function call 接入) | 2026-07-21 23:54 | 路径 C 拍板;Phase 2 sprint 内完成 |

## TL;DR

- **Backend**: FastAPI (Python 同栈 OKX)
- **Frontend**: React 18 + Vite 5 + TypeScript(v1 起)
- **数据源**: 直读 state 文件(v1)→ SQLite v2
- **进程模型**: dev 双进程(uvicorn 18787 + Vite 5173)/ prod 单进程(uvicorn + StaticFiles mount dist)
- **鉴权**: bind 127.0.0.1(零鉴权,v3+ 加)
- **三阶段路线**: v1 hello-world → v1 Portfolio/Cron + AI scope → v2 实时 + 历史 → v3 命令 + 鉴权

---

## 1. 选型对比

### 1.1 Backend

| 选项 | 优势 | 劣势 | 决策 |
|---|---|---|---|
| **FastAPI (Python)** | 同 OKX 栈(零新 runtime)、async 友好、自动 OpenAPI docs、typing 严格 | — | **✅ v1 DECIDED** |
| Flask | 简单 | 同步阻塞、N+1 慢 | ❌ |
| Express (Node) | 高性能 | 引入 Node 栈(已用,作为前端) | ❌ |
| Streamlit | Python 5 分钟出页面 | runtime 重、定制弱 | ⏸ v2 评估 |
| Django | 全栈 | 重型 ORM 不适合文件快照场景 | ❌ |

### 1.2 Frontend (LOCKED: React + Vite + TS)

| 选项 | 优势 | 劣势 | 决策 |
|---|---|---|---|
| **React 18 + Vite 5 + TypeScript** | HMR、组件复用、AI 工程师目标长期投资、生态成熟度匹配 FastAPI 栈 | 工具链 + WSL2 npm install 痛点 | **✅ v1 DECIDED(LOCKED)** |
| Jinja2 + HTMX + 静态 CSS | 零构建、原生集成 FastAPI | v3 写命令阶段会形成摩擦;HTML 不能复用 | ❌ 否决 |
| React + Next.js | 渲染策略更现代 | 引入 SSR 复杂度、与 FastAPI 解耦不必要 | ❌ |

### 1.3 数据源层

| 选项 | 优势 | 劣势 | 决策 |
|---|---|---|---|
| **直读 state 文件** | 零依赖、复用 OKX cron 现有 schema | 半截写入竞态 | **✅ v1 DECIDED** |
| SQLite 增量快照 | 时序查询稳 | 多一个 watcher | ⏸ v2 |
| TSDB | 工业级 | 杀鸡用牛刀 | ❌ |

### 1.4 实时性

| 选项 | 优势 | 劣势 | 决策 |
|---|---|---|---|
| **Polling 10s** | 5 行代码 | 10s 延迟 | **✅ v1** |
| SSE (Server-Sent Events) | 单向推送原生 | 要 handler | ⏸ v2 |
| WebSocket | 双向 | 重型、不需要 | ❌ |

### 1.5 鉴权

| 选项 | 优势 | 劣势 | 决策 |
|---|---|---|---|
| **bind 127.0.0.1 + WSL2 直连** | 零代码、零凭据 | 仅本机 | **✅ v1 DECIDED** |
| HTTP Basic | 局域网可用 | 凭据明文 | ⏸ v3 |
| OIDC/SSO | 标准 | 重型 | ❌ |

### 1.6 图表(v2)

- **Chart.js** — 轻量、Canvas、文档强(候选)
- Plotly.js — 功能多但重
- Apache ECharts — 功能强、繁

最终 v2 选 Chart.js,直到有需求撑起 Plotly。

---

## 2. 架构模块图

```
┌──────────────────────────────────────────────────────────┐
│   Browser (Windows 端 / WSL2 端)                            │
└──────────────────────────┬───────────────────────────────┘
                           │ http(s)
        ┌──────────────────┴───────────────────┐
        │                                      │
        │ dev:5173                             │ prod:18787
        │ Vite dev (HMR)                       │ uvicorn
        │ React 18 + TS                        │ (FastAPI + StaticFiles)
        │                                      │
┌───────▼──────────────────────┐    ┌──────────▼──────────────┐
│  Vite dev server              │    │  FastAPI                 │
│  src/App.tsx, src/main.tsx    │    │  routes/portfolio.py     │
│  vite proxy /api → 18787      │    │  routes/cron.py          │
└───────┬──────────────────────┘    │  services/                │
        │ dev only                  │    file_reader.py         │
        │ /api/* forwarded          │    (原子读 + flock)       │
        │                           └──────────┬──────────────┘
        │                                      │ read-only
        │                          ┌───────────▼──────────────┐
        └─────────────────────────►│  state/*.json            │
                                   │  logs/*.log              │
                                   │  logs/trades/*.csv       │
                                   │  data/market/            │
                                   └──────────────────────────┘
                                            ▲
                                            │ write (原 OKX cron 不变)
                                    ┌───────┴────────┐
                                    │ signal_runner    │
                                    │ sync_portfolio   │
                                    │ watchdog cron    │
                                    └──────────────────┘
```

**关键解耦**:Web 层只读 OKX 现有文件,OKX cron 不感知 dashboard 存在。

---

## 3. 目录结构(实际已落地)

```
okx/
├── web/                                # NEW (Phase 1 hello-world)
│   ├── .gitignore                      # node_modules/, dist/, __pycache__/
│   ├── README.md
│   ├── run.sh                          # dev launcher (双进程)
│   ├── backend/
│   │   ├── app.py                      # FastAPI: /api/health, /api/portfolio
│   │   └── requirements.txt            # fastapi, uvicorn[standard]
│   └── frontend/
│       ├── package.json                # react 18, vite 5, ts 5
│       ├── vite.config.ts              # proxy /api → 127.0.0.1:18787
│       ├── tsconfig.json
│       ├── tsconfig.node.json
│       ├── index.html
│       └── src/
│           ├── main.tsx
│           ├── App.tsx                 # fetches /api/health + /api/portfolio
│           └── index.css
└── docs/
    └── WEB_DASHBOARD_DESIGN.md         # ← 本文档
```

**Phase 2 扩展**:
```
backend/
├── routes/
│   ├── portfolio.py                    # GET /portfolio (HTML or HTML fragment)
│   ├── cron.py
│   └── ai_query.py                     # POST /api/query (自然语言查询)
├── services/
│   ├── file_reader.py
│   ├── snapshot.py                     # v2 SQLite
│   └── ai_query.py                     # LangChain agent
frontend/
└── src/
    ├── pages/
    │   ├── Portfolio.tsx
    │   ├── Cron.tsx
    │   └── Query.tsx                   # NLP 查询界面
    └── components/
        └── ... reusable
```

---

## 4. v1 页面范围(locked: Portfolio + Cron)

### 4.1 Portfolio 页

**主表格**:symbol | direction | entry | mark | size | leverage | margin | uPnL | SL | TP | strategy

**顶部卡片**:账户净值 / 毛杠杆 / uPnL % / 距离强平 / 持仓数

**数据源**:`state/portfolio.json`

### 4.2 Cron 页

**时间线 + 表格**:
| 任务 | 上次执行 | last_heartbeat | uPnL 当时 | 异常次数(7d) |
|---|---|---|---|---|

**drift 监控图** —— 对应 MEMORY.md P0 lesson:`effb148` 2m42s case
- 横轴时间 / 纵轴 cold-start drift seconds
- 红线 = 240s MAX_WAIT_SECONDS
- 红点 = "已 fallback,没 spinlock 等到整点"

**数据源**:`state/last_workflow_result.json`、`state/signal_runner.heartbeat`、`state/health_probe/`、`state/sync_history.json`

### 4.3 (Phase 2) AI 查询页

**自然语言 → 持仓答案**(Nixil 拍板 path C)
- 例:"我 BTC 仓位啥情况" → 返回当前 BTC 仓位的 entry / uPnL / SL/TP
- "今天 PnL 多少" → 返回今日 PnL
- 工具:LangChain / OpenAI function call 接入 portfolio 读取 API

---

## 5. 风险清单 + 缓解

| 风险 | 严重度 | 缓解 |
|---|---|---|
| **半截 JSON 写入**:cron 写 portfolio.json 中途被 web 读到 | 高 | `file_reader.py` 用 `fcntl.flock(LOCK_SH)`;或 `os.replace(.tmp, real)` write-then-rename 模式;读取 try-except fallback `.bak-*` |
| **WSL2 网络访问**:Windows 浏览器连 127.0.0.1 不通 | 中 | 默认 127.0.0.1 + WSL2 mirrored mode 自动 loopback forwarding(per 18789 case) |
| **凭据外泄**:模板意外渲染 API_KEY | 高 (P0) | 模板审计:只渲染数据字段,绝不引用 env / vault |
| **资源抢占**:10s polling 把 cron 卡 | 低 | 只读 open(),不调 OKX API live(v1 全静态) |
| **配置漂移**:dashboard 写死策略名,实际 v1.8.3+ disable B | 中 | 读 `code/config.json` `enabled`,绝不硬编码 |
| **npm install 失败**:WSL2 上 lockfile 或 registry 网络 | 中 | 备份:CDN/UMD 直装;首次跑 make build 后 webpack work |
| **systemd unit 冲突**:uvicorn 抢占 18789 端口 | 低 | 已校验 18787 空闲,bind 18787 错位 |

---

## 6. 三阶段路线

| 阶段 | 时间预算 | 范围 | 完成定义 |
|---|---|---|---|
| **Phase 1** hello-world | 1-2 天 | `okx/web/` 骨架;backend/frontend 跑通;/api/health + /api/portfolio | Chromium 5173 看到 React app 显示 portfolio 数据 |
| **Phase 2** 完整 v1 | +1 周 | Portfolio + Cron 双页 + AI 微功能(NLP 查询);systemd unit + drop-in | 4 页可用,NLP 查询能 return 持仓 |
| **Phase 3** 实时 + 历史 | +1 周 | SQLite snapshot、Chart.js、SSE、加 trades.csv 时序 | P&L 曲线、win-rate 图、drift heatmap 真上线 |
| **Phase 4** 写命令 + 鉴权 | 后续 | manual sync 触发按钮、Basic auth、HTTPS | 写命令受 constitution 控制 + 安全 model |

---

## 7. (已锁版的) 决策追溯

### Q1 全只读 (LOCKED A)
只允许 GET,无 POST/PUT/PATCH/DELETE。代码层 enforce:routes 文件不含写装饰器。

### Q2 Portfolio + Cron 优先 (LOCKED A)
Phase 2 验收通过 Strategy + Analytics。

### Q3 bind 127.0.0.1:18787 (LOCKED A1)
- 18787 已校验空闲
- WSL2 mirrored loopback forwarding 自动通路
- 18787 ≠ 18789(openclaw-gateway),避免冲突

### Q4 前端栈 = React + Vite + TypeScript (LOCKED)
- 决策时间 2026-07-21 23:54
- 决策依据:用户"AI 应用工程师成长第一里程碑" framing
- 工具链代价转为学习投资

### Q5 AI 范围(Phase 2 自然语言查询)
- 路径 C 拍板 2026-07-21 23:54
- 工具选择(LangChain / OpenAI function call / 自写 prompt)在 Phase 2 sprint 内决定

---

## 8. systemd 集成点(Phase 2 入)

- New unit `~/.config/systemd/user/okx-web.service`
- Drop-in `~/.config/systemd/user/okx-web.service.d/proxy.conf`(镜像 openclaw-gateway 模式)
- 端口冲突回避:已验证 18787 空闲
- 模式:prod 模式 `uvicorn --host 127.0.0.1 --port 18787`

---

## 9. 关联引用

- MEMORY.md cron P0 lesson(`effb148` spinlock adaptive fallback) — cron 页 drift 图设计依据
- MEMORY.md OKX 凭据约定(单 `.env`) — systemd `EnvironmentFile=` 来源
- `~/.openclaw/workspace/skills/systemd-env-proxy-on-wsl2/SKILL.md` — systemd user service proxy env 模式
- `~/.openclaw/workspace/skills/okx-trading-conventions/SKILL.md` — 项目级 playbook
- 7-15 footgun (-3.99 USDT) — Portfolio 页 EXTERNAL 警示 label + 写命令必须 audit log 的设计来源
- WSL2 mirrored mode 18789 案例验证 — Q3 bind 127.0.0.1 的可行性证据

---

## §10 v1.3 changelog (2026-07-22)

**Nixil approved 架构扩张 2026-07-22**：v1 LOCKED "zero-side-effect file reads only" 原则**对 /api/portfolio 失效**。

### What changed

| 维度 | v1 (LOCKED 2026-07-21) | v1.3 (2026-07-22) |
|---|---|---|
| 后端数据源 | 仅本地 `okx/state/*.json` | 本地 + OKX V5 GET endpoints |
| `/api/portfolio` 内容 | active + closed + summary | **+ risk_metrics**（equity / notional / leverage / concentration / liq distance） |
| 缓存策略 | 无 | `state/risk_metrics_cache.json`（60s TTL） |
| `/api/cron` drift | `drift_seconds` + `fallback_used` | **+ `drift_status: on_time / early / late`**（3 态语义） |
| 前端 UI 库 | 手写 CSS（GitHub Primer Dark） | **Mantine v7**（AppShell 侧栏 + 6 metric cards + drift 3-state card） |
| Proxy 路径 | 文文不验证 | SOCKS5 (`httpx[socks]>=0.27`) |
| Drift 早边界检测 | 漏 | `abs(drift) > 240s` → fallback |

### 风险与缓释

- 后端现在有 OKX API 调用 + 文件缓存写入（透明，60s TTL）
- OKX 调用**仅 GET**，无订单 / 仓位修改
- POST `/api/query` 仍无 OKX side-effect（仅可选外部 LLM）
- 单 `.env` 是 Constitution 约定的凭据模式（其他 OKX 工具同用）

### Lessons learned（完整 post-mortem `memory/2026-07-22.md`）

1. **OKX timestamp 格式严格匹配 `Z`**：`datetime.isoformat()` 产 `+00:00` → 401。必须 `strftime + "{ms:03d}Z"`
2. **`httpx` + SOCKS 需 `httpx[socks]`**：否则 `Using SOCKS proxy, but the 'socksio' package is not installed`
3. **systemd 不继承 shell env**：`run-prod.sh` 必须显式 `source ../.env`
4. **OKX 返 `notionalUsd` 直接字段**：不必自己算 `|pos| × ctVal × markPx`
5. **Cross-margin 仓 `liqPx=""`**：用 `_safe_float(..., default=0.0) or None` 模式跳过
6. **OKX 端 SSL EOF 是常见抖动**：3-retry + exponential backoff（0.5s / 1.0s）

### 顺带 ship 的 v2 原计划

设计 §6 Phase 3 的 "Charts: drift 时间序列 / win-rate / P&L 曲线"：
- **drift 时序 AreaChart 已 ship**（Cron 页）
- **Cumulative PnL LineChart 已 ship**（Portfolio 页）

Phase 3 只剩 SSE 实时推送 + SQLite 历史快照未做（v2 milestone）。

---

## 附录 A: 反向论证(为什么不选这些)

| 不选项 | 不选原因 |
|---|---|
| Streamlit | runtime 重,定制弱,跟 FastAPI + React 栈分裂 |
| 纯 SPA 不带 React(JQuery/Vue) | Vue 是选项但 React 生态成熟度更深、AI 工程师目标更贴合 |
| TSDB | 时序数据一年下来不到 1 GB,SQLite 顶得住 |
| WebSocket | 单向推送足够,SSE 更轻 |
| OAuth | 单用户工具,杀鸡用牛刀 |
| BI 工具 (Metabase/Grafana) | 重型,跟 OKX 项目解耦,自定义弱 |

---

_本文档 v1 LOCKED。Phase 2 落地 AI 范围时,新建 v1.1 + 在"决策追溯"加 Q6,v1 原文档不动。_
