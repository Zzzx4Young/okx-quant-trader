#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fragility Scan —— 策略真实成本敏感性扫描（升档版）

═══════════════════════════════════════════════════════════════════
目的：在 release 决策前，量化策略 alpha 对真实交易成本的敏感度
═══════════════════════════════════════════════════════════════════

支持任意策略 × 任意标的 × slippage × fee 的 N×M 扫描，自动判定
每个 cell 的 viability（vs buy-and-hold 或 vs 零基线），并把结果
持久化到 docs/agent-context/experiments/<name>-<date>/，解决
"fragility 结果只在 /tmp/，下次同名跑会覆盖"的痛点。

═══════════════════════════════════════════════════════════════════
CLI 例子
═══════════════════════════════════════════════════════════════════
# 1. 单轴扫描（slippage 5/10/15/20 bps，fee 固定 5.5bps）
python3 -m okx.scripts.fragility_scan \\
    --strategy C --symbol BTC-USDT-SWAP --bar 1h \\
    --slippage-bps 5,10,15,20 --fee-bps 5.5 \\
    --buy-hold-ret -6.49 --name c-btc-slip

# 2. 双轴完整网格（slippage × fee）
python3 -m okx.scripts.fragility_scan \\
    --strategy C --symbol BTC-USDT-SWAP --bar 1h \\
    --slippage-bps 5,10,15,20 --fee-bps 4.5,5.5,7.0,8.5 \\
    --buy-hold-ret -6.49 --name c-btc-full-grid

# 3. 跨策略横向对比
python3 -m okx.scripts.fragility_scan \\
    --strategy A --symbol BTC-USDT-SWAP \\
    --slippage-bps 10 --fee-bps 5.5 \\
    --name a-btc-baseline
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# ────────────────────────────────────────────────────────────────────
# 路径处理：把项目根加入 sys.path，让 okx 包可导入
# ────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]  # okx/scripts/fragility_scan.py → 项目根
sys.path.insert(0, str(_PROJECT_ROOT))

from okx.code.backtest.data_loader import load
from okx.code.backtest.matcher import BacktestEngine
from okx.code.backtest.run_phase2_experiment import STRATEGIES


# 策略缩写 → 全名（来自 STRATEGIES 注册表）
STRATEGY_ALIASES = {
    "A": "A_EMA20_BREAKOUT",
    "B": "B_BB_RSI_REVERSION",
    "C": "C_VOLATILITY_BREAKOUT",
    "D": "D_FUNDING_RATE_REVERSAL",
}


def resolve_strategy(name: str) -> str:
    """接受 'A' 或 'A_EMA20_BREAKOUT'，返回 STRATEGIES 里的全名。"""
    resolved = STRATEGY_ALIASES.get(name.upper(), name)
    if resolved not in STRATEGIES:
        valid = ", ".join(STRATEGIES.keys())
        raise SystemExit(f"❌ 未知策略: {name}\n   可用: {valid}")
    return resolved


def parse_float_list(s: str) -> List[float]:
    """解析 '5,10,15' 或 '5.5,7.0' → [5.0, 10.0, 15.0]"""
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def parse_int_list(s: str) -> List[int]:
    return [int(float(x.strip())) for x in s.split(",") if x.strip()]


# ────────────────────────────────────────────────────────────────────
# 单次回测
# ────────────────────────────────────────────────────────────────────
def run_one(
    inst_id: str,
    bar: str,
    strategy_full: str,
    slippage_bps: int,
    fee_bps: float,
    leverage: int,
    initial_capital: float,
) -> Dict:
    """跑一次回测，返回单 cell 指标。"""
    data = load(inst_id, bar)
    sig = STRATEGIES[strategy_full]
    fee_rate = fee_bps / 10000.0
    engine = BacktestEngine(
        data,
        initial_capital=initial_capital,
        leverage=leverage,
        slippage_bps=int(slippage_bps),
        taker_fee=fee_rate,
        signal_provider=sig,
    )
    result = engine.run()
    m = result.metrics()
    return {
        "inst": inst_id,
        "bar": bar,
        "strategy": strategy_full,
        "slippage_bps": slippage_bps,
        "fee_bps": fee_bps,
        # ⚠️ 关键陷阱：metrics() 返回的 _pct 字段已是百分比形式，不要 ×100
        # win_rate 是 property，返回 fraction (0.44)，要 ×100 才得到百分比
        "ret_pct": round(m.get("total_return_pct", 0), 3),
        "sharpe": round(m.get("sharpe", 0), 3),
        "maxDD_pct": round(m.get("max_drawdown_pct", 0), 3),
        "trades": result.n_trades,
        "win_rate_pct": round(result.win_rate * 100, 1),
        "slip_cost": round(result.slippage_cost_total, 2),
        "fee_paid": round(result.fee_paid_total, 2),
    }


