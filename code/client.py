# -*- coding: utf-8 -*-
"""
OKX API v5 统一客户端（高层入口）

OKXClient 聚合所有 API 子模块（market / trade / account 等）。
HTTPClient 已抽到独立模块 _http.py 以避免循环导入。

v1.2: 支持双模式（live / demo），通过 mode 参数或 OKX_TRADING_MODE 环境变量选择。
"""

from typing import Optional

from ._http import HTTPClient
from .market import MarketAPI
from .public import PublicAPI
from .trade import TradeAPI
from .account import AccountAPI
from .asset import AssetAPI
from .subaccount import SubAccountAPI

__all__ = ["OKXClient", "HTTPClient"]


class OKXClient:
    """
    OKX API v5 统一入口

    用法::

        from okx.code import OKXClient

        # 默认从环境变量 OKX_TRADING_MODE 选模式
        client = OKXClient()

        # 显式选模式（覆盖环境变量）
        client_live = OKXClient(mode="live")
        client_demo = OKXClient(mode="demo")

        ticker = client.market.get_ticker("BTC-USDT")
        balance = client.account.get_balance()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        passphrase: Optional[str] = None,
        flag: Optional[str] = None,
        mode: Optional[str] = None,
        timeout: int = 30,
    ):
        self._http = HTTPClient(
            api_key=api_key,
            secret_key=secret_key,
            passphrase=passphrase,
            flag=flag,
            mode=mode,
            timeout=timeout,
        )
        self.market = MarketAPI(self._http)
        self.public = PublicAPI(self._http)
        self.trade = TradeAPI(self._http)
        self.account = AccountAPI(self._http)
        self.asset = AssetAPI(self._http)
        self.subaccount = SubAccountAPI(self._http)

    @property
    def demo(self) -> bool:
        return self._http.flag == "1"

    @property
    def mode(self) -> str:
        """当前激活的 trading mode (live / demo)"""
        return self._http.mode

    @property
    def creds_provided(self) -> bool:
        return self._http.signer is not None

    @property
    def http(self) -> HTTPClient:
        """暴露底层 HTTP 客户端（高级场景）"""
        return self._http
