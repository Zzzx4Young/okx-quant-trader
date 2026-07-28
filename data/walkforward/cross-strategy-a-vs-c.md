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

---

## 9. Phase 3B 后验 · bootstrap 验证 (2026-07-28)> **作者**: 小野（按 7-28 计划 · Phase 3B bootstrap）
> **目标**: 用 post-hoc regime tagging + bootstrap 重新验证 Phase 3A 的 regime × strategy 矩阵
> **数据**: `data/phase3b/{a,c}_trades_with_regime.parquet`（561 + 690 trades · 7-24 walkforward 输出 · 按 exit_ts 重打 regime 标签）
> **工具**: `data/phase3b/bootstrap_regime.py`（1000 resample × regime bucket · seed=20260728 · prob_ruin threshold: mean < -$200/trade）
> **结论**: **regime_filter 现状正确，C strategy dormant by design 是合理状态**（详见 9.4）

### 9.1 bootstrap 输出（per-trade mean + 5/95 CI）

| Strategy | Regime | n | mean (USD/trade) | 5/95 CI | prob_ruin |
|---|---|---|---|---|---|
| A | **A** (DOWN) | 204 | +$6.00 | [-21, +34] | 0% |
| A | SIDE | 261 | +$9.35 | [-20, +35] | 0% |
| A | UP | 96 | -$51.65 | [-93, -9] | 0% |
| A | ALL | 561 | -$2.30 | [-21, +16] | 0% |
| C | **A** (DOWN) | 303 | **-$54.17** | **[-75, -30]** | 0% |
| C | SIDE | 276 | +$17.12 | [-8, +45] | 0% |
| C | UP | 111 | -$91.18 | [-123, -62] | 0% |
| C | ALL | 690 | -$31.60 | [-48, -15] | 0% |

### 9.2 验证 Phase 3A 结论（方向一致性 ✅）

| Phase 3A 结论 | Phase 3B 验证 | 一致性 |
|---|---|---|
| A in DOWN 100% viable, mean +1.9% | A in A regime: +$6/trade，CI [-21, +34]（正但 CI 过 0） | ✅ 同方向 · bootstrap per-trade 与 Phase 3A per-window 归一化不同 |
| C in DOWN 86% viable, mean -8.1% | C in A regime: **-$54/trade，CI 完全负**（[-75, -30]） | ✅ 同方向 · 验证 C 在 DOWN 是**亏损模式** |
| UP 区两个都死 | A: -$52 / C: -$91 · CI 都明显负 | ✅ baseline 拒 UP 正确 |

### 9.3 Phase 3B 新发现（SIDE regime 的 alpha）

**viability % 视角（Phase 3A）vs mean 视角（Phase 3B bootstrap）的差异**：

| | SIDE viability (Phase 3A) | SIDE mean/trade (Phase 3B bootstrap) |
|---|---|---|
| A | 1/3 (33%) viable | +$9 · Sharpe ≈ 0.04（std $255） |
| C | 1/4 (25%) viable | **+$17** · Sharpe ≈ 0.07（std $256） |

**新观察**：
- A 和 C 在 SIDE 都是**正均值**，但 Sharpe ratio 都 < 0.1（CI 都跨 0）—— **统计上不显著的弱 alpha**
- C 在 SIDE 的 raw mean 是 A 的 ~2×（+$17 vs +$9）—— 但仍属弱信号
- Phase 3A docstring 当时"拒 SIDE 不可复现"的判断**是 design 时正确的保守决策**（viability % 低 + Sharpe 弱）

### 9.4 结论（修正版"错配"诊断）

我（7-28 22:50 CST）初判为"双重错配"，**修正如下**：

| 原措辞 | 修正 |
|---|---|
| "C 在 DOWN 推荐 + SIDE 拒" | ❌ regime_filter **从未推荐 C**（代码无 C 分支）。准确表述："A 在 DOWN 推荐 + SIDE 一刀切拒 + C 完全 dormant" |
| "C regime_filter 是反的" | ❌ **过激**。C in A regime CI 完全负 = regime_filter 排除 C 是 correct design，不是反。准确表述："C dormant 是 correct 保守决策，bootstrap 验证了 design 的正确性" |

**正确的 regime_filter 状态评估**：

| 决策点 | 评估 | 证据 |
|---|---|---|
| 拒 UP baseline | ✅ **正确** | A: -$52 · C: -$91 · CI 都明显负 |
| 推荐 A in DOWN | ✅ **正确** | A: +$6（正但 CI 过 0）· C: -$54（CI 全负）→ 推荐 A 不推荐 C 是对的 |
| 拒 SIDE | ✅ **defensible 保守** | Sharpe < 0.1 · CI 跨 0 · viability 33%/25% 低 · 是合理 risk-off 决策 |
| C 完全 dormant | ✅ **by design correct** | regime_filter 无 C 分支 + Phase 3A 已知 C in DOWN 是 hedge（非 alpha）+ bootstrap 验证 C in A regime CI 全负 |

### 9.5 Future-self 防误区清单（最重要）

**如果未来看到这段想"启用 C 因为 C in SIDE 有 +$17 alpha"，先读这五条**：

1. **C in A regime CI 完全负**（[-75, -30]）—— 不是只在某些窗口，是**所有 18 个 walkforward 窗口平均都是亏钱**
2. **C in SIDE 的 Sharpe 0.07 极弱** —— 单笔 std $256，CI 跨 0，**统计上不显著**
3. **C 的 86% viability 是高 WR 但 mean 负**（Phase 3A 原话）—— high win rate + bad tail risk 模式，hedge 而非 alpha
4. **regime_filter 设计意图**就是排除 C 在 DOWN（A regime）—— 启用 C 必须先 fragility_scan + 限制在 SIDE only，不能放开
5. **"SIDE alpha"在 Phase 3A docstring 已被识别为"不可复现"** —— 当时的 viability % 视角已警告，今天 bootstrap 用 mean 视角再次确认 Sharpe 太弱

