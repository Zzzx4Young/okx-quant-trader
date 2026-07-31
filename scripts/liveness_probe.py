# -*- coding: utf-8 -*-
"""
Liveness Probe · 多源 heartbeat 文件新鲜度检查（Alert b · candidate #7）

设计目标：
    现有 runner_watchdog.py 已检查 last_workflow_result.json（15min）。
    本模块加一层"system-wide liveness"——
    检查多个 heartbeat 文件的新鲜度，发现"silent failure"——cron tick 缺失、
    推送进程未发、风险监控缓存未更新等系统性静默故障。

典型 scenario：
    - crontab 停了（gateway 重启后 systemd timer 未恢复）
    - signal_runner.py 抛 startup Exception 不写 heartbeat
    - heartbeat_push.py 进程假死

检查清单（每个文件独立判定 ok/warn/critical）：
    1. state/signal_runner.heartbeat     K 线驱动 cron 制品（threshold: 30 min）
    2. state/last_workflow_result.json   runner.run() 制品（threshold: 30 min）
    3. state/risk_metrics_cache.json     risk_monitor.py 制品（threshold: 60 min）
    4. state/cron_cache.json             crontab 调度缓存（threshold: 120 min）
    5. state/heartbeat_push/last.txt     heartbeat_push.py 制品（threshold: 26h）

阈值设计：
    OK           age < warn_threshold
    WARN         age in [warn, crit]      → 提示但不阻断
    CRITICAL     age > crit_threshold OR 文件缺失  → 阻断 + 告警

不在 scope：
    - Telegram 推送（Telegram 推送层是 heartbeat_push / risk_monitor，
      liveness_probe 仅写 console + state/last_liveness_report.json 供下游消费）
    - 自动修复（只告警不修复）

用法：
    # 单次 check
    bash run.sh scripts/liveness_probe.py

    # JSON 输出（供 cron / dashboard 消费）
    bash run.sh scripts/liveness_probe.py --json

    # 静默模式（仅 critical 时退出码 = 2，warn 时 1）
    bash run.sh scripts/liveness_probe.py --quiet

跑测：
    bash run.sh -m pytest okx/tests/test_liveness_probe.py -v
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# v1.4 Phase 1 (P3#4-B): SQLite history store hook (非致命)
try:
    from okx.web.backend.db import record_health_metric as _record_health_metric
    from okx.web.backend.events import publish_event as _publish_event
    _DB_AVAILABLE = True
    _SSE_AVAILABLE = True
except Exception as _e:  # pragma: no cover
    _DB_AVAILABLE = False
    _SSE_AVAILABLE = False
    logging.getLogger(__name__).warning(f"SQLite / SSE unavailable: {_e}")

logger = logging.getLogger(__name__)


# ──────────────── 数据结构 ────────────────


@dataclass(frozen=True)
class LivenessThreshold:
    """单个检查的阈值（秒）"""
    warn_sec: int
    crit_sec: int
    description: str


@dataclass
class CheckResult:
    name: str
    path: str
    level: str          # "ok" | "warn" | "critical"
    age_seconds: Optional[float]  # None 表示文件不存在或无法解析
    last_modified_at: Optional[str]
    threshold: dict     # {warn, crit, description}
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LivenessReport:
    timestamp_utc: str
    checks: List[CheckResult]
    overall_level: str  # "ok" | "warn" | "critical" — 严格最差
    critical_count: int
    warn_count: int
    ok_count: int

    def to_dict(self) -> dict:
        return {
            "timestamp_utc": self.timestamp_utc,
            "overall_level": self.overall_level,
            "critical_count": self.critical_count,
            "warn_count": self.warn_count,
            "ok_count": self.ok_count,
            "checks": [c.to_dict() for c in self.checks],
        }


# ──────────────── 配置：各文件的阈值 ────────────────


PROBE_CONFIG: dict = {
    # 设计：全 logs/* 文件（i.e. 由 live crons 写入）
    # 2026-07-25 P0 修复：signal_runner.py 已退 Death Branch后不再被 cron 调，
    # 原 state/signal_runner.heartbeat 检查会永久 stale 误告警。
    # 全部迁到 logs/*：
    #   - runner.log    k 线驱动 + 5min trade cycle 每轮写入
    #   - watchdog.log  runner_watchdog cron 每 15min 写入
    #   - heartbeat.log daily 21:00 CST 推送一次
    #   - anomaly_diagnosis.log  daily 00:00 CST 扫 runner.log
    #   - daily_review.log       daily AI 复盘
    "logs/runner.log": LivenessThreshold(
        warn_sec=600,           # 10 min
        crit_sec=1800,          # 30 min
        description="runner.log（k线驱动 + 5min `bash okx/run.sh run` 写入）",
    ),
    "logs/watchdog.log": LivenessThreshold(
        warn_sec=1800,          # 30 min
        crit_sec=4500,          # 75 min（> 3 个 every-15min 周期）
        description="runner_watchdog cron 每 15min 写入（Layer 1-4 健康检查）",
    ),
    "logs/heartbeat.log": LivenessThreshold(
        # 2026-07-31 P0-1 修复 (okx/problem.md P-1, okx/tests/test_liveness_probe.py):
        # cron `0 21 * * *` 周期 = 24h = 86400s。原阈值 warn=20h, crit=26h 错配 → 永久 stale 误报。
        # 新阈值: warn=28h (1 周期 + 4h slack 容忍 cron delay/clock drift)，
        #         crit=52h (2 周期 + 4h slack → 1 次 miss 后升级)。
        warn_sec=28 * 3600,     # 28h (1 cron period + 4h slack)
        crit_sec=52 * 3600,     # 52h (2 cron periods + 4h slack)
        description="heartbeat_push.py cron 每日 21:00 CST 推送一次",
    ),
    "logs/anomaly_diagnosis.log": LivenessThreshold(
        # 2026-07-31 P0-1 修复: cron `0 0 * * *` 周期 = 24h, 同 heartbeat 错配模式。
        warn_sec=28 * 3600,     # 28h
        crit_sec=52 * 3600,     # 52h
        description="anomaly_diagnosis cron 每日 00:00 CST 扫 runner.log",
    ),
    "logs/daily_review.log": LivenessThreshold(
        # 2026-07-31 P0-1 修复: cron `30 23 * * *` 周期 = 24h, 同 heartbeat 错配模式。
        warn_sec=28 * 3600,     # 28h
        crit_sec=52 * 3600,     # 52h
        description="ai_daily_review cron 每日 AI 复盘",
    ),
}


# ──────────────── 路径解析 ────────────────


def _okx_root() -> Path:
    """okx/ 根目录（liveness_probe.py 在 okx/scripts/）"""
    return Path(__file__).resolve().parent.parent


def _resolve_path(rel: str) -> Path:
    """把 PROBE_CONFIG 的相对路径解析到 okx/<rel>

    例：_resolve_path('state/signal_runner.heartbeat') → /workspace/okx/state/signal_runner.heartbeat
    """
    return _okx_root() / rel


# ──────────────── 向后兼容别名 _state_dir（保留以免其他模块 import 错误）──


def _state_dir() -> Path:
    """兼容别名：返回 okx/state/。新代码请用 _resolve_path() 或 _okx_root()。"""
    return _okx_root() / "state"


# ──────────────── 核心：单 check ────────────────


def _check_file(path: Path, threshold: LivenessThreshold, name: str,
                now: Optional[datetime] = None) -> CheckResult:
    """检查单个文件的新鲜度

    注意：age 基于 file.last_modified_at（filesystem mtime），不是 JSON 内部 timestamp。
          这样不依赖文件作者正确写时间戳字段，更鲁棒。
    """
    now = now or datetime.now(timezone.utc)

    if not path.exists():
        return CheckResult(
            name=name,
            path=str(path.relative_to(path.parent.parent)) if path.is_relative_to(path.parent.parent) else str(path),
            level="critical",
            age_seconds=None,
            last_modified_at=None,
            threshold={"warn_sec": threshold.warn_sec, "crit_sec": threshold.crit_sec,
                       "description": threshold.description},
            note="文件不存在",
        )

    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age_sec = (now - mtime).total_seconds()

    if age_sec < 0:
        # clock skew：mtime 在未来
        level = "warn"
        note = f"mtime 在未来（{age_sec:.0f}s），疑似 clock skew"
    elif age_sec >= threshold.crit_sec:
        level = "critical"
        note = f"超过 crit 阈值 {threshold.crit_sec}s ({age_sec:.0f}s)"
    elif age_sec >= threshold.warn_sec:
        level = "warn"
        note = f"超过 warn 阈值 {threshold.warn_sec}s ({age_sec:.0f}s)"
    else:
        level = "ok"
        note = "新鲜"

    return CheckResult(
        name=name,
        path=str(path),
        level=level,
        age_seconds=age_sec,
        last_modified_at=mtime.isoformat(),
        threshold={"warn_sec": threshold.warn_sec, "crit_sec": threshold.crit_sec,
                   "description": threshold.description},
        note=note,
    )


def run_probe(now: Optional[datetime] = None) -> LivenessReport:
    """运行全套 liveness check

    :param now: 测试用 now（默认 = 系统当前 UTC）
    :return: LivenessReport
    """
    now = now or datetime.now(timezone.utc)

    checks: List[CheckResult] = []
    for name, threshold in PROBE_CONFIG.items():
        path = _resolve_path(name)
        checks.append(_check_file(path, threshold, name, now=now))

    critical = sum(1 for c in checks if c.level == "critical")
    warn = sum(1 for c in checks if c.level == "warn")
    ok = sum(1 for c in checks if c.level == "ok")
    overall = "critical" if critical > 0 else ("warn" if warn > 0 else "ok")

    return LivenessReport(
        timestamp_utc=now.isoformat(),
        checks=checks,
        overall_level=overall,
        critical_count=critical,
        warn_count=warn,
        ok_count=ok,
    )


# ──────────────── 持久化（供下游 cron / dashboard 消费）──


def _report_path() -> Path:
    return _resolve_path("state/last_liveness_report.json")


def persist_report(report: LivenessReport) -> None:
    """写 state/last_liveness_report.json（atomic tmp + rename）"""
    p = _report_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    import os
    os.replace(tmp, p)


# ──────────────── CLI ────────────────


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Liveness probe — 多源 heartbeat 文件新鲜度检查")
    parser.add_argument("--json", action="store_true", help="输出 JSON（供 cron / dashboard 消费）")
    parser.add_argument("--quiet", action="store_true", help="静默模式（仅 critical/warn 时退码 2/1）")
    args = parser.parse_args()

    report = run_probe()
    persist_report(report)

    # v1.4 Phase 1: 写 health metrics 到 SQLite (非致命)
    if _DB_AVAILABLE:
        for c in report.checks:
            try:
                _record_health_metric(
                    component=c.name,
                    level=c.level,
                    age_seconds=c.age_seconds,
                    detail=c.threshold,
                )
            except Exception as _e:  # pragma: no cover
                logging.getLogger(__name__).warning(
                    f"DB write failed for {c.name}: {_e}"
                )

    # v1.4 Phase 2 (P3#4-A): publish event 到 SSE bus (非致命)
    if _SSE_AVAILABLE:
        try:
            _publish_event(
                "liveness_check",
                {
                    "overall_level": report.overall_level,
                    "ok_count": report.ok_count,
                    "warn_count": report.warn_count,
                    "critical_count": report.critical_count,
                },
            )
        except Exception as _e:  # pragma: no cover
            logging.getLogger(__name__).warning(f"SSE publish failed: {_e}")

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        # console 输出（简明）
        emoji = {"ok": "✅", "warn": "⚠️", "critical": "🔴"}
        print(f"Liveness Probe @ {report.timestamp_utc}")
        print(f"Overall: {emoji.get(report.overall_level, '?')} {report.overall_level.upper()}")
        print()
        for c in report.checks:
            age_str = f"{c.age_seconds:.0f}s" if c.age_seconds is not None else "N/A"
            print(f"  {emoji.get(c.level, '?')} {c.name:<30s} age={age_str:>8s}  [{c.level}]")
            print(f"      {c.note}")
            if c.level != "ok":
                print(f"      path: {c.path}")
        print()
        print(f"Summary: ok={report.ok_count} warn={report.warn_count} critical={report.critical_count}")

    # 退出码（供 cron 决策）
    if args.quiet:
        if report.overall_level == "critical":
            sys.exit(2)
        elif report.overall_level == "warn":
            sys.exit(1)
        sys.exit(0)
    else:
        sys.exit(0 if report.overall_level == "ok" else 0)  # 非 quiet 模式不 fail


if __name__ == "__main__":
    main()
