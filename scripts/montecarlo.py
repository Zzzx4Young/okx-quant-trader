# -*- coding: utf-8 -*-
"""
Monte Carlo Simulation · trades.parquet bootstrap

Phase 3C：将 walkforward 输出的 trades.parquet 作为"经验分布"，做
带放回抽样，估计策略的最终权益分布、最大回撤分布、破灭概率。

设计原则：
  - 不模拟价格路径（不造 K 线）— 只重排"已发生的交易"顺序与组合
  - bootstrap 假设：单笔 pnl 是独立同分布样本（在回测时段内近似成立）
  - 输出：5/50/95 分位权益曲线 + 95% 分位 max DD + 概率破灭
  - 不依赖 matplotlib（输出 markdown + 控制台 ASCII sparkline）

输入：
  --walkforward-dir  指向 walkforward.py 产出的根目录（包含 windows/wXX_*/cells/.../trades.parquet）
  --initial-capital  初始资金 USD（默认 10000，与 fragility_scan 一致）
  --n-sims           bootstrap 次数（默认 1000）
  --sample-multiple  每次抽样是真实笔数的几倍（默认 1.0）
  --seed             随机种子（默认 42，可复现）

输出：
  - console: result 摘要
  - file: docs/agent-context/montecarlo/<run-name>/result.md

例：
  bash run.sh scripts/montecarlo.py \\
      --walkforward-dir docs/agent-context/walkforward/c-btc-wf-3m1m-20260724-191640 \\
      --initial-capital 10000 \\
      --n-sims 1000 \\
      --name c-btc-mc-1k

跑测：
  bash run.sh -m pytest okx/tests/test_montecarlo.py -v
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ──────────────── 数据结构 ────────────────


@dataclass
class SimulationResult:
    """单次 bootstrap 的聚合统计"""

    initial_capital_usd: float
    n_real_trades: int                    # 真实样本数
    n_simulations: int                    # 模拟次数
    sample_size_per_sim: int              # 每次抽多少笔

    # ── Final equity percentiles ──
    final_equity_p05: float
    final_equity_p50: float
    final_equity_p95: float
    final_equity_mean: float
    final_equity_std: float

    # ── Max drawdown percentiles ──
    max_dd_p05: float  # 95% 分位 DD（"最坏 5% 情况下至少回撤这么多"）
    max_dd_p50: float
    max_dd_p95: float
    max_dd_mean: float

    # ── Probability of ruin ──
    prob_ruin_50pct: float   # P(final < initial * 0.5)
    prob_ruin_30pct: float   # P(final < initial * 0.3)
    prob_ruin_10pct: float   # P(final < initial * 0.1)

    # ── 原始分布（供下游画图 / Phase 3B overlay）──
    final_equity_distribution: List[float]  # length = n_sims
    max_dd_distribution: List[float]         # length = n_sims

    @property
    def total_return_p50_pct(self) -> float:
        return (self.final_equity_p50 / self.initial_capital_usd - 1.0) * 100.0


# ──────────────── 核心：单次 walkforward dir 加载所有 trades ────────────────


def load_trades(walkforward_dir: Path) -> pd.DataFrame:
    """从 walkforward 输出目录加载所有 trades.parquet（所有 windows × all cells）

    :return: DataFrame with columns: window_id, cell_id, slippage_bps, fee_bps,
             strategy, entry_ts, exit_ts, direction, net_pnl, ...
    """
    if not walkforward_dir.exists():
        raise FileNotFoundError(f"walkforward_dir 不存在: {walkforward_dir}")

    windows_dir = walkforward_dir / "windows"
    if not windows_dir.exists():
        raise FileNotFoundError(f"未找到 windows/ 子目录: {windows_dir}")

    # 收集所有 trades.parquet（递归）
    trades_files = sorted(windows_dir.rglob("trades.parquet"))
    if not trades_files:
        raise FileNotFoundError(f"未找到任何 trades.parquet: {windows_dir}")

    logger.info(f"找到 {len(trades_files)} 个 trades.parquet")
    dfs = []
    for fp in trades_files:
        df = pd.read_parquet(fp)
        # 加 metadata：window/cell/slip/fee（来自路径）
        parts = fp.parts
        # .../<windows>/<window_id>/<cells>/<cell_id>/trades.parquet
        try:
            win_idx = parts.index("windows") + 1
            win_id = parts[win_idx]
            cell_id = parts[win_idx + 2]  # windows/wXX/cells/<cell_id>
            df["window_id"] = win_id
            df["cell_id"] = cell_id
        except (ValueError, IndexError):
            df["window_id"] = "?"
            df["cell_id"] = "?"
        # 解析 slippage/fee from cell_id (格式: slipX_feeYpZ)
        df["slippage_bps"] = np.nan
        df["fee_bps"] = np.nan
        if "slip" in cell_id:
            try:
                slip = cell_id.split("slip")[1].split("_")[0]
                df["slippage_bps"] = float(slip)
            except Exception:
                pass
        if "fee" in cell_id:
            try:
                fee = cell_id.split("fee")[1].split("p")[0]
                df["fee_bps"] = float(fee)
            except Exception:
                pass
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    logger.info(f"合并后: {len(combined)} 笔 trades, strategy={combined['strategy'].unique().tolist()}")
    return combined


def extract_pnl_series(trades: pd.DataFrame, slippage_bps: Optional[float] = None,
                       fee_bps: Optional[float] = None) -> np.ndarray:
    """从 trades 提取 net_pnl 序列（可选按 slippage/fee 过滤）

    :param trades: load_trades() 的输出
    :param slippage_bps: 按 slippage 过滤（None = 不限）
    :param fee_bps: 按 fee 过滤（None = 不限）
    :return: np.ndarray of net_pnl（USD）
    """
    df = trades
    if slippage_bps is not None:
        df = df[df["slippage_bps"] == slippage_bps]
    if fee_bps is not None:
        df = df[df["fee_bps"] == fee_bps]
    if df.empty:
        return np.array([])
    return df["net_pnl"].to_numpy()


# ──────────────── 核心：单次 simulation ────────────────


def _simulate_one(pnl_series: np.ndarray, initial_capital: float,
                  sample_size: int, rng: np.random.Generator) -> Tuple[np.ndarray, float]:
    """单次 bootstrap

    :return: (equity_curve ndarray[sample_size+1], max_dd float)
    """
    n = len(pnl_series)
    if n == 0:
        return np.array([initial_capital]), 0.0

    # 带放回抽样
    sample = rng.choice(pnl_series, size=sample_size, replace=True)
    cumulative = np.cumsum(sample)
    equity = np.concatenate(([initial_capital], initial_capital + cumulative))

    # Max drawdown: 沿曲线计算 peak → current 最大跌幅
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / np.maximum(peak, 1e-9)
    max_dd = drawdown.max()
    return equity, float(max_dd)


def run_montecarlo(
    pnl_series: np.ndarray,
    initial_capital: float = 10000.0,
    n_simulations: int = 1000,
    sample_multiple: float = 1.0,
    seed: int = 42,
) -> SimulationResult:
    """运行完整 Monte Carlo

    :param pnl_series: 历史净盈亏序列（USD）
    :param initial_capital: 初始资金
    :param n_simulations: 模拟次数
    :param sample_multiple: 每次抽样 = N × sample_multiple（默认 1.0 = 同样本量）
    :param seed: 随机种子（保证可复现）
    :return: SimulationResult
    """
    n_real = len(pnl_series)
    if n_real == 0:
        raise ValueError("pnl_series 为空，无法 bootstrap")
    if n_real < 5:
        logger.warning(f"pnl_series 仅 {n_real} 笔 — bootstrap 统计不稳定，结果仅供参考")

    sample_size = max(1, int(round(n_real * sample_multiple)))
    rng = np.random.default_rng(seed)

    final_equities = np.empty(n_simulations)
    max_dds = np.empty(n_simulations)
    for i in range(n_simulations):
        _eq, max_dds[i] = _simulate_one(pnl_series, initial_capital, sample_size, rng)
        final_equities[i] = _eq[-1]

    # 分位
    p05, p50, p95 = np.percentile(final_equities, [5, 50, 95])
    dd_p05, dd_p50, dd_p95 = np.percentile(max_dds, [5, 50, 95])

    # 概率破灭：final equity < threshold × initial
    prob_ruin_50 = float((final_equities < initial_capital * 0.5).mean())
    prob_ruin_30 = float((final_equities < initial_capital * 0.3).mean())
    prob_ruin_10 = float((final_equities < initial_capital * 0.1).mean())

    return SimulationResult(
        initial_capital_usd=initial_capital,
        n_real_trades=n_real,
        n_simulations=n_simulations,
        sample_size_per_sim=sample_size,
        final_equity_p05=float(p05),
        final_equity_p50=float(p50),
        final_equity_p95=float(p95),
        final_equity_mean=float(final_equities.mean()),
        final_equity_std=float(final_equities.std(ddof=1)),
        max_dd_p05=float(dd_p05),
        max_dd_p50=float(dd_p50),
        max_dd_p95=float(dd_p95),
        max_dd_mean=float(max_dds.mean()),
        prob_ruin_50pct=prob_ruin_50,
        prob_ruin_30pct=prob_ruin_30,
        prob_ruin_10pct=prob_ruin_10,
        final_equity_distribution=final_equities.tolist(),
        max_dd_distribution=max_dds.tolist(),
    )


# ──────────────── 输出 ────────────────


def render_markdown(result: SimulationResult, meta: dict) -> str:
    """生成 result.md 内容"""
    lines = [
        f"# Monte Carlo: {meta.get('name', 'unnamed')}",
        "",
        f"- **时间**: {datetime.now(timezone.utc).isoformat()}",
        f"- **策略**: {meta.get('strategy', 'N/A')}",
        f"- **标的**: {meta.get('symbol', 'N/A')}",
        f"- **样本**: {result.n_real_trades} 笔 net_pnl（来自 {meta.get('walkforward_dir', '?')}）",
        f"- **模拟**: {result.n_simulations} 次 bootstrap × {result.sample_size_per_sim} 笔/次",
        f"- **初始资金**: ${result.initial_capital_usd:.2f}",
        "",
        "## Final Equity 分布（USD）",
        "",
        f"| 5% 分位 | 50% 分位 (中位) | 95% 分位 | 均值 | 标准差 |",
        f"|---|---|---|---|---|",
        f"| ${result.final_equity_p05:.2f} | ${result.final_equity_p50:.2f} | "
        f"${result.final_equity_p95:.2f} | ${result.final_equity_mean:.2f} | "
        f"${result.final_equity_std:.2f} |",
        "",
        f"**中位收益**: {result.total_return_p50_pct:+.2f}%",
        "",
        "## Max Drawdown 分布",
        "",
        f"| 5% 分位 | 50% 分位 | 95% 分位 | 均值 |",
        f"|---|---|---|---|",
        f"| {result.max_dd_p05*100:.2f}% | {result.max_dd_p50*100:.2f}% | "
        f"{result.max_dd_p95*100:.2f}% | {result.max_dd_mean*100:.2f}% |",
        "",
        "**最坏 5% 情况至少回撤 ≥ 95% 分位 DD**（保守估计仍能承受的 max DD 阈值）",
        "",
        "## Probability of Ruin",
        "",
        f"| 阈值 | 概率 |",
        f"|---|---|",
        f"| final < 50% initial | {result.prob_ruin_50pct*100:.1f}% |",
        f"| final < 30% initial | {result.prob_ruin_30pct*100:.1f}% |",
        f"| final < 10% initial | {result.prob_ruin_10pct*100:.1f}% |",
        "",
        "## 结论",
        "",
    ]

    # 自动判定（启发式）
    if result.prob_ruin_50pct > 0.05:
        lines.append("⚠️ **P(final < 50%) > 5%**：策略破产风险显著，不建议无熔断器运行")
    elif result.prob_ruin_30pct > 0.01:
        lines.append("⚠️ **P(final < 30%) > 1%**：极端情况下回撤严重，建议配 DD circuit breaker")
    elif result.max_dd_p95 > 0.30:
        lines.append("⚠️ **95% 分位 max DD > 30%**：最坏 5% 情况回撤较大，建议 Kelly 缩仓 + DD 熔断")
    elif result.total_return_p50_pct > 0:
        lines.append("✅ 中位正收益 + 破产概率低 + 回撤可控：策略统计上稳健（仍需 live observation 验证）")
    else:
        lines.append("ℹ️ 中位收益为负，策略仍未达到统计显著性")

    lines.extend([
        "",
        "## 复现命令",
        "",
        "```bash",
        f"python3 -m okx.scripts.montecarlo \\",
        f"    --walkforward-dir {meta.get('walkforward_dir', '?')} \\",
        f"    --initial-capital {result.initial_capital_usd} \\",
        f"    --n-sims {result.n_simulations} \\",
        f"    --name {meta.get('name', 'unnamed')}",
        "```",
        "",
        f"raw: 完整分布存于 `meta.json`（{result.n_simulations} 个 final_equity + max_dd 值）",
    ])
    return "\n".join(lines)


def _output_root() -> Path:
    """默认输出根：docs/agent-context/montecarlo/"""
    return Path(__file__).resolve().parent.parent / "docs" / "agent-context" / "montecarlo"


def persist(result: SimulationResult, meta: dict, out_dir: Path) -> None:
    """写 result.md + meta.json"""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.md").write_text(render_markdown(result, meta), encoding="utf-8")
    # meta.json 不包含 distribution 列表（避免大文件）— 单独存
    summary = {
        "name": meta.get("name"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy": meta.get("strategy"),
        "symbol": meta.get("symbol"),
        "walkforward_dir": meta.get("walkforward_dir"),
        "initial_capital_usd": result.initial_capital_usd,
        "n_real_trades": result.n_real_trades,
        "n_simulations": result.n_simulations,
        "sample_size_per_sim": result.sample_size_per_sim,
        "final_equity_p05": result.final_equity_p05,
        "final_equity_p50": result.final_equity_p50,
        "final_equity_p95": result.final_equity_p95,
        "final_equity_mean": result.final_equity_mean,
        "final_equity_std": result.final_equity_std,
        "max_dd_p05": result.max_dd_p05,
        "max_dd_p50": result.max_dd_p50,
        "max_dd_p95": result.max_dd_p95,
        "max_dd_mean": result.max_dd_mean,
        "prob_ruin_50pct": result.prob_ruin_50pct,
        "prob_ruin_30pct": result.prob_ruin_30pct,
        "prob_ruin_10pct": result.prob_ruin_10pct,
    }
    (out_dir / "meta.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    # distribution 单独
    dist = {
        "final_equity_distribution": result.final_equity_distribution,
        "max_dd_distribution": result.max_dd_distribution,
    }
    (out_dir / "distributions.json").write_text(json.dumps(dist), encoding="utf-8")


# ──────────────── CLI ────────────────


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Monte Carlo bootstrap from walkforward trades.parquet")
    parser.add_argument("--walkforward-dir", type=Path, required=True,
                        help="walkforward.py 输出的根目录（含 windows/ 子目录）")
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--n-sims", type=int, default=1000)
    parser.add_argument("--sample-multiple", type=float, default=1.0,
                        help="每次抽样 = N × multiple（>1 = 模拟更长周期）")
    parser.add_argument("--slippage-bps", type=float, default=None,
                        help="按 slippage 过滤 trades")
    parser.add_argument("--fee-bps", type=float, default=None,
                        help="按 fee 过滤 trades")
    parser.add_argument("--down-only", action="store_true",
                        help="仅 bootstrap regime_filter 推荐 A 的 window 中的 trades "
                             "（验证 'regime_filter 是否救活 A' 假设；需 BTC klines）")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--name", type=str, required=True,
                        help="输出名（用作目录前缀）")
    parser.add_argument("--out-root", type=Path, default=None,
                        help="输出根目录（默认 = docs/agent-context/montecarlo/）")
    args = parser.parse_args()

    wf_dir = args.walkforward_dir.resolve()
    trades = load_trades(wf_dir)

    # ── Optional: --down-only 过滤（regime_filter 推荐的子集）──
    if args.down_only:
        from okx.code.regime_filter import tag_trades_by_regime
        regime_breakdown = trades["_regime"].value_counts().to_dict() if "_regime" in trades.columns else None
        tagged = tag_trades_by_regime(trades)
        regime_breakdown = tagged["_regime"].value_counts().to_dict()
        # 仅保留 regime_filter 推荐 A 的 trades（即 DOWN+EMA空头会入场）
        down_trades = tagged[tagged["_regime"] == "A"]
        logger.info(
            f"--down-only: 原始 {len(trades)} 笔 → DOWN-only {len(down_trades)} 笔 "
            f"（regime 分布={regime_breakdown}）"
        )
        if len(down_trades) == 0:
            logger.error("--down-only 过滤后无 trades（当前 BTC 不在 DOWN regime？）")
            sys.exit(2)
        trades = down_trades.reset_index(drop=True)

    pnl = extract_pnl_series(trades, slippage_bps=args.slippage_bps, fee_bps=args.fee_bps)
    if len(pnl) == 0:
        logger.error("过滤后 pnl 为空（slippage/fee/down-only 不匹配？）")
        sys.exit(2)

    strategy = trades["strategy"].iloc[0] if "strategy" in trades.columns else "?"
    symbol_match = next((w for w in trades.columns if "inst" in w.lower() or "symbol" in w.lower()), None)
    symbol = trades[symbol_match].iloc[0] if symbol_match else "?"

    result = run_montecarlo(
        pnl,
        initial_capital=args.initial_capital,
        n_simulations=args.n_sims,
        sample_multiple=args.sample_multiple,
        seed=args.seed,
    )

    out_dir = (args.out_root or _output_root()) / f"{args.name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    meta = {
        "name": args.name,
        "strategy": strategy,
        "symbol": symbol,
        "walkforward_dir": str(wf_dir),
    }
    persist(result, meta, out_dir)
    print(json.dumps({
        "name": args.name,
        "n_real_trades": result.n_real_trades,
        "n_simulations": result.n_simulations,
        "final_equity_p50": round(result.final_equity_p50, 2),
        "total_return_p50_pct": round(result.total_return_p50_pct, 2),
        "max_dd_p95_pct": round(result.max_dd_p95 * 100, 2),
        "prob_ruin_50pct_pct": round(result.prob_ruin_50pct * 100, 2),
        "report": str(out_dir / "result.md"),
    }, indent=2, ensure_ascii=False))
    logger.info(f"完成 → {out_dir / 'result.md'}")


if __name__ == "__main__":
    main()
