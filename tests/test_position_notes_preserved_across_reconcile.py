# -*- coding: utf-8 -*-
"""
P1-5 RED test: position notes 跨 reconcile 周期保留

设计意图:
- ETH 双仓 (long 1.09 + short 1.59) 是用户主动 hedge (Nixil 2026-08-08 14:05 确认)
- 想加 notes 字段记录"intentional hedge, user-confirmed 2026-08-08"
- Iron Rule #11 (Fix exposes reality): 必须先 RED 验证 reconcile 是否 strip notes
- 如果 RED (notes 被 strip) → 升到 B/C 方案
- 如果 GREEN (notes 保留) → 直接实施

Layer 1 (L1 invariant) · portfolio schema 设计层验证
"""

import sys
import tempfile
import json
from pathlib import Path
from typing import Any, Dict, List

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

import pytest


@pytest.fixture
def temp_portfolio_path(tmp_path):
    """隔离的临时 portfolio.json · 不污染 state/"""
    return tmp_path / "portfolio.json"


def _make_okx_position(inst_id: str, pos_side: str, pos: float, ct_val: float = 0.1) -> Dict[str, Any]:
    """构造模拟 OKX 仓位 dict (v5 API 字段名)"""
    return {
        "instId": inst_id,
        "posSide": pos_side,
        "pos": str(pos),
        "avgPx": "1900.0",
        "mgnMode": "cross",
        "ctVal": str(ct_val),
        "lever": "5",
    }


def _make_local_position(symbol: str, direction: str, size: float, order_id: str, **extra) -> Dict[str, Any]:
    """构造模拟本地 portfolio.json position dict"""
    pos = {
        "symbol": symbol,
        "direction": direction,
        "entry_price": 1900.0,
        "size": size,
        "leverage": 5,
        "margin": 100.0,
        "order_id": order_id,
        "opened_at": "2026-07-22T00:21:23",
        "strategy": "EXTERNAL_WEB_SYNC",
        "source": "okx_reconcile",
        "sl_price": 1894.3,
        "tp_price": 1908.55,
        "tp_stage": 0,
        "trigger_strategy": "EXTERNAL_WEB_SYNC",
        "adl": "1",
        "mark_px_at_sync": 1926.35,
        "mgn_mode": "cross",
        "ct_val": 0.1,
    }
    pos.update(extra)  # 允许加 notes 等额外字段
    return pos


# ──────────────────────────────────────────────────────────────────
# TIER 1 · RED test 1: matched path 保留未知字段
# ──────────────────────────────────────────────────────────────────

