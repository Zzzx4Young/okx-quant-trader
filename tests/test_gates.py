# -*- coding: utf-8 -*-
"""
code/gates.py 直接单元测试（2026-07-26 P0：抽离 runner.py / signal_runner.py 共同闸门）

覆盖：
  - 路径 ① circuit_breaker 阻断 → passed=False, stage="circuit_breaker_blocked"
  - 路径 ① cb 短路：阻断时 regime_filter 不被调
  - 路径 ② regime_filter 阻断 → passed=False, stage="regime_skipped"
  - 双闸都通过 → passed=True, stage="pre_signal_gates"
  - 漂移修复 #1: schema "regime"（不是 "regime_decision"）
  - 漂移修复 #3: result["circuit_breaker"]["triggered_rules"] 字段存在
  - 漂移修复 #4: cb / regime emoji 日志通过 caplog 验证
  - circuit_breaker 跳过 (equity 不可读) → 仍跑到 regime_filter
  - circuit_breaker 异常 → fail-open (cb=None)，不阻断
  - regime_filter 异常 → fail-open (regime=None)，不阻断
  - 完整 schema: passed/stage/reason/circuit_breaker/regime/errors 全部存在

跑测：cd okx && bash run.sh -m pytest okx/tests/test_gates.py -v
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))


# ──────────────── Helpers ────────────────


def _cb_decision(
    *,
    level: str = "ok",
    skip: bool = False,
    reason: str = "ok",
    dd_pct: float = 0.05,
    equity: float = 10000.0,
    peak: float = 10500.0,
    consec_loss: int = 0,
    triggered_rules: list | None = None,
):
    """构造 mock CircuitBreakerDecision + State"""
    from okx.scripts.circuit_breaker import CircuitBreakerDecision, CircuitBreakerState
    now = datetime.now(timezone.utc).isoformat()
    decision = CircuitBreakerDecision(
        skip_signal=skip,
        reason=reason,
        level=level,
        current_dd_pct=dd_pct,
        current_equity_usd=equity,
        peak_equity_usd=peak,
        consec_loss_days=consec_loss,
        triggered_rules=list(triggered_rules or []),
    )
    state = CircuitBreakerState(
        peak_equity_usd=peak,
        peak_recorded_at=now,
        last_equity_usd=equity,
        last_checked_at=now,
    )
    return decision, state


def _regime(strategy_letter, reason="test reason", ret_90d_pct=-15.0, ema_ratio=0.85, **extras):
    """构造 mock recommended_strategy 返回 tuple (strat, reason, feats)"""
    feats = {
        "ret_90d_pct": ret_90d_pct,
        "ema_ratio": ema_ratio,
        "ema50": extras.get("ema50", 95.0),
        "ema200": extras.get("ema200", 110.0),
        "bars": extras.get("bars", 15000),
    }
    return (strategy_letter, reason, feats)


def _standard_pass_patches(mock_load, mock_regime, cb_dec=None, cb_state=None):
    """返回标准 'pass-through' patches 的 ctx manager。cb 默认 level=ok 不阻断。"""
    if cb_dec is None or cb_state is None:
        cb_dec, cb_state = _cb_decision(level="ok", skip=False)
    regime_tuple = _regime("A")
    return patch.multiple(
        "okx.scripts.circuit_breaker",
        read_current_equity=MagicMock(return_value=10000.0),
        compute_consecutive_losses=MagicMock(return_value=0),
        check=MagicMock(return_value=(cb_dec, cb_state)),
        save_state=MagicMock(),
    )


# ──────────────── 路径 ① circuit_breaker ────────────────


def test_both_pass_returns_stage_pre_signal_gates():
    """CB level=ok + regime 推荐 A → passed=True, stage=pre_signal_gates"""
    cb_dec, cb_state = _cb_decision(level="ok", skip=False)
    regime_tuple = _regime("A")

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy", return_value=regime_tuple):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    assert result["passed"] is True
    assert result["stage"] == "pre_signal_gates"
    assert result["reason"] is None
    assert result["circuit_breaker"]["level"] == "ok"
    assert result["regime"]["strategy"] == "A"
    assert result["errors"] == []


def test_circuit_breaker_critical_blocks_short_circuits_regime():
    """DD ≥ crit 20% → passed=False, stage=circuit_breaker_blocked + 漂移修复 #3 验证 triggered_rules"""
    cb_dec, cb_state = _cb_decision(
        level="critical",
        skip=True,
        reason="DD 25% ≥ crit 20%",
        triggered_rules=["max_dd_crit"],
    )
    regime_tuple = _regime("A")

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=5), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy") as mock_regime:
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    assert result["passed"] is False
    assert result["stage"] == "circuit_breaker_blocked"
    assert "circuit_breaker" in result["reason"]
    assert "DD 25%" in result["reason"]
    assert result["circuit_breaker"]["skip_signal"] is True
    # 漂移修复 #3: triggered_rules 必须传递
    assert result["circuit_breaker"]["triggered_rules"] == ["max_dd_crit"]
    assert result["regime"] is None
    # 短路: regime_filter 不应被调用
    mock_regime.assert_not_called()


