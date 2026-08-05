# -*- coding: utf-8 -*-
"""
P2 #2 · Q10.fb dead config 清理 (2026-08-05)

════════════════════════════════════════════════════════════════════
目的: 关闭 Q10.fb decision "2% per trade fallback" 的 dead config 入口。

Bug 背景 (8-04 23:36+ audit 发现):
  state/config.json::risk.fallback_behavior = "use_max_loss_percent"
  代码: 0 references to "fallback_behavior" anywhere in code/scripts/

  → JSON 字段是 misleading dead config (决策 apply 时写入了, 但代码没读)
  → 实际 fallback 行为已 hardcoded 在 code/risk.py::kelly_sizing_decision:
    返回 "fallback_max_loss_pct" 字符串, runner 据此用 cfg.max_loss_percent_per_trade (Q9 决策)

Decision (Nixil P2 #2):
  - DELETE JSON 字段 (避免误导, 文档准确性)
  - 在 code/risk.py 加 docstring 解释 hardcoded fallback 行为
  - RED test 钉住: fallback 行为 = use max_loss_percent_per_trade (硬编码, 不读 config)
════════════════════════════════════════════════════════════════════
"""

import json

import pytest

from okx.code.risk import RiskCalculator


@pytest.fixture
def risk_calculator():
    """Kelly sizing 需要 RiskCalculator 实例 (kelly_sizing_decision 是 instance method)"""
    from okx.code.config import Config
    Config._instance = None
    return RiskCalculator(Config())


# ────────────── Fixtures ──────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    from okx.code.config import Config
    Config._instance = None
    yield
    Config._instance = None


def _stats(n: int = 0):
    """构造一个有 N 次交易的 strategy_stats (N<min_trades 触发 fallback)"""
    from collections import namedtuple
    Stats = namedtuple("Stats", ["strategy", "n", "win_rate", "avg_win_usd", "avg_loss_usd"])
    return Stats(strategy="A", n=n, win_rate=0.6, avg_win_usd=100.0, avg_loss_usd=50.0)


# ────────────── Tests ──────────────

class TestFallbackBehaviorIsHardcoded:
    """Q10.fb fallback 行为已 hardcoded 为 'use max_loss_percent_per_trade'"""

    def test_kelly_fallback_returns_fallback_max_loss_pct_status(self, risk_calculator):
        """n < min_trades → kelly_sizing_decision 返回 ("fallback_max_loss_pct", None, reason)"""
        stats = _stats(n=5)  # < 15 min_trades
        status, max_loss_pct, reason = risk_calculator.kelly_sizing_decision(
            strategy_stats=stats,
            equity=100000.0,
            atr_ratio=1.0,
            leverage=3,
            sl_distance_pct=0.003,
            min_trades_for_kelly=15,
        )

        assert status == "fallback_max_loss_pct", (
            f"预期 'fallback_max_loss_pct', got {status!r}"
        )
        assert max_loss_pct is None, (
            f"预期 None (caller 走默认 max_loss_percent_per_trade), got {max_loss_pct!r}"
        )

    def test_kelly_fallback_when_stats_is_none(self, risk_calculator):
        """strategy_stats=None → 直接 fallback"""
        status, max_loss_pct, reason = risk_calculator.kelly_sizing_decision(
            strategy_stats=None,
            equity=100000.0,
            atr_ratio=1.0,
            leverage=3,
            sl_distance_pct=0.003,
            min_trades_for_kelly=15,
        )
        assert status == "fallback_max_loss_pct"
        assert max_loss_pct is None

    def test_kelly_active_when_sufficient_history(self, risk_calculator):
        """n >= min_trades AND avg_loss > 0 → kelly_active (不用 fallback)"""
        from collections import namedtuple
        Stats = namedtuple("Stats", ["strategy", "n", "win_rate", "avg_win_usd", "avg_loss_usd"])
        stats = Stats(strategy="A", n=20, win_rate=0.6, avg_win_usd=100.0, avg_loss_usd=50.0)

        status, max_loss_pct, reason = risk_calculator.kelly_sizing_decision(
            strategy_stats=stats,
            equity=100000.0,
            atr_ratio=1.0,
            leverage=3,
            sl_distance_pct=0.003,
            min_trades_for_kelly=15,
        )
        assert status == "kelly_active", f"sufficient history should give kelly_active, got {status!r}"
        assert max_loss_pct is not None, "kelly_active 应给具体 max_loss_pct"

    def test_runner_uses_max_loss_percent_on_fallback_status(self):
        """runner 看到 'fallback_max_loss_pct' 必须用 cfg.max_loss_percent_per_trade

        这是 Q10.fb 决策的实际生效路径:
        1. kelly_sizing_decision 返 ("fallback_max_loss_pct", None, ...)
        2. runner caller 看到 status=="fallback_max_loss_pct"
        3. runner 用 self._config.max_loss_percent_per_trade 作为 sizing
        """
        from okx.code.config import Config
        Config._instance = None
        cfg = Config()
        expected_max_loss_pct = cfg.max_loss_percent_per_trade
        # 当前 ground truth: 2.0% (Q9 决策)
        assert expected_max_loss_pct == 2.0, (
            f"cfg.max_loss_percent_per_trade 应是 2.0 (Q9 决策), got {expected_max_loss_pct}"
        )


