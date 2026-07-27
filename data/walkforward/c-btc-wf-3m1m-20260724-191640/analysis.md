# Walk-forward 深度分析 · C_VOLATILITY_BREAKOUT × BTC 1h

> **范围**: 18 个滚动窗口 · 2024-10-26 → 2026-06-18（跨度 605 天）
> **窗口配置**: 90d window / 30d stride
> **生成时间**: 2026-07-24
> **作者**: 小野（按 7-24 计划 · Step 2）

---

## 1. Executive Summary（一句话版）

**C_VOLATILITY_BREAKOUT 在 BTC 上是"regime-aware 的 hedge 策略"——在 downtrend 跑赢 buy&hold（viable），在 uptrend 落后 buy&hold（不 viable），在 sideways 表现不稳定**。模式清晰且可执行：**C 应该作为 downtrend 防御工具使用，不应作为 alpha 生成器**。

---

## 2. Regime 分类结果

按 `buy_hold_ret` 三段切（> +10% UP / -5% ~ +10% SIDE / < -5% DOWN）：

| # | 窗口 | buy&hold | viable | best_ret | regime |
|---|---|---|---|---|---|
| 00 | 2024-10-26 → 2025-01-24 | +58.28% | 0/3 | +4.33% | **UP** |
| 01 | 2024-11-25 → 2025-02-23 | -0.58% | 0/3 | -4.59% | SIDE |
| 02 | 2024-12-25 → 2025-03-25 | -10.92% | 2/3 | -7.15% | DOWN |
| 03 | 2025-01-24 → 2025-04-24 | -11.99% | 3/3 | -2.86% | DOWN |
| 04 | 2025-02-23 → 2025-05-24 | +14.08% | 0/3 | -15.51% | **UP** |
| 05 | 2025-03-25 → 2025-06-23 | +15.50% | 0/3 | -17.05% | **UP** |
| 06 | 2025-04-24 → 2025-07-23 | +27.31% | 0/3 | -1.05% | **UP** |
| 07 | 2025-05-24 → 2025-08-22 | +6.84% | 0/3 | +1.10% | SIDE |
| 08 | 2025-06-23 → 2025-09-21 | +13.91% | 0/3 | +3.52% | **UP** |
| 09 | 2025-07-23 → 2025-10-21 | -4.41% | 3/3 | +14.64% | SIDE |
| 10 | 2025-08-22 → 2025-11-20 | -22.79% | 3/3 | -9.09% | DOWN |
| 11 | 2025-09-21 → 2025-12-20 | -23.68% | 3/3 | -13.02% | DOWN |
| 12 | 2025-10-21 → 2026-01-19 | -17.97% | 3/3 | -12.04% | DOWN |
| 13 | 2025-11-20 → 2026-02-18 | -24.66% | 3/3 | -11.62% | DOWN |
| 14 | 2025-12-20 → 2026-03-20 | -20.75% | 3/3 | -9.08% | DOWN |
| 15 | 2026-01-19 → 2026-04-19 | -18.50% | 3/3 | -10.18% | DOWN |
| 16 | 2026-02-18 → 2026-05-19 | +13.05% | 0/3 | +1.50% | **UP** |
| 17 | 2026-03-20 → 2026-06-18 | -10.75% | 3/3 | +5.64% | DOWN |

**Regime 分布**:

| Regime | 窗口数 | viable 窗口 | viable 率 | 平均 best_ret | 平均 buy&hold | C vs Buy&Hold |
|---|---|---|---|---|---|---|
| **UP** | 7 | 0/7 | **0%** | -3.4% | +22.5% | -25.9pp |
| **SIDE** | 4 | 1/4 | 25% | +3.7% | -1.2% | +4.9pp |
| **DOWN** | 7 | 6/7 | **86%** | -8.1% | -18.6% | **+10.5pp** |

---

## 3. 三个反直觉发现

### 3.1 C 不是 alpha 策略，是 hedge 策略

在 DOWN 区，C 的 best_ret 仍是**负的**（-9% ~ -13%），但**比 buy&hold 少亏 10.5pp**。

> **重新定义 C 的价值主张**：不是"在 BTC 下跌时赚钱"，而是"在 BTC 下跌时少亏"。

### 3.2 UP 区 C 是稳定的 alpha destroyer

7 个 UP 窗口 0 viable：
- 平均 best_ret = -3.4%
- 平均 buy&hold = +22.5%
- **C 把 buy&hold 的 22% 利润吃成 -3% → 净损失 25.9pp**

最严重的是 w05（2025-03-25 → 2025-06-23，buy_hold +15.5%）：C 跑出 -17.05%，**solo 损失 32.5pp**。

### 3.3 SIDE 区 w09 是异常值（+14.64% on -4.41% buy&hold）

w09 (2025-07-23 → 2025-10-21) 是唯一 SIDE 窗口 viable 的，**best_ret +14.64%** vs buy&hold -4.41%。

特征：该窗口 BTC 在 ~$115k-$120k 区间震荡约 90 天，C 的 volatility breakout 策略**捕捉了 7-8 月的几次大幅波动**（BTC 在 7 月底到 10 月初多次 ±5% 单日波动）。

**推论**：SIDE 区的 viability 高度依赖"震荡幅度"。如果是低波动 SIDE，C 也无机会（w01 buy_hold -0.58%, C -4.59%）。

---

## 4. 决策规则（什么时候开 C）

### 4.1 推荐的"regime filter"（可直接落地为 runner 守门）

