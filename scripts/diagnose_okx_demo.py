#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_okx_demo.py —— Phase 4 Gate 7：DEMO 账户 100 笔滑点抽样

═══════════════════════════════════════════════════════════════════
目的：在 LIVE 上线前，量化真实网络延迟 + 撮合延迟带来的执行价偏差
      （也就是俗称的"滑点"）。
═══════════════════════════════════════════════════════════════════

流程：
  1. 拉 DEMO 账户可用张数（最小可交易单位）
  2. 连续下 100 笔：50 笔市价（taker 滑点）+ 50 笔限价（被动成交 + 立即撤单）
  3. 每笔记录：request_px / exec_px / fill_ts / request_ts / abs_slip_bps
  4. 立即 reduce_only 平仓，不留 overnight 风险
  5. 间隔 jitter 1-3 秒避免被 OKX rate limit
  6. 持久化到 docs/agent-context/experiments/<name>-YYYYMMDD-HHMMSS/

准入红线（Phase 4 Gate 7 release gate）：
  ✅ avg_taker_slip ≤ 8bps （与 fragility_scan 配套的实证验证）
  ✅ p95_taker_slip ≤ 15bps
  ✅ order_failure_rate ≤ 5%

CLI 例子：
  python3 -m okx.scripts.diagnose_okx_demo \\
      --inst-id BTC-USDT-SWAP --n-trades 100 \\
      --name gate7-btc-2026Q3

回滚：
  rm -rf docs/agent-context/experiments/diagnose_demo-<ts>/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _load_env(env_path: Optional[Path] = None) -> None:
    """从 okx/.env 加载到 os.environ。

    与 runner_watchdog.py 保持一致：不覆盖已存在的 env（setdefault）。
    """
    if env_path is None:
        # 推断路径：scripts/diagnose_okx_demo.py → 父目录的 .env
        env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        logger.warning(f"⚠️ .env not found at {env_path}; using current process env")
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)
    logger.info(f"✅ loaded env from {env_path}")


# ──────────────── 数据结构 ────────────────


@dataclass
class SlipRecord:
    """单笔滑点记录"""

    idx: int                              # 0-based 序号
    ord_type: str                         # "market" / "limit"
    side: str                             # "buy" / "sell"
    request_px: float                     # 请求价格（限价单=挂单价；市价单=下单时 markPx）
    exec_px: Optional[float]              # 实际成交价（None = 未成交）
    fill_ts_ms: Optional[int]             # 实际成交时间戳
    request_ts_ms: int                    # 请求发起时间戳
    latency_ms: Optional[int]             # 下单到成交延迟
    abs_slip_bps: Optional[float]         # |exec - request| / request × 10000
    signed_slip_bps: Optional[float]      # (exec - request) / request × 10000（正=滑价不利方向）
    order_id: Optional[str]
    error: Optional[str] = None           # 下单失败原因

    @property
    def is_filled(self) -> bool:
        return self.exec_px is not None

    @property
    def is_taker(self) -> bool:
        return self.ord_type == "market"


# ──────────────── 核心逻辑 ────────────────


def _jitter(base_seconds: float, jitter_ratio: float = 0.5) -> float:
    """计算 jitter 间隔（base × (1 ± jitter_ratio)）"""
    import random

    delta = base_seconds * jitter_ratio
    return base_seconds + random.uniform(-delta, delta)


