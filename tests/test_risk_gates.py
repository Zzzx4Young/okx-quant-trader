# -*- coding: utf-8 -*-
"""
Risk Gates 单元测试 (P1.1)

设计意图：5 个 portfolio-level risk gates · runner.run() 在开仓前检查。
所有 gate 都基于 aggregate_exposure 输出 + config 阈值。

5 个 gates:
  1. max_total_notional_usdt: total portfolio notional 上限
  2. max_net_directional_bias_pct: |net_direction| / equity 上限 (方向中性约束)
  3. max_single_position_pct: max position notional / equity 上限 (集中度约束)
  4. max_leverage: per-position leverage 上限 (杠杆约束)
  5. max_system_positions_after_manual: manual 满后 system 还能开 N 仓

RED: 这些测试假设 okx.code.risk.RiskGateChecker 已实现。当前不存在 → 全部 fail。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest


def make_position(**overrides) -> dict:
    """构造 position dict（aggregate_exposure 兼容格式）。"""
    base = {
        "symbol": "BTCUSDTSWAP", "direction": "long",
        "size": 0.1, "entry_price": 50000.0, "leverage": 5,
        "strategy": "EMA20_BREAKOUT",
    }
    base.update(overrides)
    return base


class TestRiskGateChecker:
    """okx.code.risk.RiskGateChecker 测试。"""

    # ─── Gate 1 · max_total_notional_usdt ───

    def test_total_notional_under_limit_passes(self):
        """total_notional < limit → 通过。"""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(max_total_notional_usdt=100000.0)
        positions = [make_position(size=0.1, entry_price=50000.0)]  # 5000

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is True
        assert result.failed_gates == []
        assert result.total_notional_usdt == pytest.approx(5000.0)

    def test_total_notional_exceeds_limit_blocks(self):
        """total_notional > limit → 拒 (Gate 1 fail)."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(max_total_notional_usdt=10000.0)
        positions = [
            make_position(size=0.2, entry_price=50000.0),  # 10000
            make_position(symbol="ETHUSDTSWAP", size=1.0, entry_price=2000.0),  # 2000
        ]  # total = 12000

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is False
        assert any("max_total_notional_usdt" in g for g in result.failed_gates)
        assert any("10000" in r for r in result.reasons)  # limit value in reason

    # ─── Gate 2 · max_net_directional_bias_pct ───

    def test_net_bias_under_limit_passes(self):
        """|net_direction| / equity < limit → 通过."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(
            max_net_directional_bias_pct=0.5,
            max_system_positions_after_manual=10,  # 隔离 Gate 5
        )
        positions = [
            make_position(size=0.1, entry_price=50000.0, direction="long"),  # +5000
            make_position(symbol="ETHUSDTSWAP", size=1.0, entry_price=2000.0, direction="short"),  # -2000
        ]
        # net = +3000, equity = 10000, bias = 0.3 (< 0.5) ✓

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is True
        assert result.net_direction_usdt == pytest.approx(3000.0)

    def test_net_bias_exceeds_limit_blocks(self):
        """|net_direction| / equity > limit → 拒 (Gate 2 fail)."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(max_net_directional_bias_pct=0.3)
        positions = [
            make_position(size=0.1, entry_price=50000.0, direction="long"),  # +5000
        ]
        # net = +5000, equity = 10000, bias = 0.5 (> 0.3) ✗

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is False
        assert any("max_net_directional_bias_pct" in g for g in result.failed_gates)

    def test_net_bias_zero_with_offsetting_positions_passes(self):
        """long + short 完全对冲 → net ≈ 0 → bias < limit → 通过."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(
            max_net_directional_bias_pct=0.5,
            max_system_positions_after_manual=10,  # 隔离 Gate 5
        )
        positions = [
            make_position(size=0.1, entry_price=50000.0, direction="long"),  # +5000
            make_position(symbol="ETHUSDTSWAP", size=2.5, entry_price=2000.0, direction="short"),  # -5000
        ]

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is True

    # ─── Gate 3 · max_single_position_pct ───

    def test_single_position_under_limit_passes(self):
        """max position / equity < limit → 通过."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(max_single_position_pct=0.5)
        positions = [
            make_position(size=0.05, entry_price=50000.0),  # 2500 / 10000 = 0.25
        ]

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is True

    def test_single_position_exceeds_limit_blocks(self):
        """max position / equity > limit → 拒 (Gate 3 fail)."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(max_single_position_pct=0.3)
        positions = [
            make_position(size=0.1, entry_price=50000.0),  # 5000 / 10000 = 0.5 > 0.3
        ]

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is False
        assert any("max_single_position_pct" in g for g in result.failed_gates)

    # ─── Gate 4 · max_leverage ───

    def test_leverage_under_limit_passes(self):
        """all position leverage ≤ limit → 通过."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(
            max_leverage=10,
            max_system_positions_after_manual=10,  # 隔离 Gate 5
            max_net_directional_bias_pct=10.0,      # 隔离 Gate 2（两仓都 LONG → net 100% bias）
        )
        positions = [
            make_position(leverage=5),
            make_position(symbol="ETHUSDTSWAP", leverage=3),
        ]

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is True

    def test_leverage_exceeds_limit_blocks(self):
        """某仓 leverage > limit → 拒 (Gate 4 fail)."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(max_leverage=5)
        positions = [
            make_position(leverage=5),
            make_position(symbol="ETHUSDTSWAP", leverage=10),  # > 5
        ]

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is False
        assert any("max_leverage" in g for g in result.failed_gates)

    # ─── Gate 5 · max_system_positions_after_manual ───

    def test_no_manual_positions_system_can_open(self):
        """0 manual + 0 system → 系统仍可开 N 个（受 max_concurrent_positions 约束)."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(max_system_positions_after_manual=1, max_concurrent_positions=3)
        positions = []

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        # system capacity OK（无仓）
        # 但 max_concurrent_positions 也参与 → 3 空 → system can open up to 3
        assert result.passed is True

    def test_manual_full_system_capacity_limited(self):
        """manual 满 = 3 → system 仍可开 max_system_positions_after_manual 个."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(
            max_system_positions_after_manual=1,
            max_concurrent_positions=3,
            max_net_directional_bias_pct=10.0,  # 隔离 Gate 2（3 long 仓会 bias 超限）
            max_total_notional_usdt=1e9,        # 隔离 Gate 1
            max_single_position_pct=10.0,        # 隔离 Gate 3
        )
        # 仓需要 balance 才不超 bias gate
        positions = [
            make_position(strategy="EXTERNAL_WEB_SYNC", direction="long"),
            make_position(symbol="ETHUSDTSWAP", strategy="EXTERNAL_WEB_SYNC", direction="short"),
            make_position(symbol="SOLUSDTSWAP", strategy="EXTERNAL_WEB_SYNC", direction="long"),
        ]
        # 3 manual, 0 system → system capacity = 1 (per gate 5)

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is True  # gate 5 PASSED（系统可开 1）
        assert result.system_position_capacity_remaining == 1

    def test_system_position_count_exceeds_capacity_blocks(self):
        """manual=3 + system=2 > system_capacity=1 → 拒."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(
            max_system_positions_after_manual=1,
            max_concurrent_positions=5,
        )
        positions = [
            make_position(strategy="EXTERNAL_WEB_SYNC"),
            make_position(symbol="ETHUSDTSWAP", strategy="EXTERNAL_WEB_SYNC"),
            make_position(symbol="SOLUSDTSWAP", strategy="EXTERNAL_WEB_SYNC"),
            make_position(symbol="BTCUSDTSWAP2", strategy="EMA20_BREAKOUT"),
            make_position(symbol="ETHUSDTSWAP2", strategy="EMA20_BREAKOUT"),
        ]
        # 3 manual + 2 system = 5 total · 但 system capacity = 1 → 拒

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is False
        assert any("max_system_positions_after_manual" in g for g in result.failed_gates)

    # ─── 多 gate 同时 fail ───

    def test_multiple_gates_fail_simultaneously(self):
        """多个 gate 同时 fail → failed_gates 列全, reasons 详细."""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(
            max_total_notional_usdt=1000.0,  # total 2000 → fail
            max_net_directional_bias_pct=0.1,  # bias 0.2 > 0.1 → fail
            max_single_position_pct=0.15,  # 0.2 > 0.15 → fail
        )
        positions = [
            make_position(size=0.04, entry_price=50000.0),  # 2000, 0.2 of equity
        ]

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        assert result.passed is False
        assert len(result.failed_gates) == 3
        assert any("max_total_notional_usdt" in g for g in result.failed_gates)
        assert any("max_net_directional_bias_pct" in g for g in result.failed_gates)
        assert any("max_single_position_pct" in g for g in result.failed_gates)

    # ─── current demo 实证 ───

    def test_current_demo_portfolio_passes_or_fails_consistently(self):
        """当前 demo 满仓 3 manual → gate 5 PASS (有 system capacity 1)。"""
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(
            max_total_notional_usdt=200000.0,        # demo ~19K < 200K → pass
            max_net_directional_bias_pct=10.0,       # demo bias 1.32 < 10.0 → pass (宽松)
            max_single_position_pct=10.0,            # demo BTC=1.40 < 10.0 → pass (宽松)
            max_leverage=20,                        # demo ETH short 10x < 20 → pass
            max_system_positions_after_manual=1,
            max_concurrent_positions=3,
        )
        # demo 3 manual
        positions = [
            make_position(symbol="BTCUSDTSWAP", direction="long",
                         size=0.22, entry_price=63892.01, leverage=5,
                         strategy="EXTERNAL_WEB_SYNC"),
            make_position(symbol="ETHUSDTSWAP", direction="long",
                         size=1.09, entry_price=1926.20, leverage=5,
                         strategy="EXTERNAL_WEB_SYNC"),
            make_position(symbol="ETHUSDTSWAP", direction="short",
                         size=1.59, entry_price=1882.59, leverage=10,
                         strategy="EXTERNAL_WEB_SYNC"),
        ]

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        # 宽松 config 下全 pass
        assert result.passed is True
        assert result.system_position_capacity_remaining == 1
        assert result.total_notional_usdt == pytest.approx(19149.0, rel=1e-2)