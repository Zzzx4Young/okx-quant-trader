#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_send.py — OpenClaw agent 主动发送 Telegram 消息的 CLI wrapper.

背景: OpenClaw 当前缺 telegram_send tool, 此 wrapper 复用现有 TelegramNotifier
从 okx/.env 读凭据, 支持 info / critical 两个 level.

用法:
    python3 okx/scripts/telegram_send.py "your message here"
    python3 okx/scripts/telegram_send.py "critical alert" --level critical
    python3 okx/scripts/telegram_send.py --dry-run            # 验证凭据
    python3 okx/scripts/telegram_send.py --help

Exit codes:
    0 成功 (消息已发送 / dry-run 通过)
    1 失败 (凭据缺失 / Telegram API error)
    2 参数错误

注意: 真实推送会到 Nixil 的 Telegram (chat_id 来自 okx/.env).
谨慎使用 --level critical (走 notify_error 自动 dedup, 同类 5min 仅 1 次).
"""

import argparse
import sys
from pathlib import Path

# scripts/telegram_send.py → okx/scripts/ → okx/  (code package 在这里)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code.notifier import TelegramNotifier  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenClaw agent 主动发送 Telegram 消息 (CLI wrapper for TelegramNotifier)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  %(prog)s "v1.8.2 release 完成"
  %(prog)s "🚨 critical alert" --level critical
  %(prog)s --dry-run
""",
    )
    parser.add_argument("message", help="要发送的消息内容")
    parser.add_argument(
        "--level", choices=["info", "critical"], default="info",
        help="消息级别 (info=常规通知, 直发; critical=严重告警, 走 notify_error 含 dedup)",
    )
    parser.add_argument(
        "--env-path", default=None,
        help="自定义 .env 路径 (默认 = okx/.env, 自动定位)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅验证凭据 + notifier 状态, 不真发",
    )
    args = parser.parse_args()

    # ── 默认 env_path: okx/.env (auto-detect via script location) ──
    # 原因: TelegramNotifier.from_env(env_path) 只在显式给路径时加载 .env
    if args.env_path is None:
        args.env_path = str(Path(__file__).resolve().parent.parent / ".env")

    # ── 加载 notifier ──
    try:
        notifier = TelegramNotifier.from_env(args.env_path)
    except Exception as e:
        print(f"❌ notifier init failed: {e}", file=sys.stderr)
        return 1

    if not notifier.enabled:
        print("⚠️ notifier disabled (TELEGRAM_ENABLED=false 或凭据缺失)", file=sys.stderr)
        return 1

    print(f"📤 ready: chat_id={notifier.chat_id}, level={args.level}")
    print(f"   message: {args.message[:80]}{'...' if len(args.message) > 80 else ''}")

    # ── dry-run ──
    if args.dry_run:
        print("✅ dry-run OK (notifier enabled, 凭据完整)")
        return 0

    # ── 发送 ──
    try:
        if args.level == "critical":
            # 走 notify_error: 自动 dedup (5min/同类), 自动格式化为 "⚠️ 交易系统错误"
            ok = notifier.notify_error(args.message, context="[agent-critical]")
        else:
            # info: 直接 send, 不 dedup 不加格式
            ok = notifier.send(args.message)
    except Exception as e:
        print(f"❌ send exception: {e}", file=sys.stderr)
        return 1

    if ok:
        print("✅ sent OK")
        return 0
    print("❌ send FAILED (notifier returned False; check fallback log)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())