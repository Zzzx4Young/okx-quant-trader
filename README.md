# OKX 量化交易系统

> 版本：v1.4 | 基于 OKX API v5

一个由 **Market Constitution（明文风控准则）** 驱动的加密货币自动化交易系统。当前激活 **4 个策略**（趋势市右侧 + 震荡市左侧 + 波动率爆发 + 资金费率反转），配合 Telegram 实时通知与 portfolio ↔ OKX 自动对账。

**核心理念**：所有交易决策都来自代码 + 配置（不黑盒），所有凭据走环境变量（LLM 永远看不到明文）。

---

## 📁 项目结构

```
okx/
├── __init__.py                # 包根（v1.4）
├── run.sh                     # CLI 启动脚本（自动加载 .env）
├── .env                       # 凭据（不入版本控制）
├── .gitignore                 # state/* 排除（除 config.json）+ 缓存/日志/备份
│
├── code/                      # 核心代码（20 个 .py）
│   ├── __init__.py            # 顶层 API
│   ├── _http.py               # HTTPClient + 双模式凭据（OKX_LIVE_* / OKX_DEMO_*）
│   ├── client.py              # OKXClient 统一入口
│   ├── cli.py                 # CLI 入口
│   ├── auth.py                # OKX V5 签名（HMAC-SHA256 + base64）
│   ├── market.py              # 市场数据（K 线统一返回 oldest → newest）
│   ├── signal.py              # 信号引擎（4 策略：A/B/C/D）
│   ├── risk.py                # 风控（ATR 止损 + 净 RR + ctVal 计 PnL）
│   ├── portfolio.py           # 持仓 + reconcile_with_okx() 自动对账
│   ├── runner.py              # 交易周期调度（每 5 分钟）
│   ├── notifier.py            # Telegram 通知层（7 类事件 + drift 告警）
│   ├── market_filter.py       # 流动性/黑名单过滤
│   ├── config.py / utils.py / logger.py
│   └── public.py trade.py account.py asset.py subaccount.py
│
├── scripts/                   # 运维工具（9 个）
│   ├── convert_env.py         # 双模式凭据分组解析
│   ├── verify_env.py          # 验证 .env 加载（✓/✗ 不打真值）
│   ├── audit_credentials.py   # 凭据完整性静态审计（mask 输出）
│   ├── test_connection.py     # 公+私 API 连通性 + 延迟
│   ├── sync_portfolio.py      # portfolio ↔ OKX 手动对账
│   ├── test_notifier.py       # Telegram 通知 7 类测试
│   ├── verify_order_chain.py  # 信号→风控→下单 端到端验证
│   ├── daily_summary.py       # 每日报告生成
│   └── runner_watchdog.py     # watchdog 健康检查
│
├── tests/                     # 单元测试（98/98 ✓）
│   ├── conftest.py
│   ├── test_risk.py           # 风控 + 净 RR + 杠杆矩阵
│   ├── test_signal.py         # EMA / RSI / ATR / BB / 策略 C/D
│   ├── test_utils.py          # side / pos_side / time format
│   └── test_constitution.py   # Constitution 配置 + 熔断
│
├── prompts/                   # AI 决策 prompt
│   ├── JOB-DISCIPLINE.md      # 角色定义
│   └── trade-rule.md          # 决断准则（Market Constitution 原文）
│
├── docs/                      # 技术文档
│   ├── OKX-API-v5-Trading-Documentation.md
│   ├── WORKFLOW.md            # 系统工作流
│   ├── SIGNALS.md             # 4 策略信号定义
│   ├── SECURITY.md            # 双模式凭据 + LLM 隔离规范
│   ├── NOTIFIER.md            # Telegram 通知层
│   └── examples/basic_usage.py
│
├── state/                     # 运行时状态（git 跟踪仅 config.json）
│   ├── config.json            # 交易配置（策略/风控参数版本化）
│   └── .gitkeep
│
└── logs/                      # 运行时日志（git 忽略）
    ├── .gitkeep
    └── trades/                # 每日成交 CSV
```

---

## 🚀 快速开始

### 1. 配置 API 凭据（双模式）

```bash
# 编辑 .env，填入 OKX_LIVE_* 和 OKX_DEMO_* 两组凭据
# 选激活模式：OKX_TRADING_MODE=live  或  demo
cp .env.template .env  # 或参考 docs/SECURITY.md 手动创建
chmod 600 .env

# 验证凭据完整性（不打印真值，只审计格式）
./run.sh scripts/audit_credentials.py

# 验证连通性（公+私 API + 延迟）
./run.sh scripts/test_connection.py
```

### 2. 运行交易

```bash
# CLI 运维（人读字符串 / JSON）
./run.sh status            # 系统状态
./run.sh summary           # 组合摘要（JSON）
./run.sh run               # 手动执行一个完整周期（含 SL/TP/趋势反转/对账）

# 手动 portfolio ↔ OKX 对账（当 OKX 持仓跟本地不一致时）
./run.sh scripts/sync_portfolio.py --dry-run
./run.sh scripts/sync_portfolio.py --reason "after_web_manual_trade"

# 紧急熔断
./run.sh stop              # 禁止新开仓
./run.sh resume            # 解除
./run.sh close-all         # 一键平所有持仓
```

### 3. 单元测试

```bash
./run.sh scripts/verify_env.py   # 先验证 env
pytest tests/ -v                 # 98/98 ✓
```

---

## 🛡️ Market Constitution（风控准则）

`state/config.json` + `prompts/trade-rule.md` 定义了一整套明文规则，系统在每个信号/开仓前都会校验：

