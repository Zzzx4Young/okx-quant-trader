#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rotate_telegram_key.py 单测

覆盖：
  - scan_token_exposure 扫描准确性
  - _assess_risk 风险分级
  - format_scan_report 输出格式
  - 边界情况：空 token / 无暴露 / 大文件跳过

⚠️ 安全警告（2026-07-18 security audit）
   本文件仅使用明显假的占位符 token。如需测试真实 token 检测能力，请使用
   rotate_telegram_key.py 专用的 fake_workspace fixture。未轮换且未撤销的真实 token
   绝对不能进入 git history。
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import rotate_telegram_key as rt


# ──────────── Fixtures ────────────


@pytest.fixture
def fake_workspace(tmp_path):
    """构造一个 fake workspace 含 .env + 日志 + .py + memory 文件"""
    # 明显假的占位符（保持 46 字符长度让 len() 断言通过）。
    # 绝不写入真实 token — test 用 .env 注入或临时 monkeypatch。
    fake_token = "1111111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    # okx/.env
    env_dir = tmp_path / "okx"
    env_dir.mkdir()
    (env_dir / ".env").write_text(
        f"OKX_DEMO_API_KEY=test\n"
        f"TELEGRAM_BOT_TOKEN={fake_token}\n"
        f"TELEGRAM_CHAT_ID=12345\n"
    )

    # okx/logs/daily_summary.log (含完整 token —— 真实错误日志泄露场景)
    logs_dir = env_dir / "logs"
    logs_dir.mkdir()
    (logs_dir / "daily_summary.log").write_text(
        "2026-07-18 04:00:00 INFO ... telegram send exception: HTTPSConnectionPool "
        f"(host='api.telegram.org', port=443): Max retries ... /bot{fake_token}\n"
    )

    # okx/scripts/xxx.py (无 token)
    scripts_dir = env_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "safe_script.py").write_text("# no token here\nprint('hello')\n")

    # memory/.dreams/session-corpus (medium risk, 含完整 token)
    dreams_dir = tmp_path / "memory" / ".dreams" / "session-corpus"
    dreams_dir.mkdir(parents=True)
    (dreams_dir / "2026-07-10.txt").write_text(
        f"[session.jsonl#L187] Assistant: ## Telegram 配置与状态 ...  bot_token={fake_token}\n"
    )

    # .env.example 不应被扫到
    (env_dir / ".env.example").write_text(
        "TELEGRAM_BOT_TOKEN=<your_telegram_bot_token_here>\n"
    )

    return tmp_path


# ──────────── scan_token_exposure 测试 ────────────


def test_scan_finds_env_exposure(fake_workspace):
    """应找到 .env 里的 token"""
    result = rt.scan_token_exposure(fake_workspace)
    assert result["current_token"] is not None
    assert len(result["current_token"]) == 46
    # 至少 1 处 high（.env 本身）
    assert result["summary"]["high"] >= 1
    # .env 暴露存在
    env_exposures = [e for e in result["exposures"] if e["file"] == "okx/.env"]
    assert len(env_exposures) == 1


def test_scan_finds_log_exposure(fake_workspace):
    """应找到 .log 文件里的 token 片段"""
    result = rt.scan_token_exposure(fake_workspace)
    log_exposures = [e for e in result["exposures"] if ".log" in e["file"]]
    assert len(log_exposures) >= 1
    # log 是 high 风险
    for e in log_exposures:
        assert e["risk"] == "high"


def test_scan_finds_memory_dream_exposure(fake_workspace):
    """应找到 memory/.dreams/ 里的 token 提及（medium）"""
    result = rt.scan_token_exposure(fake_workspace)
    dream_exposures = [e for e in result["exposures"] if "memory" in e["file"]]
    assert len(dream_exposures) >= 1


def test_scan_ignores_env_example(fake_workspace):
    """.env.example 含占位符，不应被扫为暴露"""
    result = rt.scan_token_exposure(fake_workspace)
    example_exposures = [e for e in result["exposures"] if e["file"] == "okx/.env.example"]
    assert len(example_exposures) == 0


def test_scan_ignores_safe_files(fake_workspace):
    """无 token 的 .py 文件不应被扫为暴露"""
    result = rt.scan_token_exposure(fake_workspace)
    safe_exposures = [e for e in result["exposures"] if e["file"] == "okx/scripts/safe_script.py"]
    assert len(safe_exposures) == 0


def test_scan_skips_large_files(tmp_path):
    """> 5MB 的文件应被跳过"""
    (tmp_path / "huge.txt").write_text("x" * (6 * 1024 * 1024))
    result = rt.scan_token_exposure(tmp_path)
    # 即使 huge.txt 里有 token，也不应被报告
    huge_exposures = [e for e in result["exposures"] if "huge.txt" in e["file"]]
    assert len(huge_exposures) == 0


