# OKX 量化交易系统

> **版本 v1.8.2** · 基于 OKX API v5 · 396/396 测试通过（其中核心 168+）· 4 策略 + Constitution + 跨策略过滤 + Kelly 动态仓位 + 摩擦校准 + K 线驱动调度

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-1.8.2-orange)](okx/__init__.py)
[![Tests](https://img.shields.io/badge/tests-396%2F396-brightgreen)](tests/)
[![License](https://img.shields.io/badge/license-Proprietary-lightgrey)](LICENSE)

一个由 **Market Constitution（明文风控准则）** 驱动的加密货币自动化交易系统。当前激活 **4 个策略**（趋势右侧 + 震荡左侧 + 波动率爆发 + 资金费率反转），配合 Telegram 实时通知与 portfolio ↔ OKX 自动对账。

**核心理念**：所有交易决策都来自代码 + 配置（不黑盒），所有凭据走环境变量（LLM 永远看不到明文）。

> **English**: This is an OKX V5 API quantitative trading system. Currently Chinese docs (zh-CN); English summary in section 6.

---

## ⚠️ 风险声明（必读）

**量化交易存在重大风险，可能导致全部本金损失。** 本仓库按"原样"提供，作者（[Nixil](https://github.com/Nixil)）**不对任何因使用本项目造成的损失负责**。

- **回测不等于实盘表现**：历史数据有幸存者偏差、滑点、流动性假设
- **先 Demo 后 Live**：默认 demo 模式（OKX 模拟盘），验证 1-2 周再切 live
- **本人已验证**：项目用 OKX 模拟盘 + 历史 20 月 BTC/ETH 数据回测，实盘未投真金
- **不构成投资建议**：fork 开发者自负盈亏

---

## 🏛 架构概览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       OpenClaw 调度层（v1.8.1: 6 个 cron job）           │
│  · signal-runner（每小时 58 分 spinlock 到整点）· watchdog（每 15min）   │
│  · daily-heartbeat · ai-daily-review · anomaly-diagnosis · memory-dream │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ 调用
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Runner (code/runner.py)                              │
│  ① risk.check_strategy_conflict (Constitution §3)  ← v1.8.1 新增       │
│  ② 不确定性决策树 (_conflict_check)                                      │
│  ③ 风控计算仓位 (2% 本金 risk, v1.8.1 可锁 1%)                         │
│  ④ position_limit 拦截 (满仓 3 拒绝新开)                                │
│  ⑤ portfolio ↔ OKX 对账 → ⑤ 通知                                       │
└──┬───────────┬──────────┬─────────────┬─────────────┬────────────────┘
   ▼           ▼          ▼             ▼             ▼
┌────────┐ ┌────────┐ ┌────────┐  ┌──────────┐ ┌────────────────┐
│Market  │ │Signal  │ │Risk    │  │Portfolio │ │Telegram       │
│API v5  │ │Engine  │ │Calc    │  │+ Sync    │ │Notifier        │
│K线/ticker│ A/B/C/D │ + §3 跨策略│ │ OKX v.s.  │ │7 类事件 + dedup│
└────────┘ └────────┘ └────┬───┘  └──────────┘ └────────────────┘
                           │                                 │
                           ▼                                 ▼
                  ┌────────────────────┐          ┌─────────────────┐
                  │ §6.2 friction      │          │  Watchdog       │
                  │ calibration        │          │  (每 15 min)    │
                  │ (Gate 7 实测写回   │          │  + force-run    │
                  │  config.json)      │          │  恢复 worker    │
                  └────────────────────┘          └─────────────────┘
```

**v1.8.1 控制流**：调度层 (cron + watchdog) → Runner（§3 跨策略过滤在前置）→ risk 计算（§6.2 校准参数）→ 5 大模块协作 → 对账触发 OKX 历史拉取 → TelegramNotifier 推 critical。**K 线驱动**：signal_runner 整点 spinlock 完成首轮实证（17:58→18:00 exit 0）。**watchdog**：每 15min 真实告警已实证 5+ 次（BTC 73.7% / EXTERNAL 100%）。

---

## ✨ 核心特性

| 模块 | 能力 |
|---|---|
| **4 个策略** | A EMA 趋势右侧 / B BB+RSI 震荡左侧 / C 波动率爆发 / D 资金费率反转 |
| **多层风控** | Constitution 明文规则：杠杆矩阵 + 流动性过滤 + 熔断冷静期 + 净 RR ≥ 1.5 |
| **跨策略冲突过滤 §3** | A 趋势 vs B 反转同 symbol 反向 → 拒绝新信号，避免多空互弒；强趋势屏蔽 B + 窄幅震荡屏蔽 A |
| **摩擦成本校准 §6.2** | Gate 7 实测滑点 / Lv1 费率自动写入 `config.risk.calibration`，fragility_scan 默认读取 |
| **K 线驱动调度 §4.3** | `signal_runner.py` 每小时 spin-lock 整点毫秒级精度 Runner.run()，cron 注册 + force-run 验证 |
| **三批分级止盈** | 1:1 / 1.5:1 / 2.5:1 RR 分级，每批独立 TP，止损随之上移 |
| **Portfolio 对账** | 本地 vs OKX 自动 reconciliation，drift 告警，外部手动仓 sentinel 保护 |
| **Telegram 通知** | 7 类事件（开/平/部分平/错误/daily/heartbeat/drift），5min dedup。**双写凭证 + restart 修复**（v1.8.1） |
| **回测引擎 v2** | 4 策略 + 2 基准（1x_spot / 5x_leverage 含动态爆仓），完整 metrics + tranche fills |
| **脆弱性扫描** | `fragility_scan.py` N×M slippage×fee 网格 + 实证 Gate 7 N=50 DEMO 验证 avg 5.42 bps |
| **外部仓 Sentinel** | 手动在 OKX Web 开的仓位不会被系统自动平仓（Defense-in-Depth） |
| **Kelly 动态仓位 §3.2** | `calculate_kelly_size()` 经典 Kelly + Fractional 1/4 + 波动率缩仓 + `kelly_sizing_decision()` 纯决策包装 + Runner 集成 (v1.8.2)。Negative EV → 自动拒绝（C 策略正面启用，B 策略 BTC 1h 27.8% WR → Kelly 拒绝，与 fragility_scan 结论一致）|
| **Micro-Live 锁参数 §5.2** | 杠杆锁 3x、单笔锁 1% 本金（路线图 Phase 5 准备） |
| **396 单测** | pytest 全过（28 Kelly sizing + 13 Kelly decision + 15 portfolio stats + 32 §3 冲突 + Constitution 配置 + calibration + A+C double-lock 回归） |

---

## 🚀 5 分钟快速开始（fork 开发者向）

### 1. 系统要求

- Python **3.8+** （推荐 3.10+）
- OKX 账户（[注册](https://www.okx.com)，需完成 KYC）
- OKX **API v5 key**（在 OKX 账户 → API 管理创建，**重要**：trade 权限勾选；IP 白名单可选）
- Linux / macOS / WSL2（已在 Windows 11 + WSL2 Ubuntu 验证）
- ⚠️ **中国大陆用户**：OKX API 偶发 GFW 阻断，建议准备 HTTP/SOCKS 代理（参看 [§代理](#-gfw--代理配置中国大陆用户)）

### 2. Clone + 安装

```bash
git clone https://github.com/Nixil/okx-quant-trading.git
cd okx-quant-trading
pip install -e ".[dev]"   # 安装运行时 + dev 测试依赖
```

或仅运行时：
```bash
pip install -r requirements-min.txt  # 见下方"依赖"
```

### 3. 配 API 凭据

```bash
# 1. 复制模板（fork 开发者拿到手就有）
cp .env.example .env

# 2. 编辑 .env，把 <your_…ere> 占位符替换为真实 OKX API 三件套
#    OKX_DEMO_*  → https://www.okx.com/demotrading 子账户创建
#    OKX_LIVE_*  → OKX 主账户 → API 管理创建（**先用 demo 跑 1 周再开 live**）
chmod 600 .env

# 3. 验证凭据完整性（不打印真值，只审计格式）
./run.sh scripts/audit_credentials.py

# 4. 验证连通性（公 + 私 API + 延迟）
./run.sh scripts/test_connection.py
```

**关键设计**：所有真值凭据**永远不**进 git（`.env` 已 gitignore）—— `.env` 是程序读的环境变量源，Python 通过 `os.getenv()` 间接读取，LLM 永远看不到明文。

### 4. 第一次跑（Demo 模式安全）

```bash
# Demo 模式（默认）—— 不动真金
./run.sh status                  # 系统状态：持仓/熔断/连续亏损
./run.sh summary                 # portfolio JSON 摘要

# 单元测试（验证环境 + 代码）
pytest tests/ -v                 # 应输出 111 passed

# 跑一个完整交易周期（含对账）
./run.sh run

# 手动 portfolio ↔ OKX 对账（如你在 OKX Web 手动开过仓）
./run.sh scripts/sync_portfolio.py --dry-run   # 先 dry-run 看会发生什么
./run.sh scripts/sync_portfolio.py --reason "after_web_manual_trade"
```

### 5. 切换到 Live（**等你充分验证 demo 后**）

```bash
# 编辑 .env，把 OKX_TRADING_MODE 改成 live
# ⚠️ 务必先用 demo 跑至少 7 天

# ⚠️ 切换前 checklist：
#  ✓ demo 跑满 7+ 天无 emergency_stop 触发
#  ✓ 连续亏损熔断未触发（默认 3 次 / 30min cooldown）
#  ✓ Telegram 通知能收到（用 TELEGRAM_ENABLED=true 测试）
#  ✓ 04:00 UTC 自动日切，你观察过 daily_summary
#  ✓ portfolio 对账无 ghost/mismatch（state/sync_history.json）
```

---

## ⚙️ 配置详解

### `.env`（双模式必填）

| 字段 | 是否必填 | 说明 |
|---|---|---|
| `OKX_API_KEY / SECRET / PASSPHRASE` | ✅（demo） | **旧版**单模式字段，仍兼容 |
| `OKX_DEMO_API_KEY / SECRET / PASSPHRASE` | ✅ | 模拟盘三件套（在 OKX demotrading 子账户创建） |
| `OKX_LIVE_API_KEY / SECRET / PASSPHRASE` | ⚠️ 切 live 时 | 实盘三件套（**慎用**——必先 demo 验证） |
| `OKX_TRADING_MODE` | ✅ | `demo` 或 `live`，**默认 demo** |
| `HTTPS_PROXY` / `HTTP_PROXY` | 可选 | 大陆用户绕过 GFW 阻断（参看 [§代理](#)） |
| `TELEGRAM_BOT_TOKEN` | 可选 | @BotFather 创建的 bot token |
| `TELEGRAM_CHAT_ID` | 可选 | 接收通知的 chat id（个人或群组） |
| `TELEGRAM_ENABLED` | 可选 | 默认 `true`，设为 `false` 关闭通知 |

完整字段参考 `scripts/audit_credentials.py` 输出。

### `state/config.json`（git 追踪，**策略/风控参数**版本化）

完整字段示意（**改前请读 Constitution**）：
```json
{
  "version": "1.7.0",
  "trading": {
    "timeframe": "15m",                       // K 线周期
    "whitelist_symbols": ["BTCUSDT", "ETHUSDT"],
    "margin_mode": "isolated",                 // isolated or cross
    "default_leverage_main": 5,               // 主币默认杠杆
    "max_leverage_limit": 10,
    "max_concurrent_positions": 3,
    "emergency_stop": false
  },
  "risk": {
    "max_loss_percent_per_trade": 2.0,
    "min_reward_risk_ratio": 1.5,             // 净 RR（含手续费）
    "daily_max_loss_trades": 3,
    "sl_buffer_percent": 0.5,
    "atr_multiplier": 2.0,
    "time_stop_hours": 2,
    "slippage_bps": 5,
    "tp_partial_ratios": [0.30, 0.30, 0.40]
  },
  "leverage_matrix": { "BTC": {...}, "ETH": {...}, ... },
  "blacklist": { "min_24h_volume_usdt": 50000000, ... },
  "audit": { "max_consecutive_losses": 3, ... }
}
```

详细每个字段的语义见 `state/config.json` 注释 + Constitution。

---

## 🌐 GFW / 代理配置（中国大陆用户）

OKX API / Telegram Bot API 在大陆偶发 connection refused / 30s timeout。**症状**：`runner.log` 持续 `Connection to www.okx.com timed out`。

**推荐方案**（systemd-managed daemon）：

```bash
mkdir -p ~/.config/systemd/user/<service>.service.d/
cat > ~/.config/systemd/user/<service>.service.d/proxy.conf <<'EOF'
[Service]
Environment=HTTPS_PROXY=http://127.0.0.1:10809
Environment=HTTP_PROXY=http://127.0.0.1:10809
Environment=ALL_PROXY=socks5h://127.0.0.1:10809
Environment=NO_PROXY=localhost,127.0.0.1
EOF
systemctl --user daemon-reload && systemctl --user restart <service>
```

项目自身的 cron jobs（如 okx-runner-watchdog）走 OpenClaw 内置支持，需在 OpenClaw 配置层加 proxy env。

---

## 📊 4 个策略详解

| ID | 名称 | 适用市况 | 触发条件概要 |
|---|---|---|---|
| **A** | `EMA20_BREAKOUT` | 趋势市右侧 | EMA20 同侧确认 + 量比 ≥ 1.2 + RSI 过滤 |
| **B** | `BB_RSI_REVERSION` | 震荡市左侧 | BB 触轨 + RSI 极值（>70/<30）+ 反转 K 线 |
| **C** | `VOLATILITY_BREAKOUT` | 波动率盘整后爆发 | BBW 收缩 + 突破 BB 上下轨 + 量能 ≥ 1.5x |
| **D** | `FUNDING_RATE_REVERSAL` | 资金费率极端反转 | funding \|rate\| > 0.05% 8h 持续 + RSI 反向 |

详细信号定义 + 回测结论见 `docs/SIGNALS.md` 和 `docs/BACKTEST_DESIGN.md`。

---

## 🧪 回测 (Phase 2 milestone)

> v1.6 → v1.7 重要里程碑：4 策略 + 2 基准全跑，撮合引擎无回归。

### 一键实验

```bash
python3 -u -m okx.code.backtest.run_phase2_experiment \
  --inst-ids BTC-USDT-SWAP ETH-USDT-SWAP \
  --timeframe 1h
```

### 实测结果（BTC 1h, 20 月数据）

| 策略 | 收益 | Sharpe | Trades | 评价 |
|---|---|---|---|---|
| **C_VOLATILITY_BREAKOUT** | **+2.87%** | **+0.208** | 47 / 62 tranche | ✅ 真 alpha（跑赢 buy-hold -6.49%） |
| A_EMA20_BREAKOUT | +1.21% | +0.119 | 32 | 勉强正 alpha |
| B_BB_RSI_REVERSION | **-37.16%** | **-1.950** | 30 | ⚠️ 大牛市反策略被止损；需 trend filter |
| D_FUNDING_RATE_REVERSAL | +0% | 0 | 0 | ⚠️ 1h 频率不适合（funding 太稀疏） |
| **[BENCH] 1x_spot** | -6.49% | +0.145 | — | 现货基准 |
| **[BENCH] 5x_leverage** | -32.43% | +0.682 | — | BTC 杠杆基准（含动态爆仓） |

### ETH 1h, 20 月

| 策略 | 收益 | Sharpe | Trades |
|---|---|---|---|
| C_VOLATILITY_BREAKOUT | -1.19% | +0.039 | 47 |
| [BENCH] 5x_leverage | **-100% (爆仓)** @bar 3242 | -178 | — |

**关键发现**：
- **C 是唯一可靠的真 alpha**（建议先 C 上 LIVE）
- A 勉强，B/D 在当前参数 + 1h 频率下不可用
- 5x 杠杆基准在 ETH 暴跌时爆仓 → 动态爆仓模拟正确

详细 + 撮合 bug 修复过程见 `okx/docs/LESSONS_LEARNED.md` §9。

---

## 🔁 Portfolio ↔ OKX 自动对账

每次 Runner 启动第一步拉 OKX 真实持仓，跟本地 portfolio 比对：

| 场景 | 处理 | 备注 |
|---|---|---|
| 本地有 / OKX 无 | 视为外部平仓 → 归档到 `closed_positions` | 拉 OKX history 真实 realizedPnl |
| 本地无 / OKX 有 | 视为手动开仓 → 补到本地（**sl/tp 哨兵 = 0**，strategy = `MANUAL_NO_AUTO_CLOSE`） | 防止系统自动平仓 |
| size/direction 不一致 | 归档旧记录 + 从 OKX 重建 | drift 告警 |

**为什么 sentinel = 0**：fork 开发者如果在 OKX Web 手动开过仓，sync 时**绝不能**自动套 SL/TP——之前 v1.6 有 footgun（24h 内误平仓 -3.99 USDT），v1.7 已用 Defense-in-Depth 修复（A+C double-lock）。

**手动对账**（救命）：
```bash
./run.sh scripts/sync_portfolio.py --dry-run --reason "investigation"
# 看完没问题去掉 --dry-run 真正执行
```

---

## 🔔 Telegram 通知（可选但推荐）

**强烈建议配置**：watchdog / emergency_stop / drift 等关键事件错过等于盲飞。

```bash
# .env 加：
TELEGRAM_BOT_TOKEN=1234567890:AAH...     # @BotFather
TELEGRAM_CHAT_ID=7703161528                # 你的 chat id
TELEGRAM_ENABLED=true
```

**7 类事件**：

| 事件 | 触发时机 | 示例 |
|---|---|---|
| `notify_open` | 系统开仓 | "🟢 LONG BTC 0.5 张 @ 50000" |
| `notify_close` | 平仓（盈/亏） | "✅ +12.5 USDT (RR 2.0)" |
| `notify_partial_close` | 部分平（三批止盈） | "TP-1:1 平 30%" |
| `notify_error` | 错误（5min dedup） | "Cannot connect to proxy" |
| `notify_daily_summary` | 每日 23:00 (Asia/Shanghai) | 净盈亏 / 持仓 / 风控状态 |
| `notify_heartbeat` | 每 30 分钟 | "持仓 2/3, 连续亏损 0" |
| `notify_drift` | portfolio 对账漂移 | "本地 vs OKX size 不一致" |

详见 `docs/NOTIFIER.md`。

---

## ⏰ 调度方式（v1.8.1 推荐 OpenClaw cron · 6 job 全 active）

### v1.8.1 活跃 cron 清单（`~/.openclaw/cron/jobs.json`）

| Job name | Schedule | Purpose | Delivery | 验证状态 |
|---|---|---|---|---|
| **`okx-signal-runner`** | `cron 58 * * * *` Asia/Shanghai | 信号 Runner 整点 spinlock + Runner.run() | telegram announce | ✅ 18:00 exit 0 首轮实证 |
| `okx-runner-watchdog` | `every 15m` | 7 类健康检查 + 自动告警 | telegram announce | ✅ 18:03 CRITICAL 已发送 |
| `okx-daily-heartbeat` | `cron 0 21 * * *` | 每日 21:00 日切对账 | telegram announce | ✅ |
| `okx-ai-daily-review` | `cron 30 23 * * *` | AI 每日复盘 + 改进建议 | telegram announce | ✅ |
| `okx-anomaly-diagnosis` | `cron 0 0 * * *` | 异常检测 + 诊断 | telegram announce | ✅ |
| `okx-memory-dreaming` | `cron 0 3 * * *` | long-term memory promotion | not requested | ✅ |

查看实时状态：`openclaw cron list` / `openclaw cron get <jobId>` / `openclaw cron runs --id <jobId>`。

### 备选调度方式（未推荐，v1.8.1 后首选 OpenClaw cron）

| 方式 | 适用场景 | 配位置 |
|---|---|---|
| Linux crontab | 纯服务器 + 不要 watchdog | `crontab -e`，示例：`58 * * * * cd /path/to/okx && bash run.sh signal_runner.py --timeframe 1h` |
| 手动 | 调试 / 验证 | `bash run.sh signal_runner.py --timeframe 1h --no-spin` |

### v1.8.1 K 线驱动精度的关键设计
- **spinlock 5s**：整点前 5 秒进入 busy-wait（`spinlock_until()`），避免 sleep 不精确
- **2m42s 冷启动预算**：cron 提前 2 分钟触发，预热 numpy/pandas/OKXClient 需 ≤ 162s
- **首次走通实证**：2026-07-18 17:58 触发 → 18:00 整点 spinlock 完成 → Runner.run() exit 0
- **force-run 救援**：cron worker 被 gateway restart 打断时，手动 `openclaw cron run <id>` 重置 worker
| **AI agent 触发** | 跟对话助手集成 | OpenClaw LLM 直接调 `bash run.sh` |

⚠️ **别同时跑多个调度**——会导致 portfolio.json 并发写，产生 data race。

---

## 🛡 安全模型（关键设计）

### 凭据隔离（单层 .env）

```
.env (用户维护，chmod 600，gitignore)
   ↓ run.sh 加载到 shell 环境变量
os.environ  (Python 只读 via os.getenv，绝不 print)
   ↓ _http.py 按 OKX_TRADING_MODE 选 OKX_DEMO_* / OKX_LIVE_*
OKX REST API
```

**核心原则**：
- `.env` 已 gitignore，**永不**入仓
- Python 代码**只**通过 `os.getenv()` 读取凭据，LLM 在 agent context 中看不到明文
- 双模式凭据 `OKX_LIVE_*` 和 `OKX_DEMO_*` 隔离存储，由 `OKX_TRADING_MODE` 切换激活
- 无 convert 工具、无 KEY.md 草稿层——单一来源原则

### 变量命名约定

| 变量 | 含义 |
|---|---|
| `OKX_DEMO_API_KEY / SECRET / PASSPHRASE` | 模拟凭据（在 `https://www.okx.com/demotrading` 创建） |
| `OKX_LIVE_API_KEY / SECRET / PASSPHRASE` | 实盘凭据（OKX 主账户 → API 管理）。**先用 demo 跑 1 周再开 live** |
| `OKX_TRADING_MODE` | `demo`（默认）或 `live` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram 通知（可选，强烈推荐） |
| `TELEGRAM_ENABLED` | `true` / `false`，默认 `true` |
| `HTTPS_PROXY` / `HTTP_PROXY` | GFW 代理（中国大陆用户，需同时配 systemd drop-in） |

### 旧版兼容

`OKX_API_*` 旧变量在 **demo 模式**下仍可用（仅当 `OKX_DEMO_*` 缺失时回退）。迁移完成后建议删除。

### 凭据轮换

```bash
# 1. OKX 平台创建新 key + 作废旧 key
# 2. 编辑 .env 更新对应 *_API_KEY / _SECRET / _PASSPHRASE
# 3. 重启 runner（自动重新加载）
./run.sh run
```

### 故障兜底（错 → 修）

| 症状 | 原因 | 修复 |
|---|---|---|
| `Connection to www.okx.com timed out` | 大陆直连 GFW 阻断 | 配 `HTTPS_PROXY` 环境变量 + systemd drop-in |
| `401 Unauthorized` | key 错或已过期 | OKX 平台重置 key → 更新 `.env` |
| `50101 demo / live 互不可见` | mode 切错 | 检查 `OKX_TRADING_MODE` 与 key 前缀匹配 |
| `.env file not found` | 第一次没 cp 模板 | `cp .env.example .env` |
| TelegramNotifier "disabled" | bot_token 或 chat_id 缺失 | `.env` 加 `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |

### _http.py 凭据解析顺序（了解即可，外部无须配置）

```python
# 1. 显式构造参数（覆盖 env）
# 2. env OKX_TRADING_MODE → 选 OKX_LIVE_* 或 OKX_DEMO_*
# 3. (仅 demo 模式) 兜底读取 OKX_API_* (旧版兼容)
```

### 风控承诺

- ✅ 每笔信号过 Constitution（杠杆 + 流动性 + 净 RR）
- ✅ 连续亏损 ≥ 3 → 30min cooldown
- ✅ portfolio 对账漂移立即告警
- ✅ 紧急熔断（`./run.sh stop` / `state/config.json: emergency_stop=true`）

### ⚠️ 给 fork 开发者的安全提醒

1. **别把 `.env` 推到任何地方**（gitignore 已配，但你也要确保 IDE 不自动同步）
2. **Demo 跑满 1 周再 Live**——这是 v1.7 的硬性建议
3. **OKX API key 权限最小化**：trade 即可，**不要勾 withdrawal**（提币权限）
4. **IP 白名单**：OKX 支持，强烈建议在创建 key 时配你的服务器 IP

---

## 📚 文档索引

| 文档 | 内容 |
|---|---|
| **[docs/SIGNALS.md](docs/SIGNALS.md)** | 4 策略信号精确定义（参数 + 触发条件） |
| **[docs/WORKFLOW.md](docs/WORKFLOW.md)** | 系统工作流与执行时序 |
| **[docs/BACKTEST_DESIGN.md](docs/BACKTEST_DESIGN.md)** | 回测引擎设计文档 |
| **[docs/NOTIFIER.md](docs/NOTIFIER.md)** | Telegram 通知层 |
| **[docs/LESSONS_LEARNED.md](docs/LESSONS_LEARNED.md)** | 33KB 实战经验沉淀（必读） |
| **[docs/OKX-API-v5-Trading-Documentation.md](docs/OKX-API-v5-Trading-Documentation.md)** | OKX V5 API 速查 |
| **[prompts/trade-rule.md](prompts/trade-rule.md)** | Market Constitution 原文 |
| **[prompts/JOB-DISCIPLINE.md](prompts/JOB-DISCIPLINE.md)** | AI agent 角色定义 |

---

## 🧑‍💻 开发 & 贡献

### 跑测试

```bash
# 全部测试（111 个）
pytest tests/ -v

# 单类
pytest tests/test_risk.py -v
pytest tests/test_runner_filter.py -v   # v1.7 新增 A+C double-lock 13 个 case

# 覆盖率
pytest tests/ --cov=okx.code --cov-report=term-missing
```

### 代码风格

```bash
# Lint（ruff）
ruff check code/ tests/

# 类型检查（mypy）
mypy okx/code/

# 提 PR 前的 checklist
#  ✓ pytest 全过
#  ✓ ruff 无警告
#  ✓ 重大改动同步更新 docs/LESSONS_LEARNED.md
#  ✓ 新增策略同步更新 docs/SIGNALS.md + state/config.json schema
```

### 贡献方向（欢迎 PR）

- **新策略适配器**：在 `code/backtest/STRATEGIES` dict 注册 + 写 `docs/SIGNALS.md` + 加 `test_signal.py` case
- **新 OKX 市场**：`whitelist_symbols` 加新 symbol，配 `leverage_matrix`，加 `tests/`
- **新通知渠道**（Discord / Slack）：扩展 `code/notifier.py` 接口

### Architecture Decision Records (ADR)

重大架构决策写进 `docs/LESSONS_LEARNED.md`，不要散落各处。

---

## ❓ 常见问题

**Q: 回测显示策略 C 真 alpha，多久能上 live？**
A: 建议流程 — Demo 1 周 + 小仓位 live 1 周 + 全仓 live。**v1.7 默认 demo 模式**。

**Q: 同步 portfolio 时会不会把我 Web 开的仓位自动平掉？**
A: 不会。v1.7 已用 A+C double-lock 修复：sync 端设 sentinel（`sl_price=0, tp_price=0`），runner 端 strategy 白名单 + 哨兵双重过滤。手动仓被识别为 `MANUAL_NO_AUTO_CLOSE`，系统永不动。详见 [§Portfolio 对账](#-portfolio--okx-自动对账)。

**Q: 没有 OKX 账户能跑吗？**
A: 可以跑测试 + 回测 + dry-run，但不连 OKX API 就只能离线运行。**模拟盘必须用 OKX demotrading 的真实 API 三件套**。

**Q: 多个交易系统实例能跑同一个 OKX 账户吗？**
A: 不建议——同一个 OKX API key 跨多个实例会触发 portfolio race condition。**严格 1 实例 1 key**。

**Q: AI agent / LLM 帮我管这个项目安全吗？**
A: 安全（这是设计核心）：所有凭据走 `os.getenv`，LLM 看不到明文；所有交易决策来源于代码 + 配置（不黑盒）。但**你仍然需要人工盯 emergency_stop 信号**——AI 不能替你承担 trade-off。

---

## ⚖️ License

**Proprietary**（截至 v1.7）。详细许可条款待定（参见 [LICENSE](LICENSE)（如有））。

---

## 🙏 致谢

- **OKX 团队**：提供稳定 V5 API
- **回测社区**：pandas / numpy 栈让 1h × 20 月 backtest < 1 分钟
- **所有 fork 贡献者**：你的 issue / PR 让这个项目更鲁棒

---

## 📜 版本历史

| 版本 | 日期 | 关键变更 |
|---|---|---|
| **v1.8.2** | **2026-07-18** | **Constitution §3.2 Kelly Criterion 动态仓位 (`calculate_kelly_size` + `kelly_sizing_decision` + Runner 集成)。经典 Kelly 公式 + Fractional 1/4 + 波动率缩仓 × 0.7。Negative EV → 自动拒绝（C 策略正面启用，B 策略 BTC 1h 27.8% WR / b=1.5 → f_full=-0.20 → 必须拒绝，与 fragility_scan 结论一致）。Hard cap 永远不破 Constitution §5 (1% 本金/笔)。56 个新单测（28 sizing + 13 decision + 15 portfolio stats）；总测试 396/396。** |
| **v1.8.1** | **2026-07-18** | **Constitution §3 跨策略冲突过滤（A↔B 反向 + 强趋势屏蔽 B + 窄幅震荡屏蔽 A）+ 32 单测 + runner 集成；§6.2 摩擦成本自动写回 config（Gate 7 实测 slip=5.42 bps / fee=5 bps）；§4.3 K 线驱动 cron（signal_runner.py spinlock 实证 18:00 exit 0）；§5.2 Micro-Live 锁参数（杠杆锁 3x + 单笔锁 1%）；Gate 7 DEMO N=50 滑点验证（avg 5.42 / p95 7.99）；Telegram token 双写 + restart 修复（14:03）；side-agent watchdog force-run 修复 CronSessionLifecycleClaimError；清理废弃 code/reference/；安全修复 tests/test_rotate_telegram_key.py token 占位符** |
| v1.7 | 2026-07-15 | A+C double-lock 修复外部仓 auto-close footgun（-3.99 USDT 事故）+ Phase 2 4 策略回测 milestone + cron noise 砍 + systemd drop-in |
| v1.6 | 2026-07-13 | portfolio 对账 + ctVal / mgn_mode bug 修复 |
| v1.5 | 2026-07-12 | 三层错误响应 / Constitution 1.0 |
| v1.4 | 2026-07-11 | 双模式凭据 + Constitution 风控 + 8 个 cron 配置 |
| ... | ... | 见 git log |

---

_最后更新：2026-07-18 v1.8.1_
