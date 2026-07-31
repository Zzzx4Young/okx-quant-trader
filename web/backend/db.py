# -*- coding: utf-8 -*-
"""
OKX 历史数据 SQLite store —— v1.4 Phase 1 (P3#4-B)

设计目标：
  - 持久化 cron 运行 / portfolio 快照 / 健康度指标
  - 用 sqlite3 stdlib（无新依赖）
  - WAL mode 支持并发读 + 单写
  - 为前端 dashboard 提供历史 API 数据源（4-C Charts 依赖）

Schema:
  cron_runs            — 每次 cron 执行记录
  portfolio_snapshots  — portfolio 状态时序快照
  health_metrics       — liveness_probe 检查项历史

用法：
  from okx.web.backend.db import init_db, record_cron_run
  init_db()  # 幂等
  record_cron_run("okx-daily-heartbeat", "ok", summary={"equity": 79234.5})

跑测：bash run.sh -m pytest okx/tests/test_db_history.py -v
CLI：python3 -m okx.web.backend.db init
"""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


# ──────────────── 路径 ────────────────

# 默认 DB: okx/web/backend/okx_history.sqlite
# 同目录避免跨 fs (SQLite WAL 需要)
_DEFAULT_DB_PATH = Path(__file__).parent / "okx_history.sqlite"


# ──────────────── Schema ────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS cron_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc   TEXT NOT NULL,
    cron_name       TEXT NOT NULL,
    status          TEXT NOT NULL,
    summary_json    TEXT,
    duration_ms     INTEGER,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_cron_runs_ts    ON cron_runs(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_cron_runs_name  ON cron_runs(cron_name);
CREATE INDEX IF NOT EXISTS idx_cron_runs_status ON cron_runs(status);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc   TEXT NOT NULL,
    equity_usdt     REAL NOT NULL,
    position_count  INTEGER NOT NULL,
    daily_pnl_usdt  REAL,
    positions_json  TEXT,
    source          TEXT DEFAULT 'demo'  -- 'demo' | 'live'
);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_ts ON portfolio_snapshots(timestamp_utc);

