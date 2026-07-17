# -*- coding: utf-8 -*-
"""
test_heartbeat_push.py —— heartbeat_push.py 单测

只依赖 pytest 内置 fixture（monkeypatch），不依赖 pytest-mock。

覆盖：
- compose_message: 5 行 Markdown 格式（数字格式化、符号、边界）
- get_daily_stats: portfolio.json 读取 + 异常 fallback
- get_status_and_max: 状态判定优先级 + max_concurrent_positions
- write_log: 时间戳 + 内容
- get_positions_summary: 标为 @slow（需要 OKX 真实 API + 凭据）
- main: 端到端流程（mock OKX + Telegram）

跑法:
  pytest okx/tests/test_heartbeat_push.py -v
  bash okx/run.sh pytest okx/tests/test_heartbeat_push.py -v -m slow   # 含真 OKX API
"""
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

from okx.scripts import heartbeat_push as hb


# ────────────────────────────────────────────────────────────────────
# compose_message —— 纯函数，全覆盖
# ────────────────────────────────────────────────────────────────────

class TestComposeMessage:
    """v2: 5 段结构（§1 系统状态 / §2 集中度 / §3 工作流 / §4 风控 / §5 持仓）"""

    # 兼容 v1 字段（必须保留以匹配旧测试的语义）
    def _kwargs(self):
        return dict(
            n_held=1, n_max=5, n_trades=3, daily_pnl=12.3456,
            total_upl=-0.1225, status="active",
            daily_stats_full={}, workflow_ts="2026-07-18 00:00 UTC",
            workflow_age_min=10, inst_pct=0.5, inst_name="BTC-USDT-SWAP",
            strat_pct=0.5, strat_name="EXTERNAL_WEB_SYNC",
        )

    def test_active_normal_5_sections(self):
        msg = hb.compose_message(**self._kwargs())
        # 5 段标题都在
        for s in ["1. 系统状态", "2. 集中度", "3. 工作流新鲜度",
                  "4. 风控标记", "5. 持仓明细"]:
            assert s in msg, f"缺段: {s}"
        # §1 baseline 字段（兼容 v1）
        assert "持仓 1/5" in msg
        assert "今日 3 笔" in msg
        assert "今日已平仓 +12.3456 USDT" in msg
        assert "持仓未实现 -0.1225 USDT" in msg
        assert "状态 active" in msg

    def test_zero_values(self):
        msg = hb.compose_message(
            n_held=0, n_max=5, n_trades=0, daily_pnl=0.0,
            total_upl=0.0, status="active",
            daily_stats_full={}, workflow_ts="N/A", workflow_age_min=-1,
            inst_pct=0.0, inst_name="", strat_pct=0.0, strat_name="",
        )
        assert "+0.0000 USDT" in msg
        assert "持仓 0/5" in msg
        assert "无持仓" in msg  # §2 / §5

    def test_negative_upl(self):
        msg = hb.compose_message(
            n_held=1, n_max=5, n_trades=0, daily_pnl=0.0,
            total_upl=-3.99, status="active",
            daily_stats_full={}, workflow_ts="2026-07-18 00:00 UTC",
            workflow_age_min=10, inst_pct=1.0, inst_name="BTC-USDT-SWAP",
            strat_pct=1.0, strat_name="EXTERNAL_WEB_SYNC",
        )
        assert "-3.9900 USDT" in msg

    def test_degraded_marker(self):
        """OKX 失败时头部加 degraded 标识"""
        msg = hb.compose_message(
            n_held=0, n_max=5, n_trades=0, daily_pnl=0.0,
            total_upl=0.0, status="active",
            daily_stats_full={}, workflow_ts="N/A", workflow_age_min=-1,
            inst_pct=0.0, inst_name="", strat_pct=0.0, strat_name="",
            okx_degraded=True,
        )
        assert "degraded" in msg
        assert "OKX API 不可用" in msg  # §2 标注

    def test_workflow_stale_warning(self):
        """workflow > 15min 应标 stale"""
        msg = hb.compose_message(
            n_held=0, n_max=5, n_trades=0, daily_pnl=0.0,
            total_upl=0.0, status="active",
            daily_stats_full={}, workflow_ts="2026-07-17 22:00 UTC",
            workflow_age_min=120,
            inst_pct=0.0, inst_name="", strat_pct=0.0, strat_name="",
        )
        assert "⚠️ 距今 120 分钟" in msg

    def test_risk_flags_visible(self):
        """连续亏损 + 紧急熔断显示对应图标"""
        msg = hb.compose_message(
            n_held=1, n_max=5, n_trades=2, daily_pnl=-8.0,
            total_upl=1.0, status="emergency_stop",
            daily_stats_full={"consecutive_losses": 5, "emergency_stop_triggered": True},
            workflow_ts="2026-07-18 00:00 UTC", workflow_age_min=5,
            inst_pct=1.0, inst_name="BTC-USDT-SWAP",
            strat_pct=1.0, strat_name="EXTERNAL_WEB_SYNC",
        )
        assert "连续亏损: 5 次" in msg
        assert "紧急熔断: 已触发" in msg
        assert "状态 emergency_stop" in msg

    def test_paused_status(self):
        msg = hb.compose_message(
            n_held=0, n_max=5, n_trades=0, daily_pnl=0.0,
            total_upl=0.0, status="paused",
            daily_stats_full={}, workflow_ts="2026-07-18 00:00 UTC",
            workflow_age_min=10, inst_pct=0.0, inst_name="",
            strat_pct=0.0, strat_name="",
        )
        assert "状态 paused" in msg

    def test_emergency_stop_status(self):
        msg = hb.compose_message(
            n_held=0, n_max=5, n_trades=0, daily_pnl=0.0,
            total_upl=0.0, status="emergency_stop",
            daily_stats_full={"emergency_stop_triggered": True, "consecutive_losses": 3},
            workflow_ts="2026-07-18 00:00 UTC", workflow_age_min=10,
            inst_pct=0.0, inst_name="", strat_pct=0.0, strat_name="",
        )
        assert "状态 emergency_stop" in msg
        assert "紧急熔断: 已触发" in msg

    def test_no_html_special_chars(self):
        msg = hb.compose_message(
            n_held=2, n_max=5, n_trades=1, daily_pnl=-99.99,
            total_upl=-50.00, status="active",
            daily_stats_full={}, workflow_ts="2026-07-18 00:00 UTC",
            workflow_age_min=10, inst_pct=0.5, inst_name="AAA-USDT-SWAP",
            strat_pct=0.5, strat_name="B_STRATEGY",
        )
        for ch in ["<", ">", "&"]:
            assert ch not in msg, f"消息含 HTML 字符 {ch!r}"