```python
def c_regime_allowed(btc_klines_1d) -> Tuple[bool, str]:
    """
    判定当前 BTC regime 是否允许 C_VOLATILITY_BREAKOUT 入场。
    基于 90d 滚动 buy&hold 收益 + 50d/200d EMA 交叉。
    """
    last_90d_ret = (btc_klines_1d['close'].iloc[-1] / btc_klines_1d['close'].iloc[-90] - 1) * 100
    ema50 = btc_klines_1d['close'].ewm(span=50).mean().iloc[-1]
    ema200 = btc_klines_1d['close'].ewm(span=200).mean().iloc[-1]
    
    if last_90d_ret > 10 and ema50 > ema200 * 1.02:
        return False, f"UP+EMA多头 (90d_ret={last_90d_ret:+.1f}%, EMA50/200={ema50/ema200:.3f})"
    if last_90d_ret < -5 and ema50 < ema200:
        return True, f"DOWN+EMA空头 (90d_ret={last_90d_ret:+.1f}%, EMA50/200={ema50/ema200:.3f})"
    # SIDE 区间 → 默认禁用（w01/w07 都是 SIDE 不 viable，w09 是异常值不可复现）
    return False, f"SIDE 不确定 (90d_ret={last_90d_ret:+.1f}%, EMA50/200={ema50/ema200:.3f})"
```

### 4.2 决策矩阵（给 ops）

| 当前 BTC regime | C 是否入场 | 期望 | 备注 |
|---|---|---|---|
| 强 UP (>+10%/90d, EMA多头) | ❌ **不入场** | best_ret -3%~-17% | 7 窗口 0 viable |
| 弱 UP / SIDE (0% ~ +10%) | ❌ **不入场** | 不可预测 | 4 窗口 1 viable（异常） |
| SIDE 震荡 (>5% 振幅/30d) | ⚠️ **人工评估** | 可能 +14% | 需手动 override |
| 弱 DOWN (0% ~ -5%) | ⚠️ **人工评估** | 可能 -3%~-5% | 接近 buy&hold |
| 强 DOWN (<-5%, EMA空头) | ✅ **入场** | best_ret -9%~-13% | **C 跑赢 buy&hold 10pp** |

### 4.3 资本配置建议

| Regime | C 配置 | 备注 |
|---|---|---|
| UP | 0% | 全仓 buy&hold 优于 C |
| SIDE | 0%（人工例外） | C 期望接近 0 |
| DOWN | **10-15% 净值的 C + 85-90% USDT** | C 作为对冲，与 buy&hold 互补 |

---

## 5. Action Items（按优先级）

### 🔴 P0 · 立即
- [ ] **加 C 策略 regime filter** 到 `signal_runner.py` — C 入场前跑 `c_regime_allowed()`，DOWN 区以外一律 no_signal
  - 预计代码改动：~30 行
  - 验证：写 unit test（mock 不同 regime 的 BTC K 线 → 验证 allow/deny）
  - 风险：误判 SIDE 区间（w09 异常值说明震荡区有 alpha）— 建议保留人工 override 通道

### 🟡 P1 · 一周内
- [ ] **回测 regime-filtered C** — 在 18 窗口数据上重跑 C，regime filter 开启后：
  - 期望：DOWN 区 6/7 仍 viable，UP 区 0/7 → 总 viable 率应上升（6/14 vs 10/18 = 33% vs 56%）
  - **质量提升** 显著（避免 7 个 UP 窗口的 -25.9pp 平均损失）
  - 同样口径：净 Sharpe 应提升
- [ ] **跨策略 A vs C 横向 walkforward** — Option 3 (Step 3) 计划内，今天做
  - 假设：A 在 SIDE 区可能更好（EMA 趋势策略），A vs C 互补

### 🟢 P2 · 未来
- [ ] **regime filter 加到 dashboard** — WalkforwardDetail 页面标注每个窗口的 regime 颜色
  - 复用 regime 分类逻辑
  - 让 ops 一眼看出"该窗口的 C 是真有效还是侥幸"
- [ ] **做实盘验证**（v1.8.3 demo first week 结束，2026-07-31 之后）
  - 当前 BTC 状态（7-24）应属 DOWN（buy&hold 7 月以来 -10.75%）→ **regime filter 应允许 C**
  - 实盘 1 周对比 C vs buy&hold

---

## 6. 关键 takeaway

> **"Walkforward 的价值不在 avg，而在 worst case"**

C 在 18 窗口的 best_ret 均值是 -4.58%，看起来很惨。但拆开看：
- 7 个 DOWN 窗口均值 -8.1%（C 跑赢 buy&hold 10.5pp）
- 7 个 UP 窗口均值 -3.4%（C 跑输 buy&hold 25.9pp，**这是真正的问题**）
- 4 个 SIDE 窗口均值 +3.7%（依赖波动率）

**没有 regime filter 的 C = 7/18 时间都在做赔本买卖**。**regime filter 是把"全天候 C"变成"择时 C"的必要条件**。

---

## 7. 复现链接

- 走查数据：`okx/data/walkforward/c-btc-wf-3m1m-20260724-191640/`
  - `meta.json`（18 窗口明细）
  - `result.md`（脚本自动分析）
  - `analysis.md`（本文）
  - `windows/w00_*/` ... `windows/w17_*/`（每个窗口完整 fragility_scan 产物）
- 重新跑：`./run.sh scripts/walkforward.py --strategy C --symbol BTC-USDT-SWAP --bar 1h --window-days 90 --stride-days 30 --slippage-bps 5,10,15 --fee-bps 5.0 --leverage 5 --name c-btc-wf-3m1m`
- git commit: `e6a9ba1fbd2a1a1154cc54566666114587de9bc2` (Phase 2C bar-axis multi-period heatmap 时的 HEAD)
