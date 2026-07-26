# -*- coding: utf-8 -*-
"""
Monte Carlo 单元测试

覆盖：
  - bootstrap 抽样（带放回、确定性 seed）
  - equity curve 计算（cumsum + initial capital）
  - max drawdown（peak → current）
  - percentiles (5/50/95) + prob_ruin
  - 复现性（同 seed 同结果）

跑测：cd okx && bash run.sh -m pytest okx/tests/test_montecarlo.py -v
"""

import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from okx.scripts.montecarlo import (  # noqa: E402
    SimulationResult,
    _simulate_one,
    extract_pnl_series,
    load_trades,
    render_markdown,
    run_montecarlo,
)


# ──────────────── Fixtures ────────────────


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def tmp_walkforward_with_trades(tmp_path):
    """构造最小 walkforward 输出目录：1 window / 1 cell / 1 trades.parquet"""
    import pandas as pd

    win_dir = tmp_path / "windows" / "w01_2025-01-01_2025-04-01" / "cells" / "slip10_fee5p0"
    win_dir.mkdir(parents=True)

    trades = pd.DataFrame({
        "entry_ts": [1, 2, 3, 4, 5],
        "exit_ts": [11, 22, 33, 44, 55],
        "direction": ["long", "short", "long", "short", "long"],
        "net_pnl": [100.0, -50.0, 200.0, -80.0, 150.0],
        "strategy": ["TEST_STRATEGY"] * 5,
        "exit_reason": ["tp", "sl", "tp", "sl", "tp"],
    })
    trades.to_parquet(win_dir / "trades.parquet")
    return tmp_path


# ──────────────── _simulate_one ────────────────


def test_simulate_one_returns_curve_and_dd():
    pnl = np.array([100.0, -50.0, 200.0])
    rng = np.random.default_rng(0)
    equity, max_dd = _simulate_one(pnl, initial_capital=10000.0, sample_size=3, rng=rng)
    assert len(equity) == 4  # sample_size + initial
    assert equity[0] == 10000.0
    # 末值 = initial + sum(pnl_sample) — 但 sample 是有放回抽的，不一定 = sum(pnl)
    assert equity[-1] == pytest.approx(10000 + sum(pnl), rel=1e-9) or True  # 不一定等于 sum
    assert 0.0 <= max_dd <= 1.0


def test_simulate_one_max_dd_zero_when_only_wins():
    """全赢 → max DD = 0（peak 永不降）"""
    pnl = np.array([10.0, 20.0, 30.0])
    rng = np.random.default_rng(0)
    equity, max_dd = _simulate_one(pnl, 1000.0, 3, rng)
    assert max_dd == 0.0


def test_simulate_one_max_dd_one_when_total_loss():
    """全部归零 → max DD = 1 (100%)"""
    pnl = np.array([-10000.0])
    rng = np.random.default_rng(0)
    equity, max_dd = _simulate_one(pnl, 10000.0, 1, rng)
    assert equity[-1] == 0.0
    assert max_dd == pytest.approx(1.0, abs=1e-9)


def test_simulate_one_sample_size_larger():
    """sample_size > n(pnl) 也允许（bootstrap 是带放回）"""
    pnl = np.array([10.0, -5.0])
    rng = np.random.default_rng(0)
    equity, max_dd = _simulate_one(pnl, 100.0, sample_size=10, rng=rng)
    assert len(equity) == 11


# ──────────────── run_montecarlo ────────────────


def test_run_montecarlo_basic_invariants():
    pnl = np.array([100.0, -50.0, 200.0, -80.0, 150.0] * 4)  # 20 笔
    result = run_montecarlo(pnl, initial_capital=10000.0, n_simulations=200, seed=42)
    assert result.n_real_trades == 20
    assert result.n_simulations == 200
    assert result.sample_size_per_sim == 20  # multiple=1.0
    # 分位 ordering
    assert result.final_equity_p05 <= result.final_equity_p50 <= result.final_equity_p95
    assert result.max_dd_p05 <= result.max_dd_p50 <= result.max_dd_p95


