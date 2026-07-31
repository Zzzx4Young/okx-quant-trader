# -*- coding: utf-8 -*-
"""
Liveness Probe 单元测试

覆盖：
  - 文件缺失 → critical
  - 文件超 crit → critical
  - 文件超 warn 但 < crit → warn
  - 文件 < warn → ok
  - mtime 在未来（clock skew）→ warn
  - 整体 level 取最差
  - persist_report 写盘
  - 各文件阈值正确（按需）

跑测：bash run.sh -m pytest okx/tests/test_liveness_probe.py -v
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from okx.scripts.liveness_probe import (  # noqa: E402
    CheckResult,
    LivenessReport,
    LivenessThreshold,
    PROBE_CONFIG,
    _check_file,
    _okx_root,
    _resolve_path,
    _state_dir,
    persist_report,
    run_probe,
)


# ──────────────── Fixtures ────────────────


@pytest.fixture
def tmp_state_dir(tmp_path):
    """临时 okx 根目录（同时含 state/ 和 logs/ 子目录）"""
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    yield tmp_path


def _touch(path: Path, mtime: datetime):
    """touch 文件并设置 mtime"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (mtime.timestamp(), mtime.timestamp()))


# ──────────────── 单 check：_check_file ────────────────


def test_check_file_missing_is_critical(tmp_state_dir):
    """文件不存在 → critical"""
    threshold = LivenessThreshold(warn_sec=600, crit_sec=1800, description="x")
    result = _check_file(tmp_state_dir / "nope.json", threshold, "nope.json",
                         now=datetime.now(timezone.utc))
    assert result.level == "critical"
    assert result.age_seconds is None
    assert "不存在" in result.note


def test_check_file_fresh_is_ok(tmp_state_dir):
    p = tmp_state_dir / "fresh.json"
    now = datetime.now(timezone.utc)
    _touch(p, now - timedelta(seconds=10))
    threshold = LivenessThreshold(warn_sec=600, crit_sec=1800, description="x")
    result = _check_file(p, threshold, "fresh.json", now=now)
    assert result.level == "ok"
    assert result.age_seconds == pytest.approx(10.0, abs=1.0)


def test_check_file_warn_threshold(tmp_state_dir):
    """age 在 [warn, crit) → warn"""
    p = tmp_state_dir / "w.json"
    now = datetime.now(timezone.utc)
    _touch(p, now - timedelta(seconds=900))  # 15 min, warn=600 crit=1800
    threshold = LivenessThreshold(warn_sec=600, crit_sec=1800, description="x")
    result = _check_file(p, threshold, "w.json", now=now)
    assert result.level == "warn"


def test_check_file_crit_threshold(tmp_state_dir):
    """age >= crit → critical"""
    p = tmp_state_dir / "c.json"
    now = datetime.now(timezone.utc)
    _touch(p, now - timedelta(seconds=2000))  # 33 min, crit=1800
    threshold = LivenessThreshold(warn_sec=600, crit_sec=1800, description="x")
    result = _check_file(p, threshold, "c.json", now=now)
    assert result.level == "critical"


def test_check_file_at_exact_warn_threshold(tmp_state_dir):
    """边界：age == warn → warn (>= semantics)"""
    p = tmp_state_dir / "ew.json"
    now = datetime.now(timezone.utc)
    _touch(p, now - timedelta(seconds=600))
    threshold = LivenessThreshold(warn_sec=600, crit_sec=1800, description="x")
    result = _check_file(p, threshold, "ew.json", now=now)
    assert result.level == "warn"


def test_check_file_at_exact_crit_threshold(tmp_state_dir):
    """边界：age == crit → critical (>= semantics)"""
    p = tmp_state_dir / "ec.json"
    now = datetime.now(timezone.utc)
    _touch(p, now - timedelta(seconds=1800))
    threshold = LivenessThreshold(warn_sec=600, crit_sec=1800, description="x")
    result = _check_file(p, threshold, "ec.json", now=now)
    assert result.level == "critical"


def test_check_file_future_mtime_is_warn(tmp_state_dir):
    """mtime 在未来（clock skew）→ warn（不报 critical，避免误报）"""
    p = tmp_state_dir / "future.json"
    now = datetime.now(timezone.utc)
    _touch(p, now + timedelta(seconds=10))  # 未来 10s
    threshold = LivenessThreshold(warn_sec=600, crit_sec=1800, description="x")
    result = _check_file(p, threshold, "future.json", now=now)
    assert result.level == "warn"
    assert "skew" in result.note.lower() or "未来" in result.note


# ──────────────── run_probe ────────────────


