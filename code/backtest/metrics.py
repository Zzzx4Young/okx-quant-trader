#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测风险与表现指标（Phase 2）

基于 equity_curve 计算机构级精度指标：
- Sharpe Ratio（年化）
- Sortino Ratio（年化，下行风险）
- Max Drawdown
- Calmar Ratio（去杠杆）
- 总收益率、胜率、Avg PnL

所有指标自动从 equity_curve 时间戳检测 bar 间隔并年化。
"""

from typing import List, Tuple, Optional
import math
import numpy as np
import pandas as pd


# ─── 工具：检测 bar 间隔 ───

def detect_bar_seconds(timestamps_ms: List[int]) -> float:
    """
    从时间戳自动检测 bar 间隔（秒）。
    用前 5 个间隔的中位数（防御异常值）。
    """
    if len(timestamps_ms) < 2:
        return 3600.0  # 默认 1h
    
    diffs = []
    for i in range(1, min(6, len(timestamps_ms))):
        diffs.append((timestamps_ms[i] - timestamps_ms[i-1]) / 1000.0)
    
    if not diffs:
        return 3600.0
    
    return float(np.median(diffs))


def annualization_factor(bar_seconds: float) -> float:
    """年化因子 = 1 年的 bar 数"""
    seconds_per_year = 365.25 * 24 * 3600
    return seconds_per_year / bar_seconds if bar_seconds > 0 else 252.0


# ─── 核心指标 ───

def compute_returns(equity_curve: List[Tuple[int, float]]) -> np.ndarray:
    """
    从 equity_curve 计算每 bar 的简单收益率。
    equity_curve: [(ts_ms, equity), ...]
    """
    if len(equity_curve) < 2:
        return np.array([])
    equities = np.array([e for _, e in equity_curve], dtype=float)
    # 防 0 除
    prev = equities[:-1]
    curr = equities[1:]
    prev = np.where(np.abs(prev) < 1e-9, 1e-9, prev)
    return (curr - prev) / prev


def sharpe_ratio(
    equity_curve: List[Tuple[int, float]],
    risk_free_rate: float = 0.0,
) -> float:
    """
    Sharpe Ratio = (mean(r) - rf) / std(r) × sqrt(annualization_factor)
    """
    if len(equity_curve) < 2:
        return 0.0
    
    returns = compute_returns(equity_curve)
    if len(returns) == 0 or np.std(returns) == 0:
        return 0.0
    
    ts_ms = [t for t, _ in equity_curve]
    bar_sec = detect_bar_seconds(ts_ms)
    ann = annualization_factor(bar_sec)
    
    excess = returns - (risk_free_rate / ann)  # 年化 rf 折算到每 bar
    mean_excess = float(np.mean(excess))
    std_returns = float(np.std(returns, ddof=1))
    
    if std_returns < 1e-12:
        return 0.0
    
    return (mean_excess / std_returns) * math.sqrt(ann)


def sortino_ratio(
    equity_curve: List[Tuple[int, float]],
    risk_free_rate: float = 0.0,
) -> float:
    """
    Sortino Ratio = (mean(r) - rf) / downside_std(r) × sqrt(annualization_factor)
    downside_std: 只看负收益（< 0）的标准差
    """
    if len(equity_curve) < 2:
        return 0.0
    
    returns = compute_returns(equity_curve)
    if len(returns) == 0:
        return 0.0
    
    ts_ms = [t for t, _ in equity_curve]
    bar_sec = detect_bar_seconds(ts_ms)
    ann = annualization_factor(bar_sec)
    
    excess = returns - (risk_free_rate / ann)
    mean_excess = float(np.mean(excess))
    
    # 下行收益：只取 < 0 的
    downside = returns[returns < 0]
    if len(downside) < 2:
        return 0.0 if mean_excess <= 0 else float('inf')
    
    downside_std = float(np.std(downside, ddof=1))
    if downside_std < 1e-12:
        return 0.0 if mean_excess <= 0 else float('inf')
    
    return (mean_excess / downside_std) * math.sqrt(ann)


def max_drawdown_pct(equity_curve: List[Tuple[int, float]]) -> float:
    """最大回撤（百分比）"""
    if not equity_curve:
        return 0.0
    equities = np.array([e for _, e in equity_curve], dtype=float)
    if len(equities) == 0:
        return 0.0
    
    # 防 0 除 + 负权益处理（修 Bug 3）
    # 当 equity <= 0：账户已死，MaxDD = 100%（从峰值到 0）
    if np.any(equities <= 0):
        return 100.0

    running_max = np.maximum.accumulate(equities)
    # 防 running_max 接近 0
    running_max = np.where(np.abs(running_max) < 1e-9, 1e-9, running_max)
    drawdowns = (equities - running_max) / running_max
    # drawdowns 全是 ≤ 0；返回绝对值最大的百分比
    return float(-np.min(drawdowns) * 100) if len(drawdowns) > 0 else 0.0


def calmar_ratio(
    equity_curve: List[Tuple[int, float]],
    initial_capital: float,
) -> float:
    """
    de-Leveraged Calmar = 年化收益 / max_drawdown
    不依赖杠杆，只看策略本身 alpha
    """
    if not equity_curve or initial_capital <= 0:
        return 0.0
    
    ts_ms = [t for t, _ in equity_curve]
    bar_sec = detect_bar_seconds(ts_ms)
    ann = annualization_factor(bar_sec)
    
    final = equity_curve[-1][1]
    total_return_pct = (final - initial_capital) / initial_capital * 100
    
    # 年化收益率（CAGR 近似）
    n_bars = len(equity_curve)
    years = n_bars / ann
    if years < 1e-6:
        return 0.0
    
    cagr = ((final / initial_capital) ** (1 / years) - 1) * 100
    
    dd = max_drawdown_pct(equity_curve)
    if dd < 1e-6:
        return float('inf') if cagr > 0 else 0.0
    
    return cagr / dd


# ─── 聚合 ───

def compute_all_metrics(
    equity_curve: List[Tuple[int, float]],
    initial_capital: float,
    trades: Optional[list] = None,
    risk_free_rate: float = 0.0,
) -> dict:
    """
    一次算完所有指标。返回 dict 便于 DataFrame 化。
    """
    if not equity_curve or initial_capital <= 0:
        return {
            "total_return_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown_pct": 0.0,
            "calmar": 0.0,
            "n_trades": 0,
            "win_rate_pct": 0.0,
        }
    
    final = equity_curve[-1][1]
    total_return_pct = (final - initial_capital) / initial_capital * 100
    
    sr = sharpe_ratio(equity_curve, risk_free_rate=risk_free_rate)
    so = sortino_ratio(equity_curve, risk_free_rate=risk_free_rate)
    dd = max_drawdown_pct(equity_curve)
    ca = calmar_ratio(equity_curve, initial_capital)
    
    n_trades = len(trades) if trades else 0
    win_rate = 0.0
    if n_trades > 0:
        wins = sum(1 for t in trades if getattr(t, 'net_pnl', 0) > 0)
        win_rate = wins / n_trades * 100
    
    return {
        "total_return_pct": total_return_pct,
        "sharpe": sr,
        "sortino": so,
        "max_drawdown_pct": dd,
        "calmar": ca,
        "n_trades": n_trades,
        "win_rate_pct": win_rate,
    }


# ─── 格式化输出 ───

def format_metrics_table(metrics_dict: dict, label: str = "") -> str:
    """格式化为可打印字符串"""
    lines = [
        f"── {label or 'Metrics'} ──",
        f"  总收益率:        {metrics_dict.get('total_return_pct', 0):+.2f}%",
        f"  Sharpe:          {metrics_dict.get('sharpe', 0):+.3f}",
        f"  Sortino:         {metrics_dict.get('sortino', 0):+.3f}",
        f"  Max Drawdown:    {metrics_dict.get('max_drawdown_pct', 0):.2f}%",
        f"  Calmar:          {metrics_dict.get('calmar', 0):+.3f}",
        f"  Trades:          {metrics_dict.get('n_trades', 0)}",
        f"  Win Rate:        {metrics_dict.get('win_rate_pct', 0):.1f}%",
    ]
    return "\n".join(lines)


__all__ = [
    "detect_bar_seconds",
    "annualization_factor",
    "compute_returns",
    "sharpe_ratio",
    "sortino_ratio",
    "max_drawdown_pct",
    "calmar_ratio",
    "compute_all_metrics",
    "format_metrics_table",
]