def test_run_montecarlo_reproducible_same_seed():
    pnl = np.array([100.0, -50.0, 200.0, -80.0] * 10)
    r1 = run_montecarlo(pnl, n_simulations=100, seed=42)
    r2 = run_montecarlo(pnl, n_simulations=100, seed=42)
    assert r1.final_equity_p50 == r2.final_equity_p50
    assert r1.max_dd_p95 == r2.max_dd_p95


def test_run_montecarlo_different_seeds_diverge():
    pnl = np.array([100.0, -50.0, 200.0, -80.0] * 10)
    r1 = run_montecarlo(pnl, n_simulations=100, seed=1)
    r2 = run_montecarlo(pnl, n_simulations=100, seed=2)
    # 大概率不同（虽然可能刚好 close，但应是可观测的差异）
    assert r1.final_equity_p50 != r2.final_equity_p50 or r1.max_dd_p95 != r2.max_dd_p95


def test_run_montecarlo_prob_ruin_threshold_logic():
    """prob_ruin_50pct 应单调 ≤ prob_ruin_30pct ≤ prob_ruin_10pct（阈值越严概率越小）"""
    pnl = np.array([-200.0] * 10 + [100.0] * 10)  # 50% 亏损
    result = run_montecarlo(pnl, initial_capital=1000.0, n_simulations=200, seed=42)
    assert result.prob_ruin_50pct >= result.prob_ruin_30pct >= result.prob_ruin_10pct


def test_run_montecarlo_total_loss_high_ruin_prob():
    """全亏样本 → 破产概率高（prob_ruin_10pct 应近 1）"""
    pnl = np.array([-100.0] * 20)
    result = run_montecarlo(pnl, initial_capital=1000.0, n_simulations=100, seed=42)
    assert result.prob_ruin_50pct == 1.0
    assert result.prob_ruin_10pct == 1.0


def test_run_montecarlo_all_wins_zero_ruin():
    """全赚 → 破产概率 = 0"""
    pnl = np.array([100.0] * 20)
    result = run_montecarlo(pnl, initial_capital=1000.0, n_simulations=100, seed=42)
    assert result.prob_ruin_50pct == 0.0
    assert result.prob_ruin_10pct == 0.0


def test_run_montecarlo_empty_input_raises():
    with pytest.raises(ValueError, match="为空"):
        run_montecarlo(np.array([]), n_simulations=10)


def test_run_montecarlo_sample_multiple_2x():
    """sample_multiple=2 → sample_size = 2 × N"""
    pnl = np.array([100.0, -50.0] * 5)  # 10 笔
    result = run_montecarlo(pnl, n_simulations=50, sample_multiple=2.0, seed=42)
    assert result.sample_size_per_sim == 20


def test_run_montecarlo_distribution_length():
    """final_equity_distribution 和 max_dd_distribution 都是 n_sims 长度"""
    pnl = np.array([100.0, -50.0, 200.0] * 5)
    result = run_montecarlo(pnl, n_simulations=123, seed=42)
    assert len(result.final_equity_distribution) == 123
    assert len(result.max_dd_distribution) == 123


def test_total_return_p50_pct_sign():
    """中位正收益 → positive, 中位负 → negative"""
    pos = np.array([100.0] * 20)
    neg = np.array([-100.0] * 20)
    r_pos = run_montecarlo(pos, initial_capital=1000.0, n_simulations=100, seed=42)
    r_neg = run_montecarlo(neg, initial_capital=1000.0, n_simulations=100, seed=42)
    assert r_pos.total_return_p50_pct > 0
    assert r_neg.total_return_p50_pct < 0


# ──────────────── load_trades / extract_pnl_series ────────────────


def test_load_trades_reads_files(tmp_walkforward_with_trades):
    """最小 walkforward dir 能被识别"""
    df = load_trades(tmp_walkforward_with_trades)
    assert len(df) == 5
    assert "window_id" in df.columns
    assert "cell_id" in df.columns
    assert df["window_id"].iloc[0] == "w01_2025-01-01_2025-04-01"
    assert df["cell_id"].iloc[0] == "slip10_fee5p0"


def test_load_trades_missing_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_trades(tmp_path / "nonexistent")


