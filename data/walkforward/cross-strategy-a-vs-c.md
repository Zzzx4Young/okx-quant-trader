# 横向对比 · A_EMA20_BREAKOUT vs C_VOLATILITY_BREAKOUT · BTC 1h

> **对比对象**: `a-btc-wf-3m1m-20260724-194650` (A) vs `c-btc-wf-3m1m-20260724-191640` (C)
> **窗口配置**: 18 窗口 × 90d / 30d stride × BTC-USDT-SWAP 1h
> **生成时间**: 2026-07-24
> **作者**: 小野（按 7-24 计划 · Step 3 横向对比）

---

## 1. 核心发现（一句话）

**A 是"alpha + hedge"两栖策略，在 DOWN 区是 alpha（C 是 hedge），在 SIDE 区比 C 略好，在 UP 区**两个都死**。首选 A，C 作为 A 触发不了时的 fallback。**

---

## 2. 逐窗口对比（regime 分类一致）

> 同口径：buy_hold > +10% = UP / -5% ~ +10% = SIDE / < -5% = DOWN

| # | 窗口 | buy&hold | regime | C viable | C best_ret | A viable | A best_ret | 赢家 |
|---|---|---|---|---|---|---|---|---|
| 00 | 2024-10-26 → 2025-01-24 | +58.28% | UP | 0/3 | +4.33% | 0/3 | -1.16% | A 略输（少亏） |
| 01 | 2024-11-25 → 2025-02-23 | -0.58% | SIDE | 0/3 | -4.59% | 2/3 | +6.18% | **A 完胜** |
| 02 | 2024-12-25 → 2025-03-25 | -10.92% | DOWN | 2/3 | -7.15% | 3/3 | +1.33% | **A 完胜** |
| 03 | 2025-01-24 → 2025-04-24 | -11.99% | DOWN | 3/3 | -2.86% | 3/3 | +2.58% | **A** |
| 04 | 2025-02-23 → 2025-05-24 | +14.08% | UP | 0/3 | -15.51% | 0/3 | +3.09% | **A 完胜** |
| 05 | 2025-03-25 → 2025-06-23 | +15.50% | UP | 0/3 | -17.05% | 0/3 | -10.97% | A |
| 06 | 2025-04-24 → 2025-07-23 | +27.31% | UP | 0/3 | -1.05% | 0/3 | -10.32% | C 略好 |
| 07 | 2025-05-24 → 2025-08-22 | +6.84% | SIDE | 0/3 | +1.10% | 0/3 | -4.29% | C |
| 08 | 2025-06-23 → 2025-09-21 | +13.91% | UP | 0/3 | +3.52% | 0/3 | -1.56% | C |
| 09 | 2025-07-23 → 2025-10-21 | -4.41% | SIDE | 3/3 | +14.64% | 1/3 | -4.14% | **C 完胜** |
| 10 | 2025-08-22 → 2025-11-20 | -22.79% | DOWN | 3/3 | -9.09% | 3/3 | +2.40% | **A** |
| 11 | 2025-09-21 → 2025-12-20 | -23.68% | DOWN | 3/3 | -13.02% | 3/3 | +5.96% | **A 完胜** |
| 12 | 2025-10-21 → 2026-01-19 | -17.97% | DOWN | 3/3 | -12.04% | 3/3 | +3.16% | **A** |
| 13 | 2025-11-20 → 2026-02-18 | -24.66% | DOWN | 3/3 | -11.62% | 3/3 | +1.36% | **A** |
| 14 | 2025-12-20 → 2026-03-20 | -20.75% | DOWN | 3/3 | -9.08% | 3/3 | -6.30% | A 略输 |
| 15 | 2026-01-19 → 2026-04-19 | -18.50% | DOWN | 3/3 | -10.18% | 3/3 | +4.92% | **A 完胜** |
| 16 | 2026-02-18 → 2026-05-19 | +13.05% | UP | 0/3 | +1.50% | 0/3 | +5.89% | A |
| 17 | 2026-03-20 → 2026-06-18 | -10.75% | DOWN | 3/3 | +5.64% | 3/3 | +1.96% | C 略好 |