def test_run_probe_overall_ok_when_all_fresh(tmp_state_dir):
    """所有文件都新鲜 → overall=ok"""
    now = datetime.now(timezone.utc)
    # 写所有 PROBE_CONFIG 里定义的文件
    for name in PROBE_CONFIG.keys():
        _touch(tmp_state_dir / name, now - timedelta(seconds=10))

    with patch("okx.scripts.liveness_probe._okx_root", return_value=tmp_state_dir):
        report = run_probe(now=now)
    assert report.overall_level == "ok"
    assert report.ok_count == len(PROBE_CONFIG)
    assert report.warn_count == 0
    assert report.critical_count == 0


def test_run_probe_overall_critical_when_one_critical(tmp_state_dir):
    """任一 critical → overall=critical（严格最差）"""
    now = datetime.now(timezone.utc)
    for name in PROBE_CONFIG.keys():
        if name == "logs/runner.log":
            # Stale (超 crit=1800)
            _touch(tmp_state_dir / name, now - timedelta(seconds=7200))
        else:
            _touch(tmp_state_dir / name, now - timedelta(seconds=10))

    with patch("okx.scripts.liveness_probe._okx_root", return_value=tmp_state_dir):
        report = run_probe(now=now)
    assert report.overall_level == "critical"
    assert report.critical_count == 1
    # 其余应该是 ok
    assert report.ok_count == len(PROBE_CONFIG) - 1


def test_run_probe_overall_warn_when_only_warn(tmp_state_dir):
    """只有 warn → overall=warn"""
    now = datetime.now(timezone.utc)
    for name in PROBE_CONFIG.keys():
        # runner.log warn=600, crit=1800 → 11 min (700s) 在 warn 区间
        if name == "logs/runner.log":
            _touch(tmp_state_dir / name, now - timedelta(seconds=700))
        else:
            _touch(tmp_state_dir / name, now - timedelta(seconds=10))

    with patch("okx.scripts.liveness_probe._okx_root", return_value=tmp_state_dir):
        report = run_probe(now=now)
    assert report.overall_level == "warn"
    assert report.warn_count == 1


def test_run_probe_missing_all_files_is_all_critical(tmp_state_dir):
    """所有文件缺失 → 全部 critical"""
    with patch("okx.scripts.liveness_probe._okx_root", return_value=tmp_state_dir):
        report = run_probe()
    assert report.critical_count == len(PROBE_CONFIG)
    assert report.overall_level == "critical"


# ──────────────── 阈值配置 ────────────────


def test_probe_config_has_runner_log_threshold():
    """logs/runner.log 是最敏感的（5min 写入）：warn=10min crit=30min"""
    assert "logs/runner.log" in PROBE_CONFIG
    threshold = PROBE_CONFIG["logs/runner.log"]
    assert threshold.warn_sec == 600
    assert threshold.crit_sec == 1800


def test_probe_config_has_heartbeat_push_threshold():
    """logs/heartbeat.log 是 daily-cadence（cron `0 21 * * *` 周期 24h）。

    关键断言（2026-07-31 P0-1 修复, okx/problem.md P-1）：
    - warn_sec 必须 > 24h 周期，否则每次 cron 执行后第 4h 开始 stale 误报
    - crit_sec 必须 > 48h（2 倍周期），允许 1 次 miss 后升级到 critical

    历史佐证：2026-07-31 19:36 daily_review WARN, 20:06 anomaly WARN 是
    cron 周期 24h 但 warn_sec=20h 错配的直接结果（runtime 已 cascade 验证）。
    """
    assert "logs/heartbeat.log" in PROBE_CONFIG
    threshold = PROBE_CONFIG["logs/heartbeat.log"]
    # warn 必须 > 24h 周期（86400s）
    assert threshold.warn_sec > 24 * 3600, (
        f"heartbeat.log warn_sec={threshold.warn_sec}s ≤ 24h cron 周期 → 慢性 stale 误报"
    )
    # crit 必须 > 48h（2 倍周期）
    assert threshold.crit_sec > 2 * 24 * 3600, (
        f"heartbeat.log crit_sec={threshold.crit_sec}s ≤ 48h → 无法区分真故障和正常周期"
    )


