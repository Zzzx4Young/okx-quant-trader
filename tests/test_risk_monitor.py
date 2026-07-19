# -*- coding: utf-8 -*-
"""
risk_monitor.py 单元测试

覆盖：
- fetch_snapshot: 正常 / 空仓 / API 失败 / skip zero pos
- compute_metrics: 杠杆 / 集中度 / uPnL / 强平距离 / SL
- check_thresholds: 各阈值临界点触发
- format_report: 健康 / 异常 / 无持仓 / degraded
- format_telegram_alert: critical only
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# 让 pytest 找到 okx 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from okx.scripts.risk_monitor import (
    COMMON_CTVAL,
    check_thresholds,
    compute_metrics,
    fetch_snapshot,
    format_report,
    format_telegram_alert,
)
from okx.scripts.risk_thresholds import (
    RISK_THRESHOLDS,
    PositionRisk,
    RiskMetrics,
    get_threshold,
)


# ──────────── Mocks ────────────


class MockAccount:
    """Mock OKX account API"""

    def __init__(self, balance=None, positions=None, raise_exc: bool = False):
        self._balance = balance
        self._positions = positions
        self._raise_exc = raise_exc

    def get_balance(self, ccy=None):
        if self._raise_exc:
            raise ConnectionError("API timeout")
        return self._balance

    def get_positions(self, inst_type=None, inst_id=None):
        if self._raise_exc:
            raise ConnectionError("API timeout")
        return self._positions


class MockOKXClient:
    def __init__(self, balance=None, positions=None, raise_exc: bool = False):
        self.account = MockAccount(balance, positions, raise_exc)


def _make_okx_balance(total_eq: str = "77000") -> list:
    return [{"totalEq": total_eq, "availEq": "50000"}]


def _make_okx_position(
    inst_id: str = "BTC-USDT-SWAP",
    pos: str = "10",
    pos_side: str = "long",
    avg_px: str = "60000",
    mark_px: str = "61000",
    upl: str = "100",
    margin: str = "6000",
    liq_px: str = "55000",
    lever: str = "10",
    attach_algo_ords: list = None,
) -> dict:
    pos_dict = {
        "instId": inst_id,
        "posSide": pos_side,
        "pos": pos,
        "avgPx": avg_px,
        "markPx": mark_px,
        "upl": upl,
        "margin": margin,
        "liqPx": liq_px,
        "lever": lever,
    }
    if attach_algo_ords:
        pos_dict["attachAlgoOrds"] = attach_algo_ords
    return pos_dict


# ──────────── fetch_snapshot ────────────


class TestFetchSnapshot:
    def test_normal_one_position(self):
        client = MockOKXClient(
            balance=_make_okx_balance("77000"),
            positions=[_make_okx_position()],
        )
        positions, equity, status = fetch_snapshot(client, None)
        assert status == "ok"
        assert equity == 77000.0
        assert len(positions) == 1
        assert positions[0].inst_id == "BTC-USDT-SWAP"
        assert positions[0].notional_usd == pytest.approx(6100.0)  # 10 * 0.01 * 61000

    def test_empty_positions(self):
        client = MockOKXClient(
            balance=_make_okx_balance("77000"),
            positions=[],
        )
        positions, equity, status = fetch_snapshot(client, None)
        assert status == "ok"
        assert equity == 77000.0
        assert positions == []

    def test_skip_zero_position(self):
        """pos="0" 的应被过滤掉"""
        client = MockOKXClient(
            balance=_make_okx_balance("77000"),
            positions=[
                _make_okx_position(pos="0"),
                _make_okx_position(pos="5"),
            ],
        )
        positions, _, _ = fetch_snapshot(client, None)
        assert len(positions) == 1
        assert positions[0].size == 5.0

    def test_api_failure_returns_failed(self):
        client = MockOKXClient(raise_exc=True)
        positions, equity, status = fetch_snapshot(client, None)
        assert status == "failed"
        assert positions == []
        assert equity == 0.0

    def test_empty_balance_degraded(self):
        client = MockOKXClient(balance=[], positions=[])
        positions, equity, status = fetch_snapshot(client, None)
        assert status == "degraded"
        assert equity == 0.0

    def test_ctVal_fallback(self):
        """未知 inst_id 用 fallback ct_val=1.0"""
        client = MockOKXClient(
            balance=_make_okx_balance("77000"),
            positions=[_make_okx_position(inst_id="UNKNOWN-SWAP")],
        )
        positions, _, _ = fetch_snapshot(client, None)
        assert positions[0].ct_val == 1.0

    def test_attach_algo_ords_sl_tp(self):
        """attachAlgoOrds 中的 SL/TP 应被解析"""
        client = MockOKXClient(
            balance=_make_okx_balance("77000"),
            positions=[_make_okx_position(
                attach_algo_ords=[
                    {"slTriggerPx": "58000", "tpTriggerPx": "65000"}
                ]
            )],
        )
        positions, _, _ = fetch_snapshot(client, None)
        assert positions[0].sl_px == 58000.0
        assert positions[0].tp_px == 65000.0

    def test_match_strategy_with_direction_field(self):
        """v2 bug fix：portfolio 用 direction，OKX 用 posSide，应能匹配"""
        import json
        import tempfile
        from pathlib import Path
        # portfolio 存的是本地格式（symbol + direction）
        portfolio = {
            "positions": [
                {
                    "symbol": "BTCUSDTSWAP",
                    "direction": "short",
                    "size": 0.15,
                    "strategy": "EXTERNAL_WEB_SYNC",
                }
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(portfolio, f)
            tmp_path = Path(f.name)
        try:
            # fetch_snapshot 的 _match_strategy 内部调用
            # OKX 返回 inst_id="BTC-USDT-SWAP" + pos_side="short"
            client = MockOKXClient(
                balance=_make_okx_balance("77000"),
                positions=[_make_okx_position(
                    inst_id="BTC-USDT-SWAP",
                    pos_side="short",
                    pos="15",  # 15 张 = 0.15 BTC（ctVal=0.01）
                )],
            )
            positions, _, _ = fetch_snapshot(client, tmp_path)
            assert len(positions) == 1
            assert positions[0].strategy == "EXTERNAL_WEB_SYNC", \
                f"应匹配到 EXTERNAL_WEB_SYNC，实际: {positions[0].strategy}"
        finally:
            tmp_path.unlink()

    def test_match_strategy_instid_normalization(self):
        """v2 bug fix：instId 格式双向归一化（BTC-USDT-SWAP ↔ BTCUSDTSWAP）"""
        import json
        import tempfile
        from pathlib import Path
        portfolio = {
            "positions": [
                {
                    "symbol": "BTCUSDTSWAP",  # 本地简化格式
                    "direction": "long",
                    "strategy": "A_EMABREAKOUT",
                }
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(portfolio, f)
            tmp_path = Path(f.name)
        try:
            # OKX 返回带连字符格式
            client = MockOKXClient(
                balance=_make_okx_balance("77000"),
                positions=[_make_okx_position(
                    inst_id="BTC-USDT-SWAP",
                    pos_side="long",
                    pos="10",
                )],
            )
            positions, _, _ = fetch_snapshot(client, tmp_path)
            assert positions[0].strategy == "A_EMABREAKOUT"
        finally:
            tmp_path.unlink()


# ──────────── compute_metrics ────────────


def _make_position(
    inst_id: str = "BTC-USDT-SWAP",
    pos_side: str = "long",
    size: float = 10.0,
    ct_val: float = 0.01,
    avg_px: float = 60000.0,
    mark_px: float = 61000.0,
    upl: float = 100.0,
    margin: float = 6000.0,
    liq_px: float = 55000.0,
    leverage: float = 10.0,
    strategy: str = "A",
    sl_px: float = None,
) -> PositionRisk:
    return PositionRisk(
        inst_id=inst_id,
        pos_side=pos_side,
        size=size,
        ct_val=ct_val,
        avg_px=avg_px,
        mark_px=mark_px,
        upl=upl,
        margin=margin,
        liq_px=liq_px,
        leverage=leverage,
        strategy=strategy,
        sl_px=sl_px,
    )


class TestComputeMetrics:
    def test_no_positions(self):
        m = compute_metrics([], equity_usd=77000.0)
        assert m.position_count == 0
        assert m.gross_leverage == 0.0
        assert m.equity_buffer_pct == 1.0
        assert m.upl_pct == 0.0

    def test_zero_equity(self):
        """equity=0 时不应除零"""
        positions = [_make_position()]
        m = compute_metrics(positions, equity_usd=0.0)
        assert m.gross_leverage == 0.0

    def test_single_position_gross_leverage(self):
        """毛杠杆 = total_notional / equity"""
        # notional = 10 * 0.01 * 61000 = 6100
        # equity = 77000 → gross_lev = 0.0792x
        positions = [_make_position(size=10.0, ct_val=0.01, mark_px=61000.0)]
        m = compute_metrics(positions, equity_usd=77000.0)
        assert m.total_notional_usd == pytest.approx(6100.0)
        assert m.gross_leverage == pytest.approx(6100 / 77000)

    def test_long_short_net(self):
        """多空混合时净敞口 = 长 - 短"""
        long_pos = _make_position(inst_id="BTC-USDT-SWAP", pos_side="long", size=10, ct_val=0.01, mark_px=60000)
        short_pos = _make_position(inst_id="ETH-USDT-SWAP", pos_side="short", size=20, ct_val=0.1, mark_px=3000)
        m = compute_metrics([long_pos, short_pos], equity_usd=77000.0)
        # long notional = 10 * 0.01 * 60000 = 6000
        # short notional = 20 * 0.1 * 3000 = 6000
        # net = 6000 - 6000 = 0
        assert m.net_notional_usd == pytest.approx(0.0)

    def test_concentration(self):
        """单标的占比"""
        # BTC 占大头 → inst_concentration 应接近 80%
        btc = _make_position(inst_id="BTC-USDT-SWAP", size=100, ct_val=0.01, mark_px=60000)  # 60000
        eth = _make_position(inst_id="ETH-USDT-SWAP", size=15, ct_val=0.1, mark_px=3000)  # 4500
        m = compute_metrics([btc, eth], equity_usd=77000.0)
        assert m.inst_concentration_target == "BTC-USDT-SWAP"
        assert m.inst_concentration == pytest.approx(60000 / 64500)

    def test_strategy_concentration(self):
        a1 = _make_position(inst_id="BTC-USDT-SWAP", strategy="A", size=100, ct_val=0.01, mark_px=60000)
        a2 = _make_position(inst_id="ETH-USDT-SWAP", strategy="A", size=15, ct_val=0.1, mark_px=3000)
        b1 = _make_position(inst_id="SOL-USDT-SWAP", strategy="B", size=1, ct_val=1, mark_px=100)
        m = compute_metrics([a1, a2, b1], equity_usd=77000.0)
        assert m.strategy_concentration_target == "A"

    def test_min_liq_distance(self):
        """最小强平距离 = min over positions"""
        p1 = _make_position(inst_id="BTC-USDT-SWAP", mark_px=60000, liq_px=55000)  # 8.33%
        p2 = _make_position(inst_id="ETH-USDT-SWAP", mark_px=3000, liq_px=2700)    # 10%
        m = compute_metrics([p1, p2], equity_usd=77000.0)
        assert m.min_liq_target == "BTC-USDT-SWAP"
        assert m.min_liq_distance_pct < 0.1

    def test_max_sl_consumed(self):
        p1 = _make_position(inst_id="BTC-USDT-SWAP", avg_px=60000, mark_px=59500, sl_px=58000)  # 25%
        p2 = _make_position(inst_id="ETH-USDT-SWAP", avg_px=3000, mark_px=2700, sl_px=2400)    # 50%
        m = compute_metrics([p1, p2], equity_usd=77000.0)
        assert m.max_sl_target == "ETH-USDT-SWAP"
        assert m.max_sl_consumed_pct == pytest.approx(0.5)

    def test_equity_buffer(self):
        """净值缓冲 = (equity - used_margin) / equity"""
        positions = [_make_position(margin=6000.0)]  # 6000 used
        m = compute_metrics(positions, equity_usd=77000.0)
        expected = (77000 - 6000) / 77000
        assert m.equity_buffer_pct == pytest.approx(expected)


# ──────────── check_thresholds ────────────


class TestCheckThresholds:
    def test_no_positions_empty_issues(self):
        m = RiskMetrics(equity_usd=77000.0, position_count=0)
        issues = check_thresholds(m)
        assert issues == []

    def test_gross_leverage_warning(self):
        m = RiskMetrics(
            equity_usd=10000.0,
            gross_leverage=3.5,  # warn=3.0, crit=5.0 → warning
            position_count=1,
        )
        issues = check_thresholds(m)
        assert any(i.check == "gross_leverage" and i.level == "warning" for i in issues)

    def test_gross_leverage_critical(self):
        m = RiskMetrics(
            equity_usd=10000.0,
            gross_leverage=5.5,
            position_count=1,
        )
        issues = check_thresholds(m)
        assert any(i.check == "gross_leverage" and i.level == "critical" for i in issues)

    def test_upl_pct_critical(self):
        """uPnL -12% → critical（阈值 -10%）"""
        m = RiskMetrics(
            equity_usd=77000.0,
            upl_pct=-0.12,
            position_count=1,
        )
        issues = check_thresholds(m)
        assert any(i.check == "upl_pct" and i.level == "critical" for i in issues)

    def test_upl_pct_warning(self):
        m = RiskMetrics(
            equity_usd=77000.0,
            upl_pct=-0.07,  # 介于 -5% 和 -10% 之间
            position_count=1,
        )
        issues = check_thresholds(m)
        assert any(i.check == "upl_pct" and i.level == "warning" for i in issues)

    def test_liq_proximity_critical(self):
        """最小强平距离 4% → critical（阈值 5%）"""
        m = RiskMetrics(
            equity_usd=77000.0,
            min_liq_distance_pct=0.04,
            min_liq_target="BTC-USDT-SWAP",
            position_count=1,
        )
        issues = check_thresholds(m)
        assert any(i.check == "liq_proximity_pct" and i.level == "critical" for i in issues)

    def test_inst_concentration_structural(self):
        """inst_concentration 属结构性失衡，应返回 level="structural"（不被 watchdog 发 Telegram）

        设计：集中度是 portfolio 结构特征，不是当下爆仓风险。
        watchdog 会抑制 Telegram，仅写日志。v1.8.3+ (2026-07-19)。
        """
        m = RiskMetrics(
            equity_usd=77000.0,
            inst_concentration=0.75,  # crit=0.70
            inst_concentration_target="BTC-USDT-SWAP",
            position_count=1,
        )
        issues = check_thresholds(m)
        assert any(i.check == "inst_concentration" and i.level == "structural" for i in issues)
        # 不再是 critical (防告警噪声)
        assert not any(i.check == "inst_concentration" and i.level == "critical" for i in issues)

    def test_strategy_concentration_structural(self):
        """strategy_concentration 同样属于 structural"""
        m = RiskMetrics(
            equity_usd=77000.0,
            strategy_concentration=0.85,  # crit=0.80
            strategy_concentration_target="A",
            position_count=1,
        )
        issues = check_thresholds(m)
        assert any(i.check == "strategy_concentration" and i.level == "structural" for i in issues)
        assert not any(i.check == "strategy_concentration" and i.level == "critical" for i in issues)

    def test_structural_override_does_not_affect_real_critical(self):
        """structural 标记只 override 集中度；真 critical 仍然发 critical（如 leverage 爆仓）"""
        m = RiskMetrics(
            equity_usd=77000.0,
            gross_leverage=5.5,  # crit
            inst_concentration=0.75,  # structural
            position_count=1,
        )
        issues = check_thresholds(m)
        # gross_leverage 应仍是 critical (真风险)
        assert any(i.check == "gross_leverage" and i.level == "critical" for i in issues)
        # inst_concentration 是 structural
        assert any(i.check == "inst_concentration" and i.level == "structural" for i in issues)

    def test_sl_consumed_warning(self):
        m = RiskMetrics(
            equity_usd=77000.0,
            max_sl_consumed_pct=0.75,
            max_sl_target="BTC-USDT-SWAP",
            position_count=1,
        )
        issues = check_thresholds(m)
        assert any(i.check == "sl_consumed_pct" and i.level == "warning" for i in issues)

    def test_healthy_no_issues(self):
        """正常仓位：杠杆低、uPnL 0、集中度合理"""
        m = RiskMetrics(
            equity_usd=77000.0,
            gross_leverage=0.5,
            net_leverage=0.5,
            upl_pct=0.0,
            inst_concentration=0.4,
            strategy_concentration=0.4,
            min_liq_distance_pct=0.2,
            max_sl_consumed_pct=0.1,
            equity_buffer_pct=0.8,
            position_count=2,
        )
        issues = check_thresholds(m)
        assert issues == []


# ──────────── format_report ────────────


class TestFormatReport:
    def test_no_positions_healthy(self):
        m = RiskMetrics(equity_usd=77000.0, position_count=0)
        text = format_report(m, [], mode="demo")
        assert "✓ 健康" in text
        assert "$77,000" in text

    def test_healthy_with_positions_dashboard(self):
        """健康时也输出完整仪表板"""
        m = RiskMetrics(
            equity_usd=77000.0,
            used_margin_usd=6000.0,
            total_notional_usd=10000.0,
            net_notional_usd=5000.0,
            gross_leverage=0.13,
            net_leverage=0.065,
            total_upl_usd=100.0,
            upl_pct=0.0013,
            inst_concentration=0.6,
            inst_concentration_target="BTC-USDT-SWAP",
            strategy_concentration=0.5,
            strategy_concentration_target="A_EMABREAKOUT",
            min_liq_distance_pct=0.15,
            min_liq_target="BTC-USDT-SWAP",
            max_sl_consumed_pct=0.2,
            max_sl_target="ETH-USDT-SWAP",
            equity_buffer_pct=0.92,
            position_count=2,
        )
        text = format_report(m, [], mode="demo")
        assert "✓ 健康" in text
        assert "仓位风险仪表板" in text
        assert "$77,000" in text
        assert "BTC-USDT-SWAP" in text

    def test_critical_issues_listed(self):
        m = RiskMetrics(
            equity_usd=10000.0,
            gross_leverage=5.5,  # crit
            upl_pct=-0.12,  # crit
            position_count=1,
        )
        issues = check_thresholds(m)
        text = format_report(m, issues, mode="demo")
        assert "🚨" in text or "异常" in text
        assert "gross_leverage" in text
        assert "upl_pct" in text

    def test_degraded_mode(self):
        m = RiskMetrics(equity_usd=0, position_count=0, api_status="degraded")
        text = format_report(m, [], mode="demo")
        assert "degraded" in text.lower() or "API" in text

    def test_failed_mode_no_dashboard(self):
        m = RiskMetrics(equity_usd=0, position_count=0, api_status="failed")
        text = format_report(m, [], mode="demo")
        assert "跳过" in text or "failed" in text.lower()


# ──────────── format_telegram_alert ────────────


class TestFormatTelegramAlert:
    def test_empty_when_no_critical(self):
        m = RiskMetrics(equity_usd=77000.0)
        issues = []
        text = format_telegram_alert(issues, m, mode="demo")
        assert text == ""

    def test_only_warning_returns_empty(self):
        """仅 warning 时不应发 Telegram"""
        m = RiskMetrics(equity_usd=77000.0, position_count=1, gross_leverage=3.5)
        issues = check_thresholds(m)
        assert all(i.level == "warning" for i in issues)
        text = format_telegram_alert(issues, m, mode="demo")
        assert text == ""

    def test_critical_includes_alert_header(self):
        m = RiskMetrics(
            equity_usd=77000.0,
            position_count=1,
            gross_leverage=5.5,
            upl_pct=-0.12,
        )
        issues = check_thresholds(m)
        critical = [i for i in issues if i.level == "critical"]
        assert len(critical) > 0
        text = format_telegram_alert(issues, m, mode="demo")
        assert "🚨" in text
        assert "OKX 仓位风险告警" in text
        assert "DEMO" in text
