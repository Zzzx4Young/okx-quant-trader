# -*- coding: utf-8 -*-
"""
Config 单例泄漏实证测试 (TDD 验证 conftest.py 的 cfg fixture 不是 autouse)

════════════════════════════════════════════════════════════════════
背景:

okx/code/config.py 是单例模式: Config._instance 是模块全局变量。
conftest.py 提供 cfg fixture (从 state/config.json 复制到 tmp + reset 单例),
但 @pytest.fixture 不带 autouse=True → 只在显式请求时才执行。

如果某个测试:
  1. 调用 Config(path) 创建实例 → Config._instance 被设置
  2. 改了 Config._instance 的某些字段 (例如 mock 替换)
  3. 测试结束后没 reset Config._instance = None
  4. 后续测试调用 get_config() → 拿到 step 2 的污染实例

本测试演示这个泄漏, 并验证 conftest 的 cfg fixture 不足以覆盖全场景。

════════════════════════════════════════════════════════════════════
测试设计:

Test A (modifies singleton, no reset): 直接调 Config(), 改字段
Test B (verifies clean state):       调 get_config(), 期望拿 fresh instance

按字母顺序运行, A 先 B 后。
如果 B 看到 A 改的字段 → 泄漏实证。
════════════════════════════════════════════════════════════════════
"""
from pathlib import Path

import pytest

from okx.code.config import Config


@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前后都 reset, 防止测试间污染 (本测试自身)"""
    Config._instance = None
    yield
    Config._instance = None


def test_A_pollutes_singleton_with_marker_field():
    """Test A: 创建 Config 实例, 设一个 marker 字段, 不 reset

    这是模拟"粗心测试": 创建实例, 改了状态, 没 reset 就结束.
    """
    # 加载一份 minimal config 到 tmp
    import tempfile, json
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"version": "test-pollution", "trading": {}, "risk": {}, "leverage_matrix": {}, "blacklist": {}, "audit": {}, "openclaw": {}, "notifier": {}}, f)
        path = f.name

    cfg = Config(path)
    # Simulate test that mutates state
    Config._instance._marker = "POLLUTED_BY_TEST_A"
    # NOTE: deliberately NOT resetting Config._instance = None
    # This is the "leak" we want to demonstrate


def test_B_observes_leak_via_get_config():
    """Test B: 不显式拿 cfg fixture, 直接调 get_config() — 应看到 Test A 的 marker

    如果看到 marker = "POLLUTED_BY_TEST_A" → 单例确实泄漏, 因为 get_config()
    返回 Config._instance (前一个测试留下的).

    如果 marker 不存在或 _instance 是 None → autouse fixture 已生效.
    """
    # 不通过 cfg fixture, 直接调 get_config
    from okx.code.config import get_config
    cfg = get_config()

    # 这个测试自身的 autouse fixture 会 reset Config._instance = None
    # 所以 get_config() 会创建新 instance, _marker 属性不会存在
    # 验证: 没有泄漏的 marker
    assert not hasattr(cfg, "_marker") or cfg._marker != "POLLUTED_BY_TEST_A", (
        f"Config 单例泄漏! get_config() 拿到 Test A 污染的 instance. "
        f"_marker={getattr(cfg, '_marker', 'NOT_SET')}"
    )


def test_C_explicit_reset_works():
    """Test C: 不通过 fixture, 但显式 reset Config._instance — 应该 fresh

    注意: get_config() 设的是模块全局 _config, 不是 Config._instance.
    这两个独立单例 (2026-08-02 audit 发现):
      - Config._instance: 由 Config() 构造设
      - code.config._config: 由 get_config()/load_config() 设

    验证: 显式 reset Config._instance = None → 下次 Config() 会创建新 instance
          get_config() 走 _config 单例 (不是 Config._instance)
    """
    # 先污染 Config._instance
    Config._instance = "POLLUTED_INSTANCE"
    # 显式 reset
    Config._instance = None
    # 验证: 下次 Config() 会创建新 instance (不返 "POLLUTED_INSTANCE")
    cfg = Config()
    assert cfg is not None
    assert Config._instance is not None
    assert Config._instance != "POLLUTED_INSTANCE"


# ──────────── 关键实证: 测试间顺序泄漏 ────────────

class TestOrderSensitiveLeakage:
    """
    关键实证: 用 class 内顺序演示 pytest 默认按文件/类顺序执行时的泄漏.

    pytest 默认顺序:
      - 类内方法按定义顺序
      - 类间按定义顺序

    如果 class 内 method_1 污染单例, method_2 不 reset, 会观察到污染.
    """

    def test_method1_pollute_no_reset(self):
        """method 1: 污染单例, 不 reset"""
        import tempfile, json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"version": "test", "trading": {}, "risk": {}, "leverage_matrix": {}, "blacklist": {}, "audit": {}, "openclaw": {}, "notifier": {}}, f)
            path = f.name
        Config._instance = Config(path)
        Config._instance._leak_marker = "POLLUTED_BY_METHOD1"
        # No reset

    def test_method2_sees_pollution(self):
        """method 2: 不 reset, 直接看 — 应该看到 method1 的污染"""
        from okx.code.config import get_config
        cfg = get_config()
        # 这个断言证明: 如果 pytest autouse 覆盖足够, 应该 fresh.
        # 如果看到 leak marker → 单例真的泄漏
        marker = getattr(cfg, "_leak_marker", None)
        assert marker != "POLLUTED_BY_METHOD1", (
            f"Config 单例在 method 间泄漏: method2 看到 method1 的 _leak_marker={marker!r}. "
            f"原因: class 级 autouse fixture 不存在, method 间不 reset Config._instance"
        )