# -*- coding: utf-8 -*-
"""
Config.demo_mode ground-truth 锁定测试 (2026-08-05)

════════════════════════════════════════════════════════════════════
目的: 钉住 OKX runtime mode (demo / live) 的 ground truth 永不漂移。

Bug 背景:
  - runtime context 反复确认 mode=demo, equity=$79,708.55
  - 但 state/config.json 是 single source of truth, 必须显式记录 mode
  - 当前: state/config.json::trading.demo_mode=True (已存在)
  - Config.demo_mode property (line 122-123) 已实现

防御目标:
  1. 真实 config.json::trading.demo_mode 字段不能被默默删除
  2. Config.demo_mode property 必须返回正确 bool (不返回 None / 字符串)
  3. 字段缺失时 (config 损坏/旧版 fallback) → fail-safe to demo (True)
  4. 字符串值 "true" / "yes" 必须被识别为非合法值 (防 silent drift)

为什么重要:
  - 金融系统必须显式记录 mode (sentinel 不能被省略)
  - 切 live 时 config 字段是 ground truth, 必须在 audit trail 留痕
  - silent drift (config demo_mode 被改/删) 可能导致 live trading 在 demo config 下
════════════════════════════════════════════════════════════════════
"""

import json
from pathlib import Path

import pytest

from okx.code.config import Config


# ────────────── Fixtures ──────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    """每个 test 前后 reset singleton, 防测试间污染"""
    Config._instance = None
    yield
    Config._instance = None


# ────────────── Tests ──────────────

class TestConfigDemoModeGroundTruth:
    """
    state/config.json::trading.demo_mode 是 runtime mode 的 ground truth。
    必须存在 + 必须是合法 bool。
    """

    def test_real_config_trading_demo_mode_field_exists(self, real_config_dict):
        """state/config.json::trading.demo_mode 字段必须存在 (防默默删除)

        设计: runtime mode 是金融 sentinel, 必须显式记录 (不能 silently 假设)
        Bug 防御: 字段被删 → 切 live 时无法 audit mode 是何时变的
        """
        assert "trading" in real_config_dict, (
            "config.json 缺顶层 trading 块 — schema 漂移"
        )
        assert "demo_mode" in real_config_dict["trading"], (
            "❌ config.json::trading.demo_mode 字段被默默删除！"
            "这是金融 sentinel, 必须显式存在 (不能 fallback 默认). "
            "修复: 在 state/config.json::trading 加 \"demo_mode\": true 字段"
        )

    def test_real_config_demo_mode_value_is_true(self, real_config_dict):
        """当前 ground truth 是 demo (运行时持续确认)"""
        demo_mode = real_config_dict["trading"]["demo_mode"]
        assert demo_mode is True, (
            f"❌ trading.demo_mode 当前值是 {demo_mode!r}, 但 runtime 确认是 demo. "
            f"同步 config.json 与 ground truth (runtime context)"
        )

    def test_real_config_demo_mode_value_is_bool_not_string(self, real_config_dict):
        """值必须是 bool (True/False), 不能是字符串 'true' / 'yes'

        Bug 防御: 字符串 'true' 在 Python 里 truthy 但不等于 True,
        可能导致 silent drift (if demo_mode: vs if demo_mode == True: 行为不同)
        """
        demo_mode = real_config_dict["trading"]["demo_mode"]
        assert isinstance(demo_mode, bool), (
            f"❌ trading.demo_mode 应是 bool, got {type(demo_mode).__name__} ({demo_mode!r}). "
            f"防 silent drift: 字符串 'true' 与 True 行为不一致"
        )


class TestConfigDemoModePropertyBehavior:
    """
    Config.demo_mode property 必须返回正确 bool,
    且字段缺失时 fail-safe to demo (True)
    """

    def test_demo_mode_property_returns_true_when_field_present(self, cfg):
        """Config.demo_mode 必须返回 True (字段存在时)"""
        assert cfg.demo_mode is True, (
            f"Config.demo_mode 应返回 True, got {cfg.demo_mode!r}"
        )

    def test_demo_mode_property_returns_bool_type(self, cfg):
        """Config.demo_mode 必须是 bool, 不是 None / 0 / 字符串"""
        result = cfg.demo_mode
        assert isinstance(result, bool), (
            f"Config.demo_mode 应是 bool, got {type(result).__name__}"
        )

    def test_demo_mode_property_failsafe_to_demo_when_field_missing(self, tmp_path):
        """字段缺失时 Config.demo_mode 必须默认 True (fail-safe to demo)

        设计哲学: 金融系统 fail-safe — 未知 mode → 默认 demo (避免 live 误触发)
        这是 Iron Rule #11 (fail-closed / fail-safe) 的具体应用
        """
        # 写一个没有 demo_mode 字段的 config
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({
            "version": "1.0.0",
            "trading": {
                "timeframe": "1m",
                "whitelist_symbols": ["BTC-USDT-SWAP"],
                "margin_mode": "isolated",
                # ⚠️ demo_mode 字段故意缺失
            },
            "risk": {},
            "audit": {},
        }))

        Config._instance = None
        c = Config(config_path=str(cfg_path))

        # 字段缺失 → 必须默认 True (fail-safe to demo)
        assert c.demo_mode is True, (
            f"demo_mode 字段缺失时应 fail-safe to True (demo), "
            f"got {c.demo_mode!r}. "
            f"金融系统 sentinel: 未知 mode 永不能默认 live"
        )

    def test_demo_mode_property_explicit_false_means_live(self, tmp_path):
        """demo_mode=False 明确表示 live 模式"""
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({
            "version": "1.0.0",
            "trading": {
                "timeframe": "1m",
                "whitelist_symbols": ["BTC-USDT-SWAP"],
                "margin_mode": "isolated",
                "demo_mode": False,  # ← 显式切 live
            },
            "risk": {},
            "audit": {},
        }))

        Config._instance = None
        c = Config(config_path=str(cfg_path))

        # 显式 False → 必须返回 False (live mode)
        assert c.demo_mode is False, (
            f"demo_mode=False 应返回 False (live), got {c.demo_mode!r}"
        )