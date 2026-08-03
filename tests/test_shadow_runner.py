# -*- coding: utf-8 -*-
"""
L4 Shadow Runner 单元测试 (Week 1 MVP)

设计意图：signal 层 backtest vs live divergence 检测。
8 tests 覆盖：
- 零 divergence（identical input）
- direction mismatch
- slippage diff
- both empty (acceptable)
- high divergence → alert
- cross-symbol not confused
- reporter console mode
- reporter json mode

RED: 这些测试假设 code/shadow/comparator.py + reporter.py 已实现。
当前不存在 → 全部失败 (真 RED)。
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from okx.code.signal import Signal


def make_signal(
    *,
    strategy: str = "EMA20_BREAKOUT",
    symbol: str = "BTC-USDT-SWAP",
    direction: str = "long",
    entry_price: float = 50000.0,
    sl_price: float = 49500.0,
    tp_price: float = 51000.0,
    confidence: float = 0.7,
    kline_time: str = "2026-08-03T12:00:00Z",
    leverage: int = 3,
    size: float = 0.0,
) -> Signal:
    """工厂函数：构造 Signal 对象（重复使用避免每个 test 写 boilerplate）。"""
    return Signal(
        strategy=strategy,
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        sl_price=sl_price,
        tp_price=tp_price,
        leverage=leverage,
        size=size,
        confidence=confidence,
        reason="test",
        kline_time=kline_time,
    )


class TestCompareSignals:
    """code/shadow/comparator.py::compare_signals 测试。"""

    def test_identical_signals_yield_zero_divergence(self):
        """相同 input → divergence_score == 0 (RED)."""
        from okx.code.shadow.comparator import compare_signals

        sig = make_signal()
        result = compare_signals(expected=[sig], actual=[sig])

        assert result.direction_match is True
        assert result.sl_diff_bps == pytest.approx(0.0, abs=1e-9)
        assert result.tp_diff_bps == pytest.approx(0.0, abs=1e-9)
        assert result.divergence_score == pytest.approx(0.0, abs=1e-9)
        assert result.alert_level == "ok"

    def test_direction_mismatch_raises_divergence(self):
        """方向不同 (long vs short) → divergence_score > 0 + alert_level 非 ok."""
        from okx.code.shadow.comparator import compare_signals

        expected = make_signal(direction="long")
        actual = make_signal(direction="short")
        result = compare_signals(expected=[expected], actual=[actual])

        assert result.direction_match is False
        assert result.divergence_score > 0
        assert result.alert_level in ("warn", "alert")

    def test_slippage_diff_reported_in_bps(self):
        """SL 差 5bps → sl_diff_bps ≈ 5."""
        from okx.code.shadow.comparator import compare_signals

        expected = make_signal(entry_price=50000.0, sl_price=49500.0)  # 1% SL
        actual = make_signal(entry_price=50000.0, sl_price=49475.0)    # 1.05% SL (差 ~5bps)
        result = compare_signals(expected=[expected], actual=[actual])

        assert result.sl_diff_bps == pytest.approx(5.0, abs=1.0)
        assert result.divergence_score > 0

    def test_both_empty_lists_acceptable(self):
        """两组都空 → divergence_score == 0 (acceptable · 两 regime 都拒入场)."""
        from okx.code.shadow.comparator import compare_signals

        result = compare_signals(expected=[], actual=[])

        assert result.divergence_score == 0.0
        assert result.alert_level == "ok"
        # notes 应能反映 "no_signals" 或 "empty" 任一关键词（修正 list/string 操作符 precedence bug）
        notes_text = " ".join(result.notes).lower()
        assert "empty" in notes_text or "no_signals" in notes_text

    def test_high_divergence_triggers_alert(self):
        """divergence > 15% → alert_level == 'alert'."""
        from okx.code.shadow.comparator import compare_signals

        # SL 差 20% (10000bps) → divergence 远超 15% 阈值
        expected = make_signal(entry_price=50000.0, sl_price=40000.0)  # 20% SL
        actual = make_signal(entry_price=50000.0, sl_price=49999.0)    # 0.002% SL
        result = compare_signals(expected=[expected], actual=[actual])

        assert result.divergence_score > 0.15
        assert result.alert_level == "alert"

    def test_cross_symbol_not_confused(self):
        """comparator 不应跨 symbol 混淆 (BTC 信号和 ETH 信号不比较)."""
        from okx.code.shadow.comparator import compare_signals

        btc_sig = make_signal(symbol="BTC-USDT-SWAP")
        eth_sig = make_signal(symbol="ETH-USDT-SWAP")
        # expected 是 BTC, actual 是 ETH → 应报 cross_symbol_mismatch 或高 divergence
        result = compare_signals(expected=[btc_sig], actual=[eth_sig])

        assert result.divergence_score > 0
        # 备注应包含 symbol mismatch 信息
        notes_text = " ".join(result.notes).lower()
        assert "symbol" in notes_text or "btc" in notes_text or "eth" in notes_text


class TestMultiSignalCase:
    """P0 · Bug #1 · comparator 静默忽略额外 signals.

    Bug: expected=[sig1, sig2], actual=[sig1] → 当前只比对 [0]，忽略第二对。
    Expected: divergence_score > 0 + alert_level != ok。
    """

    def test_multi_signal_missing_should_diverge(self):
        """expected=[sig1, sig2], actual=[sig1] → 第二轮 missing 应被捕获."""
        from okx.code.shadow.comparator import compare_signals

        sig1 = make_signal(direction="long", kline_time="2026-08-03T12:00:00Z")
        sig2 = make_signal(direction="short", kline_time="2026-08-03T13:00:00Z")
        result = compare_signals(expected=[sig1, sig2], actual=[sig1])

        # 当前 bug: 第二轮 missing 被忽略 → score=0
        # 修复后: 应 > 0
        assert result.divergence_score > 0, (
            f"Multi-signal missing should diverge, got score={result.divergence_score}"
        )
        notes_text = " ".join(result.notes).lower()
        assert "missing" in notes_text or "count" in notes_text, (
            f"Notes should mention missing signals, got: {result.notes}"
        )

    def test_multi_signal_extra_should_diverge(self):
        """expected=[sig1], actual=[sig1, sig2] → expected 缺第二对应触发 alert."""
        from okx.code.shadow.comparator import compare_signals

        sig1 = make_signal(direction="long")
        sig2 = make_signal(direction="short", kline_time="2026-08-03T13:00:00Z")
        result = compare_signals(expected=[sig1], actual=[sig1, sig2])

        assert result.divergence_score > 0
        notes_text = " ".join(result.notes).lower()
        assert "missing" in notes_text or "count" in notes_text


class TestLeverageAndSizeComparison:
    """P0 · Bug #3 · leverage 和 size 字段未比对."""

    def test_leverage_difference_should_diverge(self):
        """expected.leverage=3, actual.leverage=5 → 应触发 divergence."""
        from okx.code.shadow.comparator import compare_signals

        expected = make_signal(leverage=3)
        actual = make_signal(leverage=5)
        result = compare_signals(expected=[expected], actual=[actual])

        assert result.divergence_score > 0, (
            f"Leverage diff should diverge, got score={result.divergence_score}"
        )
        notes_text = " ".join(result.notes).lower()
        assert "leverage" in notes_text, (
            f"Notes should mention leverage, got: {result.notes}"
        )

    def test_size_difference_should_diverge(self):
        """expected.size=0.0, actual.size=1.5 → 应触发 divergence."""
        from okx.code.shadow.comparator import compare_signals

        expected = make_signal(size=0.0)
        actual = make_signal(size=1.5)
        result = compare_signals(expected=[expected], actual=[actual])

        assert result.divergence_score > 0, (
            f"Size diff should diverge, got score={result.divergence_score}"
        )
        notes_text = " ".join(result.notes).lower()
        assert "size" in notes_text, (
            f"Notes should mention size, got: {result.notes}"
        )


