# -*- coding: utf-8 -*-
"""
OKX 交易系统通知层（Telegram）

设计原则：
- 通知失败不能阻塞交易：所有 send 调用都 try/except
- 易于关闭：通过 env / config 控制 enabled
- 富文本：HTML 格式（兼容 Telegram Bot API）
- 走代理：复用 OKX 客户端的代理配置（WSL2 / 跨网场景）
- 限频：避免被 Telegram 限流（同一分钟内同类消息合并）

事件类型：
- 开仓 (notify_open)
- 平仓 (notify_close)
- 部分平仓 (notify_partial_close)
- 错误 (notify_error)
- 心跳/日报 (notify_daily_summary)
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


logger = logging.getLogger(__name__)


# ──────────── 格式化器 ────────────


def _fmt_price(p: float) -> str:
    """价格格式化：BTC 用 2 位小数，小币种用 4 位"""
    if p > 100:
        return f"{p:,.2f}"
    elif p > 1:
        return f"{p:,.4f}"
    return f"{p:.6f}"


def _fmt_pct(p: float) -> str:
    """百分比：+2.30% / -1.50%"""
    return f"{p:+.2f}%"


def _fmt_usdt(x: float) -> str:
    """金额：保留 2-4 位"""
    if abs(x) < 0.01:
        return f"{x:.6f}"
    return f"{x:,.2f}"


def _now_str() -> str:
    """UTC + 北京时间"""
    utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    beijing = datetime.now(timezone.utc).strftime("%H:%M")  # 简化
    # 转为北京时间
    from datetime import timedelta
    beijing_t = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%H:%M")
    return f"{utc} (北京 {beijing_t})"


# ──────────── 主类 ────────────


class TelegramNotifier:
    """Telegram 通知器（直接调 Bot API）"""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        proxy_url: Optional[str] = None,
        timeout: int = 10,
        enabled: bool = True,
        min_interval_sec: int = 1,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.proxy_url = proxy_url
        self.timeout = timeout
        self.enabled = enabled
        self.min_interval_sec = min_interval_sec

        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._last_send_ts = 0.0
        self._lock = threading.Lock()

        # 限频内存
        self._last_error_sent_at: Dict[str, float] = {}  # error_type -> ts
        self._error_dedup_window = 300  # 同类错误 5 分钟内不重复发

    @classmethod
    def from_env(cls, env_path: Optional[str] = None) -> "TelegramNotifier":
        """从 .env / 环境变量构造

        环境变量：
          TELEGRAM_BOT_TOKEN    - Bot token (从 @BotFather 拿)
          TELEGRAM_CHAT_ID      - 接收消息的 chat_id
          TELEGRAM_ENABLED      - true/false（默认 true）

        也支持从 OKX .env 的 notifier 段读取（保持配置集中）：
          # OKX .env
          OKX_NOTIFIER_TELEGRAM_BOT_TOKEN=...
          OKX_NOTIFIER_TELEGRAM_CHAT_ID=...
        """
        # 加载 .env（如果给了路径）
        if env_path and os.path.exists(env_path):
            for line in open(env_path):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)

        bot_token = (
            os.getenv("TELEGRAM_BOT_TOKEN")
            or os.getenv("OKX_NOTIFIER_TELEGRAM_BOT_TOKEN")
            or ""
        )
        chat_id = (
            os.getenv("TELEGRAM_CHAT_ID")
            or os.getenv("OKX_NOTIFIER_TELEGRAM_CHAT_ID")
            or ""
        )
        enabled = (
            os.getenv("TELEGRAM_ENABLED", "true").lower() in ("1", "true", "yes")
            and os.getenv("OKX_NOTIFIER_ENABLED", "true").lower() in ("1", "true", "yes")
        )
        proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")

        return cls(
            bot_token=bot_token,
            chat_id=chat_id,
            proxy_url=proxy_url,
            enabled=enabled and bool(bot_token) and bool(chat_id),
        )

    # ───── 底层发送 ─────

    def send(self, text: str, parse_mode: str = "HTML", silent: bool = False) -> bool:
        """发送消息

        :param text: 消息内容（HTML 格式）
        :param parse_mode: HTML / MarkdownV2
        :param silent: 是否静默（不发推送通知）
        :return: True if successful
        """
        if not self.enabled:
            logger.debug("notifier disabled, skipping send")
            return False
        if not self.bot_token or not self.chat_id:
            logger.warning("notifier not configured (missing bot_token or chat_id)")
            return False

        with self._lock:
            # 限频
            now = time.time()
            elapsed = now - self._last_send_ts
            if elapsed < self.min_interval_sec:
                time.sleep(self.min_interval_sec - elapsed)
            self._last_send_ts = time.time()

        try:
            proxies = {"https": self.proxy_url, "http": self.proxy_url} if self.proxy_url else None
            resp = requests.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                    "disable_notification": silent,
                },
                proxies=proxies,
                timeout=self.timeout,
            )
            data = resp.json()
            if data.get("ok"):
                return True
            logger.error(f"telegram send failed: {data}")
            return False
        except Exception as e:
            logger.error(f"telegram send exception: {e}")
            return False

    def _dedup_error(self, error_key: str) -> bool:
        """检查并记录错误事件，用于去重（同类型 5 分钟内只发一次）

        :return: True 表示应发送，False 表示已去重跳过
        """
        now = time.time()
        last = self._last_error_sent_at.get(error_key, 0)
        if now - last < self._error_dedup_window:
            return False
        self._last_error_sent_at[error_key] = now
        return True

    # ───── 业务事件 ─────

    def notify_open(self, position: Dict[str, Any]) -> bool:
        """通知开仓成功"""
        direction_emoji = "🟢" if position["direction"] == "long" else "🔴"
        direction_cn = "做多" if position["direction"] == "long" else "做空"

        entry = float(position["entry_price"])
        sl = float(position["sl_price"])
        tp = float(position["tp_price"])
        sl_pct = (sl - entry) / entry * 100 if entry > 0 else 0
        tp_pct = (tp - entry) / entry * 100 if entry > 0 else 0

        text = (
            f"{direction_emoji} <b>开仓</b> #{position['symbol']}\n\n"
            f"方向: {direction_cn} ({position['direction']})\n"
            f"入场价: <code>{_fmt_price(entry)}</code>\n"
            f"止损: <code>{_fmt_price(sl)}</code> ({_fmt_pct(sl_pct)})\n"
            f"止盈: <code>{_fmt_price(tp)}</code> ({_fmt_pct(tp_pct)})\n"
            f"杠杆: {position.get('leverage', '?')}x {position.get('margin_mode', 'isolated')}\n"
            f"数量: {position.get('size', '?')} 张\n"
            f"保证金: {_fmt_usdt(position.get('margin', 0))} USDT\n"
            f"策略: {position.get('trigger_strategy', position.get('strategy', '?'))}\n"
            f"订单: <code>{position.get('order_id', '?')}</code>\n"
            f"\n⏰ {_now_str()}"
        )
        return self.send(text)

    def notify_close(self, close_result: Dict[str, Any]) -> bool:
        """通知平仓"""
        pnl = float(close_result.get("pnl", 0))
        roe = float(close_result.get("roe", 0))
        pnl_emoji = "💰" if pnl > 0 else ("💸" if pnl < 0 else "➖")
        pnl_sign = "+" if pnl > 0 else ""

        text = (
            f"{pnl_emoji} <b>平仓</b> #{close_result.get('symbol', '?')}\n\n"
            f"原因: {close_result.get('reason', '?')}\n"
            f"盈亏: <code>{pnl_sign}{_fmt_usdt(pnl)} USDT</code>\n"
            f"收益率: <code>{pnl_sign}{roe:.2f}%</code>\n"
            f"\n⏰ {_now_str()}"
        )
        return self.send(text)

    def notify_partial_close(self, partial_result: Dict[str, Any]) -> bool:
        """通知部分平仓"""
        pnl = float(partial_result.get("pnl", 0))
        roe = float(partial_result.get("roe", 0))
        ratio = float(partial_result.get("close_ratio", 0)) * 100

        text = (
            f"📊 <b>部分平仓</b> #{partial_result.get('symbol', '?')}\n\n"
            f"原因: {partial_result.get('reason', '?')}\n"
            f"平仓比例: {ratio:.0f}%\n"
            f"本次盈亏: <code>{pnl:+.2f} USDT</code> ({roe:+.2f}%)\n"
            f"新止损: {_fmt_price(partial_result.get('new_sl', 0)) if partial_result.get('new_sl') else '未变'}\n"
            f"止盈阶段: TP-{partial_result.get('new_tp_stage', '?')}\n"
            f"\n⏰ {_now_str()}"
        )
        return self.send(text)

    def notify_error(self, error_msg: str, context: str = "", dedup_key: Optional[str] = None) -> bool:
        """通知错误（自动去重，同类 5 分钟内只发一次）

        :param dedup_key: 自定义去重 key（默认用 error_msg 前 50 字符）
        """
        key = dedup_key or error_msg[:50]
        if not self._dedup_error(key):
            logger.debug(f"error dedup: {key}")
            return False

        text = (
            f"⚠️ <b>交易系统错误</b>\n\n"
            f"{context + chr(10) if context else ''}"
            f"<code>{error_msg}</code>\n"
            f"\n⏰ {_now_str()}"
        )
        return self.send(text)

    def notify_daily_summary(self, stats: Dict[str, Any]) -> bool:
        """发送每日交易报告"""
        pnl_net = float(stats.get("pnl_net", 0))
        pnl_gross = float(stats.get("pnl_gross", 0))
        fee = float(stats.get("total_fee", 0))
        opens = int(stats.get("opens", 0))
        closes = int(stats.get("closes", 0))

        # 计算胜率
        win_rate = stats.get("win_rate")
        win_rate_str = f"{win_rate:.1f}%" if win_rate is not None else "N/A"

        pnl_emoji = "📈" if pnl_net > 0 else ("📉" if pnl_net < 0 else "➖")

        text = (
            f"{pnl_emoji} <b>每日交易报告</b> ({stats.get('date', '?')})\n\n"
            f"开仓: {opens} 笔\n"
            f"平仓: {closes} 笔\n"
            f"总盈亏: <code>{pnl_gross:+.4f} USDT</code>\n"
            f"手续费: <code>{fee:.4f} USDT</code>\n"
            f"净盈亏: <code>{pnl_net:+.4f} USDT</code>\n"
            f"胜率: {win_rate_str}\n"
            f"\n⏰ {_now_str()}"
        )
        return self.send(text)

    def notify_heartbeat(self, status: Dict[str, Any]) -> bool:
        """发送心跳/状态报告（轻量级）"""
        text = (
            f"💓 <b>交易系统心跳</b>\n\n"
            f"持仓: {status.get('position_count', 0)}/{status.get('max_positions', '?')}\n"
            f"今日交易: {status.get('daily_trades', 0)} 笔\n"
            f"今日净盈亏: <code>{status.get('daily_pnl', 0):+.4f} USDT</code>\n"
            f"模式: {'模拟盘' if status.get('demo_mode', True) else '⚠️ 实盘'}\n"
            f"\n⏰ {_now_str()}"
        )
        return self.send(text)

    def notify_action_result(self, result: Dict[str, Any]) -> bool:
        """通用：通知交易结果（自动判断 open/close/error）

        接受 runner 输出的 actions 列表中的单个 action dict。
        """
        if not result:
            return False

        status = result.get("status", "")
        symbol = result.get("signal", {}).get("symbol", "?")

        if status == "success":
            pos_rec = result.get("position_record", {})
            return self.notify_open(pos_rec)
        elif status == "rejected":
            return self.notify_error(
                result.get("error", "未知错误"),
                context=f"风控拒绝 #{symbol}",
                dedup_key=f"rejected:{symbol}",
            )
        elif status == "error":
            return self.notify_error(
                result.get("error", "未知错误"),
                context=f"下单错误 #{symbol}",
                dedup_key=f"order_error:{symbol}",
            )
        return False

    def notify_drift(self, recon_result: Dict[str, Any]) -> bool:
        """portfolio ↔ OKX 对账发现 drift，推 Telegram 告警。

        recon_result 结构：
          {
            "drift_detected": bool,
            "ghost_closed":   [已归档的本地鬼记录],
            "new_synced":     [从 OKX 补齐的新仓位],
            "mismatched":     [本地 vs OKX 不一致],
            "actions":        [操作摘要 list],
          }
        """
        if not recon_result.get("drift_detected"):
            return False

        ghost = recon_result.get("ghost_closed", [])
        new = recon_result.get("new_synced", [])
        mm = recon_result.get("mismatched", [])
        parts = []
        if ghost:
            lines = []
            for g in ghost[:5]:
                lines.append(
                    f"  · {g.get('symbol','?')} {g.get('direction','?')} "
                    f"realized={float(g.get('realized_pnl', 0) or 0):+.4f} USDT"
                )
            parts.append(f"<b>鬼记录已归档 ({len(ghost)})</b>\n" + "\n".join(lines))
        if new:
            lines = []
            for n in new[:5]:
                lines.append(
                    f"  · {n.get('symbol','?')} {n.get('direction','?')} "
                    f"sz={n.get('size','?')} entry={n.get('entry_price','?'):.4f} "
                    f"SL={n.get('sl_price','?'):.4f} TP={n.get('tp_price','?'):.4f}"
                )
            parts.append(f"<b>OKX 已补齐 ({len(new)})</b>\n" + "\n".join(lines))
        if mm:
            parts.append(f"<b>大小不一致 ({len(mm)})</b>\n手动检查")

        body = (
            "🟠 <b>portfolio ↔ OKX drift</b>\n"
            f"ghost={len(ghost)} new={len(new)} mismatch={len(mm)}\n\n"
            + "\n\n".join(parts)
        )
        return self.send(body, parse_mode="HTML", disable_notification=False)


# ──────────── NoopNotifier（禁用 / 测试用） ────────────


class NoopNotifier:
    """什么都不做的 notifier，用于禁用通知或测试"""

    def send(self, *args, **kwargs) -> bool:
        return False

    def notify_open(self, *args, **kwargs) -> bool:
        return False

    def notify_close(self, *args, **kwargs) -> bool:
        return False

    def notify_partial_close(self, *args, **kwargs) -> bool:
        return False

    def notify_error(self, *args, **kwargs) -> bool:
        return False

    def notify_daily_summary(self, *args, **kwargs) -> bool:
        return False

    def notify_heartbeat(self, *args, **kwargs) -> bool:
        return False

    def notify_action_result(self, *args, **kwargs) -> bool:
        return False

    def notify_drift(self, *args, **kwargs) -> bool:
        return False