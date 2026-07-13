#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K 线数据拉取 + Parquet 缓存（Phase 1 数据引擎）

复用 code/market.py:MarketAPI.get_history_candles 端点
功能：
1. 增量拉取（检查 parquet 最大 ts，只拉新区间）
2. 分页循环（OKX limit 上限 100/300，按 bar 不同）
3. 倒序修正（OKX 返回 newest → oldest，存储前反转）
4. 字段标准化（[ts, o, h, l, c, vol, volCcy, volQuote] → 命名列）
5. Snappy 压缩 parquet（体积小 ~10x vs CSV）

CLI:
  python fetch_klines.py --inst-id BTC-USDT-SWAP --timeframe 1h --days 90
  python fetch_klines.py --inst-id ETH-USDT-SWAP --timeframe 15m --days 30
"""

import argparse
import sys
import time
from pathlib import Path
from typing import List

import pandas as pd

# 复用现有 MarketAPI（已含双 header + 重试 + 签名）
from code.client import OKXClient
from code.market import MarketAPI

# 同包 utils
from .utils import (
    DATA_ROOT,
    market_path,
    load_parquet,
    save_parquet,
    merge_incremental,
    retry_with_backoff,
)


# OKX 历史 K 线 limit 上限（按 bar 不同）
BAR_LIMITS = {
    "1m": 300,    # 5h
    "5m": 300,    # 25h
    "15m": 300,   # 75h
    "30m": 300,   # 150h
    "1h": 300,    # 12.5d
    "4h": 300,    # 50d
    "1d": 300,    # ~10mo
}


def _normalize_bar(timeframe: str) -> str:
    """
    标准化 timeframe → OKX V5 bar 参数
    ⚠️ OKX V5 大小写敏感：小时/日/周 须大写（H/D/W），分钟小写（m）
    :param timeframe: "1h" / "1H" / "15m" / "1d" / "1D" 都接受
    :return: "1H" / "15m" / "1D" 等 OKX 标准格式
    """
    tf = timeframe.strip()
    if tf.lower().endswith(("h", "d", "w")):
        # 小时/日/周 → 大写
        return tf.upper()
    elif tf.lower().endswith("m"):
        # 分钟 → 小写
        return tf.lower()
    return tf  # 原样返回，让 OKX 自己报错


@retry_with_backoff(max_retries=3, exceptions=(Exception,))
def _fetch_page(market: MarketAPI, inst_id: str, bar: str, after: str = None) -> List[list]:
    """拉一页 K 线（OKX 返回 newest → oldest 倒序）

    ⚠️ OKX V5 实测语义（与官方文档描述相反）：
    - after=<ts> → 返回 ts < ts 的 limit 条记录（更老的数据）
    - before=<ts> → 文档说"更老"，实测返回最新数据（参数似乎被忽略）
    - 正确分页：循环传 after=<上一页最后一根的 ts>
    """
    limit = BAR_LIMITS.get(bar, 100)
    return market.get_history_candles(
        inst_id=inst_id,
        bar=_normalize_bar(bar),
        limit=limit,
        after=after,
    )


def fetch_klines(
    inst_id: str,
    timeframe: str = "1h",
    days: int = 90,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    拉取 K 线并写入 Parquet（带增量更新）

    :param inst_id: 交易对，如 BTC-USDT-SWAP
    :param timeframe: K 线周期，如 1h / 15m / 4h
    :param days: 拉取天数（仅在无现有 parquet 时生效）
    :param verbose: 是否打印进度
    :return: 写入的 DataFrame
    """
    if timeframe not in BAR_LIMITS:
        raise ValueError(f"不支持的 timeframe: {timeframe}, 可选 {list(BAR_LIMITS.keys())}")

    parquet_path = market_path(inst_id, timeframe)
    existing = load_parquet(parquet_path)

    # 决定拉取起点（after 参数语义：返回 ts < after 的记录）
    if existing is not None and not existing.empty:
        # 增量模式：从已存最小 ts 之前继续拉（after = min_ts）
        start_cursor = str(int(existing["timestamp"].min()))
        mode = "增量更新（向更早拉取）"
    else:
        # 全量模式：起点设为 now（最新时间），拉取 [now-days, now] 的所有数据
        from datetime import datetime, timezone
        start_cursor = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        mode = "全量拉取"

    if verbose:
        print(f"[{inst_id} {timeframe}] {mode} 起点 cursor={start_cursor[:10]}...")

    market = OKXClient().market
    all_pages: List[list] = []
    cursor = start_cursor
    page_count = 0
    max_pages = 50  # 安全上限（约 50 × 300 = 15000 条，足够 1h/1.7 年）

    while page_count < max_pages:
        raw_page = _fetch_page(market, inst_id, timeframe, after=cursor)

        if not raw_page:
            break

        all_pages.extend(raw_page)
        page_count += 1

        if verbose:
            print(f"  第 {page_count} 页: {len(raw_page)} 条, "
                  f"范围 [{raw_page[-1][0]} ~ {raw_page[0][0]}]")

        # 检查是否还能继续分页
        if len(raw_page) < BAR_LIMITS[timeframe]:
            # 不足一页，说明已到尽头
            break

        # 下一页 after = 当前页最老一根的 ts
        # OKX 返回 newest → oldest，所以 raw_page[-1][0] 是最老的 ts
        cursor = str(raw_page[-1][0])

        # 速率限制保护：每秒最多 10 次
        time.sleep(0.15)

    if not all_pages:
        if verbose:
            print(f"  ⚠️  无新数据")
        return existing if existing is not None else pd.DataFrame()

    # 转换字段：OKX history-candles 实际返回 9 列
    # [ts, o, h, l, c, vol_base, vol_ccy, vol_quote, confirm]
    # ⚠️ OKX 返回 newest → oldest，先反转再存
    df_new = pd.DataFrame(all_pages, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "volume_currency", "volume_quote", "confirm",
    ])
    df_new = df_new.iloc[::-1].reset_index(drop=True)  # 反转为 oldest → newest
    df_new["timestamp"] = df_new["timestamp"].astype("int64")
    for col in ["open", "high", "low", "close", "volume", "volume_currency", "volume_quote"]:
        df_new[col] = df_new[col].astype("float64")
    df_new["confirm"] = df_new["confirm"].astype("int64")

    # 合并已有数据
    df_merged = merge_incremental(existing, df_new)

    save_parquet(df_merged, parquet_path)

    if verbose:
        size_kb = parquet_path.stat().st_size / 1024
        print(f"  ✓ 写入 {parquet_path.relative_to(DATA_ROOT.parent)} "
              f"({len(df_merged)} 条, {size_kb:.1f} KB)")
        print(f"  ✓ 时间范围: {df_merged['timestamp'].min()} ~ {df_merged['timestamp'].max()}")
        if not df_merged.empty:
            from .utils import ms_to_datetime
            print(f"  ✓ UTC: {ms_to_datetime(df_merged['timestamp'].min())} → "
                  f"{ms_to_datetime(df_merged['timestamp'].max())}")

    return df_merged


def main():
    parser = argparse.ArgumentParser(description="拉取 OKX K 线 + 写 Parquet")
    parser.add_argument("--inst-id", required=True, help="如 BTC-USDT-SWAP")
    parser.add_argument("--timeframe", default="1h", help="1m/5m/15m/30m/1h/4h/1d")
    parser.add_argument("--days", type=int, default=90, help="首次拉取天数（增量时忽略）")
    args = parser.parse_args()

    df = fetch_klines(args.inst_id, args.timeframe, args.days)
    print(f"\n汇总: {len(df)} 条 K 线已缓存")


if __name__ == "__main__":
    main()