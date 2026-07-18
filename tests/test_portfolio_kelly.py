# -*- coding: utf-8 -*-
"""
Portfolio.get_strategy_stats() 单元测试

用于 Constitution §3.2 Kelly Criterion 动态仓位决策 (v1.8.2)。

覆盖场景:
- 无历史 → 返回 None
- 全胜 → win_rate=1, avg_win>0, avg_loss=0 (avg_loss=0 触发 Kelly fallback)
- 全亏 → win_rate=0, avg_win=0, avg_loss>0
- 混合胜率/盈亏比 → 正确聚合
- 多 strategy 过滤 → 只算指定 strategy
- 缺 realized_pnl 字段 → fallback pnl
- 零 pnl 笔 → 算入分母不算入 wins/losses (平局笔)
"""

import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from code.portfolio import Portfolio, StrategyStats


# ──────────── Fixtures ────────────

@pytest.fixture
def portfolio(tmp_path):
    """用 tmp_path 隔离 portfolio.json, 不污染 state/。"""
    p = Portfolio(portfolio_path=str(tmp_path / "portfolio.json"))
    yield p


def _populate_closed_positions(portfolio: Portfolio, positions: list) -> None:
    """
    直接写 closed_positions (绕开 close_position 的 P&L 计算).
    每个 position 字段:
      symbol, direction, size, entry_price, leverage, sl_price, tp_price,
      order_id, trigger_strategy, opened_at, closed_at, realized_pnl
    """
    portfolio._data["closed_positions"] = list(positions)
    portfolio._save()


# ──────────── 基础: NamedTuple 字段 ────────────

def test_strategy_stats_has_expected_fields():
    """StrategyStats NamedTuple 字段定义. caller 依赖这 5 个字段."""
    stats = StrategyStats(strategy="X", n=10, win_rate=0.5, avg_win_usd=100.0, avg_loss_usd=80.0)
    assert stats.strategy == "X"
    assert stats.n == 10
    assert stats.win_rate == 0.5
    assert stats.avg_win_usd == 100.0
    assert stats.avg_loss_usd == 80.0


# ──────────── 无历史 ────────────

def test_get_strategy_stats_no_history_returns_none(portfolio):
    """空 closed_positions → None."""
    result = portfolio.get_strategy_stats("BB_RSI_REVERSION")
    assert result is None


def test_get_strategy_stats_filters_by_strategy(portfolio):
    """closed_positions 存在但 strategy 不匹配 → None."""
    _populate_closed_positions(portfolio, [
        {"trigger_strategy": "EMA20_BREAKOUT", "realized_pnl": 100.0},
        {"trigger_strategy": "VOLATILITY_BREAKOUT", "realized_pnl": -50.0},
    ])
    # 查不存在的 strategy
    assert portfolio.get_strategy_stats("BB_RSI_REVERSION") is None


# ──────────── 全胜 (avg_loss=0 → 触发 Kelly fallback) ────────────

def test_get_strategy_stats_all_wins_triggers_kelly_fallback(portfolio):
    """全胜 N=5: win_rate=1, avg_win=100, avg_loss=0.
    avg_loss=0 会让 Kelly 自动 fallback 到 1% 本金 (caller 负责检查 min_trades)."""
    _populate_closed_positions(portfolio, [
        {"trigger_strategy": "X", "realized_pnl": 100.0},
        {"trigger_strategy": "X", "realized_pnl": 50.0},
        {"trigger_strategy": "X", "realized_pnl": 200.0},
        {"trigger_strategy": "X", "realized_pnl": 80.0},
        {"trigger_strategy": "X", "realized_pnl": 70.0},
    ])
    stats = portfolio.get_strategy_stats("X")
    assert stats is not None
    assert stats.n == 5
    assert stats.win_rate == 1.0
    assert stats.avg_win_usd == pytest.approx(100.0, rel=1e-3)
    assert stats.avg_loss_usd == 0.0  # 触发 Kelly fallback


# ──────────── 全亏 ────────────

def test_get_strategy_stats_all_losses_returns_negative_ev_signal(portfolio):
    """全亏: win_rate=0, avg_loss>0 → Kelly f_full ≤ 0 → caller 拒绝."""
    _populate_closed_positions(portfolio, [
        {"trigger_strategy": "X", "realized_pnl": -100.0},
        {"trigger_strategy": "X", "realized_pnl": -50.0},
        {"trigger_strategy": "X", "realized_pnl": -200.0},
    ])
    stats = portfolio.get_strategy_stats("X")
    assert stats is not None
    assert stats.n == 3
    assert stats.win_rate == 0.0
    assert stats.avg_win_usd == 0.0
    assert stats.avg_loss_usd == pytest.approx((100 + 50 + 200) / 3, rel=1e-3)


# ──────────── 混合胜率/盈亏比 ────────────