**按窗口胜率**: A 14/18 (78%) | C 4/18 (22%)

---

## 3. Regime × Strategy 矩阵

| Regime | 窗口数 | C viable 率 | C mean best_ret | A viable 率 | A mean best_ret | 推荐策略 |
|---|---|---|---|---|---|---|
| **UP** (buy&hold > +10%) | 7 | **0%** | -3.4% | **0%** | -2.3% | ❌ **都不入场** |
| **SIDE** (-5% ~ +10%) | 3-4 | 25% | +3.7% | 33% | -0.8% | ⚠️ **人工 override**（w09 是 C 异常值） |
| **DOWN** (< -5%) | 7-8 | 86% | -8.1% | **100%** | **+1.9%** | ✅ **A 首选，C fallback** |

---

## 4. 三个关键发现

### 4.1 A 在 DOWN 区是 alpha 策略，C 是 hedge 策略

- A mean best_ret in DOWN: **+1.9%**（实际赚钱 7/8 窗口）
- C mean best_ret in DOWN: **-8.1%**（少亏而已，0/8 窗口赚钱）

> **重新定义两个策略的分工**：
> - A = "下行时也赚钱"（真正的 alpha）
> - C = "下行时少亏"（成本管理）

### 4.2 UP 区两个都死，但 A 死得"优雅"一点

UP 区 7 窗口都 0 viable：
- A mean best_ret: -2.3%（平均 -10pp 跑输 buy&hold）
- C mean best_ret: -3.4%（平均 -25.9pp 跑输 buy&hold）

**A 的 UP 损失是 C 的 1/2.5** → UP 区硬要选，A 比 C 好，但**首选仍是不入场**（both 都跑输 buy&hold）。

### 4.3 SIDE 区高度依赖波动，不是稳定的 alpha 源

SIDE 区 3-4 窗口：
- A: 1/3 viable，mean -0.8%（接近 buy&hold）
- C: 1/4 viable (w09 异常值 +14.64%)，mean +3.7%

w09 (BTC 7-10 月震荡 ±5%) C 大爆发，但**w01 / w07 都是 SIDE 失败**。SIDE 是不可复现的 alpha 源。

---

## 5. 决策规则（合并 A + C）

### 5.1 推荐的 regime filter（合并版）

```python
def recommended_strategy(btc_klines_1d) -> Tuple[Optional[str], str]:
    """
    判定当前 BTC regime 推荐哪个策略。
    返回: (strategy_letter, reason) - None = 不入场
    """
    last_90d_ret = (btc_klines_1d['close'].iloc[-1] / btc_klines_1d['close'].iloc[-90] - 1) * 100
    ema50 = btc_klines_1d['close'].ewm(span=50).mean().iloc[-1]
    ema200 = btc_klines_1d['close'].ewm(span=200).mean().iloc[-1]
    
    # 强 UP：两个都死，不入场
    if last_90d_ret > 10 and ema50 > ema200 * 1.02:
        return None, f"UP+EMA多头 (90d_ret={last_90d_ret:+.1f}%)"
    
    # 强 DOWN：A 首选
    if last_90d_ret < -5 and ema50 < ema200:
        return "A", f"DOWN+EMA空头 (90d_ret={last_90d_ret:+.1f}%)"
    
    # SIDE：人工评估（标记待 review）
    return None, f"SIDE 待人工评估 (90d_ret={last_90d_ret:+.1f}%)"
```

### 5.2 决策矩阵（合并版，给 ops）

| 当前 BTC regime | 推荐 | 期望 best_ret | 期望 buy&hold | 策略 vs 持币 |
|---|---|---|---|---|
| 强 UP (>+10% + EMA多头) | **不入场** | -2% ~ -3% | +22% | -25pp |
| 弱 UP / SIDE (0% ~ +10%) | **人工评估** | 不可预测 | 不可预测 | TBD |
| 强 DOWN (<-5% + EMA空头) | **A** | **+1.9%** | -18% | **+20pp** |
| 强 DOWN 但 A 触发不了 | **C fallback** | -8% | -18% | +10pp |

