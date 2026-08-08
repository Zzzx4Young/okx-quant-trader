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

    def test_capacity_gate_intentional_drift_counts_zombies(self):
        """check_all_gates capacity gate 必须 count ALL positions (含 size=0 zombie) - defense-in-depth.

        8-04 scholar evaluation (Nixil critique): size=0 zombie 占 capacity slot 是 intentional design
        - aggregate_exposure 跳过 size=0 (notional=0, no risk exposure)
        - check_all_gates 数 ALL positions (capacity reserve slot 直到 portfolio.json cleanup)
        - zombie 不及时清理 → capacity 一直被占 → system 无法新开仓 → conservative (正确)

        之前 (我的 "fix"): system_count 只数 valid → zombie 不占 slot → 太宽松 (错)
        revert 后: system_count 数 ALL → zombie 占 slot → defense-in-depth (正)
        """
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        cfg = RiskGateConfig(
            max_total_notional_usdt=100000.0,
            max_system_positions_after_manual=3,  # 3 个 system slots
        )
        positions = [
            # 1 valid manual
            make_position(strategy="EXTERNAL_WEB_SYNC", size=0.1, entry_price=50000.0),
            # 1 valid system
            make_position(strategy="EMA20_BREAKOUT", size=0.3, entry_price=50000.0),
            # 1 size=0 system zombie (已平未清)
            make_position(strategy="EMA20_BREAKOUT", size=0.0, entry_price=50000.0,
                         symbol="BTCUSDTSWAP"),
        ]

        result = RiskGateChecker.check_all_gates(positions, equity=10000.0, cfg=cfg)

        # Intentional: count ALL positions (1 valid system + 1 zombie = 2)
        assert result.manual_position_count == 1, (
            f"1 manual, expected manual_position_count=1, got {result.manual_position_count}"
        )
        assert result.system_position_count == 2, (
            f"Defense-in-depth: zombie 必须占 capacity slot. "
            f"1 valid + 1 zombie = 2, got {result.system_position_count}. "
            f"如果 =1 则 zombie 没被 count，违反 defense-in-depth 设计"
        )
        # capacity_remaining = max_system_positions_after_manual - system_count = 3 - 2 = 1
        assert result.system_position_capacity_remaining == 1


# ──────────────────────────────────────────────────────────────
# Risk Gate Fail Mode Resolution (8-04 Step 2)
# Iron Rule #11 nuance: 金融 sentinel 不应粗暴 fail-closed
# - transient (OSError/FileNotFoundError/ConnectionError/TimeoutError) → 可能是临时 I/O 问题
#   fail-open with explicit reason 比锁死 system 1 周期 (15min) 更合理
# - 其他 (KeyError/ValueError/ImportError/AttributeError) → 代码 bug
#   fail-closed 避免 unverified position
# ──────────────────────────────────────────────────────────────

