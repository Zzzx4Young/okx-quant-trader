# -*- coding: utf-8 -*-
"""
utils 模块单元测试

覆盖：
- OKXError.from_response（顶层 code + data[].sCode 两层错误检查）
"""

import pytest

from okx.code.utils import OKXError, check_response, side_to_str, pos_side_to_str


class TestOKXError:
    """OKXError 错误解析"""

    def test_no_error_when_code_is_zero(self):
        """顶层 code='0' → 无错误"""
        resp = {"code": "0", "msg": "", "data": [{"foo": "bar"}]}
        assert OKXError.from_response(resp) is None

    def test_no_error_when_data_is_empty_list(self):
        """data 为空列表 → 无错误"""
        resp = {"code": "0", "msg": "", "data": []}
        assert OKXError.from_response(resp) is None

    def test_no_error_when_data_is_none(self):
        """data 为 None → 无错误"""
        resp = {"code": "0", "msg": "", "data": None}
        assert OKXError.from_response(resp) is None

    def test_top_level_error(self):
        """顶层 code != '0' → 抛出顶层错误"""
        resp = {"code": "50113", "msg": "Invalid Sign", "data": []}
        err = OKXError.from_response(resp)
        assert err is not None
        assert err.code == 50113
        assert err.msg == "Invalid Sign"

    def test_data_scode_error_place_order(self):
        """下单业务错误（OKX 真实响应：顶层 code='1' + data[].sCode != '0'）

        实际从 OKX API 拿到的下单失败响应是这样的：
        {
          "code": "1",
          "msg": "All operations failed",
          "data": [{
            "sCode": "51008",
            "sMsg": "Order failed. Your available USDT balance is insufficient..."
          }]
        }
        必须优先返回 sCode 错误（更具体），而不是顶层 code="1"。
        """
        resp = {
            "code": "1",
            "msg": "All operations failed",
            "data": [
                {
                    "clOrdId": "",
                    "ordId": "",
                    "sCode": "51008",
                    "sMsg": "Order failed. Your available USDT balance is insufficient, "
                    "and your available margin (in USD) is too low for borrowing.",
                    "subCode": "1000",
                    "tag": "",
                    "ts": "1783746312997",
                }
            ],
        }
        err = OKXError.from_response(resp)
        assert err is not None
        assert err.code == 51008
        assert "balance is insufficient" in err.msg

    def test_top_zero_with_scode_zero(self):
        """顶层 code='0' 且所有 sCode='0' → 成功，不抛错"""
        resp = {
            "code": "0",
            "msg": "",
            "data": [
                {"sCode": "0", "sMsg": "", "ordId": "12345"},
            ],
        }
        assert OKXError.from_response(resp) is None

    def test_partial_success_in_batch(self):
        """批量下单部分成功：第一个失败第二个成功 → 应抛第一个错误"""
        resp = {
            "code": "0",
            "msg": "All operations failed",
            "data": [
                {"sCode": "51008", "sMsg": "balance insufficient"},
                {"sCode": "0", "sMsg": "", "ordId": "12345"},
            ],
        }
        err = OKXError.from_response(resp)
        assert err is not None
        assert err.code == 51008

    def test_check_response_raises_on_error(self):
        """check_response 触发异常路径"""
        resp = {
            "code": "0",
            "data": [{"sCode": "51008", "sMsg": "balance insufficient"}],
        }
        with pytest.raises(OKXError) as exc_info:
            check_response(resp)
        assert exc_info.value.code == 51008

    def test_check_response_returns_data_on_success(self):
        """check_response 成功路径返回 data"""
        resp = {"code": "0", "data": [{"foo": "bar"}]}
        result = check_response(resp)
        assert result == [{"foo": "bar"}]

    def test_non_dict_data_item_ignored(self):
        """data 里非 dict 元素（如 [1,2,3] 类型的 K 线）应被忽略，不误报"""
        resp = {
            "code": "0",
            "data": [
                [1234567890, "100", "110", "90", "105", "1000"],  # K 线是 list
            ],
        }
        assert OKXError.from_response(resp) is None

    def test_scode_with_string_message(self):
        """sCode 错误但 sMsg 为空时，使用顶层 msg 作为兜底"""
        resp = {
            "code": "0",
            "msg": "All operations failed",
            "data": [{"sCode": "51111", "sMsg": ""}],
        }
        err = OKXError.from_response(resp)
        assert err is not None
        assert err.code == 51111
        assert err.msg == "All operations failed"


class TestSideNormalization:
    """side_to_str / pos_side_to_str 翻译"""

    def test_side_to_str_buy_sell(self):
        """buy / sell 原样返回"""
        assert side_to_str("buy") == "buy"
        assert side_to_str("sell") == "sell"
        assert side_to_str("BUY") == "buy"
        assert side_to_str("SELL") == "sell"

    def test_side_to_str_long_short_translation(self):
        """long → buy，short → sell（做多=买入，做空=卖出）

        这样 Signal.direction (long/short) 可以直接传给 place_order 的 side 参数。
        """
        assert side_to_str("long") == "buy"
        assert side_to_str("short") == "sell"
        assert side_to_str("LONG") == "buy"
        assert side_to_str("SHORT") == "sell"

    def test_side_to_str_passthrough_unknown(self):
        """未知输入原样透传（避免静默丢错）"""
        assert side_to_str("unknown") == "unknown"

    def test_pos_side_to_str(self):
        """pos_side 保持 long/short 不变"""
        assert pos_side_to_str("long") == "long"
        assert pos_side_to_str("short") == "short"
        assert pos_side_to_str("net") == "net"
        assert pos_side_to_str("LONG") == "long"