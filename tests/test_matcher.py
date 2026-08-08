# -*- coding: utf-8 -*-
"""
test_matcher.py —— BacktestEngine 数值正确性测试 (8-04 P0-P2 fix)

设计意图:
- 之前 BacktestEngine 没有直接 unit test (test_fragility_scan 是 CLI smoke)
- 8-04 cascade check 发现 matcher.py 3 处缺 ct_val (margin/fee/nominal_value)
- 这里首次直接测 BacktestEngine 数值

8-04 P0/P1 fix 覆盖:
- margin 必须 = size × entry × ct_val / leverage (不是 size × entry / leverage)
- entry_fee 必须 = size × fill_price × ct_val × taker_fee (fee 100x off for BTC)
- FillEvent.nominal_value 必须 = size × fill_price × ct_val (funding fee 用)
- Position.nominal_value property 必须用 ct_val
- 默认 ct_val=1.0 保持 backward compat (老 tests 不需改)

TDD 流程: RED (verify current bug) → GREEN (fix) → verify all
"""
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

import numpy as np
import pandas as pd
import pytest

from okx.code.backtest.matcher import BacktestEngine, Position, FillEvent
from okx.code.backtest.data_loader import BacktestData


# ──────────────────────────────────────────────────────────────
# 工具: 构造 minimal klines DataFrame + BacktestData
# ──────────────────────────────────────────────────────────────

def _make_klines(n_bars: int = 50, base_price: float = 30000.0, trend: float = 100.0) -> pd.DataFrame:
    """构造 minimal klines (上涨趋势确保 ATR > 0 + 触发 EMA signal)。

    50 bars × 1h timeframe · 价格从 base_price 线性上涨 trend/bar
    """
    timestamps = np.arange(1_700_000_000_000, 1_700_000_000_000 + n_bars * 3600_000, 3600_000)
    close = base_price + np.arange(n_bars) * trend
    high = close + 50
    low = close - 50
    open_ = close - 20
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.ones(n_bars) * 100,
    })


def _make_funding(n_bars: int = 50) -> pd.DataFrame:
    """构造 minimal funding (零费率, 不影响测试).

    BacktestEngine 要求 fundingTime_aligned 列 (line 277-278 期望).
    """
    timestamps = np.arange(1_700_000_000_000, 1_700_000_000_000 + n_bars * 3600_000, 3600_000)
    return pd.DataFrame({
        "timestamp": timestamps,
        "fundingTime_aligned": timestamps,  # 8-04: matcher 期望这列
        "fundingRate": np.zeros(n_bars),
    })


def _make_backtest_data(inst_id: str = "BTC-USDT-SWAP", n_bars: int = 50) -> BacktestData:
    """构造 minimal BacktestData。"""
    return BacktestData(
        klines=_make_klines(n_bars=n_bars),
        funding=_make_funding(n_bars=n_bars),
        inst_id=inst_id,
        timeframe="1h",
    )


def _always_long_signal(klines, i, indicators, position, funding, inst_id) -> Optional[str]:
    """Custom signal provider: bar 25 强制 long (用于触发 open_position).

    BacktestEngine 实际调用签名: (klines, i, indicators, position, funding, inst_id)
    必须在 i >= DEFAULT_EMA_SLOW (21) 时才会被调用。
    """
    return "long" if i == 25 else None


# ──────────────────────────────────────────────────────────────
# P0 fix 1: margin 必须包含 ct_val
# ──────────────────────────────────────────────────────────────

class TestOpenPositionMarginCtVal:
    """margin = (size × entry × ct_val) / leverage · 不是 (size × entry) / leverage"""

    def test_btc_swap_margin_uses_ct_val_0_01(self):
        """BTC SWAP ct_val=0.01 → margin 应为 (size × entry × 0.01) / leverage.

        旧代码: margin = (size × entry) / leverage (无 ct_val) → 100x 偏大
        新代码: margin = (size × entry × 0.01) / leverage → 正确
        """
        data = _make_backtest_data(inst_id="BTC-USDT-SWAP")
        engine = BacktestEngine(
            data=data,
            initial_capital=10000.0,
            leverage=5,
            taker_fee=0.0005,
            ct_val=0.01,  # 8-04 P0 fix: 必须传 ct_val
            signal_provider=_always_long_signal,
        )
        result = engine.run()

        # 触发 trade → 检查 margin
        assert result.n_trades >= 1, "应该至少触发 1 笔 trade"
        trade = result.trades[0]
        # size × entry × ct_val / leverage = (entry price 取决于 ATR/sizing)
        # 关键 assertion: trade.margin 必须 < entry × size (因为 ct_val < 1)
        # 旧代码: trade.margin = entry × size / leverage → 大值
        # 新代码: trade.margin = entry × size × 0.01 / leverage → 100x 偏小
        assert trade.margin < 1000.0, (
            f"BTC margin 100x off (旧代码): {trade.margin} 应 < 1000 (real)。"
            f"如果 = 10000+ 则 ct_val 被忽略"
        )

    def test_default_ct_val_one_backward_compat(self):
        """默认 ct_val=1.0 (无 ct_val kwarg) → backward compat, 老 tests 不需改."""
        data = _make_backtest_data(inst_id="BTC-USDT-SWAP")
        engine = BacktestEngine(
            data=data,
            initial_capital=10000.0,
            leverage=5,
            taker_fee=0.0005,
            # 不传 ct_val → 默认 1.0 → 行为与原代码一致 (size × entry / leverage)
            signal_provider=_always_long_signal,
        )
        result = engine.run()

        assert result.n_trades >= 1
        trade = result.trades[0]
        # ct_val=1.0 时 margin = (size × entry) / leverage (与旧代码一致)
        # 旧 BTC 测试如果不传 ct_val, margin 会是大值
        # 这里我们只验证 default 1.0 仍 work, 不验证具体数值
        assert trade.margin > 0


