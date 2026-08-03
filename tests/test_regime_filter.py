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
from unittest.mock import patch, Mock

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from okx.code.regime_filter import (
    resample_to_daily,
    _compute_features,
    recommended_strategy,
    tag_trades_by_regime,
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
        strategies, reason, feats = recommended_strategy(df)
        assert strategies == []
        assert "数据不足" in reason

    def test_up_strong_returns_none(self):
        df = make_regime_klines("UP_STRONG")
        strategies, reason, feats = recommended_strategy(df)
        assert strategies == []
        assert "UP+EMA多头" in reason
        assert feats["ret_90d_pct"] > DEFAULT_UP_RET_THRESHOLD
        assert feats["ema_ratio"] > DEFAULT_EMA_BULLISH_RATIO

    def test_down_strong_returns_a(self):
        df = make_regime_klines("DOWN_STRONG")
        strategies, reason, feats = recommended_strategy(df)
        assert strategies == ["A"]
        assert "DOWN+EMA空头 首选 A" in reason
        assert feats["ret_90d_pct"] < DEFAULT_DOWN_RET_THRESHOLD
        assert feats["ema_ratio"] < 1.0

    def test_side_returns_e_in_default_mapping(self):
        """SIDE 默认 mapping → ["E"] (Plan B 填补空白)."""
        df = make_regime_klines("SIDE")
        strategies, reason, feats = recommended_strategy(df)
        assert strategies == ["E"]
        assert "SIDE" in reason

    def test_flat_returns_e_in_default_mapping(self):
        """FLAT_UP 落入 SIDE → 默认 mapping ["E"]."""
        df = make_regime_klines("FLAT_UP")
        strategies, reason, feats = recommended_strategy(df)
        assert strategies == ["E"]
        assert "SIDE" in reason or "UP" in reason

    def test_up_weak_returns_e_in_default_mapping(self):
        """UP_WEAK 落入 SIDE → 默认 mapping ["E"]."""
        df = make_regime_klines("UP_WEAK")
        strategies, reason, feats = recommended_strategy(df)
        assert strategies == ["E"]

    def test_down_weak_returns_e_in_default_mapping(self):
        """DOWN_WEAK 落入 SIDE → 默认 mapping ["E"]."""
        df = make_regime_klines("DOWN_WEAK")
        strategies, reason, feats = recommended_strategy(df)
        assert strategies == ["E"]

    # ──────────────────────────────────────────────────────────────
# 新增 · multi-strategy return type (Plan B mini-refactor)
# 推荐函数从 Optional[str] 改为 list[str] —— 多策略 candidate + 空 = 拒入场
# ──────────────────────────────────────────────────────────────

class TestRecommendedStrategyMultiStrategy:
    """v1.9.0 · recommended_strategy 返回类型从 Optional[str] 改为 list[str]。"""

    def test_return_type_is_list(self):
        """返回类型必须是 list[str]，不再是 str 或 None。"""
        df = make_regime_klines("DOWN_STRONG")
        result = recommended_strategy(df)
        assert isinstance(result, tuple) and len(result) == 3
        strategies, reason, feats = result
        assert isinstance(strategies, list), (
            f"strategies 必须是 list, got {type(strategies).__name__}"
        )
        for s in strategies:
            assert isinstance(s, str)

    def test_down_strong_returns_list_containing_a(self):
        """DOWN_STRONG → list 必须严格包含 'A' (list 长度 = 1)。"""
        df = make_regime_klines("DOWN_STRONG")
        strategies, reason, _ = recommended_strategy(df)
        assert isinstance(strategies, list), f"必须返回 list, got {type(strategies).__name__}"
        assert strategies == ["A"], f"DOWN_STRONG 应返回 ['A'], got {strategies}"
        assert "DOWN+EMA空头" in reason

    def test_side_returns_e_in_list(self):
        """SIDE regime → 包含 "E"（填空白 · Plan B 核心改动）。"""
        df = make_regime_klines("SIDE")
        strategies, reason, _ = recommended_strategy(df)
        assert "E" in strategies, (
            f"SIDE regime 应推荐 E (VEB), got {strategies}"
        )

    def test_up_returns_empty_list(self):
        """UP_STRONG → [] (拒入场)。"""
        df = make_regime_klines("UP_STRONG")
        strategies, reason, _ = recommended_strategy(df)
        assert strategies == [], (
            f"UP_STRONG 应返回空 list, got {strategies}"
        )

    def test_empty_data_returns_empty_list(self):
        """数据不足时返回 [] (而非 None)。"""
        df = pd.DataFrame(columns=["timestamp", "close"])
        strategies, reason, feats = recommended_strategy(df)
        assert strategies == []
        assert "数据不足" in reason


class TestRegimeStrategyMapConfig:
    """regime_strategy_map 应在 state/config.json 中可配置 (而非硬编码)。"""

    def test_default_down_to_a(self):
        """默认 mapping: DOWN → [A]。"""
        from okx.code.config import Config
        cfg = Config()
        m = cfg.regime_strategy_map
        assert "A" in m.get("DOWN", [])

    def test_default_side_to_e(self):
        """默认 mapping: SIDE → [E] (Plan B 填补空白)。"""
        from okx.code.config import Config
        cfg = Config()
        m = cfg.regime_strategy_map
        assert "E" in m.get("SIDE", []), (
            f"SIDE 应默认映射 E (VEB), got {m.get('SIDE', [])}"
        )

    def test_default_up_empty(self):
        """默认 mapping: UP → [] (实证亏损)。"""
        from okx.code.config import Config
        cfg = Config()
        m = cfg.regime_strategy_map
        assert m.get("UP", []) == []


# ──────────────────────────────────────────────────────────────
# 原 Threshold Override 等测试继续在下方
# ──────────────────────────────────────────────────────────────

    def test_threshold_override(self):
        """手动提高 up_threshold 到 30% → UP_STRONG 不再拒。

        v1.9.0 后：SIDE regime 默认 mapping 返回 ["E"] (Plan B 填补空白)。
        """
        df = make_regime_klines("UP_STRONG")
        strategies, reason, _ = recommended_strategy(
            df, up_ret_threshold=30.0,
        )
        # 25% < 30% → 不再触发 UP 拒绝 → 落入 SIDE → 默认 mapping ["E"]
        assert strategies == ["E"], f"UP+overridden 应落入 SIDE → ['E'], got {strategies}"
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
        ("UP_STRONG", []),         # 拒入场 (v1.9.0 改 list[str])
        ("DOWN_STRONG", ["A"]),    # 首选 A
        ("SIDE", ["E"]),           # 人工 (SIDE 在 Plan B 后默认 ["E"] — VEB 自动启用)
        ("UP_WEAK", ["E"]),        # 弱 UP 落入 SIDE
        ("DOWN_WEAK", ["E"]),      # 弱 DOWN 落入 SIDE
        ("FLAT_UP", ["E"]),        # 边界 SIDE
        ("FLAT_DOWN", ["E"]),      # 边界 SIDE
    ])
    def test_walkforward_window_mapping(self, regime_mock, expected_strategy):
        df = make_regime_klines(regime_mock)
        strategies, reason, _ = recommended_strategy(df)
        assert strategies == expected_strategy, (
            f"regime={regime_mock} expected={expected_strategy} got={strategy}, reason={reason}"
        )