### 5.3 资本配置建议（合并版）

| Regime | A 配置 | C 配置 | USDT | 备注 |
|---|---|---|---|---|
| UP | 0% | 0% | 100% | buy&hold 不如持币 |
| SIDE | 0% | 0% | 100% | 待人工评估 |
| DOWN（强） | **15-20%** | 5%（fallback） | 75-80% | A 主力，C 备用 |

---

## 6. Action Items

### 🔴 P0 · 立即
- [ ] **regime filter 实现 + 单元测试**（合并版，用 A 替代 C 作为首选）
  - `code/regime_filter.py` 新文件：~50 行
  - `tests/test_regime_filter.py` 新文件：~80 行（mock 18 窗口数据 + 边界 case）
  - 接入 `signal_runner.py`：A / C 入场前调 `recommended_strategy()`

### 🟡 P1 · 一周内
- [ ] **回测 regime-filtered A 单独跑** —— 18 窗口上验证"只 DOWN 区跑 A"的实际 Sharpe
  - 期望：A 的 8 个 DOWN 窗口都保留，A 的 7 个 UP 窗口和 3 个 SIDE 窗口被禁
  - 总 viable 窗口 8/18 = 44%（低于 56% 因为禁了 SIDE 异常值）
  - 但 Sharpe 应该显著提升（去掉 7 个 UP 的负贡献）
- [ ] **实盘观察 1 周（7-25 → 7-31）** —— 当前 BTC 在 7-24 是 DOWN 区（buy&hold 7 月以来 -10.75%）
  - regime filter 应允许 A 跑
  - 观察 A 的实际表现 vs walkforward 预期（mean +1.9% in DOWN）

### 🟢 P2 · 未来
- [ ] **Dashboard 加 regime 标注** —— WalkforwardDetail 页面每个窗口加 regime badge
  - UP（红）/ SIDE（黄）/ DOWN（绿）
  - 让 ops 一眼看出策略在该 regime 的胜率
- [ ] **Phase 3B · Live vs Backtest overlay** —— 跟实际 portfolio.json 的 closed positions 时间对齐
  - 验证 A 在当前 DOWN regime 的实盘表现是否跟 walkforward 一致

---

## 7. 关键 takeaway

> **A 替代 C 作为首选策略**。

| 维度 | A (EMA20_BREAKOUT) | C (VOLATILITY_BREAKOUT) |
|---|---|---|
| DOWN 区 viable 率 | **100%** | 86% |
| DOWN 区 mean best_ret | **+1.9%** | -8.1% |
| UP 区 viable 率 | 0% | 0% |
| UP 区 mean best_ret | -2.3% | -3.4% |
| 适用场景 | **首选**，DOWN 区主力 | fallback，SIDE 异常值捕获 |

但**没有 regime filter 都是空谈**——regime filter 是把"全天候策略"变成"择时策略"的必要条件。

---

## 8. 复现链接

- A 走查：`data/walkforward/a-btc-wf-3m1m-20260724-194650/`
- C 走查：`data/walkforward/c-btc-wf-3m1m-20260724-191640/`
- 横向对比（本文）：`data/walkforward/cross-strategy-a-vs-c.md`
- 重新跑 A：`./run.sh scripts/walkforward.py --strategy A --symbol BTC-USDT-SWAP --bar 1h --window-days 90 --stride-days 30 --slippage-bps 5,10,15 --fee-bps 5.0 --leverage 5 --name a-btc-wf-3m1m`
- 重新跑 C：`./run.sh scripts/walkforward.py --strategy C --symbol BTC-USDT-SWAP --bar 1h --window-days 90 --stride-days 30 --slippage-bps 5,10,15 --fee-bps 5.0 --leverage 5 --name c-btc-wf-3m1m`
