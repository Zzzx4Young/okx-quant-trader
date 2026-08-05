# -*- coding: utf-8 -*-
"""
P1 audit #3 · PortfolioRisk 加 manual_count/system_count 字段 (2026-08-05)

════════════════════════════════════════════════════════════════════
目的: 关闭 Iron Rule #5 实证的 silent drift 入口。

Bug 背景 (8-04 audit 发现):
  code/risk.py::aggregate_exposure() 用 `valid = [size>0]` 过滤 → 算 manual/system notional
  code/risk.py::RiskGateChecker.check_all_gates() 独立算 manual_count/system_count (all positions)

  → 两条独立计算路径 → drift (size=0 zombie 仓位时尤其明显)

修复 (Nixil 23:29 拍板):
  - PortfolioRisk dataclass 加 manual_count + system_count 字段
  - aggregate_exposure() 一处计算并写入字段 (single source of truth)
  - check_all_gates() 读字段, 不再独立计

Semantic 决策 (8-04 scholar evaluation):
  - manual_count / system_count = count ALL positions (含 size=0 zombie) for "position slot reservation"
  - 与 check_all_gates 原行为一致 (capacity 保留 slot 直到 portfolio.json cleanup)
  - manual_notional_usdt / system_notional_usdt = 仅 size>0 valid 仓位的 notional
════════════════════════════════════════════════════════════════════
"""

import pytest

from okx.code.risk import PortfolioRisk, aggregate_exposure, RiskGateChecker, RiskGateConfig


# ────────────── Fixtures ──────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    from okx.code.config import Config
    Config._instance = None
    yield
    Config._instance = None


def _make_position(
    strategy: str,
    size: float = 1.0,
    direction: str = "long",
    symbol: str = "BTCUSDTSWAP",
    leverage: int = 3,
    ct_val: float = 0.01,
    entry_price: float = 100.0,
) -> dict:
    """构造一个 OKX 仓位 dict (test fixture)"""
    return {
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "size": size,
        "leverage": leverage,
        "ct_val": ct_val,
        "strategy": strategy,
    }


# ────────────── Tests ──────────────

class TestPortfolioRiskCountFields:
    """PortfolioRisk dataclass 必须暴露 manual_count + system_count 字段"""

    def test_portfolio_risk_has_manual_count_field(self):
        """PortfolioRisk 必须有 manual_count 字段"""
        pr = PortfolioRisk()
        assert hasattr(pr, "manual_count"), (
            "❌ PortfolioRisk.manual_count 字段缺失. "
            "修复: 在 code/risk.py::PortfolioRisk 加 manual_count: int = 0"
        )
        assert isinstance(pr.manual_count, int)
        assert pr.manual_count == 0, "默认 0"

    def test_portfolio_risk_has_system_count_field(self):
        """PortfolioRisk 必须有 system_count 字段"""
        pr = PortfolioRisk()
        assert hasattr(pr, "system_count"), (
            "❌ PortfolioRisk.system_count 字段缺失. "
            "修复: 在 code/risk.py::PortfolioRisk 加 system_count: int = 0"
        )
        assert isinstance(pr.system_count, int)
        assert pr.system_count == 0, "默认 0"

    def test_portfolio_risk_count_fields_total_equals_position_count(self):
        """manual_count + system_count 必须 == position_count (不变量)"""
        pr = PortfolioRisk(position_count=5, manual_count=3, system_count=2)
        assert pr.manual_count + pr.system_count == pr.position_count


