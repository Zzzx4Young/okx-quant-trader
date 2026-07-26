#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regime Filter —— 判定当前 BTC regime 推荐哪个策略

═══════════════════════════════════════════════════════════════════
目的：根据 BTC 当前 regime（趋势状态），给出"该不该入场 + 入哪个策略"的建议
     这是从 Phase 3A walkforward 分析得出的可落地规则。
═══════════════════════════════════════════════════════════════════

决策逻辑（基于 walkforward 18 窗口的横向对比）：
  - 强 UP（90d ret > +10% AND EMA50 > EMA200 * 1.02）：不入场
    原因：A/C 在 UP 区都是 0 viable（avg best_ret 负 25pp vs buy&hold）
  - 强 DOWN（90d ret < -5% AND EMA50 < EMA200）：入场首选 A
    原因：A 在 DOWN 区 100% viable（mean +1.9%，实际赚钱）；C 86% viable（hedge）
  - SIDE（其他区间）：不入场，标记人工 review
    原因：A 33% viable、C 25% viable，高度依赖震荡幅度不可复现

可调用形式：
  1. 生产：signal_runner.py 每次 cron tick 调用一次，判定后做信号生成/不生成
  2. 工具：CLI `python -m okx.code.regime_filter` 打印当前 regime + 建议
  3. 测试：tests/test_regime_filter.py 用 mock K-lines 验证决策逻辑
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import pandas as pd


# ────────────────────────────────────────────────────────────────────
# 默认阈值（来自 Phase 3A 分析 — 见 okx/docs/agent-context/walkforward/
# cross-strategy-a-vs-c.md）
# ────────────────────────────────────────────────────────────────────
DEFAULT_UP_RET_THRESHOLD = 10.0       # 90d return > +10% → UP
DEFAULT_DOWN_RET_THRESHOLD = -5.0     # 90d return < -5% → DOWN
DEFAULT_EMA_BULLISH_RATIO = 1.02      # EMA50/EMA200 > 1.02 → 多头确认


