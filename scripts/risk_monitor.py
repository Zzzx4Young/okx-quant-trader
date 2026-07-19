# -*- coding: utf-8 -*-
"""
OKX 仓位风险监控核心（OKX 数据拉取 + 指标计算 + 阈值检查）

调用顺序：
    1. fetch_snapshot(okx_client, portfolio_path) → (positions, equity, api_status)
    2. compute_metrics(positions, equity)         → RiskMetrics
    3. check_thresholds(metrics, thresholds)      → List[RiskIssue]
    4. format_report(metrics, issues)             → str（Telegram/log 友好）

设计原则：
    - 所有计算函数是纯函数（除 IO 函数），单测无需 mock OKX
    - API 失败 = degraded 模式（指标全 0 + api_status="failed"），不静默
    - ctVal 优先用 OKX instruments API，查不到时 fallback 到常见映射
"""

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from okx.scripts.risk_thresholds import (
    RISK_THRESHOLDS,
    PositionRisk,
    RiskMetrics,
    RiskIssue,
    RiskThreshold,
    get_threshold,
)

logger = logging.getLogger(__name__)


# ──────────── ctVal 兜底（OKX instruments API 拉不到时用） ────────────


COMMON_CTVAL: Dict[str, float] = {
    # 主流 USDT-SWAP 合约面值（每张多少标的）
    "BTC-USDT-SWAP": 0.01,
    "ETH-USDT-SWAP": 0.1,
    "SOL-USDT-SWAP": 1.0,
    "XRP-USDT-SWAP": 100.0,
    "DOGE-USDT-SWAP": 1000.0,
    "ADA-USDT-SWAP": 100.0,
    "AVAX-USDT-SWAP": 1.0,
    "LINK-USDT-SWAP": 1.0,
    "MATIC-USDT-SWAP": 100.0,
    "DOT-USDT-SWAP": 1.0,
    "LTC-USDT-SWAP": 0.1,
    "TRX-USDT-SWAP": 1000.0,
}


# ──────────── Layer 2: 实时快照 ────────────


def _safe_float(v: Any, default: float = 0.0) -> float:
    """OKX API 返回的数值大多是字符串，统一转 float"""
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _normalize_inst_id(s: str) -> str:
    """instId 归一化：BTC-USDT-SWAP ↔ BTCUSDTSWAP 双向兼容

    OKX API 返回 "BTC-USDT-SWAP"，本地 portfolio.json 存 "BTCUSDTSWAP"
    """
    return s.upper().replace("-", "").replace("_", "").strip()


def _match_strategy(
    portfolio_path: Optional[Path],
    inst_id: str,
    pos_side: str,
) -> str:
    """从本地 portfolio.json 匹配策略名（best effort）

    支持字段组合：
      - instId: "instId" / "symbol"（两种命名）
      - side:   "posSide" / "side" / "direction"（三种命名）
      - 格式:   OKX "BTC-USDT-SWAP" ↔ 本地 "BTCUSDTSWAP"（自动归一化）
    """
    if not portfolio_path or not portfolio_path.exists():
        return "UNKNOWN"
    try:
        with open(portfolio_path) as f:
            data = json.load(f)
        positions = data.get("positions", []) or []
        target_inst = _normalize_inst_id(inst_id)
        target_side = pos_side.lower().strip()
        for p in positions:
            p_inst = p.get("instId", "") or p.get("symbol", "")
            p_side = (
                p.get("posSide")
                or p.get("side")
                or p.get("direction")
                or ""
            ).lower().strip()
            if _normalize_inst_id(p_inst) == target_inst and p_side == target_side:
                return p.get("strategy", "UNKNOWN")
    except Exception as e:
        logger.debug(f"读 portfolio.json 失败: {e}")
    return "UNKNOWN"


