#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward Analysis —— 滚动窗口跨 regime 稳健性扫描

═══════════════════════════════════════════════════════════════════
目的：把历史 K 线切成滚动窗口，对每个窗口独立跑 fragility_scan，
     回答"策略在牛市 / 震荡市 / 熊市 表现是否一致"。
═══════════════════════════════════════════════════════════════════

设计：
- 复用 fragility_scan 的 grid_scan() + persist()（Phase 0 patch 后者含 git_commit + per-cell parquet）
- 每个窗口产出完整 fragility_scan 目录（cells/equity.parquet + trades.parquet）
- walkforward 自己写 meta.json（含 per-window summary table）+ result.md（跨窗口一致性分析）

CLI 例子
═══════════════════════════════════════════════════════════════════
# 3 月窗口 + 1 月 stride，BTC 1h × 策略 C
python3 -m okx.scripts.walkforward \\
    --strategy C --symbol BTC-USDT-SWAP --bar 1h \\
    --window-days 90 --stride-days 30 \\
    --slippage-bps 5,10,15 --fee-bps 5.5 \\
    --leverage 5 \\
    --name c-btc-wf-3m1m

# 短窗口快速测试（7d window + 1d stride）
python3 -m okx.scripts.walkforward \\
    --strategy A --symbol BTC-USDT-SWAP --bar 1h \\
    --window-days 7 --stride-days 1 \\
    --slippage-bps 5 --fee-bps 5.5 \\
    --name a-btc-wf-smoke

═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

import pandas as pd

# 复用 fragility_scan 的所有工具
from okx.scripts.fragility_scan import (
    resolve_strategy,
    parse_int_list,
    parse_float_list,
    load_calibration_defaults,
    grid_scan,
    persist,
    viability,
    render_markdown,
    render_text_log,
    _HERE,
)


# ────────────────────────────────────────────────────────────────────
# 类型与辅助函数
# ────────────────────────────────────────────────────────────────────
@dataclass
class WindowSpec:
    """单个滚动窗口的元数据。"""
    idx: int
    start_ts: int
    end_ts: int


@dataclass
class WindowSummary:
    """单窗口的聚合指标（写入 walkforward meta.json + result.md）。"""
    idx: int
    start_ts: int
    end_ts: int
    bar_count: int
    buy_hold_ret_pct: float
    viable_count: int
    total_cells: int
    best_ret_pct: float
    best_sharpe: float
    best_slip_bps: int
    best_fee_bps: float
    worst_ret_pct: float
    ret_spread_pct: float          # best - worst


def _ms_to_iso(ts_ms: int) -> str:
    """毫秒 → ISO 8601（带时区）。"""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()


def _window_dir_label(spec: WindowSpec) -> str:
    """文件目录名：w00_2024-10-27_2025-01-25。"""
    start_iso = _ms_to_iso(spec.start_ts)[:10]
    end_iso = _ms_to_iso(spec.end_ts)[:10]
    return f"w{spec.idx:02d}_{start_iso}_{end_iso}"


def generate_windows(
    data_start_ms: int,
    data_end_ms: int,
    window_days: int,
    stride_days: int,
) -> List[WindowSpec]:
    """生成滚动窗口列表（毫秒戳，闭区间 [start, end]）。

    :param data_start_ms: 数据最早时间戳（ms）
    :param data_end_ms: 数据最晚时间戳（ms）
    :param window_days: 窗口长度（天）
    :param stride_days: 滑动步长（天）
    :return: List[WindowSpec]，按 start_ts 升序
    :raises ValueError: window_days > data range / stride_days <= 0
    """
    if stride_days <= 0:
        raise ValueError(f"stride_days 必须 > 0，got {stride_days}")
    if window_days <= 0:
        raise ValueError(f"window_days 必须 > 0，got {window_days}")

    day_ms = 86400 * 1000
    window_ms = window_days * day_ms
    stride_ms = stride_days * day_ms

    total_span = data_end_ms - data_start_ms
    if total_span < window_ms:
        raise ValueError(
            f"数据跨度 {(total_span/day_ms):.1f}d 小于窗口长度 {window_days}d，无法生成任何窗口"
        )

    windows: List[WindowSpec] = []
    idx = 0
    start = data_start_ms
    while start + window_ms <= data_end_ms:
        windows.append(WindowSpec(
            idx=idx,
            start_ts=start,
            end_ts=start + window_ms,
        ))
        idx += 1
        start += stride_ms

    return windows