def diagnose_slippage(
    client: Any,
    inst_id: str,
    n_trades: int = 100,
    size_per_trade: Optional[float] = None,
    limit_offset_bps: float = 2.0,
    jitter_base_seconds: float = 2.0,
    progress_callback: Optional[Any] = None,
) -> List[SlipRecord]:
    """
    执行 N 笔真实滑点抽样（DEMO 账户）

    :param client: OKXClient
    :param inst_id: 标的，如 'BTC-USDT-SWAP'
    :param n_trades: 总笔数（市价 + 限价各 50%）
    :param size_per_trade: 单笔张数（None = 自动用最小可交易单位）
    :param limit_offset_bps: 限价单偏离 markPx 的 bps（保证快速成交）
    :param jitter_base_seconds: 下单间隔基准秒数（实际 jitter ±50%）
    :param progress_callback: 可选进度回调 (idx, record)
    :return: SlipRecord 列表
    """
    market = client.market
    trade = client.trade
    account = client.account

    # 自动选最小张数（如果未指定）
    if size_per_trade is None:
        size_per_trade = _detect_min_size(client, inst_id)

    records: List[SlipRecord] = []
    n_market = n_trades // 2
    n_limit = n_trades - n_market

    logger.info(
        "🔬 diagnose_slippage 启动: %s, n=%d (市价=%d / 限价=%d), 单笔=%g 张",
        inst_id, n_trades, n_market, n_limit, size_per_trade,
    )

    for i in range(n_trades):
        ord_type = "market" if i % 2 == 0 else "limit"
        side = "buy" if i % 4 < 2 else "sell"  # 50/50 多空

        try:
            ticker = market.get_ticker(inst_id)
            # OKX V5 /api/v5/market/ticker 返回 List[Dict]，取第一个
            if not ticker or not isinstance(ticker, list):
                raise ValueError(f"unexpected ticker payload: {type(ticker).__name__}")
            mark_px = float(ticker[0]["last"])
        except Exception as e:
            logger.error("[%d] 拉 ticker 失败: %s", i, e)
            records.append(SlipRecord(
                idx=i, ord_type=ord_type, side=side,
                request_px=0.0, exec_px=None, fill_ts_ms=None,
                request_ts_ms=int(time.time() * 1000), latency_ms=None,
                abs_slip_bps=None, signed_slip_bps=None,
                order_id=None, error=f"ticker fetch failed: {e}",
            ))
            continue

        # 计算挂单价
        if ord_type == "market":
            request_px = mark_px
        else:
            # 限价偏离 ±5bps（多 = -5bps 卖在 mark 下方；空 = +5bps 买在 mark 上方）
            offset = -limit_offset_bps / 10000 if side == "buy" else +limit_offset_bps / 10000
            request_px = mark_px * (1 + offset)

        request_ts = int(time.time() * 1000)

        # 下单（SWAP 永续合约：td_mode 必须是 isolated/cross，long_short_mode 必传 posSide）
        pos_side = "long" if side == "buy" else "short"
        try:
            if ord_type == "market":
                order = trade.place_order(
                    inst_id=inst_id, side=side, ord_type="market",
                    sz=str(size_per_trade), td_mode="isolated",
                    pos_side=pos_side,
                )
            else:
                order = trade.place_order(
                    inst_id=inst_id, side=side, ord_type="limit",
                    sz=str(size_per_trade), td_mode="isolated",
                    pos_side=pos_side,
                    px=f"{request_px:.2f}",
                )
            # OKX V5 /api/v5/trade/order 返回 List[Dict]，取第一个
            if isinstance(order, list):
                order = order[0] if order else {}
            order_id = order.get("ordId") if isinstance(order, dict) else None
        except Exception as e:
            logger.error("[%d] 下单失败: %s", i, e)
            records.append(SlipRecord(
                idx=i, ord_type=ord_type, side=side,
                request_px=request_px, exec_px=None, fill_ts_ms=None,
                request_ts_ms=request_ts, latency_ms=None,
                abs_slip_bps=None, signed_slip_bps=None,
                order_id=None, error=str(e),
            ))
            continue

        # 等成交（限价单 1.5s 超时未成交 → 撤单）
        exec_px = None
        fill_ts = None
        deadline = request_ts + 1500 if ord_type == "limit" else request_ts + 5000

        while int(time.time() * 1000) < deadline:
            time.sleep(0.05)
            try:
                status = trade.get_order(inst_id, order_id)
                # OKX V5 /api/v5/trade/order 返回 List[Dict]
                if isinstance(status, list):
                    status = status[0] if status else {}
                if not isinstance(status, dict):
                    continue
                state = status.get("state", "")
                if state in ("filled", "partially_filled"):
                    fill_px = float(status.get("avgPx") or status.get("fillPx") or 0)
                    fill_ts_str = status.get("fillTime") or status.get("uTime")
                    if fill_px > 0:
                        exec_px = fill_px
                    if fill_ts_str:
                        fill_ts = int(fill_ts_str)
                    break
                elif state in ("canceled", "failed", "rejected"):
                    break
            except Exception as e:
                logger.warning("[%d] 查订单状态失败: %s", i, e)

        # 限价单超时撤单
        if ord_type == "limit" and exec_px is None:
            try:
                trade.cancel_order(inst_id, order_id)
            except Exception:
                pass

        # 计算滑点
        abs_slip_bps = None
        signed_slip_bps = None
        latency_ms = None
        if exec_px is not None and request_px > 0:
            signed_bps = (exec_px - request_px) / request_px * 10000
            # 调整方向：买入 = 正不利；卖出 = 负不利
            if side == "buy":
                signed_slip_bps = signed_bps  # 买高了 = 正
            else:
                signed_slip_bps = -signed_bps  # 卖低了 = 正（cost more）
            abs_slip_bps = abs(signed_slip_bps)
        if fill_ts is not None:
            latency_ms = fill_ts - request_ts

        rec = SlipRecord(
            idx=i, ord_type=ord_type, side=side,
            request_px=request_px, exec_px=exec_px,
            fill_ts_ms=fill_ts, request_ts_ms=request_ts,
            latency_ms=latency_ms,
            abs_slip_bps=abs_slip_bps,
            signed_slip_bps=signed_slip_bps,
            order_id=order_id,
        )
        records.append(rec)

        if progress_callback:
            progress_callback(i, rec)

        # ── reduce_only 平仓（不隔夜持仓）──
        if exec_px is not None and ord_type == "market":
            # 市价单已成交 → 立即下 reduce_only 反向单平仓
            close_side = "sell" if side == "buy" else "buy"
            try:
                close_order = trade.place_order(
                    inst_id=inst_id, side=close_side, ord_type="market",
                    sz=str(size_per_trade), td_mode="isolated",
                    pos_side=pos_side, reduce_only=True,
                )
                if isinstance(close_order, list):
                    close_order = close_order[0] if close_order else {}
                logger.info("[%d] reduce_only 平仓完成 ordId=%s", i, close_order.get("ordId"))
            except Exception as e:
                logger.warning("[%d] reduce_only 平仓失败: %s", i, e)

        # jitter
        if i < n_trades - 1:
            time.sleep(_jitter(jitter_base_seconds))

    logger.info(
        "✅ diagnose_slippage 完成: filled=%d / total=%d (%.1f%%)",
        sum(1 for r in records if r.is_filled),
        len(records),
        100 * sum(1 for r in records if r.is_filled) / max(len(records), 1),
    )
    return records


