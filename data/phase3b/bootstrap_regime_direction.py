"""Phase 3B Track A: Regime × Direction Filter bootstrap analysis.

Hypothesis (from data mining 2026-07-28 23:08):
- A in DOWN regime: 165 LONG (mean +$13.02) vs 39 SHORT (mean -$23.67)
  → A's "alpha in DOWN" is from LONG, not SHORT
- A in UP regime: 27 LONG (mean +$25.41) vs 69 SHORT (mean -$81.80)
- C in SIDE regime: 138 LONG (mean +$6.78) vs 138 SHORT (mean +$27.47)
  → C's "alpha in SIDE" is from SHORT only

Goal: Bootstrap each (strategy × regime × direction) cell separately,
evaluate "if we filtered by direction within regime, what's the alpha?"

Outputs:
- data/phase3b/bootstrap_results_direction.json (raw)
- data/phase3b/bootstrap_report_direction.md (human-readable verdict)

Run:
    python3 data/phase3b/bootstrap_regime_direction.py
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WORKSPACE = Path("/home/zzzx47/.openclaw/workspace")
PROJECT_ROOT = WORKSPACE / "okx"
PHASE3B_DIR = PROJECT_ROOT / "data" / "phase3b"

REGIMES = ["A", "UP", "SIDE", "UNKNOWN"]
DIRECTIONS = ["long", "short"]
STRATEGIES = [("a", "A"), ("c", "C")]
PROB_RUIN_THRESHOLD = -200.0


def bootstrap_subset(net_pnl: np.ndarray, n_iter: int, rng: np.random.Generator) -> dict | None:
    n = len(net_pnl)
    if n < 5:
        return None
    idx = rng.integers(0, n, size=(n_iter, n))
    samples = net_pnl[idx]
    means = samples.mean(axis=1)
    return {
        "n": int(n),
        "raw_mean": float(net_pnl.mean()),
        "raw_median": float(np.median(net_pnl)),
        "raw_std": float(net_pnl.std()),
        "raw_pos_frac": float((net_pnl > 0).mean()),
        "raw_sum": float(net_pnl.sum()),
        "mean_ci_low": float(np.percentile(means, 5)),
        "mean_ci_high": float(np.percentile(means, 95)),
        "prob_ruin": float((means < PROB_RUIN_THRESHOLD).mean()),
        "prob_negative_mean": float((means < 0).mean()),
    }


def analyze_cell(df: pd.DataFrame, regime: str, direction: str, n_iter: int, rng: np.random.Generator) -> dict | None:
    """Filter to (regime, direction) and bootstrap."""
    subset = df[(df["_regime"] == regime) & (df["direction"] == direction)]
    if subset.empty:
        return None
    return bootstrap_subset(subset["net_pnl"].to_numpy(), n_iter, rng)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-iter", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260728)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    print(f"Phase 3B Track A · Regime × Direction Filter · n_iter={args.n_iter}")

    all_results = {}
    md_parts = ["# Phase 3B Track A · Regime × Direction Filter Bootstrap",
                "",
                f"_n_iter={args.n_iter}, seed={args.seed}_",
                "_prob_ruin threshold: mean < -$200/trade_",
                "",
                "**Hypothesis**: A 的 DOWN alpha 来自 LONG（拒 SHORT）· C 的 SIDE alpha 来自 SHORT（拒 LONG）",
                ""]

    for strat_key, strat_label in STRATEGIES:
        pq_path = PHASE3B_DIR / f"{strat_key}_trades_with_regime.parquet"
        df = pd.read_parquet(pq_path)
        print(f"\n=== Strategy {strat_label} ({strat_key}) · {len(df)} trades ===")

        all_results[strat_label] = {}
        md_parts.append(f"## Strategy {strat_label}")
        md_parts.append("")
        md_parts.append("| Regime × Direction | n | mean (CI) | prob_ruin | Verdict |")
        md_parts.append("|---|---|---|---|---|")

        # Full table
        for regime in REGIMES:
            for direction in DIRECTIONS:
                stats = analyze_cell(df, regime, direction, args.n_iter, rng)
                if stats is None:
                    continue
                key = f"{regime}_{direction}"
                all_results[strat_label][key] = stats
                ci = f"[{stats['mean_ci_low']:+.0f}, {stats['mean_ci_high']:+.0f}]"
                # Verdict
                v = ""
                if stats["raw_mean"] < 0:
                    v = "❌ negative mean"
                elif stats["raw_mean"] > 0:
                    if stats["mean_ci_low"] > 0:
                        v = "✅ positive mean · **CI 全正**"
                    else:
                        v = "⚠️ positive but CI 过 0"
                md_parts.append(
                    f"| {regime} × {direction} | {stats['n']} | "
                    f"{stats['raw_mean']:+.1f} {ci} | "
                    f"{stats['prob_ruin']:.0%} | {v or '—'} |"
                )

        # Regime-only (baseline, for comparison)
        for regime in REGIMES:
            subset = df[df["_regime"] == regime]
            if subset.empty:
                continue
            stats = bootstrap_subset(subset["net_pnl"].to_numpy(), args.n_iter, rng)
            if stats:
                key = f"{regime}_ALL"
                all_results[strat_label][key] = stats
                ci = f"[{stats['mean_ci_low']:+.0f}, {stats['mean_ci_high']:+.0f}]"
                md_parts.append(
                    f"| {regime} × ALL | {stats['n']} | "
                    f"{stats['raw_mean']:+.1f} {ci} | "
                    f"{stats['prob_ruin']:.0%} | baseline |"
                )

        md_parts.append("")

    # Verdict section
    md_parts.extend([
        "## Filter Recommendation",
        "",
        "If we apply direction filter within regime, here's the alpha:",
        "",
    ])

    # A: DOWN → LONG only (drop SHORT)
    a_down_long = all_results.get("A", {}).get("A_long")
    a_down_short = all_results.get("A", {}).get("A_short")
    if a_down_long and a_down_short:
        kept = a_down_long["raw_mean"] * a_down_long["n"]
        dropped = a_down_short["raw_mean"] * a_down_short["n"]
        md_parts.extend([
            f"### Strategy A · DOWN regime",
            f"- **KEEP** LONG: n={a_down_long['n']}, mean=+${a_down_long['raw_mean']:.1f} (sum +${kept:.0f})",
            f"- **DROP** SHORT: n={a_down_short['n']}, mean=-${a_down_short['raw_mean']:.1f} (sum ${dropped:.0f})",
            f"- Net effect: **+${kept + dropped:.0f}** vs **${kept:.0f}** baseline",
            "",
        ])

    # C: SIDE → SHORT only (drop LONG)
    c_side_long = all_results.get("C", {}).get("SIDE_long")
    c_side_short = all_results.get("C", {}).get("SIDE_short")
    if c_side_long and c_side_short:
        kept = c_side_short["raw_mean"] * c_side_short["n"]
        dropped = c_side_long["raw_mean"] * c_side_long["n"]
        md_parts.extend([
            f"### Strategy C · SIDE regime",
            f"- **KEEP** SHORT: n={c_side_short['n']}, mean=+${c_side_short['raw_mean']:.1f} (sum +${kept:.0f})",
            f"- **DROP** LONG: n={c_side_long['n']}, mean=+${c_side_long['raw_mean']:.1f} (sum +${dropped:.0f})",
            f"- Net effect: keep SHORT only (LONG is +$6.78 mean but wide CI)",
            "",
        ])

    # Save
    json_path = PHASE3B_DIR / "bootstrap_results_direction.json"
    with open(json_path, "w") as f:
        json.dump(
            {"n_iter": args.n_iter, "seed": args.n_seed if hasattr(args, "n_seed") else args.seed, "results": all_results},
            f, indent=2,
        )
    md_path = PHASE3B_DIR / "bootstrap_report_direction.md"
    md_path.write_text("\n".join(md_parts) + "\n", encoding="utf-8")
    print(f"\n✅ JSON: {json_path}")
    print(f"✅ Report: {md_path}")


if __name__ == "__main__":
    main()