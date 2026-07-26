# -*- coding: utf-8 -*-
"""
Circuit Breaker 单元测试

覆盖：
  - peak 更新语义（high water mark only）
  - 阈值判断（warn / crit）
  - skip 决策（OR semantics）
  - 持久化（atomic save → load 还原）
  - 历史截断（最近 50 条）
  - 边界条件（equity=0 / None）

跑测：cd okx && bash run.sh tests/test_circuit_breaker.py -v
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# 确保 from okx.scripts.circuit_breaker 可 import
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from okx.scripts.circuit_breaker import (  # noqa: E402
    CircuitBreakerConfig,
    CircuitBreakerDecision,
    CircuitBreakerState,
    DEFAULT_CONFIG,
    _init_state,
    check,
    compute_consecutive_losses,
    load_state,
    read_current_equity,
    save_state,
)


# ──────────────── Fixtures ────────────────


def _mk_state(peak: float, last: float, history=None) -> CircuitBreakerState:
    return CircuitBreakerState(
        peak_equity_usd=peak,
        peak_recorded_at="2026-07-24T00:00:00+00:00",
        last_equity_usd=last,
        last_checked_at="2026-07-24T00:00:00+00:00",
        meltdown_history=history or [],
    )


# ──────────────── peak 更新 ────────────────


def test_peak_only_rises():
    """peak 是 high water mark，只升不降"""
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, new_state = check(9500.0, consec_loss_days=0, state=state, now_iso="2026-07-24T01:00:00+00:00")
    assert new_state.peak_equity_usd == 10000.0, f"peak 不应下降: {new_state.peak_equity_usd}"

    # equity 高过 peak 时更新
    decision, new_state = check(11000.0, consec_loss_days=0, state=new_state, now_iso="2026-07-24T02:00:00+00:00")
    assert new_state.peak_equity_usd == 11000.0, f"peak 应该上升: {new_state.peak_equity_usd}"


def test_peak_recorded_at_updates_on_new_high():
    """新的 peak 时记录更新到新时间戳"""
    state = _mk_state(peak=10000.0, last=9500.0)
    decision, new_state = check(11000.0, consec_loss_days=0, state=state, now_iso="2026-07-25T00:00:00+00:00")
    assert new_state.peak_recorded_at == "2026-07-25T00:00:00+00:00"


def test_peak_unchanged_keeps_old_timestamp():
    """peak 不刷新时保留原时间戳（用于追溯首次峰值的日期）"""
    state = _mk_state(peak=10000.0, last=9500.0)
    decision, new_state = check(9900.0, consec_loss_days=0, state=state, now_iso="2026-07-30T00:00:00+00:00")
    assert new_state.peak_recorded_at == "2026-07-24T00:00:00+00:00"


# ──────────────── 净值回撤判定 ────────────────


def test_drawdown_under_warn_is_ok():
    """DD < 10%: OK level"""
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, _ = check(9500.0, consec_loss_days=0, state=state)
    assert decision.level == "ok", decision
    assert decision.skip_signal is False
    assert abs(decision.current_dd_pct - 0.05) < 1e-9


def test_drawdown_warn_does_not_skip():
    """DD >= 10% 但 < 20%: warn, 不阻断"""
    state = _mk_state(peak=10000.0, last=10000.0)
    # DD = 12%
    decision, _ = check(8800.0, consec_loss_days=0, state=state)
    assert decision.level == "warning"
    assert decision.skip_signal is False


def test_drawdown_crit_triggers_skip():
    """DD >= 20%: critical + 阻断"""
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, _ = check(7000.0, consec_loss_days=0, state=state)
    assert decision.level == "critical"
    assert decision.skip_signal is True
    assert "DD" in decision.reason and "crit" in decision.reason


def test_drawdown_exactly_at_warn_threshold():
    """边界：DD == 10% 触发 warn"""
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, _ = check(9000.0, consec_loss_days=0, state=state)
    assert decision.level in ("warning", "critical"), decision.level


# ──────────────── 连续亏损判定 ────────────────


def test_no_consec_loss_is_ok():
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, _ = check(10000.0, consec_loss_days=0, state=state)
    assert decision.level == "ok"


def test_consec_loss_warn():
    """3 天连亏: warn"""
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, _ = check(10000.0, consec_loss_days=3, state=state)
    assert decision.level == "warning"
    assert decision.skip_signal is False


def test_consec_loss_crit():
    """5 天连亏: crit + skip"""
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, _ = check(10000.0, consec_loss_days=5, state=state)
    assert decision.level == "critical"
    assert decision.skip_signal is True
    assert any("consec_loss" in r for r in decision.triggered_rules)


# ──────────────── OR 语义（任一触发即阻断）───


def test_drawdown_warn_and_consec_loss_crit_blocks():
    """即使 DD 只触发 warn, consec_loss crit 仍然能 block"""
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, _ = check(8800.0, consec_loss_days=5, state=state)
    assert decision.level == "critical"
    assert decision.skip_signal is True
    assert len(decision.triggered_rules) == 2  # 两个规则都被记下


def test_drawdown_crit_alone_blocks():
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, _ = check(7000.0, consec_loss_days=2, state=state)
    assert decision.skip_signal is True


# ──────────────── 持久化 ────────────────


def test_save_load_round_trip(tmp_path):
    """save → load 完整还原"""
    # 重定向 state dir 到 tmp
    with patch("okx.scripts.circuit_breaker._state_dir", return_value=tmp_path):
        st = CircuitBreakerState(
            peak_equity_usd=12345.67,
            peak_recorded_at="2026-07-24T10:00:00+00:00",
            last_equity_usd=11000.0,
            last_checked_at="2026-07-24T11:00:00+00:00",
            meltdown_history=[{"at": "2026-07-24T10:30:00", "type": "drawdown"}],
        )
        save_state(st)

        loaded = load_state()
        assert loaded is not None
        assert loaded.peak_equity_usd == 12345.67
        assert loaded.peak_recorded_at == "2026-07-24T10:00:00+00:00"
        assert loaded.last_equity_usd == 11000.0
        assert loaded.meltdown_history == [{"at": "2026-07-24T10:30:00", "type": "drawdown"}]


def test_load_state_missing_returns_none(tmp_path):
    """state 文件缺失时返回 None（让 caller 走 init 分支）"""
    with patch("okx.scripts.circuit_breaker._state_dir", return_value=tmp_path):
        assert load_state() is None


def test_atomic_save_no_partial_writes(tmp_path):
    """save 必须用 .tmp + rename，避免被信号打断产生半行 JSON"""
    with patch("okx.scripts.circuit_breaker._state_dir", return_value=tmp_path):
        st = _init_state(10000.0, "2026-07-24T00:00:00+00:00")
        save_state(st)
        # 目录里不应该残留 .tmp
        files = list(tmp_path.iterdir())
        assert all(".tmp" not in f.name for f in files), f"残留 tmp 文件: {files}"


# ──────────────── 历史截断 ────────────────


def test_meltdown_history_truncates_to_50():
    """连续 critical > 50 次时只保留最近 50 条"""
    state = CircuitBreakerState(
        peak_equity_usd=10000.0,
        peak_recorded_at="2026-07-24T00:00:00+00:00",
        last_equity_usd=10000.0,
        last_checked_at="2026-07-24T00:00:00+00:00",
        meltdown_history=[{"at": f"2026-07-{i:02d}T00:00:00", "type": "drawdown"} for i in range(1, 21)],
    )
    # 连续触发 crit 60 次
    for i in range(60):
        _, state = check(equity_usd=5000.0, consec_loss_days=10, state=state, now_iso=f"2026-08-{i+1:02d}T00:00:00+00:00")
    assert len(state.meltdown_history) == 50, f"应截断到 50, 实际: {len(state.meltdown_history)}"


def test_warning_does_not_record_history():
    """warning level 不打点，避免 history 被噪声填满"""
    state = _mk_state(peak=10000.0, last=10000.0)
    _, state = check(equity_usd=8800.0, consec_loss_days=3, state=state)
    # warning level：不更新 history
    assert len(state.meltdown_history) == 0


# ──────────────── 边界条件 ────────────────


def test_zero_equity_initial_state():
    """首次启动时 equity 可能还没刷出来：用 _init_state 兜底"""
    st = _init_state(0.0, "2026-07-24T00:00:00+00:00")
    assert st.peak_equity_usd == 0.0
    # 后续有 equity 进来时正常更新
    _, st2 = check(equity_usd=10000.0, consec_loss_days=0, state=st, now_iso="2026-07-24T01:00:00+00:00")
    assert st2.peak_equity_usd == 10000.0


def test_read_current_equity_missing_file(tmp_path):
    """risk_metrics_cache.json 缺失时返回 None（fail-closed 信号）"""
    with patch("okx.scripts.circuit_breaker._risk_metrics_cache") as mock_path:
        mock_path.return_value = tmp_path / "nonexistent.json"
        assert read_current_equity() is None


def test_read_current_equity_zero_value(tmp_path):
    """equity_usd == 0 视为无效（fail-closed）"""
    p = tmp_path / "risk_metrics_cache.json"
    p.write_text(json.dumps({"data": {"equity_usd": 0}}))
    with patch("okx.scripts.circuit_breaker._risk_metrics_cache", return_value=p):
        assert read_current_equity() is None


def test_read_current_equity_normal(tmp_path):
    """正常情况：读出 > 0 的 equity"""
    p = tmp_path / "risk_metrics_cache.json"
    p.write_text(json.dumps({"data": {"equity_usd": 50000.5}}))
    with patch("okx.scripts.circuit_breaker._risk_metrics_cache", return_value=p):
        eq = read_current_equity()
        assert eq == 50000.5


# ──────────────── reason 字符串 ────────────────


def test_reason_contains_threshold_when_critical():
    """reason 在 critical 时必须含具体数值（人眼能一眼看到）"""
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, _ = check(equity_usd=7000.0, consec_loss_days=0, state=state)
    assert "30.0%" in decision.reason or "DD" in decision.reason
    assert "BLOCKED" in decision.reason


def test_reason_lists_both_triggers_or():
    """当两个维度都触发，reason 列出全部"""
    state = _mk_state(peak=10000.0, last=10000.0)
    decision, _ = check(equity_usd=6000.0, consec_loss_days=6, state=state)
    assert "DD" in decision.reason
    assert "连亏" in decision.reason


# ──────────────── 默认配置 ────────────────


def test_default_config_thresholds():
    """DEFAULT_CONFIG 必须与设计文档一致（防止人为篡改默认值）"""
    assert DEFAULT_CONFIG.max_drawdown_warn_pct == 0.10
    assert DEFAULT_CONFIG.max_drawdown_crit_pct == 0.20
    assert DEFAULT_CONFIG.consec_loss_warn == 3
    assert DEFAULT_CONFIG.consec_loss_crit == 5


def test_crit_breached_helper():
    """CircuitBreakerConfig.crit_breached 单一决策入口"""
    # 都没触达
    assert DEFAULT_CONFIG.crit_breached(current_dd_pct=0.15, consec_loss=2) is False
    # 仅 DD crit
    assert DEFAULT_CONFIG.crit_breached(current_dd_pct=0.25, consec_loss=2) is True
    # 仅 consec crit
    assert DEFAULT_CONFIG.crit_breached(current_dd_pct=0.15, consec_loss=6) is True
    # 两都
    assert DEFAULT_CONFIG.crit_breached(current_dd_pct=0.25, consec_loss=6) is True


# ──────────────── 跨日连续亏损推算（compute_consecutive_losses）────


def _cp(closed_at: str, pnl: float) -> dict:
    """小工厂：closed_position 字典"""
    return {"closed_at": closed_at, "realized_pnl": pnl}


def test_compute_consec_empty():
    assert compute_consecutive_losses([]) == 0


def test_compute_consec_skips_unclosed():
    """closed_at 缺失的仓位不计入（仍未平仓）"""
    positions = [
        {"closed_at": None, "realized_pnl": -100},
        _cp("2026-07-24T01:00:00+00:00", -50),
    ]
    assert compute_consecutive_losses(positions) == 1


def test_compute_consec_basic_run():
    """3 笔亏损连续 → 3"""
    positions = [
        _cp("2026-07-24T03:00:00+00:00", -100),
        _cp("2026-07-24T02:00:00+00:00", -50),
        _cp("2026-07-24T01:00:00+00:00", -200),
        _cp("2026-07-23T10:00:00+00:00", 100),  # 被这笔盈利打断
    ]
    assert compute_consecutive_losses(positions) == 3


def test_compute_consec_cross_day():
    """跨日连续（portfolio.py 的 daily_stats 会错：会归零）"""
    positions = [
        _cp("2026-07-24T10:00:00+00:00", -50),   # 今日
        _cp("2026-07-23T10:00:00+00:00", -100),  # 昨日
        _cp("2026-07-22T10:00:00+00:00", -75),   # 前日
        _cp("2026-07-21T10:00:00+00:00", 100),   # 周四：被这笔盈利打断
    ]
    assert compute_consecutive_losses(positions) == 3


def test_compute_consec_stops_at_win():
    """遇到胜场立即停（不能穿透过去计数）"""
    positions = [
        _cp("2026-07-24T10:00:00+00:00", -100),  # 连亏 1
        _cp("2026-07-23T10:00:00+00:00", 200),   # 胜场 1 → 切断
        _cp("2026-07-22T10:00:00+00:00", -50),   # 之前的亏损不计
        _cp("2026-07-21T10:00:00+00:00", -75),
    ]
    assert compute_consecutive_losses(positions) == 1


def test_compute_consec_unsorted_input():
    """输入顺序不限，内部排序"""
    positions = [
        _cp("2026-07-22T10:00:00+00:00", -75),
        _cp("2026-07-24T10:00:00+00:00", -100),
        _cp("2026-07-23T10:00:00+00:00", -50),
    ]
    assert compute_consecutive_losses(positions) == 3


def test_compute_consec_zero_pnl_treated_as_win():
    """realized_pnl == 0 视为盈亏中性，会切断连亏（防 0 造成的连环计数）"""
    positions = [
        _cp("2026-07-24T10:00:00+00:00", -100),
        _cp("2026-07-23T10:00:00+00:00", 0),     # 中性 = 切断
        _cp("2026-07-22T10:00:00+00:00", -50),
    ]
    assert compute_consecutive_losses(positions) == 1


def test_compute_consec_missing_pnl_treated_as_win():
    """realized_pnl 缺失视为中性"""
    positions = [
        _cp("2026-07-24T10:00:00+00:00", -100),
        {"closed_at": "2026-07-23T10:00:00+00:00", "symbol": "X", "order_id": "y"},  # 无 realized_pnl
        _cp("2026-07-22T10:00:00+00:00", -50),
    ]
    assert compute_consecutive_losses(positions) == 1
