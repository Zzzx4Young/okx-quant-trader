# docs/ 设计文档索引

> OKX 项目设计文档。系统状态 / 战术知识见 [`../memory/OKX.md`](../memory/OKX.md)，科学输出说明见 [`../data/README.md`](../data/README.md)。
> 本文件只做导航 + 阅读顺序，**不重复 doc 内容**（避免 stale）。

---

## 📖 阅读顺序（新 OKX session 或子任务）

1. **[LESSONS_LEARNED.md](LESSONS_LEARNED.md)** (33KB) — **必读** · 9 条 API 反直觉点 + 撮合 / OKX / 业务坑全套
2. **[WORKFLOW.md](WORKFLOW.md)** — 系统工作流与执行时序（cron + runner + 对账）
3. 按子任务读:
   - **回测改动** → [BACKTEST_DESIGN.md](BACKTEST_DESIGN.md) + [SIGNALS.md](SIGNALS.md)
   - **OKX API 调用** → [OKX-API-v5-Trading-Documentation.md](OKX-API-v5-Trading-Documentation.md)
   - **Telegram 通知** → [NOTIFIER.md](NOTIFIER.md)
   - **Web Dashboard** → [WEB_DASHBOARD_DESIGN.md](WEB_DASHBOARD_DESIGN.md)

---

## 📚 各文件用途速查

| 文件 | 用途 | 何时查阅 |
|---|---|---|
| [BACKTEST_DESIGN.md](BACKTEST_DESIGN.md) | 回测引擎设计（撮合 / tranche fill / 摩擦） | 改撮合 / slippage / fill 逻辑 |
| **[LESSONS_LEARNED.md](LESSONS_LEARNED.md)** | **实战经验沉淀（必读）** | **任何 OKX 工作前先扫一遍** |
| [NOTIFIER.md](NOTIFIER.md) | Telegram 通知层设计 | 改通知逻辑 / 加新事件类型 |
| [OKX-API-v5-Trading-Documentation.md](OKX-API-v5-Trading-Documentation.md) | OKX V5 API 速查 | 写新 API 调用 / 调试 endpoint 行为 |
| [SIGNALS.md](SIGNALS.md) | 3 策略信号精确定义（参数 + 触发条件） | 改策略触发 / 加新策略 |
| [WEB_DASHBOARD_DESIGN.md](WEB_DASHBOARD_DESIGN.md) | Web Dashboard 架构 | 改 dashboard / 加 endpoint / 加 page |
| [WORKFLOW.md](WORKFLOW.md) | 工作流与调度时序 | 理解 cron / runner / watchdog 协作 |

---

## 🔗 跨 README 导航

| README | 定位 | 何时查阅 |
|---|---|---|
| [`okx/README.md`](../README.md) | 项目入口 / 系统状态总览 | 第一次了解项目 |
| [`okx/data/README.md`](../data/README.md) | 科学输出目录说明 (walkforward / phase3b / montecarlo) | 跑 backtest / bootstrap / 查 raw 数据 |
| **`docs/README.md`** (本文件) | 设计文档导航 + 阅读顺序 | OKX 子任务开始时 |
| [`workspace/MEMORY.md`](../../MEMORY.md) | persona + 跨项目元经验 | 每次 main session auto-load |
| [`workspace/memory/OKX.md`](../../memory/OKX.md) | OKX 战术知识（API 速查 / commit 索引 / 业务坑） | OKX 项目工作 session 第一个 tool call |

---

## ❌ 本 README 不覆盖

- **内容摘要**: 各 doc 内容会变，复制会 stale。需要时直接读对应 doc。
- **commit 索引**: 属于 [`workspace/memory/OKX.md`](../../memory/OKX.md)。
- **changelog**: 属于 `git log`。
- **API 反直觉点速查**: 属于 [`workspace/memory/OKX.md`](../../memory/OKX.md) 的 7 条速查（完整 9 条见 [LESSONS_LEARNED.md](LESSONS_LEARNED.md)）。