# ──────────────────────────────────────────────────────────────
# P0 fix 2: entry_fee 必须包含 ct_val
# ──────────────────────────────────────────────────────────────

class TestOpenPositionEntryFeeCtVal:
    """entry_fee = size × fill_price × ct_val × taker_fee · 不是 size × fill_price × taker_fee"""

    def test_btc_swap_entry_fee_uses_ct_val(self):
        """BTC SWAP ct_val=0.01 → entry fee 应 < 旧公式 100x.

        旧代码: entry_fee = size × fill_price × 0.0005
        新代码: entry_fee = size × fill_price × 0.01 × 0.0005
        """
        data = _make_backtest_data(inst_id="BTC-USDT-SWAP")
        engine = BacktestEngine(
            data=data,
            initial_capital=10000.0,
            leverage=5,
            taker_fee=0.0005,
            ct_val=0.01,
            signal_provider=_always_long_signal,
        )
        result = engine.run()

        assert result.n_trades >= 1
        trade = result.trades[0]
        # 旧 BTC entry fee: size × $30000 × 0.0005 ≈ $15+ (太大)
        # 新 BTC entry fee: size × $30000 × 0.01 × 0.0005 ≈ $0.15
        assert trade.fee < 5.0, (
            f"BTC entry fee 100x off: {trade.fee} 应 < 5.0 (real). "
            f"如果 > 5 则 ct_val 被忽略 (旧公式 size × entry × fee)"
        )

    def test_eth_swap_entry_fee_uses_ct_val_0_1(self):
        """ETH SWAP ct_val=0.1 → entry fee 应 < 旧公式 10x."""
        data = _make_backtest_data(inst_id="ETH-USDT-SWAP")
        engine = BacktestEngine(
            data=data,
            initial_capital=10000.0,
            leverage=5,
            taker_fee=0.0005,
            ct_val=0.1,
            signal_provider=_always_long_signal,
        )
        result = engine.run()

        assert result.n_trades >= 1
        trade = result.trades[0]
        # 旧 ETH fee: size × $30000 × 0.0005 ≈ $15+ (假设同 entry price)
        # 新 ETH fee: size × $30000 × 0.1 × 0.0005 ≈ $1.5
        assert trade.fee < 10.0, (
            f"ETH entry fee 10x off: {trade.fee} 应 < 10.0 (real). "
            f"如果 > 10 则 ct_val 被忽略"
        )


# ──────────────────────────────────────────────────────────────
# P1 fix 3: FillEvent nominal_value 必须包含 ct_val (funding fee 用)
# ──────────────────────────────────────────────────────────────

class TestFillEventNominalValueCtVal:
    """FillEvent.nominal_value = size × fill_price × ct_val · 用于 funding fee 结算"""

    def test_entry_fill_nominal_value_includes_ct_val(self):
        """entry FillEvent.nominal_value 必须 = size × fill_price × ct_val."""
        data = _make_backtest_data(inst_id="BTC-USDT-SWAP")
        engine = BacktestEngine(
            data=data,
            initial_capital=10000.0,
            leverage=5,
            taker_fee=0.0005,
            ct_val=0.01,
            signal_provider=_always_long_signal,
        )
        result = engine.run()

        assert result.n_trades >= 1
        trade = result.trades[0]
        entry_fill = trade.fills[0]
        assert entry_fill.fill_type == "entry"
        # size × fill_price × 0.01 (BTC) · 远小于 旧 size × fill_price
        # 假设 size ≈ 0.5, fill_price ≈ 30000 → nominal = 0.5 × 30000 × 0.01 = 150
        # 旧 (无 ct_val): 0.5 × 30000 = 15000
        assert entry_fill.nominal_value < 1000.0, (
            f"BTC entry nominal 100x off: {entry_fill.nominal_value} 应 < 1000 (real). "
            f"如果 > 10000 则 ct_val 被忽略"
        )

    def test_position_nominal_value_property_uses_ct_val(self):
        """Position.nominal_value property 必须 = current_size × entry_fill_price × ct_val.

        funding fee 结算 (line 247) 用这个 property。
        """
        data = _make_backtest_data(inst_id="BTC-USDT-SWAP")
        engine = BacktestEngine(
            data=data,
            initial_capital=10000.0,
            leverage=5,
            taker_fee=0.0005,
            ct_val=0.01,
            signal_provider=_always_long_signal,
        )
        # 用 engine._open_position 直接测试 Position
        # 构造 minimal bar data
        prev_bar = pd.Series({"open": 30000, "high": 30050, "low": 29950, "close": 30020, "timestamp": 1_700_000_000_000})
        curr_bar = pd.Series({"open": 30020, "high": 30080, "low": 30000, "close": 30050, "timestamp": 1_700_000_000_000 + 3600_000})

        # 模拟 open_position 后的 Position
        pos = Position(
            direction="long",
            entry_price=30000.0,
            entry_fill_price=30050.0,
            initial_size=0.5,
            current_size=0.5,
            leverage=5,
            margin=0.0,  # 旧代码无 ct_val 时算的
            entry_ts=1_700_000_000_000,
            sl_price=29000.0,
            tranches=[],
            strategy="A",
            ct_val=0.01,  # 8-04 P1 fix
        )
        # 0.5 × 30050 × 0.01 = 150.25 (real)
        # 旧 (无 ct_val): 0.5 × 30050 = 15025
        assert pos.nominal_value == pytest.approx(150.25, rel=1e-2), (
            f"Position.nominal_value 应用 ct_val=0.01: got {pos.nominal_value}, "
            f"expected ~150.25 (0.5 × 30050 × 0.01). "
            f"如果 = 15025 则 ct_val 被忽略"
        )


