# -*- coding: utf-8 -*-
"""
OKX API v5 通用工具函数
"""

import time
from typing import Any, Dict, Optional, List


class OKXError(Exception):
    """OKX API 业务错误"""

    def __init__(self, code: int, msg: str, data: Any = None):
        self.code = code
        self.msg = msg
        self.data = data
        super().__init__(f"[{code}] {msg}")

    @classmethod
    def from_response(cls, resp: Dict) -> Optional["OKXError"]:
        """从 API 响应中解析错误

        OKX 下单/取消等接口的错误响应同时包含两层错误码：
        - 顶层 code="1"、msg="All operations failed"（HTTP 层错误指示）
        - data[].sCode="51008"（业务层具体错误码，sMsg 是详细原因）

        其他公开接口（ticker、balance 等）data 里没有 sCode，顶级 code 足矣。

        优先级：data[].sCode 更具体，优先使用。即使顶层 code 是 "0"或非 "0"，
        只要 data 里任一项 sCode != "0"，就返回该 sCode 错误。
        """
        top_msg = resp.get("msg", "")
        data = resp.get("data")

        # 1. 优先检查业务层错误（更具体）
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                sub_code = str(item.get("sCode", "0"))
                if sub_code != "0":
                    return cls(
                        code=int(sub_code),
                        msg=item.get("sMsg") or top_msg or "Business error",
                        data=item,
                    )

        # 2. 顶层 code 错误（HTTP/认证/参数错误等）
        if str(resp.get("code", "0")) != "0":
            return cls(
                code=int(resp.get("code", 0)),
                msg=top_msg or "Unknown error",
                data=data,
            )
        return None


def check_response(resp: Dict) -> Any:
    """
    检查 API 响应是否成功，失败则抛出 OKXError

    :param resp: API 响应字典
    :return: data 字段内容
    """
    err = OKXError.from_response(resp)
    if err:
        raise err
    return resp.get("data", resp)


def inst_type_to_str(inst_type: str) -> str:
    """规范化品种类型"""
    mapping = {
        "SPOT": "SPOT",
        "MARGIN": "MARGIN",
        "SWAP": "SWAP",
        "FUTURES": "FUTURES",
        "OPTION": "OPTION",
        "spot": "SPOT",
        "margin": "MARGIN",
        "swap": "SWAP",
        "futures": "FUTURES",
        "option": "OPTION",
    }
    return mapping.get(inst_type.upper(), inst_type.upper())


def pos_side_to_str(pos_side: str) -> str:
    """规范化持仓方向"""
    mapping = {"long": "long", "short": "short", "net": "net"}
    return mapping.get(pos_side.lower(), pos_side.lower())


def side_to_str(side: str) -> str:
    """规范化交易方向

    接受以下输入：
    - buy / sell：原样返回
    - long / short：翻译为 buy / sell（做多=买入，做空=卖出）

    这样上层可以传入 Signal.direction（long/short）而不必手动转换。
    """
    mapping = {
        "buy": "buy", "sell": "sell",
        "long": "buy", "short": "sell",  # 方向 → 交易动作
    }
    return mapping.get(side.lower(), side.lower())


def ord_type_to_str(ord_type: str) -> str:
    """规范化订单类型"""
    mapping = {
        "market": "market",
        "limit": "limit",
        "post_only": "post_only",
        "fok": "fok",
        "ioc": "ioc",
        "optimal_limit_ioc": "optimal_limit_ioc",
        "stop_market": "stop_market",
        "stop_limit": "stop_limit",
        "take_profit": "take_profit",
        "move_order_stop": "move_order_stop",
    }
    return mapping.get(ord_type.lower(), ord_type.lower())


def td_mode_to_str(td_mode: str) -> str:
    """规范化交易模式"""
    mapping = {"cross": "cross", "isolated": "isolated", "cash": "cash"}
    return mapping.get(td_mode.lower(), td_mode.lower())


def now_timestamp_ms() -> int:
    """当前毫秒时间戳"""
    return int(time.time() * 1000)