def _detect_min_size(client: Any, inst_id: str) -> float:
    """自动探测最小可交易张数（从 instruments API 拿 minSz）"""
    try:
        inst = client.public.get_instrument(inst_id)
        min_sz = float(inst.get("minSz", 0.01))
        return max(min_sz, 0.01)
    except Exception as e:
        logger.warning("探测 min_sz 失败，用 0.01 兜底: %s", e)
        return 0.01


# ──────────────── 统计与报告 ────────────────


def compute_stats(records: List[SlipRecord]) -> Dict[str, Any]:
    """计算滑点统计（按 ord_type 切分）"""
    stats: Dict[str, Any] = {"by_type": {}, "overall": {}}

    for ord_type in ["market", "limit"]:
        typed = [r for r in records if r.ord_type == ord_type and r.is_filled]
        if not typed:
            stats["by_type"][ord_type] = {"count": 0}
            continue
        slips = [r.signed_slip_bps for r in typed if r.signed_slip_bps is not None]
        abs_slips = [r.abs_slip_bps for r in typed if r.abs_slip_bps is not None]
        latencies = [r.latency_ms for r in typed if r.latency_ms is not None]
        stats["by_type"][ord_type] = {
            "count": len(typed),
            "fill_rate": len(typed) / max(sum(1 for r in records if r.ord_type == ord_type), 1),
            "avg_slip_bps": statistics.mean(slips) if slips else None,
            "avg_abs_slip_bps": statistics.mean(abs_slips) if abs_slips else None,
            "median_abs_slip_bps": statistics.median(abs_slips) if abs_slips else None,
            "p95_abs_slip_bps": _percentile(abs_slips, 95) if abs_slips else None,
            "p99_abs_slip_bps": _percentile(abs_slips, 99) if abs_slips else None,
            "max_abs_slip_bps": max(abs_slips) if abs_slips else None,
            "avg_latency_ms": statistics.mean(latencies) if latencies else None,
            "p95_latency_ms": _percentile(latencies, 95) if latencies else None,
        }

    all_filled = [r for r in records if r.is_filled]
    stats["overall"] = {
        "total_orders": len(records),
        "filled": len(all_filled),
        "failed": sum(1 for r in records if not r.is_filled),
        "fill_rate": len(all_filled) / max(len(records), 1),
    }
    return stats


def _percentile(xs: List[float], p: float) -> Optional[float]:
    """计算百分位数（无 numpy 依赖）"""
    if not xs:
        return None
    s = sorted(xs)
    idx = int(len(s) * p / 100)
    idx = min(max(idx, 0), len(s) - 1)
    return s[idx]


