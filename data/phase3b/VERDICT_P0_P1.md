# Phase B + C Verdict: Comprehensive Stability Audit

**Date**: 2026-07-29 22:50 CST
**Session**: ABC execution per Nixil directive (A=pre-reg, B=timeframe, C=carry)
**Pre-registration**: `data/phase3b/PREREGISTRATION.md` (frozen 22:35 CST)

---

## 🚨 Headline Verdict

**ALL THREE PHASES FAILED pre-registered success criteria.**

| Phase | Hypothesis | Required | Actual | Pass? |
|-------|-----------|----------|--------|-------|
| A | Pre-registration freezing | (process) | Done 22:35 | ✅ |
| **B** | H1: 4h d ≥ 0.20, p < 0.001 | Yes | d=-0.110, p=0.83 (NEGATIVE) | ❌ |
| **B** | H2: 1d d ≥ 0.20, p < 0.001 | Yes | d=0.086, p=0.39 (n=11 insufficient) | ❌ |
| **B** | H3: combined 4h+1d viable | Yes | fails individually | ❌ |
| **C** | H4: Carry Sharpe ≥ 0.30, p<0.05 | Yes | Sharpe=-2.54, p=0.785 | ❌ |
| **C** | H5: Carry + A combined improves | Yes | A has no alpha (per P0) | ❌ (untestable) |

**Conclusion**: We have **no demonstrable alpha** in any approach tested. The pre-registered failure modes F1 (no timeframe shows viable alpha) and F5 (carry negative) both fire.

---

## 📊 Phase B Detailed Results: Timeframe Comparison

### Setup
- Aggregated BTC 1h klines → 4h and 1d (deterministic resampling, no API fetch)
- 4h: 3,751 bars (2024-10-26 → 2026-07-13)
- 1d: 626 bars (same range)
- Ran `fragility_scan.py` on A strategy at slip={5,10,15} bps, fee=5 bps, leverage=5x

### Results Across Timeframes (slip=5, fee=5 — the "best cost cell")

| Timeframe | n trades | mean PnL | std PnL | total | win% | Cohen's d | p (1-sided) | Verdict |
|-----------|----------|----------|---------|-------|------|-----------|-------------|---------|
| 1h (walkforward combined) | 187 | $16.24 | $254 | $3,037 | 44.9% | 0.064 | 0.192 | NOT sig |
| 4h | 76 | **-$23.35** | $212 | -$1,774 | **35.5%** | **-0.110** | **0.830** | **NEGATIVE** |
| 1d | 11 | $20.06 | $234 | $221 | 45.5% | 0.086 | 0.391 | NOT sig (n too small) |

### Fragility Scan Viability (3 cost cells: slip {5,10,15} × fee 5)

| Timeframe | viable cells | viable/total |
|-----------|--------------|--------------|
| 1h (existing a-btc-full) | 1/3 (only slip=5) | 33% |
| 4h | **0/3** | **0%** |
| 1d | 3/3 | 100% (but n=11) |

### Interpretation

- **1h (existing)**: marginal. Best estimate +$16/trade, but p=0.19 — NOT distinguishable from zero.
- **4h**: significantly NEGATIVE. d=-0.110 means the strategy loses money on average. Win rate 35.5% < 50% means the strategy is structurally wrong for 4h timeframe.
- **1d**: only 11 trades over 626 days. Statistical test meaningless (n too small). Viability 3/3 is illusory — with such small sample, ret% is dominated by noise.

### Why 4h Fails (post-mortem)

The A strategy uses EMA20 + 2-bar confirmation + volume ratio + RSI filter. On 4h bars:
- EMA20 = 80 hours of lookback (~3.3 days)
- 2-bar confirmation = 8 hours
- The signal-to-noise ratio on 4h is **lower** because 4h bars have higher volatility per bar (median range 111 bps vs 53 bps on 1h)
- Result: more whipsaws, worse entries, worse exits

**Higher timeframe is NOT a magic bullet.** Moving from 1h to 4h made things worse, not better.

---

## 📊 Phase C Detailed Results: Funding Rate Carry