class TestRiskGateFailModeResolution:
    """should_fail_closed() pure function 决策。"""

    def test_classified_mode_transient_oserror_fails_open(self):
        """classified mode + OSError (transient) → fail-OPEN (避免锁死 system 1 周期)."""
        from okx.code.risk import should_fail_closed, RiskGateFailMode

        assert should_fail_closed(OSError("disk full"), RiskGateFailMode.CLASSIFIED) is False

    def test_classified_mode_transient_connectionerror_fails_open(self):
        from okx.code.risk import should_fail_closed, RiskGateFailMode

        assert should_fail_closed(ConnectionError("api timeout"), RiskGateFailMode.CLASSIFIED) is False

    def test_classified_mode_transient_filenotfounderror_fails_open(self):
        from okx.code.risk import should_fail_closed, RiskGateFailMode

        assert should_fail_closed(FileNotFoundError("state/portfolio.json"), RiskGateFailMode.CLASSIFIED) is False

    def test_classified_mode_transient_timeouterror_fails_open(self):
        from okx.code.risk import should_fail_closed, RiskGateFailMode

        assert should_fail_closed(TimeoutError("CB equity read timeout"), RiskGateFailMode.CLASSIFIED) is False

    def test_classified_mode_code_error_keyerror_fails_closed(self):
        """classified mode + KeyError (schema/code bug) → fail-CLOSED (防止 unverified position)."""
        from okx.code.risk import should_fail_closed, RiskGateFailMode

        assert should_fail_closed(KeyError("missing_field"), RiskGateFailMode.CLASSIFIED) is True

    def test_classified_mode_code_error_valueerror_fails_closed(self):
        from okx.code.risk import should_fail_closed, RiskGateFailMode

        assert should_fail_closed(ValueError("bad config"), RiskGateFailMode.CLASSIFIED) is True

    def test_classified_mode_code_error_importerror_fails_closed(self):
        from okx.code.risk import should_fail_closed, RiskGateFailMode

        assert should_fail_closed(ImportError("CB module broken"), RiskGateFailMode.CLASSIFIED) is True

    def test_classified_mode_code_error_attributeerror_fails_closed(self):
        from okx.code.risk import should_fail_closed, RiskGateFailMode

        assert should_fail_closed(AttributeError("NoneType has no attribute get"), RiskGateFailMode.CLASSIFIED) is True

    def test_closed_mode_always_fails_closed(self):
        """closed mode: 任何 exception 都 fail-CLOSED (显式保守)."""
        from okx.code.risk import should_fail_closed, RiskGateFailMode

        # 即使是 transient 也 fail-closed
        assert should_fail_closed(OSError("disk full"), RiskGateFailMode.CLOSED) is True
        assert should_fail_closed(ConnectionError("api"), RiskGateFailMode.CLOSED) is True
        # code error 也 fail-closed
        assert should_fail_closed(KeyError("x"), RiskGateFailMode.CLOSED) is True

    def test_open_mode_always_fails_open(self):
        """open mode: 任何 exception 都 fail-OPEN (explicit aggressive, for testing 或已知 buggy env)."""
        from okx.code.risk import should_fail_closed, RiskGateFailMode

        # 即使是 code error 也 fail-open
        assert should_fail_closed(KeyError("x"), RiskGateFailMode.OPEN) is False
        assert should_fail_closed(ValueError("bad"), RiskGateFailMode.OPEN) is False
        assert should_fail_closed(ImportError("x"), RiskGateFailMode.OPEN) is False

    def test_unknown_mode_defaults_to_fail_closed(self):
        """未知 mode → fail-closed (safer default, 不静默 fail-open)."""
        from okx.code.risk import should_fail_closed

        # typo / config corruption 仍 fail-closed
        assert should_fail_closed(OSError("x"), "clased") is True  # typo
        assert should_fail_closed(KeyError("x"), "") is True
        assert should_fail_closed(KeyError("x"), None) is True


# ──────────────────────────────────────────────────────────────
# _pre_risk_gates classified mode 集成 (8-04 Step 2)
# Default mode=classified: transient → open, code error → closed
# closed/open mode: 显式覆盖 (rare, for testing 或已知 buggy env)
# ──────────────────────────────────────────────────────────────

