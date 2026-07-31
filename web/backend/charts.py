# -*- coding: utf-8 -*-
"""
OKX 历史数据 Chart API —— v1.4 Phase 3 (P3#4-C)

3 个 chart endpoint (供 frontend dashboard 显示历史曲线):

  GET /api/charts/equity-curve?n=90      portfolio_snapshots.equity_usdt 时序
  GET /api/charts/health-timeline?n=100  health_metrics.level/age_seconds 时序
  GET /api/charts/cron-success?n=100     cron_runs.status 分布 (按 cron_name 分组)

设计: 纯 read-only, 数据源 = 4-B SQLite, 与 4-A SSE 共享 event_bus (publish chart_update event)

跑测: bash run.sh -m pytest okx/tests/test_charts.py -v
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/charts", tags=["charts"])


def _publish_chart_update(chart_name: str, row_count: int) -> None:
    """4-A SSE integration: 推送 chart data 更新事件"""
    try:
        from okx.web.backend.events import publish_event
        publish_event(
            "chart_update",
            {"chart": chart_name, "rows": row_count},
        )
    except Exception as e:  # pragma: no cover
        logger.warning(f"Failed to publish chart_update event: {e}")


# ──────────── 1. Equity Curve ────────────


@router.get("/equity-curve")
def get_equity_curve(
    n: int = Query(default=90, ge=1, le=365),
    source: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Portfolio equity 时序曲线 (供 PnL LineChart 显示)

    数据源: portfolio_snapshots.equity_usdt + daily_pnl_usdt
    默认 90 条 (~3 个月 daily snapshots)
    """
    from okx.web.backend.db import get_portfolio_snapshots_last_n
    rows = get_portfolio_snapshots_last_n(n=n, source=source)

    # 按 timestamp_utc ASC (frontend chart 通常需要时间正序)
    rows.sort(key=lambda r: r["timestamp_utc"])

    series = [
        {
            "timestamp": r["timestamp_utc"],
            "equity_usdt": r["equity_usdt"],
            "daily_pnl_usdt": r.get("daily_pnl_usdt"),
            "position_count": r["position_count"],
            "source": r.get("source", "demo"),
        }
        for r in rows
    ]

    _publish_chart_update("equity-curve", len(series))

    return {
        "ok": True,
        "chart": "equity-curve",
        "count": len(series),
        "series": series,
        "meta": {
            "source": source or "all",
            "n_requested": n,
            "first_at": series[0]["timestamp"] if series else None,
            "last_at": series[-1]["timestamp"] if series else None,
        },
    }


# ──────────── 2. Health Timeline ────────────


@router.get("/health-timeline")
def get_health_timeline(
    component: Optional[str] = Query(default=None),
    n: int = Query(default=100, ge=1, le=1000),
) -> Dict[str, Any]:
    """Health metrics 时序 (供 health AreaChart / drift LineChart 显示)

    数据源: health_metrics.level (ok/warn/critical) + age_seconds
    返回 level 数值化 (ok=0, warn=1, critical=2) 便于前端 line chart 渲染
    """
    from okx.web.backend.db import get_health_metrics_last_n
    rows = get_health_metrics_last_n(component=component, n=n)

    # 按 timestamp_utc ASC
    rows.sort(key=lambda r: r["timestamp_utc"])

    LEVEL_NUM = {"ok": 0, "warn": 1, "critical": 2}
    LEVEL_LABEL = ["ok", "warn", "critical"]

    series = [
        {
            "timestamp": r["timestamp_utc"],
            "component": r["component"],
            "level": r["level"],
            "level_num": LEVEL_NUM.get(r["level"], 0),
            "age_seconds": r.get("age_seconds"),
        }
        for r in rows
    ]

    _publish_chart_update("health-timeline", len(series))

    return {
        "ok": True,
        "chart": "health-timeline",
        "count": len(series),
        "series": series,
        "meta": {
            "component": component or "all",
            "n_requested": n,
            "level_legend": LEVEL_LABEL,
        },
    }


# ──────────── 3. Cron Success Rate ────────────


@router.get("/cron-success")
def get_cron_success(
    n: int = Query(default=100, ge=1, le=1000),
    cron_name: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Cron jobs success rate 分布 (供 win-rate BarChart 显示)

    数据源: cron_runs.status (ok/warn/error/skipped) per cron_name
    返回每 cron_name 的 status 计数 + 总体 success rate
    """
    from okx.web.backend.db import get_cron_runs_last_n
    rows = get_cron_runs_last_n(cron_name=cron_name, n=n)

    # 按 cron_name 分组 + 统计 status
    by_cron: Dict[str, Dict[str, int]] = {}
    for r in rows:
        name = r["cron_name"]
        status = r["status"]
        if name not in by_cron:
            by_cron[name] = {"ok": 0, "warn": 0, "error": 0, "skipped": 0}
        if status in by_cron[name]:
            by_cron[name][status] += 1

    # 算每个 cron 的 success_rate (ok / total)
    cron_stats = []
    for name, counts in sorted(by_cron.items()):
        total = sum(counts.values())
        ok = counts.get("ok", 0)
        success_rate = ok / total if total > 0 else 0.0
        cron_stats.append({
            "cron_name": name,
            "total": total,
            "ok": counts.get("ok", 0),
            "warn": counts.get("warn", 0),
            "error": counts.get("error", 0),
            "skipped": counts.get("skipped", 0),
            "success_rate": round(success_rate, 4),
        })

    # 总体 success rate
    total_all = sum(c["total"] for c in cron_stats)
    ok_all = sum(c["ok"] for c in cron_stats)
    overall_rate = ok_all / total_all if total_all > 0 else 0.0

    _publish_chart_update("cron-success", len(cron_stats))

    return {
        "ok": True,
        "chart": "cron-success",
        "count": len(cron_stats),
        "series": cron_stats,
        "meta": {
            "n_requested": n,
            "cron_name_filter": cron_name,
            "overall_success_rate": round(overall_rate, 4),
            "total_runs": total_all,
            "total_ok": ok_all,
        },
    }


# ──────────── 4. Chart Catalog (前端动态加载用) ────────────


@router.get("/catalog")
def get_chart_catalog() -> Dict[str, Any]:
    """可用 chart endpoint 列表 (供前端动态加载)

    前端可以基于这个 catalog 渲染 chart picker, 避免硬编码 endpoint URL
    """
    return {
        "ok": True,
        "charts": [
            {
                "id": "equity-curve",
                "endpoint": "/api/charts/equity-curve",
                "title": "Portfolio Equity Curve",
                "type": "line",
                "data_source": "portfolio_snapshots",
                "params": ["n", "source"],
                "default_n": 90,
            },
            {
                "id": "health-timeline",
                "endpoint": "/api/charts/health-timeline",
                "title": "Health Timeline",
                "type": "area",
                "data_source": "health_metrics",
                "params": ["n", "component"],
                "default_n": 100,
            },
            {
                "id": "cron-success",
                "endpoint": "/api/charts/cron-success",
                "title": "Cron Success Rate",
                "type": "bar",
                "data_source": "cron_runs",
                "params": ["n", "cron_name"],
                "default_n": 100,
            },
        ],
    }
