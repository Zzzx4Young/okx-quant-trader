# -*- coding: utf-8 -*-
"""
Portfolio Risk Aggregator 单元测试 (P0)

设计意图：聚合所有持仓（manual + system）→ 一组风险指标。
让 runner.run() 能基于 total book 做 risk gates（不是只看仓位数）。

RED: 这些测试假设 okx.code.risk.PortfolioRisk + aggregate_exposure 已实现。
当前不存在 → 全部 fail。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest


def make_position(
    *,
    symbol: str = "BTCUSDTSWAP",
    direction: str = "long",
    size: float = 0.1,
    entry_price: float = 50000.0,
    leverage: int = 5,
    strategy: str = "EMA20_BREAKOUT",
    opened_at: str = "2026-08-03T12:00:00Z",
) -> dict:
    """工厂函数：构造 position dict（与 state/portfolio.json::positions 兼容）。"""
    return {
        "symbol": symbol,
        "direction": direction,
        "size": size,
        "entry_price": entry_price,
        "leverage": leverage,
        "strategy": strategy,
        "opened_at": opened_at,
        "sl_price": entry_price * 0.99 if direction == "long" else entry_price * 1.01,
        "tp_price": entry_price * 1.02 if direction == "long" else entry_price * 0.98,
    }


class TestAggregateExposure:
    """okx.code.risk.aggregate_exposure 测试。"""

    def test_empty_positions_returns_zero_risk(self):
        """空 positions 列表 → 所有指标为 0。"""
        from okx.code.risk import aggregate_exposure

        risk = aggregate_exposure([])

        assert risk.position_count == 0
        assert risk.total_notional_usdt == 0.0
        assert risk.long_notional_usdt == 0.0
        assert risk.short_notional_usdt == 0.0
        assert risk.net_direction_usdt == 0.0
        assert risk.gross_exposure_usdt == 0.0
        assert risk.leverage_max == 0
        assert risk.leverage_avg == 0.0
        assert risk.symbol_concentration == {}
        assert risk.has_manual_position is False
        assert risk.has_system_position is False
        assert risk.manual_notional_usdt == 0.0
        assert risk.system_notional_usdt == 0.0

    def test_single_long_position_calculates_notional(self):
        """1 个 long 仓 → notional = size * entry_price, long_notional = total。"""
        from okx.code.risk import aggregate_exposure

        pos = make_position(
            symbol="BTCUSDTSWAP", direction="long",
            size=0.5, entry_price=60000.0, leverage=5,
        )
        risk = aggregate_exposure([pos])

        assert risk.position_count == 1
        assert risk.total_notional_usdt == pytest.approx(30000.0)
        assert risk.long_notional_usdt == pytest.approx(30000.0)
        assert risk.short_notional_usdt == 0.0
        assert risk.net_direction_usdt == pytest.approx(30000.0)
        assert risk.gross_exposure_usdt == pytest.approx(30000.0)
        assert risk.leverage_max == 5
        assert risk.leverage_avg == pytest.approx(5.0)

    def test_single_short_position(self):
        """1 个 short 仓 → short_notional > 0, net = -short。"""
        from okx.code.risk import aggregate_exposure

        pos = make_position(
            symbol="ETHUSDTSWAP", direction="short",
            size=2.0, entry_price=2000.0, leverage=10,
        )
        risk = aggregate_exposure([pos])

        assert risk.position_count == 1
        assert risk.total_notional_usdt == pytest.approx(4000.0)
        assert risk.long_notional_usdt == 0.0
        assert risk.short_notional_usdt == pytest.approx(4000.0)
        assert risk.net_direction_usdt == pytest.approx(-4000.0)
        assert risk.leverage_max == 10

    def test_mixed_long_short_computes_net_and_gross(self):
        """多仓 long+short → net = long - short, gross = long + short。"""
        from okx.code.risk import aggregate_exposure

        long_pos = make_position(
            symbol="BTCUSDTSWAP", direction="long",
            size=0.5, entry_price=60000.0,
        )  # notional = 30000
        short_pos = make_position(
            symbol="ETHUSDTSWAP", direction="short",
            size=2.0, entry_price=2000.0,
        )  # notional = 4000

        risk = aggregate_exposure([long_pos, short_pos])

        assert risk.position_count == 2
        assert risk.total_notional_usdt == pytest.approx(34000.0)
        assert risk.long_notional_usdt == pytest.approx(30000.0)
        assert risk.short_notional_usdt == pytest.approx(4000.0)
        assert risk.net_direction_usdt == pytest.approx(26000.0)
        assert risk.gross_exposure_usdt == pytest.approx(34000.0)

    def test_manual_position_detected_via_strategy_field(self):
        """strategy=EXTERNAL_WEB_SYNC → has_manual_position=True, manual_notional > 0。"""
        from okx.code.risk import aggregate_exposure

        manual_pos = make_position(strategy="EXTERNAL_WEB_SYNC", size=0.2, entry_price=60000.0)
        system_pos = make_position(strategy="EMA20_BREAKOUT", size=0.1, entry_price=60000.0)

        risk = aggregate_exposure([manual_pos, system_pos])

        assert risk.position_count == 2
        assert risk.has_manual_position is True
        assert risk.has_system_position is True
        assert risk.manual_notional_usdt == pytest.approx(12000.0)  # 0.2 * 60000
        assert risk.system_notional_usdt == pytest.approx(6000.0)   # 0.1 * 60000

    def test_manual_only_positions(self):
        """全部 manual → has_system_position=False。"""
        from okx.code.risk import aggregate_exposure

        positions = [
            make_position(strategy="EXTERNAL_WEB_SYNC", size=0.1),
            make_position(strategy="MANUAL_OKX_WEB", size=0.2),
        ]

        risk = aggregate_exposure(positions)

        assert risk.has_manual_position is True
        assert risk.has_system_position is False
        assert risk.manual_notional_usdt == pytest.approx(0.1*50000 + 0.2*50000)

    def test_symbol_concentration_tracks_per_symbol_notional(self):
        """symbol_concentration dict 应该记录每个 symbol 的 notional 聚合。"""
        from okx.code.risk import aggregate_exposure

        positions = [
            make_position(symbol="BTCUSDTSWAP", size=0.1, entry_price=60000.0),  # 6000
            make_position(symbol="BTCUSDTSWAP", size=0.2, entry_price=60000.0),  # 12000
            make_position(symbol="ETHUSDTSWAP", size=2.0, entry_price=2000.0),   # 4000
        ]

        risk = aggregate_exposure(positions)

        assert "BTCUSDTSWAP" in risk.symbol_concentration
        assert risk.symbol_concentration["BTCUSDTSWAP"] == pytest.approx(18000.0)
        assert risk.symbol_concentration["ETHUSDTSWAP"] == pytest.approx(4000.0)

    def test_leverage_max_takes_max_across_positions(self):
        """leverage_max = 所有仓 leverage 的 max, leverage_avg = mean。"""
        from okx.code.risk import aggregate_exposure

        positions = [
            make_position(leverage=5),
            make_position(leverage=10),
            make_position(leverage=3),
        ]

        risk = aggregate_exposure(positions)

        assert risk.leverage_max == 10
        assert risk.leverage_avg == pytest.approx((5 + 10 + 3) / 3)

    def test_size_zero_position_skipped(self):
        """size=0 的仓应该被跳过（不影响 notional 计算）。"""
        from okx.code.risk import aggregate_exposure

        positions = [
            make_position(size=0.0, entry_price=50000.0),  # 仓已平
            make_position(size=0.1, entry_price=50000.0),  # 有效仓
        ]

        risk = aggregate_exposure(positions)

        assert risk.position_count == 2  # count includes size=0
        assert risk.total_notional_usdt == pytest.approx(5000.0)  # 只算 size>0

    def test_current_demo_portfolio_aggregate(self):
        """实证：当前 demo portfolio (3 manual positions) 的 aggregate 结果。"""
        from okx.code.risk import aggregate_exposure

        # 当前 demo 状态（从 state/portfolio.json 提取）
        positions = [
            {
                "symbol": "BTCUSDTSWAP", "direction": "long",
                "size": 0.22, "entry_price": 63892.01, "leverage": 5,
                "strategy": "EXTERNAL_WEB_SYNC",
            },
            {
                "symbol": "ETHUSDTSWAP", "direction": "long",
                "size": 1.09, "entry_price": 1926.20, "leverage": 5,
                "strategy": "EXTERNAL_WEB_SYNC",
            },
            {
                "symbol": "ETHUSDTSWAP", "direction": "short",
                "size": 1.59, "entry_price": 1882.59, "leverage": 10,
                "strategy": "EXTERNAL_WEB_SYNC",
            },
        ]

        risk = aggregate_exposure(positions)

        # BTC long: 0.22 * 63892.01 = 14056.24
        # ETH long: 1.09 * 1926.20 = 2099.56
        # ETH short: 1.59 * 1882.59 = 2993.32
        expected_total = 14056.24 + 2099.56 + 2993.32  # ~19149
        expected_long = 14056.24 + 2099.56  # ~16155
        expected_net = expected_long - 2993.32  # ~13162

        assert risk.position_count == 3
        assert risk.has_manual_position is True
        assert risk.has_system_position is False
        assert risk.total_notional_usdt == pytest.approx(expected_total, rel=1e-3)
        assert risk.long_notional_usdt == pytest.approx(expected_long, rel=1e-3)
        assert risk.short_notional_usdt == pytest.approx(2993.32, rel=1e-3)
        assert risk.net_direction_usdt == pytest.approx(expected_net, rel=1e-3)
        assert risk.leverage_max == 10
        # ETH 集中度：BTC=14056, ETH=2099+2993=5092
        # ETH/Total = 5092/19149 ≈ 26.6%
        # BTC/Total = 14056/19149 ≈ 73.4%
        assert risk.symbol_concentration["BTCUSDTSWAP"] == pytest.approx(14056.24, rel=1e-3)
        assert risk.symbol_concentration["ETHUSDTSWAP"] == pytest.approx(5092.88, rel=1e-3)