# -*- coding: utf-8 -*-
"""
Constitution §3：跨策略冲突过滤（A↔B 趋势 vs 反转）单元测试

覆盖：
- 规则 1：方向冲突（同 symbol 反向策略 → 保留 confidence 高的）
- 规则 2：强趋势 → 屏蔽 B（mean_reversion）
- 规则 3：窄幅震荡 → 屏蔽 A（trend_follow）
- 边界：C / D 不参与冲突
- 边界：None / 空列表 / 时间窗口外 / 同方向
"""

from datetime import datetime, timedelta, timezone

import pytest

from okx.code.risk import RiskCalculator


# ─────────────────────────────────────────────────────────────
# 测试用 Signal mock（避免循环 import signal.py）
# ─────────────────────────────────────────────────────────────


def make_signal(
    strategy: str,
    direction: str,
    confidence: float = 0.6,
    kline_time: str = None,
    symbol: str = "BTC-USDT-SWAP",
):
    """构造一个轻量级 Signal-like 对象（duck typing）。"""
    class _S:
        pass
    s = _S()
    s.strategy = strategy
    s.symbol = symbol
    s.direction = direction
    s.confidence = confidence
    s.entry_price = 50000.0
    s.sl_price = 49500.0
    s.tp_price = 51000.0
    s.leverage = 5
    s.size = 0.0
    s.reason = "test"
    s.kline_time = kline_time or "2026-07-18T12:00:00Z"
    return s


@pytest.fixture
def risk(cfg):
    from okx.code.risk import RiskCalculator
    return RiskCalculator(cfg)


# ─────────────────────────────────────────────────────────────
# 规则 1：方向冲突
# ─────────────────────────────────────────────────────────────


class TestRule1DirectionConflict:
    """规则 1：同 symbol 反向策略冲突 → 保留 confidence 高的"""

    def test_a_long_vs_b_short_new_higher_conf_kept(self, risk):
        """A 做多 conf=0.8 vs B 做空 conf=0.6，新信号 conf 更高 → 仍拒绝新信号（避免多空互弒）"""
        prev = make_signal("BB_RSI_REVERSION", "short", confidence=0.6)
        new = make_signal("EMA20_BREAKOUT", "long", confidence=0.8)
        result = risk.check_strategy_conflict(new, [prev])
        # 旧信号已下单，新信号一律拒绝（冲突避免）→ message 含 "拒绝新信号"
        assert result is not None
        assert "规则 1" in result
        assert "拒绝新信号" in result
        assert "新信号 conf 更高" in result

    def test_a_long_vs_b_short_new_lower_conf_dropped(self, risk):
        """A 做多 conf=0.5 vs B 做空 conf=0.7，新信号 conf 更低 → 拒绝新信号"""
        prev = make_signal("BB_RSI_REVERSION", "short", confidence=0.7)
        new = make_signal("EMA20_BREAKOUT", "long", confidence=0.5)
        result = risk.check_strategy_conflict(new, [prev])
        assert result is not None
        assert "规则 1" in result
        assert "拒绝新信号" in result
        assert "新信号 conf 不占优" in result

    def test_a_long_vs_b_short_equal_conf_dropped(self, risk):
        """A 与 B conf 相等 → 仍拒绝新信号（避免多空互弒）"""
        prev = make_signal("BB_RSI_REVERSION", "short", confidence=0.6)
        new = make_signal("EMA20_BREAKOUT", "long", confidence=0.6)
        result = risk.check_strategy_conflict(new, [prev])
        assert result is not None
        assert "规则 1" in result
        assert "拒绝新信号" in result

    def test_a_short_vs_b_long_conflict(self, risk):
        """A 做空 vs B 做多 → 同样触发冲突"""
        prev = make_signal("EMA20_BREAKOUT", "short", confidence=0.7)
        new = make_signal("BB_RSI_REVERSION", "long", confidence=0.6)
        result = risk.check_strategy_conflict(new, [prev])
        assert result is not None
        assert "规则 1" in result

    def test_a_long_vs_a_long_same_regime_no_conflict(self, risk):
        """同 regime (A vs A) 不算冲突"""
        prev = make_signal("EMA20_BREAKOUT", "short", confidence=0.7)
        new = make_signal("EMA20_BREAKOUT", "long", confidence=0.6)
        result = risk.check_strategy_conflict(new, [prev])
        assert result is None

    def test_b_short_vs_b_long_same_regime_no_conflict(self, risk):
        """同 regime (B vs B) 不算冲突"""
        prev = make_signal("BB_RSI_REVERSION", "long", confidence=0.7)
        new = make_signal("BB_RSI_REVERSION", "short", confidence=0.6)
        result = risk.check_strategy_conflict(new, [prev])
        assert result is None

    def test_a_long_vs_b_long_same_direction_no_conflict(self, risk):
        """不同 regime 但同方向 → 不冲突"""
        prev = make_signal("BB_RSI_REVERSION", "long", confidence=0.7)
        new = make_signal("EMA20_BREAKOUT", "long", confidence=0.6)
        result = risk.check_strategy_conflict(new, [prev])
        assert result is None

    def test_time_window_outside_no_conflict(self, risk):
        """时间窗口外（>60 min）不冲突"""
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
        prev = make_signal("BB_RSI_REVERSION", "short", confidence=0.7, kline_time=old_time)
        new = make_signal("EMA20_BREAKOUT", "long", confidence=0.6)
        result = risk.check_strategy_conflict(new, [prev])
        assert result is None

    def test_time_window_inside_conflict(self, risk):
        """时间窗口内（30 min）冲突"""
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        prev = make_signal("BB_RSI_REVERSION", "short", confidence=0.7, kline_time=recent_time)
        new = make_signal("EMA20_BREAKOUT", "long", confidence=0.6, kline_time=now_time)
        result = risk.check_strategy_conflict(new, [prev])
        assert result is not None
        assert "规则 1" in result


