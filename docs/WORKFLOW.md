# OKX 交易系统工作流定义

> 版本：v1.0 | 更新：2026-06-28

---

## 1. 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                       OpenClaw 调度层                             │
│                                                                  │
│   ⏰ Cron Job (可选定时)                                         │
│   💓 Heartbeat (每 30 分钟)  ──→ heartbeat_check()              │
│   👤 人工触发 (CLI / 直接对话)                                    │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 调用
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Runner (runner.py)                             │
│                                                                  │
│   ① 前置风控检查                                                  │
│      ├─ emergency_stop？ → 拒绝                                   │
│      ├─ 连续亏损熔断？ → 拒绝                                     │
│      └─ 持仓已达上限？ → 拒绝                                     │
│                                                                  │
│   ② 检查持仓状态（check_and_close_positions）                    │
│      ├─ 触发 SL → 市价平仓                                       │
│      ├─ 触发 TP → 市价平仓 50%                                   │
│      └─ 趋势反转 → 市价平仓                                       │
│                                                                  │
│   ③ 信号检测与开仓（run）                                         │
│      ├─ 获取 15m K线数据                                         │
│      ├─ 计算 EMA20                                               │
│      ├─ 量价共振检测                                             │
│      └─ 通过风控 → 下单                                           │
└────────────────────────────┬─────────────────────────────────────┘
                             │ 更新
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                      状态管理层                                    │
│                                                                  │
│   state/portfolio.json    ←──  持仓记录 + 日统计                   │
│   state/config.json      ←──  全局配置（emergency_stop 等）        │
│   logs/trades/YYYY-MM-DD.csv ← 每笔交易记录                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 触发机制

### 2.1 Heartbeat 触发（主要方式）

OpenClaw 每 30 分钟发送一次心跳，进入 `heartbeat_check()`：

```
Heartbeat 到达
    │
    ├─ 读取 state/config.json 的 emergency_stop
    │       └─ True → 输出警告，拒绝新开仓
    │
    ├─ 读取 state/portfolio.json 的 daily_stats
    │       └─ 连续亏损 ≥ 3 → 熔断状态
    │
    ├─ 如果到达 15m 结算点（00/15/30/45 分）：
    │       └─ 执行 run_trading_cycle()
    │
    └─ 输出状态摘要（持仓数 / 今日盈亏 / 是否熔断）
```

### 2.2 人工干预

| 操作 | 命令 | 说明 |
|------|------|------|
| 开启熔断 | `python -m okx.code.openclaw_integration stop` | 禁止所有新开仓 |
| 关闭熔断 | `python -m okx.code.openclaw_integration resume` | 恢复交易 |
| 一键平仓 | `python -m okx.code.openclaw_integration close-all` | 平掉所有持仓 + 开启熔断 |
| 查看状态 | `python -m okx.code.openclaw_integration status` | 系统状态摘要 |
| 执行交易 | `python -m okx.code.openclaw_integration run` | 手动执行完整交易周期 |

---

## 3. 完整交易周期流程

### 阶段 1：持仓检查与平仓（每次 Heartbeat 都执行）

```
for each 持仓 in portfolio.positions:
    │
    ├─ 获取当前行情（market.get_ticker）
    │
    ├─ 检查止损：价格触及 sl_price？
    │       └─ 是 → 市价平仓，记录日志
    │
    ├─ 检查止盈：价格触及 tp_price？
    │       └─ 是 → 市价平仓 50%，剩余仓位上移止损
    │
    ├─ 检查趋势反转（EMA20）：
    │       └─ 反转 → 市价全平
    │
    └─ 时间止损：持仓 > 2 小时且盈亏比 < 1:1？
            └─ 是 → 强制平仓
```

### 阶段 2：信号检测与开仓（仅 15m K 线走完时执行）

```
① 获取所有白名单交易对（BTCUSDT / ETHUSDT）
│
② for each 交易对:
│   ├─ 获取最新 30 根 15m K线
│   ├─ 计算 EMA20
│   │
│   ├─ 做多信号：
│   │   ├─ 连续 2 根收盘价 > EMA20
│   │   ├─ EMA20 由降转升（上翘）
│   │   └─ 成交量 > 前 5 均量 × 1.2
│   │
│   ├─ 做空信号：
│   │   ├─ 连续 2 根收盘价 < EMA20
│   │   ├─ EMA20 由升转降（下拐）
│   │   └─ 成交量 > 前 5 均量 × 1.2
│   │
│   └─ 无信号 → 跳过
│
③ 对每个信号执行风控计算：
│   ├─ 获取账户可用余额
│   ├─ 计算最大可开仓位（2% 风险）
│   ├─ 计算 SL（±0.5%）
│   ├─ 计算 TP（SL × 1.5）
│   └─ 杠杆校验（≤ 10x）
│
④ 下单（市价单 + 附加 SL/TP）
│
⑤ 更新 portfolio.json
│
⑥ 记录开仓日志到 CSV
```

