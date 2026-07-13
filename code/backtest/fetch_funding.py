#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金费率历史拉取 + Parquet 缓存（Phase 1 数据引擎）

V2.1 关键点 1 + 关键点 3：
1. 毫秒级对齐：拉取的 fundingTime 经过 round_to_standard_funding_time 规整
2. 双用途隔离：数据存入 funding.parquet 后，由调用方在查询时做
   - 成本扣除：fundingTime <= t_curr（半开区间包含）
   - 策略信号：fundingTime < t_curr（严格小于）

CLI:
  python fetch_funding.py --inst-id BTC-USDT-SWAP --days 90
  python fetch_funding.py --inst-id ETH-USDT-SWAP --days 30
"""

import argparse
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List

import pandas as pd

from code.client import OKXClient
from code.market import MarketAPI

from .utils import (
    DATA_ROOT,
    funding_path,
    load_parquet,
    save_parquet,
    merge_incremental,
    retry_with_backoff,
    round_to_standard_funding_time,
    datetime_to_ms,
)


# OKX 公共 API 单页 limit 上限
FUNDING_PAGE_LIMIT = 100

# 推测的资金费率结算周期（用于 round_to_standard_funding_time）
# OKX 标准是 8h，但 2025/2026 升级后极端波动会缩短到 4h/2h/1h
# 我们用 1h 作为"最细粒度"对齐，因为更短周期不会发生
DEFAULT_FUNDING_INTERVAL_HOURS = 1


@retry_with_backoff(max_retries=3, exceptions=(Exception,))
def _fetch_funding_page(market: MarketAPI, inst_id: str, after: str = None) -> List[dict]:
    """拉一页资金费率历史（OKX 返回 newest → oldest 倒序）

    ⚠️ OKX V5 实测语义：
    - after=<ms_ts> → 返回 ts < after 的 limit 条记录（更老的数据）✅ 有效
    - before=<ms_ts> → 返回空（参数无效）❌
    - 正确分页：循环传 after=<上一页最后一根 fundingTime>
    """
    params = {"instId": inst_id, "limit": FUNDING_PAGE_LIMIT}
    if after:
        params["after"] = after
    return market._client.get(
        "/api/v5/public/funding-rate-history",
        params=params,
    )


def fetch_funding(
    inst_id: str,
    days: int = 90,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    拉取资金费率历史并写入 Parquet（带增量更新 + 毫秒对齐）

    :param inst_id: 永续合约 ID，如 BTC-USDT-SWAP
    :param days: 首次拉取天数（增量模式忽略）
    :param verbose: 是否打印进度
    :return: 写入的 DataFrame
    """
    parquet_path = funding_path(inst_id)
    existing = load_parquet(parquet_path)

    # 决定拉取起点（after 参数语义：返回 ts < after 的记录）
    if existing is not None and not existing.empty:
        start_cursor = str(int(existing["fundingTime_aligned"].min()))
        mode = "增量更新（向更早拉取）"
    else:
        # 全量模式：起点设为 now（最新时间），循环向更老拉
        start_cursor = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        mode = "全量拉取"

    if verbose:
        print(f"[{inst_id} funding] {mode} 起点 after={start_cursor[:10]}...")

    market = OKXClient().market
    all_pages: List[dict] = []
    cursor = start_cursor
    page_count = 0
    max_pages = 30  # 30 × 100 = 3000 条 ≈ 8h 周期下 1000 天 ≈ 2.7 年

    while page_count < max_pages:
        raw_page = _fetch_funding_page(market, inst_id, after=cursor)

        if not raw_page:
            break

        all_pages.extend(raw_page)
        page_count += 1

        if verbose:
            ts_min = raw_page[-1].get("fundingTime", "?")
            ts_max = raw_page[0].get("fundingTime", "?")
            print(f"  第 {page_count} 页: {len(raw_page)} 条, "
                  f"fundingTime 范围 [{ts_min} ~ {ts_max}]")

        if len(raw_page) < FUNDING_PAGE_LIMIT:
            break

        # 下一页 after = 当前页最老一条的 fundingTime
        cursor = raw_page[-1].get("fundingTime")
        if not cursor:
            break

        time.sleep(0.15)

    if not all_pages:
        if verbose:
            print(f"  ⚠️  无新数据")
        return existing if existing is not None else pd.DataFrame()

    # 转换字段
    df_new = pd.DataFrame(all_pages)
    if "fundingTime" not in df_new.columns or "fundingRate" not in df_new.columns:
        raise ValueError(f"OKX 返回字段缺失: {df_new.columns.tolist()}")

    df_new["fundingTime"] = df_new["fundingTime"].astype("int64")
    df_new["fundingRate"] = df_new["fundingRate"].astype("float64")

    # V2.1 关键点 1：毫秒级对齐到标准结算点
    df_new["fundingTime_aligned"] = df_new["fundingTime"].apply(
        lambda ts: round_to_standard_funding_time(ts, DEFAULT_FUNDING_INTERVAL_HOURS)
    )

    # OKX 返回 newest → oldest，反转为 oldest → newest
    df_new = df_new.iloc[::-1].reset_index(drop=True)

    # 合并（按 fundingTime_aligned 去重，因对齐后可能有冲突）
    df_merged = merge_incremental(existing, df_new, key_col="fundingTime_aligned")

    save_parquet(df_merged, parquet_path)

    if verbose:
        size_kb = parquet_path.stat().st_size / 1024
        print(f"  ✓ 写入 {parquet_path.relative_to(DATA_ROOT.parent)} "
              f"({len(df_merged)} 条, {size_kb:.1f} KB)")
        if not df_merged.empty:
            ts_min = df_merged["fundingTime_aligned"].min()
            ts_max = df_merged["fundingTime_aligned"].max()
            rate_min = df_merged["fundingRate"].min()
            rate_max = df_merged["fundingRate"].max()
            print(f"  ✓ 时间范围: {ts_min} ~ {ts_max}")
            print(f"  ✓ 费率范围: {rate_min*100:.4f}% ~ {rate_max*100:.4f}%")

    return df_merged


def main():
    parser = argparse.ArgumentParser(description="拉取 OKX 资金费率历史 + 写 Parquet")
    parser.add_argument("--inst-id", required=True, help="如 BTC-USDT-SWAP")
    parser.add_argument("--days", type=int, default=90, help="首次拉取天数")
    args = parser.parse_args()

    df = fetch_funding(args.inst_id, args.days)
    print(f"\n汇总: {len(df)} 条资金费率已缓存")


if __name__ == "__main__":
    main()