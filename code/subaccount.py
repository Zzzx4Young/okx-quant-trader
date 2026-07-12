# -*- coding: utf-8 -*-
"""
OKX API v5 子账户模块（私有接口，需签名）
"""

from typing import Any, Dict, List, Optional

from ._http import HTTPClient


class SubAccountAPI:
    """子账户 API"""

    def __init__(self, client: HTTPClient):
        self._client = client

    def get_subaccount_balances(self, sub_acct: str, ccy: Optional[str] = None) -> List[Dict]:
        """
        子账户余额

        :param sub_acct: 子账户名称
        :param ccy: 币种（可选）
        :return: 子账户余额列表
        """
        params: Dict[str, str] = {"subAcct": sub_acct}
        if ccy:
            params["ccy"] = ccy
        return self._client.get(
            "/api/v5/account/subaccount/balances",
            signed=True,
            params=params,
        )

    def get_subaccount_asset_balances(
        self,
        sub_acct: str,
        ccy: Optional[str] = None,
    ) -> List[Dict]:
        """
        子账户资产

        :param sub_acct: 子账户名称
        :param ccy: 币种（可选）
        :return: 子账户资产列表
        """
        params: Dict[str, str] = {"subAcct": sub_acct}
        if ccy:
            params["ccy"] = ccy
        return self._client.get(
            "/api/v5/asset/subaccount/balances",
            signed=True,
            params=params,
        )

    def subaccount_transfer(
        self,
        ccy: str,
        amt: str,
        from_sub: str,
        to_sub: str,
        from_: str = "6",
        to: str = "6",
    ) -> Dict:
        """
        子账户间划转

        :param ccy: 币种
        :param amt: 数量
        :param from_sub: 转出子账户名称
        :param to_sub: 转入子账户名称
        :param from_: 转出账户（6：统一账户）
        :param to: 转入账户（6：统一账户）
        :return: 划转结果
        """
        data: Dict[str, str] = {
            "ccy": ccy,
            "amt": amt,
            "fromSubAcct": from_sub,
            "toSubAcct": to_sub,
            "from": from_,
            "to": to,
        }
        return self._client.post("/api/v5/asset/subaccount/transfer", signed=True, data=data)

    def get_subaccount_list(self, enable: Optional[bool] = None, limit: int = 100) -> List[Dict]:
        """
        子账户列表

        :param enable: 启用状态（True/False）
        :param limit: 返回数量
        :return: 子账户列表
        """
        params: Dict[str, Any] = {"limit": str(limit)}
        if enable is not None:
            params["enable"] = "true" if enable else "false"
        return self._client.get("/api/v5/users/subaccount/list", signed=True, params=params)

    def modify_subaccount_apikey(
        self,
        sub_acct: str,
        apikey: str,
        perm: Optional[str] = None,
        ip_list: Optional[List[str]] = None,
    ) -> Dict:
        """
        修改子账户 API Key

        :param sub_acct: 子账户名称
        :param apikey: API Key
        :param perm: 权限（readOnly/trade/withdraw）
        :param ip_list: IP 白名单
        :return: 修改结果
        """
        data: Dict[str, Any] = {"subAcct": sub_acct, "apiKey": apikey}
        if perm:
            data["perm"] = perm
        if ip_list:
            data["ipList"] = ip_list
        return self._client.post(
            "/api/v5/users/subaccount/modify-apikey",
            signed=True,
            data=data,
        )
