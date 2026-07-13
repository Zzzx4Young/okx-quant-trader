#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 1 数据加载器

职责：
1. 加载 Parquet（K 线 + funding）
2. 切时间窗口（start/end → DataFrame slice）
3. 缺失值处理（前向填充 + 标记列）
4. 返回标准化数据结构

设计原则：
- 返回只读视图（防止误修改原 parquet 缓存）
- 时间戳统一 int64 毫秒级
- 字段类型严格：float64 价格、int64 时间戳
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from .utils import (
    load_parquet,
    market_path,
    funding_path,
    ms_to_datetime,
)


@dataclass
class BacktestData:
    """回测数据集（K线 + funding 配对）"""
    inst_id: str
    timeframe: str
    klines: pd.DataFrame       # 主时间轴，老→新
    funding: pd.DataFrame      # funding 历史（含 fundingTime_aligned）
    
    @property
    def start_ts(self) -> int:
        return int(self.klines["timestamp"].iloc[0])
    
    @property
    def end_ts(self) -> int:
        return int(self.klines["timestamp"].iloc[-1])
    
    @property
    def bar_count(self) -> int:
        return len(self.klines)
    
    def __repr__(self):
        return (
            f"<BacktestData {self.inst_id} {self.timeframe} "
            f"bars={self.bar_count} "
            f"range=[{ms_to_datetime(self.start_ts)} → {ms_to_datetime(self.end_ts)}]>"
        )


def load(
    inst_id: str,
    timeframe: str = "1h",
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    forward_fill_missing: bool = True,
) -> BacktestData:
    """
    加载回测数据（K线 + funding 自动配对）

    :param inst_id: 交易对，如 BTC-USDT-SWAP
    :param timeframe: K 线周期，如 1h
    :param start_ts: 起始时间戳（毫秒），None = parquet 最早
    :param end_ts: 结束时间戳（毫秒），None = parquet 最晚
    :param forward_fill_missing: 缺失 K 线时是否前向填充（默认 True）
    :return: BacktestData（只读视图）
    :raises FileNotFoundError: parquet 不存在
    """
    # ─── 1. 加载 K 线 ───
    klines = load_parquet(market_path(inst_id, timeframe))
    if klines is None or klines.empty:
        raise FileNotFoundError(
            f"K线 parquet 不存在: {market_path(inst_id, timeframe)}\n"
            f"先跑: python -m code.backtest.fetch_klines --inst-id {inst_id} --timeframe {timeframe}"
        )

    # 严格 int64（防 parquet 反序列化偏差）
    klines["timestamp"] = klines["timestamp"].astype("int64")
    klines = klines.sort_values("timestamp").reset_index(drop=True)

    # ─── 2. 时间窗口切片 ───
    if start_ts is not None:
        klines = klines[klines["timestamp"] >= start_ts].reset_index(drop=True)
    if end_ts is not None:
        klines = klines[klines["timestamp"] <= end_ts].reset_index(drop=True)

    if klines.empty:
        raise ValueError(f"窗口 [{start_ts} → {end_ts}] 内无 K 线数据")

    # ─── 3. 缺失 K 线检测 + 标记 ───
    # 期望的相邻 ts 差 = timeframe 毫秒数
    expected_diff_ms = _timeframe_to_ms(timeframe)
    diffs = klines["timestamp"].diff()
    klines["bar_missing"] = (diffs > expected_diff_ms).fillna(False).astype(bool)

    n_missing = int(klines["bar_missing"].sum())
    if n_missing > 0 and forward_fill_missing:
        # 前向填充价格（保持 OHLC 连续性），但标记 bar_missing=True
        klines = klines.copy()
        for col in ["open", "high", "low", "close"]:
            klines[col] = klines[col].ffill()
        # volume 等于 0（标记缺失时段无成交）
        klines.loc[klines["bar_missing"], "volume"] = 0.0

    # ─── 4. 加载 funding ───
    funding = load_parquet(funding_path(inst_id))
    if funding is None or funding.empty:
        # 允许 funding 缺失（策略 D 会被跳过，其他策略不受影响）
        funding = pd.DataFrame(columns=[
            "fundingTime", "fundingRate", "fundingTime_aligned", "instType", "instId"
        ])
    else:
        funding["fundingTime"] = funding["fundingTime"].astype("int64")
        funding["fundingTime_aligned"] = funding["fundingTime_aligned"].astype("int64")
        funding["fundingRate"] = funding["fundingRate"].astype("float64")
        funding = funding.sort_values("fundingTime_aligned").reset_index(drop=True)

    # ─── 5. 返回只读视图 ───
    klines.flags.writeable = False
    funding.flags.writeable = False

    return BacktestData(
        inst_id=inst_id,
        timeframe=timeframe,
        klines=klines,
        funding=funding,
    )


def _timeframe_to_ms(timeframe: str) -> int:
    """timeframe → 毫秒数"""
    tf = timeframe.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60 * 1000
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600 * 1000
    if tf.endswith("d"):
        return int(tf[:-1]) * 86400 * 1000
    if tf.endswith("w"):
        return int(tf[:-1]) * 7 * 86400 * 1000
    raise ValueError(f"不支持的 timeframe: {timeframe}")


__all__ = ["BacktestData", "load"]