class TestGetDailyStats:
    """v2: get_daily_stats 返回 (n_trades, daily_pnl, full_dict) 3-tuple"""

    def test_normal(self, tmp_path, monkeypatch):
        pf = tmp_path / "portfolio.json"
        pf.write_text(json.dumps({
            "daily_stats": {
                "total_trades": 7,
                "total_pnl": -3.5,
                "consecutive_losses": 2,
                "emergency_stop_triggered": False,
            }
        }))
        monkeypatch.setattr(hb, "PORTFOLIO", pf)
        n, pnl, full = hb.get_daily_stats()
        assert n == 7
        assert pnl == -3.5
        assert full["consecutive_losses"] == 2

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hb, "PORTFOLIO", tmp_path / "nonexistent.json")
        n, pnl, full = hb.get_daily_stats()
        assert n == 0
        assert pnl == 0.0
        assert full == {}

    def test_corrupt_json(self, tmp_path, monkeypatch):
        pf = tmp_path / "portfolio.json"
        pf.write_text("{not valid json")
        monkeypatch.setattr(hb, "PORTFOLIO", pf)
        n, pnl, full = hb.get_daily_stats()
        assert n == 0
        assert pnl == 0.0
        assert full == {}

    def test_missing_daily_stats(self, tmp_path, monkeypatch):
        """portfolio.json 存在但没有 daily_stats 字段"""
        pf = tmp_path / "portfolio.json"
        pf.write_text(json.dumps({"positions": []}))
        monkeypatch.setattr(hb, "PORTFOLIO", pf)
        n, pnl, full = hb.get_daily_stats()
        assert n == 0
        assert pnl == 0.0
        assert full == {}