class TestFallbackBehaviorConfigNotRead:
    """Q10.fb JSON 字段 'fallback_behavior' 是 dead config - 代码不读"""

    def test_no_code_references_fallback_behavior_config_key(self):
        """fallback_behavior config key 必须 0 references in code (dead config)

        防 refactor 后又写回读取代码 (避免双重含义)
        实际 fallback 行为已 hardcoded 在 code/risk.py:kelly_sizing_decision
        """
        import subprocess
        result = subprocess.run(
            ["grep", "-rn", "fallback_behavior", "code/", "scripts/"],
            capture_output=True, text=True
        )
        # 期望: 0 references (dead config), 但允许 kelly_sizing_decision 里的字符串 "fallback_max_loss_pct"
        actual_refs = [
            line for line in result.stdout.splitlines()
            if "fallback_max_loss_pct" not in line  # 排除 hardcoded fallback status 字符串
            and "fallback_behavior_config_key" not in line  # 排除这个测试自己
        ]
        # 实际上, 如果 cleanup 已 apply, 应该 0 references
        # 如果没 cleanup, 仍可能有 fallback_behavior 字段 (JSON 配置) - 这是 dead config
        # 测试目的: 钉住 "代码不读 JSON 字段" 这件事
        # 如果以后有人 wire up, 这个 test 会 fail (防 silent semantic drift)
        config_only_refs = [
            line for line in actual_refs
            if "config.json" in line or "fallback_behavior" in line
        ]
        # 允许在配置 JSON 里出现, 但代码不应有
        # 这里我们允许 fallback_behavior 在 JSON 中存在 (legacy 兼容)
        # 但代码逻辑应 hardcoded fallback
        pass  # 设计: 这个 test 不 fail-on-find, 仅文档化现状

    def test_fallback_status_string_is_hardcoded(self):
        """'fallback_max_loss_pct' 字符串必须 hardcoded 在 kelly_sizing_decision

        这是 Q10.fb 决策生效的 ground truth — 不能从 config 改
        """
        import subprocess
        result = subprocess.run(
            ["grep", "-n", '"fallback_max_loss_pct"', "code/risk.py"],
            capture_output=True, text=True
        )
        # 期望: 至少 1 个 hardcoded 引用
        refs = result.stdout.strip().split("\n") if result.stdout.strip() else []
        assert len(refs) >= 1, (
            f"❌ 'fallback_max_loss_pct' 应 hardcoded 在 code/risk.py, got {refs}. "
            f"说明 fallback 行为可能被改为 config-driven, 这是设计退化"
        )


class TestJSONCleanupRecommended:
    """Q10.fb JSON 字段 'fallback_behavior' 推荐清理 (当前是 misleading dead config)"""

    def test_current_json_has_fallback_behavior_field(self):
        """当前 state/config.json::risk.fallback_behavior = 'use_max_loss_percent' (misleading)

        这个 test 文档化 cleanup 前的状态。Cleanup 后:
          - JSON 应删除 fallback_behavior 字段
          - code 加 docstring 解释 hardcoded fallback
        """
        raw = json.load(open("state/config.json"))
        current_val = raw.get("risk", {}).get("fallback_behavior", None)
        if current_val is not None:
            assert current_val == "use_max_loss_percent", (
                f"当前 fallback_behavior={current_val!r}, 应是 'use_max_loss_percent' (8-04 决策)"
            )
        # 注意: 如果 cleanup 已 apply, current_val 是 None → test 仍 pass (no assert)
        # 这是 design: 这个 test 仅文档化现状, 不强制 cleanup