# -*- coding: utf-8 -*-
"""
OKX API v5 市场数据模块（公开接口，无需签名）
"""

from typing import Any, Dict, List, Optional

from ._http import HTTPClient


class MarketAPI:
    """市场数据 API"""

    def __init__(self, client: HTTPClient):
        self._client = client

    def get_ticker(self, inst_id: str) -> List[Dict]:
        """
        获取单个交易对的行情

        :param inst_id: 交易对 ID，如 'BTC-USDT'
        :return: 行情数据字典
        """
        return self._client.get("/api/v5/market/ticker", params={"instId": inst_id})

    def get_tickers(self, inst_type: str = "SPOT") -> List[Dict]:
        """
        获取所有交易对的行情

        :param inst_type: 品种类型 SPOT/MARGIN/SWAP/FUTURES/OPTION
        :return: 行情列表
        """
        return self._client.get("/api/v5/market/tickers", params={"instType": inst_type})

    def get_orderbook(
        self, inst_id: str, depth: int = 20, sz: Optional[int] = None
    ) -> Dict:
        """
        获取订单簿

        :param inst_id: 交易对 ID
        :param depth: 档位数，默认 20
        :param sz: 市场深度数量（某些端点支持）
        :return: 订单簿数据
        """
        params: Dict[str, Any] = {"instId": inst_id, "sz": sz or depth}
        return self._client.get("/api/v5/market/books", params=params)

    def get_orderbook_lite(self, inst_id: str, depth: int = 20) -> List[Dict]:
        """
        获取订单簿（轻量版）

        :param inst_id: 交易对 ID
        :param depth: 档位数
        :return: 订单簿数据
        """
        params: Dict[str, Any] = {"instId": inst_id, "sz": depth}
        return self._client.get("/api/v5/market/books-lite", params=params)

    def get_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[List]:
        """
        获取 K 线数据（蜡烛图）

        :param inst_id: 交易对 ID
        :param bar: K 线周期，如 '1m', '5m', '15m', '1H', '4H', '1D'
        :param limit: 返回数量上限（1-100）
        :param after: 起始光标（时间戳或 index，筛选 newer）
        :param before: 结束光标（时间戳或 index，筛选 older）
        :return: K 线数据列表（oldest → newest），每项为 [ts, open, high, low, close, vol]

        注意：OKX 接口默认返回 newest → oldest（倒序）。本方法在返回前反转
        为 oldest → newest，让调用方用 [-1] 即可拿到最新一根。
        """
        params: Dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": limit}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        candles = self._client.get("/api/v5/market/candles", params=params)
        # 倒序 → 正序 (oldest first)，避免调用方拿到“最新”成“历史”
        return list(reversed(candles)) if candles else candles

    def get_history_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[List]:
        """
        获取历史 K 线数据（近2年）

        :param inst_id: 交易对 ID
        :param bar: K 线周期
        :param limit: 返回数量上限
        :param after: 起始光标
        :param before: 结束光标
        :return: K 线数据列表
        """
        params: Dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": limit}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/market/history-candles", params=params)

    def get_trades(self, inst_id: str, limit: int = 100) -> List[Dict]:
        """
        获取实时成交（最近60条）

        :param inst_id: 交易对 ID
        :param limit: 返回数量上限（1-100）
        :return: 成交列表
        """
        return self._client.get("/api/v5/market/trades", params={"instId": inst_id, "limit": limit})

    def get_history_trades(self, inst_id: str, limit: int = 100) -> List[Dict]:
        """
        获取历史成交

        :param inst_id: 交易对 ID
        :param limit: 返回数量上限（1-100）
        :return: 历史成交列表
        """
        return self._client.get("/api/v5/market/history-trades", params={"instId": inst_id, "limit": limit})

    def get_index_tickers(self, inst_id: Optional[str] = None) -> List[Dict]:
        """
        获取指数行情

        :param inst_id: 指数 ID（可选，如 'BTC-USDT'）
        :return: 指数行情列表
        """
        params = {}
        if inst_id:
            params["instId"] = inst_id
        return self._client.get("/api/v5/market/index-tickers", params=params if params else None)

    def get_funding_rate(self, inst_id: str) -> List[Dict]:
        """
        获取当前资金费率

        :param inst_id: 永续合约 ID，如 'BTC-USDT-SWAP'
        :return: 资金费率数据
        """
        return self._client.get("/api/v5/public/funding-rate", params={"instId": inst_id})

    def get_funding_rate_history(
        self, inst_id: str, limit: int = 100
    ) -> List[Dict]:
        """
        获取资金费率历史

        :param inst_id: 永续合约 ID
        :param limit: 返回数量
        :return: 资金费率历史列表
        """
        return self._client.get(
            "/api/v5/public/funding-rate-history",
            params={"instId": inst_id, "limit": limit},
        )

    def get_exchange_rate(self) -> List[Dict]:
        """
        获取汇率

        :return: 汇率数据
        """
        return self._client.get("/api/v5/market/exchange-rate")

    def get_platform_24_volume(self) -> List[Dict]:
        """
        获取平台 24 小时交易量

        :return: 交易量数据
        """
        return self._client.get("/api/v5/market/platform-24-volume")

    def get_price_limit(self, inst_id: str) -> List[Dict]:
        """
        获取限价

        :param inst_id: 交易对 ID
        :return: 限价数据
        """
        return self._client.get("/api/v5/public/price-limit", params={"instId": inst_id})

    def get_mark_price(self, inst_id: str) -> List[Dict]:
        """
        获取标记价格

        :param inst_id: 交易对 ID
        :return: 标记价格数据
        """
        return self._client.get("/api/v5/public/mark-price", params={"instId": inst_id})
