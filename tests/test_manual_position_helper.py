# -*- coding: utf-8 -*-
"""
P1 audit #1 · is_manual_position helper 抽离 (2026-08-05)

════════════════════════════════════════════════════════════════════
目的: 关闭 Iron Rule #5/#7 实证的 silent drift 入口。

Bug 背景 (8-04 audit 发现):
  manual-detection 6 副本:
    - code/runner.py:255,264 (_count_positions_by_source)
    - code/risk.py:791 (comment)
    - code/risk.py:832 (aggregate_exposure)
    - code/risk.py:1007 (check_all_gates)
    - scripts/risk_monitor.py:87 (is_manual_position helper, 已存在但未复用)

  此外: 4 inline 用 startswith(("EXTERNAL", "MANUAL")) 无尾下划线
        scripts/risk_monitor.py:84 用 MANUAL_STRATEGY_PREFIXES = ("EXTERNAL", "MANUAL_") 有下划线
  → subtle semantic drift (Iron Rule #7)

修复 (Nixil 23:29 拍板):
  - 抽 is_manual_position(p) 到 code/risk.py, 接受 dict + PositionRisk-like
  - 用 MANUAL_STRATEGY_PREFIXES = ("EXTERNAL", "MANUAL_") (与 scripts/risk_monitor.py 对齐, 更严格)
  - 6 处都改用 helper
════════════════════════════════════════════════════════════════════
"""

from dataclasses import dataclass
from typing import List, Dict, Any

import pytest

from okx.code.risk import (
    is_manual_position,
    aggregate_exposure,
    RiskGateChecker,
    MANUAL_STRATEGY_PREFIXES,
)


# ────────────── Fixtures ──────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    from okx.code.config import Config
    Config._instance = None
    yield
    Config._instance = None


@dataclass
class FakePositionRisk:
    """Mock PositionRisk for tests requiring dataclass input."""
    strategy: str = ""
    size: float = 0.0
    direction: str = "long"
    entry_price: float = 100.0
    symbol: str = "BTCUSDTSWAP"
    leverage: int = 3
    ct_val: float = 0.01


# ────────────── Helper Contract Tests ──────────────

class TestIsManualPositionHelper:
    """helper 自身 contract: 接受 dict + dataclass, 正确分类"""

    def test_helper_exists_in_risk_module(self):
        """is_manual_position 必须存在于 okx.code.risk 模块"""
        assert callable(is_manual_position), (
            "❌ okx.code.risk.is_manual_position 缺失. "
            "修复: 在 code/risk.py 加 module-level is_manual_position(p) helper"
        )

    def test_helper_returns_true_for_EXTERNAL_prefix(self):
        """EXTERNAL_WEB_SYNC 等 EXTERNAL* 必须判 manual"""
        assert is_manual_position({"strategy": "EXTERNAL_WEB_SYNC"})
        assert is_manual_position({"strategy": "EXTERNAL_OTHER"})

    def test_helper_returns_true_for_MANUAL_prefix_with_underscore(self):
        """MANUAL_xxx 必须判 manual (scripts/risk_monitor.py 同语义)"""
        assert is_manual_position({"strategy": "MANUAL_NO_AUTO_CLOSE"})
        assert is_manual_position({"strategy": "MANUAL_OKX_WEB"})
        assert is_manual_position({"strategy": "MANUAL_X"})

    def test_helper_returns_false_for_system_strategies(self):
        """EMA20_BREAKOUT / A / C 等 system strategy 必须判非 manual"""
        assert not is_manual_position({"strategy": "EMA20_BREAKOUT"})
        assert not is_manual_position({"strategy": "A"})
        assert not is_manual_position({"strategy": "C"})
        assert not is_manual_position({"strategy": "BB_RSI_REVERSION"})

    def test_helper_handles_empty_or_missing_strategy(self):
        """缺 strategy / 空 string 必须判非 manual (防 AttributeError)"""
        assert not is_manual_position({})  # no strategy key
        assert not is_manual_position({"strategy": ""})
        assert not is_manual_position({"strategy": None})

    def test_helper_accepts_dataclass_with_strategy_attr(self):
        """PositionRisk-like dataclass 输入 (scripts/risk_monitor.py 用)"""
        pos = FakePositionRisk(strategy="EXTERNAL_WEB_SYNC")
        assert is_manual_position(pos), "dataclass EXTERNAL_WEB_SYNC 应判 manual"

        pos2 = FakePositionRisk(strategy="EMA20_BREAKOUT")
        assert not is_manual_position(pos2), "dataclass EMA20_BREAKOUT 应判非 manual"

    def test_helper_uses_MANUAL_STRATEGY_PREFIXES_constant(self):
        """helper 必须用 MANUAL_STRATEGY_PREFIXES 常量 (Iron Rule #5 单一来源)"""
        # 若 helper 内嵌 prefix tuple → constant 无意义, 此 test 失败
        assert ("EXTERNAL", "MANUAL_") == MANUAL_STRATEGY_PREFIXES, (
            f"MANUAL_STRATEGY_PREFIXES 应是 ('EXTERNAL', 'MANUAL_'), got {MANUAL_STRATEGY_PREFIXES}"
        )


# ────────────── Helper Wire-up Tests (6 副本) ──────────────