def test_probe_config_all_daily_cadence_logs_have_above_period_thresholds():
    """所有 daily-cadence log（cron 周期 24h）必须 warn > 24h, crit > 48h

    P0-1 修复（okx/problem.md P-1）：
    - logs/heartbeat.log          (cron `0 21 * * *`  @ Asia/Shanghai)
    - logs/anomaly_diagnosis.log  (cron `0 0 * * *`   @ Asia/Shanghai)
    - logs/daily_review.log       (cron `30 23 * * *` @ Asia/Shanghai)

    当前 bug (2026-07-31 已确认): 三个 log 全部 warn=20h, crit=26h
    → 每次 cron 执行后第 4h 开始 WARN, 永久 stale 误报
    → runtime 19:36 / 20:06 已 cascade 验证（runtime context 时间线）
    """
    daily_logs = [
        "logs/heartbeat.log",
        "logs/anomaly_diagnosis.log",
        "logs/daily_review.log",
    ]
    for log_name in daily_logs:
        assert log_name in PROBE_CONFIG, (
            f"{log_name} 必须在 PROBE_CONFIG 中（见 scripts/liveness_probe.py:110-145）"
        )
        t = PROBE_CONFIG[log_name]
        # warn 必须 > 24h cron 周期
        assert t.warn_sec > 24 * 3600, (
            f"{log_name} warn_sec={t.warn_sec}s (={t.warn_sec/3600:.1f}h) "
            f"≤ 24h cron 周期 → 慢性 stale 误报"
        )
        # crit 必须 > 48h（2 倍周期，允许 1 次 miss 后升级）
        assert t.crit_sec > 2 * 24 * 3600, (
            f"{log_name} crit_sec={t.crit_sec}s (={t.crit_sec/3600:.1f}h) "
            f"≤ 48h（2 倍 cron 周期）→ 无法区分真故障和正常周期"
        )


def test_probe_config_is_all_logs_only():
    """2026-07-25 P0 修复：PROBE_CONFIG 全部迁到 logs/*（避免 state 文件假阳性）"""
    for name in PROBE_CONFIG.keys():
        assert name.startswith("logs/"), f"state/* 检查会导致假阳性 stale-告警: {name}"


def test_all_thresholds_have_positive_values():
    """所有阈值都 > 0 且 warn < crit"""
    for name, threshold in PROBE_CONFIG.items():
        assert threshold.warn_sec > 0, f"{name} warn_sec 应 > 0"
        assert threshold.crit_sec > threshold.warn_sec, f"{name} crit 应 > warn"


# ──────────────── 持久化 ────────────────


def test_persist_report_writes_atomically(tmp_state_dir):
    """persist_report 写 last_liveness_report.json"""
    report = LivenessReport(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        checks=[
            CheckResult(
                name="test", path="/x", level="ok",
                age_seconds=10.0, last_modified_at="2026-07-24T00:00:00+00:00",
                threshold={"warn_sec": 600, "crit_sec": 1800, "description": "x"},
                note="x",
            )
        ],
        overall_level="ok",
        critical_count=0, warn_count=0, ok_count=1,
    )
    with patch("okx.scripts.liveness_probe._okx_root", return_value=tmp_state_dir):
        persist_report(report)
    out = tmp_state_dir / "state" / "last_liveness_report.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["overall_level"] == "ok"
    assert data["ok_count"] == 1


def test_persist_report_atomic_no_tmp_left(tmp_state_dir):
    """写盘不应残留 .tmp"""
    report = LivenessReport(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        checks=[],
        overall_level="ok",
        critical_count=0, warn_count=0, ok_count=0,
    )
    with patch("okx.scripts.liveness_probe._okx_root", return_value=tmp_state_dir):
        persist_report(report)
    out = tmp_state_dir / "state" / "last_liveness_report.json"
    # 不能有 .tmp
    leftovers = list(tmp_state_dir.glob("*.tmp"))
    assert not leftovers, f"残留 tmp: {leftovers}"


# ──────────────── LivenessReport 数据结构 ────────────────


def test_liveness_report_to_dict():
    """to_dict 输出包含关键字段"""
    report = LivenessReport(
        timestamp_utc="2026-07-24T00:00:00+00:00",
        checks=[
            CheckResult(
                name="a", path="/p", level="ok",
                age_seconds=1.0, last_modified_at="2026-07-24T00:00:00+00:00",
                threshold={"warn_sec": 600, "crit_sec": 1800, "description": "x"},
            )
        ],
        overall_level="ok",
        critical_count=0, warn_count=0, ok_count=1,
    )
    d = report.to_dict()
    assert d["timestamp_utc"] == "2026-07-24T00:00:00+00:00"
    assert d["overall_level"] == "ok"
    assert d["checks"][0]["name"] == "a"
    assert d["checks"][0]["level"] == "ok"


# ──────────────── CheckResult 数据结构 ────────────────


def test_check_result_to_dict_full():
    """to_dict 输出所有字段"""
    cr = CheckResult(
        name="x", path="/y", level="warn",
        age_seconds=900.0, last_modified_at="2026-07-24T00:00:00+00:00",
        threshold={"warn_sec": 600, "crit_sec": 1800, "description": "z"},
        note="note text",
    )
    d = cr.to_dict()
    assert d["name"] == "x"
    assert d["path"] == "/y"
    assert d["level"] == "warn"
    assert d["age_seconds"] == 900.0
    assert d["note"] == "note text"