class TestPreRiskGatesClassifiedMode:
    """_pre_risk_gates() 集成 - classified mode 行为验证。"""

    def test_classified_default_transient_oserror_fails_open(self):
        """classified (default) + OSError → fail-OPEN (transient, recover next tick)."""
        from unittest.mock import Mock
        from okx.code.runner import Runner

        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        runner._portfolio.get_all_positions.side_effect = OSError("disk full")
        runner._config = {"risk": {}}  # no risk_gate_fail_mode → default classified
        runner._notifier = None

        result = runner._pre_risk_gates()

        assert result.passed is True, (
            f"classified + transient OSError 应 fail-open，但 passed={result.passed}"
        )
        assert any("fail-open-transient" in r.lower() for r in result.reasons), (
            f"reason 应含 'fail-open-transient'，实际 reasons={result.reasons}"
        )

    def test_classified_default_keyerror_fails_closed(self):
        """classified (default) + KeyError → fail-CLOSED (code error, unverified position risk)."""
        from unittest.mock import Mock
        from okx.code.runner import Runner

        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        runner._portfolio.get_all_positions.side_effect = KeyError("missing_field")
        runner._config = {"risk": {}}
        runner._notifier = None

        result = runner._pre_risk_gates()

        assert result.passed is False
        assert any("fail-closed" in r.lower() for r in result.reasons)

    def test_explicit_closed_mode_transient_fails_closed(self):
        """closed mode 显式保守: transient 也 fail-closed (override classified)."""
        from unittest.mock import Mock
        from okx.code.runner import Runner

        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        runner._portfolio.get_all_positions.side_effect = OSError("disk full")
        runner._config = {"risk": {}, "risk_gate_fail_mode": "closed"}
        runner._notifier = None

        result = runner._pre_risk_gates()

        assert result.passed is False
        assert any("fail-closed" in r.lower() for r in result.reasons)

    def test_explicit_open_mode_code_error_fails_open(self):
        """open mode 显式激进: code error 也 fail-open (override classified, for testing)."""
        from unittest.mock import Mock
        from okx.code.runner import Runner

        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        runner._portfolio.get_all_positions.side_effect = KeyError("x")
        runner._config = {"risk": {}, "risk_gate_fail_mode": "open"}
        runner._notifier = None

        result = runner._pre_risk_gates()

        assert result.passed is True
        assert any("fail-open" in r.lower() for r in result.reasons)


class TestPreRiskGatesTelegramAlert:
    """_pre_risk_gates fail-closed 必须发 Telegram 报警 (Telegram visibility for ops)。"""

    def test_fail_closed_sends_telegram_alert(self):
        """fail-closed trigger → notifier.notify_error() 被调用。"""
        from unittest.mock import Mock
        from okx.code.runner import Runner

        mock_notifier = Mock()
        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        runner._portfolio.get_all_positions.side_effect = KeyError("missing_field")
        runner._config = {"risk": {}}  # default classified → KeyError → fail-closed
        runner._notifier = mock_notifier

        result = runner._pre_risk_gates()

        assert result.passed is False
        mock_notifier.notify_error.assert_called_once()
        # 验证 alert 内容含 exception type (ops 可快速定位)
        call_args = mock_notifier.notify_error.call_args
        error_msg = call_args[0][0] if call_args[0] else call_args[1].get("error_msg", "")
        assert "KeyError" in error_msg or "missing_field" in error_msg, (
            f"alert error_msg 应含 exception type/name，实际='{error_msg}'"
        )

    def test_fail_open_transient_does_not_send_alert(self):
        """fail-open (transient) → NOT 发 Telegram (避免 alert spam for 临时 I/O 问题)."""
        from unittest.mock import Mock
        from okx.code.runner import Runner

        mock_notifier = Mock()
        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        runner._portfolio.get_all_positions.side_effect = OSError("disk full")
        runner._config = {"risk": {}}  # classified + OSError → fail-open
        runner._notifier = mock_notifier

        result = runner._pre_risk_gates()

        assert result.passed is True
        mock_notifier.notify_error.assert_not_called()

    def test_no_notifier_does_not_break_fail_closed(self):
        """_notifier=None 时 fail-closed 仍工作 (防御性 code, alert 静默 skip)."""
        from unittest.mock import Mock
        from okx.code.runner import Runner

        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        runner._portfolio.get_all_positions.side_effect = KeyError("x")
        runner._config = {"risk": {}}
        runner._notifier = None  # no notifier configured

        result = runner._pre_risk_gates()

        # Should still fail-closed (alert 静默 skip, 不 cascade)
        assert result.passed is False
        assert any("fail-closed" in r.lower() for r in result.reasons)

    def test_alert_failure_does_not_break_fail_closed(self):
        """notify_error 本身抛异常 → fail-closed 仍 work (不能因 Telegram 挂而让 gate 失效)."""
        from unittest.mock import Mock
        from okx.code.runner import Runner

        # Mock notifier whose notify_error throws
        mock_notifier = Mock()
        mock_notifier.notify_error.side_effect = ConnectionError("Telegram API down")

        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        runner._portfolio.get_all_positions.side_effect = KeyError("x")
        runner._config = {"risk": {}}
        runner._notifier = mock_notifier

        result = runner._pre_risk_gates()

        # fail-closed 必须 still work despite Telegram failure
        assert result.passed is False
        assert any("fail-closed" in r.lower() for r in result.reasons)