### Setup
- Data: 292 funding periods (8h each), 2026-04-07 → 2026-07-13 (97 days)
- Strategy (frozen per pre-reg):
  - SHORT when funding > +0.5 bps (collect from longs paying)
  - LONG when funding < -0.5 bps (collect from shorts paying)
  - Hold K=1 funding period (8h)
  - 1x notional, no leverage
  - Cost: 10 bps round-trip (slip 5 + fee 5)

### Results

**Trades generated**: 107
- 82 short signals (funding > +0.5 bps)
- 25 long signals (funding < -0.5 bps)
- 185 neutral periods (skipped)

**Per-trade PnL (on $1000 notional)**:
- Mean: **-$1.03**
- Median: -$1.52
- Std: $13.50
- Total: -$110.71 (-11% over 97 days)
- Win rate: 43.0%

**PnL Decomposition**:
- Funding collected: -$8.08 (NEGATIVE — we collected negative funding because this was a BTC bull run, shorts got squeezed)
- Price PnL: +$4.37 (positive — longs covered by negative funding did OK)
- Cost: $107.00 (10 bps × 107 trades)

### Success Criteria Check

| Criterion | Required | Actual | Pass? |
|-----------|----------|--------|-------|
| Sharpe annualized | ≥ 0.30 | **-2.54** | ❌ |
| p (one-sided) | < 0.05 | **0.785** | ❌ |
| Bonferroni (6 tests) | < 0.0083 | 0.785 | ❌ |
| Profit factor | ≥ 1.20 | **0.80** | ❌ |
| Max DD ≤ 15% | yes | yes | ✅ (vacuous — total DD is small) |

### Interpretation

- Carry strategy lost money on this 97-day window
- The window was BTC UPTREND (April-July 2026), so shorts got squeezed
- Funding collected was actually NEGATIVE because we shorted in an uptrend (the funding was high precisely BECAUSE shorts were getting squeezed, and we added to the squeeze)
- Cost ($107 on $1000 notional × 107 trades = 10.7% drag) exceeded funding collected

**Funding carry is NOT a stable alpha source on this data.** It depends entirely on which regime BTC is in.

---

## 💀 Combined Verdict: Three Independent Approaches, All Fail

| Approach | Test | Result |
|----------|------|--------|
| **A strategy on 1h** | Multiple comparison correction (P0) | p=0.19, NOT significant |
| **A strategy on 4h** | Higher timeframe test (Phase B) | p=0.83, SIGNIFICANTLY NEGATIVE |
| **A strategy on 1d** | Higher timeframe test (Phase B) | p=0.39, n=11 insufficient |
| **Funding carry** | Frozen carry strategy (Phase C) | p=0.785, Sharpe -2.54 |

**Three independent approaches. All fail statistical significance.** The "alpha" we thought we had is not detectable.

---

## 🪞 Why We're Failing: Diagnosis

### Diagnosis 1: Effect sizes are tiny, sample sizes are small

| Cell | Cohen's d | n have | n needed (80% power, p<0.05) | Gap |
|------|-----------|--------|------------------------------|-----|
| A×1h | 0.064 | 187 | 1,900 | 10× |
| A×4h | -0.110 | 76 | 650 (for d=0.20) | 8.5× |
| A×1d | 0.086 | 11 | 1,070 | 97× |
| Carry | -0.077 | 107 | 1,330 | 12.4× |

**We are uniformly underpowered by 8-100×.** Even if true alpha were EXACTLY what backtest shows, we can't statistically distinguish it from zero.

### Diagnosis 2: Cost floor eats any plausible alpha

- 1h BTC slip: ≥5 bps one-way (100% of bars)
- Carry cost: 10 bps round-trip per funding period
- Best alpha estimate: $16/trade on 1h A strategy
- Best alpha estimate: $20/trade on 1d A strategy (but n=11)

For a $3000 notional position (5x leverage on $600 margin):
- 1h round-trip cost: 30 bps = $9
- Best alpha per trade: $16
- Net of cost: ~$7/trade (which is below statistical noise of $254)

### Diagnosis 3: We're sampling a single regime

The 97-day funding window (2026-04-07 → 2026-07-13) was BTC in strong uptrend. Our 1h klines span 20 months including both bull and bear periods, but:
- Walkforward combined trades dilute signal across regimes
- We don't have regime-conditional statistical tests with sufficient n per regime

### Diagnosis 4: We lack out-of-sample data

