"""
P0-2: Multiple Comparison Correction Audit
==========================================

Question: After honest accounting of all hypothesis tests we ran, is A strategy's
"alpha" still statistically significant?

Strategy × Regime × Direction × Cost cell combinations tested:
- 3 strategies (A, B, C) — B analysed for Kelly but disabled
- 3 regimes (A, UP, SIDE)
- 2 directions (LONG, SHORT)
- 9 cost cells (3 slip × 3 fee in fragility_scan grid)
- 2 with/without direction filter
= 3 × 3 × 2 × 9 × 2 = 324 cells theoretically explored

Conservative accounting for tests that yielded published point estimates / decisions:
- A: 3 regimes × 2 directions = 6 cells (per regime bootstrap results)
- C: 3 regimes × 2 directions = 6 cells
- fragility_scan: 2 strategies × 9 cost cells × 2 with/without filter = 36 cells
- Total: 48 cells with published numbers
- Plus direction filter rule decisions: ~6 implicit tests

Per-test α thresholds:
- Naive α=0.05
- Bonferroni α=0.05/48 = 0.00104
- Holm-Bonferroni (step-down): much less conservative
- Benjamini-Hochberg (FDR control at 5%): most reasonable for exploratory research

Per-cell test: one-sample t-test of mean(net_pnl) > 0
Effect size: mean / std_error = t-statistic

Outputs verdict on whether any cell survives multiple comparison correction.
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats

ROOT = Path("/home/zzzx47/.openclaw/workspace/okx")
DATA = ROOT / "data" / "phase3b"


def compute_cell_stats(df: pd.DataFrame, strategy: str, regime: str, direction: str | None = None) -> dict | None:
    """Compute one-sample t-test for mean > 0."""
    subset = df[df["strategy"].str.contains(strategy, case=False, na=False)]
    if subset.empty:
        return None
    if regime != "ALL":
        subset = subset[subset["_regime"] == regime]
    if direction is not None:
        subset = subset[subset["direction"] == direction]
    n = len(subset)
    if n < 5:
        return None

    pnl = subset["net_pnl"].values
    mean = pnl.mean()
    std = pnl.std(ddof=1)
    se = std / np.sqrt(n)

    # One-sample t-test against 0
    t_stat, p_two_sided = stats.ttest_1samp(pnl, 0)
    p_one_sided = p_two_sided / 2 if t_stat > 0 else 1 - p_two_sided / 2

    # 95% CI on mean
    ci_low, ci_high = stats.t.interval(0.95, n - 1, loc=mean, scale=se)

    return {
        "n": n,
        "mean": mean,
        "std": std,
        "se": se,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "t_stat": t_stat,
        "p_one_sided": p_one_sided,
    }


def bonferroni(pvalues: list[float], alpha: float = 0.05) -> list[float]:
    """Classic Bonferroni: reject if p < alpha/m."""
    m = len(pvalues)
    threshold = alpha / m
    return [p < threshold for p in pvalues]


def holm_bonferroni(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    """Holm-Bonferroni step-down procedure."""
    m = len(pvalues)
    indexed = sorted(enumerate(pvalues), key=lambda x: x[1])
    rejected = [False] * m
    cummax_threshold = 0
    for rank, (orig_idx, p) in enumerate(indexed):
        threshold = alpha / (m - rank)
        if p < threshold:
            rejected[orig_idx] = True
            cummax_threshold = max(cummax_threshold, p)
        else:
            # Once we fail to reject, all larger ones also fail
            break
    return rejected


def benjamini_hochberg(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    """BH FDR control."""
    m = len(pvalues)
    indexed = sorted(enumerate(pvalues), key=lambda x: x[1])
    rejected = [False] * m
    max_p_below_threshold = 0
    for rank, (orig_idx, p) in enumerate(indexed, start=1):
        threshold = (rank / m) * alpha
        if p <= threshold:
            rejected[orig_idx] = True
            max_p_below_threshold = max(max_p_below_threshold, p)
    return rejected


def main():
    a_df = pd.read_parquet(DATA / "a_trades_with_regime.parquet")
    c_df = pd.read_parquet(DATA / "c_trades_with_regime.parquet")

    print(f"A trades: {len(a_df)} | regimes: {a_df['_regime'].value_counts().to_dict()}")
    print(f"C trades: {len(c_df)} | regimes: {c_df['_regime'].value_counts().to_dict()}")

    # Collect cells (we'll evaluate ALL strategy × regime × direction combinations)
    cells = []
    for strat, df in [("A", a_df), ("C", c_df)]:
        for regime in ["A", "UP", "SIDE", "ALL"]:
            for direction in ["long", "short", None]:  # None = all directions
                stats_dict = compute_cell_stats(df, strat, regime, direction)
                if stats_dict and stats_dict["n"] >= 30:  # only n>=30 cells
                    label = f"{strat}_{regime}_{direction or 'ALL'}"
                    cells.append({"label": label, **stats_dict})

    print(f"\nTotal cells with n>=30: {len(cells)}")

    # Honest multiple comparison accounting
    n_tests_total = (
        2  # strategies
        * 4  # regimes
        * 3  # direction buckets (long/short/all)
        * 9  # cost cells in fragility_scan
        * 2  # with/without direction filter
    )
    print(f"Total theoretical hypothesis tests: {n_tests_total} (Bonferroni α=0.05/{n_tests_total} = {0.05/n_tests_total:.6f})")

    # Sort by raw p-value
    cells_sorted = sorted(cells, key=lambda x: x["p_one_sided"])
    pvalues = [c["p_one_sided"] for c in cells_sorted]

    # Apply corrections
    bonf_rejected = bonferroni(pvalues)
    holm_rejected = holm_bonferroni(pvalues)
    bh_rejected = benjamini_hochberg(pvalues)

    print(f"\n{'='*100}")
    print("MULTIPLE COMPARISON CORRECTION — RAW CELLS (n>=30)")
    print(f"{'='*100}")
    print(f"{'Cell':<22} {'n':>5} {'mean':>10} {'CI_low':>10} {'CI_high':>10} {'p_1s':>10} {'Bonf':>6} {'Holm':>6} {'BH':>6}")
    print("-" * 100)

    for i, c in enumerate(cells_sorted):
        label = c["label"]
        bonf = "✓" if bonf_rejected[i] else "✗"
        holm = "✓" if holm_rejected[i] else "✗"
        bh = "✓" if bh_rejected[i] else "✗"
        print(f"{label:<22} {c['n']:>5} {c['mean']:>10.2f} {c['ci_low']:>10.2f} {c['ci_high']:>10.2f} {c['p_one_sided']:>10.4f} {bonf:>6} {holm:>6} {bh:>6}")

    # The "winning" cell: A × DOWN × LONG
    winning_cell = next((c for c in cells_sorted if c["label"] == "A_A_long"), None)
    if winning_cell:
        print(f"\n{'='*100}")
        print("FOCUS: A × DOWN × LONG (the 'winning' cell we shipped on)")
        print(f"{'='*100}")
        print(f"  n={winning_cell['n']}  mean=${winning_cell['mean']:.2f}  CI=[${winning_cell['ci_low']:.2f}, ${winning_cell['ci_high']:.2f}]")
        print(f"  p (one-sided) = {winning_cell['p_one_sided']:.4f}")
        print(f"  Survives naive α=0.05?     {'YES' if winning_cell['p_one_sided'] < 0.05 else 'NO'}")
        print(f"  Survives Bonferroni (48)?  {'YES' if winning_cell['p_one_sided'] < 0.05/48 else 'NO'}")
        print(f"  Survives Bonferroni (324)? {'YES' if winning_cell['p_one_sided'] < 0.05/324 else 'NO'}")

    # Save results
    out = {
        "n_cells_tested": len(cells),
        "n_tests_conservative_estimate": 324,
        "n_tests_conservative_min": 48,
        "alpha_naive": 0.05,
        "alpha_bonferroni_48": 0.05 / 48,
        "alpha_bonferroni_324": 0.05 / 324,
        "cells": [
            {**c,
             "bonferroni_rejected": bonf_rejected[i],
             "holm_rejected": holm_rejected[i],
             "bh_rejected": bh_rejected[i]}
            for i, c in enumerate(cells_sorted)
        ],
    }

    out_path = DATA / "multiple_comparison_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()