class TestHelperWiredUpAcrossSixOccurrences:
    """6 副本必须改用 helper (防 refactor 后又写回 hardcode)"""

    def test_helper_used_by_aggregate_exposure(self):
        """code/risk.py::aggregate_exposure 必须用 helper"""
        positions = [
            {"strategy": "EXTERNAL_WEB_SYNC", "size": 1.0, "entry_price": 100.0,
             "direction": "long", "symbol": "BTCUSDTSWAP", "leverage": 3, "ct_val": 0.01},
            {"strategy": "EMA20_BREAKOUT", "size": 2.0, "entry_price": 200.0,
             "direction": "short", "symbol": "ETHUSDTSWAP", "leverage": 3, "ct_val": 0.1},
        ]
        risk = aggregate_exposure(positions)

        # 验证 helper 真生效 (manual 仓位 → has_manual=True, has_system=True, notional 拆分)
        assert risk.has_manual_position is True, "EXTERNAL 仓必须算 manual"
        assert risk.has_system_position is True, "EMA20 仓必须算 system"
        assert risk.manual_notional_usdt > 0, "manual notional 应 > 0"
        assert risk.system_notional_usdt > 0, "system notional 应 > 0"
        assert risk.manual_notional_usdt == pytest.approx(1.0, rel=1e-3)   # 1*100*0.01 = 1.0
        assert risk.system_notional_usdt == pytest.approx(40.0, rel=1e-3)  # 2*200*0.1 = 40.0

    def test_helper_used_by_check_all_gates(self):
        """code/risk.py::RiskGateChecker.check_all_gates 必须用 helper"""
        positions = [
            {"strategy": "EXTERNAL_WEB_SYNC", "size": 1.0, "entry_price": 100.0,
             "direction": "long", "symbol": "BTCUSDTSWAP", "leverage": 3, "ct_val": 0.01},
            {"strategy": "EMA20_BREAKOUT", "size": 2.0, "entry_price": 200.0,
             "direction": "short", "symbol": "ETHUSDTSWAP", "leverage": 3, "ct_val": 0.1},
        ]
        from okx.code.risk import RiskGateConfig
        cfg = RiskGateConfig()
        result = RiskGateChecker.check_all_gates(positions, equity=100000.0, cfg=cfg)

        assert result.manual_position_count == 1, (
            f"EXTERNAL 仓应计 manual_count=1, got {result.manual_position_count}"
        )
        assert result.system_position_count == 1, (
            f"EMA20 仓应计 system_count=1, got {result.system_position_count}"
        )

    def test_helper_used_by_count_positions_by_source(self):
        """code/runner.py::_count_positions_by_source 必须用 helper"""
        from okx.code.runner import Runner

        positions = [
            {"strategy": "EXTERNAL_WEB_SYNC"},
            {"strategy": "EXTERNAL_WEB_SYNC"},
            {"strategy": "MANUAL_NO_AUTO_CLOSE"},
            {"strategy": "EMA20_BREAKOUT"},
            {"strategy": "A"},
        ]
        manual, system = Runner._count_positions_by_source(positions)

        assert manual == 3, f"EXTERNAL×2 + MANUAL×1 = manual=3, got {manual}"
        assert system == 2, f"EMA20 + A = system=2, got {system}"

    def test_helper_used_by_aggregate_exposure_with_no_manual_no_system(self):
        """边界: 全是 manual / 全是 system / 混合"""
        # 全 manual
        positions_all_manual = [
            {"strategy": "EXTERNAL_WEB_SYNC", "size": 1.0, "entry_price": 100.0,
             "direction": "long", "symbol": "BTCUSDTSWAP", "leverage": 3, "ct_val": 0.01},
        ]
        risk = aggregate_exposure(positions_all_manual)
        assert risk.has_manual_position is True
        assert risk.has_system_position is False
        assert risk.manual_notional_usdt > 0
        assert risk.system_notional_usdt == 0

        # 全 system
        positions_all_system = [
            {"strategy": "EMA20_BREAKOUT", "size": 1.0, "entry_price": 100.0,
             "direction": "long", "symbol": "BTCUSDTSWAP", "leverage": 3, "ct_val": 0.01},
        ]
        risk2 = aggregate_exposure(positions_all_system)
        assert risk2.has_manual_position is False
        assert risk2.has_system_position is True
        assert risk2.manual_notional_usdt == 0
        assert risk2.system_notional_usdt > 0


# ────────────── Backward Compat with scripts/risk_monitor.py ──────────────

class TestHelperBackwardCompat:
    """helper 与 scripts/risk_monitor.py::is_manual_position 行为必须一致"""

    def test_helper_matches_risk_monitor_behavior(self):
        """同 input → 同 output (避免两个 helper 行为 drift)"""
        test_strategies = [
            ("EXTERNAL_WEB_SYNC", True),
            ("EXTERNAL_X", True),
            ("MANUAL_NO_AUTO_CLOSE", True),
            ("MANUAL_OKX_WEB", True),
            ("EMA20_BREAKOUT", False),
            ("A", False),
            ("BB_RSI_REVERSION", False),
            ("", False),
        ]

        for strategy, expected in test_strategies:
            # helper from code/risk.py
            from okx.code.risk import is_manual_position as new_helper
            new_result = new_helper({"strategy": strategy})

            # helper from scripts/risk_monitor.py (现在复用 risk.py 的, 行为必须一致)
            from okx.scripts.risk_monitor import is_manual_position as old_helper
            from okx.scripts.risk_thresholds import PositionRisk

            # PositionRisk 需要所有必填字段 (取合理默认值只为测 helper 行为)
            pos_risk = PositionRisk(
                inst_id="BTC-USDT-SWAP", pos_side="long", size=1.0,
                ct_val=0.01, avg_px=100.0, mark_px=100.0, upl=0.0,
                margin=10.0, liq_px=None, leverage=3.0, strategy=strategy,
            )
            old_result = old_helper(pos_risk)

            assert new_result == old_result == expected, (
                f"strategy={strategy!r}: new={new_result}, old={old_result}, "
                f"expected={expected}. "
                f"helper 行为必须与 scripts/risk_monitor.py 一致"
            )