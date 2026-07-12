# OKX 量化交易系统

> 版本：v1.1.0 | 基于 OKX API v5

一个由定量规则驱动的加密货币自动化交易系统。当前激活策略为 **EMA20 均线突破 + 量价共振 + RSI 过滤**（策略 A），预留 **布林带 + RSI 均值回归**（策略 B）。

---

## 📁 项目结构

```
okx/
├── __init__.py                # 包根（v1.1.0）
├── run.sh                     # CLI 启动脚本（自动加载 .env）
├── .env                       # 凭据（不入版本控制）
├── .gitignore
│
├── code/                      # 核心代码（18 个 .py）
│   ├── __init__.py            # 顶层 API + 暴露 CLI
│   ├── _http.py               # HTTPClient（底层）
│   ├── client.py              # OKXClient（统一入口）
│   ├── cli.py                 # 唯一 CLI 入口
│   ├── auth.py utils.py
│   ├── config.py              # 配置加载
│   ├── portfolio.py logger.py
│   ├── risk.py                # 风控计算器
│   ├── signal.py              # 信号引擎
│   ├── runner.py              # 交易周期调度
│   └── market.py public.py trade.py
│       account.py asset.py subaccount.py
│
├── scripts/                   # 运维工具
│   ├── convert_env.py         # docs/KEY.md → .env
│   ├── verify_env.py          # 验证 .env 加载
│   └── test_connection.py     # API 连通性测试
│
├── tests/                     # 单元测试
│   ├── __init__.py
│   ├── test_risk.py           # RiskCalculator 覆盖
│   └── test_signal.py         # SignalEngine 辅助函数
│
├── prompts/                   # AI 决策 prompt
│   ├── JOB-DISCIPLINE.md      # 角色定义
│   └── trade-rule.md          # 决断准则
│
├── docs/                      # 技术文档
│   ├── OKX-API-v5-Trading-Documentation.md
│   ├── WORKFLOW.md SIGNALS.md SECURITY.md
│   └── examples/basic_usage.py
│
├── state/                     # 运行时状态
│   ├── config.json            # 交易配置
│   ├── portfolio.json         # 持仓快照
│   └── last_workflow_result.json
│
└── logs/trades/               # 每日交易日志 CSV
```

---

## 🚀 快速开始

### 1. 配置 API 凭据

```bash
# 编辑 docs/KEY.md，填入你的 OKX API 凭据
$EDITOR docs/KEY.md

# 生成 .env（不进入版本控制）
./run.sh scripts/convert_env.py

# 验证配置
./run.sh scripts/verify_env.py
```

### 2. 测试连接

```bash
./run.sh scripts/test_connection.py
```

### 3. 运行交易

```bash
# CLI 运维
./run.sh status            # 系统状态（人读字符串）
./run.sh summary           # 组合摘要（JSON）
./run.sh run               # 手动执行一个完整交易周期
./run.sh stop              # 开启紧急熔断
./run.sh resume            # 关闭紧急熔断
./run.sh close-all         # 一键平所有持仓 + 自动熔断

# Python API
python3 -c "from okx.code import OKXClient; print(OKXClient().market.get_ticker('BTC-USDT'))"
```

### 4. 单元测试

```bash
pytest tests/ -v
# 或
python3 -m pytest tests/ -v
```

---

## 🔧 交易配置

`state/config.json` 包含全部可调参数，**在线修改后无需重启**（`Config` 实例会自动 reload）：

```json
{
  "trading": {
    "timeframe": "15m",
    "whitelist_symbols": ["BTCUSDT", "ETHUSDT"],
    "margin_mode": "isolated",
    "default_leverage_main": 5,
    "max_leverage_limit": 10,
    "max_concurrent_positions": 3,
    "emergency_stop": false,
    "demo_mode": true
  },
  "risk": {
    "max_loss_percent_per_trade": 2.0,
    "min_reward_risk_ratio": 1.5,
    "daily_max_loss_trades": 3,
    "sl_buffer_percent": 0.5,
    "atr_multiplier": 2.0,
    "time_stop_hours": 2,
    "slippage_bps": 5,
    "taker_fee_rate": 0.00055
  },
  "strategy_a": {
    "name": "EMA20_BREAKOUT",
    "enabled": true,
    "ema_period": 20,
    "kline_count_for_confirmation": 2,
    "volume_ratio_threshold": 1.2,
    "atr_period": 14,
    "rsi_period": 14,
    "rsi_overbought": 65,
    "rsi_oversold": 35
  }
}
```

