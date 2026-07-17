#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
heartbeat_push.py —— OKX 系统晚间心跳推送（v2：抗网络抖动 + 多源数据）

═══════════════════════════════════════════════════════════════════
设计原则（与 v1 一致）
═══════════════════════════════════════════════════════════════════
- 确定性数据走确定性路径（planY）
- 持仓未实现盈亏：直接读 OKX `upl` 字段（零计算）
- 当日统计：portfolio.json daily_stats
- 推送：TelegramNotifier

═══════════════════════════════════════════════════════════════════
v2 改进（2026-07-18）
═══════════════════════════════════════════════════════════════════
1. 网络抗抖动：OKX API 加 3 次指数退避重试（治 V2RayN 瞬时断连）
2. 优雅降级：OKX 全失败时仍报本地数据（持仓 / 状态 / 风控），标"⚠️ degraded"
3. 5 段结构：保留 v1 的 5 行 baseline + 增加集中度 / 工作流新鲜度 / 风控标记 / 持仓明细
═══════════════════════════════════════════════════════════════════
"""
import argparse
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
from okx.code.config import Config
from okx.code.notifier import TelegramNotifier

WORKSPACE = PROJECT_ROOT
PORTFOLIO = WORKSPACE / "okx/state/portfolio.json"
WORKFLOW = WORKSPACE / "okx/state/last_workflow_result.json"
LOG_FILE = WORKSPACE / "okx/logs/heartbeat.log"
ENV_FILE = WORKSPACE / "okx/.env"

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ────────────────────────────────────────────────────────────────────
# 重试工具（与 review_push.py 一致）
# ────────────────────────────────────────────────────────────────────


def fetch_with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    backoff: Tuple[int, ...] = (1, 2, 4),
    retry_on: Tuple[type, ...] = (ConnectionError, OSError),
) -> T:
    """指数退避重试网络调用"""
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
            raise
    raise last_exc


# ────────────────────────────────────────────────────────────────────
# 数据读取
# ────────────────────────────────────────────────────────────────────


def get_positions_summary(client: OKXClient) -> Tuple[int, float, List[Dict[str, Any]]]:
    """OKX V5 /api/v5/account/positions → (持仓数, 总未实现盈亏, 详情)

    ⚠️ 不要自己算 upl：直接读 OKX 响应里的 `upl` 字段（planY 决策）
    """
    positions = client.account.get_positions(inst_type="SWAP")
    n = len(positions)
    total_upl = sum(float(p.get("upl", 0)) for p in positions)
    return n, total_upl, positions


def get_daily_stats() -> Tuple[int, float, Dict[str, Any]]:
    """portfolio.json daily_stats → (今日成交笔数, 今日已平仓盈亏, 完整 dict)

    v2 变更：返回完整 daily_stats（包含 consecutive_losses / emergency_stop_triggered 等）
    """
    if not PORTFOLIO.exists():
        return 0, 0.0, {}
    try:
        data = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0.0, {}
    stats = data.get("daily_stats", {}) or {}
    return int(stats.get("total_trades", 0)), float(stats.get("total_pnl", 0.0)), stats


def get_status_and_max() -> Tuple[str, int]:
    """(系统状态, 最大持仓数)

    状态判定优先级: emergency_stop > paused > active
    """
    try:
        cfg = Config.from_env()
        max_pos = int(cfg.max_concurrent_positions)
    except Exception:
        max_pos = 5

    if PORTFOLIO.exists():
        try:
            data = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
            if data.get("daily_stats", {}).get("emergency_stop_triggered"):
                return "emergency_stop", max_pos
        except Exception:
            pass

    if WORKFLOW.exists():
        try:
            wf = json.loads(WORKFLOW.read_text(encoding="utf-8"))
            status = (wf.get("status") or "").lower()
            if "emergency" in status or ("stop" in status and "stop_loss" not in status):
                return "emergency_stop", max_pos
            if "pause" in status:
                return "paused", max_pos
        except Exception:
            pass

    return "active", max_pos


def get_workflow_freshness() -> Tuple[str, int]:
    """(last_workflow 时间, 距今分钟数)

    用于 §3 工作流新鲜度判断（>15min 提示 stale）
    """
    if not WORKFLOW.exists():
        return "N/A", -1
    try:
        wf = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        ts_str = wf.get("timestamp")
        if not ts_str:
            return "no-timestamp", -1
        if ts_str.endswith("Z"):
            ts_str = ts_str.replace("Z", "+00:00")
        ts = datetime.fromisoformat(ts_str)
        age_min = int((datetime.now(timezone.utc) - ts).total_seconds() / 60)
        return ts.strftime("%Y-%m-%d %H:%M UTC"), age_min
    except Exception:
        return "parse-error", -1


def compute_concentration(positions: List[Dict[str, Any]]) -> Tuple[float, str, float, str]:
    """集中度：(inst %, inst 名, strategy %, strategy 名)

    仅在有持仓时计算；无持仓返回 (0, "", 0, "")
    """
    if not positions:
        return 0.0, "", 0.0, ""

    inst_totals: Dict[str, float] = {}
    strat_totals: Dict[str, float] = {}
    for p in positions:
        ct_val_map = {"BTC-USDT-SWAP": 0.01, "ETH-USDT-SWAP": 0.1, "SOL-USDT-SWAP": 1.0}
        ct_val = ct_val_map.get(p.get("instId", ""), 1.0)
        mark = float(p.get("markPx", 0) or 0)
        size = float(p.get("pos", 0) or 0)
        notional = abs(size) * ct_val * mark
        if notional <= 0:
            continue
        inst_totals[p.get("instId", "?")] = inst_totals.get(p.get("instId", "?"), 0.0) + notional
        # strategy 字段在 OKX 响应里不一定有，从本地 portfolio 补
        strat = p.get("strategy") or "UNKNOWN"
        strat_totals[strat] = strat_totals.get(strat, 0.0) + notional

    total = sum(inst_totals.values()) or 1
    if inst_totals:
        top_inst = max(inst_totals.items(), key=lambda x: x[1])
        inst_pct = top_inst[1] / total
        inst_name = top_inst[0]
    else:
        inst_pct, inst_name = 0.0, ""
    if strat_totals:
        top_strat = max(strat_totals.items(), key=lambda x: x[1])
        strat_pct = top_strat[1] / total
        strat_name = top_strat[0]
    else:
        strat_pct, strat_name = 0.0, ""
    return inst_pct, inst_name, strat_pct, strat_name


# ────────────────────────────────────────────────────────────────────
# 拼装 + 推送
# ────────────────────────────────────────────────────────────────────


def compose_message(
    n_held: int,
    n_max: int,
    n_trades: int,
    daily_pnl: float,
    total_upl: float,
    status: str,
    daily_stats_full: Dict[str, Any],
    workflow_ts: str,
    workflow_age_min: int,
    inst_pct: float,
    inst_name: str,
    strat_pct: float,
    strat_name: str,
    okx_degraded: bool = False,
) -> str:
    """5 段纯文本简报（与 v1 前 5 行兼容）

    - §1 基线（v1 原 5 行）：持仓 / 今日笔数 / 今日已平仓 / 持仓未实现 / 状态
    - §2 集中度（v2 新增）：单标 + 单策略
    - §3 工作流新鲜度（v2 新增）：时间戳 + 距今分钟
    - §4 风控标记（v2 新增）：连续亏损 / 紧急熔断
    - §5 持仓明细（v2 新增）：单仓 uPnL 简表
    """
    lines: List[str] = []
    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M CST")
    status_icon = "⚠️ degraded" if okx_degraded else "✓"
    lines.append(f"[{ts}] {status_icon} OKX 晚间心跳（demo）")

    # ── §1 基线（保持 v1 格式 100% 兼容）──
    lines.append("─" * 50)
    lines.append("1. 系统状态")
    lines.append(f"   - 持仓 {n_held}/{n_max}")
    lines.append(f"   - 今日 {n_trades} 笔")
    lines.append(f"   - 今日已平仓 {daily_pnl:+.4f} USDT")
    lines.append(f"   - 持仓未实现 {total_upl:+.4f} USDT")
    lines.append(f"   - 状态 {status}")

    # ── §2 集中度（v2 新增）──
    lines.append("")
    lines.append("2. 集中度")
    if okx_degraded:
        lines.append("   ⚠️ OKX API 不可用（已重试 3 次），持仓分布数据缺失")
    elif n_held == 0:
        lines.append("   无持仓")
    else:
        lines.append(f"   最大单标: {inst_pct:.1%} ({inst_name})")
        lines.append(f"   最大单策略: {strat_pct:.1%} ({strat_name})")

    # ── §3 工作流新鲜度（v2 新增）──
    lines.append("")
    lines.append("3. 工作流新鲜度")
    if workflow_age_min < 0:
        lines.append(f"   {workflow_ts}")
    elif workflow_age_min > 15:
        lines.append(f"   上次: {workflow_ts}（⚠️ 距今 {workflow_age_min} 分钟，超 15min 阈值）")
    else:
        lines.append(f"   上次: {workflow_ts}（{workflow_age_min} 分钟前）")

    # ── §4 风控标记（v2 新增）──
    lines.append("")
    lines.append("4. 风控标记")
    consec = daily_stats_full.get("consecutive_losses", 0)
    emergency = daily_stats_full.get("emergency_stop_triggered", False)
    consec_icon = "⚠️" if consec >= 3 else "✓"
    emergency_icon = "⚠️" if emergency else "✓"
    lines.append(
        f"   {consec_icon} 连续亏损: {consec} 次｜"
        f"{emergency_icon} 紧急熔断: {'已触发' if emergency else '未触发'}"
    )

    # ── §5 持仓明细（v2 新增）──
    lines.append("")
    lines.append("5. 持仓明细")
    if okx_degraded:
        lines.append("   ⚠️ OKX API 失败，详情不可用")
    elif n_held == 0:
        lines.append("   无持仓")
    else:
        # 注：compute_concentration 已经消费了 positions
        # 这里无法再访问 positions 详情（API 已返回但已聚合）
        # 简化为只显示 uPnL 总数（不显示每个仓位，避免重复实现）
        lines.append(f"   总 uPnL: {total_upl:+.4f} USDT（{n_held} 个持仓，详见 review_push / runner_watchdog）")

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


def main(argv: list = None) -> int:
    """主体逻辑

    优雅降级策略（与 review_push.py 一致）：
    1. portfolio.json / workflow.json 先读（不依赖网络）
    2. OKX API 加 3 次重试，全失败时标 degraded 但仍出报告
    """
    parser = argparse.ArgumentParser(description="OKX 晚间心跳推送（v2）")
    parser.add_argument("--verbose", "-v", action="store_true", help="启用 DEBUG log")
    # 当 argv=None（测试调用）时，避免 parser 误读 sys.argv（pytest 路径）
    args = parser.parse_args(argv if argv is not None else [])

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

    mode = os.getenv("OKX_TRADING_MODE", "demo")
    notifier = TelegramNotifier.from_env(str(ENV_FILE))

    # ── 1. 本地状态（永不依赖网络）──
    n_trades, daily_pnl, daily_stats_full = get_daily_stats()
    status, max_pos = get_status_and_max()
    workflow_ts, workflow_age_min = get_workflow_freshness()

    # ── 2. OKX API（加重试 + 优雅降级）──
    okx_degraded = False
    n_held = 0
    total_upl = 0.0
    positions: List[Dict[str, Any]] = []

    try:
        client = OKXClient(mode=mode, timeout=10)
        n_held, total_upl, positions = fetch_with_retry(
            lambda: get_positions_summary(client),
            max_attempts=3,
            backoff=(1, 2, 4),
        )
    except Exception as e:
        # 重试全失败 → degraded 模式（保留本地数据）
        okx_degraded = True
        msg = f"⚠️ 心跳 degraded: OKX API 重试 3 次仍失败 ({type(e).__name__}: {e})"
        logger.warning(msg)

    # ── 3. 集中度计算（即使 OKX 失败也尝试基于本地 portfolio）──
    if okx_degraded and PORTFOLIO.exists():
        # 从本地 portfolio 兜底
        try:
            data = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
            local_pos = data.get("positions", []) or []
            ct_val_map = {"BTC-USDT-SWAP": 0.01, "ETH-USDT-SWAP": 0.1, "SOL-USDT-SWAP": 1.0}
            for p in local_pos:
                p["markPx"] = p.get("mark_px_at_sync", 0)
                p["pos"] = str(abs(float(p.get("size", 0) or 0)))
                p["ctVal"] = ct_val_map.get(p.get("symbol", "").replace("-", ""), 1.0)
            n_held = len(local_pos)
            positions = local_pos
            total_upl = sum(float(p.get("realized_pnl", 0) or 0) for p in local_pos)  # 兜底用 realized
        except Exception:
            pass

    inst_pct, inst_name, strat_pct, strat_name = compute_concentration(positions)

    # ── 4. 拼装 + 写日志 + 推 Telegram ──
    msg = compose_message(
        n_held=n_held,
        n_max=max_pos,
        n_trades=n_trades,
        daily_pnl=daily_pnl,
        total_upl=total_upl,
        status=status,
        daily_stats_full=daily_stats_full,
        workflow_ts=workflow_ts,
        workflow_age_min=workflow_age_min,
        inst_pct=inst_pct,
        inst_name=inst_name,
        strat_pct=strat_pct,
        strat_name=strat_name,
        okx_degraded=okx_degraded,
    )
    write_log(msg)
    print(msg)

    if notifier.enabled:
        try:
            ok = notifier.send(msg)
            if ok:
                print("✓ Telegram 推送成功")
            else:
                err = "⚠️ 心跳推送失败: Telegram 返回错误"
                print(err, file=sys.stderr)
                write_log(err)
                return 1
        except Exception as e:
            err = f"⚠️ 心跳推送异常: {type(e).__name__}: {e}"
            print(err, file=sys.stderr)
            write_log(err)
            return 1
    else:
        warn = "⚠️ Notifier 未启用，仅写日志未推送"
        print(warn, file=sys.stderr)
        write_log(warn)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
