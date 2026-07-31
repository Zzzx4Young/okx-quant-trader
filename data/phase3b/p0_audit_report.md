# P0 Audit Report: Statistical Reality Check

**Date**: 2026-07-29 22:30 CST
**Scope**: Honest assessment of whether our backtested "alpha" is statistically real
**Verdict**: ❌ **NO statistical evidence of alpha. We have been curve-fitting noise.**

---

## 🚨 Executive Summary

After three independent audits (multiple comparison correction, slip reality, power analysis), we must conclude:

1. **Zero cells survive even naive α=0.05 significance** — best p-value was 0.123
2. **Best "alpha" cell ($13/trade A×A×LONG) has p=0.25** — indistinguishable from noise
3. **Real slip on 1h BTC-SWAP is ≥5 bps one-way floor (100% of bars exceed)** — fragility_scan's slip=5 viability is borderline optimistic
4. **We are 4-14× underpowered** — to detect even our best effect at p<0.05 we'd need 600-5,600 trades; we have 138-561
5. **Conclusion**: Current strategies (A, B, C) do NOT have demonstrable alpha on this data. The "winning cells" we shipped on are likely curve-fitted noise within the natural variance of trade returns.

**Strategic implication**: The path to "stable profitability" cannot be "improve current strategies". It requires **fundamentally different approaches** (higher timeframe, lower-frequency, or known crypto alpha sources like funding rate carry).

---

## 📊 Audit 1: Multiple Comparison Correction

**Method**: One-sample t-test on mean(net_pnl) > 0 per strategy × regime × direction cell (n≥30). Bonferroni / Holm-Bonferroni / Benjamini-Hochberg corrections applied.

**Honest test accounting**:
- 2 strategies (A, C) tested in detail
- 4 regime buckets (A/UP/SIDE/ALL)
- 3 direction buckets (LONG/SHORT/ALL)
- 9 cost cells in fragility_scan
- 2 with/without direction filter
- = **216-432 theoretical hypothesis tests**

**Results — Best 10 cells by p-value**:

| Cell | n | mean ($) | 95% CI | p (1-sided) | Bonf (48) | BH (5%) |
|------|---|----------|--------|-------------|-----------|---------|
| C × SIDE × SHORT | 138 | +27.47 | [-19, +74] | **0.1232** | ✗ | ✗ |
| C × SIDE | 276 | +17.12 | [-15, +50] | 0.1512 | ✗ | ✗ |
| A × ALL × LONG | 312 | +10.69 | [-17, +38] | 0.2228 | ✗ | ✗ |
| **A × DOWN × LONG** ⭐ | 165 | +13.02 | [-25, +51] | **0.2515** | ✗ | ✗ |
| A × SIDE × SHORT | 141 | +13.77 | [-32, +60] | 0.2779 | ✗ | ✗ |
| A × SIDE | 261 | +9.35 | [-23, +41] | 0.2833 | ✗ | ✗ |
| A × DOWN | 204 | +6.00 | [-29, +41] | 0.3666 | ✗ | ✗ |
| C × SIDE × LONG | 138 | +6.78 | [-39, +53] | 0.3859 | ✗ | ✗ |
| A × SIDE × LONG | 120 | +4.16 | [-41, +49] | 0.4270 | ✗ | ✗ |
| A × ALL | 561 | -2.30 | [-23, +19] | 0.5845 | ✗ | ✗ |

**Worst cells (significant NEGATIVE alpha)**:
- C × ALL: -$31.60 (CI [-51, -12]) — significant loss
- C × DOWN: -$54.17 (CI [-82, -26]) — definitely losing
- C × UP: -$91.18 (CI [-131, -52]) — definitely losing
- A × UP: -$51.65 (CI [-100, -3]) — likely losing

**The "winning cell" we shipped on (A × DOWN × LONG)**:
- Mean $13.02/trade, n=165, CI [-$25, +$51]
- p-value (one-sided) = 0.2515
- Survives naive α=0.05? **NO**
- Survives Bonferroni (48 tests)? **NO**
- Survives Bonferroni (432 tests)? **NO**

**Interpretation**: Our regime filter over-restricts (rejects C in SIDE which had +$17/trade mean). But even the cells that pass our regime filter don't survive basic significance testing.