def compute_buy_hold_ret(
    klines: pd.DataFrame,
    leverage: int = 1,
) -> float:
    """简单 buy-and-hold 收益（%），无资金费率/手续费近似。

    用途：walkforward 每个窗口跑出来跟策略比，判断 viable。
    用 unleveraged (leverage=1) 跟原 fragility_scan 一致（"策略 vs 持币"）。

    :param klines: 至少含 close 列
    :param leverage: 杠杆倍数（默认 1 = unleveraged）
    """
    if klines is None or len(klines) < 2:
        return 0.0
    first_close = float(klines.iloc[0]["close"])
    last_close = float(klines.iloc[-1]["close"])
    if first_close == 0:
        return 0.0
    return round((last_close / first_close - 1.0) * 100.0 * leverage, 3)


def _safe_git_commit() -> str:
    """获取 okx repo HEAD commit hash（与 fragility_scan 一致的实现）。"""
    try:
        okx_root = _HERE.parents[1]
        return subprocess.check_output(
            ["git", "-C", str(okx_root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown"


# ────────────────────────────────────────────────────────────────────
# 跨窗口聚合分析
# ────────────────────────────────────────────────────────────────────
def _format_result_md(
    scan_name: str,
    inst_id: str,
    bar: str,
    strategy_full: str,
    slippage_bps_list: List[int],
    fee_bps_list: List[float],
    leverage: int,
    window_days: int,
    stride_days: int,
    data_start_ts: int,
    data_end_ts: int,
    n_windows: int,
    summaries: List[WindowSummary],
) -> str:
    """生成 walkforward 级别的 result.md。"""
    lines: List[str] = []
    lines.append(f"# Walk-forward Analysis: {scan_name}")
    lines.append("")
    lines.append(f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **策略**: `{strategy_full}`")
    lines.append(f"- **标的**: `{inst_id}` ({bar})")
    lines.append(f"- **杠杆**: {leverage}x")
    lines.append(f"- **窗口配置**: {window_days}d window, {stride_days}d stride")
    lines.append(f"- **数据范围**: {_ms_to_iso(data_start_ts)} → {_ms_to_iso(data_end_ts)}")
    lines.append(f"- **Slippage**: {slippage_bps_list} bps | **Fee**: {fee_bps_list} bps")
    lines.append(f"- **窗口数**: {n_windows}")
    lines.append("")
    lines.append(f"- **Git commit**: `{_safe_git_commit()}`")
    lines.append("")

    # ─── 跨窗口一致性指标 ───
    if summaries:
        best_rets = [s.best_ret_pct for s in summaries]
        viable_windows = sum(1 for s in summaries if s.viable_count > 0)
        # 最佳 cell 集中度：跨窗口 best cell 的 slip/fee 组合去重数
        best_combos = {(s.best_slip_bps, s.best_fee_bps) for s in summaries}

        lines.append("## 跨窗口一致性")
        lines.append("")
        lines.append(f"- **Viable 窗口占比**: {viable_windows}/{n_windows} = {viable_windows/n_windows*100:.0f}%")
        lines.append(f"- **best_ret 范围**: min={min(best_rets):+.2f}%  max={max(best_rets):+.2f}%  "
                     f"mean={statistics.mean(best_rets):+.2f}%  std={statistics.stdev(best_rets):.2f}pp" if len(best_rets) > 1 else
                     f"- **best_ret**: {best_rets[0]:+.2f}%")
        lines.append(f"- **最佳 cell 组合 (slip/fee)**: {len(best_combos)} 种 unique 配置")
        if len(best_combos) <= 3:
            combos_str = ", ".join(f"{s}/{f}" for s, f in sorted(best_combos))
            lines.append(f"  - 实际: {combos_str}")
        lines.append("")

    # ─── Per-window 表格 ───
    lines.append("## Per-Window 详细")
    lines.append("")
    lines.append("| # | 窗口起止 | bars | buy&hold | viable/total | best_ret | best_sharpe | best cell (slip/fee) | spread |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for s in summaries:
        window_str = f"{_ms_to_iso(s.start_ts)[:10]} → {_ms_to_iso(s.end_ts)[:10]}"
        best_combo = f"{s.best_slip_bps}/{s.best_fee_bps}"
        viable_str = f"{s.viable_count}/{s.total_cells}"
        lines.append(
            f"| {s.idx:02d} | {window_str} | {s.bar_count} | {s.buy_hold_ret_pct:+.2f}% | "
            f"{viable_str} | {s.best_ret_pct:+.2f}% | {s.best_sharpe:+.3f} | {best_combo} | "
            f"{s.ret_spread_pct:.2f}pp |"
        )
    lines.append("")

    # ─── 结论 ───
    if summaries:
        viable_pct = viable_windows / n_windows * 100
        best_window = max(summaries, key=lambda s: s.best_ret_pct)
        worst_window = min(summaries, key=lambda s: s.best_ret_pct)
        lines.append("## 结论")
        lines.append("")
        if viable_pct >= 80:
            lines.append(f"→ **跨 regime 高度稳健**：{viable_pct:.0f}% 窗口 viable，策略对 regime 不敏感。")
        elif viable_pct >= 50:
            lines.append(f"→ **部分稳健**：{viable_pct:.0f}% 窗口 viable，需关注 non-viable 窗口的 regime 特征。")
        else:
            lines.append(f"→ **跨 regime 脆弱**：仅 {viable_pct:.0f}% 窗口 viable，策略对 regime 高度敏感。")
        lines.append("")
        lines.append(f"- **最佳窗口**: w{best_window.idx:02d} ({_ms_to_iso(best_window.start_ts)[:10]} → {_ms_to_iso(best_window.end_ts)[:10]}) "
                     f"ret={best_window.best_ret_pct:+.2f}%")
        lines.append(f"- **最差窗口**: w{worst_window.idx:02d} ({_ms_to_iso(worst_window.start_ts)[:10]} → {_ms_to_iso(worst_window.end_ts)[:10]}) "
                     f"ret={worst_window.best_ret_pct:+.2f}%")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**复现命令**:")
    lines.append("```bash")
    lines.append("python3 -m okx.scripts.walkforward \\")
    lines.append(f"    --strategy {strategy_full.split('_')[0]} \\")
    lines.append(f"    --symbol {inst_id} --bar {bar} \\")
    lines.append(f"    --window-days {window_days} --stride-days {stride_days} \\")
    lines.append(f"    --slippage-bps {','.join(str(s) for s in slippage_bps_list)} \\")
    lines.append(f"    --fee-bps {','.join(str(f) for f in fee_bps_list)} \\")
    lines.append(f"    --leverage {leverage} \\")
    lines.append(f"    --name {scan_name}")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────────────────────────────
def run_walkforward(
    scan_name: str,
    inst_id: str,
    bar: str,
    strategy_full: str,
    slippage_bps_list: List[int],
    fee_bps_list: List[float],
    leverage: int,
    initial_capital: float,
    window_days: int,
    stride_days: int,
    out_dir: Path,
) -> List[WindowSummary]:
    """主流程：对每个窗口跑 fragility_scan，聚合跨窗口指标。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ─── 1. 加载完整数据范围（用于生成 windows）───
    from okx.code.backtest.data_loader import load
    full_data = load(inst_id, bar)
    data_start_ts = full_data.start_ts
    data_end_ts = full_data.end_ts
    print(f"📊 数据范围: {_ms_to_iso(data_start_ts)} → {_ms_to_iso(data_end_ts)} "
          f"({full_data.bar_count} bars)")

    # ─── 2. 生成 windows ───
    windows = generate_windows(data_start_ts, data_end_ts, window_days, stride_days)
    if not windows:
        raise ValueError(
            f"数据跨度 {(data_end_ts - data_start_ts) / 86400000:.1f}d < 窗口长度 {window_days}d"
        )
    print(f"🪟 窗口数: {len(windows)} ({window_days}d window × {stride_days}d stride)")
    print()

    # ─── 3. 每个窗口独立跑 fragility_scan ───
    summaries: List[WindowSummary] = []
    windows_root = out_dir / "windows"

    for spec in windows:
        start_iso = _ms_to_iso(spec.start_ts)[:10]
        end_iso = _ms_to_iso(spec.end_ts)[:10]
        print(f"⏳ Window {spec.idx:02d}: {start_iso} → {end_iso}  ", end="", flush=True)

        # 跑 grid_scan
        try:
            slip_axis, fee_axis, grid, cell_data = grid_scan(
                inst_id=inst_id,
                bar=bar,
                strategy_full=strategy_full,
                slippage_bps_list=slippage_bps_list,
                fee_bps_list=fee_bps_list,
                leverage=leverage,
                initial_capital=initial_capital,
                start_ts=spec.start_ts,
                end_ts=spec.end_ts,
            )
        except Exception as e:
            print(f"❌ grid_scan 失败: {e}")
            continue

        if not grid:
            print("⚠️ 空 grid（窗口内无数据？）跳过")
            continue

        # 计算 buy-hold 收益
        window_data = load(inst_id, bar, start_ts=spec.start_ts, end_ts=spec.end_ts)
        bh_ret = compute_buy_hold_ret(window_data.klines, leverage=1)

        # 持久化该窗口的 fragility_scan 全套产物
        window_dir = windows_root / _window_dir_label(spec)
        persist(
            out_dir=window_dir,
            scan_name=f"{scan_name}_w{spec.idx:02d}",
            inst_id=inst_id,
            bar=bar,
            strategy_full=strategy_full,
            slippage_bps_list=slippage_bps_list,
            fee_bps_list=fee_bps_list,
            leverage=leverage,
            initial_capital=initial_capital,
            buy_hold_ret_pct=bh_ret,
            slip_axis=slip_axis,
            fee_axis=fee_axis,
            grid=grid,
            cell_data=cell_data,
            timestamp=timestamp,
            start_ts=spec.start_ts,
            end_ts=spec.end_ts,
        )

        # 聚合单窗口指标
        viable_count = sum(1 for r in grid if viability(r["ret_pct"], bh_ret))
        best = max(grid, key=lambda r: r["ret_pct"])
        worst = min(grid, key=lambda r: r["ret_pct"])
        summary = WindowSummary(
            idx=spec.idx,
            start_ts=spec.start_ts,
            end_ts=spec.end_ts,
            bar_count=window_data.bar_count,
            buy_hold_ret_pct=bh_ret,
            viable_count=viable_count,
            total_cells=len(grid),
            best_ret_pct=best["ret_pct"],
            best_sharpe=best["sharpe"],
            best_slip_bps=best["slippage_bps"],
            best_fee_bps=best["fee_bps"],
            worst_ret_pct=worst["ret_pct"],
            ret_spread_pct=round(best["ret_pct"] - worst["ret_pct"], 3),
        )
        summaries.append(summary)
        print(f"viable {viable_count}/{len(grid)}  best_ret={best['ret_pct']:+.2f}%  buy&hold={bh_ret:+.2f}%")

    if not summaries:
        raise SystemExit("❌ 所有窗口都跑失败，无 summaries 可写")

    # ─── 4. 写 walkforward 级别 meta.json + result.md ───
    meta = {
        "scan_name": scan_name,
        "timestamp": timestamp,
        "strategy": strategy_full,
        "symbol": inst_id,
        "bar": bar,
        "leverage": leverage,
        "initial_capital": initial_capital,
        "window_days": window_days,
        "stride_days": stride_days,
        "data_start_ts": data_start_ts,
        "data_end_ts": data_end_ts,
        "slippage_bps_list": slippage_bps_list,
        "fee_bps_list": fee_bps_list,
        "git_commit": _safe_git_commit(),
        "n_windows": len(summaries),
        "windows": [asdict(s) for s in summaries],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    md = _format_result_md(
        scan_name, inst_id, bar, strategy_full,
        slippage_bps_list, fee_bps_list, leverage,
        window_days, stride_days, data_start_ts, data_end_ts,
        len(summaries), summaries,
    )
    (out_dir / "result.md").write_text(md, encoding="utf-8")

    # 快照 walkforward.py 副本（复现性证据）
    shutil.copy2(Path(__file__).resolve(), out_dir / "walkforward.py")

    print()
    print(f"✅ 完成：{len(summaries)}/{len(windows)} 窗口成功")
    print(f"   报告: {out_dir}/result.md")
    print(f"   Per-window fragility_scan: {out_dir}/windows/")
    return summaries


# ────────────────────────────────────────────────────────────────────
# CLI 入口
# ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Walk-forward Analysis —— 滚动窗口跨 regime 稳健性扫描",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--strategy", required=True,
                        help="策略名（支持缩写 A/B/C/D 或全名）")
    parser.add_argument("--symbol", required=True,
                        help="标的，如 BTC-USDT-SWAP")
    parser.add_argument("--bar", default="1h", help="K 线周期（默认 1h）")
    parser.add_argument("--window-days", type=int, default=90,
                        help="窗口长度（天），默认 90")
    parser.add_argument("--stride-days", type=int, default=30,
                        help="窗口滑动步长（天），默认 30")
    parser.add_argument("--slippage-bps", default=None,
                        help="滑点扫描列表，逗号分隔。缺省 = calibration")
    parser.add_argument("--fee-bps", default=None,
                        help="手续费扫描列表，逗号分隔。缺省 = calibration")
    parser.add_argument("--leverage", type=int, default=5, help="杠杆（默认 5x）")
    parser.add_argument("--capital", type=float, default=10000.0, help="初始资金")
    parser.add_argument("--name", required=True,
                        help="扫描名（用作输出目录前缀）")
    parser.add_argument("--out-root", default=None,
                        help="输出根目录（默认 = data/walkforward/）")
    args = parser.parse_args()

    if args.out_root is None:
        args.out_root = str(_HERE.parents[1] / "docs" / "agent-context" / "walkforward")

    strategy_full = resolve_strategy(args.strategy)

    # 摩擦参数 fallback：与 fragility_scan 同样的逻辑
    calib = load_calibration_defaults()
    if args.slippage_bps is None:
        measured = calib.get("real_measured_taker_slippage_bps")
        if measured is None:
            parser.error("缺少 --slippage-bps 且 calibration 未配置")
        slippage_bps_list = [max(1, int(round(measured * 0.6))), int(round(measured)), int(round(measured * 1.5))]
        print(f"🔧 slippage_bps 未指定，使用 calibration：{slippage_bps_list}")
    else:
        slippage_bps_list = parse_int_list(args.slippage_bps)

    if args.fee_bps is None:
        measured = calib.get("real_measured_taker_fee_bps")
        if measured is None:
            parser.error("缺少 --fee-bps 且 calibration 未配置")
        fee_bps_list = [float(measured)]
        print(f"🔧 fee_bps 未指定，使用 calibration：{fee_bps_list}")
    else:
        fee_bps_list = parse_float_list(args.fee_bps)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_root) / f"{args.name}-{timestamp}"
    print(f"🚀 Walk-forward 启动")
    print(f"   策略: {strategy_full}")
    print(f"   标的: {args.symbol} ({args.bar})")
    print(f"   窗口: {args.window_days}d × stride {args.stride_days}d")
    print(f"   杠杆: {args.leverage}x | 资金: ${args.capital:,.0f}")
    print(f"   Slippage: {slippage_bps_list} bps | Fee: {fee_bps_list} bps")
    print(f"   输出: {out_dir}")
    print()

    run_walkforward(
        scan_name=args.name,
        inst_id=args.symbol,
        bar=args.bar,
        strategy_full=strategy_full,
        slippage_bps_list=slippage_bps_list,
        fee_bps_list=fee_bps_list,
        leverage=args.leverage,
        initial_capital=args.capital,
        window_days=args.window_days,
        stride_days=args.stride_days,
        out_dir=out_dir,
    )


if __name__ == "__main__":
    main()
