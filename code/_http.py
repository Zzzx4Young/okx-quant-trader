# -*- coding: utf-8 -*-
"""
OKX API v5 底层 HTTP 客户端

独立模块，避免与 api/* 的循环导入。

- HTTPClient: 签名 + JSON + 重试 + 代理
- v1.2: 双模式（live / demo），按 OKX_TRADING_MODE 自动选对应凭据

凭据解析顺序（覆盖式）：
1. 显式参数 (api_key / secret_key / passphrase / mode)
2. OKX_TRADING_MODE 决定前缀：live → OKX_LIVE_* / demo → OKX_DEMO_*
3. 回退：OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE（视为 demo，旧版兼容）
"""

import os
import json
import requests
from typing import Any, Dict, Optional
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from .auth import Signer
from .utils import OKXError, check_response


class HTTPClient:
    """底层 HTTP 客户端：签名、JSON、重试、代理"""

    _VALID_MODES = ("live", "demo")

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        passphrase: Optional[str] = None,
        flag: Optional[str] = None,
        mode: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        proxy: Optional[Dict] = None,
    ):
        # ─── 1. 解析 mode ───
        # 显式参数 > env > 默认 demo
        env_mode = os.getenv("OKX_TRADING_MODE", "").strip().lower()
        if mode is None and env_mode in self._VALID_MODES:
            mode = env_mode
        elif mode is None:
            mode = "demo"

        if mode not in self._VALID_MODES:
            raise ValueError(
                f"Invalid trading mode: {mode!r}. Must be one of {self._VALID_MODES}"
            )

        self.mode = mode
        prefix = f"OKX_{mode.upper()}_"

        # ─── 2. 解析三件套凭据 ───
        # 优先级：显式参数 > OKX_<MODE>_* > OKX_API_*（向后兼容老 .env）
        legacy = (
            os.getenv("OKX_API_KEY"),
            os.getenv("OKX_API_SECRET"),
            os.getenv("OKX_PASSPHRASE"),
        )
        prefixed = (
            os.getenv(f"{prefix}API_KEY"),
            os.getenv(f"{prefix}API_SECRET"),
            os.getenv(f"{prefix}PASSPHRASE"),
        )

        # 显式参数 > prefixed > legacy（仅 demo 模式允许 legacy 回退）
        self.api_key = (
            api_key or prefixed[0] or (legacy[0] if mode == "demo" else None) or ""
        )
        self.secret_key = (
            secret_key or prefixed[1] or (legacy[1] if mode == "demo" else None) or ""
        )
        self.passphrase = (
            passphrase or prefixed[2] or (legacy[2] if mode == "demo" else None) or ""
        )

        # ─── 3. flag：0=实盘, 1=模拟（demo mode 始终用模拟 header）───
        env_flag = os.getenv("OKX_FLAG", "").strip()
        if flag is not None:
            self.flag = flag
        elif env_flag in ("0", "1"):
            self.flag = env_flag
        else:
            self.flag = "0" if mode == "live" else "1"

        self.base_url = "https://www.okx.com"
        self.timeout = timeout
        self.proxy = proxy or os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=retry_backoff,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "OPTIONS", "POST", "PUT", "DELETE"],
        )
        self.session = requests.Session()
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        if self.proxy:
            self.session.proxies = self.proxy

        if self.api_key and self.secret_key and self.passphrase:
            self.signer = Signer(self.api_key, self.secret_key, self.passphrase, self.flag)
        else:
            self.signer = None

    def _request(
        self,
        method: str,
        path: str,
        signed: bool = False,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
    ) -> Any:
        url = self.base_url + path
        req_headers = {"Content-Type": "application/json"}
        body = json.dumps(data) if data is not None else ""

        if signed:
            if not self.signer:
                raise OKXError(0, "API credentials not provided")
            if params:
                qs = "&".join(f"{k}={v}" for k, v in params.items())
                path_with_qs = path + ("?" + qs if qs else "")
            else:
                path_with_qs = path
            req_headers.update(self.signer.headers(method, path_with_qs, body))

        if headers:
            req_headers.update(headers)

        resp = self.session.request(
            method=method,
            url=url,
            params=params,
            data=body,
            headers=req_headers,
            timeout=self.timeout,
        )

        try:
            resp_json = resp.json()
        except Exception:
            raise OKXError(0, f"Invalid JSON response: {resp.text[:200]}")

        return check_response(resp_json)

    def get(self, path: str, signed: bool = False, params: Optional[Dict] = None) -> Any:
        return self._request("GET", path, signed=signed, params=params)

    def post(self, path: str, signed: bool = False, data: Optional[Dict] = None) -> Any:
        return self._request("POST", path, signed=signed, data=data)

    def delete(self, path: str, signed: bool = False, params: Optional[Dict] = None) -> Any:
        return self._request("DELETE", path, signed=signed, params=params)
