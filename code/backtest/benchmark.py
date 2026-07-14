#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测基准对比（Phase 2）

实现两个 passive 基准策略，用于评估策略是否真有 alpha：
- 1x 现货持有基准（Buy-and-Hold）
- Lx 杠杆持有基准（带爆仓模拟）

两者均在第一个 bar close 建仓，持有至最后一条 bar close。
杠杆版严格模拟：当账户权益 ≤ 0 时判爆仓，剩余时间权益归零。
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional

import numpy as np
import pandas as pd

from .data_loader import BacktestData


@dataclass
class BenchmarkResult:
    """基准回测结果"""
    name: str                          # "1x_spot" / "5x_leverage"
    initial_capital: float
    final_equity: float
    total_return_pct: float
    equity_curve: List[Tuple[int, float]] = field(default_factory=list)
    liquidated: bool = False           # 是否爆仓
    liquidation_idx: Optional[int] = None
    liquidation_ts: Optional[int] = None
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "initial_capital": self.initial_capital,
            "final_equity": self.final_equity,
            "total_return_pct": self.total_return_pct,
            "liquidated": self.liquidated,
            "liquidation_idx": self.liquidation_idx,
        }


def run_buy_and_hold(
    data: BacktestData,
    initial_capital: float = 10000.0,
) -> BenchmarkResult:
    """
    1x 现货持有基准
    
    策略：
    - 第一个 bar 的 close 价全仓买入
    - 持有到最后 bar 的 close 价
    - 不做调仓、不扣费（理想化对照）
    """
    klines = data.klines
    if klines is None or len(klines) < 2:
        return BenchmarkResult(
            name="1x_spot",
            initial_capital=initial_capital,
            final_equity=initial_capital,
            total_return_pct=0.0,
        )
    
    entry_price = float(klines.iloc[0]["close"])
    entry_ts = int(klines.iloc[0]["timestamp"])
    
    # 单位数 = initial_capital / entry_price（按 1 单位 = 1 标的计）
    units = initial_capital / entry_price
    
    equity_curve: List[Tuple[int, float]] = []
    for _, row in klines.iterrows():
        ts = int(row["timestamp"])
        px = float(row["close"])
        equity = units * px
        equity_curve.append((ts, equity))
    
    final_equity = equity_curve[-1][1]
    total_return = (final_equity - initial_capital) / initial_capital * 100
    
    return BenchmarkResult(
        name="1x_spot",
        initial_capital=initial_capital,
        final_equity=final_equity,
        total_return_pct=total_return,
        equity_curve=equity_curve,
    )


def run_leveraged_hold(
    data: BacktestData,
    initial_capital: float = 10000.0,
    leverage: float = 5.0,
) -> BenchmarkResult:
    """
    Lx 杠杆持有基准（带爆仓模拟）
    
    策略：
    - 第一个 bar 的 close 价全仓建仓（用全部 initial_capital 当保证金）
    - 名义价值 = initial_capital × leverage
    - 每个 bar 按 close mark-to-market
    - 模拟爆仓：当账户权益 ≤ 0（损失 ≥ 100% 保证金）→ 归零
    - 爆仓后剩余 bar equity 保持 0
    
    近似说明：
    - 真实 OKX 维持保证金率 ≈ 0.5% 名义价值（BTC/ETH 永续）
    - 真实爆仓触发早于 equity ≤ 0（margin < maintenance）
    - 本实现采用"equity ≤ 0 爆仓"作为保守上界（更晚爆仓，结果更乐观）
    - 高杠杆下（如 5x），一次 ~20% 回撤即触发归零
    """
    klines = data.klines
    if klines is None or len(klines) < 2:
        return BenchmarkResult(
            name=f"{leverage:.0f}x_leverage",
            initial_capital=initial_capital,
            final_equity=initial_capital,
            total_return_pct=0.0,
        )
    
    entry_price = float(klines.iloc[0]["close"])
    initial_ts = int(klines.iloc[0]["timestamp"])
    
    # 杠杆后单位数 = (initial_capital × leverage) / entry_price
    units = (initial_capital * leverage) / entry_price
    initial_margin = initial_capital  # 全部作保证金
    
    equity_curve: List[Tuple[int, float]] = []
    liquidated = False
    liquidation_idx: Optional[int] = None
    liquidation_ts: Optional[int] = None
    
    for idx, row in klines.iterrows():
        ts = int(row["timestamp"])
        px = float(row["close"])
        # mark-to-market equity
        equity = initial_margin + units * (px - entry_price)
        
        if not liquidated and equity <= 0:
            # 爆仓
            equity = 0.0
            liquidated = True
            liquidation_idx = int(idx)
            liquidation_ts = ts
            equity_curve.append((ts, 0.0))
            # 后续 bar 全部归零
            for jdx, jrow in klines.iloc[idx+1:].iterrows():
                jts = int(jrow["timestamp"])
                equity_curve.append((jts, 0.0))
            break
        else:
            equity_curve.append((ts, equity))
    
    if not equity_curve:
        return BenchmarkResult(
            name=f"{leverage:.0f}x_leverage",
            initial_capital=initial_capital,
            final_equity=initial_capital,
            total_return_pct=0.0,
        )
    
    final_equity = equity_curve[-1][1]
    total_return = (final_equity - initial_capital) / initial_capital * 100
    
    return BenchmarkResult(
        name=f"{leverage:.0f}x_leverage",
        initial_capital=initial_capital,
        final_equity=final_equity,
        total_return_pct=total_return,
        equity_curve=equity_curve,
        liquidated=liquidated,
        liquidation_idx=liquidation_idx,
        liquidation_ts=liquidation_ts,
    )


def run_all_benchmarks(
    data: BacktestData,
    initial_capital: float = 10000.0,
    leverage_levels: List[float] = (1.0, 5.0),
) -> List[BenchmarkResult]:
    """运行所有基准（1x + Lx）"""
    results = []
    # 1x spot
    results.append(run_buy_and_hold(data, initial_capital=initial_capital))
    # 杠杆版（除 1x 跳过避免重复）
    for L in leverage_levels:
        if L == 1.0:
            continue
        results.append(run_leveraged_hold(data, initial_capital=initial_capital, leverage=L))
    return results


def format_benchmark_table(results: List[BenchmarkResult]) -> str:
    """格式化基准结果为可打印字符串"""
    lines = ["── Benchmarks ──"]
    lines.append(f"  {'Name':<15} {'Return':>10} {'Liquidated':>12} {'Final Equity':>15}")
    lines.append("  " + "-" * 56)
    for r in results:
        liq = f"@{r.liquidation_idx}" if r.liquidated else "No"
        lines.append(f"  {r.name:<15} {r.total_return_pct:>+9.2f}% {liq:>12} ${r.final_equity:>13,.2f}")
    return "\n".join(lines)


__all__ = [
    "BenchmarkResult",
    "run_buy_and_hold",
    "run_leveraged_hold",
    "run_all_benchmarks",
    "format_benchmark_table",
]