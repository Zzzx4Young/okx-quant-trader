#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 2 一键实验：A+B+C 联合验证

═══════════════════════════════════════════════════════════════════
目的：告别"回测天堂，实盘地狱"，用机构级精度实测 4 个策略 vs 2 个基准
═══════════════════════════════════════════════════════════════════

对每个标的（BTC / ETH）× 每个时间窗口（默认 20 个月）× 每种策略：
  - A: EMA20_BREAKOUT          （趋势右侧突破）
  - B: BB_RSI_REVERSION        （震荡左侧反转）
  - C: VOLATILITY_BREAKOUT     （波动率盘整后爆发）
  - D: FUNDING_RATE_REVERSAL   （资金费率极端反转）

输出：
  - 每个策略的 Sharpe / Sortino / MaxDD / Calmar / Trades / WinRate
  - 1x 现货持有基准 + 5x 杠杆持有基准（带爆仓模拟）
  - Alpha 判断：策略 vs 基准的 sharpe 差 + return 差

CLI:
  python -m okx.code.backtest.run_phase2_experiment
  python -m okx.code.backtest.run_phase2_experiment --timeframe 5m
  python -m okx.code.backtest.run_phase2_experiment --strategies A B
"""

import argparse
import sys
from typing import Callable, Dict, List, Optional

import pandas as pd
import numpy as np

from .data_loader import load
from .matcher import BacktestEngine
from .benchmark import run_all_benchmarks, BenchmarkResult
from .metrics import compute_all_metrics, format_metrics_table


# ────────────────────────────────────────────────────────────────────
# 4 个策略信号函数（V2.1 strict index：df.iloc[:i] 已包含）
# ────────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    return 100 - (100 / (1 + rs))


def strategy_a_ema_breakout(df, i, indicators, position, funding_df, symbol) -> Optional[str]:
    """
    A · EMA20_BREAKOUT（趋势右侧）
    EMA8 上穿 EMA20 → long，下穿 → short；持反向 → close
    使用缓存指标（indicators），O(1) 每 bar。
    """
    if i < 22:
        return None
    
    ema_fast = indicators["ema_8"]
    ema_slow = indicators["ema_20"]
    
    if pd.isna(ema_fast.iloc[i-1]) or pd.isna(ema_slow.iloc[i-1]):
        return None
    
    curr_fast = ema_fast.iloc[i-1]
    curr_slow = ema_slow.iloc[i-1]
    prev_fast = ema_fast.iloc[i-2]
    prev_slow = ema_slow.iloc[i-2]
    
    long_sig = prev_fast <= prev_slow and curr_fast > curr_slow
    short_sig = prev_fast >= prev_slow and curr_fast < curr_slow
    
    if long_sig:
        return "long"
    if short_sig:
        return "short"
    if position is not None:
        if position.direction == "long" and short_sig:
            return "close"
        if position.direction == "short" and long_sig:
            return "close"
    return None


def strategy_b_bb_rsi_reversion(df, i, indicators, position, funding_df, symbol) -> Optional[str]:
    """
    B · BB_RSI_REVERSION（震荡左侧反转）
    close < 下轨 + RSI < 45 → long；close > 上轨 + RSI > 55 → short
    使用缓存指标，O(1) 每 bar。
    """
    if i < 22:
        return None
    
    rsi = indicators["rsi_14"]
    upper = indicators["bb_upper"]
    lower = indicators["bb_lower"]
    closes = df["close"]
    
    if pd.isna(rsi.iloc[i-1]) or pd.isna(lower.iloc[i-1]):
        return None
    
    curr_close = closes.iloc[i-1]
    curr_rsi = rsi.iloc[i-1]
    
    if curr_close <= lower.iloc[i-1] and curr_rsi < 45:
        return "long"
    if curr_close >= upper.iloc[i-1] and curr_rsi > 55:
        return "short"
    return None


def strategy_c_volatility_breakout(df, i, indicators, position, funding_df, symbol) -> Optional[str]:
    """
    C · VOLATILITY_BREAKOUT（波动率盘整后爆发）
    BBW 收缩至 < 0.04 + close 突破近 5 根 high/low → 入场
    使用缓存指标，O(1) 每 bar。
    """
    if i < 25:
        return None
    
    bbw = indicators["bbw"]
    high_5 = indicators["high_5"]
    low_5 = indicators["low_5"]
    closes = df["close"]
    
    if pd.isna(bbw.iloc[i-1]):
        return None
    
    bbw_squeeze = bbw.iloc[i-1] < 0.04
    if not bbw_squeeze:
        return None
    
    # 注意：high_5.iloc[i-1] 包含当前 bar。设计：突破“前 5 根”不含当前
    # 这里用 high_5.iloc[i-2]（上一根的近 5 根最高）作为参考点
    prev_high_5 = high_5.iloc[i-2] if i >= 2 else None
    prev_low_5 = low_5.iloc[i-2] if i >= 2 else None
    if prev_high_5 is None or pd.isna(prev_high_5):
        return None
    
    curr_close = closes.iloc[i-1]
    
    if curr_close > prev_high_5:
        return "long"
    if curr_close < prev_low_5:
        return "short"
    return None


def strategy_d_funding_reversal(df, i, indicators, position, funding_df, symbol) -> Optional[str]:
    """
    D · FUNDING_RATE_REVERSAL（资金费率极端反转）
    fundingRate > +0.05% (8h) → 情绪过度多头 → 做空
    fundingRate < -0.05% (8h) → 情绪过度空头 → 做多
    """
    if funding_df is None or len(funding_df) < 1:
        return None
    
    # 用与当前 bar 时间戳 <= t_curr 的最后一个 funding（避免未来函数）
    t_curr_ms = int(df.iloc[i-1]["timestamp"])
    valid_funding = funding_df[funding_df["fundingTime"] <= t_curr_ms]
    if len(valid_funding) == 0:
        return None
    
    last_rate = valid_funding.iloc[-1].get("fundingRate", 0.0)
    if pd.isna(last_rate):
        return None
    
    THRESHOLD = 0.0002  # 0.02%（修 Bug 2：原 0.05% 在 20 月数据上永不触发）
    
    if last_rate > THRESHOLD:
        return "short"
    if last_rate < -THRESHOLD:
        return "long"
    return None


# 策略注册表
STRATEGIES: Dict[str, Callable] = {
    "A_EMA20_BREAKOUT": strategy_a_ema_breakout,
    "B_BB_RSI_REVERSION": strategy_b_bb_rsi_reversion,
    "C_VOLATILITY_BREAKOUT": strategy_c_volatility_breakout,
    "D_FUNDING_RATE_REVERSAL": strategy_d_funding_reversal,
}


# ────────────────────────────────────────────────────────────────────
# 单标的 + 单策略实验
# ────────────────────────────────────────────────────────────────────

def run_single_experiment(
    inst_id: str,
    timeframe: str = "1h",
    initial_capital: float = 10000.0,
    leverage: int = 5,
    slippage_bps: int = 5,
    strategies: Optional[List[str]] = None,
    leverage_levels: List[float] = (1.0, 5.0),
) -> Dict[str, any]:
    """对单标的跑 4 策略 + 基准，返回完整结果"""
    
    data = load(inst_id, timeframe)
    print(f"\n{'='*70}")
    print(f"实验：{inst_id} ({timeframe}) | 初始 ${initial_capital:,.0f} | 杠杆 {leverage}x | 滑点 {slippage_bps}bps")
    print(f"  数据：{data.bar_count} K 线 + {len(data.funding)} funding events")
    print(f"  窗口：{data.start_ts} → {data.end_ts}")
    print(f"{'='*70}")
    
    strategies_to_run = strategies or list(STRATEGIES.keys())
    
    strategy_results = {}
    for strat_name in strategies_to_run:
        if strat_name not in STRATEGIES:
            print(f"⚠️ 未知策略：{strat_name}，跳过")
            continue
        
        sig_provider = STRATEGIES[strat_name]
        engine = BacktestEngine(
            data,
            initial_capital=initial_capital,
            leverage=leverage,
            slippage_bps=slippage_bps,
            signal_provider=sig_provider,
        )
        result = engine.run()
        m = result.metrics()
        strategy_results[strat_name] = (result, m)
        
        # 单条打印
        print(f"\n📊 策略 [{strat_name}]")
        print(format_metrics_table(m, label=strat_name))
        print(f"  tranche 总命中: {result.total_tranche_fills}")
        print(f"  滑点成本: ${result.slippage_cost_total:.2f}")
        print(f"  funding 净支付: ${result.funding_paid_total:.2f}")
    
    # 基准
    benchmarks = run_all_benchmarks(data, initial_capital=initial_capital, leverage_levels=leverage_levels)
    
    print(f"\n📈 基准对比")
    print(f"  {'Name':<15} {'Return':>10} {'Liquidated':>12} {'Final Equity':>15}")
    print(f"  {'-'*56}")
    for b in benchmarks:
        liq = f"@{b.liquidation_idx}" if b.liquidated else "No"
        print(f"  {b.name:<15} {b.total_return_pct:>+9.2f}% {liq:>12} ${b.final_equity:>13,.2f}")
    
    # Alpha 判断：策略 sharpe - 最佳基准 sharpe
    benchmark_metrics = {}
    for b in benchmarks:
        benchmark_metrics[b.name] = compute_all_metrics(
            equity_curve=b.equity_curve,
            initial_capital=b.initial_capital,
        )
    
    return {
        "inst_id": inst_id,
        "timeframe": timeframe,
        "strategies": strategy_results,
        "benchmarks": {b.name: b for b in benchmarks},
        "benchmark_metrics": benchmark_metrics,
    }


# ────────────────────────────────────────────────────────────────────
# 一键实验主入口
# ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 2 一键实验：A+B+C 联合验证")
    parser.add_argument("--inst-ids", nargs="+", default=["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--leverage", type=int, default=5)
    parser.add_argument("--slippage-bps", type=int, default=5)
    parser.add_argument("--strategies", nargs="+", default=None,
                        help="子集指定，如 --strategies A B D")
    parser.add_argument("--leverage-levels", nargs="+", type=float, default=[1.0, 5.0])
    args = parser.parse_args()
    
    # 缩写 → 全名映射
    if args.strategies:
        expanded = []
        for s in args.strategies:
            if "-" in s:  # 已是全名
                expanded.append(s)
            else:  # 单字母
                key = f"{s}_" + {
                    "A": "EMA20_BREAKOUT",
                    "B": "BB_RSI_REVERSION",
                    "C": "VOLATILITY_BREAKOUT",
                    "D": "FUNDING_RATE_REVERSAL",
                }.get(s, s)
                expanded.append(key)
        args.strategies = expanded
    
    print(f"\n🚀 Phase 2 一键实验启动")
    print(f"   标的: {args.inst_ids}")
    print(f"   周期: {args.timeframe}")
    print(f"   杠杆: {args.leverage}x | 滑点: {args.slippage_bps}bps")
    print(f"   策略: {args.strategies or list(STRATEGIES.keys())}")
    print(f"   基准: 1x 现货 + {'/'.join(str(L)+'x' for L in args.leverage_levels)} 杠杆持有")
    
    all_results = []
    for inst_id in args.inst_ids:
        result = run_single_experiment(
            inst_id=inst_id,
            timeframe=args.timeframe,
            initial_capital=args.capital,
            leverage=args.leverage,
            slippage_bps=args.slippage_bps,
            strategies=args.strategies,
            leverage_levels=args.leverage_levels,
        )
        all_results.append(result)
    
    # ── 跨标的综合对比表 ──
    print(f"\n\n{'='*90}")
    print(f"🏁 综合对比矩阵（所有标的 × 所有策略 + 基准）")
    print(f"{'='*90}\n")
    
    header = f"  {'Strategy':<24}"
    for inst in [r["inst_id"] for r in all_results]:
        header += f" {inst[:8]+'_ret':>11} {inst[:8]+'_shp':>9}"
    header += f" {'胜率%':>6}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    
    # 行：每策略 × 多标的
    strategies_keys = list(STRATEGIES.keys())
    for strat in (args.strategies or strategies_keys):
        row = f"  {strat:<24}"
        wins = 0
        total = 0
        for r in all_results:
            if strat in r["strategies"]:
                _, m = r["strategies"][strat]
                row += f" {m['total_return_pct']:>+10.2f}% {m['sharpe']:>+8.3f}"
                if m['total_return_pct'] > 0:
                    wins += 1
                total += 1
            else:
                row += f" {'N/A':>11} {'N/A':>9}"
        win_pct = (wins / total * 100) if total > 0 else 0
        row += f" {win_pct:>5.0f}%"
        print(row)
    
    # 基准行
    print("  " + "-" * (len(header) - 2))
    for bench_name in ["1x_spot", "5x_leverage"]:
        row = f"  [BENCH] {bench_name:<17}"
        for r in all_results:
            if bench_name in r["benchmark_metrics"]:
                m = r["benchmark_metrics"][bench_name]
                row += f" {m['total_return_pct']:>+10.2f}% {m['sharpe']:>+8.3f}"
            else:
                row += f" {'N/A':>11} {'N/A':>9}"
        print(row + "    --")
    
    print(f"\n✅ 实验完成。")
    return all_results


if __name__ == "__main__":
    main()