| 维度 | 规则 |
|---|---|
| **杠杆矩阵** | BTC/ETH 5-10x 按 ATR 动态调整；山寨币 3-5x；高波动资产 0x 禁用 |
| **流动性过滤** | 24h 量 < 5000万 USDT 或 funding \|rate\| > 0.1% → 拦截 |
| **不确定性决策树** | 置信度 < 0.5 → HOLD；偏离最佳入场点 > 1% → 严禁追单 |
| **熔断冷静期** | 连续亏损 ≥ 3 次 → 30 分钟 cooldown |
| **手续费/盈利比** | ratio > 阈值 → 警告 + 提高开仓门槛 |
| **净盈亏比** | 扣除手续费（taker 0.055% × 2）+ 滑点（5bps × 2）后净 RR ≥ 1.5 |
| **三批分级止盈** | 第一批 RR=1:1 平 30%；第二批 RR=1.5:1 平 30%；最后 40% 追踪止盈 |
| **时间止损** | 持仓 > 2h 且未达 1:1 RR → 强制平仓 |

---

## 📈 4 个策略

| ID | 名称 | 适用市况 | 触发条件概要 |
|---|---|---|---|
| **A** | `EMA20_BREAKOUT` | 趋势市右侧 | EMA20 同侧确认 + 量价共振（量比 ≥ 1.2）+ RSI 过滤（不追超买/超卖） |
| **B** | `BB_RSI_REVERSION` | 震荡市左侧 | BB 触轨 + RSI 极值（>70/<30）+ 反转 K 线形态 |
| **C** | `VOLATILITY_BREAKOUT` | 波动率盘整后爆发 | BBW 收缩（双 K 线 BBW < squeeze_threshold）+ 突破 BB 上下轨 + 量能 ≥ 1.5x |
| **D** | `FUNDING_RATE_REVERSAL` | 资金费率极端反转 | funding \|rate\| > 0.05% 持续 + RSI 反向确认 |

详细信号定义见 `docs/SIGNALS.md`。

---

## 🔁 Portfolio ↔ OKX 自动对账

每次 Runner 启动第一步会拉 OKX 真实持仓，跟本地 portfolio 比对：

| 场景 | 处理 |
|---|---|
| 本地有 / OKX 无 | 视为外部平仓 → 归档到 `closed_positions`，写入 OKX history 真实 realizedPnl |
| 本地无 / OKX 有 | 视为手动开仓 → 自动补到本地（含 SL/TP/ctVal/mgn_mode） |
| size/direction 不一致 | 归档旧记录，从 OKX 重建 |

漂移发生时自动调用 `Notifier.notify_drift()` 推 Telegram 告警（需配置 bot token）。

CLI 手动对账：`./run.sh scripts/sync_portfolio.py [--dry-run] [--reason ...]`

---

## 🤖 Telegram 通知（可选）

`.env` 配置：
```bash
TELEGRAM_BOT_TOKEN=<your_bot_token_here>
TELEGRAM_CHAT_ID=<your_chat_id_here>
```

支持 7 类事件：开仓 / 平仓（盈/亏）/ 部分平 / 错误（5min dedup）/ 每日报告 / 心跳 / drift 告警

详见 `docs/NOTIFIER.md`。

---

## ⏰ Cron 调度

| 频率 | 任务 | 方式 |
|---|---|---|
| 每 5 分钟 | Runner 完整周期 | Linux crontab |
| 每天 23:00 | daily_summary | Linux crontab |
| 每天 23:30 | AI 复盘 | OpenClaw cron (isolated + Telegram announce) |
| 每天 00:00 | 异常诊断 | OpenClaw cron |
| 每天 08:00 | 早间心跳 | OpenClaw cron |
| 每 15 分钟 | Runner watchdog | OpenClaw cron |

---

## 🔐 安全

- **凭据隔离**：`.env` 由 `run.sh` 在 shell 层加载，Python 代码只读 `os.getenv`，LLM 永远看不到明文
- **双模式架构**：`OKX_LIVE_*` 和 `OKX_DEMO_*` 隔离，避免误用
- **gitignore**：`.env`、`state/portfolio.json`、`state/sync_history.json`、`state/last_workflow_result.json`、所有日志、Python 缓存
- **状态版本化**：仅 `state/config.json` 入版本控制（策略/风控参数可追溯）
- 详见 `docs/SECURITY.md`

---

## 📚 文档索引

| 文档 | 内容 |
|---|---|
| `docs/WORKFLOW.md` | 系统工作流与执行时序 |
| `docs/SIGNALS.md` | 4 策略信号定义 |
| `docs/NOTIFIER.md` | Telegram 通知层 |
| `docs/SECURITY.md` | 双模式凭据 + LLM 隔离 |
| `docs/OKX-API-v5-Trading-Documentation.md` | OKX V5 API 速查 |
| `prompts/JOB-DISCIPLINE.md` | AI 角色定义 |
| `prompts/trade-rule.md` | Market Constitution 原文 |

---

## ⚠️ 注意事项

1. **模拟盘优先**：`OKX_TRADING_MODE=demo` 验证充分后再切 `live`
2. **K 线方向**：`code/market.py:get_candles` 已统一返回 `oldest → newest`，业务层用 `[-1]` 即可拿到最新
3. **PnL 计算**：使用 OKX `ctVal`（每张合约对应的标的数量）做正确换算（0.55 张 ETH = 0.055 ETH，不是 0.55 ETH）
4. **mgn_mode**：每个仓位按 OKX 实际 `mgnMode`（cross/isolated）调用 close API，避免 51023
5. **demo K 线延迟**：OKX demo 环境 K 线数据可能延迟，趋势判定一律用 ticker 实时价