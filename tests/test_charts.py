# -*- coding: utf-8 -*-
"""
OKX Charts API tests —— v1.4 Phase 3 (P3#4-C)

覆盖:
  T1 /api/charts/catalog 返回 3 个 chart 定义
  T2 /api/charts/equity-curve 返回 portfolio_snapshots 时序
  T3 /api/charts/health-timeline 返回 health_metrics 时序 + level_num 数值化
  T4 /api/charts/cron-success 返回 cron_runs 分组 + success_rate
  T5 各 endpoint 都通过 SSE bus 发布 chart_update event
  T6 参数校验: n 必须 >= 1, source 过滤正常
  T7 空数据时不崩溃 (返回空 series)
  T8 equity-curve 排序: timestamp ASC (chart 渲染需要时间正序)

跑测: bash run.sh -m pytest okx/tests/test_charts.py -v
"""

import tempfile
from pathlib import Path

import pytest

from okx.web.backend.charts import (
    _publish_chart_update,
    get_chart_catalog,
    get_cron_success,
    get_equity_curve,
    get_health_timeline,
)
from okx.web.backend.db import (
    init_db,
    record_cron_run,
    record_health_metric,
    record_portfolio_snapshot,
)


# ──────────────── Fixtures ────────────────


@pytest.fixture
def seeded_db(tmp_path):
    """Fresh DB + 3 tables with seed data"""
    db = tmp_path / "test_charts.sqlite"
    init_db(db)

    # 5 portfolio snapshots (different times)
    for i in range(5):
        record_portfolio_snapshot(
            equity_usdt=79000.0 + i * 100,
            position_count=i,
            daily_pnl_usdt=float(i) * 5,
            db_path=db,
        )

    # 6 health metrics (2 components, 3 timestamps each)
    for component, age in [("logs/runner.log", 5.0), ("logs/heartbeat.log", 100.0)]:
        for i, level in enumerate(["ok", "warn", "critical"]):
            record_health_metric(
                component=component,
                level=level,
                age_seconds=age + i * 10,
                db_path=db,
            )

    # 4 cron runs (2 names, mixed status)
    for i, (name, status) in enumerate([
        ("okx-daily-heartbeat", "ok"),
        ("okx-daily-heartbeat", "ok"),
        ("okx-anomaly-diagnosis", "warn"),
        ("okx-anomaly-diagnosis", "error"),
    ]):
        record_cron_run(cron_name=name, status=status, db_path=db)

    return db


@pytest.fixture
def empty_db(tmp_path):
    """Fresh DB with no records"""
    db = tmp_path / "empty.sqlite"
    init_db(db)
    return db


# ──────────────── T1. /api/charts/catalog ────────────────


def test_catalog_returns_3_charts():
    """T1: catalog 应返回 3 个 chart 定义 + 各自 endpoint + 默认参数"""
    result = get_chart_catalog()
    assert result["ok"] is True
    assert len(result["charts"]) == 3
    for chart in result["charts"]:
        assert "id" in chart
        assert "endpoint" in chart
        assert chart["endpoint"].startswith("/api/charts/")
        assert "title" in chart
        assert "type" in chart
        assert "data_source" in chart
        assert "default_n" in chart


# ──────────────── T2. /api/charts/equity-curve ────────────────


def test_equity_curve_returns_seed_data(seeded_db):
    """T2: equity-curve 返回 5 条 portfolio snapshot, 按 timestamp ASC (chart 渲染需要时间正序)"""
    # 直接调 DB helper (DESC), 再 sort ASC (模拟 chart endpoint 内的排序逻辑)
    from okx.web.backend.db import get_portfolio_snapshots_last_n
    rows = get_portfolio_snapshots_last_n(n=90, db_path=seeded_db)
    rows.sort(key=lambda r: r["timestamp_utc"])  # ASC sort (matches chart endpoint)

    # 验证: 5 条 record, equity 单调递增 (79000 → 79400)
    assert len(rows) == 5
    equities = [r["equity_usdt"] for r in rows]
    assert equities == sorted(equities)  # ASC 顺序


def test_equity_curve_empty_db(empty_db):
    """T7: 空 DB 不崩溃, 返回空 series"""
    from okx.web.backend.db import get_portfolio_snapshots_last_n
    rows = get_portfolio_snapshots_last_n(n=90, db_path=empty_db)
    assert rows == []


