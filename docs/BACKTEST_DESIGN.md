# OKX 回测框架 — 设计概览

> **版本**：v0.1（设计阶段，2026-07-13）  
> **范围**：基于现有 v1.5 OKX 量化系统，扩展回测能力  
> **状态**：待 Nixil 拍板后进入实施

---

## 1. 目标与非目标

### 目标

1. **验证策略假设**：用历史数据量化 4 策略（ABCD）的真实表现
2. **比较策略组合**：单策略 vs 多策略并行的夏普 / 回撤 / 胜率
3. **参数寻优**：在不 overfit 的前提下找稳健参数区间
4. **离线沙盒**：策略改动的回归测试，跑过历史才上 live

### 非目标（明确不做）

- ❌ 实时 tick 级回测（数据成本 + 撮合复杂度太高）
- ❌ 订单簿微观模拟（depth / queue priority 等）
- ❌ 多账户 / 多资金层（先单账户单策略跑通）
- ❌ 跨交易所套利（OKX 单边）
- ❌ 机器学习 / 神经网络策略（保留给未来）

---

## 2. 核心设计原则（继承自 LESSONS_LEARNED）

1. **最大化复用现有模块**：`signal.py` / `risk.py` / `portfolio.py` 的纯逻辑部分直接复用，**不重新发明**
2. **API client 层做归一化**：历史 K 线接口在边界处统一方向、字段名
3. **真实撮合 > 简化撮合**：避免 look-ahead bias，宁可模型保守
4. **本地状态 reconcile**：回测 portfolio 与"OKX 假设真实账户"也需要对账思维
5. **可观测性 > 功能完整性**：每根 bar 的状态可追溯，出问题能 debug

---

## 3. 架构分层

```
backtest/
├── __init__.py
├── data/                      # 数据层
│   ├── __init__.py
│   ├── fetcher.py             # 从 OKX 拉历史 K 线（含分页）
│   ├── cache.py               # parquet 缓存（按 instId+bar 分片）
│   └── loader.py              # 加载数据 + 切时间窗口 + 缺失处理
│
├── engine/                    # 回测引擎
│   ├── __init__.py
│   ├── engine.py              # 时间驱动事件循环（核心）
│   ├── scheduler.py           # 决定每根 bar 触发什么（信号/风控/平仓）
│   └── clock.py               # 虚拟时钟 + 资金费率结算点（00/08/16 UTC）
│
├── execution/                 # 模拟撮合
│   ├── __init__.py
│   ├── matcher.py             # 订单撮合（开盘/收盘/止损触发）
│   ├── slippage.py            # 滑点模型（固定 bps + 波动率缩放）
│   ├── fee.py                 # 手续费（taker 0.05% / maker 0.02%）
│   └── funding.py             # 资金费率（每 8h，按 OKX 真实费率）
│
├── strategies/                # 策略适配层
│   ├── __init__.py
│   └── adapter.py             # 把 okx.code.strategies.X 适配成回测接口
│
├── risk/                      # 风控（直接复用 okx.code.risk）
│   └── __init__.py            # re-export + 回测专属覆写（如虚拟资金）
│
├── portfolio/                 # 组合管理（直接复用 okx.code.portfolio 的纯逻辑）
│   ├── __init__.py
│   └── virtual.py             # VirtualPortfolio：持仓/余额/统计/daily_stats
│
├── reporting/                 # 报告生成
│   ├── __init__.py
│   ├── metrics.py             # 指标计算（夏普/回撤/月度收益等）
│   ├── plots.py               # Plotly 图表（收益曲线/回撤/热力图）
│   └── report.py              # HTML/Markdown 报告生成
│
├── runner.py                  # CLI 入口（argparse + 输出 JSON + 落盘）
└── cli.py                     # 子命令：run / compare / report / sweep
```

**复用边界**（关键决策）：

| 现有模块 | 复用方式 | 改动 |
|----------|----------|------|
| `code/signal.py` (SignalEngine) | **直接复用** | 加一个 adapter 喂"历史 K 线 + 当前虚拟持仓"代替"实时 ticker + OKX 持仓" |
| `code/risk.py` (RiskCalculator) | **直接复用** | ct_val 参数从 OKX instruments 拉（在 backtest 也走相同路径） |
| `code/portfolio.py` Portfolio 类 | **复用纯逻辑**（开仓/平仓/统计） | 不复用 reconcile_with_okx；新建 VirtualPortfolio 继承基础结构 |
| `code/config.py` Config | **复用但只读** | 回测期间 config 冻结，不允许改 emergency_stop 等 |
| `code/notifier.py` | **NoopNotifier** | 回测不需要发通知，但保留接口方便日后 e2e |
| `code/utils.py` | **直接复用** | `side_to_str()` / `OKXError` 全部适用 |
| `code/auth.py` / `_http.py` / `trade.py` | **不直接复用** | 回测数据从 fetcher 走，不走 OKX HTTP；下单走 execution/matcher |