class TestAggregateExposurePopulatesCountFields:
    """aggregate_exposure 必须 populate manual_count + system_count"""

    def test_aggregate_exposure_manual_count_from_all_positions(self):
        """manual_count 应包含 size=0 zombie (与 check_all_gates 一致语义)"""
        positions = [
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=1.0),
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=0.0),  # zombie
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=2.0),
        ]
        risk = aggregate_exposure(positions)
        assert risk.manual_count == 3, (
            f"❌ manual_count 应=3 (含 zombie), got {risk.manual_count}. "
            f"说明 aggregate_exposure 用 valid filter 而不是 all positions"
        )

    def test_aggregate_exposure_system_count_from_all_positions(self):
        """system_count 应包含 size=0 zombie"""
        positions = [
            _make_position(strategy="EMA20_BREAKOUT", size=1.0),
            _make_position(strategy="EMA20_BREAKOUT", size=0.0),  # zombie
            _make_position(strategy="A", size=2.0),
        ]
        risk = aggregate_exposure(positions)
        assert risk.system_count == 3

    def test_aggregate_exposure_mixed_counts(self):
        """混合 manual + system 仓位"""
        positions = [
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=1.0),
            _make_position(strategy="EMA20_BREAKOUT", size=2.0),
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=0.0),  # zombie manual
            _make_position(strategy="A", size=0.0),                  # zombie system
        ]
        risk = aggregate_exposure(positions)
        assert risk.manual_count == 2, "2 EXTERNAL (含 zombie)"
        assert risk.system_count == 2, "2 system (含 zombie)"
        assert risk.position_count == 4

    def test_aggregate_exposure_count_notional_only_valid(self):
        """manual_notional / system_notional 仍仅 valid 仓位 (size>0)"""
        # semantic: count 包含 zombie (slot reservation), notional 仅 valid
        positions = [
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=1.0, entry_price=100.0),
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=0.0, entry_price=100.0),  # zombie
        ]
        risk = aggregate_exposure(positions)
        assert risk.manual_count == 2  # both count
        assert risk.manual_notional_usdt == pytest.approx(1.0, rel=1e-3)  # 1*100*0.01 (zombie=0)

    def test_aggregate_exposure_zero_positions(self):
        """空 positions 列表 → 全 0"""
        risk = aggregate_exposure([])
        assert risk.manual_count == 0
        assert risk.system_count == 0
        assert risk.position_count == 0


class TestCheckAllGatesReadsCountFields:
    """check_all_gates 必须读 PortfolioRisk.manual_count + system_count (不独立计)"""

    def test_check_all_gates_uses_aggregate_exposure_count_fields(self):
        """check_all_gates 结果必须与 aggregate_exposure 一致 (无 drift)"""
        positions = [
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=1.0),
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=0.0),  # zombie
            _make_position(strategy="EMA20_BREAKOUT", size=2.0),
            _make_position(strategy="A", size=0.0),                  # zombie
        ]
        # Aggregate first
        risk = aggregate_exposure(positions)

        # Gates should read from risk
        cfg = RiskGateConfig()
        result = RiskGateChecker.check_all_gates(positions, equity=100000.0, cfg=cfg)

        assert result.manual_position_count == risk.manual_count, (
            f"❌ check_all_gates 独立计 manual_count ({result.manual_position_count}) "
            f"!= aggregate_exposure.manual_count ({risk.manual_count}). "
            f"drift! check_all_gates 应读字段而非独立计算"
        )
        assert result.system_position_count == risk.system_count, (
            f"❌ check_all_gates 独立计 system_count ({result.system_position_count}) "
            f"!= aggregate_exposure.system_count ({risk.system_count})"
        )

    def test_check_all_gates_count_includes_zombies(self):
        """zombie 仓位仍计入 manual_count/system_count (slot reservation)"""
        positions = [
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=1.0),
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=0.0),  # zombie
        ]
        cfg = RiskGateConfig()
        result = RiskGateChecker.check_all_gates(positions, equity=100000.0, cfg=cfg)
        assert result.manual_position_count == 2, (
            f"含 zombie 应 manual=2, got {result.manual_position_count}"
        )


class TestAuditFindingsClosed:
    """集成测试: 6 副本 + PortfolioRisk drift 全部关闭 (P1 #1 + #2)"""

    def test_aggregate_and_gates_count_drift_closed(self):
        """聚合与 gates 用同字段, 不可能 drift"""
        # 含 zombie + mix
        positions = [
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=1.0, entry_price=100.0),
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=0.5, entry_price=100.0),
            _make_position(strategy="EMA20_BREAKOUT", size=2.0, entry_price=200.0),
            _make_position(strategy="EXTERNAL_WEB_SYNC", size=0.0, entry_price=100.0),  # zombie
        ]
        risk = aggregate_exposure(positions)
        cfg = RiskGateConfig()
        result = RiskGateChecker.check_all_gates(positions, equity=100000.0, cfg=cfg)

        # 一致性 (单一来源)
        assert result.manual_position_count == risk.manual_count == 3
        assert result.system_position_count == risk.system_count == 1
        # 不变量: count sum = position_count
        assert risk.manual_count + risk.system_count == risk.position_count == 4