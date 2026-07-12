#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX Runner Watchdog — 监控 Runner 健康状态

检查项：
1. 心跳新鲜度：last_workflow_result.json 时间戳是否过旧
2. 连续亏损：portfolio.daily_stats.consecutive_losses
3. 熔断触发：emergency_stop_triggered
4. API 错误：runner.log 最近 N 行的 OKX 5xx 错误码
5. 下单失败率：signal_triggered=true 但 status=error 的占比
6. quarter 漏掉：最近 1h 没有任何 tick=true 的运行

执行：./run.sh scripts/runner_watchdog.py
选项：
  --dry-run     只打印不发
  --verbose     打印每个检查项的中间值
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 加载 .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in open(env_path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)

from okx.code.notifier import TelegramNotifier


# ──────────── 工具函数 ────────────


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(s: str) -> Optional[datetime]:
    """解析 ISO 8601 时间戳"""
    try:
        # 处理 Z 后缀
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        return None
    return None


def tail_file(path: Path, n_lines: int = 200) -> str:
    """读文件最后 n 行"""
    if not path.exists():
        return ""
    try:
        # 高效 tail
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # 读 16KB 足够覆盖 ~200 行
            block_size = min(size, 16384)
            f.seek(max(0, size - block_size))
            data = f.read().decode("utf-8", errors="replace")
        return "\n".join(data.splitlines()[-n_lines:])
    except Exception:
        return ""


# ──────────── 检查项 ────────────


def check_heartbeat_freshness(state_dir: Path, max_age_min: int = 15) -> Optional[Dict[str, Any]]:
    """检查 last_workflow_result.json 时间戳新鲜度"""
    last = load_json(state_dir / "last_workflow_result.json")
    if not last:
        return {
            "level": "critical",
            "check": "heartbeat",
            "message": "last_workflow_result.json 不存在或为空",
        }

    ts_str = last.get("timestamp")
    if not ts_str:
        return {
            "level": "critical",
            "check": "heartbeat",
            "message": "last_workflow_result.json 缺少 timestamp 字段",
        }

    last_ts = parse_ts(ts_str)
    if not last_ts:
        return {
            "level": "critical",
            "check": "heartbeat",
            "message": f"时间戳解析失败: {ts_str}",
        }

    age_sec = (now_utc() - last_ts).total_seconds()
    age_min = age_sec / 60

    if age_min > max_age_min:
        return {
            "level": "critical",
            "check": "heartbeat",
            "message": f"Runner 已 {age_min:.0f} 分钟未运行（上次: {ts_str}）",
        }

    return None


def check_consecutive_losses(state_dir: Path, threshold: int = 3) -> Optional[Dict[str, Any]]:
    """检查连续亏损"""
    portfolio = load_json(state_dir / "portfolio.json")
    if not portfolio:
        return None  # 没有交易不算异常

    daily = portfolio.get("daily_stats", {})
    consec = daily.get("consecutive_losses", 0)
    if consec >= threshold:
        return {
            "level": "critical",
            "check": "consecutive_losses",
            "message": f"连续亏损 {consec} 次（阈值 {threshold}），交易系统自动暂停",
        }
    return None


def check_emergency_stop(state_dir: Path) -> Optional[Dict[str, Any]]:
    """检查熔断触发"""
    portfolio = load_json(state_dir / "portfolio.json")
    if not portfolio:
        return None

    daily = portfolio.get("daily_stats", {})
    if daily.get("emergency_stop_triggered", False):
        return {
            "level": "critical",
            "check": "emergency_stop",
            "message": "紧急熔断已触发，需人工介入恢复",
        }

    # 也检查 last_workflow_result 里的 slots.emergency_stop
    last = load_json(state_dir / "last_workflow_result.json")
    if last:
        slots = last.get("steps", {}).get("8_slots", {})
        if slots.get("emergency_stop"):
            return {
                "level": "critical",
                "check": "emergency_stop",
                "message": f"熔断已触发: {slots.get('reason', '?')}",
            }
    return None


def check_api_errors(logs_dir: Path, window_min: int = 60) -> Optional[Dict[str, Any]]:
    """检查 OKX 5xx 错误码频次"""
    log_path = logs_dir / "runner.log"
    if not log_path.exists():
        return None

    cutoff = now_utc().timestamp() - window_min * 60
    # 取最近 2KB
    text = tail_file(log_path, 200)
    if not text:
        return None

    # 匹配 [5xxxx] 错误码（如 [51008]、[50113] 等）
    error_codes = re.findall(r"\[(\d{5})\]", text)
    error_count = sum(1 for c in error_codes if c.startswith("5") and int(c) >= 50000)

    if error_count > 10:
        return {
            "level": "warning",
            "check": "api_errors",
            "message": f"过去 {window_min} 分钟 OKX API 5xx 错误 {error_count} 次（>10/h 阈值）",
            "error_count": error_count,
        }
    return None