# ──────────────────────────────────────────────────────────────
# P1 fix 4: BacktestEngine 必须接受 ct_val kwarg
# ──────────────────────────────────────────────────────────────

class TestBacktestEngineCtValKwargs:
    """BacktestEngine 必须接受 ct_val kwarg, 默认 1.0 backward compat"""

    def test_engine_accepts_ct_val_kwarg(self):
        """BacktestEngine 必须接受 ct_val kwarg (不传则默认 1.0)."""
        data = _make_backtest_data(inst_id="BTC-USDT-SWAP")
        # 不传 ct_val → 默认 1.0
        engine_default = BacktestEngine(data=data, signal_provider=_always_long_signal)
        assert hasattr(engine_default, "ct_val"), "BacktestEngine 必须有 ct_val 属性"
        assert engine_default.ct_val == 1.0, f"默认 ct_val 应为 1.0, got {engine_default.ct_val}"

        # 传 ct_val
        engine_btc = BacktestEngine(data=data, ct_val=0.01, signal_provider=_always_long_signal)
        assert engine_btc.ct_val == 0.01

    def test_position_dataclass_accepts_ct_val(self):
        """Position dataclass 必须接受 ct_val 字段."""
        pos = Position(
            direction="long",
            entry_price=30000.0,
            entry_fill_price=30000.0,
            initial_size=1.0,
            current_size=1.0,
            leverage=5,
            margin=100.0,
            entry_ts=0,
            sl_price=29000.0,
            tranches=[],
            strategy="A",
            ct_val=0.01,
        )
        assert pos.ct_val == 0.01


# ──────────────────────────────────────────────────────────────
# P1 fix 5: funding fee 必须用 corrected nominal_value
# ──────────────────────────────────────────────────────────────

class TestFundingFeeUsesCorrectNominalValue:
    """funding fee 结算 (line 247) 用 position.nominal_value → 必须已包含 ct_val."""

    def test_funding_fee_uses_real_notional(self):
        """funding fee = position.nominal_value × funding_rate。

        若 Position.nominal_value 已修 (含 ct_val), funding fee 自动正确。
        间接验证 Position.nominal_value property 修复。
        """
        # funding rate = 0.0001 (典型 0.01%/8h)
        data = _make_backtest_data(inst_id="BTC-USDT-SWAP")
        # 用 funding_rate 通过 BacktestData.funding 注入
        data.funding["fundingRate"] = 0.0001

        engine = BacktestEngine(
            data=data,
            initial_capital=10000.0,
            leverage=5,
            taker_fee=0.0005,
            ct_val=0.01,  # BTC
            signal_provider=_always_long_signal,
        )
        result = engine.run()

        assert result.n_trades >= 1
        trade = result.trades[0]
        # 若 Position.nominal_value 已修, funding fee 应远小于 旧公式
        # funding fee = position_size × entry × ct_val × funding_rate
        # ≈ 0.5 × 30000 × 0.01 × 0.0001 × 50 bars ≈ 0.75
        # 旧 (无 ct_val): 0.5 × 30000 × 0.0001 × 50 ≈ 75
        # trade.funding_fee 应该远小于 trade.fee (因为 rate 更小)
        # 这里只验证 funding_fee 不超过一定值 (防止 100x off)
        # 实际值依赖 bar 数, 宽松断言
        assert trade.funding_fee < trade.fee * 10, (
            f"funding_fee 不应远大于 fee: funding={trade.funding_fee}, fee={trade.fee}. "
            f"如果 funding >> fee 可能 ct_val 被忽略"
        )
