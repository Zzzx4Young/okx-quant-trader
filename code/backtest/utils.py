#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest 公共工具（V2.1 设计稿 common/utils.py 的 okx/ 实现版）

核心功能：
1. round_to_standard_funding_time：毫秒级时间戳对齐（防 API 微秒漂移）
2. parquet_io：Parquet 读写 + 增量更新工具
3. retry_with_backoff：API 重试装饰器
"""

import os
import time
import random
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, List, Optional

import pandas as pd


# ─── 时间戳对齐（V2.1 关键点 1） ───

def round_to_standard_funding_time(ts_ms: int, interval_hours: int = 8) -> int:
    """
    将带有微秒漂移的资金费率时间戳规整到标准结算点。

    V2.1 设计：
    - OKX 历史费率 API 可能返回 11:59:59.998 这样的偏移
    - 必须四舍五入到最近的整点（1h/2h/4h/8h 周期）
    - 否则半开区间归属会出现边界争议

    :param ts_ms: 毫秒级 Unix 时间戳
    :param interval_hours: 结算周期（小时），默认 8h（OKX 标准）
    :return: 规整后的毫秒级时间戳
    """
    interval_ms = interval_hours * 3600 * 1000
    rounded = int(round(ts_ms / interval_ms) * interval_ms)
    # 边界 case：ts_ms 正好在两个结算点中间时，round 会进位
    # 此时如果进位后超出 ts_ms 很多，回退到 floor
    if rounded - ts_ms > interval_ms / 2:
        rounded -= interval_ms
    return rounded


def ms_to_datetime(ts_ms: int) -> datetime:
    """毫秒级时间戳 → datetime（UTC）"""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)


def datetime_to_ms(dt: datetime) -> int:
    """datetime → 毫秒级时间戳"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


# ─── Parquet 读写 ───

def load_parquet(path: Path) -> Optional[pd.DataFrame]:
    """加载 Parquet，文件不存在返回 None"""
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if not df.empty and "timestamp" in df.columns:
        df["timestamp"] = df["timestamp"].astype("int64")
    return df


def save_parquet(df: pd.DataFrame, path: Path):
    """保存 Parquet（自动创建父目录）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow", compression="snappy")


def merge_incremental(
    existing: Optional[pd.DataFrame],
    new: pd.DataFrame,
    key_col: str = "timestamp",
) -> pd.DataFrame:
    """
    合并增量数据（去重 + 排序）

    :param existing: 已有数据
    :param new: 新拉取的数据
    :param key_col: 去重 key（默认 timestamp）
    :return: 合并后按 key 排序的 DataFrame
    """
    if existing is None or existing.empty:
        combined = new.copy()
    else:
        combined = pd.concat([existing, new], ignore_index=True)

    # 去重（保留 last，因 OKX 可能修正历史）
    combined = combined.drop_duplicates(subset=[key_col], keep="last")
    combined = combined.sort_values(key_col).reset_index(drop=True)
    return combined


# ─── API 重试 ───

def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
):
    """
    API 重试装饰器（指数退避 + 抖动）

    OKX 限流常见错误：50011 Too Many Requests
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_retries:
                        raise
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    delay += random.uniform(0, 0.5)  # 抖动
                    time.sleep(delay)
            raise last_exc  # pragma: no cover
        return wrapper
    return decorator


# ─── 路径辅助 ───

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_ROOT = PROJECT_ROOT / "data"


def market_path(inst_id: str, timeframe: str) -> Path:
    """K 线 Parquet 路径：data/market/{instId}/{timeframe}.parquet"""
    return DATA_ROOT / "market" / inst_id / f"{timeframe}.parquet"


def funding_path(inst_id: str) -> Path:
    """资金费率 Parquet 路径：data/funding/{instId}_funding.parquet"""
    return DATA_ROOT / "funding" / f"{inst_id}_funding.parquet"


__all__ = [
    "round_to_standard_funding_time",
    "ms_to_datetime",
    "datetime_to_ms",
    "load_parquet",
    "save_parquet",
    "merge_incremental",
    "retry_with_backoff",
    "market_path",
    "funding_path",
    "DATA_ROOT",
]