# ─────────────────────────────────────────────────────────────
# 规则 2：强趋势 → 屏蔽 B
# ─────────────────────────────────────────────────────────────


class TestRule2TrendHighBlocksB:
    """规则 2：atr_ratio ≥ 1.5 → 屏蔽 mean_reversion (B)"""

    def test_high_atr_blocks_b_short(self, risk):
        new = make_signal("BB_RSI_REVERSION", "short")
        result = risk.check_strategy_conflict(new, [], atr_ratio=1.8)
        assert result is not None
        assert "规则 2" in result
        assert "强趋势" in result

    def test_high_atr_blocks_b_long(self, risk):
        new = make_signal("BB_RSI_REVERSION", "long")
        result = risk.check_strategy_conflict(new, [], atr_ratio=2.0)
        assert result is not None
        assert "规则 2" in result

    def test_high_atr_does_not_block_a(self, risk):
        """强趋势时 A (trend_follow) 不应被屏蔽"""
        new = make_signal("EMA20_BREAKOUT", "long")
        result = risk.check_strategy_conflict(new, [], atr_ratio=1.8)
        assert result is None

    def test_high_atr_does_not_block_c(self, risk):
        """C 策略不受 ATR 屏蔽（独立判定）"""
        new = make_signal("VOLATILITY_BREAKOUT", "long")
        result = risk.check_strategy_conflict(new, [], atr_ratio=2.5)
        assert result is None

    def test_high_atr_does_not_block_d(self, risk):
        """D 策略不受 ATR 屏蔽（独立判定）"""
        new = make_signal("FUNDING_RATE_REVERSAL", "short")
        result = risk.check_strategy_conflict(new, [], atr_ratio=2.5)
        assert result is None

    def test_atr_ratio_at_threshold_blocks_b(self, risk):
        """边界值 1.5（包含）触发屏蔽"""
        new = make_signal("BB_RSI_REVERSION", "long")
        result = risk.check_strategy_conflict(new, [], atr_ratio=1.5)
        assert result is not None
        assert "规则 2" in result


# ─────────────────────────────────────────────────────────────
# 规则 3：窄幅震荡 → 屏蔽 A
# ─────────────────────────────────────────────────────────────


class TestRule3TrendLowBlocksA:
    """规则 3：atr_ratio ≤ 0.7 → 屏蔽 trend_follow (A)"""

    def test_low_atr_blocks_a_long(self, risk):
        new = make_signal("EMA20_BREAKOUT", "long")
        result = risk.check_strategy_conflict(new, [], atr_ratio=0.5)
        assert result is not None
        assert "规则 3" in result
        assert "窄幅震荡" in result

    def test_low_atr_blocks_a_short(self, risk):
        new = make_signal("EMA20_BREAKOUT", "short")
        result = risk.check_strategy_conflict(new, [], atr_ratio=0.6)
        assert result is not None
        assert "规则 3" in result

    def test_low_atr_does_not_block_b(self, risk):
        """窄幅震荡时 B (mean_reversion) 不应被屏蔽（B 主场）"""
        new = make_signal("BB_RSI_REVERSION", "short")
        result = risk.check_strategy_conflict(new, [], atr_ratio=0.5)
        assert result is None

    def test_low_atr_does_not_block_c(self, risk):
        """C 策略不受窄幅屏蔽（C 是 BBW 收缩触发，本来就是窄幅信号）"""
        new = make_signal("VOLATILITY_BREAKOUT", "long")
        result = risk.check_strategy_conflict(new, [], atr_ratio=0.5)
        assert result is None

    def test_atr_ratio_at_threshold_blocks_a(self, risk):
        """边界值 0.7（包含）触发屏蔽"""
        new = make_signal("EMA20_BREAKOUT", "long")
        result = risk.check_strategy_conflict(new, [], atr_ratio=0.7)
        assert result is not None
        assert "规则 3" in result


# ─────────────────────────────────────────────────────────────
# 中性区间：atr_ratio 在 (0.7, 1.5) → A 和 B 都不屏蔽
# ─────────────────────────────────────────────────────────────