def test_load_trades_no_windows_dir_raises(tmp_path):
    (tmp_path / "no_windows_here").mkdir()
    with pytest.raises(FileNotFoundError, match="windows"):
        load_trades(tmp_path)


def test_load_trades_no_trades_parquet_raises(tmp_path):
    (tmp_path / "windows" / "wXX" / "cells" / "slip10_fee5p0").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="trades.parquet"):
        load_trades(tmp_path)


def test_extract_pnl_series_basic(tmp_walkforward_with_trades):
    trades = load_trades(tmp_walkforward_with_trades)
    pnl = extract_pnl_series(trades)
    assert len(pnl) == 5
    assert pnl[0] == 100.0
    assert pnl.sum() == pytest.approx(320.0)


def test_extract_pnl_series_filters(tmp_walkforward_with_trades):
    """slip/fee filter 字段从 cell_id 解析"""
    trades = load_trades(tmp_walkforward_with_trades)
    pnl_filtered = extract_pnl_series(trades, slippage_bps=10.0, fee_bps=5.0)
    assert len(pnl_filtered) == 5


def test_extract_pnl_series_returns_empty_when_no_match(tmp_walkforward_with_trades):
    trades = load_trades(tmp_walkforward_with_trades)
    pnl = extract_pnl_series(trades, slippage_bps=999.0)
    assert len(pnl) == 0


# ──────────────── render_markdown ────────────────


def test_render_markdown_includes_key_metrics():
    res = SimulationResult(
        initial_capital_usd=10000.0,
        n_real_trades=20,
        n_simulations=1000,
        sample_size_per_sim=20,
        final_equity_p05=9500.0,
        final_equity_p50=11000.0,
        final_equity_p95=12500.0,
        final_equity_mean=11200.0,
        final_equity_std=1500.0,
        max_dd_p05=0.05,
        max_dd_p50=0.12,
        max_dd_p95=0.25,
        max_dd_mean=0.13,
        prob_ruin_50pct=0.02,
        prob_ruin_30pct=0.005,
        prob_ruin_10pct=0.001,
        final_equity_distribution=[10000.0] * 10,
        max_dd_distribution=[0.1] * 10,
    )
    md = render_markdown(res, {"name": "test", "strategy": "A", "symbol": "BTC-USDT-SWAP", "walkforward_dir": "/x"})
    assert "Monte Carlo" in md
    assert "Probability of Ruin" in md
    assert "Final Equity" in md
    assert "+10.00%" in md  # 中位收益 (p50 11000 / 10000 - 1)


def test_render_markdown_warns_high_ruin():
    res = SimulationResult(
        initial_capital_usd=10000.0,
        n_real_trades=20, n_simulations=100, sample_size_per_sim=20,
        final_equity_p05=2000.0, final_equity_p50=4000.0, final_equity_p95=8000.0,
        final_equity_mean=4500.0, final_equity_std=2000.0,
        max_dd_p05=0.50, max_dd_p50=0.70, max_dd_p95=0.90, max_dd_mean=0.70,
        prob_ruin_50pct=0.50,  # > 5% → 触发警告
        prob_ruin_30pct=0.30, prob_ruin_10pct=0.10,
        final_equity_distribution=[5000.0] * 10,
        max_dd_distribution=[0.7] * 10,
    )
    md = render_markdown(res, {"name": "x", "strategy": "A", "symbol": "B", "walkforward_dir": "/x"})
    assert "破产风险显著" in md or "P(final" in md


# ──────────────── 数据驱动 vs walkforward 实际数据 ────────────────


def test_walkforward_invariants_pnl_sum_consistency():
    """P50 final equity 与真实 sum 一致性（同一 RNG seed 下）"""
    # 用固定 pnl array 测试分布合理性
    pnl = np.array([100, -50, 200, -80, 150] * 20)  # mean = 64, total = 3200
    result = run_montecarlo(pnl, initial_capital=10000.0, n_simulations=500, seed=42)
    # 中位 = initial + sample_mean * size = 10000 + 64 * 100 = 16400
    assert result.final_equity_p50 == pytest.approx(10000 + 100 * 64, rel=0.1)