---

## 📈 核心交易逻辑

### 策略 A：EMA20 均线突破 + 量价共振（已激活）

| 条件 | 做多 | 做空 |
|------|------|------|
| **价格** | 连续 2 根 K 线收盘价 > EMA20 | 连续 2 根 K 线收盘价 < EMA20 |
| **EMA 方向** | 3 根 K 线斜率由负转正（上翘） | 3 根 K 线斜率由正转负（下拐） |
| **成交量** | ≥ 前 5 均量 × 1.2 | ≥ 前 5 均量 × 1.2 |
| **RSI 过滤** | RSI < 65（不追超买） | RSI > 35（不追超卖） |
| **止损** | ATR14 × 2.0（保底 0.5%） | ATR14 × 2.0（保底 0.5%） |
| **止盈** | 止损距离 × 1.5 | 止损距离 × 1.5 |

**净盈亏比校验**：扣除手续费（taker 0.055% × 2）+ 滑点（5bps × 2）后，净盈亏比仍需 ≥ 1.5。

### 风控规则

- **单笔最大亏损**：账户余额 × 2%
- **杠杆硬上限**：10x（超过即拒绝开仓）
- **连续亏损熔断**：≥ 3 次后禁止新开仓
- **最大同时持仓**：3 个交易对
- **人工熔断**：`emergency_stop` 字段（CLI: `./run.sh stop`）
- **时间止损**：持仓 > 2h 且未达 1:1 盈亏比 → 强制平仓

---

## 🤖 OpenClaw 集成

### Heartbeat 检查

在 `HEARTBEAT.md` 中加入：

```bash
python3 -c "from okx.code import run_heartbeat_check; print(run_heartbeat_check())"
```

### Cron 定时执行

```bash
# 15 分钟 K 线结算点执行（每 15 分钟）
*/15 * * * *  cd /home/zzzx47/.openclaw/workspace && ./okx/run.sh run > /tmp/okx-run.log 2>&1
```

---

## 🧪 开发与测试

### 目录约定

- `code/` — 业务核心（不可放工具脚本）
- `scripts/` — 一次性运维工具
- `tests/` — 单元测试
- `docs/` — 技术文档（人读）
- `prompts/` — AI prompt 工程（机器读）
- `state/` — 运行时持久化（git 跟踪，但人少改）
- `logs/` — 运行时日志（git 忽略）

### 提交规范

- 凭据（`.env`、`docs/KEY.md`）**绝不入版本控制**
- 修改 `state/config.json` 需在 commit message 标注 `config:`
- 修改策略/风控参数需同步更新 `docs/SIGNALS.md` / `prompts/trade-rule.md`

---

## 🔐 安全

- API 凭据隔离：`run.sh` 在 shell 层加载 `.env`，Python 代码只读 `os.getenv`
- LLM 接触不到明文密钥
- 详见 `docs/SECURITY.md`

---

## 📚 文档索引

- **架构**：`docs/WORKFLOW.md`
- **信号定义**：`docs/SIGNALS.md`
- **API 参考**：`docs/OKX-API-v5-Trading-Documentation.md`
- **凭据安全**：`docs/SECURITY.md`
- **AI 角色**：`prompts/JOB-DISCIPLINE.md`
- **AI 决断准则**：`prompts/trade-rule.md`

---

## ⚠️ 注意事项

1. **模拟盘优先**：`OKX_FLAG=1` 是模拟盘，验证充分后再切 `0`
2. **参数调整**：`state/config.json` 在线修改即可生效
3. **日志审计**：`logs/trades/YYYY-MM-DD.csv` 是成交记录唯一来源
4. **紧急熔断**：极端行情下优先 `./run.sh stop` 再排查
5. **P0 重构后**（2026-07-10）：统一 CLI 入口，废弃旧的 `workflow.py` / `run_workflow.py`
