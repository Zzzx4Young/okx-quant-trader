#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX Runner Watchdog v2 — 仓位风险监控 + 进程健康守护

Layer 1: 进程健康（保留 v1.7 行为，向后兼容）
    • heartbeat_freshness    last_workflow_result.json > 15min → critical
    • consecutive_losses     daily_stats.consecutive_losses >= 3 → critical
    • emergency_stop         双源：portfolio + last_workflow → critical
    • api_errors             runner.log 5xx > 10/h → warning

Layer 2-4: 仓位风险监控（v2 新增）
    • 6 个核心指标 + 8 个阈值检查
    • 调用 OKX API 拉实时持仓
    • API 失败时 → degraded 模式（仅保留 Layer 1）

Layer 5: 报告 + 告警
    • 健康：详细仪表板（包含 dashboard + 时间戳）
    • 异常：仪表板 + issue 列表 + Telegram 推送

执行：./run.sh scripts/runner_watchdog.py
选项：
  --dry-run     只打印不发 Telegram
  --verbose     打印每个检查项的中间值
  --no-risk     跳过 Layer 2-4（仅进程健康）
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 让脚本能被直接调用（python3 okx/scripts/xxx.py），无需依赖 run.sh 注入 PYTHONPATH
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # scripts/ → okx/ → workspace/
sys.path.insert(0, str(PROJECT_ROOT))

# ──────────── .env 加载（与 v1.7 一致：setdefault 保留外部 env 优先级） ────────────


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


# ──────────── 工具函数 ────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(s: str) -> Optional[datetime]:
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _tail_file(path: Path, n_lines: int = 200) -> str:
    """高效 tail（最后 16KB）"""
    if not path.exists():
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block_size = min(size, 16384)
            f.seek(max(0, size - block_size))
            data = f.read().decode("utf-8", errors="replace")
        return "\n".join(data.splitlines()[-n_lines:])
    except Exception:
        return ""


# ──────────── Layer 1: 进程健康检查 ────────────


def check_heartbeat_freshness(state_dir: Path, max_age_min: int = 15) -> Optional[Dict[str, Any]]:
    """检查 last_workflow_result.json 时间戳新鲜度"""
    last = _load_json(state_dir / "last_workflow_result.json")
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
    last_ts = _parse_ts(ts_str)
    if not last_ts:
        return {
            "level": "critical",
            "check": "heartbeat",
            "message": f"时间戳解析失败: {ts_str}",
        }
    age_min = (_now_utc() - last_ts).total_seconds() / 60
    if age_min > max_age_min:
        return {
            "level": "critical",
            "check": "heartbeat",
            "message": f"Runner 已 {age_min:.0f} 分钟未运行（上次: {ts_str}）",
        }
    return None


def check_consecutive_losses(state_dir: Path, threshold: int = 3) -> Optional[Dict[str, Any]]:
    """检查连续亏损"""
    portfolio = _load_json(state_dir / "portfolio.json")
    if not portfolio:
        return None
    consec = portfolio.get("daily_stats", {}).get("consecutive_losses", 0)
    if consec >= threshold:
        return {
            "level": "critical",
            "check": "consecutive_losses",
            "message": f"连续亏损 {consec} 次（阈值 {threshold}），交易系统自动暂停",
        }
    return None


def check_emergency_stop(state_dir: Path) -> Optional[Dict[str, Any]]:
    """检查熔断触发（双源）"""
    portfolio = _load_json(state_dir / "portfolio.json")
    if portfolio:
        daily = portfolio.get("daily_stats", {})
        if daily.get("emergency_stop_triggered", False):
            return {
                "level": "critical",
                "check": "emergency_stop",
                "message": "紧急熔断已触发（portfolio），需人工介入恢复",
            }
    last = _load_json(state_dir / "last_workflow_result.json")
    if last:
        slots = last.get("steps", {}).get("8_slots", {})
        if slots.get("emergency_stop"):
            return {
                "level": "critical",
                "check": "emergency_stop",
                "message": f"熔断已触发（workflow）: {slots.get('reason', '?')}",
            }
    return None


def check_api_errors(logs_dir: Path, window_min: int = 60) -> Optional[Dict[str, Any]]:
    """检查 OKX 5xx 错误码频次"""
    log_path = logs_dir / "runner.log"
    if not log_path.exists():
        return None
    text = _tail_file(log_path, 200)
    if not text:
        return None
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


