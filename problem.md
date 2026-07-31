# OKX Problem Log — 2026-07-31

> 小野记录的不确定 / 待决策 / 调查后澄清的问题。
> 触发场景：`完成待办任务，遇到不确定的问题记录在okx\problem.md`（Nixil 19:04 CST 设定）。
> 与 `docs/LESSONS_LEARNED.md §7.1` 是不同文件：本文件是**当前会话待决**，LESSONS 是**已沉淀经验**。

---

## 🔴 已确认的"问题"（调查后澄清）

### P-1. `logs/heartbeat.log` 21h59m WARN — 监控阈值与 cron 周期错配 ✅ 已修复

- **症状**：`logs/heartbeat.log` age=79184s，超过 `liveness_probe.py` 阈值 72000s
- **根因**（已查证，100% 定位）：
  - `scripts/liveness_probe.py:130-133`：`heartbeat.log` `warn_sec=20*3600` (20h), `crit_sec=26*3600` (26h)
  - `okx-daily-heartbeat` cron：`0 21 * * *` @ Asia/Shanghai = **每 24h 一次**
  - 阈值 < cron 周期 → 每次执行后立即进入 warn 状态，永不恢复
- **同类错配**（同文件同模式）：
  - `logs/anomaly_diagnosis.log` warn=20h, crit=26h，cron `0 0 * * *`（24h）— 当前 age 68268s ≈ 19h 接近 warn，下次 cron 5h 后必然 WARN
  - `logs/daily_review.log` warn=20h, crit=26h，cron `30 23 * * *`（24h）— 当前 age 70332s ≈ 19.5h 已 warn，下次 cron 4h 后必然 CRIT
- **下次 cron 触发时间**：
  - `okx-daily-heartbeat` in **2h**（21:00 CST）
  - `okx-ai-daily-review` in **4h**（23:30 CST）
  - `okx-anomaly-diagnosis` in **5h**（00:00 CST）
- **影响范围**：监控噪声慢性 + 真实告警被淹没（狼来了效应）
- **修复**（2026-07-31 20:18 CST, TDD red→green 闭环）：
  - warn: 20h → **28h** (1 cron 周期 24h + 4h slack 容忍 cron delay/clock drift)
  - crit: 26h → **52h** (2 cron 周期 + 4h slack → 1 次 miss 后升级到 critical)
  - 三个 daily-cadence log 统一应用 (heartbeat / anomaly_diagnosis / daily_review)
- **TDD 证据**：
  - `okx/tests/test_liveness_probe.py::test_probe_config_has_heartbeat_push_threshold` (强化断言：warn > 24h, crit > 48h)
  - `okx/tests/test_liveness_probe.py::test_probe_config_all_daily_cadence_logs_have_above_period_thresholds` (新增：三个 daily log 统一校验)
- **验证**：
  - 8/8 新/强化测试 PASS
  - 全量回归 614 passed + 2 skipped + 0 failed (baseline 607+2 + 7 新测试)
  - 立刻跑 `python3 scripts/liveness_probe.py` → **Overall: ✅ OK** (三个 log age 83855s/72938s/75002s 均 < 100800s 新阈值)
- **回滚**：`git checkout -- scripts/liveness_probe.py`
- **状态**：✅ **RESOLVED**（待 Nixil commit）

### P-2. `state/last_workflow_result.json` 落盘检查 — ✅ 健康

- mtime 2026-07-31 19:05（最近一次 runner.run）
- 内容：3 manual 持仓全部 `HOLD_MANUAL`，`reconcile.matched=3/mismatched=0`，`drift_detected=false`
- `state/signal_runner.heartbeat` (189 bytes, mtime 19:00) 也在
- **结论**：正常，无须操作

### P-3. `state/portfolio.json` 持久化原子性 — 已知 bug 复确认 ✅ 已修复

