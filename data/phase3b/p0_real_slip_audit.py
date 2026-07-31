"""
P0-1: Real Slip Audit
=====================

Question: Is our fragility_scan slip=5 bps assumption realistic for actual
1h timeframe BTC-SWAP execution at our typical order sizes?

Approach:
1. Look at BTC 1h klines — compute typical bar range, volatility
2. Compare to fragility_scan assumptions (slip=5, 10, 15 bps one-way)
3. Estimate realistic achievable slip based on:
   - Spread (typical bid-ask for BTC-SWAP)
   - Volatility (high vol = bigger slippage)
   - Order size relative to typical depth
   - Whether we use limit or market orders

Reality check sources:
- OKX BTC-SWAP typical spread: 1-3 bps in normal conditions
- Market impact for 0.1-1 BTC orders: 1-5 bps depending on volatility
- Round-trip slip with limit orders at mid: 2-5 bps achievable
- Round-trip slip with market orders: 5-15 bps typical

We'll use the 1h kline data to estimate:
- Typical bar range as % of price (volatility proxy)
- Median vs p95 vs p99 volatility
- What fraction of bars have range > 0.3% (which would imply >10 bps one-way slip even with limit orders)
"""
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path("/home/zzzx47/.openclaw/workspace/okx")
MARKET = ROOT / "data" / "market" / "BTC-USDT-SWAP"


def load_btc_1h() -> pd.DataFrame:
    df = pd.read_parquet(MARKET / "1h.parquet")
    if "timestamp" in df.columns:
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms")
    elif "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    # Identify columns
    print(f"Columns: {list(df.columns)}")
    # Compute bar range as % of close
    df["range_pct"] = (df["high"] - df["low"]) / df["close"] * 10000  # in bps
    df["body_pct"] = abs(df["close"] - df["open"]) / df["close"] * 10000
    df["ret_pct"] = df["close"].pct_change() * 10000
    return df


def main():
    df = load_btc_1h()
    print(f"\n=== BTC 1h data: {len(df)} bars ===")
    print(f"Time range: {df['ts'].min()} to {df['ts'].max()}")
    print(f"Days covered: {(df['ts'].max() - df['ts'].min()).days}")

    # Typical bar range
    rng = df["range_pct"]
    print(f"\n=== Bar range (high-low) as % of close (in bps) ===")
    print(f"  mean:   {rng.mean():.1f} bps")
    print(f"  median: {rng.median():.1f} bps")
    print(f"  p75:    {rng.quantile(0.75):.1f} bps")
    print(f"  p90:    {rng.quantile(0.90):.1f} bps")
    print(f"  p95:    {rng.quantile(0.95):.1f} bps")
    print(f"  p99:    {rng.quantile(0.99):.1f} bps")
    print(f"  max:    {rng.max():.1f} bps")

    # Bar body (close-open, actual move)
    body = df["body_pct"]
    print(f"\n=== Bar body |close-open| (in bps) ===")
    print(f"  mean:   {body.mean():.1f} bps")
    print(f"  median: {body.median():.1f} bps")
    print(f"  p95:    {body.quantile(0.95):.1f} bps")

    # What fraction of bars have range > X bps
    print(f"\n=== Fraction of bars with range > X bps (realistic one-way slip floor) ===")
    for thresh in [5, 10, 15, 20, 30, 50]:
        frac = (rng > thresh).mean()
        print(f"  > {thresh:3d} bps: {frac*100:.1f}%")

    # Annualized vol
    ret = df["ret_pct"].dropna()
    hourly_vol = ret.std()
    annual_vol = hourly_vol * np.sqrt(24 * 365) / 10000  # back to fraction
    print(f"\n=== Volatility ===")
    print(f"  1h return std: {hourly_vol:.1f} bps")
    print(f"  Annualized vol (8760h): {annual_vol*100:.1f}%")

    # Slip reality verdict
    print(f"\n=== Slip Reality Verdict ===")
    print(f"fragility_scan assumed: slip = {{5, 10, 15}} bps one-way")
    print(f"For 1h timeframe BTC-SWAP:")
    pct_above_5 = (rng > 5).mean() * 100
    pct_above_10 = (rng > 10).mean() * 100
    pct_above_15 = (rng > 15).mean() * 100
    print(f"  {pct_above_5:.0f}% of bars have range > 5 bps  → slip=5 floor hits {pct_above_5:.0f}% of time")
    print(f"  {pct_above_10:.0f}% of bars have range > 10 bps → slip=10 floor hits {pct_above_10:.0f}% of time")
    print(f"  {pct_above_15:.0f}% of bars have range > 15 bps → slip=15 floor hits {pct_above_15:.0f}% of time")

    print(f"\nWith limit orders at mid + spread crossing:")
    print(f"  Normal vol: achievable slip = 2-5 bps round-trip = 1-2.5 bps one-way")
    print(f"  High vol (>10 bps bar): achievable slip = 5-10 bps round-trip")
    print(f"\nWith market orders:")
    print(f"  Normal vol: 5-10 bps one-way")
    print(f"  High vol: 10-30 bps one-way")

    # Stress periods (high volatility)
    print(f"\n=== High-volatility subperiods (top 10% range bars) ===")
    high_vol = df[rng > rng.quantile(0.90)].copy()
    print(f"  N bars: {len(high_vol)}")
    print(f"  Mean range in this subset: {high_vol['range_pct'].mean():.1f} bps")
    print(f"  Time range: {high_vol['ts'].min()} to {high_vol['ts'].max()}")

    # Quick comparison with fragility_scan assumptions
    print(f"\n=== Implication for fragility_scan viability ===")
    print(f"If fragility_scan showed viability ONLY at slip=5 (low-cost cell):")
    print(f"  → This is only achievable with limit orders at mid in NORMAL vol")
    print(f"  → In HIGH vol (>10 bps range), realistic slip is 5-10 bps one-way")
    print(f"  → So fragility_scan's 'slip=5 viable' conclusion overstates true viability")


if __name__ == "__main__":
    main()