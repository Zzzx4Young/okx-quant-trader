# -*- coding: utf-8 -*-
"""
OKX API v5 资金模块（私有接口，需签名）
"""

from typing import Any, Dict, List, Optional

from ._http import HTTPClient


class AssetAPI:
    """资金 API"""

    def __init__(self, client: HTTPClient):
        self._client = client

    def get_balances(self, ccy: Optional[str] = None) -> List[Dict]:
        """
        获取资金余额

        :param ccy: 币种（可选）
        :return: 资金余额列表
        """
        params = {}
        if ccy:
            params["ccy"] = ccy
        return self._client.get(
            "/api/v5/asset/balances",
            signed=True,
            params=params if params else None,
        )

    def transfer(
        self,
        ccy: str,
        amt: str,
        from_: str,
        to: str,
        inst_id: Optional[str] = None,
        sub_acct: Optional[str] = None,
        to_sub_acct: Optional[str] = None,
        loan_trans_id: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> Dict:
        """
        资金划转

        :param ccy: 币种
        :param amt: 数量
        :param from_: 转出账户（6：统一账户 / 18：交易账户 / 19：金融账户）
        :param to: 转入账户（6：统一账户 / 18：交易账户 / 19：金融账户）
        :param inst_id: 交易对 ID（币币杠杆划转时需要，如 'BTC-USDT'）
        :param sub_acct: 子账户名称（子账户划转时需要）
        :param to_sub_acct: 目标子账户名称
        :param loan_trans_id: 借贷划转 ID（借贷划转时需要）
        :param client_id: 客户端划转 ID（用于去重）
        :return: 划转结果
        """
        data: Dict[str, str] = {
            "ccy": ccy,
            "amt": amt,
            "from": from_,
            "to": to,
        }
        if inst_id:
            data["instId"] = inst_id
        if sub_acct:
            data["subAcct"] = sub_acct
        if to_sub_acct:
            data["toSubAcct"] = to_sub_acct
        if loan_trans_id:
            data["loanTransId"] = loan_trans_id
        if client_id:
            data["clientId"] = client_id
        return self._client.post("/api/v5/asset/transfer", signed=True, data=data)

    def get_transfer_state(self, trans_id: str, ccy: Optional[str] = None) -> Dict:
        """
        查询划转状态

        :param trans_id: 划转 ID
        :param ccy: 币种
        :return: 划转状态
        """
        params: Dict[str, str] = {"transId": trans_id}
        if ccy:
            params["ccy"] = ccy
        return self._client.get("/api/v5/asset/transfer-state", signed=True, params=params)

    def get_deposit_address(self, ccy: str) -> List[Dict]:
        """
        获取充值地址

        :param ccy: 币种（如 'USDT'）
        :return: 充值地址列表（可能返回多个地址，如 TRC20/ERC20）
        """
        return self._client.get(
            "/api/v5/asset/deposit-address",
            signed=True,
            params={"ccy": ccy},
        )

    def get_deposit_history(
        self,
        ccy: Optional[str] = None,
        tx_id: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        充值记录

        :param ccy: 币种
        :param tx_id: 交易 ID
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 充值记录列表
        """
        params: Dict[str, Any] = {"limit": str(limit)}
        if ccy:
            params["ccy"] = ccy
        if tx_id:
            params["txId"] = tx_id
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/asset/deposit-history", signed=True, params=params)

    def withdrawal(
        self,
        ccy: str,
        amt: str,
        dst: str,
        to_address: str,
        chain: Optional[str] = None,
        fee: Optional[str] = None,
        addr: Optional[str] = None,
        pwd: Optional[str] = None,
    ) -> Dict:
        """
        提币

        :param ccy: 币种
        :param amt: 数量
        :param dst: 提币目标（3：内部转账 / 4：链上提币）
        :param to_address: 目标地址
        :param chain: 链名称（如 'USDT-TRC20'，'USDT-ERC20' 等）
        :param fee: 手续费（链上提币必填）
        :param addr: 标签（某些币种需要，如 XRP/XLM）
        :param pwd: 资金密码
        :return: 提币结果
        """
        data: Dict[str, str] = {
            "ccy": ccy,
            "amt": amt,
            "dst": dst,
            "toAddress": to_address,
        }
        if chain:
            data["chain"] = chain
        if fee:
            data["fee"] = fee
        if addr:
            data["addr"] = addr
        if pwd:
            data["pwd"] = pwd
        return self._client.post("/api/v5/asset/withdrawal", signed=True, data=data)

    def get_withdrawal_history(
        self,
        ccy: Optional[str] = None,
        tx_id: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        提币记录

        :param ccy: 币种
        :param tx_id: 交易 ID
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 提币记录列表
        """
        params: Dict[str, Any] = {"limit": str(limit)}
        if ccy:
            params["ccy"] = ccy
        if tx_id:
            params["txId"] = tx_id
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get(
            "/api/v5/asset/withdrawal-history",
            signed=True,
            params=params,
        )

    def get_currencies(self, ccy: Optional[str] = None) -> List[Dict]:
        """
        币种信息

        :param ccy: 币种（可选）
        :return: 币种信息列表
        """
        params = {}
        if ccy:
            params["ccy"] = ccy
        return self._client.get(
            "/api/v5/asset/currencies",
            signed=True,
            params=params if params else None,
        )

    def cancel_withdrawal(self, wd_id: str) -> Dict:
        """
        取消提币

        :param wd_id: 提币 ID
        :return: 取消结果
        """
        return self._client.post(
            "/api/v5/asset/cancel-withdrawal",
            signed=True,
            data={"wdId": wd_id},
        )

    def convert_dust_assets(self, ccies: List[str]) -> Dict:
        """
        dust 币兑换

        :param ccies: 币种列表（需要兑换的 dust 币种）
        :return: 兑换结果
        """
        return self._client.post(
            "/api/v5/asset/convert-dust-assets",
            signed=True,
            data={"ccys": ccies},
        )

    def get_asset_valuation(self, ccy: Optional[str] = None) -> Dict:
        """
        资产估值

        :param ccy: 币种（可选，不填则返回总估值）
        :return: 资产估值数据
        """
        params = {}
        if ccy:
            params["ccy"] = ccy
        return self._client.get(
            "/api/v5/asset/asset-valuation",
            signed=True,
            params=params if params else None,
        )
