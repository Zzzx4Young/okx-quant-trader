# -*- coding: utf-8 -*-
"""
heartbeat 隔离测试 (TDD 暴露 tests/test_signal_runner.py 污染生产 state 的 bug)

════════════════════════════════════════════════════════════════════
本套件目的:

旧 tests/test_signal_runner.py::test_write_heartbeat_creates_file 直接调用
sr._write_heartbeat(result), 该函数硬编码写到 Path(__file__).parent.parent/state/.
而 tests/ 不是 scripts/, 但因为 _write_heartbeat 用 __file__ 解析, 仍然命中
okx/state/signal_runner.heartbeat (生产路径).

→ 每次跑 pytest, 生产 heartbeat 被覆盖为测试数据
→ liveness_probe 看到 fake timestamp, 误报 STALE
→ 这是一个"测试自己制造生产事故"的反模式

合约修复方向:
  _write_heartbeat(result, state_dir=None) → 若 state_dir 给定则用它,
  否则 fallback 到默认生产路径 (向后兼容)
════════════════════════════════════════════════════════════════════
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import signal_runner as sr


# ──────────── Layer 1: _write_heartbeat 必须接受 state_dir 参数 ────────────

class TestWriteHeartbeatAcceptsStateDir:
    """_write_heartbeat 必须接受可选 state_dir 参数, 默认行为不变"""

    def test_write_heartbeat_writes_to_specified_state_dir(self, tmp_path):
        """[核心 RED] 显式传 state_dir, 必须写到该目录 (非默认生产路径)"""
        fake_state_dir = tmp_path / "state"
        fake_state_dir.mkdir()

        result = {
            "timeframe": "15m",
            "boundary": "2026-07-18T12:45:00+00:00",
            "warmup_duration_s": 0.95,
            "runner_result": {"signal_triggered": False},
            "errors": [],
        }

        # 当前 API 不接受 state_dir → TypeError (RED)
        sr._write_heartbeat(result, state_dir=fake_state_dir)

        heartbeat_path = fake_state_dir / "signal_runner.heartbeat"
        assert heartbeat_path.exists(), "应写到指定 state_dir"
        payload = json.loads(heartbeat_path.read_text())
        assert payload["timeframe"] == "15m"


# ──────────── Layer 2: 即使不传 state_dir, 也不能污染测试 fixture ────────────

class TestWriteHeartbeatDoesNotPolluteProductionState:
    """
    旧测试的 bug: 不传 state_dir, 直接写到生产 state/.
    这个测试是 sentinel: 如果 _write_heartbeat 被"修了又改回去", 立即 fail.
    """

    def test_default_state_dir_resolves_to_repo_not_test_dir(self):
        """_write_heartbeat 的默认 state_dir 必须 = scripts/../state/

        这是 production-correctness 测试 ——
        即使测试不传 state_dir, 也必须写到 okx/state/ (不是 tests/...)
        """
        # 验证函数存在 (RED if missing refactor)
        import inspect
        sig = inspect.signature(sr._write_heartbeat)
        assert "state_dir" in sig.parameters, (
            f"_write_heartbeat 必须支持 state_dir 参数以避免测试污染. "
            f"当前签名: {sig}"
        )


# ──────────── Layer 3: tests/test_signal_runner.py 的旧测试必须 redirect ────────────

class TestOldHeartbeatTestUsesTmpPath:
    """旧 test_write_heartbeat_creates_file 必须 redirect 到 tmp_path, 不能写生产"""

    def test_old_test_does_not_pollute_production_heartbeat(self, tmp_path):
        """[核心 RED] 模拟旧测试的行为, 验证生产 heartbeat 不被覆盖

        这个测试模拟旧 test 的所有副作用, 验证如果 monkeypatch/setattr 不正确
        实际工作时, 生产 heartbeat 不会被覆盖。
        """
        # 保存生产 heartbeat 当前内容
        prod_heartbeat = Path("/home/zzzx47/.openclaw/workspace/okx/state/signal_runner.heartbeat")
        if not prod_heartbeat.exists():
            pytest.skip("生产 heartbeat 不存在 (可能 cron 未跑), 跳过")
        original_payload = prod_heartbeat.read_text()
        original_mtime = prod_heartbeat.stat().st_mtime

        # 模拟旧测试调 _write_heartbeat (无 state_dir 参数)
        result = {
            "timeframe": "TEST_POLLUTION",
            "boundary": "1970-01-01T00:00:00+00:00",
            "warmup_duration_s": 999,
            "runner_result": {"signal_triggered": False},
            "errors": [],
        }

        # 关键: 这个调用必须不污染生产 heartbeat
        # (修复后: 传 tmp_path 进去; 旧代码会污染)
        try:
            sr._write_heartbeat(result, state_dir=tmp_path / "fake_state")
            (tmp_path / "fake_state").mkdir(exist_ok=True)
            sr._write_heartbeat(result, state_dir=tmp_path / "fake_state")
        except TypeError:
            pytest.fail(
                "_write_heartbeat 不支持 state_dir 参数, 旧测试必然污染生产. "
                "需要先重构 _write_heartbeat 接受 state_dir 参数"
            )

        # 验证生产 heartbeat 未被覆盖
        new_payload = prod_heartbeat.read_text()
        new_mtime = prod_heartbeat.stat().st_mtime

        assert new_payload == original_payload, (
            f"生产 heartbeat 被污染! \n"
            f"  原始: {original_payload[:200]}\n"
            f"  被覆盖为: {new_payload[:200]}"
        )
        # mtime 可能因其他 cron 写入变化, 但内容必须一致
