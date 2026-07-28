# Phase 3B Track A · Regime × Direction Filter Bootstrap

_n_iter=1000, seed=20260728_
_prob_ruin threshold: mean < -$200/trade_

**Hypothesis**: A 的 DOWN alpha 来自 LONG（拒 SHORT）· C 的 SIDE alpha 来自 SHORT（拒 LONG）

## Strategy A

| Regime × Direction | n | mean (CI) | prob_ruin | Verdict |
|---|---|---|---|---|
| A × long | 165 | +13.0 [-18, +45] | 0% | ⚠️ positive but CI 过 0 |
| A × short | 39 | -23.7 [-93, +49] | 0% | ❌ negative mean |
| UP × long | 27 | +25.4 [-54, +104] | 0% | ⚠️ positive but CI 过 0 |
| UP × short | 69 | -81.8 [-126, -34] | 0% | ❌ negative mean |
| SIDE × long | 120 | +4.2 [-33, +39] | 0% | ⚠️ positive but CI 过 0 |
| SIDE × short | 141 | +13.8 [-26, +55] | 0% | ⚠️ positive but CI 过 0 |
| A × ALL | 204 | +6.0 [-21, +34] | 0% | baseline |
| UP × ALL | 96 | -51.6 [-93, -9] | 0% | baseline |
| SIDE × ALL | 261 | +9.4 [-20, +35] | 0% | baseline |

## Strategy C

| Regime × Direction | n | mean (CI) | prob_ruin | Verdict |
|---|---|---|---|---|
| A × long | 162 | -83.7 [-113, -53] | 0% | ❌ negative mean |
| A × short | 141 | -20.2 [-56, +17] | 0% | ❌ negative mean |
| UP × long | 60 | -91.3 [-133, -46] | 0% | ❌ negative mean |
| UP × short | 51 | -91.1 [-142, -41] | 0% | ❌ negative mean |
| SIDE × long | 138 | +6.8 [-30, +46] | 0% | ⚠️ positive but CI 过 0 |
| SIDE × short | 138 | +27.5 [-15, +64] | 0% | ⚠️ positive but CI 过 0 |
| A × ALL | 303 | -54.2 [-75, -30] | 0% | baseline |
| UP × ALL | 111 | -91.2 [-123, -62] | 0% | baseline |
| SIDE × ALL | 276 | +17.1 [-8, +45] | 0% | baseline |

## Filter Recommendation

If we apply direction filter within regime, here's the alpha:

### Strategy A · DOWN regime
- **KEEP** LONG: n=165, mean=+$13.0 (sum +$2148)
- **DROP** SHORT: n=39, mean=-$-23.7 (sum $-923)
- Net effect: **+$1225** vs **$2148** baseline

### Strategy C · SIDE regime
- **KEEP** SHORT: n=138, mean=+$27.5 (sum +$3790)
- **DROP** LONG: n=138, mean=+$6.8 (sum +$935)
- Net effect: keep SHORT only (LONG is +$6.78 mean but wide CI)

