"""
Active Probe Chaos Test —— 心跳失联场景的离线验证

对应 v1.8.3+ candidate #7 的 P0.1 离线沙盒：
- 修改 state/last_workflow_result.json 的 timestamp，模拟 runner 失联
- 验证 runner_watchdog.check_heartbeat_freshness() 在 stale 状态下能否 1s 内返回 critical
- 验证返回的 issue 字段足以驱动 Telegram 模拟网关发出紧急报警

核心测试目标：
  1. heartbeat_freshness 在不同 stale 程度下的行为边界
  2. issue dict 结构完整（level/check/message）供 Telegram 报警使用
  3. 在 stale 600s 时能 < 1s 返回（性能回归）
  4. 多种 failure mode（file missing / timestamp missing / unparseable / 空 dict）

设计依据：
  - scripts/runner_watchdog.py:73-104 check_heartbeat_freshness() 实现
  - Layer 1 critical 经由 send_telegram_alert 发出 → critical.log fallback 路径
  - v1.8.3 P0 fix (c9d5ef2): Layer 1 critical 不再被 format_report 吞掉
"""
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# 延迟导入（脚本路径不在默认 PYTHONPATH，需动态加入）
import sys
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runner_watchdog import check_heartbeat_freshness  # noqa: E402


def _write_state(state_dir: Path, payload: dict | None) -> None:
    """写入 last_workflow_result.json；payload=None 时不创建文件"""
    state_dir.mkdir(parents=True, exist_ok=True)
    if payload is None:
        return
    (state_dir / "last_workflow_result.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _now_iso() -> str:
    """与 runner_watchdog._parse_ts 兼容的 UTC ISO 字符串"""
    return datetime.now(timezone.utc).isoformat()


def _now_minus(seconds: int) -> str:
    """N 秒前的 UTC ISO 字符串"""
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


# ─────────────────────────────────────────────────────────────
# 场景 A1: 文件不存在 → critical
# ─────────────────────────────────────────────────────────────
def test_heartbeat_missing_file_returns_critical(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()  # dir exists, but file doesn't

    issue = check_heartbeat_freshness(state_dir, max_age_min=15)

    assert issue is not None, "心跳文件缺失时应返回 issue"
    assert issue["level"] == "critical", f"心跳文件缺失必须 critical，实际 {issue['level']}"
    assert issue["check"] == "heartbeat"
    assert "不存在" in issue["message"] or "为空" in issue["message"]


# ─────────────────────────────────────────────────────────────
# 场景 A2: timestamp 字段缺失 → critical
# ─────────────────────────────────────────────────────────────
def test_heartbeat_missing_timestamp_field_returns_critical(tmp_path):
    state_dir = tmp_path / "state"
    _write_state(state_dir, {"success": True, "close_results": {"closed": []}})

    issue = check_heartbeat_freshness(state_dir, max_age_min=15)

    assert issue is not None
    assert issue["level"] == "critical"
    assert "timestamp" in issue["message"]


# ─────────────────────────────────────────────────────────────
# 场景 A3: timestamp 无法解析 → critical
# ─────────────────────────────────────────────────────────────
def test_heartbeat_unparseable_timestamp_returns_critical(tmp_path):
    state_dir = tmp_path / "state"
    _write_state(state_dir, {"timestamp": "not-a-real-iso-format-2026-13-99"})

    issue = check_heartbeat_freshness(state_dir, max_age_min=15)

    assert issue is not None
    assert issue["level"] == "critical"
    assert "解析失败" in issue["message"]


# ─────────────────────────────────────────────────────────────
# 场景 A4: timestamp 600s 前（> 15min 阈值）→ critical（核心场景）
# ─────────────────────────────────────────────────────────────
def test_heartbeat_20min_stale_returns_critical(tmp_path):
    """核心 chaos 场景：模拟 runner 失联 20 分钟（超出默认 15 min 阈值）

    注意：原文档 (无实盘非24H运行推进方案.md) 提到 600 秒，但默认
    max_age_min=15 时 600s=10min 实际 fresh，会漏报。chaos 测试必须
    用 > 15 min 的 stale 值才能真正触发 critical。
    """
    state_dir = tmp_path / "state"
    _write_state(state_dir, {"timestamp": _now_minus(20 * 60), "success": True})

    issue = check_heartbeat_freshness(state_dir, max_age_min=15)

    assert issue is not None, "stale 20min 应返回 critical"
    assert issue["level"] == "critical", f"stale 必须 critical，实际 {issue['level']}"
    assert issue["check"] == "heartbeat"
    # 消息应说明 stale 程度
    assert "分钟" in issue["message"], f"issue message 应说明 stale 程度: {issue['message']}"


# ─────────────────────────────────────────────────────────────
# 场景 A5: timestamp 在阈值内 → None（健康）
# ─────────────────────────────────────────────────────────────
def test_heartbeat_fresh_returns_none(tmp_path):
    """正常 heartbeat（60s 前）应视为健康，不返回 issue"""
    state_dir = tmp_path / "state"
    _write_state(state_dir, {"timestamp": _now_minus(60), "success": True})

    issue = check_heartbeat_freshness(state_dir, max_age_min=15)

    assert issue is None, f"fresh heartbeat 不应返回 issue，实际 {issue}"


# ─────────────────────────────────────────────────────────────
# 场景 A6: 边界——14min 仍 fresh，16min critical
# ─────────────────────────────────────────────────────────────
def test_heartbeat_boundary_at_max_age(tmp_path):
    """边界测试：max_age_min 阈值前/后行为差异"""
    state_dir = tmp_path / "state"
    max_age = 15

    # 14min < 15min，应为 None
    _write_state(state_dir, {"timestamp": _now_minus(14 * 60)})
    issue_fresh = check_heartbeat_freshness(state_dir, max_age_min=max_age)
    assert issue_fresh is None, f"14min 应 fresh，实际 {issue_fresh}"

    # 16min > 15min，应为 critical
    _write_state(state_dir, {"timestamp": _now_minus(16 * 60)})
    issue_stale = check_heartbeat_freshness(state_dir, max_age_min=max_age)
    assert issue_stale is not None, "16min 应 critical"
    assert issue_stale["level"] == "critical"


# ─────────────────────────────────────────────────────────────
# 场景 A7: 性能——stale 检测 < 1s
# ─────────────────────────────────────────────────────────────
def test_heartbeat_stale_detection_under_1s(tmp_path):
    """chaos 测试要求 stale 检测 < 1s，确保 cron 5min 周期内可快速失败"""
    state_dir = tmp_path / "state"
    _write_state(state_dir, {"timestamp": _now_minus(20 * 60)})  # 20 min stale

    start = time.perf_counter()
    issue = check_heartbeat_freshness(state_dir, max_age_min=15)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert issue is not None
    assert elapsed_ms < 1000, f"stale 检测耗时 {elapsed_ms:.1f}ms，超过 1s 阈值"


# ─────────────────────────────────────────────────────────────
# 场景 A8: 集成——issue dict 结构驱动 Telegram 模拟网关
# ─────────────────────────────────────────────────────────────
def test_heartbeat_issue_struct_compatible_with_telegram(tmp_path):
    """验证 issue dict 字段足够 send_telegram_alert 构造报警消息

    send_telegram_alert (runner_watchdog.py:222-251) 用 _get_issue(it, k) 读取
    level/check/message 字段；任一缺失会导致报警消息不完整
    """
    state_dir = tmp_path / "state"
    _write_state(state_dir, {"timestamp": _now_minus(20 * 60)})  # 20 min stale

    issue = check_heartbeat_freshness(state_dir, max_age_min=15)

    # 完整字段驱动 Telegram 报警
    for required_field in ["level", "check", "message"]:
        assert required_field in issue, f"issue 缺少 {required_field} 字段，Telegram 无法构造完整报警"
        assert issue[required_field], f"issue.{required_field} 不能为空"

    # level 必须是 critical（驱动 Telegram 分流，非 critical 只写日志）
    assert issue["level"] == "critical", \
        f"只有 critical 才会触发 Telegram，level={issue['level']} 时报警被吞"


# ─────────────────────────────────────────────────────────────
# 场景 A9: 多次连续检测——确认无状态泄漏
# ─────────────────────────────────────────────────────────────
def test_heartbeat_no_state_leakage(tmp_path):
    """连续 3 次检测同一 stale 文件，每次结果一致（无单例/全局状态污染）"""
    state_dir = tmp_path / "state"
    _write_state(state_dir, {"timestamp": _now_minus(20 * 60)})  # 20 min stale

    issues = [
        check_heartbeat_freshness(state_dir, max_age_min=15)
        for _ in range(3)
    ]

    assert all(i is not None for i in issues), "3 次检测都应返回 issue"
    assert all(i["level"] == "critical" for i in issues)
    assert all(i["check"] == "heartbeat" for i in issues)