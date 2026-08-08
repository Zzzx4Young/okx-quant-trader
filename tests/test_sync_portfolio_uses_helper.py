# -*- coding: utf-8 -*-
"""
P1-2 RED test: sync_portfolio.py 必须复用 Portfolio.append_sync_history helper

Iron Rule #6/#7 (单逻辑两份 → drift 必然):
- 当前 scripts/sync_portfolio.py 独立内联写 sync_history.json
- 不调 Portfolio._append_sync_history helper
- 3 处 drift:
  1. Timestamp 格式 (UTC Z vs local TZ +08:00)
  2. Atomic write (helper 有, inline 无)
  3. JSONDecodeError recovery (helper 精细, inline 静默)

Refactor 目标: 抽 module-level append_sync_history(parent_dir, ...) helper
- Portfolio._append_sync_history → thin wrapper
- scripts/sync_portfolio.py → 直接调 helper
"""

import sys
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

import pytest


# ──────────────────────────────────────────────────────────────────
# TIER 1 · 核心 drift 验证
# ──────────────────────────────────────────────────────────────────

class TestSyncHistoryHelperUnified:
    """两个 code path (Portfolio class + sync_portfolio.py) 必须用同一 helper"""

    def test_helper_exists_at_module_level(self):
        """code/portfolio.py 必须导出 module-level append_sync_history helper"""
        from okx.code.portfolio import append_sync_history
        assert callable(append_sync_history), "module-level helper must exist"

    def test_portfolio_method_delegates_to_module_helper(self):
        """Portfolio._append_sync_history 必须是 thin wrapper · 行为一致"""
        from okx.code.portfolio import Portfolio, append_sync_history

        # 创建 temp portfolio
        with tempfile.TemporaryDirectory() as tmpdir:
            p_path = Path(tmpdir) / "portfolio.json"
            p_path.write_text(json.dumps({
                "version": "1.0.0", "updated_at": "2026-08-08T06:10:05Z",
                "positions": [], "daily_stats": {
                    "date": "2026-08-08", "total_trades": 0, "loss_trades": 0,
                    "consecutive_losses": 0, "total_pnl": 0.0, "total_fee": 0.0,
                    "total_pnl_gross": 0.0, "last_loss_at": None,
                    "emergency_stop_triggered": False,
                },
                "closed_positions": [],
            }))
            p = Portfolio(portfolio_path=str(p_path))
            # 调用 instance method, 应该 delegate 到 module helper
            p._append_sync_history(
                reason="test_reason",
                drift_detected=True,
                ghost_closed_count=2,
                new_synced_count=1,
                actions=["test_action_1", "test_action_2"],
            )
            # 验证 sync_history.json 写入 (helper 路径)
            sync_history = p_path.parent / "sync_history.json"
            assert sync_history.exists(), "helper must write sync_history.json"
            history = json.loads(sync_history.read_text())
            assert len(history) == 1
            assert history[0]["reason"] == "test_reason"
            assert history[0]["drift_detected"] is True

    def test_helper_uses_utc_timestamp_format(self):
        """module-level helper 必须用 UTC Z 格式 (避免与 cron path drift)"""
        from okx.code.portfolio import append_sync_history

        with tempfile.TemporaryDirectory() as tmpdir:
            append_sync_history(
                parent_dir=Path(tmpdir),
                reason="test_utc_format",
                drift_detected=True,
                ghost_closed_count=0,
                new_synced_count=0,
                actions=[],
            )
            sync_history = Path(tmpdir) / "sync_history.json"
            history = json.loads(sync_history.read_text())
            ts = history[0]["at"]
            # UTC Z 格式: "2026-08-08T06:10:05Z" · 不应含 "+08:00" 等 TZ 后缀
            assert ts.endswith("Z"), f"timestamp must be UTC Z format, got: {ts}"
            assert "+" not in ts or ts.endswith("Z"), f"no local TZ offset allowed, got: {ts}"

    def test_helper_uses_atomic_write(self):
        """module-level helper 必须 atomic write (Iron Rule #11 crash-safe)"""
        from okx.code.portfolio import append_sync_history

        with tempfile.TemporaryDirectory() as tmpdir:
            # 第一次写
            append_sync_history(
                parent_dir=Path(tmpdir),
                reason="first",
                drift_detected=True,
                ghost_closed_count=0,
                new_synced_count=0,
                actions=["first_action"],
            )
            # 第二次写 (验证 atomic: 应该 append, 不是覆盖)
            append_sync_history(
                parent_dir=Path(tmpdir),
                reason="second",
                drift_detected=True,
                ghost_closed_count=0,
                new_synced_count=0,
                actions=["second_action"],
            )
            sync_history = Path(tmpdir) / "sync_history.json"
            history = json.loads(sync_history.read_text())
            assert len(history) == 2, "atomic write should append, not overwrite"
            assert history[0]["reason"] == "first"
            assert history[1]["reason"] == "second"
            # 不应有残留 tmp file
            tmp_files = list(Path(tmpdir).glob(".sync_history.json.*.tmp"))
            assert len(tmp_files) == 0, f"atomic write leaked tmp files: {tmp_files}"

    def test_helper_skips_write_when_no_drift(self):
        """module-level helper 在 drift=False 时不写 (no spam design)"""
        from okx.code.portfolio import append_sync_history

        with tempfile.TemporaryDirectory() as tmpdir:
            append_sync_history(
                parent_dir=Path(tmpdir),
                reason="no_drift_test",
                drift_detected=False,  # ← no drift
                ghost_closed_count=0,
                new_synced_count=0,
                actions=[],
            )
            sync_history = Path(tmpdir) / "sync_history.json"
            assert not sync_history.exists(), "helper must skip write when drift=False"


# ──────────────────────────────────────────────────────────────────
# TIER 2 · sync_portfolio.py 必须用 helper (不是内联)
# ──────────────────────────────────────────────────────────────────

class TestSyncPortfolioScriptUsesHelper:
    """scripts/sync_portfolio.py 内联 write block 必须 delegate 到 helper"""

    def test_sync_portfolio_imports_helper(self):
        """scripts/sync_portfolio.py 必须 import append_sync_history"""
        from scripts import sync_portfolio  # noqa
        # 静态检查: 应该 import module-level helper
        src = Path(sync_portfolio.__file__).read_text(encoding="utf-8")
        assert "from okx.code.portfolio import append_sync_history" in src, (
            "scripts/sync_portfolio.py must import module-level helper "
            "(Iron Rule #6/#7 single source of truth)"
        )

    def test_sync_portfolio_has_no_inline_sync_history_write(self):
        """scripts/sync_portfolio.py 不能有内联 sync_history 写入 block"""
        from scripts import sync_portfolio
        src = Path(sync_portfolio.__file__).read_text(encoding="utf-8")
        # 反向断言: 不应再出现旧的 inline write pattern
        # (atomic write 之前是 plain `with open(sync_log, "w") as f`)
        assert 'with open(sync_log, "w") as f:' not in src, (
            "scripts/sync_portfolio.py must NOT have inline sync_history write. "
            "Refactor to delegate to append_sync_history helper."
        )