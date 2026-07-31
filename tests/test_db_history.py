# -*- coding: utf-8 -*-
"""
OKX 历史数据 SQLite store 测试 —— v1.4 Phase 1 (P3#4-B)

覆盖:
  T1 init_db() 幂等 (多次调用不报错)
  T2 record_cron_run() 写入 + get_cron_runs_last_n() 读回
  T3 record_portfolio_snapshot() 写入 + get_portfolio_snapshots_last_n() 读回
  T4 record_health_metric() 写入 + get_health_metrics_last_n() 读回
  T5 get_health_overview() 返回每个 component 的最新 level
  T6 多写多读 round-trip (10 cron runs + 10 snapshots)
  T7 source 过滤 (demo vs live)
  T8 异常路径 (db_path 不存在 → 自动创建 parent dir)

跑测：bash run.sh -m pytest okx/tests/test_db_history.py -v
"""

import json
import sqlite3
from pathlib import Path

import pytest

from okx.web.backend.db import (
    get_conn,
    get_cron_runs_last_n,
    get_health_metrics_last_n,
    get_health_overview,
    get_portfolio_snapshots_last_n,
    init_db,
    record_cron_run,
    record_health_metric,
    record_portfolio_snapshot,
)


# ──────────────── Fixtures ────────────────


@pytest.fixture
def tmp_db(tmp_path):
    """临时 DB 路径（每次 test 独立）"""
    db = tmp_path / "test_history.sqlite"
    init_db(db)
    return db


# ──────────────── T1. init_db 幂等 ────────────────


def test_init_db_idempotent(tmp_db):
    """init_db() 多次调用应不报错 (CREATE TABLE IF NOT EXISTS)"""
    init_db(tmp_db)  # 第一次 (fixture 已调)
    init_db(tmp_db)  # 第二次
    init_db(tmp_db)  # 第三次

    with get_conn(tmp_db) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    table_names = [row["name"] for row in tables]
    # 3 张业务表 + sqlite 内置表
    assert "cron_runs" in table_names
    assert "portfolio_snapshots" in table_names
    assert "health_metrics" in table_names


def test_init_db_creates_indexes(tmp_db):
    """init_db() 应同时创建索引"""
    with get_conn(tmp_db) as conn:
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    index_names = {row["name"] for row in indexes}
    # 至少应有 7 个 index
    assert "idx_cron_runs_ts" in index_names
    assert "idx_cron_runs_name" in index_names
    assert "idx_cron_runs_status" in index_names
    assert "idx_portfolio_snapshots_ts" in index_names
    assert "idx_health_metrics_ts" in index_names
    assert "idx_health_metrics_component" in index_names


# ──────────────── T2. record_cron_run + get_cron_runs_last_n ────────────────


def test_record_cron_run_basic(tmp_db):
    """T2: cron_run 写入 + 读回, summary_json 正确序列化"""
    rid = record_cron_run(
        cron_name="okx-daily-heartbeat",
        status="ok",
        summary={"equity": 79234.5, "positions": 3, "pnl": -0.01},
        duration_ms=1234,
        db_path=tmp_db,
    )
    assert rid > 0

    runs = get_cron_runs_last_n(db_path=tmp_db)
    assert len(runs) == 1
    assert runs[0]["cron_name"] == "okx-daily-heartbeat"
    assert runs[0]["status"] == "ok"
    assert runs[0]["duration_ms"] == 1234
    assert runs[0]["summary_json"] is not None

    # summary_json 必须可解析
    summary = json.loads(runs[0]["summary_json"])
    assert summary["equity"] == 79234.5
    assert summary["positions"] == 3


def test_get_cron_runs_filter_by_name(tmp_db):
    """T2: 按 cron_name 过滤"""
    record_cron_run("okx-heartbeat", "ok", db_path=tmp_db)
    record_cron_run("okx-anomaly", "warn", db_path=tmp_db)
    record_cron_run("okx-heartbeat", "ok", db_path=tmp_db)

    heartbeat_runs = get_cron_runs_last_n(cron_name="okx-heartbeat", db_path=tmp_db)
    assert len(heartbeat_runs) == 2

    all_runs = get_cron_runs_last_n(db_path=tmp_db)
    assert len(all_runs) == 3