def resample_to_daily(klines: pd.DataFrame) -> pd.Series:
    """把任意时间粒度的 K-lines 重采样到 1d close。

    支持 'timestamp' (ms) + 'close' 列的 OHLCV K-lines。
    返回: pd.Series（DatetimeIndex UTC, name='close'）

    设计：保留 close 的 last-of-day，重采样后用 dropna 去掉不完整日。
    """
    if klines is None or klines.empty:
        return pd.Series(dtype="float64", name="close")

    df = klines.copy()
    if "timestamp" in df.columns:
        df["dt"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    elif "dt" in df.columns:
        df["dt"] = pd.to_datetime(df["dt"], utc=True)
    else:
        raise ValueError("K-lines 缺 timestamp/dt 列")

    df = df.set_index("dt").sort_index()
    daily = df.resample("1D").agg({"close": "last"})
    return daily["close"].dropna()


def _compute_features(daily_close: pd.Series) -> dict:
    """计算关键指标：last_price, 90d_ret, EMA50, EMA200

    返回 dict 便于测试 inspect。
    边界：
      - < 2 元素: ret/ema 全 None（last_price 也无意义）
      - 2-90 元素: ret_90d_pct = None（数据不足 90 天，不强算）
      - 91-199 元素: ret 有，EMA50 有，EMA200 = None（不够 200 天）
      - ≥ 200 元素: ret/EMA50/EMA200 全有
    """
    n = len(daily_close)
    if n < 2:
        return {"last_price": float(daily_close.iloc[-1]) if n else 0.0,
                "ret_90d_pct": None, "ema50": None, "ema200": None,
                "ema_ratio": None, "bars": n}

    last = float(daily_close.iloc[-1])
    # 90 天 return 需要 ≥91 个数据点
    if n >= 91:
        ninety_ago = float(daily_close.iloc[-91])
        ret_90d_pct = (last / ninety_ago - 1.0) * 100.0 if ninety_ago > 0 else None
    else:
        ret_90d_pct = None

    ema50 = float(daily_close.ewm(span=50, adjust=False).mean().iloc[-1]) if n >= 50 else None
    ema200 = float(daily_close.ewm(span=200, adjust=False).mean().iloc[-1]) if n >= 200 else None
    ema_ratio = (ema50 / ema200) if (ema50 is not None and ema200 not in (None, 0)) else None

    return {
        "last_price": last,
        "ret_90d_pct": ret_90d_pct,
        "ema50": ema50,
        "ema200": ema200,
        "ema_ratio": ema_ratio,
        "bars": n,
    }


def recommended_strategy(
    btc_klines: pd.DataFrame,
    *,
    up_ret_threshold: float = DEFAULT_UP_RET_THRESHOLD,
    down_ret_threshold: float = DEFAULT_DOWN_RET_THRESHOLD,
    ema_bullish_ratio: float = DEFAULT_EMA_BULLISH_RATIO,
) -> Tuple[Optional[str], str, dict]:
    """判定当前 BTC regime 推荐哪个策略。

    :param btc_klines: BTC K-lines (DataFrame with 'timestamp' (ms) + 'close' columns)
    :param up_ret_threshold: 90d return > this = UP 拒入场
    :param down_ret_threshold: 90d ret < this = DOWN 首选 A
    :param ema_bullish_ratio: EMA50/EMA200 > this = 多头确认
    :return: (strategy_letter or None, reason, features dict)
        - strategy_letter: 'A' / 'B' / 'C' / 'D' / None
        - reason: 人类可读的判定理由
        - features: 计算过程的中间值，便于 debug 和 dashboard 展示

    决策矩阵：
        强 UP   (ret > up_th AND ema_ratio > bullish_ratio)   → None + "UP..."
        强 DOWN (ret < down_th AND ema_ratio < 1.0)           → "A" + "DOWN..."
        其他                                                  → None + "SIDE 待人工评估..."
    """
    daily_close = resample_to_daily(btc_klines)
    feats = _compute_features(daily_close)

    if feats["ret_90d_pct"] is None or feats["ema_ratio"] is None:
        return None, f"数据不足 (bars={feats['bars']}, ret={feats['ret_90d_pct']}, ema_ratio={feats['ema_ratio']})", feats

    ret_90d = feats["ret_90d_pct"]
    ema_ratio = feats["ema_ratio"]

    # 强 UP：90d ret 高 AND EMA50 在 EMA200 上方 → 拒入场
    if ret_90d > up_ret_threshold and ema_ratio > ema_bullish_ratio:
        return None, (
            f"UP+EMA多头 拒入场 (90d_ret={ret_90d:+.1f}% > {up_ret_threshold}%, "
            f"EMA50/EMA200={ema_ratio:.3f} > {ema_bullish_ratio})"
        ), feats

    # 强 DOWN：90d ret 低 AND EMA50 在 EMA200 下方 → 首选 A
    if ret_90d < down_ret_threshold and ema_ratio < 1.0:
        return "A", (
            f"DOWN+EMA空头 首选 A (90d_ret={ret_90d:+.1f}% < {down_ret_threshold}%, "
            f"EMA50/EMA200={ema_ratio:.3f} < 1.0)"
        ), feats

    # SIDE 或混合信号 → 待人工评估
    return None, (
        f"SIDE 待人工评估 (90d_ret={ret_90d:+.1f}%, "
        f"EMA50/EMA200={ema_ratio:.3f}, 阈值: UP>{up_ret_threshold}%/EMA>{ema_bullish_ratio}, "
        f"DOWN<{down_ret_threshold}%/EMA<1.0)"
    ), feats


# ────────────────────────────────────────────────────────────────────
# CLI 工具：打印当前 state（便于 ops sanity check）
# ────────────────────────────────────────────────────────────────────
def _cli() -> int:
    import argparse
    from pathlib import Path
    from okx.code.backtest.data_loader import load

    parser = argparse.ArgumentParser(
        description="打印当前 BTC regime + 推荐策略",
    )
    parser.add_argument("--symbol", default="BTC-USDT-SWAP")
    parser.add_argument("--timeframe", default="1h",
                        help="K 线周期（默认 1h；regime filter 内部自动 resample 到 1d）")
    args = parser.parse_args()

    print(f"📊 加载 {args.symbol} {args.timeframe} K-lines ...")
    data = load(args.symbol, args.timeframe)
    print(f"   bars={data.bar_count}, "
          f"range=[{data.start_ts} → {data.end_ts}]")

    strategy, reason, feats = recommended_strategy(data.klines)

    print()
    print("━━━ 当前 regime 判断 ━━━")
    print(f"  90d return:   {feats['ret_90d_pct']:+.2f}%" if feats['ret_90d_pct'] is not None else "  90d return:   N/A")
    print(f"  EMA50:        {feats['ema50']:,.0f}" if feats['ema50'] else "  EMA50:        N/A")
    print(f"  EMA200:       {feats['ema200']:,.0f}" if feats['ema200'] else "  EMA200:       N/A")
    print(f"  EMA ratio:    {feats['ema_ratio']:.4f}" if feats['ema_ratio'] else "  EMA ratio:    N/A")
    print()
    icon = "✅" if strategy else "❌"
    print(f"  {icon} 推荐策略: {strategy or 'NONE (拒入场)'}")
    print(f"     理由: {reason}")
    return 0


__all__ = [
    "resample_to_daily",
    "_compute_features",
    "recommended_strategy",
    "tag_trades_by_regime",
    "DEFAULT_UP_RET_THRESHOLD",
    "DEFAULT_DOWN_RET_THRESHOLD",
    "DEFAULT_EMA_BULLISH_RATIO",
]


def tag_trades_by_regime(
    trades: pd.DataFrame,
    *,
    bar: str = "1h",
    end_ts_column: str = "exit_ts",
    window_id_column: str = "window_id",
    symbol: str = "BTC-USDT-SWAP",
) -> pd.DataFrame:
    """为 trades 添加 '_regime' 列：'A' | 'UP' | 'SIDE' | 'UNKNOWN'

    状态语义：
      - 'A'   DOWN+EMA空头 ：regime_filter 推荐 A 策略（live 会入场）
      - 'UP'  强 UP+EMA多头：拒入场（live 不交易）
      - 'SIDE' 其他           ：regime_filter 默认拒入场
      - 'UNKNOWN' 数据不足  ：无法判定

    实现要点：
      - 按 unique window_id 调一次 recommended_strategy（不是每笔调）
      - window 的 regime_snapshot_ts = 该 window 末笔 exit_ts（模拟"当时判断"）
      - 同一 window 的所有 trades 共用 regime label
      - 依赖 okx.code.backtest.data_loader.load(symbol, bar, end_ts=...)

    :return: 拷贝原 DataFrame + '_regime' 列（同行复制，length 不变）
    """
    if window_id_column not in trades.columns:
        raise KeyError(f"trades 缺少 window_id 列（'{window_id_column}'）；需在 load_trades 时保留")

    df = trades.copy()

    # 1. 收集 (window_id, end_ts)
    win_end_ts = (
        df.groupby(window_id_column)[end_ts_column]
        .max()
        .reset_index()
        .rename(columns={end_ts_column: "_regime_snapshot_ts"})
    )
    win_end_ts["_regime"] = "UNKNOWN"  # 默认

    # 2. 对每个 unique window 调一次 recommended_strategy
    from okx.code.backtest.data_loader import load as load_klines

    for i, row in win_end_ts.iterrows():
        win_id = row[window_id_column]
        end_ts_ms = int(row["_regime_snapshot_ts"])
        try:
            btc = load_klines(symbol, bar, end_ts=end_ts_ms)
            strat, _reason, _feats = recommended_strategy(btc.klines)
            if strat == "A":
                win_end_ts.at[i, "_regime"] = "A"
            elif strat is None:
                ret_90d = _feats.get("ret_90d_pct")
                ema_ratio = _feats.get("ema_ratio")
                if (
                    ret_90d is not None and ema_ratio is not None
                    and ret_90d > DEFAULT_UP_RET_THRESHOLD
                    and ema_ratio > DEFAULT_EMA_BULLISH_RATIO
                ):
                    win_end_ts.at[i, "_regime"] = "UP"
                else:
                    win_end_ts.at[i, "_regime"] = "SIDE"
            else:
                win_end_ts.at[i, "_regime"] = "UNKNOWN"
        except Exception:
            win_end_ts.at[i, "_regime"] = "UNKNOWN"

    # 3. 合并 _regime 回原 df
    df = df.merge(
        win_end_ts[[window_id_column, "_regime"]],
        on=window_id_column,
        how="left",
    )
    df["_regime"] = df["_regime"].fillna("UNKNOWN")
    return df


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