class TestReconcilePreservesPositionNotes:
    """核心假设: reconcile matched 路径用 survivors.append(lp) 直接保留原 dict"""

    def test_matched_position_preserves_notes_field(self, temp_portfolio_path):
        """matched (size 一致 + direction 一致) 应该完整保留本地 dict, 包括 notes"""
        from okx.code.portfolio import Portfolio

        # Setup: local 有 ETH long 1.09 + notes 字段
        initial = {
            "version": "1.0.0",
            "updated_at": "2026-08-08T06:10:05Z",
            "positions": [
                _make_local_position(
                    "ETHUSDTSWAP", "long", 1.09, "3763078669269106688",
                    notes="user_manual_hedge: long 1.09 + short 1.59 = 净空 0.5 ETH hedge, user-confirmed 2026-08-08",
                ),
            ],
            "daily_stats": {
                "date": "2026-08-08",
                "total_trades": 0,
                "loss_trades": 0,
                "consecutive_losses": 0,
                "total_pnl": 0.0,
                "total_fee": 0.0,
                "total_pnl_gross": 0.0,
                "last_loss_at": None,
                "emergency_stop_triggered": False,
            },
            "closed_positions": [],
        }
        temp_portfolio_path.write_text(json.dumps(initial, indent=2))

        portfolio = Portfolio(portfolio_path=str(temp_portfolio_path))
        okx_positions = [_make_okx_position("ETH-USDT-SWAP", "long", 1.09)]

        result = portfolio.reconcile_with_okx(okx_positions)

        # 验证 1: matched = 1 (本地 + OKX 一致)
        assert result["matched"], f"expected matched=1, got {result}"
        assert len(result["matched"]) == 1

        # 验证 2: positions 中 notes 字段被保留 (核心)
        positions = portfolio._data["positions"]
        assert len(positions) == 1, f"expected 1 position, got {len(positions)}"
        assert "notes" in positions[0], (
            f"❌ notes 字段被 strip 掉! positions[0] keys: {list(positions[0].keys())}"
        )
        assert "hedge" in positions[0]["notes"], (
            f"❌ notes 内容被破坏! got: {positions[0].get('notes')}"
        )

    def test_reload_preserves_notes_after_reconcile(self, temp_portfolio_path):
        """reconcile 后 reload portfolio (模拟新周期) · notes 应该从 JSON 读回"""
        from okx.code.portfolio import Portfolio

        initial = {
            "version": "1.0.0",
            "updated_at": "2026-08-08T06:10:05Z",
            "positions": [
                _make_local_position(
                    "ETHUSDTSWAP", "long", 1.09, "3763078669269106688",
                    notes="user_manual_hedge: long 1.09 + short 1.59",
                ),
                _make_local_position(
                    "ETHUSDTSWAP", "short", 1.59, "3791332102744735745",
                    notes="user_manual_hedge: long 1.09 + short 1.59",
                ),
            ],
            "daily_stats": {
                "date": "2026-08-08",
                "total_trades": 0,
                "loss_trades": 0,
                "consecutive_losses": 0,
                "total_pnl": 0.0,
                "total_fee": 0.0,
                "total_pnl_gross": 0.0,
                "last_loss_at": None,
                "emergency_stop_triggered": False,
            },
            "closed_positions": [],
        }
        temp_portfolio_path.write_text(json.dumps(initial, indent=2))

        # Cycle 1: reconcile
        portfolio1 = Portfolio(portfolio_path=str(temp_portfolio_path))
        okx_positions = [
            _make_okx_position("ETH-USDT-SWAP", "long", 1.09),
            _make_okx_position("ETH-USDT-SWAP", "short", 1.59),
        ]
        result1 = portfolio1.reconcile_with_okx(okx_positions)
        assert len(result1["matched"]) == 2

        # Cycle 2: reload (新实例, 模拟下一 cron 周期)
        portfolio2 = Portfolio(portfolio_path=str(temp_portfolio_path))
        positions = portfolio2._data["positions"]
        assert len(positions) == 2
        assert all("notes" in p for p in positions), (
            f"❌ reload 后 notes 丢失. positions keys: {[list(p.keys()) for p in positions]}"
        )


# ──────────────────────────────────────────────────────────────────
# TIER 2 · 验证 schema validator 接受 notes (optional field)
# ──────────────────────────────────────────────────────────────────

class TestPortfolioSchemaAcceptsNotes:
    """_validate_schema 应该接受 notes 作为 optional 字段"""

    def test_validate_schema_passes_with_notes_field(self, temp_portfolio_path):
        from okx.code.portfolio import Portfolio

        initial = {
            "version": "1.0.0",
            "updated_at": "2026-08-08T06:10:05Z",
            "positions": [
                _make_local_position(
                    "ETHUSDTSWAP", "long", 1.09, "3763078669269106688",
                    notes="test notes",
                ),
            ],
            "daily_stats": {
                "date": "2026-08-08",
                "total_trades": 0,
                "loss_trades": 0,
                "consecutive_losses": 0,
                "total_pnl": 0.0,
                "total_fee": 0.0,
                "total_pnl_gross": 0.0,
                "last_loss_at": None,
                "emergency_stop_triggered": False,
            },
            "closed_positions": [],
        }
        temp_portfolio_path.write_text(json.dumps(initial, indent=2))

        # 应该不抛 ValueError
        portfolio = Portfolio(portfolio_path=str(temp_portfolio_path))
        assert len(portfolio._data["positions"]) == 1