class TestNeutralAtrRatio:
    """中性 ATR ratio (0.7, 1.5) → A 和 B 都不被规则 2/3 屏蔽"""

    def test_neutral_atr_a_pass(self, risk):
        new = make_signal("EMA20_BREAKOUT", "long")
        result = risk.check_strategy_conflict(new, [], atr_ratio=1.0)
        assert result is None

    def test_neutral_atr_b_pass(self, risk):
        new = make_signal("BB_RSI_REVERSION", "short")
        result = risk.check_strategy_conflict(new, [], atr_ratio=1.0)
        assert result is None


# ─────────────────────────────────────────────────────────────
# 边界 & 防御
# ─────────────────────────────────────────────────────────────


class TestEdgeCases:
    """边界条件"""

    def test_none_signal_returns_none(self, risk):
        """new_signal = None → 直接返回 None"""
        result = risk.check_strategy_conflict(None, [], atr_ratio=2.0)
        assert result is None

    def test_empty_recent_signals_returns_none(self, risk):
        """recent_signals 空 → 无规则 1 冲突"""
        new = make_signal("EMA20_BREAKOUT", "long")
        result = risk.check_strategy_conflict(new, [], atr_ratio=1.0)
        assert result is None

    def test_unknown_strategy_in_recent_signals_ignored(self, risk):
        """recent_signals 中有 unknown strategy → 跳过不报错"""
        prev = make_signal("UNKNOWN_STRATEGY", "short", confidence=0.7)
        new = make_signal("EMA20_BREAKOUT", "long")
        result = risk.check_strategy_conflict(new, [prev])
        assert result is None

    def test_none_entries_in_recent_skipped(self, risk):
        """recent_signals 中有 None → 跳过"""
        new = make_signal("EMA20_BREAKOUT", "long")
        result = risk.check_strategy_conflict(new, [None])
        assert result is None

    def test_unknown_strategy_in_new_signal_only_check1(self, risk):
        """new_signal 是 C/D 时：规则 1 不参与（按实现逻辑直接 return None）"""
        new = make_signal("VOLATILITY_BREAKOUT", "long")
        prev = make_signal("EMA20_BREAKOUT", "short", confidence=0.7)
        result = risk.check_strategy_conflict(new, [prev], atr_ratio=1.0)
        assert result is None

    def test_atr_ratio_none_skips_rules_2_3(self, risk):
        """atr_ratio = None → 规则 2/3 不触发，仅规则 1 生效"""
        new = make_signal("BB_RSI_REVERSION", "short")
        result = risk.check_strategy_conflict(new, [], atr_ratio=None)
        assert result is None

    def test_invalid_kline_time_skipped_for_conflict(self, risk):
        """kline_time 解析失败 → 不参与规则 1 时间窗口比较（按 None 处理）"""
        prev = make_signal("EMA20_BREAKOUT", "short", confidence=0.7, kline_time="not-a-date")
        new = make_signal("BB_RSI_REVERSION", "long")
        result = risk.check_strategy_conflict(new, [prev])
        # new_ts 解析失败 → 不进入时间窗口过滤 → 规则 1 触发
        assert result is not None
        assert "规则 1" in result

    def test_custom_threshold_overrides(self, risk):
        """自定义阈值覆盖默认值"""
        new = make_signal("BB_RSI_REVERSION", "short")
        # 默认 1.5 才屏蔽 B；自定义 1.1 触发屏蔽
        result_default = risk.check_strategy_conflict(new, [], atr_ratio=1.2)
        assert result_default is None
        result_custom = risk.check_strategy_conflict(new, [], atr_ratio=1.2, trend_high_ratio=1.1)
        assert result_custom is not None
        assert "规则 2" in result_custom


# ─────────────────────────────────────────────────────────────
# 多 recent_signals 场景
# ─────────────────────────────────────────────────────────────


class TestMultipleRecentSignals:
    """多个 recent_signals 时取第一个命中的冲突"""

    def test_first_match_used(self, risk):
        """recent_signals 中第一个冲突被报告"""
        old_b = make_signal("BB_RSI_REVERSION", "short", confidence=0.5)
        recent_b = make_signal("BB_RSI_REVERSION", "short", confidence=0.9)  # 高 conf
        new_a = make_signal("EMA20_BREAKOUT", "long", confidence=0.6)

        result = risk.check_strategy_conflict(new_a, [old_b, recent_b])
        # 第一个匹配 (old_b) → old_b.conf=0.5 < new_a.conf=0.6 → 新信号 conf 更高
        assert result is not None
        assert "拒绝新信号" in result  # 避免多空互弒

    def test_c_d_in_recent_signals_ignored(self, risk):
        """recent_signals 中有 C/D → 不参与冲突比较"""
        prev_c = make_signal("VOLATILITY_BREAKOUT", "short", confidence=0.7)
        prev_d = make_signal("FUNDING_RATE_REVERSAL", "long", confidence=0.7)
        new = make_signal("EMA20_BREAKOUT", "long", confidence=0.6)
        result = risk.check_strategy_conflict(new, [prev_c, prev_d])
        # C/D 被忽略 → 无规则 1 冲突
        assert result is None