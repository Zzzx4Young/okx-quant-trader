# -*- coding: utf-8 -*-
"""
Integration test: 用真实 state/portfolio.json 验证 ct_val fix 后的 gate decisions

8-04 Step 4: 8-03 ship 的 risk gates 在 real data 上没有验证。
8-04 P0 fix (ct_val) 改变 notional 计算 10-100x · 必须用真实验证 gate behavior。

设计:
- 加载 state/portfolio.json (tracked file, 含真实仓位)
- 用 aggregate_exposure + check_all_gates 跑 5 个 gate
- Assert gate decisions 符合预期 (用真实 ct_val 计算)
- 文档化 threshold meaning 变化 (Nixil re-tune 用)

如果 portfolio.json 不存在 (e.g. CI), skip 测试 (不 break CI)。
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest


# Skip if portfolio.json doesn't exist (e.g. fresh CI checkout)
PORTFOLIO_PATH = Path(__file__).resolve().parent.parent / "state" / "portfolio.json"
pytestmark = pytest.mark.skipif(
    not PORTFOLIO_PATH.exists(),
    reason=f"Real portfolio.json not found at {PORTFOLIO_PATH} (CI environment?)",
)


def _load_real_portfolio() -> dict:
    """Load real state/portfolio.json."""
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)


def _make_position_dicts(portfolio: dict) -> list:
    """Convert portfolio.json::positions → aggregate_exposure 兼容的 dict 格式。

    portfolio.json fields: symbol, direction, size, entry_price, leverage, strategy, ct_val
    aggregate_exposure 期望相同 fields (含 ct_val · 8-04 P0 fix).
    """
    positions = []
    for p in portfolio.get("positions", []):
        positions.append({
            "symbol": p["symbol"],
            "direction": p["direction"],
            "size": p["size"],
            "entry_price": p["entry_price"],
            "leverage": p["leverage"],
            "strategy": p["strategy"],
            "ct_val": p.get("ct_val", 1.0),  # 8-04 P0: real notional 必须含 ct_val
            "opened_at": p.get("opened_at", ""),
        })
    return positions


class TestIntegrationRealPortfolioCtVal:
    """用 state/portfolio.json 真实仓位验证 ct_val fix + risk gate decisions."""

    def test_real_portfolio_has_3_valid_positions_with_ct_val(self):
        """3 EXTERNAL_WEB_SYNC positions, all have ct_val field (real SWAP data)."""
        portfolio = _load_real_portfolio()
        positions = portfolio.get("positions", [])

        assert len(positions) == 3, f"expected 3 positions, got {len(positions)}"
        for p in positions:
            assert "ct_val" in p, f"position missing ct_val: {p}"
            assert p["ct_val"] in (0.01, 0.1), f"unexpected ct_val {p['ct_val']} for {p['symbol']}"

    def test_real_portfolio_aggregate_real_notional(self):
        """ct_val fix: 真实 notional = $649.85 (fake was $19,149, 29.5x over-report).

        BTC: 0.22 × 63892.01 × 0.01 = $140.56
        ETH long: 1.09 × 1926.20 × 0.1 = $209.96
        ETH short: 1.59 × 1882.59 × 0.1 = $299.33
        Total: $649.85
        """
        from okx.code.risk import aggregate_exposure

        portfolio = _load_real_portfolio()
        positions = _make_position_dicts(portfolio)

        risk = aggregate_exposure(positions)

        assert risk.total_notional_usdt == pytest.approx(649.85, rel=1e-2), (
            f"real notional (with ct_val) 应为 ~$649.85，实际 {risk.total_notional_usdt}. "
            f"如果 ~$19,149 则 ct_val 被忽略 (L1 invariant 失败)"
        )
        # symbol concentration 用 real notional
        assert risk.symbol_concentration["BTCUSDTSWAP"] == pytest.approx(140.56, rel=1e-2)
        assert risk.symbol_concentration["ETHUSDTSWAP"] == pytest.approx(509.29, rel=1e-2)
        # long/short split
        long_notional = 140.56 + 209.96  # 350.52
        short_notional = 299.33
        assert risk.long_notional_usdt == pytest.approx(long_notional, rel=1e-2)
        assert risk.short_notional_usdt == pytest.approx(short_notional, rel=1e-2)
        # net direction: long - short = 51.19
        assert risk.net_direction_usdt == pytest.approx(51.19, rel=1e-2)
        # all positions are EXTERNAL_WEB_SYNC → 3 manual, 0 system
        assert risk.has_manual_position is True
        assert risk.has_system_position is False

    def test_real_portfolio_all_5_gates_pass_with_current_config(self):
        """Real portfolio + current risk config → 所有 5 个 gate 全部 pass (over-conservative).

        当前 state/config.json risk block:
          max_total_notional_usdt=200000 (real $649 << 200k → pass)
          max_net_directional_bias_pct=0.5 (real 0.06% << 50% → pass)
          max_single_position_pct=0.5 (real 0.37% << 50% → pass)
          max_leverage=10 (real 10x ≤ 10 → pass)
          max_system_positions_after_manual=1 (0 system → 1 capacity → pass)

        8-04 scholar evaluation note:
          全部 pass with huge margin = system 10-100x over-conservative.
          Nixil re-tune thresholds against real notional (e.g. $5k-10k instead of $200k).
        """
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        portfolio = _load_real_portfolio()
        positions = _make_position_dicts(portfolio)
        # 模拟当前 equity (~80k USDT, real portfolio)
        equity = 79925.11  # from liveness probe 22:00 cron

        # current state/config.json::risk block (production values)
        cfg = RiskGateConfig(
            max_total_notional_usdt=200000.0,
            max_net_directional_bias_pct=0.5,
            max_single_position_pct=0.5,
            max_leverage=10,
            max_system_positions_after_manual=1,
        )

        result = RiskGateChecker.check_all_gates(positions, equity=equity, cfg=cfg)

        # 全部 pass (over-conservative 但 pass)
        assert result.passed is True, (
            f"all 5 gates 应 pass (with huge margin)，实际 failed_gates={result.failed_gates}"
        )
        assert result.failed_gates == []
        # 文档化实际值 vs threshold (8-04 audit: 验证 over-conservative 程度)
        assert result.total_notional_usdt == pytest.approx(649.85, rel=1e-2)
        # bias = |51.19| / 79925 = 0.064% (vs 50% threshold)
        assert result.net_bias_pct == pytest.approx(0.000640, rel=1e-2)
        # max single = MAX(symbol_concentration) / equity = 509.29 / 79925 = 0.637%
        # (按 symbol 集中度: ETH long+short=$509.29 是最大 symbol 集中)
        assert result.max_single_position_pct == pytest.approx(0.00637, rel=1e-2)
        assert result.leverage_max == 10  # ETH short uses 10x
        # 3 manual + 0 system → system capacity = 1 (not 0 because gate 5 reserves slot)
        assert result.manual_position_count == 3
        assert result.system_position_count == 0
        assert result.system_position_capacity_remaining == 1

    def test_real_portfolio_tighter_threshold_still_passes(self):
        """Tighter threshold ($5000 notional) → 真实 portfolio 仍 pass (over-conservative 实证).

        这个测试文档化 8-04 fix 后 system 的 over-conservative 程度:
        - 当前 threshold $200k: 实际 0.32% utilization
        - 即便 threshold 砍到 $5k (40x tighter): 实际 13% utilization → 仍 pass

        如果 future portfolio 增长 (real notional > $5k), this test 会 fail → 提醒 Nixil 调阈值.
        """
        from okx.code.risk import RiskGateChecker, RiskGateConfig

        portfolio = _load_real_portfolio()
        positions = _make_position_dicts(portfolio)
        equity = 79925.11

        cfg = RiskGateConfig(
            max_total_notional_usdt=5000.0,  # 40x tighter than current $200k
            max_net_directional_bias_pct=0.5,
            max_single_position_pct=0.5,
            max_leverage=10,
            max_system_positions_after_manual=1,
        )

        result = RiskGateChecker.check_all_gates(positions, equity=equity, cfg=cfg)

        # 真实 $649.85 << $5000 → pass
        assert result.passed is True
        # documentation: utilization = 649.85 / 5000 = 13.0%
        assert result.total_notional_usdt / 5000.0 < 0.15
