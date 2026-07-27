"""Phase 3B data prep: consolidate trades from 7-24 walkforward + tag by regime.

Reuses 7-24 walkforward runs (3-day stale, acceptable for 200d EMA):
- a-btc-wf-3m1m-20260724-194650 (A strategy)
- c-btc-wf-3m1m-20260724-191640 (C strategy)

Each window has 3 cells (slip5/10/15 × fee5) → 54 trades.parquet per strategy.
tag_trades_by_regime dedup by window_id → 18 recommended_strategy calls per strategy.
"""
import json
import sys
from pathlib import Path

import pandas as pd

WORKSPACE = Path("/home/zzzx47/.openclaw/workspace")
sys.path.insert(0, str(WORKSPACE))

from okx.code.regime_filter import tag_trades_by_regime

PROJECT_ROOT = WORKSPACE / "okx"
WF_ROOT = PROJECT_ROOT / "docs" / "agent-context" / "walkforward"
OUT_ROOT = PROJECT_ROOT / "docs" / "agent-context" / "phase3b"
OUT_ROOT.mkdir(parents=True, exist_ok=True)

RUNS = {
    "A": "a-btc-wf-3m1m-20260724-194650",
    "C": "c-btc-wf-3m1m-20260724-191640",
}
CELLS = ["slip5_fee5p0", "slip10_fee5p0", "slip15_fee5p0"]


def collect_trades(run_name: str) -> pd.DataFrame:
    """Collect all trades from 18 windows × 3 cells."""
    run_dir = WF_ROOT / run_name / "windows"
    frames = []
    n_missing = 0
    for w_dir in sorted(run_dir.iterdir()):
        if not w_dir.is_dir():
            continue
        window_id = w_dir.name.split("_")[0]  # w00_2024-10-26_2025-01-24 → w00
        for cell in CELLS:
            trades_path = w_dir / "cells" / cell / "trades.parquet"
            if not trades_path.exists():
                n_missing += 1
                continue
            df = pd.read_parquet(trades_path)
            if df.empty:
                continue
            df["window_id"] = window_id
            df["cell"] = cell
            frames.append(df)
    if n_missing:
        print(f"  ⚠️ {n_missing} missing trades.parquet")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main():
    summary = {}
    for strategy, run_name in RUNS.items():
        print(f"\n=== {strategy} ({run_name}) ===")
        trades = collect_trades(run_name)
        if trades.empty:
            print(f"  ❌ no trades")
            continue
        print(f"  collected {len(trades)} trades | "
              f"{trades['window_id'].nunique()} windows | "
              f"{trades['cell'].nunique()} cells")
        if "exit_ts" not in trades.columns:
            print(f"  ❌ no exit_ts column")
            continue
        tagged = tag_trades_by_regime(trades, bar="1h", symbol="BTC-USDT-SWAP")
        regime_counts = tagged["_regime"].value_counts().to_dict()
        regime_counts = {k: int(v) for k, v in regime_counts.items()}
        print(f"  regime counts: {regime_counts}")
        out_path = OUT_ROOT / f"{strategy.lower()}_trades_with_regime.parquet"
        tagged.to_parquet(out_path, index=False)
        print(f"  ✅ saved: {out_path}")
        summary[strategy] = {
            "n_trades": int(len(trades)),
            "n_windows": int(trades["window_id"].nunique()),
            "n_cells": int(trades["cell"].nunique()),
            "regime_counts": regime_counts,
            "out_path": str(out_path.relative_to(PROJECT_ROOT)),
        }

    summary_path = OUT_ROOT / "phase3b_prep_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n✅ summary: {summary_path}")


if __name__ == "__main__":
    main()