---

## 💸 Audit 2: Slip Reality Check

**Method**: Analyzed 15,000 BTC 1h bars (Oct 2024 → Jul 2026, 624 days) to compute realistic slip floor.

**Bar statistics**:
- Median bar range (high-low): 52.9 bps
- Median bar body (|close-open|): 20.9 bps
- Annualized vol: 46%
- Top 10% volatility bars: 187 bps mean range

**Slip floor (% of bars exceeding X bps one-way)**:

| Threshold | % bars exceed | Implication |
|-----------|---------------|-------------|
| > 5 bps | **100.0%** | fragility_scan slip=5 is the absolute floor |
| > 10 bps | 99.6% | slip=10 is realistic default |
| > 15 bps | 97.8% | slip=15 covers ~98% of bars |
| > 20 bps | 94.4% | High-vol bars start here |
| > 30 bps | 81.9% | Stressed market |

**Realistic achievable one-way slip on 1h BTC-SWAP**:

| Execution style | Normal vol | High vol (>50 bps bar) |
|-----------------|------------|----------------------|
| Limit at mid (best case) | 1-2 bps | 2-5 bps |
| Limit with spread cross | 3-5 bps | 5-10 bps |
| Market order (worst case) | 5-15 bps | 15-30 bps |

**Verdict on fragility_scan assumptions**:
- fragility_scan's "viable at slip=5" finding was the **only positive viability signal** we had
- Realistic 1h slip is ≥5 bps one-way 100% of the time → slip=5 is the floor, not the average
- For a position held 10 hours, intra-bar volatility easily pushes realized slip to 10+ bps
- **fragility_scan's viability at slip=5 overstates true viability by ~2x**

For BTC at $60k with 0.3 BTC typical position:
- Round-trip slip 10 bps = $36/trade cost
- Round-trip slip 20 bps = $72/trade cost
- A × A × LONG mean = $13/trade
- **A single round-trip's slippage wipes out 3-5 trades' worth of expected alpha**

---

## ⚡ Audit 3: Statistical Power Analysis

**Question**: If our backtested alpha were EXACTLY real, would we have enough data to detect it?

**Cohen's d = mean / std per trade**:

| Cell | d (effect size) | n_have | n_need (α=0.05, power=0.80) | Multiplier |
|------|-----------------|--------|------------------------------|------------|
| A × DOWN × LONG | 0.052 | 165 | **2,250** | 13.6× |
| C × SIDE × SHORT | 0.099 | 138 | 631 | 4.6× |
| C × SIDE | 0.062 | 276 | 1,593 | 5.8× |
| A × SIDE | 0.036 | 261 | 4,884 | 18.7× |
| A × DOWN | 0.024 | 204 | 10,787 | 52.9× |
| A × ALL | -0.009 | 561 | 76,176 | 135.8× |

**Verdict**: We are **4-14× underpowered** for our best cells. For the broader regime-agnostic averages, we need 10,000-100,000 trades to detect.

Even if true alpha were exactly what backtest shows, **we cannot statistically distinguish it from zero** with current data.

---

## 🎯 Strategic Implications

### What this means for OKX framework

**Current state**: We have a complex backtest infrastructure that produces point estimates with 95% CIs. We've been "shipping on the winning cell" (A × DOWN × LONG) but that cell's CI crosses 0 — it's not significantly different from zero.

**Implication for the 3 strategies**:
- **A strategy**: Best case mean +$13/trade, but p=0.25 — likely noise within $250/trade variance
- **B strategy**: Permanently disabled (Kelly negative) — already correctly retired
- **C strategy**: Best mean +$27/trade in C × SIDE × SHORT (p=0.12) — also likely noise; but note C's SIDE regime mean is positive vs A's SIDE which is also positive, suggesting SIDE-friendly alpha might exist

**Implication for live deployment**: ❌ **DO NOT deploy live capital.** Even our best cell has >75% probability of being unprofitable.

### Path forward: 4 options ranked

#### Option 1: Move to higher timeframe (4h / 1d) — RECOMMENDED FIRST STEP

