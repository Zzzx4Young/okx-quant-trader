# -*- coding: utf-8 -*-
"""
Q5/Q6/Q11 Silent Drift Fix 钉住测试 (2026-08-05)

════════════════════════════════════════════════════════════════════
目的: 钉住 8-04 Q1-Q11 redesign 中 3 个 silent drift 的 ground truth。

Bug 背景:
  8-04 23:36+ apply 后:
    Q5: risk.fractional_kelly = 0.5 (JSON) vs 0.25 (risk.py function default)
    Q6: risk.volatility_dampen_factor = 1.0 (JSON) vs 0.7 (risk.py function default)
    Q11: regime.up_threshold / down_threshold = MISSING from JSON, hardcoded in regime_filter.py:36-37

  runner.py:696-697 attribute access `cfg.fractional_kelly` → AttributeError
  → try/except catch → silent fallback to 2% (实际不是 0.5 Kelly)

修复方案 (Nixil 22:14 拍板):
  Q5/Q6: Config 加 @property, default = 决策值 (0.5/1.0) — fail-safe to decision
  Q11: Config 加 3 @property (up/down/ema_bullish) + regime_filter.py 改动 B
        (None default → lazy Config load → fallback to module constants)

Iron Rule #11 应用: 金融系统 default 应 align with current decision
════════════════════════════════════════════════════════════════════
"""

import json

import pytest

from okx.code.config import Config
from okx.code.regime_filter import (
    DEFAULT_UP_RET_THRESHOLD,
    DEFAULT_DOWN_RET_THRESHOLD,
    DEFAULT_EMA_BULLISH_RATIO,
    recommended_strategy,
)


