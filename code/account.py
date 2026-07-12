# -*- coding: utf-8 -*-
"""
OKX API v5 账户模块（私有接口，需签名）
"""

from typing import Any, Dict, List, Optional

from ._http import HTTPClient


class AccountAPI:
    """账户 API"""

    def __init__(self, client: HTTPClient):
        self._client = client

    def get_balance(self, ccy: Optional[str] = None) -> List[Dict]:
        """
        获取账户余额

        :param ccy: 币种（可选，如 'USDT'）
        :return: 账户余额数据
        """
        params = {}
        if ccy:
            params["ccy"] = ccy
        return self._client.get(
            "/api/v5/account/balance",
            signed=True,
            params=params if params else None,
        )

    def get_positions(self, inst_type: Optional[str] = None, inst_id: Optional[str] = None) -> List[Dict]:
        """
        获取持仓

        :param inst_type: 品种类型 SPOT/MARGIN/SWAP/FUTURES/OPTION
        :param inst_id: 交易对 ID
        :return: 持仓列表
        """
        params: Dict[str, str] = {}
        if inst_type:
            params["instType"] = inst_type
        if inst_id:
            params["instId"] = inst_id
        return self._client.get(
            "/api/v5/account/positions",
            signed=True,
            params=params if params else None,
        )

    def get_account_position_risk(self, inst_type: str = "SWAP") -> List[Dict]:
        """
        获取账户/持仓风险

        :param inst_type: 品种类型
        :return: 风险数据
        """
        return self._client.get(
            "/api/v5/account/account-position-risk",
            signed=True,
            params={"instType": inst_type},
        )

    def get_config(self) -> List[Dict]:
        """
        获取账户配置信息

        :return: 账户配置
        """
        return self._client.get("/api/v5/account/config", signed=True)

    def set_position_mode(self, pos_mode: str) -> Dict:
        """
        设置仓位模式

        :param pos_mode: long_short_mode（双向持仓）/ net_mode（单向持仓）
        :return: 设置结果
        """
        return self._client.post(
            "/api/v5/account/set-position-mode",
            signed=True,
            data={"posMode": pos_mode},
        )

    def set_leverage(
        self,
        lever: str,
        mgn_mode: str,
        inst_id: Optional[str] = None,
        pos_side: Optional[str] = None,
    ) -> Dict:
        """
        设置杠杆倍数

        :param lever: 杠杆倍数（如 '5', '10'）
        :param mgn_mode: 逐仓/全仓模式 cross/isolated
        :param inst_id: 交易对 ID（杠杆逐仓时必填，如 'BTC-USDT-SWAP'）
        :param pos_side: 持仓方向 long/short（双向持仓时必填）
        :return: 设置结果
        """
        data: Dict[str, str] = {
            "lever": lever,
            "mgnMode": mgn_mode,
        }
        if inst_id:
            data["instId"] = inst_id
        if pos_side:
            data["posSide"] = pos_side
        return self._client.post("/api/v5/account/set-leverage", signed=True, data=data)

    def get_leverage_info(self, inst_id: str, mgn_mode: str) -> List[Dict]:
        """
        查询杠杆信息

        :param inst_id: 交易对 ID
        :param mgn_mode: cross/isolated
        :return: 杠杆信息列表
        """
        return self._client.get(
            "/api/v5/account/leverage-info",
            signed=True,
            params={"instId": inst_id, "mgnMode": mgn_mode},
        )

    def adjust_margin_balance(
        self,
        inst_id: str,
        adj_type: str,
        amt: str,
        pos_side: Optional[str] = None,
    ) -> Dict:
        """
        增加/减少保证金

        :param inst_id: 交易对 ID
        :param adj_type: add（增加）/ reduce（减少）
        :param amt: 保证金数量
        :param pos_side: long/short（双向持仓时必填）
        :return: 调整结果
        """
        data: Dict[str, str] = {
            "instId": inst_id,
            "adjType": adj_type,
            "amt": amt,
        }
        if pos_side:
            data["posSide"] = pos_side
        return self._client.post(
            "/api/v5/account/position/margin-balance",
            signed=True,
            data=data,
        )

    def get_interest_accrued(
        self,
        inst_id: Optional[str] = None,
        ccy: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        利息应计

        :param inst_id: 交易对 ID
        :param ccy: 币种
        :param limit: 返回数量
        :return: 利息应计列表
        """
        params: Dict[str, Any] = {"limit": str(limit)}
        if inst_id:
            params["instId"] = inst_id
        if ccy:
            params["ccy"] = ccy
        return self._client.get("/api/v5/account/interest-accrued", signed=True, params=params)

    def get_interest_rate(self, ccy: Optional[str] = None) -> List[Dict]:
        """
        利率查询

        :param ccy: 币种
        :return: 利率列表
        """
        params = {}
        if ccy:
            params["ccy"] = ccy
        return self._client.get(
            "/api/v5/account/interest-rate",
            signed=True,
            params=params if params else None,
        )

    def get_trade_fee(self, inst_id: Optional[str] = None, inst_type: Optional[str] = None) -> List[Dict]:
        """
        手续费率

        :param inst_id: 交易对 ID
        :param inst_type: 品种类型
        :return: 手续费率数据
        """
        params: Dict[str, str] = {}
        if inst_id:
            params["instId"] = inst_id
        if inst_type:
            params["instType"] = inst_type
        return self._client.get(
            "/api/v5/account/trade-fee",
            signed=True,
            params=params if params else None,
        )

    def get_max_withdrawal(self, ccy: Optional[str] = None) -> List[Dict]:
        """
        最大可提金额

        :param ccy: 币种
        :return: 最大可提数据
        """
        params = {}
        if ccy:
            params["ccy"] = ccy
        return self._client.get(
            "/api/v5/account/max-withdrawal",
            signed=True,
            params=params if params else None,
        )

    def get_bills(
        self,
        inst_type: Optional[str] = None,
        ccy: Optional[str] = None,
        mgn_mode: Optional[str] = None,
        ct_type: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        账单流水（近7天）

        :param inst_type: 品种类型
        :param ccy: 币种
        :param mgn_mode: 仓位模式 cross/isolated
        :param ct_type: 合约类型 linear（币本位）/ inverse（币币）
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 账单流水列表
        """
        params: Dict[str, Any] = {"limit": str(limit)}
        if inst_type:
            params["instType"] = inst_type
        if ccy:
            params["ccy"] = ccy
        if mgn_mode:
            params["mgnMode"] = mgn_mode
        if ct_type:
            params["ctType"] = ct_type
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/account/bills", signed=True, params=params)

    def get_bills_archive(
        self,
        inst_type: Optional[str] = None,
        ccy: Optional[str] = None,
        mgn_mode: Optional[str] = None,
        ct_type: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        账单流水（近3月）

        :param inst_type: 品种类型
        :param ccy: 币种
        :param mgn_mode: 仓位模式
        :param ct_type: 合约类型
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 账单流水列表
        """
        params: Dict[str, Any] = {"limit": str(limit)}
        if inst_type:
            params["instType"] = inst_type
        if ccy:
            params["ccy"] = ccy
        if mgn_mode:
            params["mgnMode"] = mgn_mode
        if ct_type:
            params["ctType"] = ct_type
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/account/bills-archive", signed=True, params=params)

    def get_positions_history(
        self,
        inst_id: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        持仓历史

        :param inst_id: 交易对 ID
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 持仓历史列表
        """
        params: Dict[str, Any] = {"limit": str(limit)}
        if inst_id:
            params["instId"] = inst_id
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/account/positions-history", signed=True, params=params)

    def get_greeks(self, ccy: Optional[str] = None) -> List[Dict]:
        """
        Greeks 信息（期权）

        :param ccy: 币种（如 'BTC'）
        :return: Greeks 数据
        """
        params = {}
        if ccy:
            params["ccy"] = ccy
        return self._client.get(
            "/api/v5/account/greeks",
            signed=True,
            params=params if params else None,
        )

    def set_greeks(self, greeks_type: str = "PAXS") -> Dict:
        """
        设置 Greeks 展示模式

        :param greeks_type: PAXS（法币）/ COIN（币种）/ BATCH（币种展示多个）
        :return: 设置结果
        """
        return self._client.post(
            "/api/v5/account/set-greeks",
            signed=True,
            data={"greeksType": greeks_type},
        )
