# -*- coding: utf-8 -*-
"""
test_regime_filter.py —— regime_filter 单元测试

覆盖：
1. resample_to_daily() —— 1h → 1d 重采样，空数据/缺失列
2. _compute_features() —— 90d return / EMA50 / EMA200
3. recommended_strategy() —— UP/SIDE/DOWN 决策 + 边界 + 数据不足

数据策略：
  - 用 mock pd.DataFrame 构造 250+ 天的 BTC 1h K-lines
  - 价格序列按 regime 手工设计（保证 90d_return + EMA50/200 落在预期区间）

跑法：
  pytest okx/tests/test_regime_filter.py -v
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from okx.code.regime_filter import (
    resample_to_daily,
    _compute_features,
    recommended_strategy,
    DEFAULT_UP_RET_THRESHOLD,
    DEFAULT_DOWN_RET_THRESHOLD,
    DEFAULT_EMA_BULLISH_RATIO,
)


# ────────────────────────────────────────────────────────────────────
# Helper：构造 mock BTC K-lines
# ────────────────────────────────────────────────────────────────────
def make_btc_klines(
    start_date: datetime,
    days: int,
    *,
    start_price: float = 100_000.0,
    end_price: float = 100_000.0,
    hourly: bool = True,
) -> pd.DataFrame:
    """构造 N 天的 BTC OHLC K-lines，价格从 start_price 单调走到 end_price。

    :param start_date: 起始时间（UTC）
    :param days: 天数
    :param start_price: 起始价
    :param end_price: 结束价（最后一天的收盘价）
    :param hourly: True=1h (24*days 行)，False=1d (days 行)
    """
    bars_per_day = 24 if hourly else 1
    n_bars = days * bars_per_day
    if hourly:
        # 1h bars: 起始 00:00 UTC
        timestamps = [int((start_date + timedelta(hours=i)).timestamp() * 1000)
                     for i in range(n_bars)]
    else:
        timestamps = [int((start_date + timedelta(days=i)).timestamp() * 1000)
                     for i in range(n_bars)]

    # 价格在 250 天里单调线性插值
    if days > 1 and hourly:
        # 1h bars
        per_hour_step = (end_price - start_price) / (n_bars - 1)
        closes = [start_price + i * per_hour_step for i in range(n_bars)]
        highs = [c * 1.001 for c in closes]
        lows = [c * 0.999 for c in closes]
        opens = [closes[0]] + closes[:-1]
    elif days > 1:
        per_day_step = (end_price - start_price) / (days - 1)
        closes = [start_price + i * per_day_step for i in range(days)]
        highs = [c * 1.001 for c in closes]
        lows = [c * 0.999 for c in closes]
        opens = [closes[0]] + closes[:-1]
    else:
        closes = [start_price]
        highs = [start_price]
        lows = [start_price]
        opens = [start_price]

    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000.0] * n_bars,
    })


def make_regime_klines(
    regime: str,
    *,
    start_date: datetime = None,
    days: int = 250,
) -> pd.DataFrame:
    """构造特定 regime 的 mock BTC K-lines。

    regime:
      - "UP_STRONG": 90d ret +25%, EMA50 > EMA200（强 UP → 拒入场）
      - "UP_WEAK": 90d ret +8%, EMA ratio 1.01（弱 UP/SIDE → 人工）
      - "SIDE": 90d ret +2%, EMA ratio 1.0（SIDE → 人工）
      - "DOWN_WEAK": 90d ret -3%, EMA ratio 0.99（弱 DOWN/SIDE → 人工）
      - "DOWN_STRONG": 90d ret -15%, EMA50 < EMA200（强 DOWN → 首选 A）
      - "FLAT_UP": 90d ret +0.5%, EMA ratio 1.005（边界 → 人工）
      - "FLAT_DOWN": 90d ret -2%, EMA ratio 0.995（边界 → 人工）
    """
    if start_date is None:
        start_date = datetime(2025, 1, 1, tzinfo=timezone.utc)

    # 构造价格序列模拟 regime
    # 简化：先平 100k 250 天，再用价格插值制造 regime
    if regime == "UP_STRONG":
        # 前 160 天平稳 100k，后 90 天涨到 125k（+25%）
        closes = [100_000.0] * 160 + [100_000 + (125_000 - 100_000) * i / 90 for i in range(1, 91)]
    elif regime == "UP_WEAK":
        # 250 天前 200 天 100k，后 90 天涨到 108k
        closes = [100_000.0] * 160 + [100_000 + (108_000 - 100_000) * i / 90 for i in range(1, 91)]
    elif regime == "SIDE":
        # 250 天 100k ~ 102k 震荡
        closes = [100_000 + (i % 8) * 250 for i in range(250)]
    elif regime == "DOWN_WEAK":
        # 250 天前 160 天 100k，后 90 天跌到 97k
        closes = [100_000.0] * 160 + [100_000 - (100_000 - 97_000) * i / 90 for i in range(1, 91)]
    elif regime == "DOWN_STRONG":
        # 前 160 天 100k，后 90 天跌到 85k
        closes = [100_000.0] * 160 + [100_000 - (100_000 - 85_000) * i / 90 for i in range(1, 91)]
    elif regime == "FLAT_UP":
        closes = [100_000.0] * 250  # 完全平：ret=0, EMA ratio ~1.0
    elif regime == "FLAT_DOWN":
        closes = [100_000.0] * 250
    else:
        raise ValueError(f"Unknown regime: {regime}")

    assert len(closes) == days, f"mock {regime}: 长度 {len(closes)} ≠ {days}"

    # 转 1h DataFrame：每个 close 复制 24 小时
    hourly_closes = []
    hourly_ts = []
    base = start_date
    for day_idx, c in enumerate(closes):
        for h in range(24):
            hourly_closes.append(c)
            ts = base + timedelta(days=day_idx, hours=h)
            hourly_ts.append(int(ts.timestamp() * 1000))

    return pd.DataFrame({
        "timestamp": hourly_ts,
        "open": hourly_closes,
        "high": [c * 1.001 for c in hourly_closes],
        "low": [c * 0.999 for c in hourly_closes],
        "close": hourly_closes,
        "volume": [1000.0] * len(hourly_closes),
    })


# ────────────────────────────────────────────────────────────────────
# resample_to_daily()
# ────────────────────────────────────────────────────────────────────
class TestResampleToDaily:
    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["timestamp", "close"])
        result = resample_to_daily(df)
        assert len(result) == 0
        assert result.name == "close"

    def test_none_input(self):
        result = resample_to_daily(None)
        assert len(result) == 0

    def test_hourly_resamples_to_daily(self):
        df = make_btc_klines(
            start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            days=10, start_price=100_000, end_price=110_000,
        )
        result = resample_to_daily(df)
        assert len(result) == 10
        assert result.iloc[0] == pytest.approx(100_000, rel=0.01)
        assert result.iloc[-1] == pytest.approx(110_000, rel=0.01)

    def test_daily_passes_through(self):
        df = make_btc_klines(
            start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            days=10, start_price=100_000, end_price=110_000,
            hourly=False,
        )
        result = resample_to_daily(df)
        assert len(result) == 10

    def test_missing_timestamp_column_raises(self):
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        with pytest.raises(ValueError, match="缺 timestamp"):
            resample_to_daily(df)


# ────────────────────────────────────────────────────────────────────
# _compute_features()
# ────────────────────────────────────────────────────────────────────
class TestComputeFeatures:
    def test_insufficient_data_no_ema(self):
        s = pd.Series([100.0, 101.0, 102.0], name="close")
        feats = _compute_features(s)
        assert feats["ret_90d_pct"] is None
        assert feats["ema50"] is None
        assert feats["ema200"] is None
        assert feats["bars"] == 3

    def test_full_year_has_all_features(self):
        # 250 天线性 100k → 110k（+10% over 250 days = ret_90d positive）
        s = pd.Series(
            [100_000 + i * (10_000 / 249) for i in range(250)],
            name="close",
        )
        feats = _compute_features(s)
        assert feats["bars"] == 250
        assert feats["ret_90d_pct"] is not None
        # 涨势 EMA50 > EMA200
        assert feats["ema50"] > feats["ema200"]
        assert feats["ema_ratio"] > 1.0

    def test_downtrend_ema_below(self):
        # 250 天 100k → 85k（下跌）
        s = pd.Series(
            [100_000 - i * (15_000 / 249) for i in range(250)],
            name="close",
        )
        feats = _compute_features(s)
        assert feats["ret_90d_pct"] < 0
        assert feats["ema50"] < feats["ema200"]
        assert feats["ema_ratio"] < 1.0


# ────────────────────────────────────────────────────────────────────
# recommended_strategy() —— 主要 API
# ────────────────────────────────────────────────────────────────────
class TestRecommendedStrategy:
    def test_empty_returns_none(self):
        df = pd.DataFrame(columns=["timestamp", "close"])
        strategy, reason, feats = recommended_strategy(df)
        assert strategy is None
        assert "数据不足" in reason

    def test_up_strong_returns_none(self):
        df = make_regime_klines("UP_STRONG")
        strategy, reason, feats = recommended_strategy(df)
        assert strategy is None
        assert "UP+EMA多头" in reason
        assert feats["ret_90d_pct"] > DEFAULT_UP_RET_THRESHOLD
        assert feats["ema_ratio"] > DEFAULT_EMA_BULLISH_RATIO

    def test_down_strong_returns_a(self):
        df = make_regime_klines("DOWN_STRONG")
        strategy, reason, feats = recommended_strategy(df)
        assert strategy == "A"
        assert "DOWN+EMA空头 首选 A" in reason
        assert feats["ret_90d_pct"] < DEFAULT_DOWN_RET_THRESHOLD
        assert feats["ema_ratio"] < 1.0

    def test_side_returns_none(self):
        df = make_regime_klines("SIDE")
        strategy, reason, feats = recommended_strategy(df)
        assert strategy is None
        assert "SIDE" in reason

    def test_flat_returns_none(self):
        df = make_regime_klines("FLAT_UP")
        strategy, reason, feats = recommended_strategy(df)
        assert strategy is None
        # 0% ret + ratio ~1 → 边界 SIDE
        assert "SIDE" in reason or "UP" in reason

    def test_up_weak_returns_none(self):
        """90d ret +8%（弱 UP < 10% 阈值）→ 落入 SIDE"""
        df = make_regime_klines("UP_WEAK")
        strategy, reason, feats = recommended_strategy(df)
        assert strategy is None

    def test_down_weak_returns_none(self):
        """90d ret -3%（弱 DOWN > -5% 阈值）→ 落入 SIDE"""
        df = make_regime_klines("DOWN_WEAK")
        strategy, reason, feats = recommended_strategy(df)
        assert strategy is None

    def test_threshold_override(self):
        """手动提高 up_threshold 到 30% → UP_STRONG 不再拒"""
        df = make_regime_klines("UP_STRONG")
        strategy, reason, _ = recommended_strategy(
            df, up_ret_threshold=30.0,
        )
        # 25% < 30% → 不再触发 UP 拒绝 → 落入 SIDE 或其他
        assert strategy is None
        assert "UP+EMA多头" not in reason

    def test_returns_features_dict(self):
        """返回的 features dict 必须包含完整指标便于 dashboard 展示"""
        df = make_regime_klines("DOWN_STRONG")
        _, _, feats = recommended_strategy(df)
        assert "ret_90d_pct" in feats
        assert "ema50" in feats
        assert "ema200" in feats
        assert "ema_ratio" in feats
        assert "last_price" in feats
        assert "bars" in feats
        assert all(v is not None for v in [feats["ret_90d_pct"], feats["ema50"],
                                            feats["ema200"], feats["ema_ratio"]])


# ────────────────────────────────────────────────────────────────────
# 集成测试：mock 18 walkforward 窗口的 regime pattern
# ────────────────────────────────────────────────────────────────────
class TestRegimePatternFromWalkforward:
    """
    Phase 3A walkforward 18 窗口的 regime 分类（基于 buy&hold）：
    - 7 个 UP 窗口（buy&hold > +10%）：C 全部 0 viable
    - 7 个 DOWN 窗口（buy&hold < -5%）：C 86% viable，A 100% viable
    - 4 个 SIDE 窗口：混合

    regime_filter 应该能根据 BTC 90d return 给出对应决策。
    """

    @pytest.mark.parametrize("regime_mock,expected_strategy", [
        ("UP_STRONG", None),       # 拒入场
        ("DOWN_STRONG", "A"),      # 首选 A
        ("SIDE", None),            # 人工
        ("UP_WEAK", None),
        ("DOWN_WEAK", None),
        ("FLAT_UP", None),
        ("FLAT_DOWN", None),
    ])
    def test_walkforward_window_mapping(self, regime_mock, expected_strategy):
        df = make_regime_klines(regime_mock)
        strategy, reason, _ = recommended_strategy(df)
        assert strategy == expected_strategy, (
            f"regime={regime_mock} expected={expected_strategy} got={strategy}, reason={reason}"
        )
