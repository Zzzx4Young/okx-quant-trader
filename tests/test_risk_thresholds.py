# -*- coding: utf-8 -*-
"""
risk_thresholds.py 单元测试

覆盖：
- RiskThreshold dataclass（frozen 不可变）
- RISK_THRESHOLDS 全键名存在
- get_threshold 抛错
- PositionRisk 属性（is_long / liq_distance_pct / sl_consumed_pct）
- PositionRisk.__post_init__ 计算 notional / upl_pct_of_margin
"""

import sys
from pathlib import Path

# 让 pytest 找到 okx 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from okx.scripts.risk_thresholds import (
    RISK_THRESHOLDS,
    PositionRisk,
    RiskIssue,
    RiskMetrics,
    RiskThreshold,
    get_threshold,
)


# ──────────── RiskThreshold ────────────


class TestRiskThreshold:
    def test_required_keys_present(self):
        """所有 8 个核心阈值必须存在"""
        required = [
            "gross_leverage",
            "net_leverage",
            "upl_pct",
            "inst_concentration",
            "strategy_concentration",
            "liq_proximity_pct",
            "sl_consumed_pct",
            "min_equity_buffer",
        ]
        for k in required:
            assert k in RISK_THRESHOLDS, f"缺失阈值: {k}"

    def test_threshold_direction_valid(self):
        """所有阈值的 direction 必须是 'high' 或 'low'"""
        for name, t in RISK_THRESHOLDS.items():
            assert t.direction in ("high", "low"), f"{name}: direction={t.direction}"

    def test_threshold_warn_vs_crit(self):
        """high 方向：warn < crit；low 方向：warn > crit"""
        for name, t in RISK_THRESHOLDS.items():
            if t.direction == "high":
                assert t.warn < t.crit, f"{name}: high 方向 warn({t.warn}) 应 < crit({t.crit})"
            else:  # low
                assert t.warn > t.crit, f"{name}: low 方向 warn({t.warn}) 应 > crit({t.crit})"

    def test_threshold_frozen(self):
        """RiskThreshold 是 frozen，不允许修改"""
        t = get_threshold("gross_leverage")
        with pytest.raises(Exception):  # FrozenInstanceError
            t.warn = 999.0  # type: ignore

    def test_get_threshold_unknown_raises(self):
        """未知 key 必须抛 KeyError（fail loud）"""
        with pytest.raises(KeyError) as exc_info:
            get_threshold("nonexistent_metric")
        assert "未知风险指标" in str(exc_info.value)


# ──────────── PositionRisk 属性 ────────────


def _make_position(**overrides) -> PositionRisk:
    """构造默认测试仓位"""
    defaults = dict(
        inst_id="BTC-USDT-SWAP",
        pos_side="long",
        size=10.0,
        ct_val=0.01,
        avg_px=60000.0,
        mark_px=61000.0,
        upl=100.0,
        margin=6000.0,
        liq_px=55000.0,
        leverage=10.0,
        strategy="A_EMABREAKOUT",
    )
    defaults.update(overrides)
    return PositionRisk(**defaults)


class TestPositionRiskPostInit:
    def test_notional_computed(self):
        """notional_usd = |size| * ct_val * mark_px"""
        p = _make_position(size=10.0, ct_val=0.01, mark_px=61000.0)
        # 10 * 0.01 * 61000 = 6100
        assert p.notional_usd == pytest.approx(6100.0)

    def test_notional_uses_abs_size(self):
        """空仓（size 为负）的 notional 也应为正"""
        p = _make_position(size=-10.0)
        assert p.notional_usd == pytest.approx(6100.0)

    def test_upl_pct_of_margin(self):
        p = _make_position(upl=100.0, margin=6000.0)
        assert p.upl_pct_of_margin == pytest.approx(100.0 / 6000.0)

    def test_upl_pct_zero_margin(self):
        p = _make_position(upl=100.0, margin=0.0)
        assert p.upl_pct_of_margin == 0.0


class TestPositionRiskProperties:
    def test_is_long_true(self):
        p = _make_position(pos_side="long", size=10.0)
        assert p.is_long is True

    def test_is_long_false_short(self):
        p = _make_position(pos_side="short", size=10.0)
        assert p.is_long is False

    def test_is_long_net_positive(self):
        p = _make_position(pos_side="net", size=10.0)
        assert p.is_long is True

    def test_is_long_net_negative(self):
        p = _make_position(pos_side="net", size=-10.0)
        assert p.is_long is False

    def test_liq_distance_pct_long(self):
        """mark=61000, liq=55000 → 距离 9.84%"""
        p = _make_position(mark_px=61000.0, liq_px=55000.0)
        expected = abs(61000 - 55000) / 61000
        assert p.liq_distance_pct == pytest.approx(expected)

    def test_liq_distance_pct_none(self):
        p = _make_position(liq_px=None)
        assert p.liq_distance_pct is None

    def test_liq_distance_pct_zero_liq(self):
        """liq_px=0 应返回 None（无法计算）"""
        p = _make_position(liq_px=0.0)
        assert p.liq_distance_pct is None

    def test_sl_consumed_pct_basic(self):
        """avg=60000, sl=58000, mark=59500 → 已走 50%（long 方向往 SL 走）"""
        p = _make_position(avg_px=60000.0, mark_px=59500.0, sl_px=58000.0)
        # |59500-60000| / |58000-60000| = 500/2000 = 0.25
        assert p.sl_consumed_pct == pytest.approx(0.25)

    def test_sl_consumed_pct_no_sl(self):
        p = _make_position(sl_px=None)
        assert p.sl_consumed_pct is None

    def test_sl_consumed_pct_clamped_to_1(self):
        """mark 超过 SL 时（已触发），clamp 到 1.0"""
        p = _make_position(avg_px=60000.0, mark_px=57000.0, sl_px=58000.0)
        # 已超过 SL（往不利方向），应 clamp 到 1.0
        assert p.sl_consumed_pct == pytest.approx(1.0)

    def test_sl_consumed_pct_zero_distance(self):
        """avg == sl（不可能但边界）→ None"""
        p = _make_position(avg_px=60000.0, sl_px=60000.0)
        assert p.sl_consumed_pct is None


# ──────────── RiskMetrics 默认值 ────────────


class TestRiskMetricsDefaults:
    def test_zero_position_safe_defaults(self):
        """无持仓时所有指标应安全默认（不会误报）"""
        m = RiskMetrics()
        assert m.gross_leverage == 0.0
        assert m.upl_pct == 0.0
        assert m.equity_buffer_pct == 1.0  # 默认无持仓 = 100% 缓冲
        assert m.min_liq_distance_pct == 1.0  # 默认无强平风险
        assert m.position_count == 0