class TestGetStatusAndMax:
    def _patch_config(self, monkeypatch, max_pos=5):
        """把 hb.Config 替换为返回 mock_cfg 的 MagicMock"""
        mock_cfg = MagicMock()
        mock_cfg.max_concurrent_positions = max_pos
        mock_cls = MagicMock()
        mock_cls.from_env.return_value = mock_cfg
        monkeypatch.setattr(hb, "Config", mock_cls)

    def test_active_when_nothing_set(self, tmp_path, monkeypatch):
        self._patch_config(monkeypatch)
        monkeypatch.setattr(hb, "PORTFOLIO", tmp_path / "missing1.json")
        monkeypatch.setattr(hb, "WORKFLOW", tmp_path / "missing2.json")
        status, max_pos = hb.get_status_and_max()
        assert status == "active"
        assert max_pos == 5

    def test_emergency_stop_from_portfolio(self, tmp_path, monkeypatch):
        self._patch_config(monkeypatch)
        pf = tmp_path / "pf.json"
        pf.write_text(json.dumps({
            "daily_stats": {"emergency_stop_triggered": True}
        }))
        monkeypatch.setattr(hb, "PORTFOLIO", pf)
        monkeypatch.setattr(hb, "WORKFLOW", tmp_path / "missing.json")
        status, _ = hb.get_status_and_max()
        assert status == "emergency_stop"

    def test_paused_from_workflow(self, tmp_path, monkeypatch):
        self._patch_config(monkeypatch)
        monkeypatch.setattr(hb, "PORTFOLIO", tmp_path / "missing.json")
        wf = tmp_path / "wf.json"
        wf.write_text(json.dumps({"status": "paused"}))
        monkeypatch.setattr(hb, "WORKFLOW", wf)
        status, _ = hb.get_status_and_max()
        assert status == "paused"

    def test_emergency_takes_priority_over_paused(self, tmp_path, monkeypatch):
        """即使 workflow 是 paused，portfolio 的 emergency_stop 优先"""
        self._patch_config(monkeypatch)
        pf = tmp_path / "pf.json"
        pf.write_text(json.dumps({
            "daily_stats": {"emergency_stop_triggered": True}
        }))
        wf = tmp_path / "wf.json"
        wf.write_text(json.dumps({"status": "paused"}))
        monkeypatch.setattr(hb, "PORTFOLIO", pf)
        monkeypatch.setattr(hb, "WORKFLOW", wf)
        status, _ = hb.get_status_and_max()
        assert status == "emergency_stop"

    def test_stop_loss_not_treated_as_emergency(self, tmp_path, monkeypatch):
        """stop_loss 出现于 status 不应被当 emergency（避免误判）"""
        self._patch_config(monkeypatch)
        wf = tmp_path / "wf.json"
        wf.write_text(json.dumps({"status": "stop_loss_triggered"}))
        monkeypatch.setattr(hb, "PORTFOLIO", tmp_path / "missing.json")
        monkeypatch.setattr(hb, "WORKFLOW", wf)
        status, _ = hb.get_status_and_max()
        assert status == "active"

    def test_corrupt_workflow_falls_back_to_active(self, tmp_path, monkeypatch):
        self._patch_config(monkeypatch)
        wf = tmp_path / "wf.json"
        wf.write_text("{not json")
        monkeypatch.setattr(hb, "PORTFOLIO", tmp_path / "missing.json")
        monkeypatch.setattr(hb, "WORKFLOW", wf)
        status, _ = hb.get_status_and_max()
        assert status == "active"

    def test_max_from_config(self, tmp_path, monkeypatch):
        """max_concurrent_positions 从 Config 读（=7 表示 mock 注入成功）"""
        self._patch_config(monkeypatch, max_pos=7)
        monkeypatch.setattr(hb, "PORTFOLIO", tmp_path / "missing.json")
        monkeypatch.setattr(hb, "WORKFLOW", tmp_path / "missing.json")
        status, max_pos = hb.get_status_and_max()
        assert max_pos == 7


# ────────────────────────────────────────────────────────────────────
# write_log —— 时间戳 + 内容
# ────────────────────────────────────────────────────────────────────

class TestWriteLog:
    def test_appends_with_cst_timestamp(self, tmp_path, monkeypatch):
        log = tmp_path / "heartbeat.log"
        monkeypatch.setattr(hb, "LOG_FILE", log)
        hb.write_log("test message")
        content = log.read_text(encoding="utf-8")
        assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} CST\]", content)
        assert "test message" in content

    def test_multiple_appends_accumulate(self, tmp_path, monkeypatch):
        log = tmp_path / "heartbeat.log"
        monkeypatch.setattr(hb, "LOG_FILE", log)
        hb.write_log("first")
        hb.write_log("second")
        content = log.read_text(encoding="utf-8")
        assert "first" in content
        assert "second" in content
        assert content.count("\n\n") == 2

    def test_creates_parent_dirs(self, tmp_path, monkeypatch):
        log = tmp_path / "nested" / "dirs" / "heartbeat.log"
        monkeypatch.setattr(hb, "LOG_FILE", log)
        hb.write_log("nested")
        assert log.exists()


# ────────────────────────────────────────────────────────────────────
# get_positions_summary —— @slow，需要真 OKX API + 凭据
# ────────────────────────────────────────────────────────────────────