def check_release_gates(stats: Dict[str, Any]) -> Dict[str, bool]:
    """Gate 7 release 红线判定"""
    market_stats = stats["by_type"].get("market", {})
    return {
        "avg_taker_slip_le_8bps": (market_stats.get("avg_abs_slip_bps") or 999) <= 8.0,
        "p95_taker_slip_le_15bps": (market_stats.get("p95_abs_slip_bps") or 999) <= 15.0,
        "fill_rate_ge_90pct": stats["overall"].get("fill_rate", 0) >= 0.90,
    }


def format_report(
    inst_id: str,
    records: List[SlipRecord],
    stats: Dict[str, Any],
    gates: Dict[str, bool],
) -> str:
    """格式化诊断报告（Markdown）"""
    lines = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines.append(f"# Phase 4 Gate 7 · DEMO 滑点抽样报告")
    lines.append(f"")
    lines.append(f"**标的**: `{inst_id}`")
    lines.append(f"**时间**: {ts}")
    lines.append(f"**总笔数**: {stats['overall']['total_orders']}（市价 50% + 限价 50%）")
    lines.append(f"**成交率**: {stats['overall']['fill_rate']:.1%} ({stats['overall']['filled']} / {stats['overall']['total_orders']})")
    lines.append(f"")

    # Release gates
    lines.append(f"## 🚦 Release Gate 判定")
    lines.append(f"")
    for name, passed in gates.items():
        emoji = "✅" if passed else "❌"
        lines.append(f"- {emoji} **{name}**: `{passed}`")
    lines.append(f"")

    # 按类型统计
    lines.append(f"## 📊 按订单类型统计")
    lines.append(f"")
    lines.append(f"| 指标 | 市价 (Taker) | 限价 (Maker) |")
    lines.append(f"|---|---|---|")
    for metric_key, label in [
        ("count", "成交笔数"),
        ("fill_rate", "成交率"),
        ("avg_abs_slip_bps", "平均绝对滑点 (bps)"),
        ("median_abs_slip_bps", "中位绝对滑点"),
        ("p95_abs_slip_bps", "p95 绝对滑点"),
        ("p99_abs_slip_bps", "p99 绝对滑点"),
        ("max_abs_slip_bps", "最大绝对滑点"),
        ("avg_latency_ms", "平均延迟 (ms)"),
        ("p95_latency_ms", "p95 延迟 (ms)"),
    ]:
        market_val = stats["by_type"].get("market", {}).get(metric_key)
        limit_val = stats["by_type"].get("limit", {}).get(metric_key)
        m_str = f"{market_val:.2f}" if isinstance(market_val, (int, float)) else "-"
        l_str = f"{limit_val:.2f}" if isinstance(limit_val, (int, float)) else "-"
        lines.append(f"| {label} | {m_str} | {l_str} |")
    lines.append(f"")

    # 失败明细
    failed = [r for r in records if not r.is_filled]
    if failed:
        lines.append(f"## ⚠️ 失败明细 ({len(failed)} 笔)")
        lines.append(f"")
        for r in failed[:10]:
            lines.append(f"- idx={r.idx} {r.ord_type}/{r.side}: {r.error or 'no fill'}")
        if len(failed) > 10:
            lines.append(f"- ...（共 {len(failed)} 笔失败，详见 records.json）")
        lines.append(f"")

    return "\n".join(lines)


# ──────────────── 持久化 ────────────────