def run_layer1_checks(workspace_root: Path) -> List[Dict[str, Any]]:
    """运行 Layer 1 进程健康检查"""
    state_dir = workspace_root / "okx" / "state"
    logs_dir = workspace_root / "okx" / "logs"

    issues = []
    checks = [
        ("heartbeat", lambda: check_heartbeat_freshness(state_dir, max_age_min=15)),
        ("consecutive_losses", lambda: check_consecutive_losses(state_dir, threshold=3)),
        ("emergency_stop", lambda: check_emergency_stop(state_dir)),
        ("api_errors", lambda: check_api_errors(logs_dir, window_min=60)),
    ]
    for name, check in checks:
        try:
            issue = check()
            if issue:
                issues.append(issue)
        except Exception as e:
            issues.append({
                "level": "warning",
                "check": f"layer1_internal_error",
                "message": f"检查 {name} 执行失败: {e}",
            })
    return issues


# ──────────── OKX 客户端构造 ────────────


def _build_okx_client(workspace_root: Path, env_path: Path) -> Tuple[Optional[Any], str]:
    """构造 OKXClient，返回 (client, mode)

    mode 由环境变量 OKX_TRADING_MODE 决定（live / demo）
    OKXClient 内部自动从 env vars 读取凭据（HTTPClient 处理）
    """
    mode = os.getenv("OKX_TRADING_MODE", "demo").lower()
    try:
        # 延迟 import，避免硬依赖
        from okx.code import OKXClient
        client = OKXClient(mode=mode, timeout=10)
        return client, mode
    except Exception as e:
        logger.warning(f"构造 OKXClient 失败: {e}")
        return None, mode


# ──────────── 主流程 ────────────


logger = logging.getLogger(__name__)


def run_risk_monitor(
    workspace_root: Path,
    skip_risk: bool = False,
) -> Tuple[Optional[Any], List[Any]]:
    """运行 Layer 2-4，返回 (RiskMetrics 或 None, issues 列表)

    返回空 metrics 时表示 API 失败或跳过风险监控。
    """
    if skip_risk:
        return None, []

    # 延迟 import 避免路径问题
    from okx.scripts.risk_monitor import fetch_snapshot, compute_metrics, check_thresholds

    env_path = workspace_root / "okx" / ".env"
    client, mode = _build_okx_client(workspace_root, env_path)
    if client is None:
        logger.warning("OKX 客户端构造失败，跳过 Layer 2-4")
        return None, [{
            "check": "risk_monitor_skipped",
            "level": "warning",
            "message": "OKX 客户端构造失败，仅保留进程健康检查",
        }]

    portfolio_path = workspace_root / "okx" / "state" / "portfolio.json"
    positions, equity, api_status = fetch_snapshot(client, portfolio_path)
    metrics = compute_metrics(positions, equity, api_status=api_status)
    risk_issues = check_thresholds(metrics)

    return metrics, risk_issues