@pytest.mark.slow
@pytest.mark.skipif(
    not os.getenv("OKX_API_KEY"),
    reason="需要 OKX_API_KEY 环境变量（建议通过 bash okx/run.sh pytest 跑）",
)
class TestGetPositionsSummary:
    def test_returns_three_tuple(self):
        from okx.code import OKXClient
        client = OKXClient(mode=os.getenv("OKX_TRADING_MODE", "demo"), timeout=10)
        n, total_upl, positions = hb.get_positions_summary(client)
        assert isinstance(n, int)
        assert isinstance(total_upl, float)
        assert isinstance(positions, list)
        if positions:
            for p in positions:
                assert "upl" in p
                assert "instId" in p

    def test_total_upl_is_sum_of_positions(self):
        from okx.code import OKXClient
        client = OKXClient(mode=os.getenv("OKX_TRADING_MODE", "demo"), timeout=10)
        _, total_upl, positions = hb.get_positions_summary(client)
        expected = sum(float(p.get("upl", 0)) for p in positions)
        assert abs(total_upl - expected) < 1e-6


# ────────────────────────────────────────────────────────────────────
# main 端到端（用 monkeypatch 注入 mock OKXClient + TelegramNotifier）
# ────────────────────────────────────────────────────────────────────

class TestMain:
    def _setup_files(self, tmp_path, monkeypatch):
        pf = tmp_path / "portfolio.json"
        pf.write_text(json.dumps({
            "daily_stats": {"total_trades": 2, "total_pnl": -0.5, "emergency_stop_triggered": False}
        }))
        monkeypatch.setattr(hb, "PORTFOLIO", pf)
        monkeypatch.setattr(hb, "WORKFLOW", tmp_path / "missing_wf.json")
        monkeypatch.setattr(hb, "LOG_FILE", tmp_path / "heartbeat.log")
        monkeypatch.setattr(hb, "ENV_FILE", tmp_path / ".env")

    def _patch_config(self, monkeypatch, max_pos=5):
        mock_cfg = MagicMock()
        mock_cfg.max_concurrent_positions = max_pos
        mock_cls = MagicMock()
        mock_cls.from_env.return_value = mock_cfg
        monkeypatch.setattr(hb, "Config", mock_cls)

    def _patch_okx(self, monkeypatch, positions):
        mock_client = MagicMock()
        mock_client.account.get_positions.return_value = positions
        monkeypatch.setattr(hb, "OKXClient", lambda mode, timeout: mock_client)

    def _patch_telegram(self, monkeypatch, send_return=True, enabled=True):
        mock_notifier = MagicMock()
        mock_notifier.enabled = enabled
        mock_notifier.send.return_value = send_return
        mock_cls = MagicMock()
        mock_cls.from_env.return_value = mock_notifier
        monkeypatch.setattr(hb, "TelegramNotifier", mock_cls)
        return mock_notifier

    def test_main_pushes_telegram_and_returns_0(self, tmp_path, monkeypatch):
        self._patch_okx(monkeypatch, [
            {"instId": "BTC-USDT-SWAP", "posSide": "short", "upl": "1.5"},
        ])
        mock_notifier = self._patch_telegram(monkeypatch, send_return=True)
        self._patch_config(monkeypatch, max_pos=5)
        self._setup_files(tmp_path, monkeypatch)

        rc = hb.main()
        assert rc == 0
        mock_notifier.send.assert_called_once()
        sent_msg = mock_notifier.send.call_args[0][0]
        assert "持仓未实现 +1.5000 USDT" in sent_msg
        assert "今日已平仓 -0.5000 USDT" in sent_msg
        assert "状态 active" in sent_msg

    def test_main_okx_failure_uses_degraded_mode_v2(self, tmp_path, monkeypatch):
        """v2 行为变更：OKX 重试全失败不再 return 1，改为 degraded 模式 + return 0"""
        def boom(mode, timeout):
            mock_client = MagicMock()
            mock_client.account.get_positions.side_effect = ConnectionError("API timeout")
            return mock_client
        monkeypatch.setattr(hb, "OKXClient", boom)
        mock_notifier = self._patch_telegram(monkeypatch, send_return=True)
        self._patch_config(monkeypatch)
        self._setup_files(tmp_path, monkeypatch)

        rc = hb.main()
        # v2 行为：返回 0，degraded 报告仍推送
        assert rc == 0
        sent_msg = mock_notifier.send.call_args[0][0]
        assert "degraded" in sent_msg
        assert "OKX API 不可用" in sent_msg
        # 本地数据仍保留
        assert "今日已平仓 -0.5000 USDT" in sent_msg
        assert "状态 active" in sent_msg

    def test_main_returns_1_when_telegram_fails(self, tmp_path, monkeypatch):
        self._patch_okx(monkeypatch, [])
        mock_notifier = self._patch_telegram(monkeypatch, send_return=False)
        self._patch_config(monkeypatch)
        self._setup_files(tmp_path, monkeypatch)

        rc = hb.main()
        assert rc == 1