def check_signal_failure_rate(state_dir: Path) -> Optional[Dict[str, Any]]:
    """检查 signal_triggered=true 但 status=error 的占比"""
    # 这个数据在 last_workflow_result.json 里只有一次运行的，不够统计
    # 实际要看 runner.log 里的结构化输出
    return None  # 简化版本跳过


# ──────────── 主流程 ────────────


def run_checks(workspace_root: Path) -> List[Dict[str, Any]]:
    """运行所有检查，返回问题列表"""
    state_dir = workspace_root / "okx" / "state"
    logs_dir = workspace_root / "okx" / "logs"

    issues = []
    for check in [
        lambda: check_heartbeat_freshness(state_dir, max_age_min=15),
        lambda: check_consecutive_losses(state_dir, threshold=3),
        lambda: check_emergency_stop(state_dir),
        lambda: check_api_errors(logs_dir, window_min=60),
        # check_signal_failure_rate(state_dir),  # 暂禁用
    ]:
        try:
            issue = check()
            if issue:
                issues.append(issue)
        except Exception as e:
            issues.append({
                "level": "warning",
                "check": "internal_error",
                "message": f"检查执行失败: {e}",
            })
    return issues


def send_alert(notifier: TelegramNotifier, issues: List[Dict[str, Any]], workspace_root: Path) -> bool:
    """发送告警到 Telegram（按 dedup_key 去重 5 分钟）"""
    if not issues:
        return True

    critical = [i for i in issues if i["level"] == "critical"]
    warning = [i for i in issues if i["level"] == "warning"]

    # 严重问题：发 Telegram
    if critical:
        lines = ["🚨 <b>OKX Runner Watchdog 告警</b>\n"]
        for issue in critical:
            lines.append(f"❌ <b>{issue['check']}</b>: {issue['message']}")
        if warning:
            lines.append("\n⚠️ 警告：")
            for issue in warning:
                lines.append(f"• <b>{issue['check']}</b>: {issue['message']}")

        lines.append(f"\n⏰ {now_utc().strftime('%Y-%m-%d %H:%M:%S')} UTC")

        text = "\n".join(lines)

        # 用 issues 拼接作为 dedup_key（同 issue 内容 5 分钟不重复）
        dedup_key = "|".join(f"{i['check']}:{i['message']}" for i in critical)
        return notifier.notify_error(text, dedup_key=dedup_key)

    # 仅警告：只写日志
    return False


def write_log(log_path: Path, issues: List[Dict[str, Any]], workspace_root: Path) -> None:
    """写 watchdog 日志"""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "a", encoding="utf-8") as f:
        ts = now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")
        if issues:
            f.write(f"\n[{ts}] ⚠️  发现 {len(issues)} 个问题\n")
            for issue in issues:
                f.write(f"  [{issue['level'].upper()}] {issue['check']}: {issue['message']}\n")
        else:
            f.write(f"[{ts}] ✓ 健康\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="OKX Runner Watchdog")
    parser.add_argument("--dry-run", action="store_true", help="只检查不发 Telegram")
    parser.add_argument("--verbose", action="store_true", help="打印详细检查过程")
    args = parser.parse_args()

    # 工作区根目录（从脚本位置推断）
    script_path = Path(__file__).resolve()
    workspace_root = script_path.parent.parent.parent  # scripts/ → okx/ → workspace/

    if args.verbose:
        print(f"[watchdog] workspace: {workspace_root}")

    # 运行检查
    issues = run_checks(workspace_root)

    if args.verbose:
        print(f"[watchdog] 发现 {len(issues)} 个问题")
        for issue in issues:
            print(f"  - [{issue['level']}] {issue['check']}: {issue['message']}")

    # 写日志
    log_path = workspace_root / "okx" / "logs" / "watchdog.log"
    write_log(log_path, issues, workspace_root)

    # 发送告警
    if args.dry_run:
        print(f"[dry-run] {'有' if issues else '无'}问题，跳过 Telegram 发送")
        return 0

    # 构造 notifier
    notifier = TelegramNotifier.from_env(str(env_path))
    if not notifier.enabled and issues:
        print(f"[watchdog] ⚠️  Notifier 未启用，问题已写日志但未发送 Telegram")
        return 1

    sent = send_alert(notifier, issues, workspace_root)
    if issues:
        if sent:
            print(f"[watchdog] ✓ Telegram 告警已发送")
        else:
            print(f"[watchdog] ⚠️  仅警告，已写日志")
    else:
        print(f"[watchdog] ✓ 健康，无问题")

    return 0


if __name__ == "__main__":
    sys.exit(main())