# ────────────────────────────────────────────────────────────────────
# tag_trades_by_regime() —— 后验标签添加
# ────────────────────────────────────────────────────────────────────
class TestTagTradesByRegime:
    """为 trades 加 '_regime' 列（4 label: A / UP / SIDE / UNKNOWN）

    Mock 策略：patch `okx.code.backtest.data_loader.load` →
    返回 Mock(klines=<regime-specific klines>) → 让 recommended_strategy
    跑真实逻辑（验证 integration）。Exception / 防御性 case 直接 mock
    推荐策略返回值。

    Lessons applied (来自 7-26 mock target drift 复盘):
    - patch 写完整 module path (okx.code.X.Y) 而非 from-import 名字
    - 不用 monkey-patch 同一个 instance；每个 test 用 fresh context manager
    """

    @staticmethod
    def _make_trades(n: int, *, window_id: str = "w0") -> pd.DataFrame:
        """构造 mock trades DataFrame"""
        return pd.DataFrame({
            "window_id": [window_id] * n,
            "exit_ts": [1700000000000 + i * 1000 for i in range(n)],
            "symbol": ["BTC-USDT-SWAP"] * n,
        })

    def test_missing_window_id_raises(self):
        """trades 缺少 window_id 列 → KeyError"""
        df = pd.DataFrame({"exit_ts": [1700000000000], "symbol": ["BTC-USDT-SWAP"]})
        with pytest.raises(KeyError, match="window_id"):
            tag_trades_by_regime(df)

    def test_empty_trades_returns_empty_with_regime_column(self):
        """空 DataFrame → 返回空 + _regime 列"""
        df = pd.DataFrame(columns=["window_id", "exit_ts"])
        result = tag_trades_by_regime(df)
        assert len(result) == 0
        assert "_regime" in result.columns

    def test_returns_copy_not_mutates_original(self):
        """原 DataFrame 不被修改"""
        df = self._make_trades(3)
        original_columns = list(df.columns)
        _ = tag_trades_by_regime(df)
        assert list(df.columns) == original_columns
        assert "_regime" not in df.columns

    def test_returns_same_length(self):
        """输出长度 == 输入长度"""
        df = self._make_trades(5)
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(klines=make_regime_klines("DOWN_STRONG"))
            result = tag_trades_by_regime(df)
        assert len(result) == len(df)

    def test_single_window_down_strong_tagged_a(self):
        """单 window + DOWN regime → 全部 trades 标 A"""
        df = self._make_trades(3)
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(klines=make_regime_klines("DOWN_STRONG"))
            result = tag_trades_by_regime(df)
        assert (result["_regime"] == "A").all()
        # 同一 window 只调一次 load（dedup by window_id）
        assert mock_load.call_count == 1

    def test_single_window_up_strong_tagged_up(self):
        """单 window + UP regime → 全部 trades 标 UP"""
        df = self._make_trades(3)
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(klines=make_regime_klines("UP_STRONG"))
            result = tag_trades_by_regime(df)
        assert (result["_regime"] == "UP").all()

    def test_single_window_side_tagged_side(self):
        """单 window + SIDE regime → 全部 trades 标 SIDE"""
        df = self._make_trades(3)
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(klines=make_regime_klines("SIDE"))
            result = tag_trades_by_regime(df)
        assert (result["_regime"] == "SIDE").all()

    def test_data_insufficient_trades_tagged_unknown(self):
        """empty klines (data insufficient) → 标 UNKNOWN (修正 Plan B 与 docstring 偏差).

        v1.9.0 Plan B: ret_90d/ema_ratio is None → UNKNOWN (符合 docstring)
        修前 (v1.8.x): ret_90d is None 走 else 分支误标 SIDE。
        """
        df = self._make_trades(2)
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(
                klines=pd.DataFrame(columns=["timestamp", "close"])
            )
            result = tag_trades_by_regime(df)
        assert (result["_regime"] == "UNKNOWN").all()

    def test_load_klines_exception_tagged_unknown(self):
        """load_klines 抛异常 → 全部 trades 标 UNKNOWN"""
        df = self._make_trades(3)
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.side_effect = Exception("klines load failed")
            result = tag_trades_by_regime(df)
        assert (result["_regime"] == "UNKNOWN").all()

    def test_other_strategy_letter_tagged_by_feats(self):
        """v1.9.0 Plan B: 推荐非 A 策略 → 按 feats 分类 (不再硬标 UNKNOWN)。

        推荐 ["B"] / ["C"] 等不参与 live dispatch 的策略时，
        regime 标签应该反映实际市场状态（SIDE/UP/UNKNOWN），不是硬编码 UNKNOWN。
        """
        df = self._make_trades(3)
        with patch("okx.code.backtest.data_loader.load") as mock_load, \
             patch("okx.code.regime_filter.recommended_strategy") as mock_rs:
            mock_load.return_value = Mock(klines=make_regime_klines("DOWN_STRONG"))
            # v1.9.0 API: list[str] 而非 str
            mock_rs.return_value = (["B"], "BB_RSI_REVERSION", {
                "ret_90d_pct": -15.0, "ema_ratio": 0.87, "ema50": 65000.0,
                "ema200": 75000.0, "last_price": 65000.0, "bars": 250,
            })
            result = tag_trades_by_regime(df)
        # feats: ret=-15 (<-5%) & ema=0.87 (<1.0) → DOWN-class → SIDE 标签
        assert (result["_regime"] == "SIDE").all()

    def test_multiple_windows_shared_regime(self):
        """同一 window_id 共用 regime；不同 window_id 各自 dedup"""
        df = pd.DataFrame({
            "window_id": ["w0"] * 5 + ["w1"] * 3,
            "exit_ts": [1700000000000 + i * 1000 for i in range(8)],
            "symbol": ["BTC-USDT-SWAP"] * 8,
        })
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(klines=make_regime_klines("DOWN_STRONG"))
            result = tag_trades_by_regime(df)
        # 2 unique windows → 2 calls（不是 8 trades × 1）
        assert mock_load.call_count == 2
        assert (result[result["window_id"] == "w0"]["_regime"] == "A").all()
        assert (result[result["window_id"] == "w1"]["_regime"] == "A").all()

    def test_multiple_windows_different_regimes(self):
        """不同 window_id 可有不同 regime"""
        df = pd.DataFrame({
            "window_id": ["w0_down"] * 3 + ["w1_up"] * 3,
            "exit_ts": [1700000000000 + i * 1000 for i in range(6)],
            "symbol": ["BTC-USDT-SWAP"] * 6,
        })
        # 第一次 call 回 DOWN klines → A；第二次回 UP klines → UP
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.side_effect = [
                Mock(klines=make_regime_klines("DOWN_STRONG")),
                Mock(klines=make_regime_klines("UP_STRONG")),
            ]
            result = tag_trades_by_regime(df)
        assert (result[result["window_id"] == "w0_down"]["_regime"] == "A").all()
        assert (result[result["window_id"] == "w1_up"]["_regime"] == "UP").all()

    def test_end_ts_taken_as_window_max(self):
        """window 的 end_ts = 该 window 末笔 exit_ts（max）"""
        df = pd.DataFrame({
            "window_id": ["w0"] * 3,
            "exit_ts": [1000, 5000, 3000],  # max = 5000
            "symbol": ["BTC-USDT-SWAP"] * 3,
        })
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(klines=make_regime_klines("DOWN_STRONG"))
            tag_trades_by_regime(df)
            # 验证传入 load 的 end_ts = 5000 (window max)
            assert mock_load.call_args.kwargs["end_ts"] == 5000

    def test_custom_end_ts_column(self):
        """自定义 end_ts_column 名"""
        df = pd.DataFrame({
            "window_id": ["w0"] * 2,
            "close_ts": [1700000000000, 1700000003000],
            "symbol": ["BTC-USDT-SWAP"] * 2,
        })
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(klines=make_regime_klines("DOWN_STRONG"))
            result = tag_trades_by_regime(df, end_ts_column="close_ts")
        assert (result["_regime"] == "A").all()

    def test_custom_window_id_column(self):
        """自定义 window_id_column 名"""
        df = pd.DataFrame({
            "session": ["s0"] * 2,
            "exit_ts": [1700000000000, 1700000003000],
            "symbol": ["BTC-USDT-SWAP"] * 2,
        })
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(klines=make_regime_klines("DOWN_STRONG"))
            result = tag_trades_by_regime(df, window_id_column="session")
        assert (result["_regime"] == "A").all()

    def test_default_symbol_and_bar(self):
        """默认 symbol='BTC-USDT-SWAP'，bar='1h'"""
        df = self._make_trades(1)
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(klines=make_regime_klines("DOWN_STRONG"))
            tag_trades_by_regime(df)
            args, kwargs = mock_load.call_args
            assert args[0] == "BTC-USDT-SWAP"
            assert args[1] == "1h"
            assert "end_ts" in kwargs

    def test_regime_column_no_nan(self):
        """merge 后 _regime 列无 NaN（fillna=UNKNOWN 兜底）"""
        df = self._make_trades(3)
        with patch("okx.code.backtest.data_loader.load") as mock_load:
            mock_load.return_value = Mock(klines=make_regime_klines("DOWN_STRONG"))
            result = tag_trades_by_regime(df)
        assert result["_regime"].notna().all()
        valid = {"A", "UP", "SIDE", "UNKNOWN"}
        assert set(result["_regime"].unique()).issubset(valid)
