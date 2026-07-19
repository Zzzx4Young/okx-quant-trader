#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_live_first_week.py —— v1.8.3+ Bitcoin-first-week-live policy regression tests

依据 (B 路径): Gate 7 ETH demo limit_fill_rate=0% (50% 总成交率) → live 第一周仅 BTC, ETH 延后 7 天。
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))


# ────────────────────── Portfolio 单元测试 ──────────────────────


class FakePortfolio:
    """最小的 Portfolio 替身, 只暴露 C 路径需要的 5 个方法。"""

    def __init__(self, first_live_tick_at=None):
        self._first_live_tick_at = first_live_tick_at

    def mark_first_live_tick(self):
        if self._first_live_tick_at is None:
            self._first_live_tick_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return True
        return False

    def is_live_first_week(self, duration_days: int = 7):
        if self._first_live_tick_at is None:
            return False
        try:
            started = datetime.fromisoformat(self._first_live_tick_at.replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - started
            return elapsed.total_seconds() < duration_days * 86400
        except (ValueError, AttributeError):
            return False

    # runner._pre_risk_check 用到的 3 个其他方法, 默认安全返回
    def is_meltdown(self, max_consec):
        return False

    def get_last_loss_timestamp(self):
        return None

    def position_count(self):
        return 0


def test_mark_first_live_tick_idempotent():
    """live 首次构造时设置, 后续构造不覆盖 (幂等)。"""
    p = FakePortfolio()
    assert p.mark_first_live_tick() is True
    first_at = p._first_live_tick_at
    assert first_at is not None

    # 第二次调用: 已存在, 不更新
    assert p.mark_first_live_tick() is False
    assert p._first_live_tick_at == first_at


def test_is_live_first_week_no_timestamp_returns_false():
    """demo 状态: first_live_tick_at 永远 None → is_live_first_week() 永远 False。"""
    p = FakePortfolio(first_live_tick_at=None)
    assert p.is_live_first_week() is False


def test_is_live_first_week_within_1_day_returns_true():
    """首次 live tick 在 1 天前 → is_live_first_week() True (< 7 天)。"""
    started = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    p = FakePortfolio(first_live_tick_at=started)
    assert p.is_live_first_week() is True
    assert p.is_live_first_week(duration_days=7) is True
    assert p.is_live_first_week(duration_days=0) is False  # duration_days=0 立即过期


def test_is_live_first_week_after_8_days_returns_false():
    """首次 live tick 在 8 天前 → is_live_first_week(7) False (已过首周)。"""
    started = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat().replace("+00:00", "Z")
    p = FakePortfolio(first_live_tick_at=started)
    assert p.is_live_first_week(duration_days=7) is False
    assert p.is_live_first_week(duration_days=30) is True  # 但 30 天窗口内仍 True


# ────────────────────── Runner._pre_risk_check 集成测试 ──────────────────────


class FakeConfig:
    """最小 Config 替身: 暴露 runner._pre_risk_check 用到的属性。"""

    def __init__(self, *, demo_mode, live_first_week_enabled=False, whitelist=None):
        self.demo_mode = demo_mode
        self._live_first_week_enabled = live_first_week_enabled
        self._data = {"trading": {"whitelist_symbols": whitelist or []}}
        # runner._pre_risk_check 用到的全部属性 (都以安全默认值)
        self.emergency_stop = False
        self.audit_max_consecutive_losses = 3
        self.audit_lockout_duration_minutes = 30
        self.max_concurrent_positions = 3
        self.whitelist_symbols = whitelist or []
        self.audit_enable_meltdown_lock = False
        self.max_loss_percent_per_trade = 1.0

    def get(self, key, default=None):
        if key == "trading.live_first_week_btc_only":
            return self._live_first_week_enabled
        parts = key.split(".")
        cur = self._data
        for p in parts:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return default
        return cur


def _make_runner(*, demo_mode, live_first_week_enabled, whitelist, first_tick_age_days=None):
    """构造 Runner 实例, mock 重 client/config/portfolio, 仅测试 _pre_risk_check。"""
    from code.runner import Runner

    runner = Runner.__new__(Runner)
    runner._config = FakeConfig(
        demo_mode=demo_mode,
        live_first_week_enabled=live_first_week_enabled,
        whitelist=whitelist,
    )
    # Portfolio 替身
    if first_tick_age_days is None:
        runner._portfolio = FakePortfolio(first_live_tick_at=None)
    elif first_tick_age_days == 0:
        runner._portfolio = FakePortfolio(first_live_tick_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    else:
        started = (datetime.now(timezone.utc) - timedelta(days=first_tick_age_days)).isoformat().replace("+00:00", "Z")
        runner._portfolio = FakePortfolio(first_live_tick_at=started)
    return runner


def test_runner_first_week_blocks_non_btc_in_live():
    """LIVE + first_week_enabled + 白名单含 ETH → _pre_risk_check 应返回 reject。"""
    runner = _make_runner(
        demo_mode=False,
        live_first_week_enabled=True,
        whitelist=["BTCUSDT", "ETHUSDT"],
        first_tick_age_days=0,
    )
    result = runner._pre_risk_check()
    assert result["passed"] is False
    assert result["stage"] == "live_first_week_btc_only"
    assert "ETH" in result["reason"]


def test_runner_first_week_passes_btc_only_whitelist():
    """LIVE + first_week_enabled + 白名单仅 BTC → _pre_risk_check 应通过。"""
    runner = _make_runner(
        demo_mode=False,
        live_first_week_enabled=True,
        whitelist=["BTCUSDT"],
        first_tick_age_days=0,
    )
    # 第一个 reject 可能是 emergency_stop 或 audit; 我们只关心 live_first_week 是否被阻断
    result = runner._pre_risk_check()
    # 不应是 live_first_week 阻断 (因为没有非 BTC)
    if result["passed"] is False:
        assert result.get("stage") != "live_first_week_btc_only", \
            f"误报: 纯 BTC 白名单不该被 live_first_week 阻断 → {result}"


def test_runner_first_week_disabled_in_demo():
    """DEMO + first_week_enabled + 白名单含 ETH → 不应触发 (demo 不限制)。"""
    runner = _make_runner(
        demo_mode=True,
        live_first_week_enabled=True,
        whitelist=["BTCUSDT", "ETHUSDT"],
        first_tick_age_days=0,  # 即使有 first_tick, demo 不该被拦
    )
    result = runner._pre_risk_check()
    if result["passed"] is False:
        assert result.get("stage") != "live_first_week_btc_only", \
            f"误报: demo 不该被 live_first_week 阻断 → {result}"


def test_runner_first_week_disabled_flag():
    """LIVE + first_week_enabled=false (开关未开) → 不限制。"""
    runner = _make_runner(
        demo_mode=False,
        live_first_week_enabled=False,
        whitelist=["BTCUSDT", "ETHUSDT"],
        first_tick_age_days=0,
    )
    result = runner._pre_risk_check()
    if result["passed"] is False:
        assert result.get("stage") != "live_first_week_btc_only", \
            f"误报: 开关未开不该被阻断 → {result}"


def test_runner_after_first_week_passes_eth():
    """LIVE + first_week_enabled=true + 已过首周 → ETH 应被允许。"""
    runner = _make_runner(
        demo_mode=False,
        live_first_week_enabled=True,
        whitelist=["BTCUSDT", "ETHUSDT"],
        first_tick_age_days=8,  # 已过首周
    )
    result = runner._pre_risk_check()
    if result["passed"] is False:
        assert result.get("stage") != "live_first_week_btc_only", \
            f"误报: 已过首周不该被阻断 → {result}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
