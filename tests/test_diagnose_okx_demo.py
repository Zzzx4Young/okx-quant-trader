#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diagnose_okx_demo.py 单测（gate 7 release test）

覆盖：
  - stats 计算正确性（market / limit 分组 + overall）
  - release gate 判定（3 条红线）
  - percentile 函数边界
  - mock records 形状合规
  - persist_experiment 4 件套齐全
"""

import json
import sys
import time
from pathlib import Path

import pytest

# 直接 import 模块（避开 okx.code 包 import 链）
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import diagnose_okx_demo as diag


# ──────────── Fixtures ────────────


@pytest.fixture
def mock_records():
    """固定 mock 记录（含已知分布）"""
    return diag._mock_records(100)


@pytest.fixture
def tmp_exp_dir(tmp_path):
    """临时实验目录"""
    return tmp_path


# ──────────── stats / gate 测试 ────────────


def test_compute_stats_groups_by_type(mock_records):
    """stats 应按 ord_type 分组"""
    stats = diag.compute_stats(mock_records)

    assert "by_type" in stats
    assert "market" in stats["by_type"]
    assert "limit" in stats["by_type"]
    assert stats["overall"]["total_orders"] == 100
    assert stats["overall"]["filled"] == 100
    assert stats["by_type"]["market"]["count"] == 50
    assert stats["by_type"]["limit"]["count"] == 50


def test_compute_stats_market_slip_distribution(mock_records):
    """市价单 avg abs slip 应在 [3, 8] bps（mock 范围）"""
    stats = diag.compute_stats(mock_records)
    market = stats["by_type"]["market"]

    assert 3.0 <= market["avg_abs_slip_bps"] <= 8.0
    assert market["max_abs_slip_bps"] <= 8.0
    assert market["p95_abs_slip_bps"] >= market["median_abs_slip_bps"]


def test_compute_stats_limit_slip_zero(mock_records):
    """限价单绝对滑点应为 0（成交价=挂单价）"""
    stats = diag.compute_stats(mock_records)
    limit = stats["by_type"]["limit"]

    assert limit["avg_abs_slip_bps"] == 0.0
    assert limit["median_abs_slip_bps"] == 0.0


def test_check_release_gates_pass_with_good_slippage(mock_records):
    """v1.8.3+ B 路径 split 化: 3 条 active gate 在 mock 数据下应全过
    (avg_taker_slip_le_8bps + p95_taker_slip_le_15bps + market_fill_rate_ge_95pct)
    _legacy_fill_rate_ge_90pct 保留为 legacy 记录，不计入主判定"""
    stats = diag.compute_stats(mock_records)
    gates = diag.check_release_gates(stats)

    assert gates["avg_taker_slip_le_8bps"] is True
    assert gates["p95_taker_slip_le_15bps"] is True
    assert gates["market_fill_rate_ge_95pct"] is True
    # main gates (excluding legacy) all true
    main_gates = {k: v for k, v in gates.items() if not k.startswith('_')}
    assert all(main_gates.values()), f"Some main gates failed: {main_gates}"


def test_check_release_gates_fail_when_slippage_too_high():
    """avg slip > 8bps → 红线 fail"""
    records = []
    for i in range(50):
        records.append(diag.SlipRecord(
            idx=i, ord_type="market", side="buy",
            request_px=100.0, exec_px=100.5,  # 50bps 滑点！
            fill_ts_ms=int(time.time() * 1000),
            request_ts_ms=int(time.time() * 1000),
            latency_ms=100,
            abs_slip_bps=50.0,
            signed_slip_bps=50.0,
            order_id=f"fail-{i}",
        ))
    stats = diag.compute_stats(records)
    gates = diag.check_release_gates(stats)

    assert gates["avg_taker_slip_le_8bps"] is False
    assert gates["p95_taker_slip_le_15bps"] is False


def test_check_release_gates_fail_when_fill_rate_low():
    """v1.8.3+ B 路径 split 化: market_fill_rate < 95% → 新 gate fail
    (原 fill_rate_ge_90pct 在 demo 上物理不可达，已废弃为 _legacy)"""
    records = []
    for i in range(100):
        # 只有 50% 成交 (market_fill_rate = 0.5 < 0.95)
        if i < 50:
            records.append(diag.SlipRecord(
                idx=i, ord_type="market", side="buy",
                request_px=100.0, exec_px=100.05,
                fill_ts_ms=int(time.time() * 1000),
                request_ts_ms=int(time.time() * 1000),
                latency_ms=100, abs_slip_bps=5.0,
                signed_slip_bps=5.0, order_id=f"ok-{i}",
            ))
        else:
            records.append(diag.SlipRecord(
                idx=i, ord_type="market", side="buy",
                request_px=100.0, exec_px=None, fill_ts_ms=None,
                request_ts_ms=int(time.time() * 1000),
                latency_ms=None, abs_slip_bps=None,
                signed_slip_bps=None, order_id=None,
                error="rate limited",
            ))
    stats = diag.compute_stats(records)
    gates = diag.check_release_gates(stats)

    # v1.8.3+ 改判 market_fill_rate
    assert gates["market_fill_rate_ge_95pct"] is False
    # legacy 保留返回值
    assert "_legacy_fill_rate_ge_90pct" in gates


# ──────────── percentile 测试 ────────────


def test_percentile_basic():
    assert diag._percentile([1, 2, 3, 4, 5], 50) == 3
    assert diag._percentile([1, 2, 3, 4, 5], 0) == 1
    assert diag._percentile([1, 2, 3, 4, 5], 100) == 5
    assert diag._percentile([1, 2, 3, 4, 5], 95) == 5  # idx=4


def test_percentile_empty():
    assert diag._percentile([], 95) is None


def test_percentile_single():
    assert diag._percentile([42.0], 95) == 42.0


# ──────────── persist 测试 ────────────


def test_persist_experiment_creates_4_files(tmp_exp_dir, mock_records):
    """持久化应产出 result.md / records.json / meta.json / scan.py 4 件套"""
    stats = diag.compute_stats(mock_records)
    gates = diag.check_release_gates(stats)

    exp_dir = diag.persist_experiment(
        inst_id="BTC-USDT-SWAP",
        records=mock_records,
        stats=stats,
        gates=gates,
        name="unit-test",
        out_root=str(tmp_exp_dir),
    )

    assert exp_dir.exists()
    assert (exp_dir / "result.md").exists()
    assert (exp_dir / "records.json").exists()
    assert (exp_dir / "meta.json").exists()
    assert (exp_dir / "scan.py").exists()


def test_persist_meta_has_gates(tmp_exp_dir, mock_records):
    """meta.json 应包含 gates 判定结果"""
    stats = diag.compute_stats(mock_records)
    gates = diag.check_release_gates(stats)

    exp_dir = diag.persist_experiment(
        inst_id="BTC-USDT-SWAP",
        records=mock_records,
        stats=stats,
        gates=gates,
        name="unit-meta-test",
        out_root=str(tmp_exp_dir),
    )

    meta = json.loads((exp_dir / "meta.json").read_text())
    assert "gates" in meta
    assert "gates_passed" in meta
    assert meta["gates_passed"] is True
    assert meta["total_records"] == 100


def test_persist_records_json_valid(tmp_exp_dir, mock_records):
    """records.json 应是合法 JSON 数组"""
    stats = diag.compute_stats(mock_records)
    gates = diag.check_release_gates(stats)

    exp_dir = diag.persist_experiment(
        inst_id="BTC-USDT-SWAP",
        records=mock_records,
        stats=stats,
        gates=gates,
        name="unit-records-test",
        out_root=str(tmp_exp_dir),
    )

    recs = json.loads((exp_dir / "records.json").read_text())
    assert isinstance(recs, list)
    assert len(recs) == 100
    assert "ord_type" in recs[0]
    assert "exec_px" in recs[0]
    assert "abs_slip_bps" in recs[0]


# ──────────── format_report 测试 ────────────


def test_format_report_contains_all_sections(mock_records):
    """报告应包含 release gate + 按类型统计 + 失败明细（如有）"""
    stats = diag.compute_stats(mock_records)
    gates = diag.check_release_gates(stats)

    report = diag.format_report("BTC-USDT-SWAP", mock_records, stats, gates)

    assert "# Phase 4 Gate 7" in report
    assert "Release Gate" in report
    assert "市价 (Taker)" in report
    assert "限价 (Maker)" in report
    assert "BTC-USDT-SWAP" in report


def test_format_report_shows_failures():
    """失败明细应在报告中显示"""
    records = []
    # 50 笔正常 + 5 笔失败
    records.extend(diag._mock_records(50))
    for i in range(5):
        records.append(diag.SlipRecord(
            idx=i, ord_type="market", side="buy",
            request_px=100.0, exec_px=None, fill_ts_ms=None,
            request_ts_ms=int(time.time() * 1000),
            latency_ms=None, abs_slip_bps=None,
            signed_slip_bps=None, order_id=None,
            error="rate limited",
        ))

    stats = diag.compute_stats(records)
    gates = diag.check_release_gates(stats)
    report = diag.format_report("BTC-USDT-SWAP", records, stats, gates)

    assert "失败明细" in report
    assert "rate limited" in report


# ──────────── jitter 测试 ────────────


def test_jitter_within_bounds():
    """jitter 间隔应在 ±50% 范围内"""
    for _ in range(100):
        result = diag._jitter(2.0)
        assert 1.0 <= result <= 3.0  # 2.0 ± 50%


# ──────────── is_filled / is_taker 属性测试 ────────────


def test_sliprecord_is_filled():
    r = diag.SlipRecord(
        idx=0, ord_type="market", side="buy",
        request_px=100.0, exec_px=100.1, fill_ts_ms=123,
        request_ts_ms=100, latency_ms=23,
        abs_slip_bps=10.0, signed_slip_bps=10.0,
        order_id="x",
    )
    assert r.is_filled is True
    assert r.is_taker is True

    r2 = diag.SlipRecord(
        idx=0, ord_type="limit", side="buy",
        request_px=100.0, exec_px=None, fill_ts_ms=None,
        request_ts_ms=100, latency_ms=None,
        abs_slip_bps=None, signed_slip_bps=None,
        order_id=None,
    )
    assert r2.is_filled is False
    assert r2.is_taker is False