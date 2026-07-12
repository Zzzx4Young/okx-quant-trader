# -*- coding: utf-8 -*-
"""
OKX API v5 公开数据模块（公开接口，无需签名）
"""

from typing import Any, Dict, List, Optional

from ._http import HTTPClient


class PublicAPI:
    """公开数据 API"""

    def __init__(self, client: HTTPClient):
        self._client = client

    def get_instruments(
        self,
        inst_type: str,
        uly: Optional[str] = None,
        inst_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        获取交易对/合约信息

        :param inst_type: 品种类型 SPOT/MARGIN/SWAP/FUTURES/OPTION
        :param uly: 标的资产（期权/期货/永续需要，如 'BTC-USDT'）
        :param inst_id: 交易对 ID（可选，精确匹配）
        :return: 交易对/合约信息列表
        """
        params: Dict[str, str] = {"instType": inst_type}
        if uly:
            params["uly"] = uly
        if inst_id:
            params["instId"] = inst_id
        return self._client.get("/api/v5/public/instruments", params=params)

    def get_delivery_exercise_history(
        self,
        inst_type: str,
        uly: Optional[str] = None,
        after: Optional[str] = None,
        before: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        交割/行权历史

        :param inst_type: FUTURES/OPTION
        :param uly: 标的资产
        :param after: 起始光标
        :param before: 结束光标
        :param limit: 返回数量
        :return: 交割/行权历史列表
        """
        params: Dict[str, Any] = {"instType": inst_type, "limit": str(limit)}
        if uly:
            params["uly"] = uly
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/public/delivery-exercise-history", params=params)

    def get_open_interest(self, inst_type: str, uly: Optional[str] = None) -> List[Dict]:
        """
        未平仓量

        :param inst_type: SWAP/FUTURES/OPTION
        :param uly: 标的资产
        :return: 未平仓量列表
        """
        params: Dict[str, str] = {"instType": inst_type}
        if uly:
            params["uly"] = uly
        return self._client.get("/api/v5/public/open-interest", params=params)

    def get_estimated_price(self, inst_id: str) -> List[Dict]:
        """
        预计交割价格

        :param inst_id: 合约 ID
        :return: 预计交割价格
        """
        return self._client.get("/api/v5/public/estimated-price", params={"instId": inst_id})

    def get_opt_summary(self, uly: str) -> List[Dict]:
        """
        期权 Greeks/IV 摘要

        :param uly: 标的资产（如 'BTC-USDT'）
        :return: 期权摘要列表
        """
        return self._client.get("/api/v5/public/opt-summary", params={"uly": uly})

    def get_underlying(self, inst_type: str) -> List[Dict]:
        """
        标的资产列表

        :param inst_type: MARGIN/SWAP/FUTURES/OPTION
        :return: 标的资产列表
        """
        return self._client.get("/api/v5/public/underlying", params={"instType": inst_type})

    def get_insurance_fund(
        self,
        inst_type: Optional[str] = None,
        uly: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        保险基金

        :param inst_type: 品种类型
        :param uly: 标的资产
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 保险基金列表
        """
        params: Dict[str, Any] = {"limit": str(limit)}
        if inst_type:
            params["instType"] = inst_type
        if uly:
            params["uly"] = uly
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/public/insurance-fund", params=params)

    def get_liquidation_orders(
        self,
        inst_type: Optional[str] = None,
        uly: Optional[str] = None,
        alias: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        强平订单

        :param inst_type: 品种类型
        :param uly: 标的资产
        :param alias: 合约到期日（如 'this_week' 'next_week' 'quarter'）
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 强平订单列表
        """
        params: Dict[str, Any] = {"limit": str(limit)}
        if inst_type:
            params["instType"] = inst_type
        if uly:
            params["uly"] = uly
        if alias:
            params["alias"] = alias
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/public/liquidation-orders", params=params)

    def get_position_tiers(
        self,
        inst_type: str,
        uly: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> List[Dict]:
        """
        仓位档位

        :param inst_type: MARGIN/SWAP/FUTURES
        :param uly: 标的资产
        :param tier: 档位
        :return: 仓位档位列表
        """
        params: Dict[str, str] = {"instType": inst_type}
        if uly:
            params["uly"] = uly
        if tier:
            params["tier"] = tier
        return self._client.get("/api/v5/public/position-tiers", params=params)

    def get_index_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[List]:
        """
        指数 K 线

        :param inst_id: 指数 ID
        :param bar: K 线周期
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: K 线数据列表
        """
        params: Dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": limit}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/market/index-candles", params=params)

    def get_mark_price_candles(
        self,
        inst_id: str,
        bar: str = "1m",
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[List]:
        """
        标记价格 K 线

        :param inst_id: 交易对 ID
        :param bar: K 线周期
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: K 线数据列表
        """
        params: Dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": limit}
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/market/mark-price-candles", params=params)

    def get_system_time(self) -> List[Dict]:
        """
        获取系统时间

        :return: 服务器时间
        """
        return self._client.get("/api/v5/public/time")