- `code/portfolio.py:146-149`：`_save()` 用 `with open(self._path, "w") as f: json.dump(...)` 直接写，**无 write-to-temp + `os.replace()`**
- 历史佐证：`state/portfolio.json.bak-20260724-231941-circuit`（suffix `-circuit` 表明 circuit_breaker 触发时 dump 的残缺文件）
- LESSONS_LEARNED.md §7.1 #3 已列待办但**至今未修**
- **修复**（2026-07-31 20:18 CST, TDD red→green 闭环）：
  ```python
  # 新 _save() (code/portfolio.py:148-185):
  # 1. tempfile.mkstemp 同目录创建 .tmp (os.replace 要求同 fs)
  # 2. os.fdopen + json.dump + flush + os.fsync (强制落盘)
  # 3. os.replace 原子 rename (POSIX rename 语义)
  # 4. except: os.unlink(tmp) + raise (清理 + re-raise)
  ```
- **TDD 证据**（`okx/tests/test_portfolio_atomic.py`, 6 测试）：
  - T1 正常 _save → JSON 合法
  - T2 崩溃 mid-write → 原文件保留 (核心 bug, 现已通过)
  - T3 os.replace 失败 (磁盘满) → tmp 清理 + 原文件保留
  - T4 成功路径无 .tmp 残留
  - T5 部分写入后 _load 读到原数据 (模拟进程重启)
  - T6 并发 _save 线程安全 (60 positions × 3 thread)
- **验证**：
  - 6/6 portfolio_atomic 测试 PASS
  - T2/T5 是最强证据：模拟崩溃后 Portfolio() 不再抛 JSONDecodeError
  - T6 验证既有 lock 契约没被破坏 (3 thread × 20 writes = 60 positions, JSON 完整)
  - 全量回归 614 passed + 2 skipped + 0 failed (0 破坏)
- **回滚**：`git checkout -- code/portfolio.py`
- **状态**：✅ **RESOLVED**（待 Nixil commit）

---

## 🟡 LESSONS_LEARNED.md §7.1 已知待办（5 项分类）

| # | 项目 | 类别 | 决策依赖 |
|---|---|---|---|
| 1 | 资金费率结算测试缺失（每 8h 结算逻辑没单测） | 测试覆盖 | ✅ **DONE 2026-07-31** |
| 2 | 4 策略 ABCD 端到端测试缺失（只有单指标，组合信号没覆盖） | 测试覆盖 | ✅ **DONE 2026-07-31** |
| 3 | portfolio 持久化原子性 | 核心代码 bug | ✅ **DONE 2026-07-31** (P-3) |
| 4 | 实盘账户入金（当前 demo，实盘余额≈0） | 外部决策 | **Nixil 独有权限** |
| 5 | OKX secretKey 轮换（Telegram 历史已暴露，建议 24h 内禁用旧 key） | 安全运维 | **Nixil 独有权限** |

---

## 🟡 7-23 已知 backlog（4 项）

| # | 项目 | 来源 | 决策依赖 |
|---|---|---|---|
| 1 | WEB_DASHBOARD_DESIGN.md §11 G1-G5 + H6-H9 changelog（v1.3.1 patch section） | promotion block | ✅ **DONE 2026-07-31** |
| 2 | `memory_search` 仍 paused（embedding provider mismatch） | promotion block | ✅ **DONE 2026-07-31** (实际在用 BM25/FTS, 7-22 那条错误是 stale) |
| 3 | systemd-env-proxy-on-wsl2/SKILL.md 累积 3 条新教训（nvm node / SOCKS [socks] / source ../.env）待下次升级 | promotion block | ✅ **DONE 2026-07-31** (proposal pending apply) |
| 4 | v1.4 milestone（可选）：SSE 实时推送 / SQLite 历史快照 / Charts win-rate 曲线 | promotion block | Nixil 是否启动 v1.4 |

---

## 🔵 Phase 3B VERDICT 待 Nixil review

