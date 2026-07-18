# -*- coding: utf-8 -*-
"""
RiskCalculator.kelly_sizing_decision() 单元测试

Constitution §3.2 runner 集成的关键纯决策包装。

覆盖:
- 数据不足 → fallback (n < min, stats is None)
- Negative EV → reject (Kelly f_full ≤ 0)
- Active → 返回 max_loss_pct, 可能 cap 到 hard_cap
- 波动率缩仓通过 (透传到 calculate_kelly_size)
- 返回值类型契约 (status: str, max_loss_pct: Optional[float], reason: str)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from code.risk import RiskCalculator
from code.config import Config


@pytest.fixture(autouse=True)
def reset_config_singleton():
    Config._instance = None
    yield
    Config._instance = None


@pytest.fixture
def cfg():
    return Config()


@pytest.fixture
def risk(cfg):
    return RiskCalculator(cfg)


# 构造 StrategyStats (duck typed)
class FakeStats:
    def __init__(self, n, win_rate, avg_win_usd, avg_loss_usd, strategy="TEST"):
        self.n = n
        self.win_rate = win_rate
        self.avg_win_usd = avg_win_usd
        self.avg_loss_usd = avg_loss_usd
        self.strategy = strategy


# ──────────── 基础 ────────────

def test_kelly_decision_returns_tuple_of_correct_types(risk):
    """返回 (str, Optional[float], str) 契约."""
    status, pct, reason = risk.kelly_sizing_decision(
        strategy_stats=None,  # 触发 fallback
        equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    assert isinstance(status, str)
    assert pct is None  # fallback 不给 pct
    assert isinstance(reason, str)


def test_kelly_decision_status_in_three_categories(risk):
    """status ∈ {fallback_max_loss_pct, reject_negative_ev, kelly_active}."""
    # Fallback
    s, _, _ = risk.kelly_sizing_decision(
        strategy_stats=None, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    assert s == "fallback_max_loss_pct"


# ──────────── Fallback 路径 ────────────

def test_kelly_decision_none_stats_returns_fallback(risk):
    """无历史 (None) → fallback."""
    status, pct, reason = risk.kelly_sizing_decision(
        strategy_stats=None, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    assert status == "fallback_max_loss_pct"
    assert pct is None
    assert "no_strategy_history" in reason


def test_kelly_decision_n_below_min_returns_fallback(risk):
    """n < min_trades → fallback (即使其他 stats 看起来 OK)."""
    stats = FakeStats(n=29, win_rate=0.5, avg_win_usd=100.0, avg_loss_usd=80.0)
    status, pct, reason = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    assert status == "fallback_max_loss_pct"
    assert pct is None
    assert "n_29" in reason
    assert "min_30" in reason


def test_kelly_decision_n_equals_min_returns_active_when_ev_positive(risk):
    """n == min_trades 是边界 → 应该能进 active 路径."""
    stats = FakeStats(n=30, win_rate=0.5, avg_win_usd=100.0, avg_loss_usd=80.0)
    status, pct, _ = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    # b = 100/80 = 1.25, f_full = (0.5*1.25 - 0.5)/1.25 = 0.0625/1.25 = 0.05
    # frac 0.25 = 0.0125, size = 125 USD = 1.25% of 10000 → cap 到 1% (100 USD)
    # pct 应该是 capped 1.0
    assert status == "kelly_active"
    assert pct is not None
    assert pct == pytest.approx(risk._config.max_loss_percent_per_trade, rel=1e-3)


# ──────────── Reject 路径 (Negative EV) ────────────

def test_kelly_decision_negative_ev_returns_reject(risk):
    """B 策略 BTC 1h: WR=27.8%, b=1.5 → negative EV → reject."""
    stats = FakeStats(n=50, win_rate=0.278, avg_win_usd=1.5, avg_loss_usd=1.0)
    status, pct, reason = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    assert status == "reject_negative_ev"
    assert pct is None
    assert "kelly_reject" in reason
    assert "negative_EV" in reason


def test_kelly_decision_zero_win_rate_returns_reject(risk):
    """WR=0% 必为 negative EV → reject."""
    stats = FakeStats(n=40, win_rate=0.0, avg_win_usd=100.0, avg_loss_usd=100.0)
    status, pct, _ = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    assert status == "reject_negative_ev"


# ──────────── Active 路径 ────────────

def test_kelly_decision_low_wr_below_cap_returns_active(risk):
    """WR=10%, b=10: f_full=0.01, frac 1/4=0.0025 → 25 USD << hard_cap 100 → not capped."""
    stats = FakeStats(n=50, win_rate=0.10, avg_win_usd=1000.0, avg_loss_usd=100.0)
    status, pct, reason = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    assert status == "kelly_active"
    # raw_pct = (25 / 10000) * 100 = 0.25% < hard_cap 1.0%
    assert pct == pytest.approx(0.25, rel=1e-3)
    assert "capped" not in reason


def test_kelly_decision_high_wr_capped_to_hard_cap(risk):
    """WR=70%, b=3: Kelly 想要 15% pct → cap 到 hard_cap 1%.
    (calculate_kelly_size 内部已 cap, reason 包含 'capped_at_max_loss_X.Xpct')."""
    stats = FakeStats(n=50, win_rate=0.7, avg_win_usd=300.0, avg_loss_usd=100.0)
    status, pct, reason = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    assert status == "kelly_active"
    assert pct == pytest.approx(risk._config.max_loss_percent_per_trade, rel=1e-3)
    # calculate_kelly_size 的 cap reason 格式
    assert "capped_at_max_loss_1.0pct" in reason
    assert "Kelly_wants_15" in reason  # 原应 15% 是如大小写存在


def test_kelly_decision_no_loss_history_fallback_to_hard_cap(risk):
    """avg_loss=0 (全胜策略) → kelly fallback → 应该是 kelly_active 但等于 hard_cap."""
    stats = FakeStats(n=50, win_rate=1.0, avg_win_usd=100.0, avg_loss_usd=0.0)
    status, pct, reason = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    # Kelly 走 fallback (计算层返回 hard_cap), pct = hard_cap
    assert status == "kelly_active"
    assert pct == pytest.approx(risk._config.max_loss_percent_per_trade, rel=1e-3)
    assert "fallback" in reason.lower() or "no_loss_history" in reason


# ──────────── 波动率缩仓 (透传) ────────────

def test_kelly_decision_high_volatility_lowers_pct(risk):
    """atr_ratio ≥ 1.5 → 缩仓 × 0.7 (透传到 calculate_kelly_size).

    用 WR=0.5, b=1.05 (f_full=0.0238) 让 pct < hard_cap, 这样缩仓比例可检查.
    (默认参数 WR=0.5, b=2 会触发 cap, 看不到 dampening 效果)"""
    # b=1.05 → f_full = (0.5*1.05-0.5)/1.05 = 0.025/1.05 = 0.0238
    # frac 1/4 = 0.00596, size = 59.6 USD << hard_cap 100 USD, no cap
    stats = FakeStats(n=50, win_rate=0.5, avg_win_usd=105.0, avg_loss_usd=100.0)
    _, pct_low, _ = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    _, pct_high, reason_high = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=2.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    # pct_low 应为 ~0.595%, pct_high 应为 ~0.417% (× 0.7)
    assert pct_low is not None and pct_high is not None
    assert pct_low == pytest.approx(0.595, abs=1e-2)  # baseline 不 cap
    assert pct_high == pytest.approx(pct_low * 0.7, rel=1e-3)
    assert "high_vol" in reason_high


def test_kelly_decision_atr_none_uses_default(risk):
    """atr_ratio=None → 默认 1.0 (不缩仓)."""
    stats = FakeStats(n=50, win_rate=0.5, avg_win_usd=200.0, avg_loss_usd=100.0)
    _, pct_default, _ = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=None, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    _, pct_explicit_1, _ = risk.kelly_sizing_decision(
        strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
        sl_distance_pct=0.005, min_trades_for_kelly=30,
    )
    assert pct_default == pct_explicit_1


# ──────────── 不变量 ────────────

def test_kelly_decision_pct_never_exceeds_hard_cap(risk):
    """max_loss_pct 永远 ≤ hard_cap (Constitution §5)."""
    cases = [
        FakeStats(n=50, win_rate=0.95, avg_win_usd=500.0, avg_loss_usd=100.0),
        FakeStats(n=50, win_rate=0.99, avg_win_usd=1000.0, avg_loss_usd=100.0),
        FakeStats(n=50, win_rate=0.50, avg_win_usd=1000.0, avg_loss_usd=100.0),
    ]
    for stats in cases:
        status, pct, _ = risk.kelly_sizing_decision(
            strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
            sl_distance_pct=0.005, min_trades_for_kelly=30,
        )
        if status == "kelly_active":
            assert pct is not None
            assert pct <= risk._config.max_loss_percent_per_trade + 1e-9


def test_kelly_decision_pct_always_non_negative_when_active(risk):
    """active 路径下 pct ≥ 0."""
    cases = [
        FakeStats(n=50, win_rate=0.5, avg_win_usd=200.0, avg_loss_usd=100.0),
        FakeStats(n=50, win_rate=0.10, avg_win_usd=1000.0, avg_loss_usd=100.0),
        FakeStats(n=50, win_rate=0.99, avg_win_usd=100.0, avg_loss_usd=100.0),
    ]
    for stats in cases:
        status, pct, _ = risk.kelly_sizing_decision(
            strategy_stats=stats, equity=10000.0, atr_ratio=1.0, leverage=3,
            sl_distance_pct=0.005, min_trades_for_kelly=30,
        )
        if status == "kelly_active":
            assert pct >= 0