def send_telegram_alert(
    notifier: Any,
    all_issues: List[Any],
    metrics: Optional[Any],
    mode: str,
) -> bool:
    """按 level 分流：critical 发 Telegram，warning 仅日志"""
    if not all_issues:
        return False  # 健康不打扰

    # 兼容两种 issue 格式（dict 和 dataclass）
    def _get_issue(it: Any, k: str, default: Any = "") -> Any:
        if isinstance(it, dict):
            return it.get(k, default)
        return getattr(it, k, default)

    critical = [i for i in all_issues if _get_issue(i, "level") == "critical"]
    warning = [i for i in all_issues if _get_issue(i, "level") == "warning"]
    structural = [i for i in all_issues if _get_issue(i, "level") == "structural"]

    # structural (集中度等结构性失衡) → 只写日志不发 Telegram (防告警噪声)
    # structural issue 仍会写入 watchdog.log + critical.log fallback, 仅抑制 Telegram
    if structural:
        logger.info(
            f"结构性告警 ({len(structural)}) 被抑制发 Telegram, 仅日志: "
            + ", ".join(f"{_get_issue(i, 'check')}:{_get_issue(i, 'level')}" for i in structural)
        )

    if not critical:
        return False  # 仅 warning / structural → 仅日志

    # 用 risk_monitor 的格式化函数（如果有 metrics）
    if metrics is not None:
        from okx.scripts.risk_monitor import format_telegram_alert
        # 把 dict 转换成类似 RiskIssue 的命名元组（format_telegram_alert 期望 dataclass）
        from okx.scripts.risk_thresholds import RiskIssue
        converted = []
        for it in all_issues:
            if isinstance(it, dict):
                converted.append(RiskIssue(
                    check=it.get("check", ""),
                    level=it.get("level", "warning"),
                    message=it.get("message", ""),
                ))
            else:
                converted.append(it)
        text = format_telegram_alert(converted, metrics, mode)
    else:
        # Layer 1 only fallback
        lines = [f"🚨 <b>OKX Runner Watchdog 告警</b>（{mode.upper()}）", ""]
        for it in critical:
            lines.append(f"❌ <b>{_get_issue(it, 'check')}</b>: {_get_issue(it, 'message')}")
        if warning:
            lines.append("")
            lines.append("<b>⚠️ 警告</b>")
            for it in warning[:5]:
                lines.append(f"  • {_get_issue(it, 'check')}: {_get_issue(it, 'message')}")
        lines.append("")
        lines.append(f"⏰ {_now_utc().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        text = "\n".join(lines)

    # ──────────────────────────────────────────────────────────
    # 5.3 本地 fallback log（Telegram 挂了也不丢 critical）
    # — 总是先写盘，即使 Telegram send 完美也会是 source-of-truth
    # — 22:41 SSL EOF 教训：仅 Telegram 单点交付不安全
    # ──────────────────────────────────────────────────────────
    # 5.3 fallback log 路径推导：parents[1] 指向 okx/根（parents[2] 是 workspace）
    fallback_path = None
    if "workspace_root" in dir() and workspace_root is not None:
        fallback_path = workspace_root / "okx" / "state" / "alerts" / "critical.log"
    if fallback_path is None:
        fallback_path = (Path(__file__).resolve().parents[1] / "state" / "alerts" / "critical.log")
    try:
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        with open(fallback_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {_now_utc().isoformat()} mode={mode} ===\n")
            f.write(text)
            f.write("\n")
    except Exception as e:
        logger.warning(f"fallback log 写入失败: {e}")

    # dedup_key：同 issue 内容 5 分钟不重复发
    dedup_key = "|".join(f"{_get_issue(i, 'check')}:{_get_issue(i, 'message')}" for i in critical)
    try:
        return notifier.notify_error(text, dedup_key=dedup_key)
    except Exception as e:
        # Telegram 挂了 → fallback log 已经在上面已写
        logger.warning(f"Telegram 发送异常（fallback log 已存盘）: {e}")
        return False


def write_log(
    log_path: Path,
    report_text: str,
    all_issues: List[Any],
) -> None:
    """写 watchdog 日志（追加）"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(report_text)
        f.write("\n")


def _build_layer1_section(layer1_issues: List[Dict[str, Any]], mode: str) -> str:
    """构建 Layer 1 issues 报告片段（如果有）。

    v1.8.3 修复：之前此逻辑嵌入在 main() 内部闭包，无法被复用 / 测试。
    提取为模块级函数便于单测 + 跨 watchdog 流程复用。

    :param layer1_issues: Layer 1 检查出的 issue dict 列表（每项含 level/check/message）
    :param mode: 交易模式（live / demo）
    :return: 格式化的报告片段；无 issues 返回 ""
    """
    if not layer1_issues:
        return ""
    ts = _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")
    critical_count = sum(1 for i in layer1_issues if i.get("level") == "critical")
    warn_count = len(layer1_issues) - critical_count
    if critical_count:
        status = f"🚨 异常（{critical_count} critical / {warn_count} warning）"
    else:
        status = f"⚠️  注意（{warn_count} warning）"
    lines = [f"[{ts}] {status} | 模式: {mode}（Layer 1: 进程健康）"]
    for it in layer1_issues:
        level = it.get("level", "?")
        check = it.get("check", "?")
        msg = it.get("message", "?")
        icon = "❌" if level == "critical" else "⚠️ "
        lines.append(f"  {icon} [{level.upper()}] {check}: {msg}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="OKX Runner Watchdog v2 — 仓位风险监控")
    parser.add_argument("--dry-run", action="store_true", help="只检查不发 Telegram")
    parser.add_argument("--verbose", action="store_true", help="打印详细检查过程")
    parser.add_argument("--no-risk", action="store_true", help="跳过 Layer 2-4 仓位风险监控")
    args = parser.parse_args()

    # 配置 logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # 加载 .env
    script_path = Path(__file__).resolve()
    workspace_root = script_path.parent.parent.parent  # scripts/ → okx/ → workspace/
    env_path = workspace_root / "okx" / ".env"
    _load_env(env_path)

    if args.verbose:
        logger.debug(f"workspace_root: {workspace_root}")
        logger.debug(f"OKX_TRADING_MODE: {os.getenv('OKX_TRADING_MODE', 'demo')}")

    # ── Layer 1: 进程健康 ──
    layer1_issues = run_layer1_checks(workspace_root)
    if args.verbose:
        logger.debug(f"Layer 1: 发现 {len(layer1_issues)} 个问题")
        for it in layer1_issues:
            logger.debug(f"  - [{it['level']}] {it['check']}: {it['message']}")

    # ── Layer 2-4: 仓位风险监控 ──
    metrics, risk_issues = run_risk_monitor(workspace_root, skip_risk=args.no_risk)
    if args.verbose:
        logger.debug(f"Layer 2-4: 发现 {len(risk_issues)} 个问题")
        if metrics:
            logger.debug(f"  metrics: gross_lev={metrics.gross_leverage:.2f}x upl_pct={metrics.upl_pct:.2%} positions={metrics.position_count}")
        for it in risk_issues:
            # 兼容 dict 和 dataclass
            lvl = it.get("level") if isinstance(it, dict) else getattr(it, "level", "?")
            chk = it.get("check") if isinstance(it, dict) else getattr(it, "check", "?")
            msg = it.get("message") if isinstance(it, dict) else getattr(it, "message", "?")
            logger.debug(f"  - [{lvl}] {chk}: {msg}")

    # ── 合并所有 issues ──
    all_issues = layer1_issues + risk_issues

    # ── Layer 5: 生成报告 ──
    mode = os.getenv("OKX_TRADING_MODE", "demo").lower()

    # ⚠️ v1.8.3 修复：之前 format_report 只接 risk_issues (Layer 2-4)，Layer 1 critical issues
    # (如 heartbeat stale / emergency_stop / consecutive_losses) 会被丢夫。
    # 结果：script 输出 "✓ 健康" + Telegram 不告警，但 Runner 实际已停摆 N 分钟。
    # 修复：永远拼接 Layer 1 issues 到报告前面, 独立判断 critical/warning。

    layer1_section = _build_layer1_section(layer1_issues, mode)

    if metrics is not None and not args.no_risk:
        from okx.scripts.risk_monitor import format_report
        layer24_text = format_report(metrics, risk_issues, mode=mode, include_dashboard=True)
        # 拼接：Layer 1 critical 在前, Layer 2-4 dashboard 在后
        report_text = (layer1_section + "\n\n" + layer24_text) if layer1_section else layer24_text
    else:
        # 仅 Layer 1 (Layer 2-4 metrics 不可用)
        if layer1_section:
            report_text = layer1_section
        else:
            ts = _now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")
            report_text = f"[{ts}] ✓ 健康（仅 Layer 1, 无 Layer 2-4） | 模式: {mode}"

    # ── 输出 + 写日志 ──
    print(report_text)
    log_path = workspace_root / "okx" / "logs" / "watchdog.log"
    write_log(log_path, report_text, all_issues)

    # ── Telegram 告警 ──
    if args.dry_run:
        print(f"[dry-run] {'有' if all_issues else '无'}问题，跳过 Telegram 发送")
        return 0

    # 构造 notifier（仅 critical 发送）
    try:
        from okx.code.notifier import TelegramNotifier
        notifier = TelegramNotifier.from_env(str(env_path))
        if not notifier.enabled and all_issues:
            print(f"[watchdog] ⚠️  Notifier 未启用，问题已写日志但未发送 Telegram")
            return 1

        sent = send_telegram_alert(notifier, all_issues, metrics, mode)
        if all_issues:
            if sent:
                print(f"[watchdog] ✓ Telegram 告警已发送")
            else:
                print(f"[watchdog] ⚠️  仅警告，已写日志")
        # 健康时静默（不打印，避免和 cron sub-session 输出打架）
        return 0
    except Exception as e:
        logger.exception(f"发送告警失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