---

## 4. 决策输出格式

Runner 输出标准 JSON 结果：

```json
{
  "timestamp": "2026-06-28T13:45:00Z",
  "tick": true,
  "signal_checked": true,
  "signal_triggered": true,
  "actions": [
    {
      "signal": {
        "strategy": "EMA20_BREAKOUT",
        "symbol": "BTCUSDT",
        "direction": "long",
        "entry_price": 61000.0,
        "sl_price": 60695.0,
        "tp_price": 61977.5,
        "leverage": 5,
        "confidence": 0.85,
        "reason": "EMA20上穿 + 放量突破（成交量 1.5x 均量）"
      },
      "risk": {
        "max_size": 1.0,
        "max_margin": 121.0,
        "sl_price": 60695.0,
        "tp_price": 61977.5,
        "rr_ratio": 1.5,
        "passed": true
      },
      "order": {
        "order_id": "1234567890",
        "avg_price": 61002.5,
        "filled_sz": 1
      },
      "status": "success",
      "position_record": {
        "symbol": "BTCUSDT",
        "direction": "long",
        "size": 1.0,
        "entry_price": 61002.5,
        "leverage": 5,
        "sl_price": 60695.0,
        "tp_price": 61977.5,
        "order_id": "1234567890",
        "trigger_strategy": "EMA20_BREAKOUT",
        "opened_at": "2026-06-28T13:45:00Z"
      }
    }
  ],
  "errors": []
}
```

---

## 5. 状态文件说明

### `state/config.json`（全局配置）

| 字段 | 类型 | 说明 |
|------|------|------|
| `emergency_stop` | bool | 人工熔断开关（True = 禁止所有新开仓） |
| `max_concurrent_positions` | int | 最大同时持仓数（默认 3） |
| `demo_mode` | bool | 是否模拟盘模式 |

### `state/portfolio.json`（持仓状态）

| 字段 | 类型 | 说明 |
|------|------|------|
| `positions` | array | 当前持仓列表 |
| `daily_stats` | object | 当日统计数据 |
| `closed_positions` | array | 已平仓记录（当日） |

---

## 6. 日志文件说明

`logs/trades/YYYY-MM-DD.csv`

| 字段 | 说明 |
|------|------|
| timestamp | 成交时间（UTC） |
| symbol | 交易对 |
| direction | long / short |
| action | OPEN / CLOSE |
| price | 成交价格 |
| size | 成交数量 |
| leverage | 杠杆倍数 |
| margin | 保证金 |
| order_id | 订单 ID |
| strategy | 策略名称 |
| pnl | 盈亏金额 |
| roe_percent | 收益率% |
| fee | 手续费 |
| slippage | 滑点估算 |
| pnl_net | 净盈亏（pnl - fee - slippage） |
| note | 备注 |

---

## 7. 风险控制流程

```
开仓请求
    │
    ├─ 杠杆 > 10x？  → 硬上限拦截 ❌
    │
    ├─ emergency_stop = True？ → 熔断拦截 ❌
    │
    ├─ 连续亏损 ≥ 3 次？ → 熔断拦截 ❌
    │
    ├─ 持仓数 ≥ 上限？ → 持仓上限拦截 ❌
    │
    ├─ 盈亏比 < 1.5？ → 风控拦截 ❌
    │
    └─ 通过全部检查 → 下单 ✅
```

---

## 8. 初始化流程（系统启动时）

```
1. 加载 state/config.json
       └─ 检查 demo_mode / emergency_stop
2. 加载 state/portfolio.json
       └─ 检查 daily_stats（跨日重置）
3. 初始化各模块
       └─ OKXClient → SignalEngine → RiskCalculator → Runner
4. 执行持仓对账
       └─ 对比 portfolio.json 与交易所实际持仓
5. 进入 Heartbeat 等待
```
