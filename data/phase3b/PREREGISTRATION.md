# Pre-Registration: Phase B (Timeframe) + Phase C (Funding Carry)

**Date frozen**: 2026-07-29 22:35 CST
**Author**: 小野
**Reviewer**: Nixil (待 review 后不可修改)
**Purpose**: Freeze hypotheses BEFORE running tests to prevent p-hacking, multiple comparison inflation, and post-hoc rationalization.

---

## Background & Motivation

P0 audit (2026-07-29 22:30 CST) revealed:
- A strategy × DOWN × LONG "winning cell": mean=$13.02/trade, p=0.25 (NOT significant)
- Best cell across all (C × SIDE × SHORT): p=0.12 (NOT significant)
- Slip floor 5 bps one-way = $36 round-trip cost ≈ 3× our best alpha
- We are 4-14× underpowered for current effect sizes

Conclusion: current framework's strategies have not demonstrated alpha. Going forward, we MUST pre-register hypotheses to avoid rebuilding the same trap.

---

## Phase B Pre-Registration: Higher Timeframe A Strategy

### Frozen Hypothesis

**H1 (Primary)**: A strategy (EMA_CROSSOVER, frozen params from `state/config.json` strategy_a block as of 2026-07-29 22:35 CST) on **4h timeframe** produces positive alpha with effect size Cohen's d ≥ 0.20 and statistical significance p < 0.001 (one-sided t-test against 0) on out-of-sample backtest.

**H2 (Secondary)**: Same strategy on **1d timeframe** produces same effect.

**H3 (Tertiary)**: Same strategy on combined 4h+1d timeframe produces same effect.

### Frozen Parameters (DO NOT MODIFY)

From `state/config.json` `strategy_a` block, frozen at 2026-07-29 22:35 CST:
- `name`: "EMA20_BREAKOUT"
- `ema_period`: 20
- `kline_count_for_confirmation`: 2
- `volume_ratio_threshold`: 0.7
- `atr_period`: 14
- `rsi_period`: 14
- `rsi_overbought`: 65
- `rsi_oversold`: 35

Regime filter (frozen from `code/regime_filter.py`):
- UP regime: 90d_ret > 10% AND EMA > 1.02
- DOWN regime: 90d_ret < -5% AND EMA < 1.0
- SIDE regime: otherwise

Position sizing (frozen from `code/risk.py` Kelly + Hard cap):
- Kelly f_full = computed from win rate × payout ratio
- Fractional = 1/4
- Volatility scaling × 0.7
- Hard cap = 1%

Cost assumptions:
- Slip = 5 bps one-way (10 bps round-trip) — best case with limit orders
- Fee = 5 bps round-trip (OKX taker tier 1)

### Frozen Evaluation Method

**Backtest engine**: `code/backtest/matcher.py` (frozen version as of commit prior to P0 work)
**Walkforward**: 3-month windows, 1-month stride
**Data**: BTC-USDT-SWAP klines (1h, 4h, 1d) from `data/market/BTC-USDT-SWAP/`
**Sample period**: Full available history (no cherry-picking)

### Frozen Success Criterion

- H1/H2/H3 only "pass" if all three hold:
  - Effect size d ≥ 0.20 (Cohen)
  - p < 0.001 (one-sided t-test against 0)
  - Sharpe annualized ≥ 0.50
  - Bonferroni-corrected significant at α=0.05 across ALL tested timeframes (3)
  - Viability across ≥3 of 9 fragility_scan cost cells (slip {5,10,15} × fee {4.5,5.5,7.0})

### Failure Modes (declare in advance)

- F1: **No timeframe shows d ≥ 0.20** → reset to research-only mode, no live deployment
- F2: **Only 1 timeframe passes** → consider that timeframe alone; do NOT generalize
- F3: **Effect size shrinks when combined** → investigate (likely over-fitting to one window)

---

## Phase C Pre-Registration: Funding Rate Carry Strategy

### Frozen Hypothesis

**H4 (Primary)**: A simple funding rate carry strategy (long spot / short perp OR long perp / short spot depending on funding sign) produces positive Sharpe > 0.3 annualized on BTC-USDT-SWAP funding rate history.

**H5 (Secondary)**: Carry + A trend filter combined improves risk-adjusted returns vs A alone.

### Frozen Strategy (Simple Carry)

```
For each 8h funding period:
  if funding_rate > X (positive): SHORT perp to collect funding
  if funding_rate < Y (negative): LONG perp to collect funding
  else: NEUTRAL

Frozen thresholds:
  X = +0.5 bps (0.00005) — collect when longs pay
  Y = -0.5 bps (0.00005) — collect when shorts pay

Position: 1x notional, hold for K funding periods (K=1 frozen)
Cost: 10 bps round-trip (slip=5, fee=5) per entry/exit
```

### Frozen Parameters (DO NOT MODIFY)

- X = +0.5 bps (0.00005)
- Y = -0.5 bps (0.00005)
- Hold K = 1 funding period (8h)
- Position notional = 1 unit (size 1, normalized)
- Slip = 5 bps one-way
- Fee = 5 bps round-trip
- No leverage (1x) for carry-only test