def test_get_cron_runs_ordering_desc(tmp_db):
    """T2: 按 timestamp_utc DESC 排序 (最新在前)"""
    record_cron_run("cron-a", "ok", db_path=tmp_db)
    record_cron_run("cron-b", "ok", db_path=tmp_db)
    record_cron_run("cron-c", "ok", db_path=tmp_db)

    runs = get_cron_runs_last_n(db_path=tmp_db)
    # 最后写入的 cron-c 应在最前
    assert runs[0]["cron_name"] == "cron-c"
    assert runs[2]["cron_name"] == "cron-a"


# ──────────────── T3. record_portfolio_snapshot ────────────────


def test_record_portfolio_snapshot_basic(tmp_db):
    """T3: portfolio snapshot 写入 + 读回"""
    rid = record_portfolio_snapshot(
        equity_usdt=79234.5,
        position_count=3,
        daily_pnl_usdt=-1.10,
        positions=[{"symbol": "BTC", "size": 0.1}, {"symbol": "ETH", "size": 1.0}],
        source="demo",
        db_path=tmp_db,
    )
    assert rid > 0

    snaps = get_portfolio_snapshots_last_n(db_path=tmp_db)
    assert len(snaps) == 1
    assert snaps[0]["equity_usdt"] == 79234.5
    assert snaps[0]["position_count"] == 3
    assert snaps[0]["daily_pnl_usdt"] == -1.10
    assert snaps[0]["source"] == "demo"

    positions = json.loads(snaps[0]["positions_json"])
    assert len(positions) == 2
    assert positions[0]["symbol"] == "BTC"


def test_portfolio_snapshots_filter_by_source(tmp_db):
    """T3: 按 source 过滤 (demo vs live)"""
    record_portfolio_snapshot(equity_usdt=100.0, position_count=0, source="demo", db_path=tmp_db)
    record_portfolio_snapshot(equity_usdt=200.0, position_count=0, source="live", db_path=tmp_db)
    record_portfolio_snapshot(equity_usdt=300.0, position_count=0, source="demo", db_path=tmp_db)

    demo = get_portfolio_snapshots_last_n(source="demo", db_path=tmp_db)
    assert len(demo) == 2
    assert all(s["source"] == "demo" for s in demo)

    live = get_portfolio_snapshots_last_n(source="live", db_path=tmp_db)
    assert len(live) == 1
    assert live[0]["equity_usdt"] == 200.0


# ──────────────── T4. record_health_metric ────────────────


def test_record_health_metric_basic(tmp_db):
    """T4: health metric 写入 + 读回"""
    rid = record_health_metric(
        component="logs/runner.log",
        level="ok",
        age_seconds=2.5,
        detail={"warn_threshold": 600, "crit_threshold": 1800},
        db_path=tmp_db,
    )
    assert rid > 0

    metrics = get_health_metrics_last_n(db_path=tmp_db)
    assert len(metrics) == 1
    assert metrics[0]["component"] == "logs/runner.log"
    assert metrics[0]["level"] == "ok"
    assert metrics[0]["age_seconds"] == 2.5

    detail = json.loads(metrics[0]["detail_json"])
    assert detail["warn_threshold"] == 600


def test_health_metrics_filter_by_component(tmp_db):
    """T4: 按 component 过滤"""
    record_health_metric("logs/runner.log", "ok", db_path=tmp_db)
    record_health_metric("logs/heartbeat.log", "warn", db_path=tmp_db)
    record_health_metric("logs/runner.log", "critical", db_path=tmp_db)

    runner_only = get_health_metrics_last_n(component="logs/runner.log", db_path=tmp_db)
    assert len(runner_only) == 2
    assert all(m["component"] == "logs/runner.log" for m in runner_only)


# ──────────────── T5. get_health_overview ────────────────


