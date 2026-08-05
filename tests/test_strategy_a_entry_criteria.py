# -*- coding: utf-8 -*-
"""
P2 #1 · Strategy A 信号生成诊断 (2026-08-05)

════════════════════════════════════════════════════════════════════
目的: 钉住 Strategy A 的实际 entry criteria, 防"0 signal = bug"误判。

实测根因 (diagnostic 22:35):
  current_price=64553, EMA20=64322 (price above EMA)
  last 2 closes vs EMA: all_above=True, all_below=False
  EMA slope=20.8 (>0), prev slope=24.7 (>0) — 一致上升趋势
  vol ratio=0.21 (need ≥0.7) — 量能不足

Strategy A 设计意图: 抓 "EMA 转点" (slope 符号反转 + 量能配合)
  - 做多: slope>0 AND prev_slope<=0 AND all_above (由降转升)
  - 做空: slope<0 AND prev_slope>=0 AND all_below (由升转降)

当前市场: EMA 持续上升 (slope 20→24→21, 平稳上升趋势)
  → 既不是转点 (slope 一直 >0) 也不量能配合
  → Strategy A 不生成信号是 **设计意图**, 不是 bug

本 test 把这个事实钉住:
  1. Strategy A 在 steady uptrend + low volume 下不生成信号
  2. Strategy A 在 EMA turning + 高 volume 下生成信号
  3. Strategy A 在 volume 不足时不生成信号 (独立验证)
════════════════════════════════════════════════════════════════════
"""

import pytest

from okx.code.config import Config
from okx.code.signal import SignalEngine


# ────────────── Fixtures ──────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    Config._instance = None
    yield
    Config._instance = None


class MockMarket:
    """构造指定 closes/volumes 的 mock market API"""

    def __init__(self, closes: list, volumes: list = None, highs: list = None, lows: list = None):
        if volumes is None:
            volumes = [1000.0] * len(closes)
        if highs is None:
            highs = [c * 1.001 for c in closes]
        if lows is None:
            lows = [c * 0.999 for c in closes]
        assert len(closes) == len(volumes) == len(highs) == len(lows), "所有数组长度必须一致"
        self._closes = closes
        self._volumes = volumes
        self._highs = highs
        self._lows = lows

    def get_candles(self, symbol, bar="15m", limit=30):
        n = min(limit, len(self._closes))
        closes = self._closes[-n:]
        vols = self._volumes[-n:]
        highs = self._highs[-n:]
        lows = self._lows[-n:]
        # OKX V5 格式: [ts, open, high, low, close, vol, volCcy, volQuote]
        # 修复: index 4=close, index 5=vol (之前错位导致 volumes=0 → ZeroDivisionError)
        return [
            [1700000000000 + i * 900000, o, h, l, c, v, 0, 0]
            for i, (o, h, l, c, v) in enumerate(zip(highs, highs, lows, closes, vols))
        ]


# ────────────── Tests: Strategy A Entry Criteria ──────────────

