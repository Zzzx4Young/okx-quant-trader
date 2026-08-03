# -*- coding: utf-8 -*-
"""
L4 Shadow Runner · Live Signal Logging 测试 (D5)

设计意图：live runner 每次产生 signal 应 append 到 state/live_signals.jsonl (atomic)。
Shadow runner 从这个文件读 "actual signal" 与 backtest "expected signal" 对比。

RED: 假设 okx.code.runner._log_signal 已实现。当前不存在 → fail。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest


def make_signal_data(**overrides) -> dict:
    """构造 Signal.to_dict() 风格的 dict（用于 jsonl 测试）。"""
    base = {
        "strategy": "EMA20_BREAKOUT",
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "entry_price": 50000.0,
        "sl_price": 49500.0,
        "tp_price": 51000.0,
        "leverage": 3,
        "size": 0.0,
        "confidence": 0.7,
        "reason": "test",
        "kline_time": "2026-08-03T12:00:00Z",
    }
    base.update(overrides)
    return base


class TestLiveSignalLogging:
    """okx.code.runner._log_signal 测试。"""

    def test_log_signal_appends_to_jsonl(self, tmp_path, monkeypatch):
        """_log_signal 应 append 一行 JSON 到 state/live_signals.jsonl。"""
        from okx.code.runner import _log_signal
        from okx.code.signal import Signal

        # 用 tmp_path 作为 state dir 避免污染真实 state
        monkeypatch.setattr("okx.code.runner.STATE_DIR", tmp_path)

        sig = Signal(**make_signal_data())
        _log_signal(sig)

        log_path = tmp_path / "live_signals.jsonl"
        assert log_path.exists()

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["direction"] == "long"
        assert parsed["strategy"] == "EMA20_BREAKOUT"
        assert parsed["entry_price"] == 50000.0

    def test_log_signal_handles_multiple_signals(self, tmp_path, monkeypatch):
        """连续多次 _log_signal 应累积成多行（每行 1 signal）。"""
        from okx.code.runner import _log_signal
        from okx.code.signal import Signal

        monkeypatch.setattr("okx.code.runner.STATE_DIR", tmp_path)

        for i in range(3):
            sig = Signal(**make_signal_data(kline_time=f"2026-08-03T1{i}:00:00Z"))
            _log_signal(sig)

        log_path = tmp_path / "live_signals.jsonl"
        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

    def test_log_signal_creates_dir_if_missing(self, tmp_path, monkeypatch):
        """STATE_DIR 不存在时应自动创建（避免冷启动 fail-open）。"""
        from okx.code.runner import _log_signal
        from okx.code.signal import Signal

        nested_dir = tmp_path / "deep" / "nested" / "state"
        monkeypatch.setattr("okx.code.runner.STATE_DIR", nested_dir)

        sig = Signal(**make_signal_data())
        _log_signal(sig)

        assert nested_dir.exists()
        assert (nested_dir / "live_signals.jsonl").exists()


class TestLiveSignalReader:
    """shadow runner 读取 last live signal 的 helper 测试。"""

    def test_load_last_live_signal_returns_most_recent(self, tmp_path, monkeypatch):
        """load_last_live_signal 应返回最后一行（最新 signal）。"""
        # Implement helper in shadow package
        from okx.code.shadow.live_runner import load_last_live_signal

        monkeypatch.setattr("okx.code.shadow.live_runner.STATE_DIR", tmp_path)

        log_path = tmp_path / "live_signals.jsonl"
        log_path.write_text(
            "\n".join([
                json.dumps(make_signal_data(direction="long", kline_time="2026-08-03T10:00:00Z")),
                json.dumps(make_signal_data(direction="short", kline_time="2026-08-03T11:00:00Z")),
                json.dumps(make_signal_data(direction="long", kline_time="2026-08-03T12:00:00Z")),
            ]) + "\n",
            encoding="utf-8",
        )

        sig = load_last_live_signal()
        assert sig is not None
        assert sig.kline_time == "2026-08-03T12:00:00Z"
        assert sig.direction == "long"

    def test_atomic_write_text_helper_exists(self):
        """scripts/run_live_shadow.py 应暴露 atomic write helper."""
        import importlib
        mod = importlib.import_module("okx.scripts.run_live_shadow")
        assert hasattr(mod, "atomic_write_text"), (
            "scripts/run_live_shadow.py 应有 atomic_write_text helper"
        )

    def test_atomic_write_text_writes_valid_json(self, tmp_path):
        """atomic_write_text 写出的文件应是 valid JSON（不被 partial write 损坏）."""
        from okx.scripts.run_live_shadow import atomic_write_text

        target = tmp_path / "test.json"
        content = '''{"key": "value", "nested": {"a": 1}}'''

        atomic_write_text(target, content)

        # 文件存在且内容完整
        assert target.exists()
        read_back = target.read_text(encoding="utf-8")
        assert read_back == content

        # 可被 json.loads parse
        import json as _json
        parsed = _json.loads(read_back)
        assert parsed["key"] == "value"
    def test_load_last_live_signal_returns_none_if_empty(self, tmp_path, monkeypatch):
            """日志文件不存在 → 返回 None（acceptable · live runner 还没跑过）."""
            from okx.code.shadow.live_runner import load_last_live_signal

            monkeypatch.setattr("okx.code.shadow.live_runner.STATE_DIR", tmp_path)

            sig = load_last_live_signal()
            assert sig is None


class TestAtomicWrite:
    """P1 · Risk #4 · atomic write pattern (per MEMORY/OKX.md portfolio atomic pattern)."""

    def test_atomic_write_text_helper_exists(self):
        """scripts/run_live_shadow.py 应暴露 atomic write helper."""
        import importlib
        mod = importlib.import_module("okx.scripts.run_live_shadow")
        assert hasattr(mod, "atomic_write_text"), (
            "scripts/run_live_shadow.py 应有 atomic_write_text helper"
        )

    def test_atomic_write_text_writes_valid_json(self, tmp_path):
        """atomic_write_text 写出的文件应是 valid JSON（不被 partial write 损坏）."""
        from okx.scripts.run_live_shadow import atomic_write_text

        target = tmp_path / "test.json"
        content = '''{"key": "value", "nested": {"a": 1}}'''

        atomic_write_text(target, content)

        assert target.exists()
        read_back = target.read_text(encoding="utf-8")
        assert read_back == content

        import json as _json
        parsed = _json.loads(read_back)
        assert parsed["key"] == "value"