def test_circuit_breaker_warn_does_not_block():
    """DD warn 但未到 crit → passed=True, 仍继续到 regime_filter"""
    cb_dec, cb_state = _cb_decision(
        level="warning",
        skip=False,
        reason="DD 12% ≥ warn 10%",
        dd_pct=0.12,
        triggered_rules=["max_dd_warn"],
    )
    regime_tuple = _regime("A")

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=2), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy", return_value=regime_tuple):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    assert result["passed"] is True
    assert result["stage"] == "pre_signal_gates"
    assert result["circuit_breaker"]["level"] == "warning"
    assert result["circuit_breaker"]["skip_signal"] is False
    assert "DD 12%" in result["circuit_breaker"]["reason"]
    assert result["regime"]["strategy"] == "A"


def test_circuit_breaker_no_equity_skips_to_regime():
    """equity 不可读 (read_current_equity returns None) → cb=None, fail-open, 仍跑 regime"""
    regime_tuple = _regime("A")

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=None), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy", return_value=regime_tuple):
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    assert result["passed"] is True
    assert result["circuit_breaker"] is None  # cb 缺 equity 时不返回 dict，None
    assert result["regime"]["strategy"] == "A"


def test_circuit_breaker_exception_fails_open():
    """read_current_equity 抛异常 → cb 闸 fail-open → 继续到 regime"""
    regime_tuple = _regime("A")

    with patch("okx.scripts.circuit_breaker.read_current_equity",
               side_effect=Exception("boom")), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy", return_value=regime_tuple):
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    assert result["passed"] is True
    assert result["circuit_breaker"] is None
    assert result["regime"]["strategy"] == "A"


# ──────────────── 路径 ② regime_filter ────────────────


def test_regime_filter_blocks_on_reject():
    """regime 推荐 None (UP/SIDE) → passed=False, stage=regime_skipped"""
    cb_dec, cb_state = _cb_decision(level="ok", skip=False)
    regime_tuple = _regime(None, reason="UP+EMA多头 拒入场", ret_90d_pct=15.0, ema_ratio=1.05)

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy", return_value=regime_tuple):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    assert result["passed"] is False
    assert result["stage"] == "regime_skipped"
    assert "regime_filter" in result["reason"]
    assert result["regime"]["strategy"] is None
    # CB 通过但被 regime 拦
    assert result["circuit_breaker"]["level"] == "ok"


def test_regime_filter_blocks_on_empty_list_v1_9_0():
    """v1.9.0 Plan B drift fix: regime_strategy = [] (空 list) → passed=False。

    Plan B mini-refactor 后, recommended_strategy() 返 list[str] (不再是 Optional[str]).
    OLD code `if regime_strategy is None:` 对 [] 永远 False → 错误放行 (UP gate 放行).
    本测试是 RED gate: 抓 gates.py:115 的 is None drift.
    """
    cb_dec, cb_state = _cb_decision(level="ok", skip=False)
    # v1.9.0 API: UP regime → [] + "UP+EMA多头 拒入场"
    regime_tuple = _regime([], reason="UP+EMA多头 拒入场", ret_90d_pct=15.0, ema_ratio=1.05)

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy", return_value=regime_tuple):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    assert result["passed"] is False, (
        f"UP regime ([]) 应被 gate 拒入场 (passed=False), got passed={result['passed']}"
    )
    assert result["stage"] == "regime_skipped", (
        f"stage 应为 regime_skipped, got {result['stage']}"
    )
    assert "regime_filter" in result["reason"]
    assert result["regime"]["strategy"] == [], (
        f"regime.strategy 应为 [] (v1.9.0 API), got {result['regime']['strategy']}"
    )
    # CB 通过但被 regime 拦 (空 list 在 v1.9.0 后等同 None 语义)
    assert result["circuit_breaker"]["level"] == "ok"


def test_regime_filter_exception_fails_open():
    """load_klines 抛异常 → regime 闸 fail-open → passed=True（CB 已通过即可入）"""
    cb_dec, cb_state = _cb_decision(level="ok", skip=False)

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load",
               side_effect=Exception("klines load failed")):
        MockPortfolio.return_value._data = {"closed_positions": []}

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    assert result["passed"] is True
    assert result["circuit_breaker"]["level"] == "ok"
    assert result["regime"] is None