# ──────────────────────────────────────────────────────────────
# Mixed Model Position Count (8-04 Q1 redesign)
# 仓位计数: manual + system 独立 cap (替代旧 max_concurrent_positions 总数限制)
# 避免 23:00 cron 永久 block by 3 EXTERNAL_WEB_SYNC manual positions
# ──────────────────────────────────────────────────────────────

class TestRunnerPositionCountMixedModel:
    """Runner._count_positions_by_source() 独立计算 manual vs system。"""

    def test_count_zero_positions(self):
        """空 positions → (0, 0)."""
        from okx.code.runner import Runner

        manual, system = Runner._count_positions_by_source([])
        assert manual == 0
        assert system == 0

    def test_count_only_manual_positions(self):
        """3 manual + 0 system → (3, 0)."""
        from okx.code.runner import Runner

        positions = [
            {"strategy": "EXTERNAL_WEB_SYNC", "size": 0.1},
            {"strategy": "EXTERNAL_WEB_SYNC", "size": 0.2},
            {"strategy": "MANUAL_NO_AUTO_CLOSE", "size": 0.3},
        ]
        manual, system = Runner._count_positions_by_source(positions)
        assert manual == 3
        assert system == 0

    def test_count_only_system_positions(self):
        """0 manual + 2 system → (0, 2)."""
        from okx.code.runner import Runner

        positions = [
            {"strategy": "EMA20_BREAKOUT", "size": 0.1},
            {"strategy": "C_VOLATILITY_BREAKOUT", "size": 0.2},
        ]
        manual, system = Runner._count_positions_by_source(positions)
        assert manual == 0
        assert system == 2

    def test_count_mixed_manual_and_system(self):
        """3 manual + 2 system → (3, 2)."""
        from okx.code.runner import Runner

        positions = [
            {"strategy": "EXTERNAL_WEB_SYNC", "size": 0.1},
            {"strategy": "EMA20_BREAKOUT", "size": 0.1},
            {"strategy": "EXTERNAL_WEB_SYNC", "size": 0.2},
            {"strategy": "C_VOLATILITY_BREAKOUT", "size": 0.2},
            {"strategy": "MANUAL_NO_AUTO_CLOSE", "size": 0.3},
        ]
        manual, system = Runner._count_positions_by_source(positions)
        assert manual == 3
        assert system == 2

    def test_count_handles_missing_strategy_field(self):
        """position 缺 strategy 字段 → 默认 system (保守)."""
        from okx.code.runner import Runner

        positions = [
            {"strategy": "EXTERNAL_WEB_SYNC"},  # manual
            {},  # missing → default system
            {"strategy": ""},  # empty → system
        ]
        manual, system = Runner._count_positions_by_source(positions)
        assert manual == 1
        assert system == 2

    def test_size_zero_position_still_counts(self):
        """size=0 (zombie) 仍占 position slot (defense-in-depth, 8-04 #1 fix)."""
        from okx.code.runner import Runner

        positions = [
            {"strategy": "EXTERNAL_WEB_SYNC", "size": 0.1},
            {"strategy": "EMA20_BREAKOUT", "size": 0.0},  # zombie
        ]
        manual, system = Runner._count_positions_by_source(positions)
        assert manual == 1
        assert system == 1  # zombie counts toward system capacity


# ──────────────────────────────────────────────────────────────
# Config 新字段测试 (8-04 Q1 + Q4-Q10 redesign)
# ──────────────────────────────────────────────────────────────

