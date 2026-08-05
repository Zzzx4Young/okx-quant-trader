# -*- coding: utf-8 -*-
"""
Portfolio.reconcile_with_okx 写 sync_history 行为测试 (2026-08-05)

════════════════════════════════════════════════════════════════════
目的: 钉住 reconcile_with_okx 在 drift_detected=true 时必须写
      sync_history.json，防止 cron 路径 silent log loss。

Bug 背景:
  scripts/sync_portfolio.py (manual sync) 写 sync_history.json
  code/portfolio.py::reconcile_with_okx (cron auto) 不写 sync_history.json

  → 当 cron reconcile 发现 drift (OKX 多仓 / 本地少仓 / size 不一致),
     portfolio.json 被修改但 sync_history.json 不会被记 → silent log loss
  → 7-22 ETH long + 7-31 ETH short 的引入完全没 trace

设计决策:
  - sync_history 路径 = portfolio_path.parent / "sync_history.json"
    (沿用 sync_portfolio.py 的约定)
  - reason 字段 = "cron_reconcile" (区别于 manual sync 的 args.reason)
  - drift=false 不写 (防 sync_history spam — 每次 tick 都匹配是常态)
  - drift=true 必须写 (audit 必备 — drift 必须可追溯)
════════════════════════════════════════════════════════════════════
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from okx.code.portfolio import Portfolio


# ────────────── Fixtures ──────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    from okx.code.config import Config
    Config._instance = None
    yield
    Config._instance = None


@pytest.fixture
def fresh_portfolio(tmp_path):
    """新建一个 tmp portfolio (空仓), 配套 sync_history.json 应在同目录"""
    pf_path = tmp_path / "portfolio.json"
    pf_path.write_text(json.dumps({
        "version": "1.0.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "positions": [],
        "closed_positions": [],
        "daily_stats": {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "total_trades": 0,
            "loss_trades": 0,
            "consecutive_losses": 0,
            "total_pnl": 0.0,
            "total_fee": 0.0,
            "total_pnl_gross": 0.0,
            "last_loss_at": None,
            "emergency_stop_triggered": False,
        },
    }))
    return Portfolio(str(pf_path))


def _okx_position(
    instId: str = "BTC-USDT-SWAP",
    posSide: str = "long",
    pos: str = "0.1",
    avgPx: str = "50000",
    markPx: str = "50100",
    lever: str = "3",
    cTime: str = "1700000000000",
    adl: str = "",
    mgnMode: str = "isolated",
) -> dict:
    """构造一个 OKX V5 API positions 格式的 dict (测试 fixture)"""
    return {
        "instId": instId,
        "posSide": posSide,
        "pos": pos,
        "avgPx": avgPx,
        "markPx": markPx,
        "lever": lever,
        "cTime": cTime,
        "uTime": cTime,
        "adl": adl,
        "posId": f"pos_{instId}_{posSide}",
        "mgnMode": mgnMode,
        "ccy": "USDT",
    }


# ────────────── Tests ──────────────

class TestReconcileWritesSyncHistory:
    """
    reconcile_with_okx 在 drift_detected=true 时必须写 sync_history.json

    Bug 防御: cron 周期 reconcile 静默修改 portfolio.json 但不写 sync_history
    影响: drift 无法审计, 7-22 ETH long / 7-31 ETH short 引入无 trace
    """

    def test_reconcile_with_new_synced_writes_sync_history(self, fresh_portfolio, tmp_path):
        """drift=true (new_synced) 必须写 sync_history.json"""
        # 本地空仓, OKX 上有 1 仓 → drift=true (new_synced=1)
        okx_positions = [_okx_position()]
        ct_val_by_inst = {"BTC-USDT-SWAP": 0.01}

        result = fresh_portfolio.reconcile_with_okx(
            okx_positions, ct_val_by_inst=ct_val_by_inst
        )

        # 1. Verify drift detected
        assert result["drift_detected"] is True, (
            f"预期 drift_detected=true (new_synced), got {result}"
        )
        assert len(result["new_synced"]) == 1

        # 2. Verify sync_history.json 在 portfolio.json 同目录
        sync_history_path = tmp_path / "sync_history.json"
        assert sync_history_path.exists(), (
            f"❌ reconcile_with_okx 在 drift=true 时未写 sync_history.json "
            f"(路径: {sync_history_path}). 这是 silent log drift bug."
        )

        # 3. Verify sync_history 内容
        history = json.loads(sync_history_path.read_text())
        assert isinstance(history, list), "sync_history 必须是 list"
        assert len(history) == 1, f"预期 1 entry, got {len(history)}"
        entry = history[0]
        assert entry["drift_detected"] is True
        assert entry["new_synced_count"] == 1
        assert entry["ghost_closed_count"] == 0
        assert isinstance(entry["actions"], list)
        assert any("new" in a for a in entry["actions"]), (
            f"actions 应记录 new → portfolio: {entry['actions']}"
        )

    def test_reconcile_with_no_drift_does_not_write_sync_history(self, fresh_portfolio, tmp_path):
        """drift=false (matched) 不写 sync_history.json (防 spam)

        设计意图: matched 是常态 (每次 cron tick 都是 matched=3), 不应该每次写 log
        只有 drift=true 才写 (audit 必备)
        """
        # 本地先加 1 仓, OKX 同样 1 仓 → matched=1, drift=false
        fresh_portfolio._data["positions"].append({
            "symbol": "BTCUSDTSWAP",
            "direction": "long",
            "entry_price": 50000.0,
            "size": 0.1,
            "leverage": 3,
            "margin": 166.67,
            "order_id": "pos_BTC-USDT-SWAP_long",
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "strategy": "EXTERNAL_WEB_SYNC",
            "source": "okx_reconcile",
            "sl_price": 49850.0,
            "tp_price": 50225.0,
            "tp_stage": 0,
            "trigger_strategy": "EXTERNAL_WEB_SYNC",
            "adl": "",
            "mark_px_at_sync": 50000.0,
            "mgn_mode": "isolated",
            "ct_val": 0.01,
        })
        fresh_portfolio._save()

        okx_positions = [_okx_position()]  # 同样的仓
        result = fresh_portfolio.reconcile_with_okx(okx_positions)

        assert result["drift_detected"] is False
        assert len(result["matched"]) == 1

        sync_history_path = tmp_path / "sync_history.json"
        assert not sync_history_path.exists(), (
            f"drift=false 时不应写 sync_history (防 spam), "
            f"但文件已存在: {sync_history_path}"
        )

    def test_sync_history_entry_has_required_audit_fields(self, fresh_portfolio, tmp_path):
        """sync_history entry 必须含审计必需字段"""
        okx_positions = [_okx_position()]
        fresh_portfolio.reconcile_with_okx(
            okx_positions, ct_val_by_inst={"BTC-USDT-SWAP": 0.01}
        )

        sync_history_path = tmp_path / "sync_history.json"
        assert sync_history_path.exists()
        history = json.loads(sync_history_path.read_text())
        entry = history[0]

        # 必须字段 (审计 trail 必需)
        required = {"at", "reason", "drift_detected", "ghost_closed_count",
                    "new_synced_count", "actions"}
        missing = required - set(entry.keys())
        assert not missing, f"sync_history entry 缺字段: {missing}"

        # reason 应标明是 cron 路径 (区别于 manual sync)
        assert entry["reason"] == "cron_reconcile", (
            f"reason 应是 'cron_reconcile' 标明 cron 路径, got '{entry['reason']}'"
        )

        # at 应是合法 ISO timestamp
        assert "T" in entry["at"], f"at 字段应是 ISO timestamp: {entry['at']}"

    def test_sync_history_accumulates_across_multiple_drifts(self, fresh_portfolio, tmp_path):
        """多次 drift 必须累积 (防覆盖)

        Bug 防御: 如果 sync_history 写成"w mode" 而非 append, 多次 drift 会被覆盖
        """
        # 第 1 次: new_synced BTC
        fresh_portfolio.reconcile_with_okx(
            [_okx_position(instId="BTC-USDT-SWAP", posSide="long", pos="0.1", avgPx="50000")],
            ct_val_by_inst={"BTC-USDT-SWAP": 0.01},
        )

        # 第 2 次: 加 ETH 仓 (本地 BTC 已 matched, ETH 是 new_synced)
        okx_with_eth = [
            _okx_position(instId="BTC-USDT-SWAP", posSide="long", pos="0.1", avgPx="50000"),
            _okx_position(instId="ETH-USDT-SWAP", posSide="short", pos="1.0", avgPx="2000", markPx="2010", cTime="1700000001000"),
        ]
        fresh_portfolio.reconcile_with_okx(
            okx_with_eth,
            ct_val_by_inst={"BTC-USDT-SWAP": 0.01, "ETH-USDT-SWAP": 0.1},
        )

        sync_history_path = tmp_path / "sync_history.json"
        assert sync_history_path.exists()
        history = json.loads(sync_history_path.read_text())

        assert len(history) == 2, (
            f"多次 drift 必须累积 entry, 预期 2 entries, got {len(history)}. "
            f"如果是 1 → sync_history 被覆盖 (silent bug)"
        )
        # 第 2 次 entry 应记录 ETH new_synced
        assert history[1]["new_synced_count"] == 1
        assert any("ETH" in a for a in history[1]["actions"])