"""
Aggregate 1h BTC klines → 4h and 1d
Saves to data/market/BTC-USDT-SWAP/{4h,1d}.parquet

This makes the same data available for higher-timeframe backtests without
requiring network access to OKX API.

Note: Aggregating 1h → higher is the standard "bar construction" approach.
We're trading some precision (intra-bar wicks hidden) for cleaner signal.
This is what real traders do.
"""
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path("/home/zzzx47/.openclaw/workspace/okx")
SRC = ROOT / "data" / "market" / "BTC-USDT-SWAP" / "1h.parquet"


def aggregate(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Aggregate to higher bar. freq e.g. '4h', '1d'."""
    df = df.copy()
    df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("dt")

    agg = df.resample(freq).agg({
        "timestamp": "first",  # bar open time
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "volume_currency": "sum",
        "volume_quote": "sum",
        "confirm": "last",
    }).dropna(subset=["open"])

    # Reset and clean
    agg = agg.reset_index(drop=True)
    # Round to standard columns
    return agg[["timestamp", "open", "high", "low", "close", "volume",
                "volume_currency", "volume_quote", "confirm"]]


def main():
    df = pd.read_parquet(SRC)
    print(f"1h source: {len(df)} bars, range {pd.to_datetime(df['timestamp'].min(), unit='ms')} → {pd.to_datetime(df['timestamp'].max(), unit='ms')}")

    # Aggregate
    for freq, fname in [("4h", "4h.parquet"), ("1d", "1d.parquet")]:
        agg = aggregate(df, freq)
        out = ROOT / "data" / "market" / "BTC-USDT-SWAP" / fname
        agg.to_parquet(out, index=False)
        print(f"  {freq}: {len(agg)} bars → {out}")
        print(f"    range: {pd.to_datetime(agg['timestamp'].min(), unit='ms')} → {pd.to_datetime(agg['timestamp'].max(), unit='ms')}")
        # Quick stats
        rng = (agg["high"] - agg["low"]) / agg["close"] * 10000
        print(f"    bar range median: {rng.median():.1f} bps, mean: {rng.mean():.1f} bps, p95: {rng.quantile(0.95):.1f} bps")


if __name__ == "__main__":
    main()