def _extract_sl_tp(pos_dict: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """从 OKX position 响应提取 SL/TP（attachAlgoOrds 数组）"""
    sl_px = None
    tp_px = None
    algo_ords = pos_dict.get("attachAlgoOrds") or []
    for algo in algo_ords:
        sl = algo.get("slTriggerPx")
        tp = algo.get("tpTriggerPx")
        if sl and sl != "":
            try:
                sl_px = float(sl)
            except (ValueError, TypeError):
                pass
        if tp and tp != "":
            try:
                tp_px = float(tp)
            except (ValueError, TypeError):
                pass
    return sl_px, tp_px


def fetch_snapshot(
    okx_client: Any,
    portfolio_path: Optional[Path] = None,
) -> Tuple[List[PositionRisk], float, str]:
    """从 OKX API 拉取实时仓位快照

    :param okx_client: OKXClient 实例（提供 .account.get_balance / .account.get_positions）
    :param portfolio_path: 本地 portfolio.json 路径（用于策略归因，可选）
    :return: (positions, equity_usd, api_status)
        api_status: "ok" / "degraded" / "failed"
    """
    try:
        # ── 1. 账户余额 ──
        balance_resp = okx_client.account.get_balance(ccy="USDT")
        if not balance_resp or not isinstance(balance_resp, list):
            logger.warning("账户余额响应为空或格式异常")
            equity_usd = 0.0
            api_status = "degraded"
        else:
            # OKX 返回 list，取第一个元素的 totalEq
            total_eq = balance_resp[0].get("totalEq", "0") if balance_resp else "0"
            equity_usd = _safe_float(total_eq)
            api_status = "ok"

        # ── 2. 持仓列表 ──
        positions_resp = okx_client.account.get_positions(inst_type="SWAP")
        positions: List[PositionRisk] = []
        # 区分三种情况：
        #   - None / 非 list  → API 异常 → degraded
        #   - []              → API 正常但无持仓 → ok（合法状态）
        if positions_resp is None or not isinstance(positions_resp, list):
            logger.warning("持仓响应为 None 或格式异常")
            if api_status == "ok":
                api_status = "degraded"
            return positions, equity_usd, api_status

        for p in positions_resp:
            # 过滤空仓（pos="0" 或 "0.0"）
            pos_str = p.get("pos", "0")
            if not pos_str or _safe_float(pos_str) == 0.0:
                continue

            inst_id = p.get("instId", "")
            pos_side = p.get("posSide", "net")
            size = _safe_float(pos_str)
            ct_val = COMMON_CTVAL.get(inst_id, 1.0)  # fallback 1.0
            if inst_id not in COMMON_CTVAL:
                logger.debug(f"未知 ctVal: {inst_id}，使用 fallback 1.0")

            pr = PositionRisk(
                inst_id=inst_id,
                pos_side=pos_side,
                size=size,
                ct_val=ct_val,
                avg_px=_safe_float(p.get("avgPx")),
                mark_px=_safe_float(p.get("markPx")),
                upl=_safe_float(p.get("upl")),
                margin=_safe_float(p.get("margin")),
                liq_px=_safe_float(p.get("liqPx"), default=0.0) or None,
                leverage=_safe_float(p.get("lever"), default=1.0),
                strategy=_match_strategy(portfolio_path, inst_id, pos_side),
            )
            # SL/TP
            pr.sl_px, pr.tp_px = _extract_sl_tp(p)
            # 重新触发 __post_init__（dataclass 不会自动重算）
            pr.notional_usd = abs(pr.size) * pr.ct_val * pr.mark_px
            if pr.margin > 0:
                pr.upl_pct_of_margin = pr.upl / pr.margin
            positions.append(pr)

        return positions, equity_usd, api_status

    except Exception as e:
        logger.exception(f"fetch_snapshot 失败: {e}")
        return [], 0.0, "failed"


# ──────────── Layer 3: 指标计算 ────────────


def compute_metrics(
    positions: List[PositionRisk],
    equity_usd: float,
    api_status: str = "ok",
) -> RiskMetrics:
    """聚合风险指标

    无持仓时返回全零/默认值的 RiskMetrics（不会误报）。
    """
    m = RiskMetrics(equity_usd=equity_usd, api_status=api_status)

    if not positions or equity_usd <= 0:
        m.position_count = 0
        return m

    # ── 总名义 / 净名义 / uPnL ──
    total_notional = sum(p.notional_usd for p in positions)
    net_notional = 0.0
    total_upl = 0.0
    used_margin = 0.0

    for p in positions:
        # 净名义：多仓为正，空仓为负
        sign = 1.0 if p.is_long else -1.0
        net_notional += sign * p.notional_usd
        total_upl += p.upl
        used_margin += p.margin

    m.total_notional_usd = total_notional
    m.net_notional_usd = net_notional
    m.total_upl_usd = total_upl
    m.used_margin_usd = used_margin
    m.gross_leverage = total_notional / equity_usd
    m.net_leverage = abs(net_notional) / equity_usd
    m.upl_pct = total_upl / equity_usd
    m.equity_buffer_pct = max(0.0, (equity_usd - used_margin) / equity_usd)

    # ── 集中度（按 inst_id / strategy） ──
    inst_totals: Dict[str, float] = {}
    strat_totals: Dict[str, float] = {}
    for p in positions:
        inst_totals[p.inst_id] = inst_totals.get(p.inst_id, 0.0) + p.notional_usd
        strat_totals[p.strategy] = strat_totals.get(p.strategy, 0.0) + p.notional_usd

    m.position_breakdown = inst_totals
    m.strategy_breakdown = strat_totals
    m.position_count = len(positions)

    if inst_totals:
        top_inst = max(inst_totals.items(), key=lambda x: x[1])
        m.inst_concentration = top_inst[1] / total_notional
        m.inst_concentration_target = top_inst[0]
    if strat_totals:
        top_strat = max(strat_totals.items(), key=lambda x: x[1])
        m.strategy_concentration = top_strat[1] / total_notional
        m.strategy_concentration_target = top_strat[0]

    # ── 最小强平距离 ──
    liq_dists = [(p.liq_distance_pct, p.inst_id) for p in positions if p.liq_distance_pct is not None]
    if liq_dists:
        min_dist, min_inst = min(liq_dists, key=lambda x: x[0])
        m.min_liq_distance_pct = min_dist
        m.min_liq_target = min_inst

    # ── 最大 SL 已走比例 ──
    sl_consumed = [(p.sl_consumed_pct, p.inst_id) for p in positions if p.sl_consumed_pct is not None]
    if sl_consumed:
        max_sl, sl_inst = max(sl_consumed, key=lambda x: x[0])
        m.max_sl_consumed_pct = max_sl
        m.max_sl_target = sl_inst

    return m


# ──────────── Layer 4: 阈值检查 ────────────


def _make_issue(check: str, level: str, message: str, value: float, threshold: RiskThreshold) -> RiskIssue:
    return RiskIssue(
        check=check,
        level=level,
        message=message,
        metric_value=value,
        threshold=threshold.crit if level == "critical" else threshold.warn,
        direction=threshold.direction,
    )


def check_thresholds(
    metrics: RiskMetrics,
    thresholds: Optional[Dict[str, RiskThreshold]] = None,
) -> List[RiskIssue]:
    """对照阈值表检查所有指标，返回触发的 issue 列表"""
    thresholds = thresholds or RISK_THRESHOLDS
    issues: List[RiskIssue] = []

    def _check(name: str, value: float, fmt: str = "{:.2f}") -> None:
        if name not in thresholds:
            return
        t = thresholds[name]
        triggered_level = None
        if t.direction == "high":
            if value >= t.crit:
                triggered_level = "critical"
            elif value >= t.warn:
                triggered_level = "warning"
        elif t.direction == "low":
            if value <= t.crit:
                triggered_level = "critical"
            elif value <= t.warn:
                triggered_level = "warning"
        if triggered_level:
            # structural 指标（集中度）override level = "structural"
            # watchdog 会只写日志不发 Telegram（避免告警噪声）
            final_level = "structural" if t.structural else triggered_level
            msg = f"{t.description}: {fmt.format(value)}（阈值 {t.direction} {fmt.format(t.crit if triggered_level=='critical' else t.warn)}）"
            issues.append(_make_issue(name, final_level, msg, value, t))

    if metrics.position_count == 0:
        return issues  # 无持仓不检查

    _check("gross_leverage", metrics.gross_leverage, "{:.2f}x")
    _check("net_leverage", metrics.net_leverage, "{:.2f}x")
    _check("upl_pct", metrics.upl_pct, "{:.2%}")
    _check("inst_concentration", metrics.inst_concentration, "{:.1%}")
    _check("strategy_concentration", metrics.strategy_concentration, "{:.1%}")
    _check("liq_proximity_pct", metrics.min_liq_distance_pct, "{:.2%}")
    _check("sl_consumed_pct", metrics.max_sl_consumed_pct, "{:.1%}")
    _check("min_equity_buffer", metrics.equity_buffer_pct, "{:.1%}")

    return issues


# ──────────── Layer 5: 报告格式化 ────────────


def _fmt_usd(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x:.2%}"


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_report(
    metrics: RiskMetrics,
    issues: List[RiskIssue],
    mode: str = "demo",
    include_dashboard: bool = True,
) -> str:
    """格式化 watchdog 输出

    - 健康时：单行 + 完整仪表板
    - 异常时：仪表板 + issue 列表
    """
    lines: List[str] = []
    ts = _now_utc_str()

    if metrics.api_status != "ok":
        lines.append(f"⚠️ [{ts}] API 状态: {metrics.api_status.upper()} | {metrics.api_error or '数据获取失败'}")
        if metrics.api_status == "failed":
            lines.append("本次跳过仓位风险检查，仅保留进程健康检查。")
            return "\n".join(lines)

    if metrics.position_count == 0:
        lines.append(f"[{ts}] ✓ 健康（无持仓） | 账户净值: {_fmt_usd(metrics.equity_usd)}")
        return "\n".join(lines)

    # ── 头部 ──
    critical_count = sum(1 for i in issues if i.level == "critical")
    warn_count = sum(1 for i in issues if i.level == "warning")
    if critical_count > 0:
        status_icon = f"🚨 异常（{critical_count} critical / {warn_count} warning）"
    elif warn_count > 0:
        status_icon = f"⚠️  注意（{warn_count} warning）"
    else:
        status_icon = "✓ 健康"
    lines.append(f"[{ts}] {status_icon} | 模式: {mode}")
    lines.append("")

    # ── 仪表板 ──
    if include_dashboard:
        lines.append("─" * 50)
        lines.append("📊 仓位风险仪表板")
        lines.append("─" * 50)
        lines.append(f"💰 账户净值:    {_fmt_usd(metrics.equity_usd)}")
        lines.append(f"📦 已用保证金:  {_fmt_usd(metrics.used_margin_usd)} ({_fmt_pct(1 - metrics.equity_buffer_pct)})")
        lines.append(f"💵 净值缓冲:    {_fmt_pct(metrics.equity_buffer_pct)}")
        lines.append("")
        lines.append(f"📐 总名义敞口:  {_fmt_usd(metrics.total_notional_usd)}")
        lines.append(f"⚖️  毛杠杆:     {metrics.gross_leverage:.2f}x")
        lines.append(f"📍 净敞口:      {_fmt_usd(metrics.net_notional_usd)}（{metrics.net_leverage:.2f}x）")
        upl_str = _fmt_usd(metrics.total_upl_usd)
        upl_pct_str = _fmt_pct(metrics.upl_pct)
        lines.append(f"📈 总 uPnL:    {upl_str} ({upl_pct_str})")
        lines.append("")
        if metrics.position_breakdown:
            lines.append(f"🎯 最大单标占比: {_fmt_pct(metrics.inst_concentration)} ({metrics.inst_concentration_target or '-'})")
            lines.append(f"🧠 最大单策略:   {_fmt_pct(metrics.strategy_concentration)} ({metrics.strategy_concentration_target or '-'})")
        if metrics.min_liq_target:
            lines.append(f"🛑 最小强平距离: {_fmt_pct(metrics.min_liq_distance_pct)} ({metrics.min_liq_target})")
        if metrics.max_sl_target:
            lines.append(f"📏 最大 SL 已走: {_fmt_pct(metrics.max_sl_consumed_pct)} ({metrics.max_sl_target})")
        lines.append(f"📋 持仓数:       {metrics.position_count}")
        lines.append("─" * 50)

    # ── Issue 列表 ──
    if issues:
        lines.append("")
        lines.append("🔍 触发的检查项:")
        for issue in issues:
            icon = "❌" if issue.level == "critical" else "⚠️ "
            lines.append(f"  {icon} [{issue.level.upper()}] {issue.check}: {issue.message}")
        lines.append("")

    return "\n".join(lines)


# ──────────── Telegram 告警格式 ────────────


def format_telegram_alert(issues: List[RiskIssue], metrics: RiskMetrics, mode: str) -> str:
    """Telegram 告警消息（HTML 格式，只发 critical）"""
    critical = [i for i in issues if i.level == "critical"]
    warning = [i for i in issues if i.level == "warning"]

    if not critical:
        return ""  # 没有 critical 不发

    lines: List[str] = [f"🚨 <b>OKX 仓位风险告警</b>（{mode.upper()}）", ""]

    for issue in critical:
        lines.append(f"❌ <b>{issue.check}</b>: {issue.message}")

    if warning:
        lines.append("")
        lines.append("<b>⚠️ 警告</b>")
        for issue in warning[:5]:  # 最多列 5 个 warning，避免太长
            lines.append(f"  • {issue.check}: {issue.message}")

    lines.append("")
    lines.append(f"📊 <b>快照</b>")
    lines.append(f"  净值: {_fmt_usd(metrics.equity_usd)} | 毛杠杆: {metrics.gross_leverage:.2f}x | uPnL: {_fmt_usd(metrics.total_upl_usd)} ({_fmt_pct(metrics.upl_pct)})")
    if metrics.min_liq_target:
        lines.append(f"  最小强平距离: {_fmt_pct(metrics.min_liq_distance_pct)} ({metrics.min_liq_target})")
    lines.append("")
    lines.append(f"⏰ {_now_utc_str()}")

    return "\n".join(lines)