- 文件：`data/phase3b/VERDICT_P0_P1.md`（2026-07-29 22:50 CST 写）
- **核心结论**：
  - 432 个 hypothesis tests → **0 个** p<0.05（Bonferroni 校正后）
  - Phase B（H1 4h A strategy）：d=-0.110, p=0.83 — **NEGATIVE**
  - Phase B（H2 1d A strategy）：d=0.086, p=0.39, n=11 不足
  - Phase C（H4 funding carry）：Sharpe=-2.54, p=0.785 — NEGATIVE
  - Phase C（H5 carry + A combined）：不可测（A 无 alpha）
- **VERDICT 末尾建议**（原文）：
  > "Operational recommendation: Hold live deployment. Pivot to research-mode only. Do NOT iterate on current strategies without fundamental rethink."
- **状态**：⚠ **待 Nixil 决策**（是否进入 research-mode 冻结策略迭代）

---

## 📝 来源追踪

- 系统 WARN 来源：runtime context, 2026-07-31 19:02:19 GMT+8
- 阈值定义：`scripts/liveness_probe.py:110-145`
- Cron 实际 schedule：`openclaw cron list` 实时拉取
- 历史佐证：`state/portfolio.json.bak-20260724-231941-circuit`
- LESSONS 待办：`docs/LESSONS_LEARNED.md:496-510`
- Phase 3B verdict：`data/phase3b/VERDICT_P0_P1.md`
- iron rule #10（significance check FIRST）：`MEMORY.md`

---

**Status**: 2026-07-31 20:20 CST — P-1 + P-3 均已 TDD red→green 闭环修复，待 Nixil commit。

## 📋 修复总结（20:18 CST, 8 min TDD 闭环）

| P# | 问题 | TDD 测试 | 修复 | 验证 |
|---|---|---|---|---|
| P-1 | liveness_probe.py 阈值<cron 周期 → 永久 stale | `test_liveness_probe.py` +2 测试 | warn 20→28h, crit 26→52h (3 log) | Overall: ✅ OK |
| P-3 | portfolio.py 直接 json.dump → 崩溃后截断 JSON | `test_portfolio_atomic.py` +6 测试 | tmp + fsync + os.replace + cleanup | 614 passed, 0 failed |

## 📋 Phase 3 修复总结（20:30-20:55 CST, ~25 min · P2 + P3 TDD 闭环）

| # | 问题 | TDD 测试 | 修复 | 验证 |
|---|---|---|---|---|
| P2#1 | 资金费率 8h 结算无单测 | `test_portfolio_funding.py` +13 测试 | 无代码改动（仅补测试） | 13/13 PASS |
| P2#2 | 4 策略 ABCD 端到端无测试 | `test_strategy_abcd_e2e.py` +7 测试 | 无代码改动（仅补测试） | 7/7 PASS |
| P3#1 | WEB_DASHBOARD §11 v1.3.1 changelog 缺失 | 无（文档补写） | `docs/WEB_DASHBOARD_DESIGN.md` §11（55 行） | 文档完整 |
| P3#3 | systemd-env-proxy skill 3 条教训未沉淀 | skill_workshop proposal | `systemd-env-proxy-on-wsl2-20260731-b38818fc49` (pending apply) | 待 Nixil apply |

**git status 累计（待 Nixil commit）**：
```
okx/code/portfolio.py                       | 43 +++++++++++++++++++++-
okx/scripts/liveness_probe.py               | 18 +++++++++---
okx/tests/test_liveness_probe.py            | 55 ++++++++++++++++++++++++++---
okx/tests/test_portfolio_atomic.py          | 12427 bytes (新增, 6 测试)
okx/tests/test_portfolio_funding.py         | 11589 bytes (新增, 13 测试)
okx/tests/test_strategy_abcd_e2e.py         | 11514 bytes (新增, 7 测试)
okx/docs/WEB_DASHBOARD_DESIGN.md            | +55 行 (§11 v1.3.1 changelog)
```

**Skill proposal（待 Nixil apply）**：
```
skills/systemd-env-proxy-on-wsl2   | proposal 20260731-b38818fc49 (3 new pitfalls: PATH/requirements/source)
```

