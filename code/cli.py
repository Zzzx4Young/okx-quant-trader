#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX 交易系统 CLI 入口（唯一命令行入口）

用法::

    python -m okx.code.cli status
    python -m okx.code.cli run
    python -m okx.code.cli stop
    python -m okx.code.cli resume
    python -m okx.code.cli close-all
    python -m okx.code.cli summary

或通过 run.sh::

    ./run.sh status
"""

import argparse
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ──────────── 心跳 / 状态 ────────────

def get_system_status() -> Dict[str, Any]:
    """获取系统当前状态"""
    try:
        from .config import get_config
        from .portfolio import Portfolio

        config = get_config()
        portfolio = Portfolio()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "emergency_stop": config.emergency_stop,
            "demo_mode": config.demo_mode,
            "position_count": portfolio.position_count(),
            "max_positions": config.max_concurrent_positions,
            "daily_stats": portfolio.get_daily_stats(),
            "meltdown": portfolio.is_meltdown(config.daily_max_loss_trades),
            "config_ok": True,
        }
    except Exception as e:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "config_ok": False,
        }


def run_heartbeat_check() -> str:
    """Heartbeat 进入时执行的轻量状态检查（输出人读字符串）"""
    status = get_system_status()

    if not status.get("config_ok"):
        return f"⚠️ 系统初始化失败: {status.get('error', 'Unknown')}"

    lines = [
        f"🕐 {status['timestamp']}",
        f"📊 持仓: {status['position_count']}/{status['max_positions']}",
    ]

    if status.get("emergency_stop"):
        lines.append("🚨 EMERGENCY_STOP 已激活，禁止新开仓")

    if status.get("meltdown"):
        lines.append("🔴 连续亏损熔断中，禁止新开仓")

    daily = status.get("daily_stats", {})
    if daily:
        lines.append(
            f"📈 今日: 交易 {daily.get('total_trades', 0)} 笔 | "
            f"亏损 {daily.get('loss_trades', 0)} 笔 | "
            f"净盈亏 {daily.get('total_pnl', 0):.4f} USDT"
        )

    return " | ".join(lines)


# ──────────── 交易周期 ────────────

def run_trading_cycle() -> Dict[str, Any]:
    """完整交易周期（先用 Runner 平已有持仓，再检测新信号）

    同时将结果持久化到 state/last_workflow_result.json，供 watchdog 监控。
    """
    from pathlib import Path

    result: Dict[str, Any]
    try:
        from .runner import Runner

        runner = Runner()
        close_results = runner.check_and_close_positions()
        open_results = runner.run()

        result = {
            "success": True,
            "close_results": close_results,
            "open_results": open_results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # 持久化 last_workflow_result.json（watchdog 依赖这个判断 freshness）
    try:
        state_dir = Path(__file__).resolve().parent.parent / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        last_path = state_dir / "last_workflow_result.json"
        with open(last_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        # 不要因为写文件失败影响主流程
        sys.stderr.write(f"⚠️  写入 last_workflow_result.json 失败: {e}\n")

    return result


# ──────────── 人工干预 ────────────

def toggle_emergency_stop(enable: bool, config_path: Optional[str] = None) -> Dict[str, Any]:
    """开启/关闭紧急熔断"""
    try:
        if config_path:
            from .config import Config
            config = Config(config_path)
        else:
            from .config import get_config
            config = get_config()

        config.emergency_stop = enable

        return {
            "success": True,
            "emergency_stop": enable,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def close_all_positions(emergency: bool = True) -> Dict[str, Any]:
    """一键平所有持仓（紧急模式自动开启熔断）"""
    try:
        from .portfolio import Portfolio
        from .runner import Runner

        portfolio = Portfolio()
        positions = portfolio.get_all_positions()

        if not positions:
            return {
                "success": True,
                "message": "无持仓，无需平仓",
                "closed": [],
            }

        runner = Runner()
        closed = []
        for pos in positions:
            result = runner._close_position(
                position=pos,
                current_price=0.0,
                reason="人工一键平仓" if emergency else "人工平仓",
            )
            closed.append(result)

        if emergency:
            from .config import get_config
            get_config().emergency_stop = True

        return {
            "success": True,
            "closed": closed,
            "total_closed": len(closed),
            "emergency_stop_set": emergency,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_portfolio_summary() -> Dict[str, Any]:
    """当前组合摘要"""
    try:
        from .portfolio import Portfolio
        from .logger import TradeLogger

        portfolio = Portfolio()
        logger = TradeLogger()

        return {
            "success": True,
            "portfolio": portfolio.get_positions_summary(),
            "daily_summary": logger.get_daily_summary(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ──────────── CLI 入口 ────────────

_ACTIONS = ["status", "close-all", "stop", "resume", "run", "summary"]


def main() -> None:
    parser = argparse.ArgumentParser(description="OKX 交易系统 CLI")
    parser.add_argument("action", choices=_ACTIONS, help="运维动作")
    args = parser.parse_args()

    if args.action == "status":
        print(run_heartbeat_check())
    elif args.action == "run":
        print(json.dumps(run_trading_cycle(), indent=2, ensure_ascii=False))
    elif args.action == "stop":
        print(json.dumps(toggle_emergency_stop(True), indent=2, ensure_ascii=False))
    elif args.action == "resume":
        print(json.dumps(toggle_emergency_stop(False), indent=2, ensure_ascii=False))
    elif args.action == "close-all":
        print(json.dumps(close_all_positions(emergency=True), indent=2, ensure_ascii=False))
    elif args.action == "summary":
        print(json.dumps(get_portfolio_summary(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()