# ──────────────── Schema 验证（漂移修复 #1, #3）────────────


def test_result_schema_unified_regime_not_regime_decision():
    """漂移修复 #1: 必须用 'regime' 而非 'regime_decision' key"""
    cb_dec, cb_state = _cb_decision(level="ok", skip=False)
    regime_tuple = _regime("A")

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy", return_value=regime_tuple):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    assert "regime" in result
    assert "regime_decision" not in result


def test_result_schema_includes_errors_and_triggered_rules():
    """漂移修复 #3: result 含完整 keys（errors 数组 + triggered_rules 字段）"""
    cb_dec, cb_state = _cb_decision(
        level="warning",
        skip=False,
        triggered_rules=["max_dd_warn", "consec_loss_warn"],
    )
    regime_tuple = _regime("A")

    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=3), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy", return_value=regime_tuple):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    # 顶层 schema
    for k in ("passed", "stage", "reason", "circuit_breaker", "regime", "errors"):
        assert k in result, f"missing top-level key: {k}"
    assert isinstance(result["errors"], list)
    assert len(result["errors"]) == 0  # 无异常时 errors=[]

    # cb result 含 triggered_rules
    assert "triggered_rules" in result["circuit_breaker"]
    assert result["circuit_breaker"]["triggered_rules"] == ["max_dd_warn", "consec_loss_warn"]


def test_result_schema_full_keys_present_even_when_none():
    """即使 cb 或 regime 闸因 fail-open 返回 None，顶层 schema 字段必须存在"""
    # cb 不可读 → cb=None
    with patch("okx.scripts.circuit_breaker.read_current_equity", return_value=None), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy",
               return_value=_regime("A")):
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        result = run_pre_signal_gates()

    for k in ("passed", "stage", "reason", "circuit_breaker", "regime", "errors"):
        assert k in result, f"missing top-level key: {k}"
    assert result["circuit_breaker"] is None
    assert result["regime"] is not None


# ──────────────── Emoji 日志（漂移修复 #4）────────────


def test_circuit_breaker_block_emits_emoji_log(caplog):
    """漂移修复 #4: cb block 时 logger.warning 含 🛑"""
    import logging
    cb_dec, cb_state = _cb_decision(
        level="critical",
        skip=True,
        reason="DD 25% ≥ crit 20%",
    )

    with caplog.at_level(logging.WARNING, logger="okx.code.gates"), \
         patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=5), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"):
        MockPortfolio.return_value._data = {"closed_positions": []}

        from okx.code.gates import run_pre_signal_gates
        run_pre_signal_gates()

    assert any("🛑" in record.message and "circuit_breaker" in record.message
               for record in caplog.records), \
        f"期望 🛑 circuit_breaker 阻断 emoji 日志，实际: {[r.message for r in caplog.records]}"


def test_circuit_breaker_ok_emits_emoji_log(caplog):
    """漂移修复 #4: cb ok 时 logger.info 含 🛡️"""
    import logging
    cb_dec, cb_state = _cb_decision(level="ok", skip=False, reason="ok")

    with caplog.at_level(logging.INFO, logger="okx.code.gates"), \
         patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy", return_value=_regime("A")):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        run_pre_signal_gates()

    assert any("🛡️" in record.message and "circuit_breaker" in record.message
               for record in caplog.records), \
        f"期望 🛡️ circuit_breaker 通过 emoji 日志，实际: {[r.message for r in caplog.records]}"


def test_regime_filter_pass_emits_emoji_log(caplog):
    """漂移修复 #4: regime ok 时 logger.info 含 🚦"""
    import logging
    cb_dec, cb_state = _cb_decision(level="ok", skip=False)

    with caplog.at_level(logging.INFO, logger="okx.code.gates"), \
         patch("okx.scripts.circuit_breaker.read_current_equity", return_value=10000.0), \
         patch("okx.code.portfolio.Portfolio") as MockPortfolio, \
         patch("okx.scripts.circuit_breaker.compute_consecutive_losses", return_value=0), \
         patch("okx.scripts.circuit_breaker.check", return_value=(cb_dec, cb_state)), \
         patch("okx.scripts.circuit_breaker.save_state"), \
         patch("okx.code.backtest.data_loader.load") as mock_load, \
         patch("okx.code.regime_filter.recommended_strategy",
               return_value=_regime("A", reason="DOWN+EMA空头")):
        MockPortfolio.return_value._data = {"closed_positions": []}
        mock_load.return_value.klines = MagicMock()

        from okx.code.gates import run_pre_signal_gates
        run_pre_signal_gates()

    assert any("🚦" in record.message and "regime_filter" in record.message
               for record in caplog.records), \
        f"期望 🚦 regime_filter emoji 日志，实际: {[r.message for r in caplog.records]}"
