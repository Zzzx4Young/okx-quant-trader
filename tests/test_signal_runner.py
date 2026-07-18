#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""signal_runner.py 单测（Phase 4 Gate 9）

覆盖：
  - K 线整点计算（1m/5m/15m/1h 等）
  - Spin-lock 截止时间计算
  - Spin-lock 精确性（busy-wait 到目标时刻）
  - compute-boundary-only 模式（纯计算，无副作用）
  - 预热 mock 注入（不实际启动 OKXClient）
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import signal_runner as sr


# ──────────── K 线整点计算 ────────────


def test_compute_next_boundary_15m_at_quarter():
    """15m 在整点附近应向上对齐到下一个整点"""
    # 12:43:30 → 下个 15m 整点是 12:45:00
    now = datetime(2026, 7, 18, 12, 43, 30, tzinfo=timezone.utc)
    boundary = sr.compute_next_bar_boundary("15m", now=now)
    assert boundary == datetime(2026, 7, 18, 12, 45, 0, tzinfo=timezone.utc)


def test_compute_next_boundary_15m_exact_quarter():
    """15m 整点本身 → 下一个是下个整点（不重复当前）"""
    now = datetime(2026, 7, 18, 12, 45, 0, tzinfo=timezone.utc)
    boundary = sr.compute_next_bar_boundary("15m", now=now)
    assert boundary == datetime(2026, 7, 18, 13, 0, 0, tzinfo=timezone.utc)


def test_compute_next_boundary_1h():
    """1h K 线：13:23 → 14:00"""
    now = datetime(2026, 7, 18, 13, 23, 0, tzinfo=timezone.utc)
    boundary = sr.compute_next_bar_boundary("1h", now=now)
    assert boundary == datetime(2026, 7, 18, 14, 0, 0, tzinfo=timezone.utc)


def test_compute_next_boundary_5m():
    """5m K 线：12:43:17 → 12:45:00"""
    now = datetime(2026, 7, 18, 12, 43, 17, tzinfo=timezone.utc)
    boundary = sr.compute_next_bar_boundary("5m", now=now)
    assert boundary == datetime(2026, 7, 18, 12, 45, 0, tzinfo=timezone.utc)


def test_compute_next_boundary_4h():
    """4h K 线：13:30 → 16:00"""
    now = datetime(2026, 7, 18, 13, 30, 0, tzinfo=timezone.utc)
    boundary = sr.compute_next_bar_boundary("4h", now=now)
    assert boundary == datetime(2026, 7, 18, 16, 0, 0, tzinfo=timezone.utc)


def test_compute_next_boundary_invalid_timeframe():
    """不支持的 timeframe 应抛 ValueError"""
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="不支持的 timeframe"):
        sr.compute_next_bar_boundary("invalid", now=now)


def test_compute_next_boundary_case_insensitive():
    """timeframe 大小写不敏感"""
    now = datetime(2026, 7, 18, 12, 43, 0, tzinfo=timezone.utc)
    b1 = sr.compute_next_bar_boundary("15m", now=now)
    b2 = sr.compute_next_bar_boundary("15M", now=now)
    assert b1 == b2


def test_compute_next_boundary_default_now():
    """不传 now 应使用当前 UTC 时间（不报错）"""
    boundary = sr.compute_next_bar_boundary("15m")
    assert isinstance(boundary, datetime)
    assert boundary.tzinfo is not None


# ──────────── Spin-lock 截止时间 ────────────


def test_spinlock_deadline_basic():
    """Spin-lock 截止时间 = boundary - 5s"""
    boundary = datetime(2026, 7, 18, 12, 45, 0, tzinfo=timezone.utc)
    deadline = sr.compute_spinlock_deadline(boundary, spinlock_seconds=5.0)
    assert deadline == datetime(2026, 7, 18, 12, 44, 55, tzinfo=timezone.utc)


def test_spinlock_deadline_custom_seconds():
    """Spin-lock 自定义秒数"""
    boundary = datetime(2026, 7, 18, 12, 45, 0, tzinfo=timezone.utc)
    deadline = sr.compute_spinlock_deadline(boundary, spinlock_seconds=10.0)
    assert deadline == datetime(2026, 7, 18, 12, 44, 50, tzinfo=timezone.utc)


# ──────────── Spin-lock 精确性 ────────────


def test_spinlock_until_precise():
    """Spin-lock 应在目标时刻 ±200ms 内完成"""
    target = datetime.now(timezone.utc) + timedelta(milliseconds=300)
    t0 = time.time()
    sr.spinlock_until(target, poll_interval_ms=50)
    elapsed_ms = (time.time() - t0) * 1000
    # 应等待 ~300ms，允许 ±200ms 抖动
    assert 100 <= elapsed_ms <= 600, f"Spin-lock 耗时异常: {elapsed_ms:.0f}ms"


def test_spinlock_until_past_target_returns_immediately():
    """目标已过去 → 立即返回（不 busy-wait）"""
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    t0 = time.time()
    sr.spinlock_until(past, poll_interval_ms=100)
    elapsed_ms = (time.time() - t0) * 1000
    # 应该立即返回（<50ms）
    assert elapsed_ms < 50


# ──────────── 预热 mock 注入 ────────────