**全量回归**：634 passed + 2 skipped + 0 failed（baseline 614+2 → +20 新测试，**0 回归**）

**剩余待决**：
- ✅ #P3 #4-C Charts (v1.4 milestone 完成！)
- 🟢 P4 LESSONS #4/#5 (Nixil-only 外部决策)
- 💡 net_pnl 不含 slippage_cost 语义不一致（freeze 生效下不紧急，待 Nixil review）

## 📦 P3 #4-C Charts 实施总结（2026-08-01 01:15 CST, ~30 min）

| 文件 | 状态 | 验证 |
|---|---|---|
| `okx/web/backend/charts.py` | ✅ 新增（7153 bytes）| 4 endpoints: equity-curve / health-timeline / cron-success / catalog |
| `okx/tests/test_charts.py` | ✅ 新增（11277 bytes）| **17/17 PASS** (catalog / data / SSE integration / sort / e2e) |
| `okx/web/backend/app.py` | ✅ 修改（+2 行）| `include_router(charts_router)` |
| `okx/web/frontend/src/pages/Charts.tsx` | ✅ 新增（10305 bytes）| 3 charts: AreaChart + BarChart + Health Summary |
| `okx/web/frontend/src/App.tsx` | ✅ 修改（+6 行）| ChartsPage import + PageId + PAGE_TITLES + items + route |

**全量回归**：**680 passed** + 2 skipped + 0 failed（baseline 663 → +17 chart tests，**0 回归**）

**3 个 chart endpoint 设计**：
- `GET /api/charts/equity-curve?n=90` — portfolio_snapshots.equity_usdt 时序 (PnL LineChart)
- `GET /api/charts/health-timeline?n=100` — health_metrics.level/age_seconds 时序 (drift AreaChart)
- `GET /api/charts/cron-success?n=100` — cron_runs.status 分布按 cron_name 分组 (success-rate BarChart)
- `GET /api/charts/catalog` — chart endpoint 元数据 (供前端动态加载)

**前端 Charts.tsx 设计**：
- 3 个 chart cards (Portfolio Equity Curve + Cron Success Rate + Health Summary)
- Mantine v7 AreaChart / BarChart 组件（已在 deps）
- 时间窗口 selector (30/60/90/180/365 days)
- Badge 显示各 chart data point count
- 4-C SSE integration: 每个 chart endpoint 都调用 `publish_event("chart_update", {...})`

**P3 #4 全部完成**：
- ✅ 4-B SQLite（scaffolding + 集成 + 3 endpoints + 15 测试）
- ✅ 4-A SSE（events.py + sse.py + app.py wire + 3 cron 集成 + 14 测试）
- ✅ 4-C Charts（charts.py + Charts.tsx + app.py wire + 17 测试）

**v1.4 milestone 100% 完成**。三项特性全部端到端跑通。

## 📦 P3 #4-A SSE 实施总结（2026-08-01 00:25 CST, ~30 min）

| 文件 | 状态 | 验证 |
|---|---|---|
| `okx/web/backend/events.py` | ✅ 新增（5859 bytes）| EventBus + publish_event + thread-safe drainer |
| `okx/tests/test_events.py` | ✅ 新增（7985 bytes）| **14/14 PASS** (basic / multi / slow / thread / drain / stats) |
| `okx/web/backend/sse.py` | ✅ 新增（2433 bytes）| FastAPI router: `/api/events/stream` + `/api/events/stats` |
| `okx/web/backend/app.py` | ✅ 修改（+14 行）| `include_router(events_router)` + startup hook |
| `scripts/liveness_probe.py` | ✅ 修改（+21 行）| import events + publish_event on success |
| `scripts/review_push.py` | ✅ 修改（+23 行）| import events + publish_event on success |
| `scripts/heartbeat_push.py` | ✅ 修改（+22 行）| import events + publish_event on success |
| `pytest.ini` | ✅ 修改（+1 行）| `asyncio_mode = auto` |

