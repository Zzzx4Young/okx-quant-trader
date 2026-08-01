# -*- coding: utf-8 -*-
"""
Layer 4 · Live Shadow Test (Production Shadow Runner Architecture)

════════════════════════════════════════════════════════════════════
目的: 在生产环境部署 "影子 runner", 与 live runner 并行运行,
      不下真单但记录应该开的仓位。每天对比两个 runner 的状态,
      drift > 阈值则告警。

为什么需要:
  - Backtest + demo 都不能保证 live 行为 (网络延迟 / 滑点 spike / API 异常)
  - Shadow 是唯一能捕获 "代码改了但没在 demo 测到" 的 ground truth
  - 一旦 shadow 与 live drift → 信号逻辑或风险控制有 bug

Layer 4 测试覆盖 (本文件):
  S-1: 信号可重现性 (相同输入 → 相同 Signal)
  S-2: 风险参数可重现性 (相同 portfolio → 相同 risk decision)
  S-3: Drift detection 算法 (生产 vs shadow 状态对比)
  S-4: Shadow 部署 contract (state 隔离 + 不污染)

完整生产部署蓝图: okx/docs/SHADOW_DEPLOYMENT.md (待写)
════════════════════════════════════════════════════════════════════
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from okx.code.config import Config
from okx.code.portfolio import Portfolio
from okx.code.risk import RiskCalculator
from okx.code.signal import Signal, SignalEngine


# ──────────── Fixtures ────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    Config._instance = None
    yield
    Config._instance = None


@pytest.fixture
def cfg(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    test_cfg = state_dir / "config.json"
    test_cfg.write_text(json.dumps({
        "version": "test",
        "trading": {
            "default_leverage_main": 3,
            "max_leverage_limit": 3,
            "max_concurrent_positions": 3,
            "margin_mode": "isolated",
            "demo_mode": True,
        },
        "risk": {
            "max_loss_percent_per_trade": 1.0,
            "min_reward_risk_ratio": 1.5,
            "daily_max_loss_trades": 3,
            "sl_buffer_percent": 0.5,
            "atr_multiplier": 2.0,
            "kelly": {
                "min_trades_for_kelly": 30,
                "fractional_kelly": 0.25,
            },
        },
        "leverage_matrix": {
            "BTC": {"min_leverage": 3, "max_leverage": 3, "hard_ceiling": 3,
                     "atr_low": 80, "atr_high": 250, "category": "mainstream"},
        },
        "audit": {
            "max_consecutive_losses": 3,
            "lockout_duration_minutes": 30,
            "fee_to_profit_ratio_threshold": 0.3,
        },
    }))
    return Config(str(test_cfg))


# ──────────── S-1: 信号可重现性 ────────────

class TestSignalReproducibility:
    """
    相同输入 (K 线 + portfolio 状态) 必须产生相同的 Signal。
    如果不同 → 策略有非确定性 bug (random / time-based / 状态泄漏)。
    """

    def test_same_input_produces_same_signal(self, cfg):
        """构造相同 K 线 + portfolio, 跑 2 次 SignalEngine → 必须相同"""
        mock_market = MagicMock()
        mock_market.get_candles = MagicMock(return_value=[
            ["ts", "50000", "50100", "49900", "50050", "100", "100", "100"],
        ])

        engine1 = SignalEngine(market_api=mock_market, config=cfg)
        engine2 = SignalEngine(market_api=mock_market, config=cfg)

        # 同样输入
        positions = []
        signals1 = engine1.check_all_symbols(positions)
        signals2 = engine2.check_all_symbols(positions)

        # 必须完全相同 (或都 None, 或都一致)
        assert len(signals1) == len(signals2), (
            f"signal count 不一致: {len(signals1)} vs {len(signals2)}. "
            f"说明 SignalEngine 有非确定性 bug."
        )
        for s1, s2 in zip(signals1, signals2):
            assert s1.symbol == s2.symbol, f"symbol 漂移: {s1.symbol} vs {s2.symbol}"
            assert s1.direction == s2.direction
            assert s1.leverage == s2.leverage
            assert abs(s1.entry_price - s2.entry_price) < 1e-8
            assert abs(s1.sl_price - s2.sl_price) < 1e-8
            assert abs(s1.tp_price - s2.tp_price) < 1e-8


# ──────────── S-2: 风险决策可重现性 ────────────

class TestRiskDecisionReproducibility:
    """相同 portfolio + 信号 → 相同 Kelly sizing decision"""

    def test_same_inputs_produce_same_kelly_decision(self, cfg):
        from types import SimpleNamespace

        risk1 = RiskCalculator(cfg)
        risk2 = RiskCalculator(cfg)

        stats = SimpleNamespace(
            n=100, win_rate=0.6, avg_win_usd=200.0, avg_loss_usd=100.0
        )

        result1 = risk1.kelly_sizing_decision(
            strategy_stats=stats, equity=10000.0, atr_ratio=1.0,
            leverage=3, sl_distance_pct=0.005, min_trades_for_kelly=30,
        )
        result2 = risk2.kelly_sizing_decision(
            strategy_stats=stats, equity=10000.0, atr_ratio=1.0,
            leverage=3, sl_distance_pct=0.005, min_trades_for_kelly=30,
        )

        assert result1 == result2, (
            f"Kelly 决策非确定性: {result1} vs {result2}. "
            f"同一输入必须同一输出 (否则 shadow 无法对齐)."
        )


# ──────────── S-3: Drift detection 算法 ────────────

class TestDriftDetectionBetweenProductionAndShadow:
    """
    比较 production portfolio vs shadow portfolio 的状态。
    drift > 阈值 → 告警。

    这是 S-4 (shadow 部署) 跑起来后, 每天自动跑的逻辑。
    """

    def test_no_drift_when_identical(self):
        """两个完全相同的 portfolio → drift = 0"""
        portfolio_a = {
            "positions": [{"symbol": "BTC", "size": 0.1, "leverage": 3}],
            "closed_positions": [],
            "daily_stats": {"total_pnl": 0.0, "total_trades": 0},
        }
        portfolio_b = copy.deepcopy(portfolio_a)

        drift = compute_drift(portfolio_a, portfolio_b)
        assert drift == 0.0, f"完全相同 portfolio drift 应 = 0, got {drift}"

    def test_drift_detects_position_count_mismatch(self):
        """production 多一个仓位 → drift 应 > 0"""
        a = {"positions": [{"symbol": "BTC", "size": 0.1}], "closed_positions": [], "daily_stats": {}}
        b = {"positions": [{"symbol": "BTC", "size": 0.1}, {"symbol": "ETH", "size": 0.5}],
             "closed_positions": [], "daily_stats": {}}

        drift = compute_drift(a, b)
        assert drift > 0, f"仓位数量不同应被检测, got drift={drift}"

    def test_drift_detects_pnl_mismatch(self):
        """production PnL 不同 → drift 应 > 0"""
        a = {"positions": [], "closed_positions": [], "daily_stats": {"total_pnl": 100.0, "total_trades": 5}}
        b = {"positions": [], "closed_positions": [], "daily_stats": {"total_pnl": 50.0, "total_trades": 5}}

        drift = compute_drift(a, b)
        assert drift > 0, f"PnL 不同应被检测, got drift={drift}"

    def test_drift_below_threshold_passes(self):
        """drift < 阈值 → 不告警 (浮点误差容忍)"""
        a = {"positions": [], "closed_positions": [], "daily_stats": {"total_pnl": 100.0, "total_trades": 5}}
        b = {"positions": [], "closed_positions": [], "daily_stats": {"total_pnl": 100.001, "total_trades": 5}}  # 0.001 差异

        drift = compute_drift(a, b)
        threshold = 0.01
        assert drift < threshold, f"小浮点误差应 < threshold, got drift={drift}"


# ──────────── S-4: Shadow 部署 contract ────────────

class TestShadowDeploymentContract:
    """
    Shadow runner 必须满足的 contract (蓝图, 依赖待实现):
      1. state/ 目录与 production 隔离 (不同 state 目录)
      2. 同样输入产生同样输出 (S-1, S-2 已验证 Signal + Risk 可重现)
      3. 不发真单 (OKXClient 下单 API 被 monkeypatch 为 no-op)
      4. drift detection 逻辑独立于 signal/risk (S-3 已验证)

    当前状态: S-4 是 contract 蓝图, 不是现状测试。完整 shadow runner
    需要额外的实现 (1-2 周工程量):
      - 新增 scripts/runner_shadow.py (复制 runner.py + monkeypatch orders)
      - 独立 cron job (okx-runner-shadow, 与 okx-signal-runner 平行)
      - 独立 state 目录 (state/shadow/portfolio.json)
      - 每日 drift comparison + Telegram 告警

    本测试只验证 S-1/S-2/S-3 这些"shadow 可行性"的前提条件,
    不验证 shadow runner 本身存在。
    """

    def test_signal_engine_is_deterministic_enough_for_shadow(self, cfg):
        """验证: SignalEngine 输出可重现 (shadow 前提)

        这是 S-4 contract 的最低门槛: 如果 SignalEngine 不确定性,
        shadow vs production drift 是必然的, 而不是 bug.
        """
        mock_market = MagicMock()
        mock_market.get_candles = MagicMock(return_value=[
            ["ts", "50000", "50100", "49900", "50050", "100", "100", "100"],
        ])
        engine = SignalEngine(market_api=mock_market, config=cfg)

        # 跑 3 次, 必须相同
        runs = [engine.check_all_symbols([]) for _ in range(3)]
        for i in range(len(runs) - 1):
            assert len(runs[i]) == len(runs[i + 1]), (
                f"Signal count 不一致: run {i}={len(runs[i])}, run {i+1}={len(runs[i+1])}"
            )
            for s1, s2 in zip(runs[i], runs[i + 1]):
                assert s1.symbol == s2.symbol
                assert s1.direction == s2.direction


# ──────────── Helpers ────────────

def compute_drift(a: dict, b: dict) -> float:
    """
    计算 production vs shadow portfolio 的 drift 分数。

    简化算法:
      - position_count_diff × 1.0 (重大)
      - closed_position_count_diff × 0.5
      - daily_pnl_diff / max(|a|, |b|, 1) × 1.0 (相对差异)

    返回: float ≥ 0, 越大 drift 越大
    """
    drift = 0.0

    # Position count
    a_pos = len(a.get("positions", []))
    b_pos = len(b.get("positions", []))
    drift += abs(a_pos - b_pos) * 1.0

    # Closed count
    a_closed = len(a.get("closed_positions", []))
    b_closed = len(b.get("closed_positions", []))
    drift += abs(a_closed - b_closed) * 0.5

    # Daily PnL relative diff
    a_pnl = a.get("daily_stats", {}).get("total_pnl", 0.0)
    b_pnl = b.get("daily_stats", {}).get("total_pnl", 0.0)
    pnl_denom = max(abs(a_pnl), abs(b_pnl), 1.0)
    drift += abs(a_pnl - b_pnl) / pnl_denom

    return drift


def _write_cfg(tmp_path) -> str:
    """写一份 minimal config 给 shadow test"""
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({
        "version": "test",
        "trading": {"demo_mode": True, "default_leverage_main": 3, "max_concurrent_positions": 3},
        "risk": {"max_loss_percent_per_trade": 1.0, "kelly": {}},
        "leverage_matrix": {"BTC": {"min_leverage": 3, "max_leverage": 3, "hard_ceiling": 3}},
        "audit": {},
        "openclaw": {},
        "notifier": {"enabled": False},
    }))
    return str(cfg)