#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 通知层测试脚本

验证 notifier 配置是否正确，能成功发送消息。

用法：
  ./run.sh scripts/test_notifier.py
  ./run.sh scripts/test_notifier.py --type=open      # 测试开仓消息
  ./run.sh scripts/test_notifier.py --type=close     # 测试平仓
  ./run.sh scripts/test_notifier.py --type=daily     # 测试每日报告
  ./run.sh scripts/test_notifier.py --type=error     # 测试错误
  ./run.sh scripts/test_notifier.py --type=all       # 全部测试
  ./run.sh scripts/test_notifier.py --dry-run       # 不真发，只打印消息

环境变量（任选其一）：
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
  或
  OKX_NOTIFIER_TELEGRAM_BOT_TOKEN + OKX_NOTIFIER_TELEGRAM_CHAT_ID
"""

import argparse
import os
import sys
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


def test_basic(n: TelegramNotifier, dry_run: bool = False) -> bool:
    """发送一条最简单的消息"""
    from okx.code.notifier import _now_str
    msg = "🧪 小野通知层测试 (test_basic)\n\n如果你看到这条消息，说明 Telegram 通知配置成功。\n\n⏰ " + _now_str()
    if dry_run:
        print(f"[DRY-RUN] {msg}")
        return True
    return n.send(msg)


def test_open(n: TelegramNotifier, dry_run: bool = False) -> bool:
    """测试开仓通知"""
    pos = {
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "entry_price": 64123.45,
        "sl_price": 63802.15,
        "tp_price": 64940.96,
        "leverage": 5,
        "margin_mode": "isolated",
        "size": 100,
        "margin": 1282.47,
        "trigger_strategy": "EMA20_BREAKOUT",
        "order_id": "1234567890",
    }
    if dry_run:
        print(f"[DRY-RUN OPEN]\n{n.notify_open.__doc__}\n")
        return True
    return n.notify_open(pos)


def test_close(n: TelegramNotifier, dry_run: bool = False) -> bool:
    """测试平仓通知（盈利）"""
    result = {
        "symbol": "BTC-USDT-SWAP",
        "reason": "TP触发（做多止盈-兜底全平）",
        "pnl": 45.20,
        "roe": 3.52,
    }
    if dry_run:
        print(f"[DRY-RUN CLOSE]\n{result}\n")
        return True
    return n.notify_close(result)


def test_close_loss(n: TelegramNotifier, dry_run: bool = False) -> bool:
    """测试平仓通知（亏损）"""
    result = {
        "symbol": "ETH-USDT-SWAP",
        "reason": "SL触发（做空止损）",
        "pnl": -12.30,
        "roe": -1.50,
    }
    if dry_run:
        print(f"[DRY-RUN CLOSE-LOSS]\n{result}\n")
        return True
    return n.notify_close(result)


def test_partial(n: TelegramNotifier, dry_run: bool = False) -> bool:
    """测试部分平仓"""
    result = {
        "symbol": "BTC-USDT-SWAP",
        "reason": "TP-1:1（第一批 30%）",
        "close_ratio": 0.3,
        "pnl": 15.20,
        "roe": 1.20,
        "new_sl": 64123.45,
        "new_tp_stage": 1,
    }
    if dry_run:
        print(f"[DRY-RUN PARTIAL]\n{result}\n")
        return True
    return n.notify_partial_close(result)


def test_error(n: TelegramNotifier, dry_run: bool = False) -> bool:
    """测试错误通知"""
    if dry_run:
        print(f"[DRY-RUN ERROR] 模拟错误消息\n")
        return True
    return n.notify_error(
        "[51008] Order failed. Your available USDT balance is insufficient",
        context="下单 #BTC-USDT-SWAP 时",
    )


def test_daily(n: TelegramNotifier, dry_run: bool = False) -> bool:
    """测试每日报告"""
    stats = {
        "date": "2026-07-11",
        "opens": 3,
        "closes": 2,
        "pnl_gross": 125.50,
        "total_fee": 8.30,
        "pnl_net": 117.20,
        "win_rate": 100.0,
    }
    if dry_run:
        print(f"[DRY-RUN DAILY]\n{stats}\n")
        return True
    return n.notify_daily_summary(stats)


def test_dedup(n: TelegramNotifier) -> bool:
    """测试错误去重：同类型错误 5 分钟内只发一次"""
    err_key = "TEST_DEDUP_KEY"
    sent_1 = n.notify_error("第一次错误", dedup_key=err_key)
    sent_2 = n.notify_error("第二次错误", dedup_key=err_key)
    sent_3 = n.notify_error("第三次错误", dedup_key=err_key)
    print(f"  去重测试: 1st={sent_1}, 2nd={sent_2}, 3rd={sent_3}")
    print(f"  预期: 1st=True, 2nd=False, 3rd=False")
    return sent_1 and not sent_2 and not sent_3


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram 通知层测试")
    parser.add_argument("--type", default="basic",
                        choices=["basic", "open", "close", "partial", "error", "daily", "dedup", "all"],
                        help="测试类型（默认 basic）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不真发")
    args = parser.parse_args()

    # 构造 notifier
    n = TelegramNotifier.from_env(str(env_path))

    print("=" * 60)
    print("  Telegram 通知层测试")
    print("=" * 60)
    print(f"  enabled: {n.enabled}")
    print(f"  bot_token: {'已配置' if n.bot_token else '❌ 未配置'}")
    print(f"  chat_id: {n.chat_id or '❌ 未配置'}")
    print(f"  proxy: {n.proxy_url or '无'}")
    print()

    if not n.enabled and not args.dry_run:
        print("⚠️  Notifier 未启用")
        print()
        print("请按以下方式启用：")
        print()
        print("  方案 A：在 okx/.env 里加（推荐）")
        print("    TELEGRAM_BOT_TOKEN=你的bot_token")
        print("    TELEGRAM_CHAT_ID=你的chat_id")
        print("    # 或者:")
        print("    OKX_NOTIFIER_TELEGRAM_BOT_TOKEN=你的bot_token")
        print("    OKX_NOTIFIER_TELEGRAM_CHAT_ID=你的chat_id")
        print()
        print("  方案 B：使用 --dry-run 只看消息格式")
        print()
        print("如何拿到 bot_token:")
        print("  1. Telegram 里跟 @BotFather 对话")
        print("  2. 发送 /newbot")
        print("  3. 按提示设置名字和 username")
        print("  4. 复制返回的 token")
        print()
        print("如何拿到 chat_id:")
        print("  1. 跟你的 bot 随便说一句")
        print("  2. 浏览器访问 https://api.telegram.org/bot<TOKEN>/getUpdates")
        print("  3. 在 chat 对象里找 id 字段")
        return 1

    handlers = {
        "basic": ("基础测试", test_basic),
        "open": ("开仓通知", test_open),
        "close": ("平仓通知(盈)", test_close),
        "partial": ("部分平仓", test_partial),
        "error": ("错误通知", test_error),
        "daily": ("每日报告", test_daily),
        "dedup": ("错误去重", test_dedup),
    }

    if args.type == "all":
        # dedup 单独跑（不需要 -dry_run 之外的）
        for k, (name, fn) in handlers.items():
            print(f"[{k}] {name}")
            ok = fn(n, dry_run=args.dry_run)
            print(f"  结果: {'✓' if ok else '✗'}")
            print()
    else:
        name, fn = handlers[args.type]
        print(f"[{args.type}] {name}")
        ok = fn(n, dry_run=args.dry_run)
        print(f"  结果: {'✓' if ok else '✗'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())