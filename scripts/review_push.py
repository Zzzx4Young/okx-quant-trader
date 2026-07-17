#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
review_push.py —— OKX 每日复盘推送（v2：真实数据 + 抗网络抖动）

═══════════════════════════════════════════════════════════════════
设计原则（与 v1 一致）
═══════════════════════════════════════════════════════════════════
- 零 LLM 幻觉：所有数据来自确定性数据源（trades CSV / OKX API / portfolio.json）
- "持仓未实现盈亏"：直接读 OKX /api/v5/account/positions 响应的 `upl` 字段
- "持仓状态"段：纯数据描述，替换原"明日策略建议"（避免幻觉）

═══════════════════════════════════════════════════════════════════
v2 改进（2026-07-18）
═══════════════════════════════════════════════════════════════════
1. 网络抗抖动：OKX API 调用加 3 次指数退避重试（治 V2RayN 瞬时断连）
2. 优雅降级：OKX 全失败时仍报 CSV/portfolio 数据，标"⚠️ degraded"
3. 6 段结构：策略归因 / 风控状态 / 持仓快照 / 昨日对比（治"内容浅"）
═══════════════════════════════════════════════════════════════════
"""
import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Tuple, List, Dict, Any, Callable, TypeVar

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # okx/scripts/ → okx/ → workspace/

sys.path.insert(0, str(PROJECT_ROOT))

from okx.code import OKXClient
from okx.code.notifier import TelegramNotifier

WORKSPACE = PROJECT_ROOT
TRADES_DIR = WORKSPACE / "okx/logs/trades"
LOG_FILE = WORKSPACE / "okx/logs/daily_review.log"
ENV_FILE = WORKSPACE / "okx/.env"
PORTFOLIO_FILE = WORKSPACE / "okx/state/portfolio.json"

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ────────────────────────────────────────────────────────────────────
# 重试工具
# ────────────────────────────────────────────────────────────────────


def fetch_with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    backoff: Tuple[int, ...] = (1, 2, 4),
    retry_on: Tuple[type, ...] = (ConnectionError, OSError),
) -> T:
    """指数退避重试网络调用

    :param fn: 无参 callable，返回 T 或抛异常
    :param max_attempts: 最大尝试次数（默认 3）
    :param backoff: 每次失败后的等待秒数（默认 1/2/4s）
    :param retry_on: 触发重试的异常类型元组（默认网络类）
    :raises: 最后一次的异常（如果全部失败）
    """
    last_exc: Exception = RuntimeError("fetch_with_retry: no attempts")
    for attempt in range(max_attempts):
        try:
            return fn()
        except retry_on as e:
            last_exc = e
            if attempt < max_attempts - 1:
                delay = backoff[min(attempt, len(backoff) - 1)]
                logger.warning(
                    f"attempt {attempt + 1}/{max_attempts} failed: {type(e).__name__}: {e}, "
                    f"retry in {delay}s"
                )
                time.sleep(delay)
            else:
                logger.error(f"all {max_attempts} attempts failed: {type(e).__name__}: {e}")
        except Exception:
            # 非网络错误（如 OKX 业务错误 5xxxx）不重试，直接抛
            raise
    raise last_exc


# ────────────────────────────────────────────────────────────────────
# 日期 / CSV
# ────────────────────────────────────────────────────────────────────


def get_today_shanghai_date() -> str:
    """Shanghai 日期 YYYY-MM-DD（与 trades/ 文件命名约定一致）"""
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def get_yesterday_shanghai_date(today: str = None) -> str:
    """昨日 Shanghai 日期"""
    today = today or get_today_shanghai_date()
    return (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


def read_closed_trades(date: str) -> List[Dict[str, Any]]:
    """读 trades/{date}.csv，返回当日平仓记录列表（CSV 头过滤）"""
    csv_path = TRADES_DIR / f"{date}.csv"
    if not csv_path.exists():
        return []
    try:
        with csv_path.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def summarize_closed_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """汇总当日 closed trades：笔数、总 pnl、最大单笔、胜率"""
    if not trades:
        return {
            "count": 0,
            "total_pnl": 0.0,
            "max_trade": None,
            "win_count": 0,
            "win_rate": None,
        }

    pnls: List[float] = []
    for t in trades:
        raw = t.get("pnl", "0") or "0"
        try:
            pnls.append(float(raw))
        except (ValueError, TypeError):
            pnls.append(0.0)

    total_pnl = sum(pnls)
    max_idx = max(range(len(pnls)), key=lambda i: pnls[i])
    max_trade = {
        "symbol": trades[max_idx].get("symbol", "?"),
        "pnl": pnls[max_idx],
    }
    win_count = sum(1 for p in pnls if p > 0)
    win_rate = win_count / len(pnls)

    return {
        "count": len(trades),
        "total_pnl": total_pnl,
        "max_trade": max_trade,
        "win_count": win_count,
        "win_rate": win_rate,
    }


# ────────────────────────────────────────────────────────────────────
# portfolio.json 读取（v2 新增）
# ────────────────────────────────────────────────────────────────────


def read_portfolio_summary(today_date: str) -> Dict[str, Any]:
    """读 portfolio.json：daily_stats + 今日平仓按策略分组

    :return: {
        "daily_stats": {"consecutive_losses": int, "emergency_stop_triggered": bool, ...},
        "strategy_breakdown": {strategy_name: {"count": int, "pnl": float}},
        "load_error": str | None,   # 文件缺失/损坏时记录
    }
    """
    result: Dict[str, Any] = {
        "daily_stats": {},
        "strategy_breakdown": {},
        "load_error": None,
    }
    if not PORTFOLIO_FILE.exists():
        result["load_error"] = "portfolio.json 不存在"
        return result
    try:
        data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        result["load_error"] = f"portfolio.json 读取失败: {e}"
        return result

    result["daily_stats"] = data.get("daily_stats", {}) or {}

    # 按 strategy 分组今日 closed
    strategy_pnl: Dict[str, float] = {}
    strategy_count: Dict[str, int] = {}
    for p in data.get("closed_positions", []) or []:
        closed_at = p.get("closed_at", "") or ""
        if not closed_at.startswith(today_date):
            continue
        strat = p.get("strategy") or "UNKNOWN"
        pnl = float(p.get("realized_pnl", 0) or 0)
        strategy_pnl[strat] = strategy_pnl.get(strat, 0.0) + pnl
        strategy_count[strat] = strategy_count.get(strat, 0) + 1

    result["strategy_breakdown"] = {
        k: {"count": strategy_count[k], "pnl": strategy_pnl[k]}
        for k in strategy_pnl
    }
    return result


# ────────────────────────────────────────────────────────────────────
# OKX 持仓（v2 加重试）
# ────────────────────────────────────────────────────────────────────


def get_positions_data(client: OKXClient) -> Tuple[int, float, List[Dict[str, Any]]]:
    """OKX V5 /api/v5/account/positions → (持仓数, 总 upl, 详情)

    ⚠️ 不要自己算 upl：直接读 OKX 响应里的 `upl` 字段（planY 决策）
    """
    positions = client.account.get_positions(inst_type="SWAP")
    n = len(positions)
    total_upl = sum(float(p.get("upl", 0)) for p in positions)
    return n, total_upl, positions


def compose_position_status(positions: List[Dict[str, Any]]) -> str:
    """纯数据描述持仓状态（无 LLM 幻觉）

    返回示例:
    - "无持仓"
    - "BTC-USDT-SWAP short 0.15张 @64225, 未实现 +1.41 USDT (盈利 +0.04%)"
    """
    if not positions:
        return "无持仓"

    parts = []
    for p in positions:
        sym = p.get("instId", "?")
        side = p.get("posSide", "?")
        size = float(p.get("pos", 0) or 0)
        avg_px = float(p.get("avgPx", 0) or 0)
        upl = float(p.get("upl", 0) or 0)
        margin = float(p.get("margin", 0) or 0)
        upl_ratio = (upl / margin * 100) if margin else 0.0
        sign = "盈利" if upl >= 0 else "亏损"
        parts.append(
            f"{sym} {side} {size}张 @{avg_px:.0f}, "
            f"未实现 {upl:+.2f} USDT ({sign} {upl_ratio:+.2f}%)"
        )
    return "; ".join(parts)


def compute_liq_proximity(positions: List[Dict[str, Any]]) -> str:
    """最小强平距离描述（v2 新增）

    返回: "34.49%" / "N/A" / "< 5% ⚠️"
    """
    distances: List[Tuple[str, float]] = []
    for p in positions:
        mark = float(p.get("markPx", 0) or 0)
        liq = float(p.get("liqPx", 0) or 0)
        if mark > 0 and liq > 0:
            d = abs(mark - liq) / mark
            distances.append((p.get("instId", "?"), d))
    if not distances:
        return "N/A"
    min_sym, min_d = min(distances, key=lambda x: x[1])
    return f"{min_d * 100:.2f}%" + (" ⚠️" if min_d < 0.05 else "")


# ────────────────────────────────────────────────────────────────────
# 拼装 + 推送
# ────────────────────────────────────────────────────────────────────


def compose_message(
    stats: Dict[str, Any],
    upl: float,
    n_positions: int,
    position_status: str,
    portfolio: Dict[str, Any],
    yesterday: Dict[str, Any],
    liq_proximity: str,
    okx_degraded: bool = False,
) -> str:
    """6 段纯文本简报（无 HTML/Markdown 特殊字符）

    :param okx_degraded: True 时头部加 ⚠️ degraded 标记（OKX 重试全失败但 CSV/portfolio 仍 OK）
    """
    lines: List[str] = []
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M CST")

    # ── 头部 ──
    status_icon = "⚠️ degraded" if okx_degraded else "✓"
    lines.append(f"[{ts}] {status_icon} OKX 每日复盘（demo）")
    lines.append("─" * 50)

    # ── 1. 今日交易 ──
    lines.append("1. 今日交易")
    lines.append(
        f"   {stats['count']} 笔｜平仓 {stats['total_pnl']:+.4f} USDT｜"
        f"持仓未实现 {upl:+.4f} USDT ({n_positions} 个持仓)"
    )

    # ── 2. 胜率 ──
    lines.append("")
    lines.append("2. 胜率")
    if stats["win_rate"] is None:
        lines.append("   0/0（无平仓样本）")
    else:
        wr_pct = stats["win_rate"] * 100
        lines.append(f"   {stats['win_count']}/{stats['count']} ({wr_pct:.1f}%)")

    # ── 3. 策略归因（v2 新增）──
    lines.append("")
    lines.append("3. 策略归因")
    breakdown = portfolio.get("strategy_breakdown", {}) or {}
    if not breakdown:
        if portfolio.get("load_error"):
            lines.append(f"   ⚠️ {portfolio['load_error']}")
        else:
            lines.append("   无（今日无平仓）")
    else:
        for strat, info in sorted(breakdown.items(), key=lambda x: -x[1]["pnl"]):
            lines.append(f"   {strat}: {info['count']} 笔｜{info['pnl']:+.4f} USDT")

    # ── 4. 风控状态（v2 新增）──
    lines.append("")
    lines.append("4. 风控状态")
    daily_stats = portfolio.get("daily_stats", {}) or {}
    consec = daily_stats.get("consecutive_losses", 0)
    emergency = daily_stats.get("emergency_stop_triggered", False)
    daily_pnl = float(daily_stats.get("total_pnl", 0) or 0)
    lines.append(
        f"   连续亏损: {consec} 次｜"
        f"紧急熔断: {'⚠️ 已触发' if emergency else '✗ 未触发'}｜"
        f"今日 PnL: {daily_pnl:+.4f} USDT"
    )

    # ── 5. 持仓快照（v2 加 liq_proximity）──
    lines.append("")
    lines.append("5. 持仓快照")
    if okx_degraded:
        lines.append(f"   ⚠️ OKX API 失败（已重试 3 次），持仓数据不可用")
    else:
        lines.append(f"   {position_status}")
        lines.append(f"   ⚠️ 最小强平距离: {liq_proximity}")

    # ── 6. 昨日对比（v2 新增）──
    lines.append("")
    lines.append("6. 昨日对比")
    lines.append(
        f"   交易: {stats['count']} (昨 {yesterday.get('count', 0)})｜"
        f"平仓 PnL: {stats['total_pnl']:+.4f} "
        f"(昨 {yesterday.get('total_pnl', 0.0):+.4f}) USDT"
    )

    lines.append("─" * 50)
    return "\n".join(lines)


def write_log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S CST")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}]\n{message}\n\n")


def push_error(notifier: TelegramNotifier, msg: str) -> None:
    try:
        if notifier.enabled:
            notifier.send(msg)
    except Exception:
        pass


def run(date: str = None) -> int:
    """主体逻辑，可被测试直接调用（避免 argparse sys.argv 冲突）

    优雅降级策略：
    1. CSV / portfolio 永远先读（不依赖网络）
    2. OKX API 加 3 次重试，全失败时标 degraded 但仍出报告
    3. 失败结果也会写本地日志（保留审计轨迹）
    """
    date = date or get_today_shanghai_date()
    yesterday_date = get_yesterday_shanghai_date(date)
    notifier = TelegramNotifier.from_env(str(ENV_FILE))

    # ── 1. CSV 数据（永不依赖网络）──
    trades = read_closed_trades(date)
    stats = summarize_closed_trades(trades)
    yesterday_trades = read_closed_trades(yesterday_date)
    yesterday = summarize_closed_trades(yesterday_trades)
    yesterday["date"] = yesterday_date

    # ── 2. portfolio.json 数据（本地文件，不依赖网络）──
    portfolio = read_portfolio_summary(date)

    # ── 3. OKX API（加重试 + 优雅降级）──
    okx_degraded = False
    n_positions = 0
    total_upl = 0.0
    positions: List[Dict[str, Any]] = []
    position_status = "⚠️ OKX API 不可用"
    liq_proximity = "N/A"

    try:
        mode = os.getenv("OKX_TRADING_MODE", "demo")
        client = OKXClient(mode=mode, timeout=10)

        # 重试包装：网络抖动时重试 3 次
        n_positions, total_upl, positions = fetch_with_retry(
            lambda: get_positions_data(client),
            max_attempts=3,
            backoff=(1, 2, 4),
        )
        position_status = compose_position_status(positions)
        liq_proximity = compute_liq_proximity(positions)
    except Exception as e:
        # 重试全失败 → degraded 模式，但仍出报告
        okx_degraded = True
        msg = f"⚠️ 复盘 degraded: OKX API 重试 3 次仍失败 ({type(e).__name__}: {e})"
        logger.warning(msg)
        # 注意：不 return 1，让 CSV/portfolio 数据继续输出

    # ── 4. 拼装 + 写日志 + 推 Telegram ──
    report = compose_message(
        stats=stats,
        upl=total_upl,
        n_positions=n_positions,
        position_status=position_status,
        portfolio=portfolio,
        yesterday=yesterday,
        liq_proximity=liq_proximity,
        okx_degraded=okx_degraded,
    )
    write_log(report)
    print(report)

    if notifier.enabled:
        try:
            ok = notifier.send(report)
            if ok:
                print("✓ Telegram 推送成功")
            else:
                err = "⚠️ 复盘推送失败: Telegram 返回错误"
                print(err, file=sys.stderr)
                write_log(err)
                return 1
        except Exception as e:
            err = f"⚠️ 复盘推送异常: {type(e).__name__}: {e}"
            print(err, file=sys.stderr)
            write_log(err)
            return 1
    else:
        warn = "⚠️ Notifier 未启用，仅写日志未推送"
        print(warn, file=sys.stderr)
        write_log(warn)

    return 0


def main(argv: list = None) -> int:
    """CLI 入口：解析 argv 后调 run()"""
    parser = argparse.ArgumentParser(description="OKX 每日复盘推送（v2）")
    parser.add_argument("--date", default=None, help="Shanghai date YYYY-MM-DD（默认今天）")
    parser.add_argument("--verbose", "-v", action="store_true", help="启用 DEBUG log")
    args = parser.parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

    return run(args.date)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