class TestStrategyAEntryCriteria:
    """Strategy A entry criteria: EMA turning + volume ≥0.7x avg"""

    def test_strategy_a_no_signal_in_steady_uptrend(self):
        """平稳上升趋势 (slope 一致 >0) → Strategy A 不生成信号

        设计意图: Strategy A 抓 "EMA 转点", 不抓趋势
        当前 demo 状态 (22:35): slope 20.8→24.7, 一致上升, 没转点
        """
        # 构造 30 根 K 线: 价格持续上升, EMA 一致上升
        closes = [100.0 + i * 0.5 for i in range(30)]  # 100 → 114.5 (单调上升)
        volumes = [1000.0] * 30
        market = MockMarket(closes, volumes)

        cfg = Config()
        engine = SignalEngine(market, config=cfg)
        signal = engine.check_ema20_signal("BTCUSDT", current_position_direction=None)

        assert signal is None, (
            f"❌ Strategy A 不应在 steady uptrend 生成信号 (设计意图是抓转点). "
            f"got: {signal}"
        )

    def test_strategy_a_no_signal_when_volume_below_threshold(self):
        """volume ratio < 0.7 → Strategy A 不生成信号 (即使 EMA turning)

        这是 P2 #1 的核心发现: 当前 demo volume 只有 0.21x avg
        """
        # EMA turning: 前 3 根 slope<0, 后 3 根 slope>0 → 转点
        # 先升 10 根, 再降 10 根, 再升 10 根 (创造 EMA 转点)
        declining = [120.0 - i * 0.5 for i in range(10)]
        rising = [declining[-1] + 0.5 * (i + 1) for i in range(10)]
        turning = [115.0 - i * 0.3 for i in range(5)]  # 短暂下降触发 EMA 转
        recovering = [turning[-1] + 0.5 * (i + 1) for i in range(5)]
        closes = declining + rising + turning + recovering
        assert len(closes) == 30

        # Volume ratio = 0.5 (不足 0.7 阈值)
        volumes = [1000.0] * 29 + [500.0]  # last volume 0.5x avg
        market = MockMarket(closes, volumes)

        cfg = Config()
        engine = SignalEngine(market, config=cfg)
        signal = engine.check_ema20_signal("BTCUSDT", current_position_direction=None)

        # volume 不足 → 不应生成
        assert signal is None, (
            f"❌ Volume ratio=0.5 < 0.7 阈值, Strategy A 不应生成信号. got: {signal}"
        )

    def test_strategy_a_signal_when_ema_turning_up_with_volume(self):
        """EMA 由降转升 + volume ≥0.7x → Strategy A 应该生成 long 信号

        设计: 构造明确触发 turning_up 的数据集
        - bars 0-26: 稳定 100.0 (EMA 平坦)
        - bar 27: 暴跌到 80 (EMA 下降)
        - bar 28: 回升到 102 (all_above 验始)
        - bar 29: 继续升到 110 (slope>0 验证)

        预期计算:
        - EMA20 在 bar 25-26 = 100 (flat)
        - EMA20 在 bar 27 = 98.1 (下跌, prev_slope<0)
        - EMA20 在 bar 28 = 98.475 (回升, 刚刚 all_above)
        - EMA20 在 bar 29 = 99.515 (slope>0)

        prev_slope(26,27,28) ≈ -0.76 (flat→下跌 → ≤0 ✓)
        slope(27,28,29) ≈ +0.71 (→+0.7 ✓)
        all_above: 102>98.475 ✓, 110>99.515 ✓
        vol_ok: 1500 ≥ 1000*0.7=700 ✓
        RSI: 中高 (~60), <65 (不过热) ✓
        """
        closes = [100.0] * 27 + [80.0, 102.0, 110.0]  # 30 bars
        # Volume: avg 1000, last 1500 (ratio=1.5 > 0.7)
        volumes = [1000.0] * 30
        volumes[-1] = 1500.0
        market = MockMarket(closes, volumes)

        cfg = Config()
        engine = SignalEngine(market, config=cfg)
        signal = engine.check_ema20_signal("BTCUSDT", current_position_direction=None)

        # 应该生成 long 信号 (条件: slope>0, prev_slope<=0, all_above, vol_ok)
        assert signal is not None, (
            "EMA 由降转升 + 高 volume → Strategy A 应生成 long 信号"
        )
        assert signal.direction == "long", f"应是 long, got {signal.direction}"
        assert signal.strategy == "EMA20_BREAKOUT"


class TestStrategyACurrentDemoState:
    """当前 demo (22:35) 状态: Strategy A 0 signals 是 expected behavior"""

    def test_current_demo_state_no_signal_expected(self):
        """用 diagnostic 22:35 真实数据验证 → 无信号 (钉住 ground truth)"""
        from okx.code.backtest.data_loader import load

        cfg = Config()
        data = load("BTC-USDT-SWAP", "15m")
        df = data.klines

        # 取最后 30 根
        closes = df["close"].tail(30).tolist()
        volumes = df["volume"].tail(30).tolist() if "volume" in df.columns else [1000.0] * 30
        highs = df["high"].tail(30).tolist() if "high" in df.columns else [c * 1.001 for c in closes]
        lows = df["low"].tail(30).tolist() if "low" in df.columns else [c * 0.999 for c in closes]

        market = MockMarket(closes, volumes, highs, lows)
        engine = SignalEngine(market, config=cfg)
        signal = engine.check_ema20_signal("BTCUSDT", current_position_direction=None)

        # 当前 demo: steady uptrend + low volume → 不应生成
        # 这条 test 把 "0 signal = expected" 钉住, 防将来误判为 bug
        assert signal is None, (
            f"当前 demo (22:35) state: steady uptrend + low volume. "
            f"Strategy A 不生成是 expected behavior. "
            f"如果将来 signal != None → 市场 state 变了 (or fix 改了 criteria), "
            f"需重新评估。got: {signal}"
        )