"""Phase 3B bootstrap: regime-tagged walkforward trades → CI + prob_ruin per regime.

Inputs:
- data/phase3b/a_trades_with_regime.parquet (561 rows · regime A/SIDE/UP)
- data/phase3b/c_trades_with_regime.parquet (690 rows · regime A/SIDE/UP)

Outputs:
- data/phase3b/bootstrap_results.json (raw numbers, machine-readable)
- data/phase3b/bootstrap_report.md (human-readable verdict)

Method (per memory/2026-07-28.md §Phase 3B plan):
- For each strategy (A, C) × regime (A, SIDE, UP, UNKNOWN):
  - Resample trades with replacement, N=len(subset), 1000 iterations
  - Compute median_return, mean_return, prob_ruin per iter
  - 5/95 CI from bootstrap distribution
- prob_ruin = fraction of bootstraps where mean_return < -$200 (i.e., 5× expected trade size)
  - rationale: per-trade std ~$255, so -$200 ≈ 0.78σ loss per trade
- Verdict per strategy:
  - A+UP<0, SIDE>0, A>SIDE → "regime_filter 收紧到只 A"
  - A>0, SIDE>0, A≈SIDE → "threshold ok, keep SIDE"
  - A<0, SIDE>0, A<<SIDE → "regime_filter 错, remove/flip"
  - Any UP<0 → "regime_filter 拒 UP 是对的 (baseline)"

Run:
    python3 data/phase3b/bootstrap_regime.py
    python3 data/phase3b/bootstrap_regime.py --n-iter 5000   # higher precision
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
STRATEGIES = [("a", "A"), ("c", "C")]

PROB_RUIN_THRESHOLD = -200.0  # USD per-trade mean threshold for "ruin"


def bootstrap_subset(net_pnl: np.ndarray, n_iter: int, rng: np.random.Generator) -> dict:
    """Bootstrap a 1D array of trade PnLs. Returns summary stats."""
    n = len(net_pnl)
    if n < 5:
        return None

    # Resample indices once → iterate stats
    idx = rng.integers(0, n, size=(n_iter, n))
    samples = net_pnl[idx]  # shape (n_iter, n)

    means = samples.mean(axis=1)
    medians = np.median(samples, axis=1)
    sums = samples.sum(axis=1)
    pos_frac_per_iter = (samples > 0).mean(axis=1)

    return {
        "n": int(n),
        "raw_mean": float(net_pnl.mean()),
        "raw_median": float(np.median(net_pnl)),
        "raw_std": float(net_pnl.std()),
        "raw_pos_frac": float((net_pnl > 0).mean()),
        "raw_sum": float(net_pnl.sum()),
        "mean_ci_low": float(np.percentile(means, 5)),
        "mean_ci_high": float(np.percentile(means, 95)),
        "median_ci_low": float(np.percentile(medians, 5)),
        "median_ci_high": float(np.percentile(medians, 95)),
        "sum_ci_low": float(np.percentile(sums, 5)),
        "sum_ci_high": float(np.percentile(sums, 95)),
        "prob_ruin": float((means < PROB_RUIN_THRESHOLD).mean()),
        "prob_negative_mean": float((means < 0).mean()),
        "pos_frac_mean": float(pos_frac_per_iter.mean()),
        "pos_frac_ci_low": float(np.percentile(pos_frac_per_iter, 5)),
        "pos_frac_ci_high": float(np.percentile(pos_frac_per_iter, 95)),
    }


def analyze_strategy(strategy_key: str, strategy_label: str, n_iter: int, rng: np.random.Generator) -> dict:
    """Run bootstrap for one strategy. Returns nested dict."""
    pq_path = PHASE3B_DIR / f"{strategy_key}_trades_with_regime.parquet"
    df = pd.read_parquet(pq_path)
    print(f"\n=== Strategy {strategy_label} ({strategy_key}) ===")
    print(f"  loaded {len(df)} trades · regime counts: {df['_regime'].value_counts().to_dict()}")

    net_pnl = df["net_pnl"].to_numpy()
    all_stats = bootstrap_subset(net_pnl, n_iter, rng)
    regime_results = {"ALL": all_stats} if all_stats else {}

    for regime in REGIMES:
        subset = df[df["_regime"] == regime]
        if subset.empty:
            continue
        stats = bootstrap_subset(subset["net_pnl"].to_numpy(), n_iter, rng)
        if stats is None:
            continue
        regime_results[regime] = stats
        print(
            f"  {regime:<8} n={stats['n']:>4}  "
            f"mean={stats['raw_mean']:>+8.2f} USD "
            f"[{stats['mean_ci_low']:>+8.2f}, {stats['mean_ci_high']:>+8.2f}]  "
            f"prob_ruin={stats['prob_ruin']:.1%}"
        )

    return regime_results


def verdict(strategy_label: str, regime_results: dict) -> str:
    """Apply decision matrix from memory/2026-07-28.md."""
    lines = [f"## Strategy {strategy_label}"]
    if not regime_results:
        return "\n".join(lines + ["  ❌ no regime data"])

    lines.append("")
    lines.append("| Regime | n | Mean (CI) | prob_ruin | Verdict |")
    lines.append("|---|---|---|---|---|")

    a_mean = regime_results.get("A", {}).get("raw_mean")
    side_mean = regime_results.get("SIDE", {}).get("raw_mean")
    up_mean = regime_results.get("UP", {}).get("raw_mean")
    all_mean = regime_results.get("ALL", {}).get("raw_mean")

    for regime, stats in regime_results.items():
        ci = f"[{stats['mean_ci_low']:+.0f}, {stats['mean_ci_high']:+.0f}]"
        v = ""
        if stats["raw_mean"] < 0:
            v = "❌ negative mean"
        if stats["prob_ruin"] > 0.5:
            v += " · HIGH ruin risk"
        if regime == "UP" and stats["raw_mean"] < 0:
            v = "✅ baseline correct (拒 UP 是对的)"
        lines.append(
            f"| {regime} | {stats['n']} | "
            f"{stats['raw_mean']:+.1f} {ci} | "
            f"{stats['prob_ruin']:.0%} | {v or '—'} |"
        )

    lines.append("")
    lines.append("### Decision")
    if a_mean is None or side_mean is None or up_mean is None:
        lines.append("  ❓ missing regime data, can't decide")
    elif up_mean < 0:
        # regime_filter 拒 UP 是 baseline 正确
        if a_mean > 0 and side_mean > 0:
            if abs(a_mean - side_mean) < 50:  # within ~$50
                lines.append(
                    f"  ✅ **keep regime_filter as-is** (A={a_mean:+.1f}, SIDE={side_mean:+.1f}, "
                    f"A≈SIDE within noise)"
                )
            elif a_mean > side_mean:
                lines.append(
                    f"  ⚠️ **tighten regime_filter to A-only** (A={a_mean:+.1f} > SIDE={side_mean:+.1f}) "
                    f"→ over-restrictive SIDE"
                )
            else:  # side_mean > a_mean
                lines.append(
                    f"  ❌ **regime_filter is WRONG** (SIDE={side_mean:+.1f} > A={a_mean:+.1f}) "
                    f"→ regime classifier inverted; consider flip or remove"
                )
        elif a_mean < 0 and side_mean > 0:
            lines.append(
                f"  ❌ **regime_filter is WRONG** (A={a_mean:+.1f} < 0, SIDE={side_mean:+.1f} > 0) "
                f"→ reject A, allow SIDE"
            )
        else:
            lines.append(
                f"  ⚠️ **A & SIDE both negative** — strategy itself broken, regime_filter moot"
            )
    else:
        lines.append(f"  ❓ UP regime positive ({up_mean:+.1f}) — contradicts baseline assumption")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-iter", type=int, default=1000, help="bootstrap iterations")
    parser.add_argument("--seed", type=int, default=20260728, help="RNG seed")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    print(f"Phase 3B bootstrap · n_iter={args.n_iter} · seed={args.seed}")
    print(f"prob_ruin threshold = mean < {PROB_RUIN_THRESHOLD:.0f} USD per trade")

    all_results = {}
    verdict_md_parts = ["# Phase 3B Bootstrap Report", ""]
    verdict_md_parts.append(f"_n_iter={args.n_iter}, seed={args.seed}, ruin_threshold={PROB_RUIN_THRESHOLD:.0f}_")
    verdict_md_parts.append("")

    for strategy_key, strategy_label in STRATEGIES:
        regime_results = analyze_strategy(strategy_key, strategy_label, args.n_iter, rng)
        all_results[strategy_label] = regime_results
        verdict_md_parts.append(verdict(strategy_label, regime_results))
        verdict_md_parts.append("")

    # Save raw JSON
    json_path = PHASE3B_DIR / "bootstrap_results.json"
    with open(json_path, "w") as f:
        json.dump(
            {"n_iter": args.n_iter, "seed": args.seed, "ruin_threshold": PROB_RUIN_THRESHOLD, "results": all_results},
            f, indent=2,
        )
    print(f"\n✅ JSON: {json_path}")

    # Save markdown report
    md_path = PHASE3B_DIR / "bootstrap_report.md"
    md_path.write_text("\n".join(verdict_md_parts) + "\n", encoding="utf-8")
    print(f"✅ Report: {md_path}")


if __name__ == "__main__":
    main()