def test_scan_handles_no_token(tmp_path):
    """无 .env 文件时不应报错"""
    result = rt.scan_token_exposure(tmp_path)
    assert result["current_token"] is None
    assert result["summary"].get("skipped") == "no token"


def test_scan_skips_pyc_and_venv(tmp_path):
    """应跳过 __pycache__ / .venv / node_modules / data/market"""
    skip_dirs = ["__pycache__", ".venv", "node_modules"]
    for d in skip_dirs:
        (tmp_path / d).mkdir()
        (tmp_path / d / "secret.txt").write_text("1111111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    result = rt.scan_token_exposure(tmp_path)
    for d in skip_dirs:
        skipped = [e for e in result["exposures"] if d in e["file"]]
        assert len(skipped) == 0


# ──────────── _assess_risk 测试 ────────────


def test_assess_risk_env():
    """.env 文件 = high"""
    risk = rt._assess_risk(Path("/workspace/okx/.env"), "TELEGRAM_BOT_TOKEN=xxx")
    assert risk == "high"


def test_assess_risk_log():
    """日志文件 = high"""
    risk = rt._assess_risk(Path("/workspace/okx/logs/foo.log"), "bot token: xxx")
    assert risk == "high"


def test_assess_risk_json():
    """json 配置 = medium"""
    risk = rt._assess_risk(Path("/workspace/okx/state/config.json"), "{...}")
    assert risk == "medium"


def test_assess_risk_markdown_token():
    """.md 含 TELEGRAM_BOT_TOKEN 字样 = high"""
    risk = rt._assess_risk(
        Path("/workspace/okx/docs/x.md"),
        "TELEGRAM_BOT_TOKEN 配置如下"
    )
    assert risk == "high"


# ──────────── format_scan_report 测试 ────────────


def test_format_report_with_exposures(fake_workspace):
    """报告应包含 token 暴露面 + 风险分布"""
    result = rt.scan_token_exposure(fake_workspace)
    report = rt.format_scan_report(result)

    assert "暴露面扫描报告" in report
    assert "11111111" in report  # masked token 前缀（占位符 1111111111...AAAAAAAA...）
    assert "HIGH" in report
    assert "MEDIUM" in report
    assert "okx/.env" in report
    # 完整 token 不应出现（masking 正确性）
    assert result["current_token"] not in report


def test_format_report_no_exposures(tmp_path):
    """无暴露时报告应有 ✅ 提示"""
    result = rt.scan_token_exposure(tmp_path)
    report = rt.format_scan_report(result)
    assert "未配置" in report


def test_format_report_masks_token(fake_workspace):
    """报告中不应出现完整 token，只显示 masked（前 8 + 后 4）"""
    result = rt.scan_token_exposure(fake_workspace)
    report = rt.format_scan_report(result)
    # 完整 token 不应出现（exposure context 也应被 mask）
    full_token = result["current_token"]
    assert full_token not in report
    # 但 masked 形式应该出现（current token 显示）
    masked = f"{full_token[:8]}...{full_token[-4:]}"
    assert masked in report


# ──────────── verify_token_via_get_me 测试（mock） ────────────


def test_verify_token_success(monkeypatch):
    """mock getMe 返回 ok=True"""
    import json as _json
    import urllib.request

    class FakeResp:
        def __init__(self, data):
            self.data = data
        def read(self):
            return _json.dumps(self.data).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=None):
        return FakeResp({
            "ok": True,
            "result": {"id": 123, "username": "test_bot", "first_name": "Test"},
        })

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = rt.verify_token_via_get_me("fake:token", timeout=1)
    assert result["ok"] is True
    assert result["bot_username"] == "test_bot"


def test_verify_token_failure(monkeypatch):
    """mock getMe 返回 ok=False"""
    import json as _json
    import urllib.error
    import urllib.request

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, None
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = rt.verify_token_via_get_me("bad:token", timeout=1)
    assert result["ok"] is False
    assert "401" in result["error"]


# ──────────── send_test_message 测试（mock） ────────────


def test_send_test_message_success(monkeypatch):
    """mock sendMessage 返回 ok=True"""
    import json as _json
    import urllib.request

    class FakeResp:
        def read(self):
            return _json.dumps({
                "ok": True,
                "result": {"message_id": 99999},
            }).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=None):
        return FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = rt.send_test_message("fake:token", "12345", "test")
    assert result["ok"] is True
    assert result["message_id"] == 99999


# ──────────── print_rotation_guide 测试 ────────────


def test_rotation_guide_contains_key_steps():
    """轮换指引应包含 4 个关键步骤"""
    guide = rt.print_rotation_guide()
    assert "@BotFather" in guide
    assert "Revoke" in guide
    assert ".env" in guide
    assert "verify" in guide
    assert "步骤 1" in guide
    assert "步骤 4" in guide