# ────────────────────────────────────────────────────────────────────
# 网格扫描
# ────────────────────────────────────────────────────────────────────
def grid_scan(
    inst_id: str,
    bar: str,
    strategy_full: str,
    slippage_bps_list: List[int],
    fee_bps_list: List[float],
    leverage: int,
    initial_capital: float,
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    跑 slippage × fee 完整网格。
    返回 (单轴 slippage 扫描 / 单轴 fee 扫描 / 完整网格)。
    """
    grid: List[Dict] = []
    for slip in slippage_bps_list:
        for fee in fee_bps_list:
            grid.append(run_one(inst_id, bar, strategy_full, slip, fee, leverage, initial_capital))

    # 单轴结果（取 fee 列表第一个作为 slippage 扫描的常量）
    fee_const = fee_bps_list[0]
    slip_axis = [r for r in grid if r["fee_bps"] == fee_const]

    # 单轴结果（取 slip 列表第一个作为 fee 扫描的常量）
    slip_const = slippage_bps_list[0]
    fee_axis = [r for r in grid if r["slippage_bps"] == slip_const]

    return slip_axis, fee_axis, grid


# ────────────────────────────────────────────────────────────────────
# 决策矩阵（viable / not viable）
# ────────────────────────────────────────────────────────────────────
def viability(ret_pct: float, buy_hold_ret_pct: float) -> bool:
    """
    viable = 策略收益 > buy-and-hold 收益（策略确实跑赢基准）。
    如果 buy_hold_ret_pct 传 None，则 viable = ret_pct > 0。
    """
    if buy_hold_ret_pct is None:
        return ret_pct > 0
    return ret_pct > buy_hold_ret_pct


def viability_marker(ret_pct: float, buy_hold_ret_pct: float) -> str:
    return "✅" if viability(ret_pct, buy_hold_ret_pct) else "❌"


# ────────────────────────────────────────────────────────────────────
# 输出格式
# ────────────────────────────────────────────────────────────────────
def fmt_cell(r: Dict, buy_hold_ret_pct: float | None) -> str:
    """单 cell 一行紧凑格式：ret + sharpe + trades + 判定。"""
    delta = ""
    if buy_hold_ret_pct is not None:
        delta = f"  Δ={r['ret_pct'] - buy_hold_ret_pct:+6.2f}pp"
    return (
        f"slip={r['slippage_bps']:>3}bps fee={r['fee_bps']:>4.1f}bps  "
        f"ret={r['ret_pct']:+7.2f}% sharpe={r['sharpe']:+6.3f} "
        f"trades={r['trades']:>3} win={r['win_rate_pct']:>5.1f}%{delta} "
        f"{viability_marker(r['ret_pct'], buy_hold_ret_pct)}"
    )


def render_markdown(
    scan_name: str,
    inst_id: str,
    bar: str,
    strategy_full: str,
    slippage_bps_list: List[int],
    fee_bps_list: List[float],
    leverage: int,
    buy_hold_ret_pct: float | None,
    slip_axis: List[Dict],
    fee_axis: List[Dict],
    grid: List[Dict],
    timestamp: str,
) -> str:
    lines: List[str] = []
    lines.append(f"# Fragility Scan: {scan_name}")
    lines.append("")
    lines.append(f"- **时间**: {timestamp}")
    lines.append(f"- **策略**: `{strategy_full}`")
    lines.append(f"- **标的**: `{inst_id}` ({bar})")
    lines.append(f"- **杠杆**: {leverage}x")
    lines.append(f"- **Buy-and-hold 参考**: {buy_hold_ret_pct if buy_hold_ret_pct is not None else 'N/A'}%")
    lines.append("")

    # 完整网格（如果有）
    if len(slippage_bps_list) > 1 and len(fee_bps_list) > 1:
        lines.append("## 完整网格 (slippage × fee)")
        lines.append("")
        # 表头
        header = "| metric \\ axis |"
        for slip in slippage_bps_list:
            header += f" slip={slip}bps |"
        lines.append(header)
        sep = "|" + "---|" * (len(slippage_bps_list) + 1)
        lines.append(sep)
        # 行：每个 fee_bps
        for fee in fee_bps_list:
            row = f"| **fee={fee}bps** |"
            for slip in slippage_bps_list:
                cell = next((r for r in grid if r["slippage_bps"] == slip and r["fee_bps"] == fee), None)
                if cell:
                    mark = viability_marker(cell["ret_pct"], buy_hold_ret_pct)
                    row += f" {cell['ret_pct']:+5.2f}% {mark} |"
                else:
                    row += " N/A |"
            lines.append(row)
        lines.append("")
        lines.append("**判定**: ✅ = viable (ret > buy-hold)；❌ = alpha 被成本吃掉")
        lines.append("")

    # 单轴 slippage 扫描
    if slip_axis:
        lines.append("## Slippage 敏感性 (fee 固定 = " + str(fee_bps_list[0]) + "bps)")
        lines.append("")
        lines.append("| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in slip_axis:
            mark = viability_marker(r["ret_pct"], buy_hold_ret_pct)
            lines.append(
                f"| {r['slippage_bps']} | {r['ret_pct']:+5.2f}% | {r['sharpe']:+6.3f} | "
                f"{r['maxDD_pct']:+5.2f}% | {r['trades']} | {r['win_rate_pct']:5.1f}% | "
                f"${r['slip_cost']:.2f} | ${r['fee_paid']:.2f} | {mark} |"
            )
        lines.append("")

    # 单轴 fee 扫描
    if fee_axis and fee_bps_list != [fee_bps_list[0]]:
        lines.append("## Fee 敏感性 (slippage 固定 = " + str(slippage_bps_list[0]) + "bps)")
        lines.append("")
        lines.append("| fee_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | viable |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in fee_axis:
            mark = viability_marker(r["ret_pct"], buy_hold_ret_pct)
            lines.append(
                f"| {r['fee_bps']:.1f} | {r['ret_pct']:+5.2f}% | {r['sharpe']:+6.3f} | "
                f"{r['maxDD_pct']:+5.2f}% | {r['trades']} | {r['win_rate_pct']:5.1f}% | {mark} |"
            )
        lines.append("")

    lines.append("## 结论")
    lines.append("")
    viable_count = sum(1 for r in grid if viability(r["ret_pct"], buy_hold_ret_pct))
    total = len(grid)
    lines.append(f"- 总扫描 cell 数: {total}")
    lines.append(f"- viable cells: **{viable_count} / {total}** ({viable_count/total*100:.0f}%)")
    lines.append("")
    if viable_count == total:
        lines.append("→ 所有 cell viable。策略对成本不敏感。**可以直接进入下一阶段评估**。")
    elif viable_count == 0:
        lines.append("→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。")
    else:
        lines.append("→ 部分 cell viable。**注意 viable 边界**：ret=0 时的 slippage/fee 上限是上 LIVE 的硬性门。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**复现命令**:")
    lines.append("```bash")
    lines.append(f"python3 -m okx.scripts.fragility_scan \\")
    lines.append(f"    --strategy {strategy_full.split('_')[0]} \\")
    lines.append(f"    --symbol {inst_id} --bar {bar} \\")
    lines.append(f"    --slippage-bps {','.join(str(s) for s in slippage_bps_list)} \\")
    lines.append(f"    --fee-bps {','.join(str(f) for f in fee_bps_list)} \\")
    lines.append(f"    --leverage {leverage} \\")
    if buy_hold_ret_pct is not None:
        lines.append(f"    --buy-hold-ret {buy_hold_ret_pct} \\")
    lines.append(f"    --name {scan_name}")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def render_text_log(
    scan_name: str,
    inst_id: str,
    bar: str,
    strategy_full: str,
    slippage_bps_list: List[int],
    fee_bps_list: List[float],
    leverage: int,
    buy_hold_ret_pct: float | None,
    slip_axis: List[Dict],
    fee_axis: List[Dict],
    grid: List[Dict],
) -> str:
    """控制台/纯文本格式，兼容 grep。"""
    lines: List[str] = []
    lines.append("=" * 80)
    lines.append(f"脆弱性扫描 · {strategy_full} · {inst_id} {bar} · {leverage}x leverage")
    lines.append("=" * 80)
    lines.append("")
    for r in grid:
        lines.append("  " + fmt_cell(r, buy_hold_ret_pct))
    lines.append("")
    lines.append(f"→ viable: {sum(1 for r in grid if viability(r['ret_pct'], buy_hold_ret_pct))}/{len(grid)}")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────
# 持久化
# ────────────────────────────────────────────────────────────────────
def persist(
    out_dir: Path,
    scan_name: str,
    inst_id: str,
    bar: str,
    strategy_full: str,
    slippage_bps_list: List[int],
    fee_bps_list: List[float],
    leverage: int,
    initial_capital: float,
    buy_hold_ret_pct: float | None,
    slip_axis: List[Dict],
    fee_axis: List[Dict],
    grid: List[Dict],
    timestamp: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. result.md（人类阅读）
    md = render_markdown(
        scan_name, inst_id, bar, strategy_full,
        slippage_bps_list, fee_bps_list, leverage, buy_hold_ret_pct,
        slip_axis, fee_axis, grid, timestamp,
    )
    (out_dir / "result.md").write_text(md, encoding="utf-8")

    # 2. result.txt（grep 友好）
    txt = render_text_log(
        scan_name, inst_id, bar, strategy_full,
        slippage_bps_list, fee_bps_list, leverage, buy_hold_ret_pct,
        slip_axis, fee_axis, grid,
    )
    (out_dir / "result.txt").write_text(txt, encoding="utf-8")

    # 3. meta.json（机器可读）
    meta = {
        "scan_name": scan_name,
        "timestamp": timestamp,
        "strategy": strategy_full,
        "symbol": inst_id,
        "bar": bar,
        "leverage": leverage,
        "initial_capital": initial_capital,
        "buy_hold_ret_pct": buy_hold_ret_pct,
        "slippage_bps_list": slippage_bps_list,
        "fee_bps_list": fee_bps_list,
        "grid": grid,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # 4. 快照 scan.py 副本（复现性证据：哪个版本的工具跑的）
    src = Path(__file__).resolve()
    shutil.copy2(src, out_dir / "scan.py")


# ────────────────────────────────────────────────────────────────────
# CLI 入口
# ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Fragility Scan —— 策略真实成本敏感性扫描（升档版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--strategy", required=True,
                        help="策略名（支持缩写 A/B/C/D 或全名）")
    parser.add_argument("--symbol", required=True,
                        help="标的，如 BTC-USDT-SWAP")
    parser.add_argument("--bar", default="1h", help="K 线周期（默认 1h）")
    parser.add_argument("--slippage-bps", required=True,
                        help="滑点扫描列表，逗号分隔，如 5,10,15,20")
    parser.add_argument("--fee-bps", required=True,
                        help="手续费扫描列表，逗号分隔，如 4.5,5.5,7.0,8.5")
    parser.add_argument("--leverage", type=int, default=5, help="杠杆（默认 5x）")
    parser.add_argument("--capital", type=float, default=10000.0, help="初始资金")
    parser.add_argument("--buy-hold-ret", type=float, default=None,
                        help="Buy-and-hold 同期收益（百分比），用于 viability 比较。缺省 = ret>0")
    parser.add_argument("--name", required=True,
                        help="扫描名（用作输出目录前缀）")
    parser.add_argument("--out-root", default="okx/docs/agent-context/experiments",
                        help="输出根目录（默认 okx/docs/agent-context/experiments）")
    args = parser.parse_args()

    strategy_full = resolve_strategy(args.strategy)
    slippage_bps_list = parse_int_list(args.slippage_bps)
    fee_bps_list = parse_float_list(args.fee_bps)

    if not slippage_bps_list or not fee_bps_list:
        raise SystemExit("❌ --slippage-bps 和 --fee-bps 必须至少各 1 个值")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_root) / f"{args.name}-{date_stamp}"

    print(f"🚀 Fragility Scan 启动")
    print(f"   策略: {strategy_full}")
    print(f"   标的: {args.symbol} ({args.bar})")
    print(f"   Slippage: {slippage_bps_list} bps")
    print(f"   Fee:      {fee_bps_list} bps")
    print(f"   杠杆: {args.leverage}x | 资金: ${args.capital:,.0f}")
    print(f"   Buy-hold ref: {args.buy_hold_ret if args.buy_hold_ret is not None else 'N/A'}")
    print(f"   输出: {out_dir}")
    print()

    slip_axis, fee_axis, grid = grid_scan(
        inst_id=args.symbol,
        bar=args.bar,
        strategy_full=strategy_full,
        slippage_bps_list=slippage_bps_list,
        fee_bps_list=fee_bps_list,
        leverage=args.leverage,
        initial_capital=args.capital,
    )

    # 控制台输出
    txt = render_text_log(
        args.name, args.symbol, args.bar, strategy_full,
        slippage_bps_list, fee_bps_list, args.leverage, args.buy_hold_ret,
        slip_axis, fee_axis, grid,
    )
    print(txt)
    print()

    # 持久化
    persist(
        out_dir, args.name, args.symbol, args.bar, strategy_full,
        slippage_bps_list, fee_bps_list, args.leverage, args.capital,
        args.buy_hold_ret, slip_axis, fee_axis, grid, timestamp,
    )

    viable_count = sum(1 for r in grid if viability(r["ret_pct"], args.buy_hold_ret))
    print(f"✅ 完成：viable {viable_count}/{len(grid)} cells")
    print(f"   报告: {out_dir}/result.md")
    print(f"   原始数据: {out_dir}/meta.json")


if __name__ == "__main__":
    main()