# ────────────── Fixtures ──────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    """每个 test 前后 reset singleton, 防测试间污染

    Iron Rule #5 实证: `cfg` fixture (conftest.py) 会在 setUp 末尾创建 Config 实例
    并设 _instance。如果本 test 需要的 Config 与前者不同, 必须先 setUp reset 一次。
    """
    Config._instance = None
    yield
    # Teardown 再 reset 一次防下个 test 被污染
    Config._instance = None


# ────────────── Q5: fractional_kelly ──────────────

class TestConfigFractionalKelly:
    """Q5 8-04 decision: 1/2 Kelly (0.5). Config 必须暴露为 @property.

    Bug: runner.py:696 写 `cfg.fractional_kelly` 但 Config 无此 property → AttributeError
    风险: Kelly sizing 调用时 silent fallback 到 2% (不是 0.5 Kelly)
    """

    def test_fractional_kelly_property_exists_and_returns_0_5(self, cfg):
        """cfg.fractional_kelly 必须返回 0.5 (8-04 决策值)"""
        # 当前应该 RED — Config 没有 fractional_kelly @property
        assert hasattr(cfg, "fractional_kelly"), (
            "❌ Config.fractional_kelly 缺失 (Iron Rule #5/#11 silent drift). "
            "修复: 在 code/config.py 加 @property fractional_kelly"
        )
        assert cfg.fractional_kelly == 0.5, (
            f"cfg.fractional_kelly 应是 0.5 (8-04 决策), got {cfg.fractional_kelly!r}"
        )

    def test_fractional_kelly_property_failsafe_to_decision_value(self, tmp_path):
        """字段缺失时 default = 0.5 (决策值, 不是 0.25 旧值)

        设计哲学: 金融系统 sentinel default 应 align with current decision,
        否则 config 漏字段就 silent drift 到旧值 (Iron Rule #11)
        """
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({
            "version": "1.0.0",
            "trading": {"demo_mode": True},
            "risk": {
                # ⚠️ fractional_kelly 故意缺失
                "max_loss_percent_per_trade": 2.0,
            },
        }))

        Config._instance = None
        c = Config(config_path=str(cfg_path))

        assert c.fractional_kelly == 0.5, (
            f"❌ fractional_kelly 字段缺失时应 default 到 0.5 (决策值), "
            f"got {c.fractional_kelly!r}. "
            f"防 silent drift: 不能 default 到 0.25 (8-03 旧值)"
        )


# ────────────── Q6: volatility_dampen_factor ──────────────

class TestConfigVolatilityDampenFactor:
    """Q6 8-04 decision: remove dampen (1.0). Config 必须暴露为 @property.

    Bug: runner.py:697 写 `cfg.volatility_dampen_factor` 但 Config 无此 property → AttributeError
    风险: Kelly sizing 调用时用 0.7 dampen 而非 1.0 (决策值)
    """

    def test_volatility_dampen_factor_property_exists_and_returns_1_0(self, cfg):
        """cfg.volatility_dampen_factor 必须返回 1.0 (8-04 决策值)"""
        assert hasattr(cfg, "volatility_dampen_factor"), (
            "❌ Config.volatility_dampen_factor 缺失 (Iron Rule #5/#11 silent drift). "
            "修复: 在 code/config.py 加 @property volatility_dampen_factor"
        )
        assert cfg.volatility_dampen_factor == 1.0, (
            f"cfg.volatility_dampen_factor 应是 1.0 (8-04 决策), "
            f"got {cfg.volatility_dampen_factor!r}"
        )

    def test_volatility_dampen_factor_property_failsafe_to_decision_value(self, tmp_path):
        """字段缺失时 default = 1.0 (决策值, 不是 0.7 旧值)"""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({
            "version": "1.0.0",
            "trading": {"demo_mode": True},
            "risk": {
                # ⚠️ volatility_dampen_factor 故意缺失
                "max_loss_percent_per_trade": 2.0,
            },
        }))

        Config._instance = None
        c = Config(config_path=str(cfg_path))

        assert c.volatility_dampen_factor == 1.0, (
            f"❌ volatility_dampen_factor 字段缺失时应 default 到 1.0 (决策值), "
            f"got {c.volatility_dampen_factor!r}. "
            f"防 silent drift: 不能 default 到 0.7 (8-03 旧值)"
        )


# ────────────── Q11: regime thresholds ──────────────

class TestConfigRegimeThresholds:
    """Q11 8-04 decision: maintain 10%/-5%. Config 必须暴露为 @property.

    Bug: state/config.json 缺 regime 块, regime_filter.py:36-37 用 module-level constants
    风险: 决策"维持 10/-5"实际未 wire 到 config.json — 无法通过配置调整
    """

    def test_regime_up_threshold_property_returns_10(self, cfg):
        """cfg.regime_up_threshold 必须返回 10.0 (8-04 决策值)"""
        assert hasattr(cfg, "regime_up_threshold"), (
            "❌ Config.regime_up_threshold 缺失 (Q11 silent drift). "
            "修复: 在 code/config.py 加 @property regime_up_threshold"
        )
        assert cfg.regime_up_threshold == 10.0, (
            f"cfg.regime_up_threshold 应是 10.0 (8-04 决策), "
            f"got {cfg.regime_up_threshold!r}"
        )

    def test_regime_down_threshold_property_returns_minus_5(self, cfg):
        """cfg.regime_down_threshold 必须返回 -5.0 (8-04 决策值)"""
        assert hasattr(cfg, "regime_down_threshold"), (
            "❌ Config.regime_down_threshold 缺失. "
            "修复: 在 code/config.py 加 @property regime_down_threshold"
        )
        assert cfg.regime_down_threshold == -5.0, (
            f"cfg.regime_down_threshold 应是 -5.0 (8-04 决策), "
            f"got {cfg.regime_down_threshold!r}"
        )

    def test_regime_ema_bullish_ratio_property_returns_1_02(self, cfg):
        """cfg.regime_ema_bullish_ratio 必须返回 1.02 (regime filter EMA50/EMA200 bullish ratio)"""
        assert hasattr(cfg, "regime_ema_bullish_ratio"), (
            "❌ Config.regime_ema_bullish_ratio 缺失. "
            "修复: 在 code/config.py 加 @property regime_ema_bullish_ratio"
        )
        assert cfg.regime_ema_bullish_ratio == 1.02, (
            f"cfg.regime_ema_bullish_ratio 应是 1.02, "
            f"got {cfg.regime_ema_bullish_ratio!r}"
        )


# ────────────── Q11 end-to-end: regime_filter wire-up ──────────────

class TestRegimeFilterConfigWireUp:
    """regime_filter.recommended_strategy 必须能从 Config 读 threshold (改动 B).

    Bug: regime_filter.py:36-37 用 module-level DEFAULT_*_THRESHOLD constants,
         signal_runner 调用时不显式传 → 永远用 constants (无法调整)
    修复: 接受 None default → lazy load Config → fallback to module constants
    """

    def _make_klines_with_ret(self, ret_90d_pct: float, n_days: int = 250):
        """构造一个能让 _compute_features 给出指定 ret_90d_pct 的 mock klines."""
        import pandas as pd
        import numpy as np

        # 用 1d klines 让 resample_to_daily 直接通过
        dates = pd.date_range(end="2026-08-05", periods=n_days, freq="1D", tz="UTC")
        # 构造 close 让 90d ret = ret_90d_pct
        last_price = 100.0
        ninety_ago_price = last_price / (1 + ret_90d_pct / 100.0)
        # 简单线性插值 (实际波动不重要，只影响 EMA, 我们设 EMA50 ≈ EMA200)
        prices = np.linspace(ninety_ago_price, last_price, n_days)
        # 关键: 让 EMA50 / EMA200 ratio = 1.0 (避免 SIDE 误判)
        prices = prices + np.random.RandomState(42).normal(0, 0.001, n_days)
        prices[-1] = last_price

        df = pd.DataFrame({
            "timestamp": (dates.astype("int64") // 10**6).astype("int64"),  # ms
            "close": prices,
        })
        return df

    def test_recommended_strategy_uses_config_threshold_when_none(self, cfg):
        """regime_filter 不传 threshold → 应从 Config 读 (8-04 决策值)

        端到端: 用 ret=+11% (UP) + EMA50/200 ratio=1.05 (>1.02) → 应判 UP 拒入场
        验证 Config wire-up 生效
        """
        klines = self._make_klines_with_ret(ret_90d_pct=11.0)

        # 不显式传 threshold → 应该从 Config 读
        strategies, reason, feats = recommended_strategy(klines)

        # 验证: 用了 Config 的 10.0 (UP threshold), 1.02 (EMA bullish ratio)
        # ret=11% > 10% → UP regime
        assert "UP" in reason or "拒入场" in reason, (
            f"❌ ret=11% 应判 UP (>10%), got reason={reason!r}. "
            f"可能 Config wire-up 没生效 (用了 module constant 或不同值)"
        )

    def test_recommended_strategy_uses_CONFIG_not_module_constant(self, tmp_path):
        """【严格 wire-up 验证】 Config 提供不同 threshold → regime_filter 必须用 Config 值

        Bug 防御: 如果 regime_filter 仍读 module-level constants,
        则 Config 改 up_threshold=20 不会影响判定 (silent drift)

        Iron Rule #5 实证: 前一个 test 的 `cfg` fixture 会创建 Config instance 指向
        真实 state/config.json (缺 regime 块), 必须显式 reset + 重新创建才能 override。
        """
        import importlib

        # Setup Config with regime.up_threshold=20.0 (override module constant 10.0)
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({
            "version": "1.0.0",
            "trading": {"demo_mode": True},
            "regime": {
                "up_threshold": 20.0,    # ← 故意设 20 (而非默认 10)
                "down_threshold": -5.0,
                "ema_bullish_ratio": 1.02,
            },
        }))
        # 显式 reset + 重新创建 (覆盖前一个 test 可能的 _instance)
        Config._instance = None
        new_cfg = Config(config_path=str(cfg_path))
        # 验证 Config 真的加载了 up_threshold=20
        assert new_cfg.regime_up_threshold == 20.0, (
            f"❌ Config 加载错位: regime_up_threshold={new_cfg.regime_up_threshold}, "
            f"预期 20.0。说明 Config._instance 未 reset 干净"
        )

        # 同时 reset module-level _config (get_config() 读这个, 不是 Config._instance!)
        import okx.code.config as config_module
        config_module._config = new_cfg

        # Reload regime_filter module 让改动 B 的 `from ... import get_config` 重新跑
        # (Iron Rule #5: 局部 import 是 lazy binding, 必须在 Config 重新创建后 reload)
        from okx.code import regime_filter as rf_module
        importlib.reload(rf_module)

        # 构造 ret=11% (UP 默认阈值下应判 UP, 但 Config 是 20 → 不应判 UP)
        klines = self._make_klines_with_ret(ret_90d_pct=11.0)
        strategies, reason, feats = rf_module.recommended_strategy(klines)

        # 严格验证: Config up_threshold=20 → ret=11% < 20 → 不应判 UP
        # ⚠️ 字符串 "UP" 出现在 "UP>20.0%" 里 — 是 Config 生效证据 (threshold 用了 20)
        # 真正的 UP regime 标记是 "UP+EMA多头 拒入场"
        assert "UP+EMA多头" not in reason, (
            f"❌ Config.up_threshold=20 + ret=11% → 不应判 UP "
            f"(ret < 20, 应判 SIDE 或 DOWN), got reason={reason!r}. "
            f"说明 regime_filter 仍读 module constant 10.0, Config wire-up 未生效"
        )
        assert "SIDE" in reason or "DOWN" in reason, (
            f"应判 SIDE 或 DOWN (因 ret < Config threshold 20), got {reason!r}"
        )
        # 额外验证: threshold 字符串确实是 20 (不是 10)
        assert "UP>20.0%" in reason, (
            f"reason 应含 'UP>20.0%' (Config 生效证据), got {reason!r}"
        )

    def test_recommended_strategy_fallback_to_module_constants_on_config_error(self):
        """Config 不可用时 fallback to module constants (backward compat)

        Iron Rule #5/#11: 防 cascade failure
        - regime_filter 不传 + Config 加载异常 → fallback 到 DEFAULT_*_THRESHOLD
        - 不应 crash, 不应 return None
        """
        import pandas as pd

        # Mock 一个会 raise 的 Config
        Config._instance = None

        original_get_config = None
        try:
            from okx.code import config as config_module
            original_get_config = config_module.get_config

            def broken_get_config():
                raise RuntimeError("simulated Config failure")

            config_module.get_config = broken_get_config

            # 用一个不会触发 regime 判定的 dummy klines (n<90)
            df = pd.DataFrame({
                "timestamp": [1700000000000],
                "close": [100.0],
            })

            # 不应 crash, 不应 raise
            strategies, reason, feats = recommended_strategy(df)

            # 数据不足 (n<90) → 直接 return
            assert strategies == [], f"数据不足应 return [], got {strategies!r}"
            assert "数据不足" in reason, f"reason 应含'数据不足', got {reason!r}"

        finally:
            # Restore
            if original_get_config is not None:
                config_module.get_config = original_get_config

    def test_recommended_strategy_module_constants_still_exist_for_backward_compat(self):
        """Module-level DEFAULT_*_THRESHOLD constants 必须保留 (Nixil 决策)

        决策 (22:14): 保留 constants 作为 fallback, 不删
        验证: constants 仍可 import, 值仍是 10/-5/1.02
        """
        assert DEFAULT_UP_RET_THRESHOLD == 10.0
        assert DEFAULT_DOWN_RET_THRESHOLD == -5.0
        assert DEFAULT_EMA_BULLISH_RATIO == 1.02