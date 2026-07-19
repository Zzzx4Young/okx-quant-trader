# -*- coding: utf-8 -*-
"""
Market Filter — 流动性/黑名单过滤 (Constitution §4)

过滤维度：
1. 24h 交易量：低于阈值（默认 5000 万 USDT）排除
2. 资金费率：绝对值超过阈值（默认 0.1%）排除
3. 平台标记：处于观察区/下架风险的合约排除
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .config import get_config
from .utils import to_okx_swap_symbol

if TYPE_CHECKING:
    # 避免循环 import，仅类型检查需要
    from .client import OKXClient


logger = logging.getLogger(__name__)


# 缓存：避免每次都拉 API
_FILTER_CACHE: Dict[str, Any] = {
    "data": {},         # symbol -> FilterResult
    "expire_at": None,  # 下次刷新时间
}


def _cache_expired() -> bool:
    if _FILTER_CACHE["expire_at"] is None:
        return True
    return datetime.utcnow() > _FILTER_CACHE["expire_at"]


class FilterResult:
    """过滤结果"""

    def __init__(self, symbol: str, passed: bool, reasons: List[str]):
        self.symbol = symbol
        self.passed = passed
        self.reasons = reasons

    def __repr__(self):
        return f"<FilterResult {self.symbol} passed={self.passed} reasons={self.reasons}>"


class MarketFilter:
    """市场过滤（Constitution §4）

    接 OKXClient（不是 MarketAPI），因为需要访问 public API（instruments）
    验证合约状态。MarketAPI._client 是 HTTPClient，没有 .public 子客户端
    —— 历史上 market_filter.py:109 误用 `self._market._client.public`
    导致 AttributeError，所有 blacklist 检查都 fallback 到默认过滤，
    BTC/ETH 因此被错拦。v1.8.3 修复。
    """

    def __init__(self, client: "OKXClient", config: Optional[Any] = None):
        self._client = client
        self._market = client.market  # 保留别名给 ticker / funding_rate 用
        self._config = config or get_config()

    def check_symbol(self, symbol: str) -> FilterResult:
        """检查单个 symbol 是否通过过滤

        三个维度：
        1. 24h 成交量 ≥ 阈值
        2. |funding rate| ≤ 阈值
        3. 不在平台观察区
        """
        if not _cache_expired():
            cached = _FILTER_CACHE["data"].get(symbol)
            if cached is not None:
                return cached

        reasons = []

        # 1. 检查 24h 成交量
        try:
            ticker = self._market.get_ticker(symbol)
            if not ticker:
                reasons.append("无 ticker 数据")
            else:
                vol_24h = float(ticker[0].get("volCcy24h", 0))  # 24h 成交量（计价币）
                # 如果是 BTC 计价，转 USDT
                if symbol.startswith("BTC-"):
                    vol_24h *= float(ticker[0].get("last", 0))
                elif symbol.startswith("ETH-"):
                    vol_24h *= float(ticker[0].get("last", 0))

                threshold = self._config.blacklist_min_24h_volume_usdt
                if vol_24h < threshold:
                    reasons.append(f"24h 成交量 {vol_24h:.0f} < {threshold:.0f} USDT")
        except Exception as e:
            logger.warning(f"获取 ticker 失败 {symbol}: {e}")
            reasons.append(f"ticker 获取失败: {e}")

        # 2. 检查资金费率
        try:
            funding_resp = self._market.get_funding_rate(symbol)
            if funding_resp:
                funding_rate = float(funding_resp[0].get("fundingRate", 0))
                threshold = self._config.blacklist_max_funding_rate_abs
                if abs(funding_rate) > threshold:
                    reasons.append(
                        f"资金费率 |{funding_rate*100:.4f}%| > {threshold*100:.2f}%"
                    )
        except Exception as e:
            logger.warning(f"获取 funding_rate 失败 {symbol}: {e}")
            reasons.append(f"funding_rate 获取失败: {e}")

        # 3. 检查平台标记（OKX 返回的 instruments 可能包含状态字段）
        try:
            inst_id = symbol
            if not symbol.endswith("-SWAP"):
                inst_id = f"{symbol}-SWAP"
            # ✅ v1.8.3 修复：之前是 `self._market._client.public.get_instruments(...)`
            # 但 MarketAPI._client 是 HTTPClient，没有 .public 属性
            # → AttributeError → blacklist fallback → BTC/ETH 被默认拦截
            instruments = self._client.public.get_instruments(inst_type="SWAP")
            for inst in instruments:
                if inst.get("instId") == inst_id:
                    state = inst.get("state", "live")
                    if state != "live":
                        reasons.append(f"合约状态={state}（非 live）")
                    break
        except Exception as e:
            logger.warning(f"获取 instruments 失败 {symbol}: {e}")

        result = FilterResult(symbol, len(reasons) == 0, reasons)

        # 写缓存
        _FILTER_CACHE["data"][symbol] = result
        if _FILTER_CACHE["expire_at"] is None:
            refresh_hours = self._config.get("blacklist.refresh_interval_hours", 4)
            _FILTER_CACHE["expire_at"] = datetime.utcnow() + timedelta(hours=refresh_hours)

        return result

    def filter_whitelist(self, whitelist: List[str]) -> Dict[str, FilterResult]:
        """过滤白名单，返回 {symbol: FilterResult} 映射

        通过过滤的 symbol 不出现在结果中（即只返回被过滤掉的）。

        v1.8.3: 用 code.utils.to_okx_swap_symbol() 统一归一化（之前是手写
        不完整归一化，缺 -SWAP 后缀 → OKX API 返回 [51000] Parameter error
        → blacklist 默认过滤 BTC/ETH）。
        """
        results = {}
        for symbol in whitelist:
            inst_id = to_okx_swap_symbol(symbol)

            result = self.check_symbol(inst_id)
            if not result.passed:
                results[inst_id] = result
        return results

    def clear_cache(self):
        """清空缓存（用于定时刷新）"""
        _FILTER_CACHE["data"].clear()
        _FILTER_CACHE["expire_at"] = None


def get_filter() -> MarketFilter:
    """工厂函数：默认从 .env + global OKXClient 构造"""
    from .client import OKXClient
    return MarketFilter(OKXClient())