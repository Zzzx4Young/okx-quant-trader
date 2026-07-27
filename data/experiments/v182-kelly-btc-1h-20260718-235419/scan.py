#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v1.8.2 Kelly Criterion per-trade backtest simulation (Constitution §3.2).

模拟 live runner._kelly_sizing_decision 在 backtest 路径中的行为:
- 每笔 trade 触发前, 用 closed_positions[0..i-1] 计算 strategy stats
- 调 kelly_sizing_decision, 决定是否接受 trade i
- 模拟 fallback (n<min) → accept; reject_negative_ev → skip

对每个策略 (A/B/C) 跑 BTC 1h 单 cell, 输出 baseline vs Kelly-on 对比.

预期:
- B strategy: WR=27.8% b=1.5 → f_full=-0.20 → Kelly 拒绝后段 trades (前 30 fallback)
- A/C strategy: 正 EV → Kelly 启用 (或 fallback), trades 保留

用法:
    python3 -m okx.scripts.kelly_backtest_demo

退出码: 0 正常, 1 错误
"""

import sys
from pathlib import Path
from datetime import datetime

# scripts/kelly_backtest_demo.py → okx/scripts/ → okx/  (code package 在这里)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.risk import RiskCalculator
from code.config import Config
from code.backtest.data_loader import load
from code.backtest.matcher import BacktestEngine
from code.backtest.run_phase2_experiment import STRATEGIES
from code.portfolio import StrategyStats


# ──────────── Kelly simulation core ────────────

def simulate_kelly_per_trade(
    baseline_trades,
    risk_calc: RiskCalculator,
    strategy_name: str,
    min_trades: int = 30,
    equity: float = 10000.0,
    leverage: int = 3,
):
    """
    模拟 live runner._kelly_sizing_decision 的 per-trade 决策.

    对每笔 baseline trade:
      1. 用 closed_positions[0..i-1] 聚合 stats
      2. 调 risk_calc.kelly_sizing_decision(stats, ...)
      3. fallback (n<min) → accept; reject_negative_ev → skip; 其他 → accept
      4. 无论 accept/reject, 都把 trade 加到 closed_positions (按 baseline 视角 trade 发生)

    返回:
      accepted_indices: List[int] - Kelly 允许开仓的 trade index
      rejected_indices: List[int] - Kelly 拒绝的 trade index
      rejection_stats_reasons: List[Dict] - 拒绝时的 stats 摘要
    """
    closed = []
    accepted = []
    rejected = []
    rejection_log = []

    for i, trade in enumerate(baseline_trades):
        # ── 1. 计算 stats ──
        if len(closed) == 0:
            stats = None
        else:
            wins = [c["realized_pnl"] for c in closed if c["realized_pnl"] > 0]
            losses = [abs(c["realized_pnl"]) for c in closed if c["realized_pnl"] < 0]
            stats = StrategyStats(
                strategy=strategy_name,
                n=len(closed),
                win_rate=len(wins) / len(closed),
                avg_win_usd=sum(wins) / len(wins) if wins else 0.0,
                avg_loss_usd=sum(losses) / len(losses) if losses else 0.0,
            )

        # ── 2. Kelly 决策 ──
        if stats is None or stats.n < min_trades:
            # data insufficient → fallback (默认 1% 本金)
            accepted.append(i)
        else:
            status, pct, reason = risk_calc.kelly_sizing_decision(
                strategy_stats=stats,
                equity=equity,
                atr_ratio=1.0,  # baseline 视角 ATR ratio 假设中性
                leverage=leverage,
                sl_distance_pct=0.005,
                min_trades_for_kelly=min_trades,
            )
            if status == "reject_negative_ev":
                rejected.append(i)
                rejection_log.append({
                    "trade_index": i,
                    "stats_n": stats.n,
                    "win_rate": round(stats.win_rate, 4),
                    "avg_win": round(stats.avg_win_usd, 2),
                    "avg_loss": round(stats.avg_loss_usd, 2),
                    "reason_short": reason.split("|")[0] if "|" in reason else reason,
                })
            else:
                accepted.append(i)

        # ── 3. 更新 closed (按 baseline 视角, trade i 发生) ──
        closed.append({"realized_pnl": trade.net_pnl})

    return accepted, rejected, rejection_log


# ──────────── Baseline backtest ────────────

def run_baseline(
    strat_full: str,
    inst_id: str = "BTC-USDT-SWAP",
    bar: str = "1h",
    slippage_bps: int = 5,
    fee_bps: float = 5.5,
    leverage: int = 3,
    capital: float = 10000.0,
):
    """跑 baseline backtest, 返回 BacktestResult."""
    data = load(inst_id, bar)
    engine = BacktestEngine(
        data,
        initial_capital=capital,
        leverage=leverage,
        slippage_bps=slippage_bps,
        taker_fee=fee_bps / 10000.0,
        signal_provider=STRATEGIES[strat_full],
    )
    return engine.run()


def compute_trade_metrics(trades):
    """从 trade list 计算关键指标."""
    if not trades:
        return {
            "n_trades": 0,
            "win_rate_pct": 0.0,
            "avg_win_usd": 0.0,
            "avg_loss_usd": 0.0,
            "total_net_pnl_usd": 0.0,
            "ret_pct": 0.0,
        }
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl < 0]
    total_pnl = sum(t.net_pnl for t in trades)
    return {
        "n_trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
        "avg_win_usd": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_usd": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "total_net_pnl_usd": round(total_pnl, 2),
        "ret_pct": round(total_pnl / 10000.0 * 100, 3),
    }


# ──────────── Main ────────────

def main():
    print("=" * 80)
    print("v1.8.2 Kelly Criterion per-trade backtest simulation")
    print("Constitution §3.2 — slip=5 bps, fee=5.5 bps, leverage=3x, BTC-USDT-SWAP 1h")
    print("=" * 80)
    print()

    config = Config()
    risk = RiskCalculator(config)

    target_strategies = [
        "A_EMA20_BREAKOUT",
        "B_BB_RSI_REVERSION",
        "C_VOLATILITY_BREAKOUT",
    ]

    results = []
    rejection_logs_by_strat = {}

    for strat in target_strategies:
        print(f"▶ {strat} ...")
        result = run_baseline(strat)
        baseline_trades = result.trades
        accepted, rejected, rej_log = simulate_kelly_per_trade(
            baseline_trades, risk, strategy_name=strat,
        )
        kelly_trades = [baseline_trades[i] for i in accepted]

        baseline_m = compute_trade_metrics(baseline_trades)
        kelly_m = compute_trade_metrics(kelly_trades)

        results.append({
            "strategy": strat,
            "baseline": baseline_m,
            "kelly": kelly_m,
            "n_rejected": len(rejected),
            "n_accepted": len(accepted),
        })
        rejection_logs_by_strat[strat] = rej_log
        print(f"  baseline: trades={baseline_m['n_trades']} ret={baseline_m['ret_pct']:+.3f}% "
              f"WR={baseline_m['win_rate_pct']:.1f}%")
        print(f"  kelly-on: trades={len(accepted)} ret={kelly_m['ret_pct']:+.3f}% "
              f"rejected={len(rejected)}")

    print()
    print("=" * 80)
    print("SUMMARY (Kelly-on vs baseline)")
    print("=" * 80)
    print()
    print(f"{'Strategy':<24} {'Trades_b':>10} {'Trades_k':>10} {'Rej':>5} "
          f"{'Ret_b%':>10} {'Ret_k%':>10} {'Δ_pp':>8} {'WR_b':>6} {'WR_k':>6}")
    print("-" * 100)
    for r in results:
        b = r["baseline"]
        k = r["kelly"]
        delta = round(k["ret_pct"] - b["ret_pct"], 3)
        print(f"{r['strategy']:<24} {b['n_trades']:>10} {k['n_trades']:>10} {r['n_rejected']:>5} "
              f"{b['ret_pct']:>+10.3f} {k['ret_pct']:>+10.3f} {delta:>+8.3f} "
              f"{b['win_rate_pct']:>6.1f} {k['win_rate_pct']:>6.1f}")

    # 输出到 result.txt
    print()
    print("=" * 80)
    print("REJECTION DETAIL (前 3 笔 reject 的 stats 摘要)")
    print("=" * 80)
    for strat in target_strategies:
        rej_log = rejection_logs_by_strat[strat]
        if rej_log:
            print(f"\n{strat}:")
            for entry in rej_log[:3]:
                print(f"  trade #{entry['trade_index']:>3}: n={entry['stats_n']:>3} "
                      f"WR={entry['win_rate']:.2%} avg_win=${entry['avg_win']:>+8.2f} "
                      f"avg_loss=${entry['avg_loss']:>+8.2f} reason={entry['reason_short']}")
        else:
            print(f"\n{strat}: (no rejections)")

    # 写 result.txt 到 stdout (供实验归档脚本捕获)
    return results


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