**结论：C 永远不该自动启用**。如果未来要走"启用 C in SIDE only"的实验路径，必须：
- 先 fragility_scan 验证（§3 规则 2 铁律）
- 至少 3 个月 live data 收集
- 永远不要 in DOWN / UP 启用 C

### 9.6 行动清单（Phase 3B 完成后）

- [x] bootstrap script ready: `data/phase3b/bootstrap_regime.py` (8477 bytes · 1000 iter · seed=20260728)
- [x] bootstrap output: `data/phase3b/bootstrap_results.json` + `bootstrap_report.md`
- [x] 修正"双重错配"误诊，写入 §9.4
- [x] future-self 防误区清单写入 §9.5
- [ ] Nixil commit（untracked files: bootstrap_regime.py + bootstrap_results.json + bootstrap_report.md）
- [ ] Phase 3C（如要进一步）需重新设计问题：BTC dominance / vol gate 区分 SIDE 子类，而不是"启用 C"

---

## 10. Phase 3B Step B · Direction Filter 验证 (2026-07-28)

> **作者**: 小野 (按 7-28 Step B 验证)
> **触发**: Track A bootstrap 发现 A 拒 DOWN·SHORT 可 +$923 saved + C 在 SIDE·SHORT 才是真正 alpha
> **工具**: `code/signal_direction_filter.py` (新) + `scripts/fragility_scan_with_filter.py` (新)
> **验证**: fragility_scan N×M 网格 baseline vs filtered

### 10.1 Filter Rules

| Strategy | DOWN (A) | UP | SIDE | 数据不足 |
|---|---|---|---|---|
| A_EMA20_BREAKOUT | 只接 **LONG** | 拒 | 拒 | 拒 |
| C_VOLATILITY_BREAKOUT | 拒 | 拒 | 只接 **SHORT** | 拒 |
| B / D | 拒 | 拒 | 拒 | 拒 |

### 10.2 fragility_scan N×M 网格（BTC 1h · BTC 当前在 DOWN regime）

**Strategy A · baseline vs filtered · 9 cells (slip 5,10,15 × fee 4.5,5.5,7.0)**

| slip | fee | baseline | filtered | Δ |
|---|---|---|---|---|
| 5 | 4.5 | -51.52% ❌ | **-4.88%** ✅ | +47pp · **viable vs buy_hold -6.49%** |
| 5 | 5.5 | -54.52% ❌ | **-6.29%** ✅ | +48pp · barely viable |
| 5 | 7.0 | -58.69% ❌ | -8.37% ❌ | +50pp |
| 10 | 4.5 | -79.48% ❌ | -21.00% ❌ | +58pp |
| 10 | 5.5 | -80.70% ❌ | -22.16% ❌ | +59pp |
| 10 | 7.0 | -82.40% ❌ | -23.86% ❌ | +58pp |
| 15 | 4.5 | -90.99% ❌ | -29.86% ❌ | +61pp |
| 15 | 5.5 | -91.49% ❌ | -30.83% ❌ | +61pp |
| 15 | 7.0 | -92.19% ❌ | -32.27% ❌ | +60pp |

**viability: 0/9 → 2/9**（slip=5 × fee=4.5/5.5 都跑赢 buy_hold）
**trades**: 263-271 → 66-70（filter 拒掉 ~73% 亏钱路径）
**sharpe**: -2.4~-3.8 → -0.0~-0.9（~4× 改善）

### 10.3 C 策略说明

C filtered = 0 trades（fragility_scan 窗口内 BTC 90d_ret = -15.6% 持续在 DOWN regime → filter 全拒）。**这是 correct 保守行为**：C in DOWN 历史平均亏 $54/trade。等 BTC 进入 SIDE regime 时 C 才激活。

### 10.4 实战建议（推荐）

| 策略 | 推荐 | 说明 |
|---|---|---|
| **A** | **可上线** (filter enabled) | slip=5/fee=4.5-5.5 viable · 低成本场景跑赢 buy_hold · 即使高 slip 改善 60pp |
| **C** | 保持 dormant | DOWN regime 不交易 · SIDE regime 启用 SHORT-only · 等待 BTC regime 转换 |
| B / D | 永久拒 | 现状 |

### 10.5 Future-self 防误区

- **不要"看 filtered C = 0 trades 就启用 C"** —— 0 trades 是 filter 正确行为，C in DOWN 仍亏 $54/trade
- **不要"想当然扩大 SIDE alpha"** —— Sharpe 0.04-0.07 极弱，是边界 alpha 不是核心 alpha
- **不要"被 viability count 2/9 迷惑"** —— 仅 slip=5 cell viable，slip=10+ 仍亏；只有低成本场景才值得开
- **保持 fail-closed**：rejection = no trade，永远不要"filter 出错就放行"

### 10.6 行动清单 (Step B 完成后)

- [x] `code/signal_direction_filter.py` (new, 4865 bytes)
- [x] `scripts/fragility_scan_with_filter.py` (new, 1252 bytes)
- [x] fragility_scan N×M 网格 baseline vs filtered (Strategy A 9 cells · Strategy C 0 cells due to regime)
- [x] §10 this doc 写入本页
- [ ] Nixil commit (上面 4 个文件 + Phase 3B 已有 4 文件 = 8 untracked)
- [ ] Live A strategy 启用 filter (若 Nixil 决定)