**Rationale**: Slip scales with intra-bar volatility. 4h bars have ~2× larger body/range, so slip becomes relatively less important. Signal/noise ratio improves.

**Test**: Re-run A strategy backtest on 4h and 1d timeframes. Compute same multiple comparison correction. If effect size d > 0.15 (vs current 0.05), we're closer to viable.

**Effort**: 4-8 hours (need to ensure kline data exists for 4h/1d, otherwise fetch).

#### Option 2: Funding rate carry research — FUNDAMENTALLY DIFFERENT ALPHA

**Rationale**: Funding rate is a known persistent alpha source in crypto perpetual futures. Direction-independent. Works in SIDE regime (where BTC spends ~30% of time).

**Test**: Pull `data/funding/BTC-USDT-SWAP_funding.parquet`. Compute carry PnL for a "long when funding > X, short when funding < Y" strategy. Test across regimes.

**Effort**: 6-10 hours (research + backtest).

**Advantage**: Effect size is typically MUCH larger (Sharpe 0.3-0.5 per trade vs our 0.05).

#### Option 3: Accept exploratory status, require pre-registration

**Rationale**: If we continue iterating on strategies, we will keep curve-fitting. Pre-register hypothesis before testing to avoid p-hacking.

**Test**: Before next backtest, write down:
- Exact hypothesis
- Exact strategy parameters (frozen)
- Exact evaluation window
- Exact success criterion (effect size d > 0.20, p < 0.001)

**Effort**: 1 hour to set up discipline; ongoing.

#### Option 4: Reduce cost floor via execution engineering

**Rationale**: Our slip floor is the dominant cost. If we can get round-trip cost to <5 bps reliably (using limit orders aggressively, TWAP, etc.), even small alpha becomes viable.

**Test**: Build an execution simulator that compares market order vs limit order fill rates and realized slip. Test against 1h BTC data.

**Effort**: 8-12 hours.

---

## 📋 Recommended Action Plan (next 1-2 weeks)

**Week 1**:
1. **Mon-Tue**: Fetch 4h and 1d BTC klines (if missing). Run A strategy backtest on both. Power analysis on each.
2. **Wed-Thu**: Funding rate carry research. Quantify Sharpe.
3. **Fri**: Decision point: do we have a viable alpha candidate? If yes → Option 1/2. If no → broader reset.

**Week 2** (if Week 1 finds candidate):
4. **Execution simulation** — what's the achievable slip with limit orders?
5. **Stress test** — 2022 crypto winter, 2020-03 crash, 2021-05 LUNA crash.
6. **Pre-registered hold-out test** — lock 6 months of recent data, evaluate candidate strategy blind.

**Week 2** (if Week 1 finds nothing):
4. **Reset**: Accept current framework's strategies are not viable. Pivot to research-mode only, no live deployment. Focus on alpha source research (fundamentals: what makes money in crypto?).

---

## 🔗 Data Files Produced

- `data/phase3b/multiple_comparison_results.json` — full per-cell stats + corrections
- `data/phase3b/p0_multiple_comparison_audit.py` — reproducible script
- `data/phase3b/p0_real_slip_audit.py` — slip analysis script
- `data/phase3b/p0_power_analysis.py` — power analysis script
- `data/phase3b/p0_audit_report.md` — this document

---

## 💡 Meta-lesson (for future 小野)

This audit was 45 minutes of work. It should have been done BEFORE:
- Shipping the direction filter
- Running fragility_scan with filter
- Considering any live deployment

**Lesson**: Statistical significance check is a 30-line script (`scipy.stats.ttest_1samp`) that takes 5 minutes to run. **It should be the FIRST thing run on any backtest result, not the last.**

We had 1 month of increasingly sophisticated backtest infrastructure (fragility_scan, walkforward, bootstrap, direction filter, regime filter). All of it was optimizing for point estimates we never verified were distinguishable from noise.

**P0 should have been: does A have alpha? Yes/No/Can't tell.** We skipped that question and went straight to "how do we make A better?"

---

**Status**: Awaiting Nixil direction on which Option 1-4 to pursue.
**Estimated work**: 1-2 weeks for any single option, longer if all four.
**Key decision**: Do we have ANY viable alpha candidate after Week 1, or do we accept current framework can't produce one?