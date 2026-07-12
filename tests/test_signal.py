# -*- coding: utf-8 -*-
"""
SignalEngine 辅助函数单元测试

覆盖纯函数（无 IO、无状态）：
- _ema: 指数移动平均
- _rsi: 相对强弱指数
- _atr: 平均真实波幅
- _bollinger_bands: 布林带
- _linear_slope: 线性回归斜率
- _calc_confidence: 信号置信度
- _get_leverage: 交易对杠杆

设计原则：每个测试用一小组手工构造的数值 + 已知预期输出（不依赖市场数据）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from okx.code.signal import SignalEngine, Signal
from okx.code.config import Config


# ──────────── Fixtures ────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    Config._instance = None
    yield
    Config._instance = None


# ──────────── _ema ────────────

def test_ema_insufficient_data():
    """数据不足时返回空列表"""
    assert SignalEngine._ema([1, 2, 3], period=5) == []


def test_ema_constant_series():
    """常数序列的 EMA 等于该常数"""
    data = [50.0] * 30
    ema = SignalEngine._ema(data, period=10)
    assert all(abs(v - 50.0) < 1e-9 for v in ema)


def test_ema_trending_up():
    """持续上升序列，EMA 应单调递增且贴近最新价格"""
    data = list(range(1, 31))  # 1..30
    ema = SignalEngine._ema(data, period=10)
    assert len(ema) == 21
    assert all(ema[i] < ema[i + 1] for i in range(len(ema) - 1))
    # period=10 的 EMA 对最近 30 个值的反应较慢
    # 实际计算：最后一个 ema ≈ 25.5
    assert ema[-1] > 20
    assert ema[-1] < 30


def test_ema_first_value_is_sma():
    """EMA 第一个值是前 period 个数据的简单平均"""
    data = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]
    ema = SignalEngine._ema(data, period=10)
    # 第一个 EMA = mean(data[0:10]) = (10+20+...+100)/10 = 55
    assert ema[0] == pytest.approx(55.0)


def test_ema_recursive_formula():
    """EMA 递推公式：ema_t = price_t * k + ema_{t-1} * (1 - k)，k=2/(period+1)"""
    data = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130]
    ema = SignalEngine._ema(data, period=5)
    k = 2 / 6  # 0.3333
    # 第一个 ema = mean(data[0:5]) = 30
    assert ema[0] == pytest.approx(30.0)
    # 第二个 ema = 60 * k + 30 * (1 - k)
    expected = 60 * k + 30 * (1 - k)
    assert ema[1] == pytest.approx(expected)


# ──────────── _rsi ────────────

def test_rsi_insufficient_data():
    """数据不足返回空"""
    assert SignalEngine._rsi([1, 2, 3], period=14) == []


def test_rsi_all_uptrend_equals_100():
    """全部上涨：RSI = 100"""
    data = list(range(1, 30))  # 单调递增
    rsi = SignalEngine._rsi(data, period=14)
    assert len(rsi) == 15
    assert all(v == pytest.approx(100.0) for v in rsi)


def test_rsi_all_downtrend_equals_0():
    """全部下跌：RSI = 0"""
    data = list(range(30, 0, -1))  # 单调递减
    rsi = SignalEngine._rsi(data, period=14)
    assert all(v == pytest.approx(0.0, abs=1e-9) for v in rsi)


def test_rsi_balanced_is_around_50():
    """交替涨跌，RSI 应在 50 附近"""
    # 奇数 +1，偶数 -1
    data = [100 + (1 if i % 2 == 0 else -1) for i in range(30)]
    rsi = SignalEngine._rsi(data, period=14)
    # 理论上 50（但 Wilder 平滑会让前期有偏差）
    assert all(40 <= v <= 60 for v in rsi[-5:])


def test_rsi_length():
    """RSI 长度 = len(closes) - period"""
    data = [100.0] * 30
    rsi = SignalEngine._rsi(data, period=14)
    assert len(rsi) == 16  # 30 - 14


# ──────────── _atr ────────────

def test_atr_insufficient_data():
    """数据不足返回空"""
    highs = [10] * 5
    lows = [9] * 5
    closes = [9.5] * 5
    assert SignalEngine._atr(highs, lows, closes, period=14) == []


def test_atr_constant_range():
    """K线 H-L 恒定时，ATR = 该常数"""
    highs = [110.0] * 20
    lows = [100.0] * 20
    closes = [105.0] * 20
    atr = SignalEngine._atr(highs, lows, closes, period=14)
    assert all(abs(v - 10.0) < 1e-9 for v in atr)


def test_atr_with_gaps():
    """考虑跳空：真实波幅 = max(H-L, |H-prev_close|, |L-prev_close|)
    准备至少 period+1+1 = 16 根 K 线才能 period=1+1 个 TR
    """
    # period=1: 需要 len(closes) >= period+1 = 2
    # 第 2 根 K 线：H=110, L=100, prev_close=80 → TR = max(10, 30, 20) = 30
    highs = [100.0, 110.0]
    lows = [95.0, 100.0]
    closes = [80.0, 105.0]
    atr = SignalEngine._atr(highs, lows, closes, period=1)
    # 第一个 ATR 是前 1 个 TR 的平均 = 30
    assert atr[0] == pytest.approx(30.0)


def test_atr_length():
    """ATR 长度 = len(closes) - 1 - period + 1 = len(closes) - period"""
    highs = [110.0] * 20
    lows = [100.0] * 20
    closes = [105.0] * 20
    atr = SignalEngine._atr(highs, lows, closes, period=14)
    assert len(atr) == 6  # 20 - 14


# ──────────── _bollinger_bands ────────────

def test_bollinger_insufficient_data():
    """数据不足返回空"""
    assert SignalEngine._bollinger_bands([1, 2, 3], period=20) == []


def test_bollinger_constant_series():
    """常数序列：上下轨 = 中轨 = 该常数"""
    data = [50.0] * 25
    bands = SignalEngine._bollinger_bands(data, period=20, std_dev=2.0)
    assert len(bands) == 6  # 25 - 20 + 1
    for upper, middle, lower in bands:
        assert upper == pytest.approx(50.0)
        assert middle == pytest.approx(50.0)
        assert lower == pytest.approx(50.0)


def test_bollinger_upper_above_middle_above_lower():
    """上轨 > 中轨 > 下轨"""
    import random
    random.seed(42)
    data = [100 + random.gauss(0, 5) for _ in range(50)]
    bands = SignalEngine._bollinger_bands(data, period=20, std_dev=2.0)
    for upper, middle, lower in bands:
        assert upper > middle > lower


def test_bollinger_symmetry():
    """上下轨关于中轨对称"""
    data = list(range(1, 30))  # 1..29
    bands = SignalEngine._bollinger_bands(data, period=10, std_dev=2.0)
    for upper, middle, lower in bands:
        assert (upper - middle) == pytest.approx(middle - lower, abs=1e-9)


# ──────────── _linear_slope ────────────

def test_slope_single_point():
    """单点斜率 = 0"""
    assert SignalEngine._linear_slope([5.0]) == 0.0


def test_slope_empty_list():
    """空列表斜率 = 0"""
    assert SignalEngine._linear_slope([]) == 0.0


def test_slope_perfectly_linear_increasing():
    """完美线性递增：斜率 = (y_n - y_0) / (n - 1)"""
    data = [1, 2, 3, 4, 5]
    slope = SignalEngine._linear_slope(data)
    # y = x, slope = 1
    assert slope == pytest.approx(1.0)


def test_slope_perfectly_linear_decreasing():
    """完美线性递减：斜率为负"""
    data = [5, 4, 3, 2, 1]
    slope = SignalEngine._linear_slope(data)
    assert slope == pytest.approx(-1.0)


def test_slope_constant_series():
    """常数序列斜率 = 0"""
    data = [10.0] * 10
    slope = SignalEngine._linear_slope(data)
    assert slope == pytest.approx(0.0)


def test_slope_three_points_linear():
    """3 点：[1, 2, 3]，x=0,1,2，slope = 1"""
    slope = SignalEngine._linear_slope([1, 2, 3])
    assert slope == pytest.approx(1.0)


# ──────────── _calc_confidence ────────────

class _FakeMarket:
    """用于实例化 SignalEngine 的最小 Market 替身"""
    def get_candles(self, *args, **kwargs):
        return []


def _make_engine():
    """_calc_confidence 是 instance method，需要实例"""
    return SignalEngine(market_api=_FakeMarket(), config=None)


def test_confidence_base():
    """无任何加分项时 = 0.5 基础分"""
    engine = _make_engine()
    conf = engine._calc_confidence(
        direction="long", all_above=False, all_below=False,
        vol_ok=False, avg_vol=100, signal_vol=50,
    )
    assert conf == pytest.approx(0.5)


def test_confidence_max_with_all_signals():
    """所有信号都强时达到 1.0 上限"""
    engine = _make_engine()
    conf = engine._calc_confidence(
        direction="long", all_above=True, all_below=False,
        vol_ok=True, avg_vol=100, signal_vol=300,  # vol_ratio=3x → +0.10
        rsi=45, rsi_overbought=65, rsi_oversold=35,  # 35-50 区间 → +0.10
    )
    # 0.5 + 0.15 (趋势) + 0.15 (量价) + 0.10 (3x量) + 0.10 (RSI) = 1.0
    # 被 min(1.0) 封顶
    assert conf == pytest.approx(1.0)


def test_confidence_capped_at_1():
    """置信度上限 1.0"""
    engine = _make_engine()
    conf = engine._calc_confidence(
        direction="long", all_above=True, all_below=False,
        vol_ok=True, avg_vol=100, signal_vol=1000,
        rsi=20, rsi_overbought=65, rsi_oversold=35,
    )
    assert conf <= 1.0


def test_confidence_floor_at_0():
    """置信度下限 0.0"""
    engine = _make_engine()
    conf = engine._calc_confidence(
        direction="long", all_above=False, all_below=False,
        vol_ok=False, avg_vol=0, signal_vol=0,
        rsi=None, rsi_overbought=65, rsi_oversold=35,
    )
    assert conf >= 0.0


def test_confidence_short_direction():
    """做空时 RSI 在 50-65 区间加分"""
    engine = _make_engine()
    conf_long = engine._calc_confidence(
        direction="long", all_above=True, all_below=False,
        vol_ok=True, avg_vol=100, signal_vol=200,
        rsi=45, rsi_overbought=65, rsi_oversold=35,
    )
    conf_short = engine._calc_confidence(
        direction="short", all_above=False, all_below=True,
        vol_ok=True, avg_vol=100, signal_vol=200,
        rsi=55, rsi_overbought=65, rsi_oversold=35,
    )
    assert conf_long == conf_short  # 同样条件下方向不影响分数


# ──────────── Signal 数据类 ────────────

def test_signal_to_dict():
    """Signal 序列化"""
    sig = Signal(
        strategy="EMA20_BREAKOUT", symbol="BTC-USDT", direction="long",
        entry_price=50000.0, sl_price=49000.0, tp_price=51500.0,
        leverage=5, size=0.1, confidence=0.75,
        reason="test", kline_time="2026-07-10T00:00:00Z",
    )
    d = sig.to_dict()
    assert d["symbol"] == "BTC-USDT"
    assert d["direction"] == "long"
    assert d["leverage"] == 5
    assert d["entry_price"] == 50000.0


def test_signal_repr_includes_key_fields():
    """Signal __repr__ 关键字段"""
    sig = Signal(
        strategy="EMA20_BREAKOUT", symbol="BTC-USDT", direction="short",
        entry_price=50000.0, sl_price=51000.0, tp_price=48500.0,
        leverage=3, size=0.5, confidence=0.6,
        reason="", kline_time="",
    )
    r = repr(sig)
    assert "BTC-USDT" in r
    assert "short" in r
    assert "3x" in r