def test_get_strategy_stats_mixed_wins_losses(portfolio):
    """混合: 4 笔, 2 盈 2 亏 → win_rate=0.5, avg_win=150, avg_loss=100."""
    _populate_closed_positions(portfolio, [
        {"trigger_strategy": "X", "realized_pnl": 200.0},   # win
        {"trigger_strategy": "X", "realized_pnl": 100.0},   # win
        {"trigger_strategy": "X", "realized_pnl": -100.0},  # loss
        {"trigger_strategy": "X", "realized_pnl": -100.0},  # loss
    ])
    stats = portfolio.get_strategy_stats("X")
    assert stats is not None
    assert stats.n == 4
    assert stats.win_rate == 0.5
    assert stats.avg_win_usd == pytest.approx(150.0, rel=1e-3)
    assert stats.avg_loss_usd == pytest.approx(100.0, rel=1e-3)


def test_get_strategy_stats_filters_correctly_across_strategies(portfolio):
    """3 个 strategies, 各 2-3 笔: 查询每条应该只返回自己."""
    _populate_closed_positions(portfolio, [
        {"trigger_strategy": "A", "realized_pnl": 100.0},
        {"trigger_strategy": "A", "realized_pnl": -80.0},
        {"trigger_strategy": "B", "realized_pnl": 200.0},
        {"trigger_strategy": "B", "realized_pnl": 150.0},
        {"trigger_strategy": "C", "realized_pnl": -50.0},
        {"trigger_strategy": "C", "realized_pnl": -30.0},
    ])
    a = portfolio.get_strategy_stats("A")
    b = portfolio.get_strategy_stats("B")
    c = portfolio.get_strategy_stats("C")
    assert a.n == 2 and a.win_rate == 0.5
    assert b.n == 2 and b.win_rate == 1.0 and b.avg_loss_usd == 0.0
    assert c.n == 2 and c.win_rate == 0.0 and c.avg_win_usd == 0.0


# ──────────── pnl 字段 fallback (reconciliation 路径) ────────────

def test_get_strategy_stats_uses_realized_pnl_or_falls_back_to_pnl(portfolio):
    """优先 realized_pnl (close_position 设置), 缺时 fallback pnl (reconciliation 设置)."""
    _populate_closed_positions(portfolio, [
        {"trigger_strategy": "X", "realized_pnl": 100.0},
        {"trigger_strategy": "X", "pnl": -50.0},  # 没有 realized_pnl, 走 pnl fallback
        {"trigger_strategy": "X", "realized_pnl": 200.0},
    ])
    stats = portfolio.get_strategy_stats("X")
    assert stats is not None
    assert stats.n == 3
    assert stats.win_rate == pytest.approx(2/3, rel=1e-3)
    assert stats.avg_win_usd == pytest.approx(150.0, rel=1e-3)
    assert stats.avg_loss_usd == pytest.approx(50.0, rel=1e-3)


def test_get_strategy_stats_handles_missing_pnl_field(portfolio):
    """既无 realized_pnl 也无 pnl → 视为 0 (在 loss list 中不计入, wins 也不计入)."""
    _populate_closed_positions(portfolio, [
        {"trigger_strategy": "X", "realized_pnl": 100.0},
        {"trigger_strategy": "X"},  # 缺 field
        {"trigger_strategy": "X", "realized_pnl": -50.0},
    ])
    stats = portfolio.get_strategy_stats("X")
    assert stats is not None
    assert stats.n == 3
    # 1 盈 + 1 亏 + 1 平局 = 3 笔, win_rate = 1/3
    assert stats.win_rate == pytest.approx(1/3, rel=1e-3)
    assert stats.avg_win_usd == pytest.approx(100.0, rel=1e-3)
    assert stats.avg_loss_usd == pytest.approx(50.0, rel=1e-3)


# ──────────── 不变量 ────────────

@pytest.mark.parametrize("n_wins,n_losses", [(5, 0), (0, 5), (10, 10), (50, 50), (1, 2)])
def test_get_strategy_stats_win_rate_always_in_01(portfolio, n_wins, n_losses):
    """win_rate 永远 ∈ [0, 1] (浮点不超界)."""
    positions = []
    for i in range(n_wins):
        positions.append({"trigger_strategy": "X", "realized_pnl": 100.0 + i})
    for i in range(n_losses):
        positions.append({"trigger_strategy": "X", "realized_pnl": -50.0 - i})
    _populate_closed_positions(portfolio, positions)
    stats = portfolio.get_strategy_stats("X")
    assert stats is not None
    assert 0.0 <= stats.win_rate <= 1.0
    assert stats.n == n_wins + n_losses


def test_get_strategy_stats_thread_safe(portfolio):
    """Portfolio 是 thread-safe (跟其他方法一致)."""
    import threading
    _populate_closed_positions(portfolio, [
        {"trigger_strategy": "X", "realized_pnl": 100.0} for _ in range(10)
    ])
    errors = []
    def call():
        try:
            for _ in range(50):
                s = portfolio.get_strategy_stats("X")
                assert s is not None
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=call) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors
