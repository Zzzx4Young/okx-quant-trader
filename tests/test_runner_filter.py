# -*- coding: utf-8 -*-
"""Tests for Runner._filter_skip_positions (A+C double-lock fix, 2026-07-15).

These tests guard against regression of the P0-4 fix that prevents
auto-closing of manually opened / externally synced positions.

Refactor rationale: 提取为静态方法便于单测，避免 mock 整个 Runner 实例。
"""

import sys
from pathlib import Path

# 让 pytest 找到 okx 包（无需 conftest）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from okx.code.runner import Runner


# ────────────── C 防线：strategy 白名单 ──────────────


class TestFilterSkipPositionsStrategyWhitelist:
    """C 防线：strategy 名命中白名单 → HOLD_MANUAL"""

    def test_manual_no_auto_close_is_skipped(self):
        positions = [
            {"symbol": "BTCUSDTSWAP", "strategy": "MANUAL_NO_AUTO_CLOSE",
             "sl_price": 64800.0, "tp_price": 64500.0},
        ]
        kept, skipped = Runner._filter_skip_positions(positions)
        assert len(kept) == 0
        assert len(skipped) == 1
        assert skipped[0]["action"] == "HOLD_MANUAL"
        assert "MANUAL_NO_AUTO_CLOSE" in skipped[0]["reason"]
        assert skipped[0]["symbol"] == "BTCUSDTSWAP"

    def test_external_web_sync_is_skipped_for_backward_compat(self):
        positions = [
            {"symbol": "ETHUSDTSWAP", "strategy": "EXTERNAL_WEB_SYNC",
             "sl_price": 1810.0, "tp_price": 1796.0},
        ]
        kept, skipped = Runner._filter_skip_positions(positions)
        assert len(kept) == 0
        assert len(skipped) == 1
        assert skipped[0]["action"] == "HOLD_MANUAL"

    def test_strategy_name_alias_also_works(self):
        # 部分代码路径可能用 strategy_name 字段
        positions = [
            {"symbol": "BTCUSDTSWAP", "strategy_name": "MANUAL_NO_AUTO_CLOSE",
             "sl_price": 64000.0, "tp_price": 66000.0},
        ]
        kept, skipped = Runner._filter_skip_positions(positions)
        assert len(kept) == 0
        assert len(skipped) == 1


# ────────────── A 防线：哨兵值拦截 ──────────────


class TestFilterSkipPositionsSentinel:
    """A 防线：sl_price=0 + tp_price=0 哨兵值 → HOLD_NO_PROTECTION"""

    def test_both_sentinels_zero_is_skipped(self):
        positions = [
            {"symbol": "BTCUSDTSWAP", "strategy": "A_EMA20_BREAKOUT",
             "sl_price": 0.0, "tp_price": 0.0},
        ]
        kept, skipped = Runner._filter_skip_positions(positions)
        assert len(kept) == 0
        assert len(skipped) == 1
        assert skipped[0]["action"] == "HOLD_NO_PROTECTION"
        assert "哨兵" in skipped[0]["reason"]

    def test_only_sl_zero_but_tp_valid_is_kept(self):
        # Nixil spec：哨兵 AND 触发（sl<=0 AND tp<=0 都满足才跳过）
        positions = [
            {"symbol": "BTCUSDTSWAP", "strategy": "A_EMA20_BREAKOUT",
             "sl_price": 0.0, "tp_price": 66000.0},
        ]
        kept, skipped = Runner._filter_skip_positions(positions)
        # sl=0 但 tp>0 → 条件不满足 → 保留（让后续 SL 检查自己处理）
        assert len(kept) == 1
        assert len(skipped) == 0

    def test_string_sl_tp_parsed_safely(self):
        # OKX API 偶发返回字符串数字
        positions = [
            {"symbol": "BTCUSDTSWAP", "strategy": "A_EMA20_BREAKOUT",
             "sl_price": "64000.0", "tp_price": "66000.0"},
        ]
        kept, skipped = Runner._filter_skip_positions(positions)
        assert len(kept) == 1
        assert len(skipped) == 0

    def test_invalid_string_sl_falls_back_to_zero(self):
        # sl_price="invalid" → 解析失败 → 当作 0.0
        positions = [
            {"symbol": "BTCUSDTSWAP", "strategy": "A_EMA20_BREAKOUT",
             "sl_price": "invalid", "tp_price": "66000.0"},
        ]
        kept, skipped = Runner._filter_skip_positions(positions)
        # sl=0 (fallback), tp>0 → 条件 sl<=0 AND tp<=0 不满足 → 保留
        assert len(kept) == 1
        assert len(skipped) == 0


# ────────────── 正常路径 ──────────────


class TestFilterSkipPositionsNormalFlow:
    """正常路径：合法 strategy + 合法 SL/TP → 保留"""

    def test_normal_strategy_kept(self):
        positions = [
            {"symbol": "BTCUSDTSWAP", "strategy": "A_EMA20_BREAKOUT",
             "sl_price": 64000.0, "tp_price": 66000.0},
        ]
        kept, skipped = Runner._filter_skip_positions(positions)
        assert len(kept) == 1
        assert len(skipped) == 0
        assert kept[0]["strategy"] == "A_EMA20_BREAKOUT"

    def test_all_four_strategies_kept(self):
        for s in ["A_EMA20_BREAKOUT", "B_BB_RSI_REVERSION",
                  "C_VOLATILITY_BREAKOUT", "D_FUNDING_RATE_REVERSAL"]:
            positions = [
                {"symbol": "BTCUSDTSWAP", "strategy": s,
                 "sl_price": 64000.0, "tp_price": 66000.0},
            ]
            kept, skipped = Runner._filter_skip_positions(positions)
            assert len(kept) == 1, f"Strategy {s} should be kept"
            assert len(skipped) == 0

    def test_missing_strategy_with_valid_prices_kept(self):
        # 没有 strategy 字段 + 有正常价格 → 视为正常策略
        positions = [
            {"symbol": "BTCUSDTSWAP", "sl_price": 64000.0, "tp_price": 66000.0},
        ]
        kept, skipped = Runner._filter_skip_positions(positions)
        assert len(kept) == 1
        assert len(skipped) == 0


# ────────────── 混合场景 ──────────────


class TestFilterSkipPositionsMixed:
    """多条仓位正确分区"""

    def test_three_positions_two_skipped_one_kept(self):
        positions = [
            {"symbol": "BTCUSDTSWAP", "strategy": "MANUAL_NO_AUTO_CLOSE",
             "sl_price": 64800.0, "tp_price": 64500.0},
            {"symbol": "ETHUSDTSWAP", "strategy": "A_EMA20_BREAKOUT",
             "sl_price": 1800.0, "tp_price": 1900.0},
            {"symbol": "SOLUSDTSWAP", "strategy": "B_BB_RSI_REVERSION",
             "sl_price": 0.0, "tp_price": 0.0},
        ]
        kept, skipped = Runner._filter_skip_positions(positions)
        assert len(kept) == 1
        assert kept[0]["symbol"] == "ETHUSDTSWAP"
        assert len(skipped) == 2
        skipped_actions = {s["action"] for s in skipped}
        assert "HOLD_MANUAL" in skipped_actions
        assert "HOLD_NO_PROTECTION" in skipped_actions

    def test_empty_input_returns_empty(self):
        kept, skipped = Runner._filter_skip_positions([])
        assert kept == []
        assert skipped == []

    def test_skipped_action_has_required_keys(self):
        # 防御：skipped dict 结构稳定，便于日志/dashboard 消费
        positions = [
            {"symbol": "BTCUSDTSWAP", "strategy": "MANUAL_NO_AUTO_CLOSE",
             "sl_price": 64800.0, "tp_price": 64500.0},
        ]
        _, skipped = Runner._filter_skip_positions(positions)
        assert len(skipped) == 1
        action = skipped[0]
        assert "symbol" in action
        assert "action" in action
        assert "reason" in action
        assert action["action"] in {"HOLD_MANUAL", "HOLD_NO_PROTECTION"}