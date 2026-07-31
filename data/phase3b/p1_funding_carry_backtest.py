"""
P1-2: Funding Rate Carry Backtest (per Pre-Registration Phase C)

Strategy (FROZEN per PREREGISTRATION.md Phase C):
- For each 8h funding period:
  if funding > +0.5 bps (X): SHORT perp to collect funding
  if funding < -0.5 bps (Y): LONG perp to collect funding
  else: NEUTRAL
- Hold K=1 funding period (8h)
- Position: 1x notional
- Cost: 10 bps round-trip slip+fee (5+5)

PnL per trade:
  carry_pnl = funding_rate * notional  (received if collecting)
  price_pnl = direction * (exit_price - entry_price) / entry_price * notional
  cost = slip + fee = 10 bps = 0.001 * notional

Data:
- funding: data/funding/BTC-USDT-SWAP_funding.parquet (292 records, 2026-04-07 → 2026-07-13)
- klines: data/market/BTC-USDT-SWAP/1h.parquet (for entry/exit prices)

Output:
- Per-trade PnL
- Aggregate Sharpe, total return, win rate
- Statistical significance test
"""
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats

ROOT = Path("/home/zzzx47/.openclaw/workspace/okx")


def get_price_at_or_before(klines: pd.DataFrame, ts_ms: int) -> float | None:
    """Find latest close at or before ts_ms."""
    subset = klines[klines["timestamp"] <= ts_ms]
    if subset.empty:
        return None
    return float(subset.iloc[-1]["close"])


def main():
    funding = pd.read_parquet(ROOT / "data/funding/BTC-USDT-SWAP_funding.parquet")
    funding["dt"] = pd.to_datetime(funding["fundingTime"], unit="ms", utc=True)
    funding = funding.sort_values("fundingTime").reset_index(drop=True)

    klines = pd.read_parquet(ROOT / "data/market/BTC-USDT-SWAP/1h.parquet")
    # Ensure sorted
    klines = klines.sort_values("timestamp").reset_index(drop=True)

    # Pre-registered parameters
    X = 0.00005  # +0.5 bps
    Y = -0.00005  # -0.5 bps
    K = 1  # hold 1 funding period
    NOTIONAL = 1000.0  # $1000 notional for ease
    COST_RT = 0.001  # 10 bps round-trip (slip 5 + fee 5)

    trades = []
    for i in range(len(funding) - K):
        row = funding.iloc[i]
        fr = row["fundingRate"]
        entry_ts = int(row["fundingTime"])
        exit_row = funding.iloc[i + K]
        exit_ts = int(exit_row["fundingTime"])

        # Determine direction
        if fr > X:
            direction = "short"
        elif fr < Y:
            direction = "long"
        else:
            continue  # neutral

        # Entry/exit prices (close just before funding_time)
        entry_price = get_price_at_or_before(klines, entry_ts)
        exit_price = get_price_at_or_before(klines, exit_ts)
        if entry_price is None or exit_price is None:
            continue

        # Funding collected across K periods
        # If short: we collect funding when it's positive, pay when negative
        # If long: we collect funding when it's negative, pay when positive
        # Net funding received = -direction * funding_rate (sign convention: short=1, long=-1)
        # Actually: short receives funding when funding_rate > 0
        #         long pays funding when funding_rate > 0
        # So funding received = -direction * funding_rate * NOTIONAL
        # direction: short=+1, long=-1 (so short with positive rate gets +funding)
        dir_sign = 1 if direction == "short" else -1
        funding_collected = -dir_sign * fr * NOTIONAL

        # Price PnL
        if direction == "short":
            price_pnl = (entry_price - exit_price) / entry_price * NOTIONAL
        else:
            price_pnl = (exit_price - entry_price) / entry_price * NOTIONAL

        # Cost
        cost = COST_RT * NOTIONAL

        net_pnl = funding_collected + price_pnl - cost
        trades.append({
            "entry_ts": entry_ts,
            "exit_ts": exit_ts,
            "funding_rate_at_entry": fr,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "funding_collected": funding_collected,
            "price_pnl": price_pnl,
            "cost": cost,
            "net_pnl": net_pnl,
        })

    df = pd.DataFrame(trades)
    print(f"=== Pre-Registered Carry Strategy Results ===")
    print(f"Period: 2026-04-07 to 2026-07-13 (97 days)")
    print(f"Total trades: {len(df)}")
    if len(df) == 0:
        print("No trades generated — strategy too restrictive")
        return

    print(f"Direction split: {df['direction'].value_counts().to_dict()}")
    print()
    print(f"=== Per-trade PnL ===")
    print(f"  mean:      ${df['net_pnl'].mean():.4f}")
    print(f"  median:    ${df['net_pnl'].median():.4f}")
    print(f"  std:       ${df['net_pnl'].std():.4f}")
    print(f"  total:     ${df['net_pnl'].sum():.4f}")
    print(f"  win rate:  {(df['net_pnl'] > 0).mean()*100:.1f}%")
    print()

    # Decompose
    print(f"=== PnL Decomposition ===")
    print(f"  Funding collected total: ${df['funding_collected'].sum():.4f}")
    print(f"  Price PnL total:         ${df['price_pnl'].sum():.4f}")
    print(f"  Cost total:              ${df['cost'].sum():.4f}")
    print()

    # Statistical test
    t, p_two = stats.ttest_1samp(df["net_pnl"], 0)
    p_one = p_two / 2 if t > 0 else 1 - p_two / 2
    print(f"=== Statistical Significance ===")
    print(f"  t-statistic: {t:.3f}")
    print(f"  p (one-sided, mean > 0): {p_one:.4f}")
    print(f"  Significant at α=0.05? {p_one < 0.05}")
    print(f"  Bonferroni (6 tests) α=0.0083: {p_one < 0.05/6}")
    print()

    # Sharpe annualized (K=1 period = 8h = 1/3 day; 3 periods/day, 365 days/year)
    periods_per_year = 3 * 365
    mean_per_period = df["net_pnl"].mean()
    std_per_period = df["net_pnl"].std()
    if std_per_period > 0:
        sharpe = mean_per_period / std_per_period * np.sqrt(periods_per_year)
        print(f"  Sharpe annualized: {sharpe:.3f}")
        print(f"  Sharpe > 0.30? {sharpe > 0.30}")
    print()

    # Profit factor
    gross_profit = df.loc[df["net_pnl"] > 0, "net_pnl"].sum()
    gross_loss = -df.loc[df["net_pnl"] < 0, "net_pnl"].sum()
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    print(f"  Gross profit: ${gross_profit:.4f}")
    print(f"  Gross loss:   ${gross_loss:.4f}")
    print(f"  Profit factor: {profit_factor:.3f}")
    print(f"  Profit factor ≥ 1.20? {profit_factor >= 1.20}")
    print()

    # Max drawdown
    cum = df["net_pnl"].cumsum()
    running_max = cum.cummax()
    drawdown = cum - running_max
    max_dd = drawdown.min()
    print(f"  Max drawdown: ${max_dd:.4f}")
    print(f"  Max DD ≤ 15% of notional? {abs(max_dd) <= 0.15 * NOTIONAL}")

    # Save
    out_path = ROOT / "data/phase3b/p1_carry_trades.parquet"
    df.to_parquet(out_path, index=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()