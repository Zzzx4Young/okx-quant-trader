# -*- coding: utf-8 -*-
"""
OKX API v5 交易模块（私有接口，需签名）
"""

from typing import Any, Dict, List, Optional

from ._http import HTTPClient
from .utils import ord_type_to_str, side_to_str, td_mode_to_str, pos_side_to_str


class TradeAPI:
    """交易 API"""

    def __init__(self, client: HTTPClient):
        self._client = client

    # ---- 下单 ----

    def place_order(
        self,
        inst_id: str,
        side: str,
        ord_type: str,
        sz: str,
        td_mode: str,
        px: Optional[str] = None,
        pos_side: Optional[str] = None,
        reduce_only: bool = False,
        cl_ord_id: Optional[str] = None,
        sl_trigger_px: Optional[str] = None,
        sl_ord_px: Optional[str] = None,
        tp_trigger_px: Optional[str] = None,
        tp_ord_px: Optional[str] = None,
        tgt_ccy: Optional[str] = None,
        sz_ccy: Optional[str] = None,
        callback_px: Optional[str] = None,
        callback_ratio: Optional[str] = None,
        tp_trigger_px_type: Optional[str] = None,
        sl_trigger_px_type: Optional[str] = None,
        attached_ord_pxs: Optional[Dict] = None,
        trigger_px: Optional[str] = None,
        ord_px: Optional[str] = None,
        order_regex: Optional[str] = None,
        quick_mgn_type: Optional[int] = None,
    ) -> Dict:
        """
        下单

        :param inst_id: 交易对 ID，如 'BTC-USDT'
        :param side: buy/sell
        :param ord_type: market/limit/post_only/fok/ioc/stop_market/stop_limit/take_profit/move_order_stop
        :param sz: 数量（字符串格式）
        :param td_mode: cross/isolated/cash
        :param px: 价格（限价单必填，市价单可不传）
        :param pos_side: long/short/net（双向合约持仓方向）
        :param reduce_only: 是否只减仓
        :param cl_ord_id: 客户端订单 ID（可自定义，用于去重）
        :param sl_trigger_px: 止损触发价格
        :param sl_ord_px: 止损订单价格
        :param tp_trigger_px: 止盈触发价格
        :param tp_ord_px: 止盈订单价格
        :param tgt_ccy: 数量单位（btc_usd/btc_ccy）
        :param sz_ccy: 数量币种（某些币对支持）
        :return: 订单结果
        """
        data: Dict[str, Any] = {
            "instId": inst_id,
            "side": side_to_str(side),
            "ordType": ord_type_to_str(ord_type),
            "sz": sz,
            "tdMode": td_mode_to_str(td_mode),
        }

        if px is not None:
            data["px"] = px
        if pos_side:
            data["posSide"] = pos_side_to_str(pos_side)
        if reduce_only:
            data["reduceOnly"] = "true"
        if cl_ord_id:
            data["clOrdId"] = cl_ord_id
        if tgt_ccy:
            data["tgtCcy"] = tgt_ccy
        if sz_ccy:
            data["szCcy"] = sz_ccy
        if callback_px:
            data["callbackPx"] = callback_px
        if callback_ratio:
            data["callbackRatio"] = callback_ratio
        if attached_ord_pxs:
            data["attachedOrdPxS"] = attached_ord_pxs
        if trigger_px:
            data["triggerPx"] = trigger_px
        if ord_px:
            data["ordPx"] = ord_px
        if order_regex:
            data["orderRegex"] = order_regex
        if quick_mgn_type is not None:
            data["quickMgnType"] = str(quick_mgn_type)

        # 止损/止盈在 OKX v5 改版后必须通过 attachAlgoOrds 数组传递
        # 旧字段 slTriggerPx/tpTriggerPx 已废弃（OKX 返回 54070）
        if sl_trigger_px or sl_ord_px or tp_trigger_px or tp_ord_px:
            algo_ord: Dict[str, Any] = {}
            if sl_trigger_px:
                algo_ord["slTriggerPx"] = sl_trigger_px
            if sl_ord_px:
                algo_ord["slOrdPx"] = sl_ord_px
            if tp_trigger_px:
                algo_ord["tpTriggerPx"] = tp_trigger_px
            if tp_ord_px:
                algo_ord["tpOrdPx"] = tp_ord_px
            data["attachAlgoOrds"] = [algo_ord]

        return self._client.post("/api/v5/trade/order", signed=True, data=data)

    def batch_place_orders(self, orders: List[Dict]) -> List[Dict]:
        """
        批量下单

        :param orders: 订单列表，每项为 place_order 的参数子集
        :return: 批量订单结果列表
        """
        data = [{"instId": o["inst_id"], "side": side_to_str(o["side"]), "ordType": ord_type_to_str(o["ord_type"]), "sz": o["sz"], "tdMode": td_mode_to_str(o["td_mode"])} for o in orders]
        for i, o in enumerate(orders):
            if "px" in o:
                data[i]["px"] = o["px"]
            if "cl_ord_id" in o:
                data[i]["clOrdId"] = o["cl_ord_id"]
        return self._client.post("/api/v5/trade/batch-orders", signed=True, data=data)

    # ---- 取消订单 ----

    def cancel_order(self, inst_id: str, ord_id: str, cl_ord_id: Optional[str] = None) -> Dict:
        """
        取消订单

        :param inst_id: 交易对 ID
        :param ord_id: 订单 ID（OKX 订单 ID，与 cl_ord_id 二选一）
        :param cl_ord_id: 客户端订单 ID（可自定义）
        :return: 取消结果
        """
        data: Dict[str, str] = {"instId": inst_id, "ordId": ord_id}
        if cl_ord_id:
            data["clOrdId"] = cl_ord_id
        return self._client.post("/api/v5/trade/cancel-order", signed=True, data=data)

    def cancel_batch_orders(self, orders: List[Dict]) -> List[Dict]:
        """
        批量取消订单

        :param orders: 取消订单列表，每项包含 instId 和 ordId（或 clOrdId）
        :return: 批量取消结果列表
        """
        data = []
        for o in orders:
            item: Dict[str, str] = {"instId": o["inst_id"]}
            if "ord_id" in o:
                item["ordId"] = o["ord_id"]
            if "cl_ord_id" in o:
                item["clOrdId"] = o["cl_ord_id"]
            data.append(item)
        return self._client.post("/api/v5/trade/cancel-batch-orders", signed=True, data=data)

    # ---- 修改订单 ----

    def amend_order(
        self,
        inst_id: str,
        ord_id: Optional[str] = None,
        cl_ord_id: Optional[str] = None,
        px: Optional[str] = None,
        new_sz: Optional[str] = None,
        req_id: Optional[str] = None,
    ) -> Dict:
        """
        修改订单

        :param inst_id: 交易对 ID
        :param ord_id: 订单 ID
        :param cl_ord_id: 客户端订单 ID
        :param px: 新价格
        :param new_sz: 新数量
        :param req_id: 请求 ID（用于去重）
        :return: 修改结果
        """
        data: Dict[str, str] = {"instId": inst_id}
        if ord_id:
            data["ordId"] = ord_id
        if cl_ord_id:
            data["clOrdId"] = cl_ord_id
        if px:
            data["newPx"] = px
        if new_sz:
            data["newSz"] = new_sz
        if req_id:
            data["reqId"] = req_id
        return self._client.post("/api/v5/trade/amend-order", signed=True, data=data)

    def amend_batch_orders(self, orders: List[Dict]) -> List[Dict]:
        """
        批量修改订单

        :param orders: 修改订单列表
        :return: 批量修改结果
        """
        data = []
        for o in orders:
            item: Dict[str, str] = {"instId": o["inst_id"]}
            if "ord_id" in o:
                item["ordId"] = o["ord_id"]
            if "cl_ord_id" in o:
                item["clOrdId"] = o["cl_ord_id"]
            if "px" in o:
                item["newPx"] = o["px"]
            if "new_sz" in o:
                item["newSz"] = o["new_sz"]
            data.append(item)
        return self._client.post("/api/v5/trade/amend-batch-orders", signed=True, data=data)

    # ---- 查询订单 ----

    def get_order(self, inst_id: str, ord_id: Optional[str] = None, cl_ord_id: Optional[str] = None) -> Dict:
        """
        查询订单详情

        :param inst_id: 交易对 ID
        :param ord_id: 订单 ID（与 cl_ord_id 二选一）
        :param cl_ord_id: 客户端订单 ID
        :return: 订单详情
        """
        params: Dict[str, str] = {"instId": inst_id}
        if ord_id:
            params["ordId"] = ord_id
        if cl_ord_id:
            params["clOrdId"] = cl_ord_id
        return self._client.get("/api/v5/trade/order", signed=True, params=params)

    def get_orders_pending(
        self, inst_id: Optional[str] = None, ord_type: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        """
        查询未成交订单

        :param inst_id: 交易对 ID（可选）
        :param ord_type: 订单类型（可选）
        :param limit: 返回数量
        :return: 未成交订单列表
        """
        params: Dict[str, Any] = {"limit": limit}
        if inst_id:
            params["instId"] = inst_id
        if ord_type:
            params["ordType"] = ord_type
        return self._client.get("/api/v5/trade/orders-pending", signed=True, params=params)

    def get_orders_history(
        self,
        inst_type: str = "SPOT",
        inst_id: Optional[str] = None,
        ord_type: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        查询历史订单（近7天）

        :param inst_type: 品种类型
        :param inst_id: 交易对 ID
        :param ord_type: 订单类型
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 历史订单列表
        """
        params: Dict[str, Any] = {"instType": inst_type, "limit": limit}
        if inst_id:
            params["instId"] = inst_id
        if ord_type:
            params["ordType"] = ord_type
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/trade/orders-history", signed=True, params=params)

    def get_orders_history_archive(
        self,
        inst_type: str = "SPOT",
        inst_id: Optional[str] = None,
        ord_type: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        查询历史订单（近3月）

        :param inst_type: 品种类型
        :param inst_id: 交易对 ID
        :param ord_type: 订单类型
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 历史订单列表
        """
        params: Dict[str, Any] = {"instType": inst_type, "limit": limit}
        if inst_id:
            params["instId"] = inst_id
        if ord_type:
            params["ordType"] = ord_type
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/trade/orders-history-archive", signed=True, params=params)

    # ---- 成交 ----

    def get_fills(
        self,
        inst_id: Optional[str] = None,
        ord_id: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        查询成交明细（近7天）

        :param inst_id: 交易对 ID
        :param ord_id: 订单 ID
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 成交明细列表
        """
        params: Dict[str, Any] = {"limit": limit}
        if inst_id:
            params["instId"] = inst_id
        if ord_id:
            params["ordId"] = ord_id
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/trade/fills", signed=True, params=params)

    def get_fills_history(
        self,
        inst_type: str = "SPOT",
        inst_id: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
    ) -> List[Dict]:
        """
        查询历史成交（近3月）

        :param inst_type: 品种类型
        :param inst_id: 交易对 ID
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :return: 历史成交列表
        """
        params: Dict[str, Any] = {"instType": inst_type, "limit": limit}
        if inst_id:
            params["instId"] = inst_id
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return self._client.get("/api/v5/trade/fills-history", signed=True, params=params)

    # ---- 平仓 ----

    def close_position(
        self,
        inst_id: str,
        pos_side: Optional[str] = None,
        mgn_mode: Optional[str] = None,
    ) -> Dict:
        """
        平仓

        :param inst_id: 交易对 ID
        :param pos_side: long/short/net
        :param mgn_mode: isolated/cross
        :return: 平仓结果
        """
        data: Dict[str, str] = {"instId": inst_id}
        if pos_side:
            data["posSide"] = pos_side_to_str(pos_side)
        if mgn_mode:
            data["mgnMode"] = mgn_mode
        return self._client.post("/api/v5/trade/close-position", signed=True, data=data)

    # ---- 算法单 ----

    def place_algo_order(
        self,
        inst_id: str,
        side: str,
        ord_type: str,
        sz: str,
        td_mode: str,
        algo_type: str,
        px: Optional[str] = None,
        pos_side: Optional[str] = None,
        reduce_only: bool = False,
        sl_trigger_px: Optional[str] = None,
        sl_ord_px: Optional[str] = None,
        tp_trigger_px: Optional[str] = None,
        tp_ord_px: Optional[str] = None,
        trigger_px: Optional[str] = None,
        trigger_px_type: Optional[str] = None,
    ) -> Dict:
        """
        下算法单（止损/止盈/冰山/TWAP等）

        :param inst_id: 交易对 ID
        :param side: buy/sell
        :param ord_type: 算法单类型，如 'conditional'（条件单）/ 'iceberg'（冰山）/ 'twap'（时间加权）
        :param sz: 数量
        :param td_mode: cross/isolated/cash
        :param algo_type: 算法类型
        :param px: 价格（条件单价格）
        :param pos_side: long/short/net
        :param reduce_only: 是否只减仓
        :param sl_trigger_px: 止损触发价格
        :param sl_ord_px: 止损订单价格
        :param tp_trigger_px: 止盈触发价格
        :param tp_ord_px: 止盈订单价格
        :param trigger_px: 触发价格
        :param trigger_px_type: 触发价格类型
        :return: 算法单结果
        """
        data: Dict[str, Any] = {
            "instId": inst_id,
            "side": side_to_str(side),
            "ordType": algo_type,
            "sz": sz,
            "tdMode": td_mode_to_str(td_mode),
        }
        if px:
            data["px"] = px
        if pos_side:
            data["posSide"] = pos_side_to_str(pos_side)
        if reduce_only:
            data["reduceOnly"] = "true"
        if sl_trigger_px:
            data["slTriggerPx"] = sl_trigger_px
        if sl_ord_px:
            data["slOrdPx"] = sl_ord_px
        if tp_trigger_px:
            data["tpTriggerPx"] = tp_trigger_px
        if tp_ord_px:
            data["tpOrdPx"] = tp_ord_px
        if trigger_px:
            data["triggerPx"] = trigger_px
        if trigger_px_type:
            data["triggerPxType"] = trigger_px_type
        return self._client.post("/api/v5/trade/order-algo", signed=True, data=data)

    def cancel_algos(self, algos: List[Dict]) -> List[Dict]:
        """
        取消算法单

        :param algos: 算法单列表，每项包含 instId 和 algoId
        :return: 取消结果列表
        """
        data = [{"instId": a["inst_id"], "algoId": a["algo_id"], "algoClOrdId": a.get("algo_cl_ord_id", "")} for a in algos]
        return self._client.post("/api/v5/trade/cancel-algos", signed=True, data=data)

    def get_orders_algo_pending(
        self,
        inst_id: Optional[str] = None,
        algoid: Optional[str] = None,
        ord_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        查询未触发算法单

        :param inst_id: 交易对 ID
        :param algoid: 算法单 ID
        :param ord_type: 算法单类型
        :param limit: 返回数量
        :return: 算法单列表
        """
        params: Dict[str, Any] = {"limit": limit}
        if inst_id:
            params["instId"] = inst_id
        if algoid:
            params["algoId"] = algoid
        if ord_type:
            params["ordType"] = ord_type
        return self._client.get("/api/v5/trade/orders-algo-pending", signed=True, params=params)

    def get_orders_algo_history(
        self,
        inst_id: Optional[str] = None,
        ord_type: Optional[str] = None,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
        state: Optional[str] = None,
    ) -> List[Dict]:
        """
        查询算法单历史

        :param inst_id: 交易对 ID
        :param ord_type: 算法单类型
        :param limit: 返回数量
        :param after: 起始光标
        :param before: 结束光标
        :param state: 状态（effective/depracted/canceled）
        :return: 算法单历史列表
        """
        params: Dict[str, Any] = {"limit": limit}
        if inst_id:
            params["instId"] = inst_id
        if ord_type:
            params["ordType"] = ord_type
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        if state:
            params["state"] = state
        return self._client.get("/api/v5/trade/orders-algo-history", signed=True, params=params)
