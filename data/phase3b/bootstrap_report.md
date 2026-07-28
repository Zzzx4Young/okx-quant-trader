# Phase 3B Bootstrap Report

_n_iter=1000, seed=20260728, ruin_threshold=-200_

## Strategy A

| Regime | n | Mean (CI) | prob_ruin | Verdict |
|---|---|---|---|---|
| ALL | 561 | -2.3 [-21, +16] | 0% | ❌ negative mean |
| A | 204 | +6.0 [-21, +34] | 0% | — |
| UP | 96 | -51.6 [-93, -9] | 0% | ✅ baseline correct (拒 UP 是对的) |
| SIDE | 261 | +9.4 [-20, +35] | 0% | — |

### Decision
  ✅ **keep regime_filter as-is** (A=+6.0, SIDE=+9.4, A≈SIDE within noise)

## Strategy C

| Regime | n | Mean (CI) | prob_ruin | Verdict |
|---|---|---|---|---|
| ALL | 690 | -31.6 [-48, -15] | 0% | ❌ negative mean |
| A | 303 | -54.2 [-75, -30] | 0% | ❌ negative mean |
| UP | 111 | -91.2 [-123, -62] | 0% | ✅ baseline correct (拒 UP 是对的) |
| SIDE | 276 | +17.1 [-8, +45] | 0% | — |

### Decision
  ❌ **regime_filter is WRONG** (A=-54.2 < 0, SIDE=+17.1 > 0) → reject A, allow SIDE

