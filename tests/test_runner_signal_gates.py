# -*- coding: utf-8 -*-
"""
Runner._pre_signal_gates 单元测试（2026-07-25 P0：gate 下沉到 runner.py）

覆盖：
  - 路径 ① circuit_breaker 阻断 → passed=False, stage="circuit_breaker_blocked"
  - 路径 ② regime_filter 阻断 → passed=False, stage="regime_skipped"
  - 双闸都通过 → passed=True, stage="pre_signal_gates"
  - circuit_breaker 跳过（equity 不可读） → 仍继续到 regime_filter
  - circuit_breaker 异常 → fail-open（不阻断）
  - regime_filter 异常 → fail-open（不阻断）
  - read_current_equity / load_klines / Portfolio 都 mock 避免外部依赖

跑测：cd okx && bash run.sh -m pytest okx/tests/test_runner_signal_gates.py -v
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))


# ──────────────── Fixtures / Helpers ────────────────


def _make_runner_minimal():
    """构造一个最小 Runner 实例（不需要真正 OKX client / portfolio）
    
    _pre_signal_gates 内部 lazy import 全部 module，外部依赖通过 mock 实现。
    """
    from okx.code.runner import Runner
    # Runner.__init__ 依赖 config/notifier/portfolio/client；我们绕过 __init__ 直接 bind
    r = Runner.__new__(Runner)
    r._config = MagicMock()
    r._config.demo_mode = True
    r._config.trade_on_quarter = False  # 让 _is_trade_time() 返回 True
    r._portfolio = MagicMock()
    r._client = MagicMock()
    r._notifier = MagicMock()
    return r


def _circuit_breaker_mock(level: str, skip: bool, reason: str = "ok"):
    """构造一个 mock CircuitBreakerDecision"""
    from okx.scripts.circuit_breaker import CircuitBreakerDecision, CircuitBreakerState
    from datetime import datetime, timezone
    decision = CircuitBreakerDecision(
        skip_signal=skip,
        reason=reason,
        level=level,
        current_dd_pct=0.05,
        current_equity_usd=10000.0,
        peak_equity_usd=10500.0,
        consec_loss_days=0,
        triggered_rules=[],
    )
    state = CircuitBreakerState(
        peak_equity_usd=10500.0,
        peak_recorded_at=datetime.now(timezone.utc).isoformat(),
        last_equity_usd=10000.0,
        last_checked_at=datetime.now(timezone.utc).isoformat(),
    )
    return decision, state


def _regime_strategy_mock(strategy_letter, reason="test reason", ret_90d_pct=-15.0, ema_ratio=0.85):
    """构造 mock recommended_strategy 返回 tuple (strat, reason, feats)"""
    return (strategy_letter, reason, {"ret_90d_pct": ret_90d_pct, "ema_ratio": ema_ratio, "bars": 15000})


# ──────────────── 路径 ① circuit_breaker 阻断 ────────────────


def test_circuit_breaker_critical_blocks():
    """DD ≥ 20% → passed=False, stage=circuit_breaker_blocked"""
    r = _make_runner_minimal()

    decision, state = _circuit_breaker_mock(level="critical", skip=True, reason="DD 25% ≥ crit 20%")

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=3), \
         patch("okx.scripts.circuit_breaker.check", return_value=(decision, state)), \
         patch("okx.scripts.circuit_breaker.save_state"):
        MockPortfolio.return_value._data = {"closed_positions": []}
        result = r._pre_signal_gates()

    assert result["passed"] is False
    assert result["stage"] == "circuit_breaker_blocked"
    assert "circuit_breaker" in result["reason"]
    assert result["circuit_breaker"]["level"] == "critical"
    assert result["circuit_breaker"]["skip_signal"] is True
    assert result["regime"] is None  # 没跑到 regime


def test_circuit_breaker_warn_does_not_block():
    """DD warn 但未到 crit → passed=True, level=warning, 仍继续到 regime"""
    r = _make_runner_minimal()

    decision, state = _circuit_breaker_mock(level="warning", skip=False, reason="DD 12% ≥ warn 10%")

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=2), \
         patch("okx.scripts.circuit_breaker.check", return_value=(decision, state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy",
               return_value=_regime_strategy_mock("A")):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()  # placeholder, regime_strategy is mocked
        result = r._pre_signal_gates()

    assert result["passed"] is True
    assert result["stage"] == "pre_signal_gates"
    assert result["circuit_breaker"]["level"] == "warning"
    assert result["regime"]["strategy"] == "A"


def test_circuit_breaker_no_equity_skips_to_regime():
    """equity 不可读 → circuit_breaker 跳过，但仍跑到 regime_filter"""
    r = _make_runner_minimal()

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=None), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy",
               return_value=_regime_strategy_mock("A")):
        mock_load.return_value.klines = MagicMock()
        result = r._pre_signal_gates()

    assert result["passed"] is True
    assert result["circuit_breaker"] is None
    assert result["regime"]["strategy"] == "A"


def test_circuit_breaker_exception_fail_open():
    """circuit_breaker 异常 → fail-open，继续到 regime"""
    r = _make_runner_minimal()

    with patch("okx.scripts.circuit_breaker.read_current_equity",
               side_effect=Exception("boom")), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy",
               return_value=_regime_strategy_mock("A")):
        mock_load.return_value.klines = MagicMock()
        result = r._pre_signal_gates()

    assert result["passed"] is True  # 没阻断
    assert result["circuit_breaker"] is None
    assert result["regime"]["strategy"] == "A"


# ──────────────── 路径 ② regime_filter 阻断 ────────────────


def test_regime_filter_blocks_on_reject():
    """regime 推荐 None (UP/SIDE) → passed=False, stage=regime_skipped"""
    r = _make_runner_minimal()

    decision, state = _circuit_breaker_mock(level="ok", skip=False)

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(decision, state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy",
               return_value=(None, "UP+EMA多头 拒入场", {"ret_90d_pct": 15.0, "ema_ratio": 1.05, "bars": 15000})):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()
        result = r._pre_signal_gates()

    assert result["passed"] is False
    assert result["stage"] == "regime_skipped"
    assert "regime_filter" in result["reason"]
    assert result["regime"]["strategy"] is None


def test_regime_filter_passes_down():
    """regime 推荐 A (DOWN) → 通过"""
    r = _make_runner_minimal()

    decision, state = _circuit_breaker_mock(level="ok", skip=False)

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(decision, state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy",
               return_value=_regime_strategy_mock("A")):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()
        result = r._pre_signal_gates()

    assert result["passed"] is True
    assert result["regime"]["strategy"] == "A"


def test_regime_filter_exception_fail_open():
    """regime_filter 异常 → fail-open"""
    r = _make_runner_minimal()

    decision, state = _circuit_breaker_mock(level="ok", skip=False)

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(decision, state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load",
               side_effect=Exception("klines load failed")):
        MockPortfolio.return_value._data = {"closed_positions": []}
        result = r._pre_signal_gates()

    assert result["passed"] is True  # fail-open
    assert result["regime"] is None


# ──────────────── 组合与边界 ────────────────


def test_both_pass_returns_stage_pre_signal_gates():
    """CB + regime 都通过 → stage='pre_signal_gates'（默认，不是 blocked/skipped）"""
    r = _make_runner_minimal()

    decision, state = _circuit_breaker_mock(level="ok", skip=False)

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=1), \
         patch("okx.scripts.circuit_breaker.check", return_value=(decision, state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy",
               return_value=_regime_strategy_mock("A")):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()
        result = r._pre_signal_gates()

    assert result["passed"] is True
    assert result["stage"] == "pre_signal_gates"
    assert result["circuit_breaker"]["level"] == "ok"
    assert result["regime"]["strategy"] == "A"


def test_circuit_breaker_blocks_short_circuits_regime():
    """circuit_breaker critical 时不调 regime_filter（短路）"""
    r = _make_runner_minimal()

    decision, state = _circuit_breaker_mock(level="critical", skip=True, reason="DD 25%")

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=5), \
         patch("okx.scripts.circuit_breaker.check", return_value=(decision, state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy") as mock_regime:
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()
        result = r._pre_signal_gates()

        # regime_filter 不应被调用（短路）
        mock_regime.assert_not_called()


def test_result_shape_has_all_keys():
    """返回 dict 必须含全部字段（即使 None）"""
    r = _make_runner_minimal()

    decision, state = _circuit_breaker_mock(level="ok", skip=False)

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(decision, state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy",
               return_value=_regime_strategy_mock("A")):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()
        result = r._pre_signal_gates()

    # 所有 key 必须存在（即使为 None）
    for k in ["passed", "stage", "circuit_breaker", "regime"]:
        assert k in result, f"missing key: {k}"