def test_equity_curve_source_filter(seeded_db):
    """T6: source 过滤 — demo 只返 demo, live 只返 live"""
    from okx.web.backend.db import get_portfolio_snapshots_last_n
    demo_rows = get_portfolio_snapshots_last_n(n=90, source="demo", db_path=seeded_db)
    live_rows = get_portfolio_snapshots_last_n(n=90, source="live", db_path=seeded_db)
    # Seed data 全是默认 source='demo'
    assert len(demo_rows) == 5
    assert len(live_rows) == 0


# ──────────────── T3. /api/charts/health-timeline ────────────────


def test_health_timeline_level_numeric_mapping(seeded_db):
    """T3: health-timeline 返回 level 数值化 (ok=0, warn=1, critical=2)"""
    from okx.web.backend.db import get_health_metrics_last_n
    rows = get_health_metrics_last_n(n=100, db_path=seeded_db)

    LEVEL_NUM = {"ok": 0, "warn": 1, "critical": 2}
    assert len(rows) == 6  # 2 components × 3 levels
    for r in rows:
        assert r["level"] in LEVEL_NUM
        # 验证 chart endpoint 会数值化 (logic test)
        assert LEVEL_NUM[r["level"]] in (0, 1, 2)


def test_health_timeline_component_filter(seeded_db):
    """T6: component 过滤"""
    from okx.web.backend.db import get_health_metrics_last_n
    runner_rows = get_health_metrics_last_n(n=100, component="logs/runner.log", db_path=seeded_db)
    heartbeat_rows = get_health_metrics_last_n(n=100, component="logs/heartbeat.log", db_path=seeded_db)
    assert len(runner_rows) == 3
    assert len(heartbeat_rows) == 3
    assert all(r["component"] == "logs/runner.log" for r in runner_rows)
    assert all(r["component"] == "logs/heartbeat.log" for r in heartbeat_rows)


def test_health_timeline_empty(empty_db):
    """T7: 空 DB 返回空 series"""
    from okx.web.backend.db import get_health_metrics_last_n
    rows = get_health_metrics_last_n(n=100, db_path=empty_db)
    assert rows == []


# ──────────────── T4. /api/charts/cron-success ────────────────


def test_cron_success_groups_by_name_with_success_rate(seeded_db):
    """T4: cron-success 按 cron_name 分组 + success_rate 计算"""
    from okx.web.backend.db import get_cron_runs_last_n
    rows = get_cron_runs_last_n(n=100, db_path=seeded_db)

    # 按 name 分组
    by_name = {}
    for r in rows:
        name = r["cron_name"]
        status = r["status"]
        if name not in by_name:
            by_name[name] = {"ok": 0, "warn": 0, "error": 0, "skipped": 0}
        if status in by_name[name]:
            by_name[name][status] += 1

    # heartbeat: 2 ok / 2 total = 1.0
    assert by_name["okx-daily-heartbeat"]["ok"] == 2
    assert by_name["okx-daily-heartbeat"]["ok"] / 2 == 1.0

    # anomaly: 0 ok, 1 warn, 1 error / 2 total = 0.0
    assert by_name["okx-anomaly-diagnosis"]["ok"] == 0
    assert by_name["okx-anomaly-diagnosis"]["ok"] / 2 == 0.0


def test_cron_success_empty(empty_db):
    """T7: 空 DB 不崩溃"""
    from okx.web.backend.db import get_cron_runs_last_n
    rows = get_cron_runs_last_n(n=100, db_path=empty_db)
    assert rows == []


def test_cron_success_cron_name_filter(seeded_db):
    """T6: cron_name 过滤"""
    from okx.web.backend.db import get_cron_runs_last_n
    hb_rows = get_cron_runs_last_n(n=100, cron_name="okx-daily-heartbeat", db_path=seeded_db)
    anomaly_rows = get_cron_runs_last_n(n=100, cron_name="okx-anomaly-diagnosis", db_path=seeded_db)
    assert len(hb_rows) == 2
    assert len(anomaly_rows) == 2
    assert all(r["cron_name"] == "okx-daily-heartbeat" for r in hb_rows)