def persist_experiment(
    inst_id: str,
    records: List[SlipRecord],
    stats: Dict[str, Any],
    gates: Dict[str, bool],
    name: str,
    out_root: Optional[str] = None,
) -> Path:
    """持久化实验结果（4 件套）"""
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = Path(out_root or "okx/docs/agent-context/experiments")
    exp_dir = base / f"diagnose_demo-{name}-{ts_str}"
    exp_dir.mkdir(parents=True, exist_ok=True)

    # result.md
    report = format_report(inst_id, records, stats, gates)
    (exp_dir / "result.md").write_text(report, encoding="utf-8")

    # records.json
    records_json = [asdict(r) for r in records]
    (exp_dir / "records.json").write_text(
        json.dumps(records_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # meta.json
    meta = {
        "name": name,
        "inst_id": inst_id,
        "timestamp_utc": ts_str,
        "total_records": len(records),
        "gates_passed": all(gates.values()),
        "gates": gates,
        "stats": stats,
    }
    (exp_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # scan.py（实验本身）
    this_file = Path(__file__)
    (exp_dir / "scan.py").write_text(this_file.read_text(encoding="utf-8"), encoding="utf-8")

    return exp_dir


# ──────────────── CLI ────────────────


def main():
    parser = argparse.ArgumentParser(description="Phase 4 Gate 7 DEMO 滑点抽样")
    parser.add_argument("--inst-id", default="BTC-USDT-SWAP", help="标的")
    parser.add_argument("--n-trades", type=int, default=100, help="总笔数（默认 100）")
    parser.add_argument("--size", type=float, default=None, help="单笔张数（默认自动探测 minSz）")
    parser.add_argument("--limit-offset-bps", type=float, default=2.0, help="限价偏离 bps（默认 2bps 提高 fill rate）")
    parser.add_argument("--jitter-seconds", type=float, default=2.0, help="下单间隔基准秒数")
    parser.add_argument("--name", required=True, help="实验名")
    parser.add_argument("--out-root", default=None, help="输出根目录")
    parser.add_argument("--dry-run", action="store_true", help="只统计不下单（mock 测试）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 加载 .env（保证 OKX_DEMO_* / OKX_TRADING_MODE 在 process env 中）
    _load_env()

    if args.dry_run:
        logger.info("🔸 dry-run 模式：生成 100 条 mock 记录用于测试")
        records = _mock_records(args.n_trades)
        stats = compute_stats(records)
        gates = check_release_gates(stats)
        exp_dir = persist_experiment(args.inst_id, records, stats, gates, args.name, args.out_root)
        print(f"\n📁 报告: {exp_dir}/result.md")
        print(format_report(args.inst_id, records, stats, gates))
        return

    from okx.code.client import OKXClient

    client = OKXClient()
    logger.info(f"Mode: {'DEMO' if client.demo else '⚠️ LIVE MODE'}")

    if not client.demo:
        logger.error("❌ 必须 DEMO 模式运行！设置 OKX_TRADING_MODE=demo")
        sys.exit(1)

    records = diagnose_slippage(
        client=client,
        inst_id=args.inst_id,
        n_trades=args.n_trades,
        size_per_trade=args.size,
        limit_offset_bps=args.limit_offset_bps,
        jitter_base_seconds=args.jitter_seconds,
    )
    stats = compute_stats(records)
    gates = check_release_gates(stats)

    exp_dir = persist_experiment(args.inst_id, records, stats, gates, args.name, args.out_root)

    print(f"\n📁 报告: {exp_dir}/")
    print(format_report(args.inst_id, records, stats, gates))

    if all(gates.values()):
        print(f"\n🎉 Gate 7 ALL PASSED ✅")
        sys.exit(0)
    else:
        print(f"\n⚠️ Gate 7 NOT PASSED ❌（see gates above）")
        sys.exit(2)


def _mock_records(n: int) -> List[SlipRecord]:
    """生成 mock 记录（用于测试 report/stats 逻辑）"""
    import random
    records = []
    for i in range(n):
        ord_type = "market" if i % 2 == 0 else "limit"
        side = "buy" if i % 4 < 2 else "sell"
        request_px = 60000.0 + i * 0.1
        # mock：市价单 3-7bps 滑点；限价单 0-3bps（成交价 = 挂单价）
        if ord_type == "market":
            signed_slip = random.uniform(3, 7) if side == "buy" else random.uniform(-7, -3)
            exec_px = request_px * (1 + signed_slip / 10000)
        else:
            exec_px = request_px
            signed_slip = 0.0
        signed_slip_bps = abs(signed_slip) if side == "buy" else -abs(signed_slip)
        # 修正方向语义
        if side == "buy":
            signed_slip_bps = (exec_px - request_px) / request_px * 10000
        else:
            signed_slip_bps = -(exec_px - request_px) / request_px * 10000
        records.append(SlipRecord(
            idx=i, ord_type=ord_type, side=side,
            request_px=request_px, exec_px=exec_px,
            fill_ts_ms=int(time.time() * 1000),
            request_ts_ms=int(time.time() * 1000) - 50,
            latency_ms=random.randint(40, 200),
            abs_slip_bps=abs(signed_slip_bps),
            signed_slip_bps=signed_slip_bps,
            order_id=f"mock-{i}",
        ))
    return records


if __name__ == "__main__":
    main()