---

## 4. 数据流图

```
用户 CLI: backtest run --strategy A --inst-id ETH-USDT-SWAP --start 2025-01-01 --end 2025-12-31
                                  │
                                  ▼
                          ┌──────────────────┐
                          │  data/fetcher.py │ ◀─── OKX /api/v5/market/history-candles
                          │  + cache.py      │      (1m K线 1440 根/页，需分页)
                          └──────────────────┘
                                  │ parquet cache
                                  ▼
                          ┌──────────────────┐
                          │  data/loader.py  │ ◀─── 切窗口 + 缺失值处理
                          └──────────────────┘
                                  │ np.ndarray / pandas.DataFrame
                                  ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  engine/engine.py  ─── 时间驱动事件循环                          │
   │                                                              │
   │   for each bar (open time):                                  │
   │     1. clock.advance()         → 检查是否到资金费率结算点       │
   │     2. funding.settle()        → 扣除/增加持仓资金费率          │
   │     3. scheduler.on_bar()      → 触发信号检测 + 风控           │
   │     4. matcher.fill()          → 撮合挂单（止损/止盈触发）      │
   │     5. portfolio.update()      → 更新虚拟持仓 + 余额           │
   │     6. metrics.snapshot()      → 记录权益曲线快照               │
   │                                                              │
   │     if signal triggered:                                     │
   │       risk.check()  → matcher.execute() → portfolio.open()    │
   └──────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                          ┌──────────────────┐
                          │ portfolio/       │ ◀─── state/backtest_<run_id>/
                          │   virtual.py     │      - positions.json
                          └──────────────────┘      - equity_curve.csv
                                  │                  - trades.csv
                                  ▼
                          ┌──────────────────┐
                          │ reporting/       │ ──▶ output/backtest_<run_id>/
                          │   report.py      │      - report.html
                          └──────────────────┘      - metrics.json
                                                     - plots/*.png
```

---

## 5. 关键设计决策（需要 Nixil 拍板）

### 决策 1：撮合模型——保守 vs 激进

| 模型 | 描述 | 优 | 劣 |
|------|------|----|----|
| **A. 当根 close 生成信号 + 下一根 open 成交**（推荐） | T 时刻 close 检测，T+1 open 成交 | 避免 look-ahead bias，最贴近真实 | 滑点假设需精确 |
| B. 当根 close 生成信号 + 当根 close 成交 | 立即成交 | 简单 | 严重 look-ahead bias |
| C. 实时模拟：每根 K 线内 100 个 tick 模拟 | 高保真 | 接近真实 | 数据 + 计算成本极高 |

**建议**：A。理由：Bug 1（K线方向）的根因就是时间边界混乱，回测必须严格遵守"T 时刻只能用 ≤ T 的信息"。

### 决策 2：滑点模型

| 模型 | 公式 | 适用 |
|------|------|------|
| **固定 bps** | slippage = 5 bps（万5） | 流动性好时低估，差时低估 |
| **波动率缩放** | slippage = base_bps * (1 + ATR / price) | 更真实，但需要历史 ATR |
| **订单簿深度模拟** | 根据 taker 量匹配 depth | 最精确，但数据成本极高 |

**建议**：波动率缩放，base 5 bps，缩放系数 0.5（保守）。

### 决策 3：手续费

直接复用 OKX 真实费率：**taker 0.05% / maker 0.02%**。止损止盈单按 taker 计算（市价单立即成交）。

### 决策 4：资金费率

- **结算时间**：每日 00:00 / 08:00 / 16:00 UTC（OKX 标准）
- **费率来源**：回测期间用**历史费率**（OKX `/api/v5/public/funding-rate-history`），不用预测
- **未平仓合约标记**：用 `mark_price`（OKX 真实 mark），不用 last price

### 决策 5：初始资金 + 杠杆

- **初始资金**：默认 10,000 USDT（可配置）
- **杠杆**：跟 Constitution 杠杆矩阵（BTC/ETH 5-10x，山寨币 3-5x）
- **保证金模式**：统一 isolated（避免 cross 复杂度；live cross 在回测里没意义）

---

## 6. 报告指标

### 核心指标（每个 run 必出）

| 类别 | 指标 |
|------|------|
| **收益** | 总收益 / 年化收益 / 月度收益均值 |
| **风险** | 最大回撤 / 最大回撤持续天数 / 波动率（年化） |
| **风险调整** | 夏普比率 / 索提诺比率 / 卡玛比率 |
| **交易** | 胜率 / 盈亏比 / 平均持仓时长 / 总交易笔数 |
| **成本** | 总手续费 / 总资金费率 / 平均滑点 |

### 可视化（Plotly HTML）

