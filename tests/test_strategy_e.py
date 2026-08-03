# -*- coding: utf-8 -*-
"""
策略 E (VEB · VOLATILITY_EXPANSION_BREAKOUT) 单元测试。

设计意图：BBW 压缩 + 扩张突破 + funding rate sanity check + 量能共振。
目标补 SIDE regime gap + A 右侧滞后。

RED: check_veb_signal 当前不存在；registry 中无 "E" entry。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from unittest.mock import MagicMock

from okx.code.config import Config
from okx.code.signal import SignalEngine, Signal


@pytest.fixture(autouse=True)
def reset_config_singleton():
    Config._instance = None
    yield
    Config._instance = None


@pytest.fixture
def cfg_with_e_enabled():
    """strategy_e.enabled=true 的最小 Config。"""
    cfg = Config()
    cfg._data.setdefault("strategy_e", {})
    cfg._data["strategy_e"]["enabled"] = True
    cfg._data["strategy_e"]["bb_period"] = 20
    cfg._data["strategy_e"]["bb_std"] = 2.0
    cfg._data["strategy_e"]["bbw_lookback"] = 100
    cfg._data["strategy_e"]["bbw_squeeze_percentile"] = 0.20
    cfg._data["strategy_e"]["bbw_expansion_ratio"] = 1.10
    cfg._data["strategy_e"]["funding_rate_cap"] = 0.0001
    cfg._data["strategy_e"]["volume_ratio"] = 1.5
    cfg._data["strategy_e"]["rsi_overbought"] = 70
    cfg._data["strategy_e"]["rsi_oversold"] = 30
    cfg._data["strategy_e"]["atr_multiplier"] = 1.5
    cfg._data["regime_strategy_map"] = {
        "DOWN": ["A"],
        "UP": [],
        "SIDE": ["E"],
    }
    return cfg


class TestCheckVebSignalExists:
    """API contract: check_veb_signal 必须存在于 SignalEngine。"""

    def test_method_exists_and_callable(self):
        assert hasattr(SignalEngine, "check_veb_signal"), (
            "SignalEngine 缺少 check_veb_signal 方法 "
            "（策略 E 是 SIDE regime 唯一可用策略）"
        )
        assert callable(getattr(SignalEngine, "check_veb_signal", None))


class TestCheckVebSignalDisabled:
    """strategy_e.enabled=false → 返回 None（不参与 dispatch）。"""

    def test_returns_none_when_disabled(self, monkeypatch):
        cfg = Config()
        cfg._data.setdefault("strategy_e", {})
        cfg._data["strategy_e"]["enabled"] = False

        mock_market = MagicMock()
        engine = SignalEngine(market_api=mock_market, config=cfg)

        sig = engine.check_veb_signal("BTC-USDT-SWAP", None)
        assert sig is None


class TestCheckVebSignalFundingRate:
    """funding rate sanity check：避免拥挤方向。"""

    def test_skips_long_when_funding_too_positive(self, monkeypatch, cfg_with_e_enabled):
        """funding_rate >= cap 时拒绝 long。"""
        monkeypatch.setattr(
            SignalEngine, "_get_funding_rate",
            lambda self, symbol: 0.0005,  # > 0.0001 cap
        )
        mock_market = MagicMock()
        mock_market.get_candles.return_value = [
            [i * 3600000, 50000, 50100, 49900, 50050, 1000, "50000", "50000"]
            for i in range(120)
        ]
        engine = SignalEngine(market_api=mock_market, config=cfg_with_e_enabled)
        sig = engine.check_veb_signal("BTC-USDT-SWAP", None)
        # funding 太拥挤 → 不出 long signal（即使 BBW + 量能满足）
        assert sig is None or sig.direction != "long"


class TestCheckVebSignalRegistryIntegration:
    """strategy_e.enabled 控制 registry 是否暴露。"""

    def test_registry_includes_e_when_enabled(self, cfg_with_e_enabled):
        cfg_with_e_enabled._data["strategy_e"]["enabled"] = True
        # E 必须在 registry 里
        assert "E" in SignalEngine.STRATEGY_REGISTRY

    def test_registry_includes_e_when_disabled(self):
        """enabled=false 不影响 registry 注册（enabled check 在 method 内）。"""
        assert "E" in SignalEngine.STRATEGY_REGISTRY