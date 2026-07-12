#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日交易报告生成器

读取当日 logs/trades/YYYY-MM-DD.csv + portfolio.json，发送每日报告到 Telegram。

用法：
  ./run.sh scripts/daily_summary.py              # 今日报告
  ./run.sh scripts/daily_summary.py --date=2026-07-10  # 指定日期
  ./run.sh scripts/daily_summary.py --date=2026-07-10 --dry-run  # 不真发
  ./run.sh scripts/daily_summary.py --print       # 只打印不发

定时任务（cron 每天 UTC 15:00 = 北京 23:00）：
  0 15 * * * cd /path/to/workspace && bash okx/run.sh okx/scripts/daily_summary.py >> okx/logs/daily_summary.log 2>&1
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

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
from okx.code.logger import TradeLogger


def read_daily_trades(date_str: str) -> dict:
    """读取指定日期的 trade log，返回统计

    :param date_str: YYYY-MM-DD
    :return: 统计 dict
    """
    log_dir = Path(__file__).parent.parent / "logs" / "trades"
    path = log_dir / f"{date_str}.csv"
    if not path.exists():
        return {"date": date_str, "total_trades": 0, "opens": 0, "closes": 0,
                "pnl_gross": 0.0, "total_fee": 0.0, "pnl_net": 0.0}

    total_pnl = 0.0
    total_fee = 0.0
    total_pnl_net = 0.0
    opens = 0
    closes = 0
    wins = 0
    losses = 0
    by_strategy = defaultdict(int)

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            action = row.get("action")
            pnl_net = float(row.get("pnl_net", 0))
            fee = float(row.get("fee", 0))
            pnl = float(row.get("pnl", 0))

            total_fee += fee
            total_pnl_net += pnl_net
            total_pnl += pnl

            if action == "OPEN":
                opens += 1
                by_strategy[row.get("strategy", "?")] += 1
            elif action == "CLOSE":
                closes += 1
                if pnl_net > 0:
                    wins += 1
                elif pnl_net < 0:
                    losses += 1

    win_rate = (wins / closes * 100) if closes > 0 else None

    return {
        "date": date_str,
        "opens": opens,
        "closes": closes,
        "wins": wins,
        "losses": losses,
        "pnl_gross": round(total_pnl, 4),
        "total_fee": round(total_fee, 4),
        "pnl_net": round(total_pnl_net, 4),
        "win_rate": win_rate,
        "by_strategy": dict(by_strategy),
    }


def read_portfolio_status() -> dict:
    """读取当前 portfolio 状态（持仓 + 今日统计）"""
    portfolio_path = Path(__file__).parent.parent / "state" / "portfolio.json"
    if not portfolio_path.exists():
        return {}

    import json
    with open(portfolio_path) as f:
        data = json.load(f)

    positions = data.get("positions", [])
    daily = data.get("daily_stats", {})

    return {
        "open_positions": positions,
        "position_count": len(positions),
        "daily_pnl": daily.get("total_pnl", 0.0),
        "daily_trades": daily.get("total_trades", 0),
        "consecutive_losses": daily.get("consecutive_losses", 0),
    }


def format_summary(stats: dict, portfolio: dict) -> str:
    """格式化为 Telegram HTML 消息"""
    lines = []
    pnl_net = stats.get("pnl_net", 0.0)
    pnl_emoji = "📈" if pnl_net > 0 else ("📉" if pnl_net < 0 else "➖")

    lines.append(f"{pnl_emoji} <b>每日交易报告</b> ({stats['date']})")
    lines.append("")

    # 交易统计
    lines.append(f"📊 交易统计")
    lines.append(f"  开仓: {stats.get('opens', 0)} 笔")
    lines.append(f"  平仓: {stats.get('closes', 0)} 笔")
    if stats.get("closes", 0) > 0:
        lines.append(f"  ├─ 盈利: {stats.get('wins', 0)} 笔")
        lines.append(f"  └─ 亏损: {stats.get('losses', 0)} 笔")
    lines.append("")

    # 盈亏
    lines.append(f"💰 盈亏")
    lines.append(f"  总盈亏: <code>{stats.get('pnl_gross', 0):+.4f} USDT</code>")
    lines.append(f"  手续费: <code>{stats.get('total_fee', 0):.4f} USDT</code>")
    lines.append(f"  净盈亏: <code>{stats.get('pnl_net', 0):+.4f} USDT</code>")
    if stats.get("win_rate") is not None:
        lines.append(f"  胜率: <code>{stats['win_rate']:.1f}%</code>")
    lines.append("")

    # 策略分布
    if stats.get("by_strategy"):
        lines.append(f"🎯 策略分布")
        for strat, count in stats["by_strategy"].items():
            lines.append(f"  {strat}: {count} 次")
        lines.append("")

    # 当前持仓
    if portfolio.get("position_count", 0) > 0:
        lines.append(f"📦 当前持仓 ({portfolio['position_count']} 个)")
        for pos in portfolio.get("open_positions", []):
            symbol = pos.get("symbol", "?")
            direction = pos.get("direction", "?")
            entry = pos.get("entry_price", 0)
            direction_emoji = "🟢" if direction == "long" else "🔴"
            lines.append(f"  {direction_emoji} {symbol} {direction} @ {entry}")
        lines.append("")

    # 时间戳
    from datetime import timedelta
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    beijing = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%H:%M")
    lines.append(f"⏰ {now_utc} (北京 {beijing})")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="每日交易报告")
    parser.add_argument("--date", default=None, help="指定日期 (YYYY-MM-DD)，默认今日")
    parser.add_argument("--print", action="store_true", help="只打印不发")
    parser.add_argument("--dry-run", action="store_true", help="构造消息但不发送")
    args = parser.parse_args()

    # 确定日期
    if args.date:
        date_str = args.date
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"📊 生成每日报告: {date_str}")

    # 读取数据
    stats = read_daily_trades(date_str)
    portfolio = read_portfolio_status()
    print(f"  开仓 {stats.get('opens', 0)} 笔, 平仓 {stats.get('closes', 0)} 笔")
    print(f"  净盈亏: {stats.get('pnl_net', 0):+.4f} USDT")

    # 格式化
    text = format_summary(stats, portfolio)

    if args.print or args.dry_run:
        print()
        print("━━━ 报告内容 ━━━")
        print(text)
        return 0

    # 发送
    n = TelegramNotifier.from_env(str(env_path))
    if not n.enabled:
        print(f"\n⚠️  Notifier 未启用，无法发送")
        print(f"  请在 okx/.env 里设置 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID")
        print(f"\n━━━ 报告内容（预览）━━━")
        print(text)
        return 1

    print(f"\n发送报告到 Telegram (chat_id={n.chat_id})...")
    ok = n.send(text)
    if ok:
        print("✓ 发送成功")
        return 0
    else:
        print("✗ 发送失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())