**全量回归**：**663 passed** + 2 skipped + 0 failed（baseline 614+2 → +49 新测试 = 14 events + 15 db_history + 13 funding + 7 ABCD E2E，**0 回归**）

**架构设计**：
```
[cron thread (sync)]                      [FastAPI event loop (async)]
    publish_event(type, data)                  event_generator:
        ↓ (thread-safe Queue.put)                  queue = event_bus.subscribe()
[thread_queue.Queue (maxsize=1000)]              ↓
        ↓ (drain_loop background task)         event = await queue.get()
[asyncio.Queue per subscriber] → SSE         yield event.to_sse()
```

**关键设计点**：
- **cross-thread 安全**：`publish_from_thread` 用 `threading.Queue` + `asyncio.Queue` 双层缓冲
- **slow consumer drop**：subscriber queue 满时不阻塞 publisher（drop）
- **non-fatal 设计**：cron script 里 publish_event 失败不阻断主流程（try/except）
- **keepalive**：每 30s 发 `: keepalive` 防 nginx/proxy 切断 SSE 连接
- **diagnostics**：`/api/events/stats` 暴露 bus 健康度（published / delivered / dropped 计数）

**P3 #4 进度更新**：
- ✅ 4-B SQLite（scaffolding + 集成 + 3 endpoints + 15 测试）
- ✅ 4-A SSE（events.py + sse.py + app.py wire + 3 cron 集成 + 14 测试）
- ⏳ 4-C Charts（drift / win-rate / P&L 曲线 — 依赖 4-B + 4-A 数据源）

**⚠️ DB bug 已知风险**：cron script 调 `record_health_metric` 时如果 `okx_history.sqlite` 不存在 + `__pycache__` 残留旧 .pyc，会报 `no such table: health_metrics`。**db.py:96 已加自愈**（`get_conn` 自动 `executescript(SCHEMA)`），smoke test 验证 PASS。下次 cron run 应自愈。

**已自动解决（无需 Nixil 决策）**：
- ✅ #2 memory_search — 实际在用 BM25/FTS（provider=none fallback），7-22 stale error 是历史问题，已自愈
- ✅ #P1 Phase 3B VERDICT — Nixil 2026-07-31 21:02 选项 (a) 接受 VERDICT → research-mode freeze 生效
  - `docs/agent-context/strategies.md §10` Constitution §6 已写入
  - 解冻需满足 §10.3 全部 6 项条件

## 📦 P3 #4-B SQLite 实施总结（21:07 CST, 25 min）

| 文件 | 状态 | 验证 |
|---|---|---|
| `okx/web/backend/db.py` | ✅ 新增（10235 bytes） | Schema + write/read helpers + CLI |
| `okx/tests/test_db_history.py` | ✅ 新增（11593 bytes） | **15/15 PASS** (init / write / read / filter / WAL / rollback) |

**Schema（3 表）**：
- `cron_runs` — 每次 cron 执行记录（timestamp / cron_name / status / summary_json / duration_ms / error）
- `portfolio_snapshots` — portfolio 状态时序（equity / position_count / daily_pnl / positions_json / source）
- `health_metrics` — liveness probe 历史（component / level / age_seconds / detail_json）

**Features**：
- WAL mode（并发读 + 单写不阻塞）
- 幂等 `init_db()`（多次调用安全）
- 6 个 write helpers + 4 个 read helpers + 1 个 overview 聚合
- 自动创建 parent dir
- `python3 -m okx.web.backend.db init` CLI 入口

**剩余集成工作**（P3 #4-B 完成度 ≈ 40%）：
- ⏳ `scripts/daily_review.py` 末尾调 `record_cron_run` + `record_portfolio_snapshot`
- ⏳ `scripts/anomaly_diagnosis.py` 末尾调 `record_health_metric`
- ⏳ `okx/web/backend/app.py` 加 3 个 `/api/history/*` endpoint
- ⏳ 健康度告警：DB 写入失败 → Telegram 告警（circuit breaker 模式）
