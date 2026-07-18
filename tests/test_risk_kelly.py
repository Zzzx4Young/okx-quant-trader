# -*- coding: utf-8 -*-
"""
RiskCalculator.calculate_kelly_size() 单元测试

覆盖 (Constitution §3.2 v1.8.2):
- 经典 Kelly 公式正确性 (50% WR + b=2 → Kelly=0.25)
- Negative EV 拒绝（B 策略 BTC 1h: 27.8% WR + b=1.5 → negative, 必须返回 0）
- Hard cap 不破 (Constitution §5, 1% 本金硬上限)
- Fractional Kelly 默认 1/4
- 高波动缩仓 (atr_ratio ≥ 1.5 → × 0.7)
- 数据不足 fallback (avg_loss=0)
- 入参校验 (win_rate, avg_win, avg_loss, equity, leverage, sl_distance)
- Reason 字符串格式 (供 logging/audit)
- 不依赖 leverage (size_usd 是 USD, 与杠杆解耦)

不变量:
- 返回类型永远是 tuple[float, str]
- size_usd >= 0 永远成立
- size_usd <= current_equity * max_loss_percent_per_trade / 100 永远成立 (Constitution §5)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from code.risk import RiskCalculator
from code.config import Config


# ──────────── Fixtures ────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    Config._instance = None
    yield
    Config._instance = None


@pytest.fixture
def cfg():
    """默认 config (v1.8.1: max_loss=1%, leverage=3x)."""
    return Config()


@pytest.fixture
def risk(cfg):
    return RiskCalculator(cfg)


# ──────────── 基础字段 ────────────

def test_kelly_returns_tuple_of_float_str(risk):
    """返回值类型: (float, str)."""
    size, reason = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=100.0, avg_loss=100.0,
    )
    assert isinstance(size, float)
    assert isinstance(reason, str)
    assert len(reason) > 0


def test_kelly_size_is_non_negative(risk):
    """size_usd 永远 >= 0."""
    # 各种参数下 size 都 >= 0
    cases = [
        (0.0, 100.0, 100.0),     # WR=0 → negative EV → 0
        (1.0, 100.0, 100.0),     # WR=100% → 高 Kelly
        (0.278, 1.5, 1.0),       # B 策略场景
        (0.5, 50.0, 100.0),      # 平衡
    ]
    for wr, aw, al in cases:
        size, reason = risk.calculate_kelly_size(
            win_rate=wr, avg_win=aw, avg_loss=al,
        )
        assert size >= 0, f"size {size} < 0 for WR={wr}, aw={aw}, al={al}"


# ──────────── 经典 Kelly 公式 ────────────

def test_kelly_classic_50_wr_b2_full(risk):
    """经典 Kelly 公式正确性: WR=50%, b=2 → f_full=0.25.
    用 small fractional=0.02 + equity=10000 避免触发 cap:
      → 0.25 × 0.02 × 10000 = 50 < hard_cap=100 不 cap."""
    equity = 10000.0
    size, reason = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=200.0, avg_loss=100.0,  # b=2
        current_equity=equity,
        current_atr_ratio=1.0,
        leverage=3,
        sl_distance_pct=0.005,
        fractional_kelly=0.02,  # 0.02 × 0.25 = 0.005 → 50 USD
    )
    # f_full = 0.25, frac 0.02 = 0.005, size = 0.005 × 10000 = 50
    assert size == pytest.approx(50.0, rel=1e-3)
    assert "kelly_0.02" in reason
    assert "capped" not in reason


def test_kelly_default_fractional_is_quarter(risk):
    """Fractional Kelly 默认 1/4: WR=50%, b=2 → 0.0625 × equity=625,
    被硬上限 cap 到 1% × equity=100 (Constitution §5)."""
    equity = 10000.0
    size, reason = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=200.0, avg_loss=100.0,  # b=2
        current_equity=equity,
        current_atr_ratio=1.0,
        leverage=3,
        sl_distance_pct=0.005,
        # default fractional_kelly = 0.25
    )
    # f_full = 0.25, frac 1/4 = 0.0625, size = 625 > 100 cap
    # → size = 100 (= max_loss_pct × equity = 1% × 10000)
    assert size == pytest.approx(equity * 0.01, rel=1e-3)
    assert "capped_at_max_loss_1.0pct" in reason
    # 大小写不敏感检查: cap 路径 reason 含 "Kelly_wants" 原始 Kelly 意图
    assert ("kelly" in reason.lower()) and ("capped" in reason.lower())


# ──────────── Negative EV (Kelly 精髓: 不赌坏赌局) ────────────

def test_kelly_negative_ev_b_strategy_btc_1h(risk):
    """B 策略 BTC 1h 5x 实测: WR=27.8%, b=1.5 → f_full = (0.278×1.5-0.722)/1.5 = -0.203
    Kelly 直接拒绝 → size=0."""
    size, reason = risk.calculate_kelly_size(
        win_rate=0.278, avg_win=1.5, avg_loss=1.0,  # b=1.5
        current_equity=10000.0,
        current_atr_ratio=1.0,
        leverage=3,
        sl_distance_pct=0.005,
    )
    # f_full = (0.278*1.5 - 0.722) / 1.5 = -0.203
    assert size == 0.0
    assert "negative_EV" in reason
    assert "kelly=-0.2034" in reason or "kelly=-0.20" in reason


def test_kelly_boundary_breakeven_returns_zero(risk):
    """Kelly 边界: f_full 恰好 = 0 → 返回 0 (期望为零 = 边缘拒绝)."""
    # 找 WR 使 f_full = 0: (p*b - (1-p))/b = 0  → p = 1/(b+1)
    # 选 b=2 → p = 1/3 ≈ 0.3333
    size, reason = risk.calculate_kelly_size(
        win_rate=1.0/3.0, avg_win=200.0, avg_loss=100.0,  # b=2, p=1/3
        current_equity=10000.0,
        current_atr_ratio=1.0,
        leverage=3,
        sl_distance_pct=0.005,
    )
    assert size == 0.0
    assert "negative_EV" in reason


def test_kelly_zero_win_rate_returns_zero(risk):
    """WR=0% 必为 negative EV → 拒绝."""
    size, reason = risk.calculate_kelly_size(
        win_rate=0.0, avg_win=100.0, avg_loss=50.0,
        current_equity=10000.0,
    )
    assert size == 0.0
    assert "negative_EV" in reason


# ──────────── Hard Cap (Constitution §5 不破) ────────────

def test_kelly_hard_cap_at_1pct(risk):
    """WR=80%, b=3 → Kelly f_full = (0.8*3-0.2)/3 = 0.733 → fractional 1/4 = 0.183
    0.183 × equity = 大于 1% 本金硬上限 → cap 到 1%."""
    equity = 10000.0
    size, reason = risk.calculate_kelly_size(
        win_rate=0.8, avg_win=300.0, avg_loss=100.0,  # b=3, WR=80%
        current_equity=equity,
        current_atr_ratio=1.0,
        leverage=3,
        sl_distance_pct=0.005,
    )
    # f_full = 0.733, fractional 1/4 = 0.183
    # 0.183 × 10000 = 1833 > 100 (1% 本金硬上限)
    # → size = 100 (= max_loss_pct × equity = 1% × 10000)
    assert size == pytest.approx(equity * 0.01, rel=1e-3)
    assert "capped" in reason
    assert "max_loss_1.0pct" in reason


def test_kelly_no_cap_below_threshold(risk):
    """WR=60%, b=2 → f_full = (0.6*2-0.4)/2 = 0.4, fractional=0.1
    0.1 × equity = 4% > 1%? 不, 等等: 0.1 × 10000 = 1000, 这 > 100 (1%) → 也 cap.
    重新选: WR=30%, b=2 → f_full=0.2, frac=1/4=0.05, 0.05*10000=500 > 100 → cap.
    实际不超 cap: WR=15%, b=1.5 → f_full=(0.15*1.5-0.85)/1.5=-0.417 → negative.
    极限例子: WR=10% + b=10 → f_full=(1-0.9)/10=0.01, frac=0.0025, size=25 < 100 → 不 cap."""
    equity = 10000.0
    size, reason = risk.calculate_kelly_size(
        win_rate=0.10, avg_win=1000.0, avg_loss=100.0,  # b=10, WR=10%
        current_equity=equity,
        current_atr_ratio=1.0,
        leverage=3,
        sl_distance_pct=0.005,
    )
    # f_full = 0.01, fractional 1/4 = 0.0025
    # size = 0.0025 × 10000 = 25 < 100 (1% × 10000)
    assert size == pytest.approx(25.0, rel=1e-3)
    assert "capped" not in reason


def test_kelly_never_violates_1pct_cap(risk):
    """遍历各种参数, size 永远不超过 1% 本金硬上限."""
    equity = 10000.0
    hard_cap = equity * 0.01
    # 大量样本
    for wr in [0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
        for b in [0.5, 1.0, 2.0, 5.0, 10.0]:
            if wr * b - (1 - wr) <= 0:
                continue  # 跳过 negative
            size, _ = risk.calculate_kelly_size(
                win_rate=wr, avg_win=b * 100, avg_loss=100.0,
                current_equity=equity,
                current_atr_ratio=1.0,
                leverage=3,
                sl_distance_pct=0.005,
            )
            assert size <= hard_cap, (
                f"WR={wr}, b={b}: size={size} > hard_cap={hard_cap}"
            )


# ──────────── 波动率缩仓 ────────────

def test_kelly_high_volatility_dampen_by_07(risk):
    """atr_ratio=2.0 ≥ 1.5 阈值 → × 0.7 缩仓.
    用 small frac + equity=10000 验证缩仓比例 (避免 cap 干扰)."""
    equity = 10000.0
    # 不缩仓基线 (frac=0.02 避免 cap → size=50)
    size_norm, reason_norm = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=200.0, avg_loss=100.0,  # b=2, WR=50%
        current_equity=equity, current_atr_ratio=1.0,
        leverage=3, sl_distance_pct=0.005,
        fractional_kelly=0.02,
    )
    # 高波动 (atr=2.0, 应缩仓 × 0.7)
    size_vol, reason_vol = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=200.0, avg_loss=100.0,
        current_equity=equity, current_atr_ratio=2.0,
        leverage=3, sl_distance_pct=0.005,
        fractional_kelly=0.02,
    )
    assert size_norm == pytest.approx(50.0, rel=1e-3)
    assert size_vol == pytest.approx(size_norm * 0.7, rel=1e-3)  # 35
    assert "high_vol_2.00x_dampen_0.70" in reason_vol
    assert "high_vol" not in reason_norm


def test_kelly_no_dampen_below_threshold(risk):
    """atr_ratio=1.4 < 1.5 阈值 → 不缩仓."""
    equity = 10000.0
    size_low, reason_low = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=200.0, avg_loss=100.0,
        current_equity=equity, current_atr_ratio=1.4,
        leverage=3, sl_distance_pct=0.005,
    )
    size_1, reason_1 = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=200.0, avg_loss=100.0,
        current_equity=equity, current_atr_ratio=1.0,
        leverage=3, sl_distance_pct=0.005,
    )
    assert size_low == pytest.approx(size_1, rel=1e-3)
    assert "high_vol" not in reason_low


def test_kelly_volatility_threshold_boundary(risk):
    """atr_ratio 恰好 1.5 → 应该 trigger dampen (>= 条件)."""
    size, reason = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=200.0, avg_loss=100.0,
        current_equity=10000.0, current_atr_ratio=1.5,
        leverage=3, sl_distance_pct=0.005,
    )
    assert "high_vol_1.50x_dampen_0.70" in reason


# ──────────── 数据不足 fallback ────────────

def test_kelly_no_loss_history_fallback_to_hard_cap(risk):
    """avg_loss=0 → no_loss_history fallback → 返回 1% 本金硬上限."""
    equity = 10000.0
    size, reason = risk.calculate_kelly_size(
        win_rate=1.0, avg_win=100.0, avg_loss=0.0,  # 无任何亏损历史
        current_equity=equity,
        current_atr_ratio=1.0,
        leverage=3,
        sl_distance_pct=0.005,
    )
    assert size == pytest.approx(equity * 0.01, rel=1e-3)
    assert "no_loss_history_fallback_to_hard_cap_1pct" in reason


def test_kelly_volatility_dampen_does_not_affect_fallback(risk):
    """fallback 路径不应用波动率缩仓."""
    equity = 10000.0
    size_vol, reason_vol = risk.calculate_kelly_size(
        win_rate=1.0, avg_win=100.0, avg_loss=0.0,
        current_equity=equity, current_atr_ratio=5.0,
        leverage=3, sl_distance_pct=0.005,
    )
    size_norm, reason_norm = risk.calculate_kelly_size(
        win_rate=1.0, avg_win=100.0, avg_loss=0.0,
        current_equity=equity, current_atr_ratio=1.0,
        leverage=3, sl_distance_pct=0.005,
    )
    assert size_vol == size_norm
    assert "no_loss_history_fallback" in reason_vol


# ──────────── 入参校验 ────────────

@pytest.mark.parametrize("invalid_wr", [-0.1, 1.01, 2.0, -0.5])
def test_kelly_invalid_win_rate_returns_zero(risk, invalid_wr):
    """win_rate 不在 [0, 1] 范围 → 返回 (0, reason)."""
    size, reason = risk.calculate_kelly_size(
        win_rate=invalid_wr, avg_win=100.0, avg_loss=50.0,
        current_equity=10000.0,
    )
    assert size == 0.0
    assert "invalid_win_rate" in reason


@pytest.mark.parametrize("invalid_aw", [-100.0, -0.01])
def test_kelly_invalid_negative_avg_win_returns_zero(risk, invalid_aw):
    """avg_win < 0 → 返回 0."""
    size, reason = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=invalid_aw, avg_loss=50.0,
        current_equity=10000.0,
    )
    assert size == 0.0
    assert "invalid_avg_win_or_loss_negative" in reason


def test_kelly_invalid_negative_avg_loss_returns_zero(risk):
    """avg_loss < 0 → 返回 0."""
    size, reason = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=100.0, avg_loss=-10.0,
        current_equity=10000.0,
    )
    assert size == 0.0
    assert "invalid_avg_win_or_loss_negative" in reason


def test_kelly_invalid_equity_zero(risk):
    """equity = 0 → 返回 0 (分母保护)."""
    size, reason = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=100.0, avg_loss=50.0,
        current_equity=0.0,
    )
    assert size == 0.0
    assert "invalid_equity" in reason


def test_kelly_invalid_leverage_zero(risk):
    """leverage < 1 → 返回 0."""
    size, reason = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=100.0, avg_loss=50.0,
        current_equity=10000.0,
        leverage=0,
    )
    assert size == 0.0
    assert "invalid_leverage" in reason


def test_kelly_invalid_fractional_out_of_range(risk):
    """fractional_kelly 不在 (0, 1] → 返回 0."""
    size, reason = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=100.0, avg_loss=50.0,
        current_equity=10000.0,
        fractional_kelly=0.0,
    )
    assert size == 0.0
    assert "invalid_fractional_kelly" in reason


# ──────────── 不变量 ────────────

def test_kelly_does_not_depend_on_leverage(risk):
    """size_usd 是美元金额, 与杠杆解耦 (Kelly 是 sizing 工具, leverage 另算)."""
    equity = 10000.0
    size_3x, _ = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=200.0, avg_loss=100.0,
        current_equity=equity, leverage=3,
    )
    size_10x, _ = risk.calculate_kelly_size(
        win_rate=0.5, avg_win=200.0, avg_loss=100.0,
        current_equity=equity, leverage=10,
    )
    assert size_3x == size_10x


def test_kelly_reason_always_non_empty(risk):
    """reason 永远是非空字符串 (供 logging)."""
    # 各种输入
    cases = [
        (0.5, 200.0, 100.0),     # 正常
        (0.278, 1.5, 1.0),       # negative
        (1.0, 100.0, 0.0),       # fallback
        (-0.1, 100.0, 50.0),     # invalid
    ]
    for wr, aw, al in cases:
        _, reason = risk.calculate_kelly_size(
            win_rate=wr, avg_win=aw, avg_loss=al,
            current_equity=10000.0,
        )
        assert isinstance(reason, str)
        assert len(reason) > 0


def test_kelly_uses_config_max_loss_pct(risk):
    """Kelly 必须读取 config.max_loss_percent_per_trade (Constitution §5)."""
    # 默认 cfg.max_loss_percent_per_trade = 1.0
    assert risk._config.max_loss_percent_per_trade == 1.0
    # 用一个高 WR + 高 b 的 case
    equity = 10000.0
    size, reason = risk.calculate_kelly_size(
        win_rate=0.95, avg_win=500.0, avg_loss=100.0,  # b=5, WR=95%
        current_equity=equity,
        current_atr_ratio=1.0,
        leverage=3,
        sl_distance_pct=0.005,
    )
    # f_full = (0.95*5 - 0.05) / 5 = 0.94
    # frac 1/4 = 0.235
    # size = 0.235 × 10000 = 2350 > 100 (1% × 10000) → cap 到 100
    assert size == pytest.approx(equity * 0.01, rel=1e-3)
    assert "max_loss_1.0pct" in reason  # 来自 config