All tests are in-sample. We have:
- 20 months of 1h BTC klines
- 3 months of funding rate data
- No held-out test set

We can't prove generalization.

---

## 🛑 What This Means (Hard Truth)

Per pre-registered failure modes:

- **F1 fires**: No timeframe shows d ≥ 0.20 → **reset to research-only mode, no live deployment**
- **F5 fires**: Carry Sharpe negative or zero → **carry alone is not viable**

**Operational implication**:
1. **NO live deployment** of A strategy (or any variant we've tested)
2. **Manual positions only** remain (BTC + ETH manual LONG, `EXTERNAL_WEB_SYNC`)
3. **Stop iterating on current strategies** — they have no statistical basis
4. **Pivot strategy design** — fundamental rethink required

---

## 📋 What Should Happen Next (Recommendations)

### Tier 1: Acknowledge & Stop
1. **Remove "A strategy viable" from any operational assumption** — it's not
2. **Update regime filter / direction filter** to NOT pretend to add edge — they don't
3. **Hold live deployment in abeyance** until alpha is proven with proper statistical test
4. **Document this finding as P0 incident** in MEMORY.md (post-mortem)

### Tier 2: Research-mode Pivot
The fundamental issue is **signal-to-noise ratio**. Options:

**Option A: Increase sample size**
- Add more instruments (ETH, SOL — but ETH was 0/3 viable, so probably not)
- Add more history (we have ~20 months; OKX has 5+ years)
- Run on lower frequency for higher trades per period

**Option B: Increase effect size**
- Find strategies with higher Cohen's d (target d > 0.20)
- This requires fundamentally different strategy design, not parameter tuning

**Option C: Decrease noise**
- Better execution (limit orders, TWAP) reduces cost noise
- Tighter stops reduce variance per trade

### Tier 3: Pre-register next round
Before doing any of Tier 2, **freeze the next hypothesis** so we don't p-hack again.

---

## 📂 Files Produced This Session

| File | Purpose |
|------|---------|
| `data/phase3b/PREREGISTRATION.md` | Frozen hypotheses for Phase B + C |
| `data/phase3b/p0_audit_report.md` | P0 multiple comparison + slip + power |
| `data/phase3b/multiple_comparison_results.json` | Per-cell stats |
| `data/phase3b/p0_multiple_comparison_audit.py` | Reproducible script |
| `data/phase3b/p0_real_slip_audit.py` | Slip analysis |
| `data/phase3b/p0_power_analysis.py` | Power analysis |
| `data/phase3b/aggregate_klines.py` | 1h → 4h/1d aggregation |
| `data/market/BTC-USDT-SWAP/4h.parquet` | New aggregated data |
| `data/market/BTC-USDT-SWAP/1d.parquet` | New aggregated data |
| `data/phase3b/p1_funding_carry_backtest.py` | Carry backtest (reproducible) |
| `data/phase3b/p1_carry_trades.parquet` | Carry trade records |
| `data/phase3b/VERDICT_P0_P1.md` | This document |

---

## 🔗 For Future 小野

**This is the most important finding of the project so far.**

For 1 month we've been building increasingly sophisticated backtest infrastructure (walkforward, fragility_scan, regime filter, direction filter, bootstrap). All of it was optimizing for point estimates we never verified were statistically distinguishable from noise.

**Lesson**: Statistical significance check is a 5-minute, 30-line script. It should be the FIRST thing run after any backtest, not the LAST.

**Process change proposal**:
1. Any new backtest MUST pass significance gate (p < 0.001 after Bonferroni) before being eligible for production consideration
2. Walkforward / fragility_scan / regime filter / direction filter — none of these can CREATE alpha. They can only FILTER alpha that already exists. If base strategy has no alpha, filters add nothing.
3. Pre-registration discipline: any test must be pre-registered with frozen params + frozen success criterion

**Three strikes**:
- P0: current strategies no alpha
- Phase B: higher timeframe no alpha (worse, in fact)
- Phase C: carry no alpha

**The framework needs a reset, not iteration.**

---

**Status**: Awaiting Nixil review of full verdict.
**Operational recommendation**: Hold live deployment. Pivot to research-mode only. Do NOT iterate on current strategies without fundamental rethink.