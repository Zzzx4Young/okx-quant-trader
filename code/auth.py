# -*- coding: utf-8 -*-
"""
OKX API v5 签名认证核心
"""

import hmac
import hashlib
import base64
import datetime
from typing import Dict


class Signer:
    """签名生成器"""

    def __init__(self, api_key: str, secret_key: str, passphrase: str, flag: str = "1"):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        # flag: '0' 实盘, '1' 模拟盘
        self.flag = flag
        self.base_url = "https://www.okx.com"

    def _get_timestamp(self) -> str:
        """获取当前 UTC 时间戳（OKX 要求 ISO 8601 毫秒精度：YYYY-MM-DDTHH:mm:ss.SSSZ）

        Python 的 %f 是微秒（6 位），需要截断到毫秒（3 位）。
        """
        now = datetime.datetime.utcnow()
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    def sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """
        生成 OKX v5 API 签名（base64(HMAC-SHA256(secret, prehash))）

        prehash = timestamp + method + requestPath + body

        OKX 官方示例：
            mac = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), sha256).digest()
            signature = base64.b64encode(mac).decode()

        :param timestamp: 请求时间戳 (UTC, ISO 8601 ms 精度)
        :param method: HTTP 方法 (GET/POST)
        :param path: 请求路径（含 query string, 如 /api/v5/account/balance?ccy=USDT）
        :param body: 请求体 (JSON 字符串，GET 时为空)
        :return: 签名字符串 (base64)
        """
        message = timestamp + method + path + body
        mac = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(mac).decode("utf-8")

    def headers(
        self, method: str, path: str, body: str = "", additional_headers: Dict[str, str] = None
    ) -> Dict[str, str]:
        """
        生成认证所需的 HTTP Headers

        :param method: GET/POST
        :param path: API 路径
        :param body: 请求体 (空字符串表示无 body)
        :param additional_headers: 额外追加的 header
        :return: 完整的 HTTP Header 字典
        """
        timestamp = self._get_timestamp()
        signature = self.sign(timestamp, method, path, body)

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

        # 模拟盘模式需要额外传 x-simulated-trading: 1 header
        # OKX V5 官方约定：不传则走实盘账户（即使 OKX_FLAG=1 也不够）
        if self.flag == "1":
            headers["x-simulated-trading"] = "1"

        if additional_headers:
            headers.update(additional_headers)

        return headers

    def demo_mode(self) -> bool:
        """是否模拟盘"""
        return self.flag == "1"