class TestConfidenceInDivergenceScore:
    """P1 · Bug #2 · confidence_diff 未计入 divergence_score."""

    def test_high_confidence_diff_should_increase_score(self):
        """expected.confidence=0.9, actual.confidence=0.3 → score 应 > 0."""
        from okx.code.shadow.comparator import compare_signals

        expected = make_signal(confidence=0.9)
        actual = make_signal(confidence=0.3)
        result = compare_signals(expected=[expected], actual=[actual])

        # 当前 bug: confidence_diff 未参与 score → 可能 score=0
        # 修复后: confidence_diff=0.6 → 应 > 0
        assert result.divergence_score > 0, (
            f"High confidence diff should diverge, got score={result.divergence_score}"
        )
        # 同时 confidence_diff 字段应 > 0.5
        assert result.confidence_diff > 0.5


class TestReporter:
    """code/shadow/reporter.py::report 测试。"""

    def test_reporter_console_format(self):
        """console mode 输出含 emoji + 关键字段 (divergence_score / alert_level)."""
        from okx.code.shadow.comparator import SignalDivergence, compare_signals
        from okx.code.shadow.reporter import report

        sig = make_signal()
        div = compare_signals(expected=[sig], actual=[sig])
        output = report(div, mode="console")

        # 关键字段应出现
        assert "divergence_score" in output or "0.00" in output
        assert "alert_level" in output or "ok" in output
        # emoji 应出现 (✅ / ⚠️ / 🔴)
        assert any(emoji in output for emoji in ("✅", "⚠️", "🔴"))

    def test_reporter_json_format(self):
        """json mode 输出是 valid JSON + 完整字段。"""
        from okx.code.shadow.comparator import compare_signals
        from okx.code.shadow.reporter import report

        sig = make_signal()
        div = compare_signals(expected=[sig], actual=[sig])
        output = report(div, mode="json")

        # 必须能 parse JSON
        parsed = json.loads(output)
        assert "divergence_score" in parsed
        assert "alert_level" in parsed
        assert "direction_match" in parsed
        assert "sl_diff_bps" in parsed
        assert "tp_diff_bps" in parsed
        assert "notes" in parsed