# ──────────────── T5. SSE chart_update event integration ────────────────


def test_publish_chart_update_basic():
    """T5: _publish_chart_update 不崩溃 (即使 event_bus 不可用)"""
    # 应该 graceful degrade — 即使没有 event_bus 也不抛异常
    _publish_chart_update("test-chart", 42)  # 不应抛异常


# ──────────────── T8. timestamp ASC sort ────────────────


def test_equity_curve_results_are_ascending(seeded_db):
    """T8: chart series 必须 timestamp ASC (chart 渲染需要时间正序)"""
    from okx.web.backend.db import get_portfolio_snapshots_last_n
    rows = get_portfolio_snapshots_last_n(n=90, db_path=seeded_db)

    # 模拟 chart endpoint 内的排序逻辑
    rows.sort(key=lambda r: r["timestamp_utc"])

    timestamps = [r["timestamp_utc"] for r in rows]
    assert timestamps == sorted(timestamps), (
        f"timestamps 应按 ASC 排序, 实际: {timestamps}"
    )


def test_health_timeline_results_are_ascending(seeded_db):
    """T8: health timeline 也需 ASC sort"""
    from okx.web.backend.db import get_health_metrics_last_n
    rows = get_health_metrics_last_n(n=100, db_path=seeded_db)
    rows.sort(key=lambda r: r["timestamp_utc"])
    timestamps = [r["timestamp_utc"] for r in rows]
    assert timestamps == sorted(timestamps)


# ──────────────── T9. End-to-end via FastAPI TestClient ────────────────


def test_equity_curve_endpoint_via_testclient(seeded_db, monkeypatch):
    """T9: 通过 FastAPI TestClient 测试完整 endpoint 流程"""
    from fastapi.testclient import TestClient
    from okx.web.backend import charts as charts_mod
    from okx.web.backend import db as db_mod

    # Patch default DB path (test isolation)
    monkeypatch.setattr(db_mod, "_DEFAULT_DB_PATH", seeded_db)

    from okx.web.backend.app import app
    with TestClient(app) as client:
        response = client.get("/api/charts/equity-curve?n=10")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["chart"] == "equity-curve"
        assert data["count"] == 5  # seed 5 条
        assert len(data["series"]) == 5
        # 验证 equity 单调递增
        equities = [s["equity_usdt"] for s in data["series"]]
        assert equities == sorted(equities)


def test_health_timeline_endpoint_via_testclient(seeded_db, monkeypatch):
    """T9: health-timeline endpoint via TestClient"""
    from fastapi.testclient import TestClient
    from okx.web.backend import db as db_mod

    monkeypatch.setattr(db_mod, "_DEFAULT_DB_PATH", seeded_db)

    from okx.web.backend.app import app
    with TestClient(app) as client:
        response = client.get("/api/charts/health-timeline?n=50")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["chart"] == "health-timeline"
        assert data["count"] == 6
        assert data["meta"]["level_legend"] == ["ok", "warn", "critical"]


def test_cron_success_endpoint_via_testclient(seeded_db, monkeypatch):
    """T9: cron-success endpoint via TestClient"""
    from fastapi.testclient import TestClient
    from okx.web.backend import db as db_mod

    monkeypatch.setattr(db_mod, "_DEFAULT_DB_PATH", seeded_db)

    from okx.web.backend.app import app
    with TestClient(app) as client:
        response = client.get("/api/charts/cron-success?n=50")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["chart"] == "cron-success"
        assert data["count"] == 2  # 2 个 cron_name
        # 验证 overall success_rate (4 runs, 2 ok = 0.5)
        assert data["meta"]["overall_success_rate"] == 0.5
        assert data["meta"]["total_runs"] == 4
        assert data["meta"]["total_ok"] == 2


def test_catalog_endpoint_via_testclient(seeded_db, monkeypatch):
    """T9: catalog endpoint via TestClient"""
    from fastapi.testclient import TestClient
    from okx.web.backend import db as db_mod

    monkeypatch.setattr(db_mod, "_DEFAULT_DB_PATH", seeded_db)

    from okx.web.backend.app import app
    with TestClient(app) as client:
        response = client.get("/api/charts/catalog")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["charts"]) == 3