### Frozen Evaluation Method

**Data**: `data/funding/BTC-USDT-SWAP_funding.parquet` (frozen at 2026-07-29 22:35 CST, 292 records)
**Sample period**: 2026-04-06 → 2026-06-21 (97 days, 8h periods)

### Frozen Success Criterion

- H4 passes if:
  - Sharpe annualized ≥ 0.30
  - p < 0.05 (one-sided t-test on per-period carry PnL > 0)
  - Profit factor (gross profit / gross loss) ≥ 1.20
  - Max drawdown ≤ 15%

- H5 passes if:
  - Sharpe (A + carry combined) > Sharpe (A alone) by ≥ 0.20 with statistical significance

### Failure Modes

- F4: **Data too short (292 records)** — even with significant result, do NOT claim robust alpha. Declare "exploratory" and seek longer funding history.
- F5: **Sharpe negative or zero** → carry alone is not viable. Combine with A or skip.
- F6: **Sharpe positive but insignificant** → likely noise. Increase sample or abandon.

---

## Multiple Comparison Adjustment (Pre-Declared)

Total hypothesis tests in Phase B + C:
- Phase B: 3 timeframes × (1 hypothesis per timeframe) = 3 tests
- Phase C: 2 carry tests + combined = 3 tests
- Total = 6 tests

**Bonferroni α for "any hypothesis passes"**: α = 0.05 / 6 = 0.00833
**BH-FDR control**: declare any test significant only if q < 0.05

---

## Disclosure Rule

If ANY pre-registered hypothesis fails, the result is reported as FAILURE even if we find a "better" parameter combination in post-hoc analysis. Post-hoc findings must be clearly labeled "EXPLORATORY" and not used for live deployment decisions.

---

## Sign-off

| Role | Name | Date | Status |
|------|------|------|--------|
| Author | 小野 | 2026-07-29 22:35 CST | Drafted |
| Reviewer | Nixil | _____________ | Pending review |
| Frozen | — | _____________ | Reviewer signs = frozen; no edits allowed |

After Nixil signs, this document is the contract for what counts as "success" in Phase B + C. Any deviation = back to square one.

---

## Meta-Discipline Rules (Added R1 · 2026-07-29 22:55 CST)

Derived from P0/P1 findings (3 independent alpha methods, **zero statistical significance**). These rules are **process-level**, not strategy-level — they shape HOW we work going forward.

### Rule 1 · Significance Gate is Mandatory
- Every backtest result MUST report: **p-value + Cohen's d + Bonferroni-corrected significance**
- "Viable cell" claim requires **p < 0.001 (one-sided) AND d ≥ 0.20**
- No promotion to production consideration without this gate

### Rule 2 · Pre-Registration Discipline
- New strategy hypothesis MUST be pre-registered BEFORE backtest
- Required components: frozen hypothesis · frozen params · frozen evaluation · frozen success criterion · frozen failure modes
- Once frozen, edits require explicit sign-off (no silent override)

### Rule 3 · Filters Don't Create Alpha
- walkforward · fragility_scan · regime_filter · direction_filter are **filtering** tools
- They can only filter alpha that **already exists** in base strategy
- Never add filters to non-significant base hoping to "discover" alpha

### Rule 4 · Parameter Search Budget
- Max 3 parameter explorations per dataset (prevents p-hacking)
- After 3: must collect new data or change strategy direction

### Rule 5 · Statistical Power Honesty
- Declare expected effect size BEFORE computing p-value
- Compute required n for 80% power at α=0.05
- If current n < 50% of required → label "**EXPLORATORY**", not "SIGNIFICANT"
- Always show n_required alongside n_have

### Rule 6 · Failure Mode Honesty
- Pre-registered failure modes that trigger = accept the failure
- No post-hoc rationalization ("adjust X and it works")
- "EXPLORATORY" findings cannot be promoted to "CONFIRMED" without re-pre-registration

### Rule 7 · Operational Hold
- Until ANY strategy passes Rule 1 gate with d ≥ 0.20 AND n ≥ 200:
  - **NO live auto-trading**
  - Manual positions only (EXTERNAL_WEB_SYNC)
  - circuit_breaker.py in passive mode
- This supersedes any prior viability claims

### Rule 8 · Documentation Discipline
- Every backtest produces: reproducible script + parquet results + written verdict
- Pre-registration changes tracked with timestamp
- Cross-strategy reports updated within same session

---

## Updated Sign-off (Post-R1 Discipline)

| Role | Name | Date | Status |
|------|------|------|--------|
| Author (Phase B+C) | 小野 | 2026-07-29 22:35 CST | Drafted |
| Author (Meta-Discipline R1) | 小野 | 2026-07-29 22:55 CST | Drafted |
| Reviewer | Nixil | _____________ | **Pending review · blocks tomorrow's research start** |
| Frozen | — | _____________ | All rules frozen; no edits without sign-off |