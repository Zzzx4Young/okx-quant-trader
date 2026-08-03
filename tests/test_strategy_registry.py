# -*- coding: utf-8 -*-
"""
Strategy Registry pattern tests · 替代 signal.py 硬编码 if-else dispatch。

设计目标：加新策略 = 加 1 行 registry，无需改 dispatch chain。
RED: STRATEGY_REGISTRY 当前不在 SignalEngine 中。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from okx.code.signal import SignalEngine


class TestStrategyRegistryPattern:
    """策略注册表：letter -> SignalEngine method_name."""

    def test_registry_is_class_attribute(self):
        """STRATEGY_REGISTRY 必须是 SignalEngine 的 class attribute。"""
        assert hasattr(SignalEngine, "STRATEGY_REGISTRY"), (
            "SignalEngine 应定义 STRATEGY_REGISTRY class attribute "
            "（替代 if-else dispatch 链）"
        )

    def test_registry_contains_active_strategies(self):
        """注册表必须包含 A / C (dormant) / E (新策略)。"""
        r = SignalEngine.STRATEGY_REGISTRY
        for letter in ["A", "C", "E"]:
            assert letter in r, f"策略 {letter} 未注册到 STRATEGY_REGISTRY"

    def test_registry_maps_letter_to_method_name(self):
        """每个 entry 是 SignalEngine 上 method name (str)。"""
        r = SignalEngine.STRATEGY_REGISTRY
        for letter, method_name in r.items():
            assert isinstance(method_name, str), (
                f"{letter} -> {method_name} 应为 str (method name), "
                f"got {type(method_name).__name__}"
            )
            assert method_name.startswith("check_"), (
                f"{letter} -> {method_name} 应以 check_ 开头"
            )
            assert method_name.endswith("_signal"), (
                f"{letter} -> {method_name} 应以 _signal 结尾"
            )

    def test_registry_methods_exist_on_engine(self):
        """每个 method name 必须实际存在于 SignalEngine。"""
        r = SignalEngine.STRATEGY_REGISTRY
        for letter, method_name in r.items():
            assert hasattr(SignalEngine, method_name), (
                f"{letter} -> {method_name} 在 SignalEngine 上找不到"
            )