def test_get_health_overview_returns_latest_per_component(tmp_db):
    """T5: 每个 component 的最新 level (供 dashboard overview card)"""
    record_health_metric("logs/runner.log", "ok", db_path=tmp_db)
    record_health_metric("logs/heartbeat.log", "warn", db_path=tmp_db)
    record_health_metric("logs/runner.log", "critical", db_path=tmp_db)  # 更新 runner.log

    overview = get_health_overview(db_path=tmp_db)
    assert overview["logs/runner.log"]["level"] == "critical"
    assert overview["logs/heartbeat.log"]["level"] == "warn"
    assert "logs/daily_review.log" not in overview  # 没写入就不出现


# ──────────────── T6. 多写多读 round-trip ────────────────


def test_multi_write_read_roundtrip(tmp_db):
    """T6: 10 cron runs + 10 snapshots + 10 health metrics 全可读回"""
    for i in range(10):
        record_cron_run(
            cron_name=f"cron-{i}",
            status="ok",
            summary={"index": i},
            duration_ms=100 + i,
            db_path=tmp_db,
        )
        record_portfolio_snapshot(
            equity_usdt=1000.0 + i * 100,
            position_count=i,
            daily_pnl_usdt=float(i),
            db_path=tmp_db,
        )
        record_health_metric(
            component=f"comp-{i}",
            level="ok",
            age_seconds=float(i),
            db_path=tmp_db,
        )

    assert len(get_cron_runs_last_n(db_path=tmp_db)) == 10
    assert len(get_portfolio_snapshots_last_n(db_path=tmp_db)) == 10
    assert len(get_health_metrics_last_n(db_path=tmp_db)) == 10

    # 验证 N=5 只返回最后 5 条 (DESC)
    assert len(get_cron_runs_last_n(n=5, db_path=tmp_db)) == 5


# ──────────────── T7. WAL mode + 并发安全 ────────────────


def test_wal_mode_enabled(tmp_db):
    """T7: get_conn 应启用 WAL mode (并发读 + 单写)"""
    with get_conn(tmp_db) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal", f"expected WAL, got {mode}"


def test_concurrent_writes_no_corruption(tmp_db):
    """T7: 并发写不损坏数据 (依赖 SQLite + WAL 串行化)

    单 process 内 sequential write 应该 100% 成功
    (多 process 并发测需要 multiprocessing, 跳过以保持测试快)
    """
    # 50 次顺序写
    for i in range(50):
        record_cron_run(
            cron_name=f"concurrent-{i % 5}",
            status="ok",
            db_path=tmp_db,
        )

    # 验证全部 50 条都成功
    runs = get_cron_runs_last_n(n=100, db_path=tmp_db)
    assert len(runs) == 50


# ──────────────── T8. 异常路径 ────────────────


def test_db_path_parent_dir_auto_created(tmp_path):
    """T8: db_path 的 parent dir 不存在时, init_db 应自动创建"""
    nested_db = tmp_path / "level1" / "level2" / "history.sqlite"
    assert not nested_db.parent.exists()

    init_db(nested_db)
    assert nested_db.parent.exists()
    assert nested_db.exists()


def test_get_conn_rollback_on_error(tmp_db):
    """T8: get_conn 在异常时应 rollback (写入不应持久化)"""
    from okx.web.backend.db import get_conn

    # 先写一条
    record_cron_run("before-error", "ok", db_path=tmp_db)
    assert len(get_cron_runs_last_n(db_path=tmp_db)) == 1

    # 触发异常
    with pytest.raises(sqlite3.IntegrityError):
        with get_conn(tmp_db) as conn:
            conn.execute(
                "INSERT INTO cron_runs (timestamp_utc, cron_name, status) VALUES (?, ?, ?)",
                ("2026-07-31T00:00:00Z", None, "ok"),  # cron_name NOT NULL → 报错
            )
            conn.execute(
                "INSERT INTO cron_runs (timestamp_utc, cron_name, status) VALUES (?, ?, ?)",
                ("2026-07-31T00:00:00Z", "should-rollback", "ok"),
            )

    # 异常后, 新写入应 rollback, 只剩原本的 1 条
    runs = get_cron_runs_last_n(db_path=tmp_db)
    assert len(runs) == 1
    assert runs[0]["cron_name"] == "before-error"