CREATE TABLE IF NOT EXISTS health_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc   TEXT NOT NULL,
    component       TEXT NOT NULL,  -- e.g. 'logs/runner.log'
    level           TEXT NOT NULL,  -- 'ok' | 'warn' | 'critical'
    age_seconds     REAL,
    detail_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_health_metrics_ts        ON health_metrics(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_health_metrics_component ON health_metrics(component);
"""


# ──────────────── Connection ────────────────


@contextmanager
def get_conn(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """SQLite 连接 context manager (auto-commit + rollback on error)"""
    db_path = db_path or _DEFAULT_DB_PATH
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    # WAL mode: 支持并发读 + 单写（dashboard 读 vs cron 写不阻塞）
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # WAL + NORMAL 平衡性能与安全
    # v1.4 自愈: idempotent schema init (消除「调用者必须先 init_db」隐式依赖)
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> None:
    """初始化 schema (幂等)"""
    db_path = db_path or _DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA)


def _now_iso() -> str:
    """UTC ISO-8601 timestamp"""
    return datetime.now(timezone.utc).isoformat()


# ──────────────── Write helpers ────────────────


def record_cron_run(
    cron_name: str,
    status: str,
    summary: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """记录一次 cron 执行。

    :param cron_name: cron job name (e.g. 'okx-daily-heartbeat')
    :param status: 'ok' | 'warn' | 'error' | 'skipped'
    :param summary: dict, JSON-serialized 写入 summary_json 字段
    :param duration_ms: 执行耗时 (ms)
    :param error: 错误信息 (status='error' 时填)
    :return: rowid
    """
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO cron_runs (timestamp_utc, cron_name, status, summary_json, duration_ms, error) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                _now_iso(),
                cron_name,
                status,
                json.dumps(summary, ensure_ascii=False) if summary else None,
                duration_ms,
                error,
            ),
        )
        return cur.lastrowid


def record_portfolio_snapshot(
    equity_usdt: float,
    position_count: int,
    daily_pnl_usdt: Optional[float] = None,
    positions: Optional[List[Dict[str, Any]]] = None,
    source: str = "demo",
    db_path: Optional[Path] = None,
) -> int:
    """记录一次 portfolio 状态快照 (供 dashboard chart 显示历史曲线)

    :param equity_usdt: 当前账户净值 (USDT)
    :param position_count: 当前持仓数
    :param daily_pnl_usdt: 当日累计 PnL
    :param positions: list of position dicts (optional)
    :param source: 'demo' | 'live'
    :return: rowid
    """
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO portfolio_snapshots (timestamp_utc, equity_usdt, position_count, daily_pnl_usdt, positions_json, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                _now_iso(),
                equity_usdt,
                position_count,
                daily_pnl_usdt,
                json.dumps(positions, ensure_ascii=False) if positions else None,
                source,
            ),
        )
        return cur.lastrowid


def record_health_metric(
    component: str,
    level: str,
    age_seconds: Optional[float] = None,
    detail: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> int:
    """记录一次 health check 指标 (来自 liveness_probe 或 watchdog)

    :param component: 'logs/runner.log' | 'logs/heartbeat.log' | etc.
    :param level: 'ok' | 'warn' | 'critical'
    :param age_seconds: 该组件的 mtime age (秒)
    :param detail: dict, JSON-serialized
    :return: rowid
    """
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO health_metrics (timestamp_utc, component, level, age_seconds, detail_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                _now_iso(),
                component,
                level,
                age_seconds,
                json.dumps(detail, ensure_ascii=False) if detail else None,
            ),
        )
        return cur.lastrowid


# ──────────────── Read helpers (供 dashboard API) ────────────────


def get_cron_runs_last_n(
    cron_name: Optional[str] = None,
    n: int = 100,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """获取最近 N 条 cron runs, 可按 name 过滤

    :return: list of dicts (含 summary_json 字段, 调用方需自己 json.loads)
    """
    with get_conn(db_path) as conn:
        if cron_name:
            rows = conn.execute(
                "SELECT * FROM cron_runs WHERE cron_name = ? ORDER BY timestamp_utc DESC LIMIT ?",
                (cron_name, n),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cron_runs ORDER BY timestamp_utc DESC LIMIT ?",
                (n,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_portfolio_snapshots_last_n(
    n: int = 90,
    source: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """获取最近 N 条 portfolio snapshots (供 dashboard 显示历史曲线)

    :param n: 默认 90 条 (~3 个月 daily 快照)
    :param source: None = 全部, 'demo' 或 'live'
    """
    with get_conn(db_path) as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM portfolio_snapshots WHERE source = ? ORDER BY timestamp_utc DESC LIMIT ?",
                (source, n),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM portfolio_snapshots ORDER BY timestamp_utc DESC LIMIT ?",
                (n,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_health_metrics_last_n(
    component: Optional[str] = None,
    n: int = 100,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """获取最近 N 条 health metrics, 可按 component 过滤"""
    with get_conn(db_path) as conn:
        if component:
            rows = conn.execute(
                "SELECT * FROM health_metrics WHERE component = ? ORDER BY timestamp_utc DESC LIMIT ?",
                (component, n),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM health_metrics ORDER BY timestamp_utc DESC LIMIT ?",
                (n,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_health_overview(db_path: Optional[Path] = None) -> Dict[str, Any]:
    """获取每个 component 的最新 health level (供 dashboard overview card)"""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT component, level, age_seconds, timestamp_utc
            FROM health_metrics
            WHERE id IN (
                SELECT MAX(id) FROM health_metrics GROUP BY component
            )
            ORDER BY component
            """
        ).fetchall()
    return {row["component"]: dict(row) for row in rows}


# ──────────────── CLI ────────────────


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="OKX history SQLite store")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Initialize DB schema (idempotent)")
    sub.add_parser("stats", help="Show row counts per table")

    args = parser.parse_args()

    if args.cmd == "init":
        init_db()
        print(f"✅ DB initialized: {_DEFAULT_DB_PATH}")
        return 0

    if args.cmd == "stats":
        with get_conn() as conn:
            for table in ("cron_runs", "portfolio_snapshots", "health_metrics"):
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"  {table}: {count} rows")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(_cli())