class TestConfigNewFields:
    """Config 接受新字段 + 默认值."""

    def test_config_max_manual_positions_default_5(self, monkeypatch):
        """缺 config 字段 → 默认 max_manual_positions=5."""
        # 使用 tmp config 文件避免污染
        import tempfile, json
        from okx.code.config import Config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"trading": {}}, f)
            tmp_path = f.name

        config = Config(config_path=tmp_path)
        assert config.max_manual_positions == 5, (
            f"缺省 max_manual_positions 应为 5, 实际 {config.max_manual_positions}"
        )

    def test_config_max_system_positions_default_5(self):
        """缺 config 字段 → 默认 max_system_positions=5."""
        import tempfile, json
        from okx.code.config import Config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"trading": {}}, f)
            tmp_path = f.name

        config = Config(config_path=tmp_path)
        assert config.max_system_positions == 5

    def test_config_max_total_positions_default_10(self):
        """缺 config 字段 → 默认 max_total_positions=10 (5+5)."""
        import tempfile, json
        from okx.code.config import Config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"trading": {}}, f)
            tmp_path = f.name

        config = Config(config_path=tmp_path)
        assert config.max_total_positions == 10



# ──────────────────────────────────────────────────────────────
# _pre_risk_gates Fail-Closed (8-04 Audit #2)
# Iron Rule #11: 金融 sentinel 必须在 exception 时 fail-closed (拒入场，不放)
# 防止 unknown state 让 unverified position 通过 risk gate
# ──────────────────────────────────────────────────────────────

class TestPreRiskGatesFailClosed:
    """Runner._pre_risk_gates() exception handling 必须 fail-closed。

    8-04 audit 发现: 当前实现 catch 任何 Exception → passed=True (fail-open)。
    金融系统 sentinel 应 fail-closed：未知状态宁可拒，不放行 unverified 仓位。
    """

    def test_exception_in_get_positions_returns_fail_closed(self):
        """_portfolio.get_all_positions() 抛 RuntimeError → _pre_risk_gates 必须 passed=False.

        当前 (fail-open): passed=True + "fail-open: ..."  → test RED
        修复后 (fail-closed): passed=False + "fail-closed: ..." → test GREEN
        """
        from unittest.mock import Mock
        from okx.code.runner import Runner

        # 构造 minimal Runner（跳过 __init__ 避免网络/IO 依赖）
        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        runner._portfolio.get_all_positions.side_effect = RuntimeError("portfolio read failed")
        runner._config = {"risk": {}}  # minimal config

        result = runner._pre_risk_gates()

        # 核心断言：金融 sentinel fail-closed
        assert result.passed is False, (
            f"金融 sentinel 必须在 exception 时 fail-closed (passed=False)，"
            f"但 passed={result.passed}. reasons={result.reasons}"
        )
        assert any("fail-closed" in r.lower() for r in result.reasons), (
            f"reason 必须含 'fail-closed' 标识以便 audit log 区分 fail-open vs fail-closed. "
            f"reasons={result.reasons}"
        )

    def test_value_error_in_aggregate_returns_fail_closed(self):
        """aggregate 抛 ValueError (e.g. bad config parse) → 同样 fail-closed.

        不同 exception type 验证 fail-closed 行为一致（不只是 RuntimeError）。
        """
        from unittest.mock import Mock
        from okx.code.runner import Runner

        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        runner._portfolio.get_all_positions.side_effect = ValueError("bad config")
        runner._config = {"risk": {}}

        result = runner._pre_risk_gates()

        assert result.passed is False
        assert any("fail-closed" in r.lower() for r in result.reasons)

    def test_happy_path_still_passes_when_no_exception(self):
        """正常路径（无 exception）必须仍 passed=True（不 regression fail-closed 逻辑）.

        防 accidental over-correction: fail-closed 只在 exception 时触发，正常路径不变。
        """
        from unittest.mock import Mock
        from okx.code.runner import Runner

        runner = Runner.__new__(Runner)
        runner._portfolio = Mock()
        # 1 个 manual position，宽松 config → 应 passed
        runner._portfolio.get_all_positions.return_value = [
            make_position(strategy="EXTERNAL_WEB_SYNC", size=0.1, entry_price=50000.0),
        ]
        runner._config = {
            "risk": {
                "max_total_notional_usdt": 1000000.0,  # 宽松
                "max_net_directional_bias_pct": 1.0,
                "max_single_position_pct": 1.0,
                "max_leverage": 20,
                "max_system_positions_after_manual": 5,
            }
        }

        result = runner._pre_risk_gates()

        assert result.passed is True
        assert result.failed_gates == []