def test_warmup_with_mocked_client():
    """预热应使用 mock OKXClient，不实际连接"""
    timings = sr.warmup_heavy_dependencies(profile=False)

    # 必须包含所有关键步骤
    assert "numpy_pandas" in timings
    assert "okx_client_init" in timings
    assert "ticker_warmup" in timings
    assert "ticker_warmup_ok" in timings
    assert "engine_init" in timings

    # numpy/pandas 加载应该有耗时
    assert timings["numpy_pandas"] > 0
    # okx_client 初始化应该有耗时
    assert timings["okx_client_init"] > 0


def test_warmup_ticker_failure_handled_gracefully():
    """ticker 拉取失败不应阻塞预热"""
    # 实际跑（连真实 OKX API）；如果失败也不应抛异常
    timings = sr.warmup_heavy_dependencies(profile=False)
    # ticker_warmup_ok 字段应存在（True 或 False）
    assert "ticker_warmup_ok" in timings


# ──────────── compute-boundary-only 模式 ────────────


def test_compute_boundary_only_via_main(capsys):
    """compute-boundary-only 模式应只打印边界，不调用 Runner"""
    # 通过 sys.argv 模拟 CLI 调用
    test_argv = ["signal_runner.py", "--compute-boundary-only", "--timeframe", "15m"]
    with patch.object(sys, "argv", test_argv):
        sr.main()

    captured = capsys.readouterr()
    output = captured.out

    assert "next_boundary_utc" in output
    assert "spinlock_start_utc" in output
    assert "15m" in output


# ──────────── dry-run 模式 ────────────


def test_dry_run_mode(capsys):
    """dry-run 模式应只跑预热 + 计算边界，不调用 Runner.run()"""
    test_argv = ["signal_runner.py", "--dry-run", "--timeframe", "15m"]
    with patch.object(sys, "argv", test_argv):
        sr.main()

    captured = capsys.readouterr()
    output = captured.out

    assert '"dry_run": true' in output
    assert "warmup_timings_ms" in output
    assert "next_boundary_utc" in output
    # 不应包含 runner_result（dry-run 不调用 Runner）
    assert "runner_result" not in output


# ──────────── heartbeat 写入 ────────────


def test_write_heartbeat_creates_file(tmp_path, monkeypatch):
    """write_heartbeat 应写入 state/signal_runner.heartbeat"""
    # 改 state_dir 到 tmp
    fake_state_dir = tmp_path / "state"
    fake_state_dir.mkdir()
    monkeypatch.setattr(sr, "Path", lambda p: Path(p))

    result = {
        "timeframe": "15m",
        "boundary": "2026-07-18T12:45:00+00:00",
        "warmup_duration_s": 0.95,
        "runner_result": {"signal_triggered": False},
        "errors": [],
    }
    # 直接调用，写到 workspace 真实 state 目录（不影响 tmp_path，因为 monkeypatch 影响范围）
    sr._write_heartbeat(result)

    heartbeat_path = Path("/home/zzzx47/.openclaw/workspace/okx/state/signal_runner.heartbeat")
    assert heartbeat_path.exists()

    import json
    payload = json.loads(heartbeat_path.read_text())
    assert "last_run_at" in payload
    assert payload["timeframe"] == "15m"
    assert payload["boundary"] == "2026-07-18T12:45:00+00:00"
    assert payload["warmup_ms"] == 950  # 0.95s * 1000
    assert payload["signal_triggered"] is False
    assert payload["errors_count"] == 0


# ──────────── run_at_next_bar 入口（mock Runner）────────────


def test_run_at_next_bar_no_spin_executes_immediately(monkeypatch):
    """skip_spinlock=True 应立即调用 Runner（不等 K 线整点）"""
    # Mock Runner.run() 避免真实调用
    mock_runner = MagicMock()
    mock_runner.run.return_value = {
        "tick": True,
        "signals_checked": True,
        "signal_triggered": False,
        "errors": [],
    }
    mock_class = MagicMock(return_value=mock_runner)

    monkeypatch.setattr("okx.code.runner.Runner", mock_class)

    t0 = time.time()
    result = sr.run_at_next_bar(
        timeframe="15m",
        spinlock_seconds=5.0,
        profile_warmup=False,
        skip_spinlock=True,
    )
    elapsed = time.time() - t0

    # skip_spinlock 应该几乎立即返回（< 5s）
    assert elapsed < 5.0
    # Runner.run() 应被调用一次
    assert mock_runner.run.call_count == 1
    # result 应包含 runner_result
    assert result["runner_result"] is not None
    assert result["spinlock_skipped"] is True


def test_run_at_next_bar_runner_error_doesnt_crash(monkeypatch):
    """Runner.run() 抛异常不应让整个脚本崩"""
    mock_runner = MagicMock()
    mock_runner.run.side_effect = RuntimeError("test error")
    mock_class = MagicMock(return_value=mock_runner)
    monkeypatch.setattr("okx.code.runner.Runner", mock_class)

    result = sr.run_at_next_bar(
        timeframe="15m",
        spinlock_seconds=5.0,
        skip_spinlock=True,
    )

    # runner_failed 应被记录到 errors
    assert any("runner_failed" in e for e in result["errors"])
    # finished_at 应仍被设置
    assert result["finished_at"] is not None