1. **权益曲线**：x=时间，y=账户净值 + benchmark（hold BTC 现货）
2. **回撤曲线**：水下深度（drawdown）
3. **月度收益热力图**：x=年，y=月，color=收益%
4. **信号分布**：按策略 / 方向 / 置信度
5. **资金费率影响**：堆叠图（PnL vs 资金费率）

### 输出文件

```
output/backtest_<run_id>/
├── report.html           # 完整报告（含所有图表）
├── metrics.json          # 数字指标（机器可读）
├── trades.csv            # 逐笔成交明细
├── equity_curve.csv      # 权益曲线
└── config_used.json      # 本次 run 的完整配置（可复现）
```

---

## 7. CLI 设计

```bash
# 单策略单标的
python -m backtest run \
  --strategy EMA20_BREAKOUT \
  --inst-id ETH-USDT-SWAP \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --capital 10000 \
  --bar 1h

# 多策略并行对比
python -m backtest compare \
  --strategies EMA20_BREAKOUT,BB_RSI_REVERSION,VOLATILITY_BREAKOUT,FUNDING_RATE_REVERSAL \
  --inst-id BTC-USDT-SWAP \
  --start 2024-01-01 \
  --end 2025-06-30 \
  --bar 4h

# 生成报告（基于已有 run_id）
python -m backtest report --run-id 20260713-eth-ema --format html

# 参数扫描（简单网格，未来支持 Bayesian）
python -m backtest sweep \
  --strategy EMA20_BREAKOUT \
  --param-grid '{"ema_period": [10, 20, 30], "rsi_filter": [40, 50, 60]}' \
  --inst-id ETH-USDT-SWAP \
  --start 2025-01-01 \
  --end 2025-12-31
```

---

## 8. 实施分阶段

### Phase 1：MVP（2 周）
- [ ] `data/fetcher.py` + `cache.py`（OKX 历史 K 线 + parquet 缓存）
- [ ] `engine/engine.py` 时间驱动循环
- [ ] `execution/matcher.py` 基础撮合（开盘价成交）
- [ ] 复用 `signal.py` Strategy A（EMA20_BREAKOUT）
- [ ] 复用 `risk.py`（ctVal 处理）
- [ ] `reporting/metrics.py` 基础指标 + `report.py` HTML 输出
- [ ] 单策略单标的 CLI：ETH-USDT-SWAP 2025-01 ~ 2025-12
- [ ] 单元测试覆盖核心模块

### Phase 2：完整撮合（1 周）
- [ ] `execution/slippage.py` + `fee.py`
- [ ] `execution/funding.py` 资金费率结算
- [ ] `engine/clock.py` 8h 结算点
- [ ] 止损/止盈触发逻辑（替代 attachAlgoOrds）

### Phase 3：多策略 + 对比（1 周）
- [ ] Strategy B/C/D adapter
- [ ] `compare` 子命令（并行跑多策略）
- [ ] 报告加入策略对比表 + benchmark

### Phase 4：参数扫描（可选）
- [ ] `sweep` 子命令 + 网格搜索
- [ ] 过拟合检测（walk-forward analysis）
- [ ] 参数稳健性热力图

**总估算**：4 周完整版。MVP 2 周可跑出第一个真实回测结果。

---

## 9. 与现有系统的集成

### 数据共享
- `data/cache/{instId}_{bar}.parquet` 可被 live Runner 复用（冷启动预热）
- `output/backtest_*/metrics.json` 可喂给 Constitution 做"策略健康度评分"

### 自动化
- Phase 3 后可加 OpenClaw cron：每月自动跑"过去 30 天"回测，对比 Constitution 实际表现
- 偏差 > 阈值 → Telegram 告警："策略 C 上月 live 收益 -2%，但回测预期 +1.5%，疑似 regime shift"

### 风险
- **回测 ≠ 实盘**：永远要标"历史业绩不代表未来"，但这是后话
- **数据缺失**：OKX 1m K 线最多 1440 根（约 1 天），更老要分页或换 5m/15m/1h
- **过拟合**：参数扫描后必须做 walk-forward（样本内/外分割）

---

## 10. 开放问题（待 Nixil 决策）

1. **撮合模型**：A / B / C？（建议 A）
2. **数据范围**：先 1h K 线还是 5m K 线？（建议先 1h，5m 数据量 12 倍且 1m 1440 限制更紧）
3. **是否包含资金费率**？（强烈建议包含——这是合约回测的核心成本）
4. **Phase 1 是否同步进 main 分支**？（建议是，但用 feature flag 隔离：`if __name__ == "__main__"` 入口和独立 `backtest/` 目录）
5. **是否复用 demo OKX 账户拉历史费率**？（可以——demo 也能调公开 API）

---

_文档状态：v0.1，待 Nixil 评审 → v1.0 后进入实施_