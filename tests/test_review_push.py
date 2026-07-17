# -*- coding: utf-8 -*-
"""
test_review_push.py —— review_push.py 单测

覆盖：
- read_closed_trades: CSV 读取 / 缺失 / 损坏 fallback
- summarize_closed_trades: 空 / 全赢 / 全亏 / 混合
- compose_position_status: 无持仓 / 单持仓 / 多持仓 / 含 HTML 危险字符检查
- compose_message: 4 段结构 + 各场景
- write_log: 时间戳 + 内容
- main: 端到端（mock OKX + Telegram + CSV）

跑法:
  pytest okx/tests/test_review_push.py -v
"""
import csv
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from okx.scripts import review_push as rv

# ────────────────────────────────────────────────────────────────────
# 工具：写测试 CSV
# ────────────────────────────────────────────────────────────────────

CSV_HEADER = "timestamp,symbol,direction,action,price,size,leverage,margin,order_id,strategy,pnl,roe_percent,fee,slippage,pnl_net,note"

def write_trades_csv(path: Path, rows: list):
    """rows 是 [{symbol, pnl, ...}, ...] 列表"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER.split(","))
        for r in rows:
            writer.writerow([
                r.get("timestamp", "2026-07-15T00:00:00Z"),
                r.get("symbol", "BTCUSDTSWAP"),
                r.get("direction", "short"),
                r.get("action", "CLOSE"),
                r.get("price", "64225"),
                r.get("size", "0.15"),
                r.get("leverage", "3"),
                r.get("margin", "3261"),
                r.get("order_id", ""),
                r.get("strategy", "EXTERNAL_WEB_SYNC"),
                r.get("pnl", "0"),
                r.get("roe_percent", "0"),
                r.get("fee", "0"),
                r.get("slippage", "0"),
                r.get("pnl_net", "0"),
                r.get("note", ""),
            ])

# ────────────────────────────────────────────────────────────────────
# read_closed_trades —— CSV 读取
# ────────────────────────────────────────────────────────────────────

class TestReadClosedTrades:
    def test_normal(self, tmp_path, monkeypatch):
        write_trades_csv(tmp_path / "trades" / "2026-07-15.csv", [
            {"symbol": "BTCUSDTSWAP", "pnl": "-0.671"},
        ])
        monkeypatch.setattr(rv, "TRADES_DIR", tmp_path / "trades")
        trades = rv.read_closed_trades("2026-07-15")
        assert len(trades) == 1
        assert trades[0]["symbol"] == "BTCUSDTSWAP"
        assert trades[0]["pnl"] == "-0.671"

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rv, "TRADES_DIR", tmp_path / "trades")
        trades = rv.read_closed_trades("2026-07-15")
        assert trades == []

    def test_corrupt_csv_returns_empty(self, tmp_path, monkeypatch):
        (tmp_path / "trades").mkdir()
        (tmp_path / "trades" / "bad.csv").write_text("{not csv", encoding="utf-8")
        monkeypatch.setattr(rv, "TRADES_DIR", tmp_path / "trades")
        trades = rv.read_closed_trades("bad")
        assert trades == []

# ────────────────────────────────────────────────────────────────────
# summarize_closed_trades —— 统计
# ────────────────────────────────────────────────────────────────────

class TestSummarizeClosedTrades:
    def test_empty(self):
        s = rv.summarize_closed_trades([])
        assert s["count"] == 0
        assert s["total_pnl"] == 0.0
        assert s["max_trade"] is None
        assert s["win_count"] == 0
        assert s["win_rate"] is None

    def test_all_win(self):
        trades = [
            {"symbol": "BTCUSDTSWAP", "pnl": "10.0"},
            {"symbol": "ETHUSDTSWAP", "pnl": "5.0"},
        ]
        s = rv.summarize_closed_trades(trades)
        assert s["count"] == 2
        assert s["total_pnl"] == 15.0
        assert s["max_trade"]["symbol"] == "BTCUSDTSWAP"
        assert s["max_trade"]["pnl"] == 10.0
        assert s["win_count"] == 2
        assert s["win_rate"] == 1.0

    def test_all_loss(self):
        trades = [
            {"symbol": "BTCUSDTSWAP", "pnl": "-1.0"},
            {"symbol": "ETHUSDTSWAP", "pnl": "-2.0"},
        ]
        s = rv.summarize_closed_trades(trades)
        assert s["count"] == 2
        assert s["total_pnl"] == -3.0
        # max by pnl value: -1.0 > -2.0，所以 max_trade 是 BTCUSDTSWAP（损失最小的）
        assert s["max_trade"]["symbol"] == "BTCUSDTSWAP"
        assert s["max_trade"]["pnl"] == -1.0
        assert s["win_count"] == 0
        assert s["win_rate"] == 0.0

    def test_mixed(self):
        trades = [
            {"symbol": "BTCUSDTSWAP", "pnl": "10.0"},
            {"symbol": "ETHUSDTSWAP", "pnl": "-3.0"},
            {"symbol": "SOLUSDTSWAP", "pnl": "2.0"},
        ]
        s = rv.summarize_closed_trades(trades)
        assert s["count"] == 3
        assert s["total_pnl"] == 9.0
        assert s["max_trade"]["symbol"] == "BTCUSDTSWAP"
        assert s["win_count"] == 2
        assert abs(s["win_rate"] - 2/3) < 1e-9

    def test_pnl_zero_counts_as_loss(self):
        """pnl=0 既不算赢也不算亏，按 >0 严格判断为亏"""
        trades = [
            {"symbol": "X", "pnl": "0"},
            {"symbol": "Y", "pnl": "1"},
        ]
        s = rv.summarize_closed_trades(trades)
        assert s["win_count"] == 1  # 只 Y 算赢
        assert abs(s["win_rate"] - 0.5) < 1e-9

    def test_invalid_pnl_falls_back_to_zero(self):
        trades = [{"symbol": "X", "pnl": "not-a-number"}]
        s = rv.summarize_closed_trades(trades)
        assert s["total_pnl"] == 0.0
        assert s["max_trade"]["pnl"] == 0.0

# ────────────────────────────────────────────────────────────────────
# compose_position_status —— 持仓描述
# ────────────────────────────────────────────────────────────────────

class TestComposePositionStatus:
    def test_no_positions(self):
        assert rv.compose_position_status([]) == "无持仓"

    def test_single_profit_position(self):
        positions = [{
            "instId": "BTC-USDT-SWAP",
            "posSide": "short",
            "pos": "0.15",
            "avgPx": "64225",
            "upl": "1.5",
            "margin": "32.15",
        }]
        out = rv.compose_position_status(positions)
        assert "BTC-USDT-SWAP short 0.15张 @64225" in out
        assert "未实现 +1.50 USDT" in out
        assert "盈利 +4.67%" in out  # 1.5/32.15*100

    def test_single_loss_position(self):
        positions = [{
            "instId": "ETH-USDT-SWAP",
            "posSide": "long",
            "pos": "1.0",
            "avgPx": "3000",
            "upl": "-50",
            "margin": "100",
        }]
        out = rv.compose_position_status(positions)
        assert "亏损 -50.00%" in out

    def test_multiple_positions_joined_with_semicolon(self):
        positions = [
            {"instId": "BTC-USDT-SWAP", "posSide": "short", "pos": "0.15", "avgPx": "64225", "upl": "1.5", "margin": "32"},
            {"instId": "ETH-USDT-SWAP", "posSide": "long", "pos": "1.0", "avgPx": "3000", "upl": "-5", "margin": "100"},
        ]
        out = rv.compose_position_status(positions)
        assert "BTC-USDT-SWAP" in out
        assert "ETH-USDT-SWAP" in out
        assert ";" in out

    def test_no_html_special_chars(self):
        """planY 关键约束：持仓描述不能含 HTML 字符（默认 parse_mode=HTML）"""
        positions = [{
            "instId": "BTC-USDT-SWAP",
            "posSide": "short",
            "pos": "0.15",
            "avgPx": "64225",
            "upl": "-3.99",
            "margin": "32.15",
        }]
        out = rv.compose_position_status(positions)
        for ch in ["<", ">", "&"]:
            assert ch not in out, f"消息含 HTML 字符 {ch!r}: {out!r}"

# ────────────────────────────────────────────────────────────────────
# compose_message —— 6 段结构（v2 重构后）
class TestFetchWithRetry:
    def test_success_first_try(self):
        """第一次就成功：不重试、不 sleep"""
        call_count = [0]
        def fn():
            call_count[0] += 1
            return "ok"
        # 用 monkeypatch 缩短 sleep（如果失败 sleep 会被跳过，因为第 1 次成功）
        result = rv.fetch_with_retry(fn, max_attempts=3, backoff=(0, 0, 0))
        assert result == "ok"
        assert call_count[0] == 1

    def test_success_after_two_retries(self):
        """前 2 次失败，第 3 次成功"""
        call_count = [0]
        def fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError(f"attempt {call_count[0]} fail")
            return "ok"
        result = rv.fetch_with_retry(fn, max_attempts=3, backoff=(0, 0, 0))
        assert result == "ok"
        assert call_count[0] == 3

    def test_all_attempts_fail_raises_last(self):
        """全部失败：抛最后一次异常"""
        call_count = [0]
        def fn():
            call_count[0] += 1
            raise ConnectionError(f"attempt {call_count[0]} fail")
        with pytest.raises(ConnectionError) as exc_info:
            rv.fetch_with_retry(fn, max_attempts=3, backoff=(0, 0, 0))
        assert call_count[0] == 3
        assert "attempt 3" in str(exc_info.value)

    def test_non_network_error_not_retried(self):
        """非网络错误（如 OKX 业务错误）不重试，立即抛"""
        call_count = [0]
        def fn():
            call_count[0] += 1
            raise ValueError("not a network error")
        with pytest.raises(ValueError):
            rv.fetch_with_retry(fn, max_attempts=3, backoff=(0, 0, 0))
        assert call_count[0] == 1  # 只调用 1 次，不重试

# ────────────────────────────────────────────────────────────────────
# read_portfolio_summary —— portfolio.json 读取（v2 新增）
# ────────────────────────────────────────────────────────────────────

class TestReadPortfolioSummary:
    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rv, "PORTFOLIO_FILE", tmp_path / "missing.json")
        result = rv.read_portfolio_summary("2026-07-18")
        assert result["daily_stats"] == {}
        assert result["strategy_breakdown"] == {}
        assert "不存在" in result["load_error"]

    def test_corrupt_file(self, tmp_path, monkeypatch):
        pf = tmp_path / "portfolio.json"
        pf.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(rv, "PORTFOLIO_FILE", pf)
        result = rv.read_portfolio_summary("2026-07-18")
        assert result["load_error"] is not None

    def test_strategy_breakdown_filters_today(self, tmp_path, monkeypatch):
        pf = tmp_path / "portfolio.json"
        data = {
            "daily_stats": {"consecutive_losses": 2, "emergency_stop_triggered": False},
            "closed_positions": [
                # 今日 2 笔：A 策略 1 笔 +5，B 策略 1 笔 -2
                {
                    "strategy": "A_EMABREAKOUT", "realized_pnl": 5.0,
                    "closed_at": "2026-07-18T10:00:00Z",
                },
                {
                    "strategy": "B_BBREV", "realized_pnl": -2.0,
                    "closed_at": "2026-07-18T15:00:00Z",
                },
                # 昨日 1 笔（应被过滤）
                {
                    "strategy": "A_EMABREAKOUT", "realized_pnl": 100.0,
                    "closed_at": "2026-07-17T15:00:00Z",
                },
            ],
        }
        pf.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(rv, "PORTFOLIO_FILE", pf)

        result = rv.read_portfolio_summary("2026-07-18")
        assert result["daily_stats"]["consecutive_losses"] == 2
        # 今日 A: 1 笔 +5, B: 1 笔 -2
        assert result["strategy_breakdown"]["A_EMABREAKOUT"]["count"] == 1
        assert result["strategy_breakdown"]["A_EMABREAKOUT"]["pnl"] == 5.0
        assert result["strategy_breakdown"]["B_BBREV"]["count"] == 1
        assert result["strategy_breakdown"]["B_BBREV"]["pnl"] == -2.0
        # 昨日的 100 USDT 不能混进来
        assert len(result["strategy_breakdown"]) == 2

# ────────────────────────────────────────────────────────────────────
# get_yesterday_shanghai_date（v2 新增）
# ────────────────────────────────────────────────────────────────────

class TestGetYesterdayShanghaiDate:
    def test_normal(self):
        assert rv.get_yesterday_shanghai_date("2026-07-18") == "2026-07-17"

    def test_month_boundary(self):
        assert rv.get_yesterday_shanghai_date("2026-08-01") == "2026-07-31"

    def test_year_boundary(self):
        assert rv.get_yesterday_shanghai_date("2026-01-01") == "2025-12-31"

# ────────────────────────────────────────────────────────────────────
# compute_liq_proximity（v2 新增）
# ────────────────────────────────────────────────────────────────────

class TestComputeLiqProximity:
    def test_no_positions(self):
        assert rv.compute_liq_proximity([]) == "N/A"

    def test_single_position_safe(self):
        positions = [{"instId": "BTC-USDT-SWAP", "markPx": "60000", "liqPx": "55000"}]
        # |60000-55000|/60000 = 8.33%
        assert "8.33%" in rv.compute_liq_proximity(positions)
        assert "⚠️" not in rv.compute_liq_proximity(positions)

    def test_near_liq_warns(self):
        positions = [{"instId": "BTC-USDT-SWAP", "markPx": "60000", "liqPx": "58000"}]
        # |60000-58000|/60000 = 3.33% < 5% → ⚠️
        result = rv.compute_liq_proximity(positions)
        assert "3.33%" in result
        assert "⚠️" in result

    def test_picks_min_distance(self):
        positions = [
            {"instId": "BTC-USDT-SWAP", "markPx": "60000", "liqPx": "55000"},  # 8.33%
            {"instId": "ETH-USDT-SWAP", "markPx": "3000", "liqPx": "2850"},    # 5.0%
        ]
        result = rv.compute_liq_proximity(positions)
        assert "5.00%" in result
        assert "ETH-USDT-SWAP" not in result  # 只有距离，不含 symbol

# ────────────────────────────────────────────────────────────────────
# compose_message —— 6 段结构验证（v2 新增）
# ────────────────────────────────────────────────────────────────────

class TestComposeMessage6Sections:
    def _empty_stats(self):
        return {"count": 0, "total_pnl": 0.0, "max_trade": None, "win_count": 0, "win_rate": None}

    def test_all_6_sections_present(self):
        msg = rv.compose_message(
            stats=self._empty_stats(),
            upl=0.0, n_positions=0,
            position_status="无持仓",
            portfolio={"daily_stats": {}, "strategy_breakdown": {}},
            yesterday={"count": 0, "total_pnl": 0.0},
            liq_proximity="N/A",
        )
        for section in ["1. 今日交易", "2. 胜率", "3. 策略归因",
                        "4. 风控状态", "5. 持仓快照", "6. 昨日对比"]:
            assert section in msg, f"缺段: {section}"

    def test_strategy_breakdown_rendered(self):
        msg = rv.compose_message(
            stats=self._empty_stats(),
            upl=0.0, n_positions=0,
            position_status="无持仓",
            portfolio={
                "daily_stats": {},
                "strategy_breakdown": {"A_EMABREAKOUT": {"count": 3, "pnl": 12.5}},
            },
            yesterday={"count": 0, "total_pnl": 0.0},
            liq_proximity="N/A",
        )
        assert "A_EMABREAKOUT" in msg
        assert "3 笔" in msg
        assert "+12.5000 USDT" in msg

    def test_risk_status_with_emergency(self):
        msg = rv.compose_message(
            stats=self._empty_stats(),
            upl=0.0, n_positions=0,
            position_status="无持仓",
            portfolio={
                "daily_stats": {"consecutive_losses": 5, "emergency_stop_triggered": True, "total_pnl": -8.0},
                "strategy_breakdown": {},
            },
            yesterday={"count": 0, "total_pnl": 0.0},
            liq_proximity="N/A",
        )
        assert "连续亏损: 5 次" in msg
        assert "⚠️ 已触发" in msg
        assert "-8.0000 USDT" in msg

    def test_degraded_marker(self):
        msg = rv.compose_message(
            stats=self._empty_stats(),
            upl=0.0, n_positions=0,
            position_status="⚠️ OKX API 不可用",
            portfolio={"daily_stats": {}, "strategy_breakdown": {}},
            yesterday={"count": 0, "total_pnl": 0.0},
            liq_proximity="N/A",
            okx_degraded=True,
        )
        assert "degraded" in msg
        assert "持仓数据不可用" in msg

# ────────────────────────────────────────────────────────────────────
# main 端到端 —— degraded 模式（v2 新增）
# ────────────────────────────────────────────────────────────────────

class TestMainDegradedMode:
    """OKX API 失败时仍出报告（graceful degradation）"""

    def _setup_files(self, tmp_path, monkeypatch, trades_csv_rows=None, date=None,
                     portfolio_data=None):
        date = date or rv.get_today_shanghai_date()
        trades_dir = tmp_path / "trades"
        if trades_csv_rows is not None:
            write_trades_csv(trades_dir / f"{date}.csv", trades_csv_rows)
        monkeypatch.setattr(rv, "TRADES_DIR", trades_dir)
        monkeypatch.setattr(rv, "LOG_FILE", tmp_path / "daily_review.log")
        monkeypatch.setattr(rv, "ENV_FILE", tmp_path / ".env")
        if portfolio_data is not None:
            pf = tmp_path / "portfolio.json"
            pf.write_text(json.dumps(portfolio_data), encoding="utf-8")
            monkeypatch.setattr(rv, "PORTFOLIO_FILE", pf)
        return date

    def _patch_telegram(self, monkeypatch, send_return=True, enabled=True):
        mock_notifier = MagicMock()
        mock_notifier.enabled = enabled
        mock_notifier.send.return_value = send_return
        mock_cls = MagicMock()
        mock_cls.from_env.return_value = mock_notifier
        monkeypatch.setattr(rv, "TelegramNotifier", mock_cls)
        return mock_notifier

    def test_okx_fails_after_3_retries_returns_0_with_degraded_report(self, tmp_path, monkeypatch):
        """OKX 全部重试失败：返回 0（不再是 1），报告标 degraded"""
        self._setup_files(tmp_path, monkeypatch, trades_csv_rows=[
            {"symbol": "BTCUSDTSWAP", "pnl": "5.0"},
        ])
        # OKXClient 构造后所有调用都失败
        def boom(mode, timeout):
            mock_client = MagicMock()
            mock_client.account.get_positions.side_effect = ConnectionError("proxy reset")
            return mock_client
        monkeypatch.setattr(rv, "OKXClient", boom)
        mock_notifier = self._patch_telegram(monkeypatch, send_return=True)

        rc = rv.run()
        # v2: degraded 模式仍返回 0
        assert rc == 0
        # 仍调 Telegram 推送（degraded 报告）
        assert mock_notifier.send.call_count == 1
        sent = mock_notifier.send.call_args[0][0]
        assert "degraded" in sent
        assert "1 笔" in sent  # CSV 数据仍保留
        assert "平仓 +5.0000 USDT" in sent

    def test_okx_non_network_error_not_retried(self, tmp_path, monkeypatch):
        """OKX 业务错误（非网络类）不重试，直接降级"""
        self._setup_files(tmp_path, monkeypatch, trades_csv_rows=[])
        def boom(mode, timeout):
            mock_client = MagicMock()
            # ValueError 不在 retry_on 列表里 → 只调用 1 次
            mock_client.account.get_positions.side_effect = ValueError("bad param")
            return mock_client
        monkeypatch.setattr(rv, "OKXClient", boom)
        mock_notifier = self._patch_telegram(monkeypatch, send_return=True)

        rc = rv.run()
        assert rc == 0
        sent = mock_notifier.send.call_args[0][0]
        assert "degraded" in sent

    def test_okx_recovers_on_third_attempt(self, tmp_path, monkeypatch):
        """前 2 次失败，第 3 次成功 → 正常报告（非 degraded）"""
        self._setup_files(tmp_path, monkeypatch, trades_csv_rows=[])
        call_count = [0]
        def okx_factory(mode, timeout):
            mock_client = MagicMock()
            def maybe_fail(*args, **kwargs):  # 接受 inst_type 等 kwargs
                call_count[0] += 1
                if call_count[0] < 3:
                    raise ConnectionError(f"attempt {call_count[0]}")
                return []  # 成功 → 返回空仓 list（不是 tuple）
            mock_client.account.get_positions.side_effect = maybe_fail
            return mock_client
        monkeypatch.setattr(rv, "OKXClient", okx_factory)
        mock_notifier = self._patch_telegram(monkeypatch, send_return=True)

        rc = rv.run()
        assert rc == 0
        sent = mock_notifier.send.call_args[0][0]
        assert "degraded" not in sent  # 第 3 次成功，不标 degraded
        assert call_count[0] == 3  # 重试了 3 次

# ────────────────────────────────────────────────────────────────────
# write_log —— 时间戳 + 内容
# ────────────────────────────────────────────────────────────────────

class TestWriteLog:
    def test_appends_with_cst_timestamp(self, tmp_path, monkeypatch):
        log = tmp_path / "daily_review.log"
        monkeypatch.setattr(rv, "LOG_FILE", log)
        rv.write_log("test message")
        content = log.read_text(encoding="utf-8")
        assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} CST\]", content)
        assert "test message" in content

    def test_multiple_appends_accumulate(self, tmp_path, monkeypatch):
        log = tmp_path / "daily_review.log"
        monkeypatch.setattr(rv, "LOG_FILE", log)
        rv.write_log("first")
        rv.write_log("second")
        content = log.read_text(encoding="utf-8")
        assert content.count("first") == 1
        assert content.count("second") == 1

# ────────────────────────────────────────────────────────────────────
# get_today_shanghai_date —— 日期格式
# ────────────────────────────────────────────────────────────────────

class TestGetTodayShanghaiDate:
    def test_format(self):
        date = rv.get_today_shanghai_date()
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", date), f"格式错误: {date!r}"

# ────────────────────────────────────────────────────────────────────
# main 端到端
# ────────────────────────────────────────────────────────────────────

class TestMain:
    def _setup_files(self, tmp_path, monkeypatch, trades_csv_rows=None, date=None):
        """写 trades CSV + 设置路径"""
        date = date or rv.get_today_shanghai_date()
        trades_dir = tmp_path / "trades"
        if trades_csv_rows is not None:
            write_trades_csv(trades_dir / f"{date}.csv", trades_csv_rows)
        monkeypatch.setattr(rv, "TRADES_DIR", trades_dir)
        monkeypatch.setattr(rv, "LOG_FILE", tmp_path / "daily_review.log")
        monkeypatch.setattr(rv, "ENV_FILE", tmp_path / ".env")
        return date

    def _patch_okx(self, monkeypatch, positions):
        mock_client = MagicMock()
        mock_client.account.get_positions.return_value = positions
        monkeypatch.setattr(rv, "OKXClient", lambda mode, timeout: mock_client)

    def _patch_telegram(self, monkeypatch, send_return=True, enabled=True):
        mock_notifier = MagicMock()
        mock_notifier.enabled = enabled
        mock_notifier.send.return_value = send_return
        mock_cls = MagicMock()
        mock_cls.from_env.return_value = mock_notifier
        monkeypatch.setattr(rv, "TelegramNotifier", mock_cls)
        return mock_notifier

    def test_main_no_trades_with_position(self, tmp_path, monkeypatch):
        """今日无 closed + 有 1 持仓"""
        self._setup_files(tmp_path, monkeypatch, trades_csv_rows=[])
        self._patch_okx(monkeypatch, [{
            "instId": "BTC-USDT-SWAP", "posSide": "short", "pos": "0.15",
            "avgPx": "64225", "upl": "1.5", "margin": "32.15",
        }])
        mock_notifier = self._patch_telegram(monkeypatch, send_return=True)

        rc = rv.run()
        assert rc == 0
        mock_notifier.send.assert_called_once()
        sent = mock_notifier.send.call_args[0][0]
        assert "0 笔" in sent
        assert "+0.0000 USDT" in sent
        assert "持仓未实现 +1.5000 USDT" in sent
        assert "BTC-USDT-SWAP" in sent

    def test_main_with_trades_with_position(self, tmp_path, monkeypatch):
        """今日有 closed + 有 1 持仓"""
        self._setup_files(tmp_path, monkeypatch, trades_csv_rows=[
            {"symbol": "ETHUSDTSWAP", "pnl": "5.0"},
            {"symbol": "BTCUSDTSWAP", "pnl": "-1.0"},
        ])
        self._patch_okx(monkeypatch, [{
            "instId": "BTC-USDT-SWAP", "posSide": "short", "pos": "0.15",
            "avgPx": "64225", "upl": "2.0", "margin": "32.15",
        }])
        mock_notifier = self._patch_telegram(monkeypatch, send_return=True)

        rc = rv.run()
        assert rc == 0
        sent = mock_notifier.send.call_args[0][0]
        assert "2 笔" in sent
        assert "平仓 +4.0000 USDT" in sent  # 5 + (-1)
        assert "持仓未实现 +2.0000 USDT" in sent
        # v2: 最大单笔移到 §3 策略归因（需 portfolio.json），本测试只测 CSV 路径
        assert "1/2 (50.0%)" in sent

    def test_main_okx_failure_uses_degraded_mode_v2(self, tmp_path, monkeypatch):
        """v2 行为变更：OKX 全失败不再 return 1，改为 degraded 模式 + return 0"""
        self._setup_files(tmp_path, monkeypatch, trades_csv_rows=[])
        def boom(mode, timeout):
            mock_client = MagicMock()
            mock_client.account.get_positions.side_effect = ConnectionError("API timeout")
            return mock_client
        monkeypatch.setattr(rv, "OKXClient", boom)
        mock_notifier = self._patch_telegram(monkeypatch, send_return=True)

        rc = rv.run()
        # v2 行为：返回 0，degraded 报告仍推送
        assert rc == 0
        assert mock_notifier.send.call_count == 1
        sent = mock_notifier.send.call_args[0][0]
        assert "degraded" in sent
        assert "OKX API" in sent  # 显式说明原因

    def test_main_returns_1_when_telegram_fails(self, tmp_path, monkeypatch):
        self._setup_files(tmp_path, monkeypatch, trades_csv_rows=[])
        self._patch_okx(monkeypatch, [])
        mock_notifier = self._patch_telegram(monkeypatch, send_return=False)

        rc = rv.run()
        assert rc == 1

    def test_run_with_specific_date(self, tmp_path, monkeypatch):
        """run(date='...') 直接传日期"""
        self._setup_files(
            tmp_path, monkeypatch,
            trades_csv_rows=[{"symbol": "BTCUSDTSWAP", "pnl": "-3.99"}],
            date="2026-07-15",
        )
        self._patch_okx(monkeypatch, [])
        mock_notifier = self._patch_telegram(monkeypatch, send_return=True)

        rc = rv.run("2026-07-15")
        assert rc == 0
        sent = mock_notifier.send.call_args[0][0]
        assert "1 笔" in sent
        assert "平仓 -3.9900 USDT" in sent

    def test_main_parses_argv(self, tmp_path, monkeypatch):
        """main(argv=['--date', '...']) 走 argparse 路径"""
        self._setup_files(
            tmp_path, monkeypatch,
            trades_csv_rows=[{"symbol": "BTCUSDTSWAP", "pnl": "-3.99"}],
            date="2026-07-15",
        )
        self._patch_okx(monkeypatch, [])
        mock_notifier = self._patch_telegram(monkeypatch, send_return=True)

        rc = rv.main(["--date", "2026-07-15"])
        assert rc == 0
        sent = mock_notifier.send.call_args[0][0]
        assert "1 笔" in sent