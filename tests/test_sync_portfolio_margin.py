#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_sync_portfolio_margin.py —— v1.8.3 candidate #6 regression

bug: sync_portfolio.py notional = mark * sz (缺 × ct_val)
     → margin 被算成 100 倍 (BTC sz=0.16 ct_val=0.01 应 notional ~$103, 旧算 $10,317)
fix: notional = mark * sz * ct_val
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))


def _build_op(mark: float, sz: float, lever: float, ct_val: float = 0.01):
    """构造 OKX position API dict 模拟输入"""
    return {
        "instId": "BTC-USDT-SWAP",
        "posSide": "short",
        "pos": str(sz),
        "avgPx": str(mark),
        "markPx": str(mark),
        "lever": str(lever),
        "ctVal": str(ct_val),
        "mgnMode": "isolated",
        "cTime": "1784467967697",
    }


def test_btc_short_notional_uses_ct_val():
    """v1.8.3+ fix: notional 必须 = mark × sz × ct_val

    BTC-USDT-SWAP: sz=0.16 张, ct_val=0.01 BTC/张, mark=64486.5, lever=3
    notional = 64486.5 × 0.16 × 0.01 = $103.18  ✅
    margin   = notional / 3 = $34.39  ✅
    """
    from scripts import sync_portfolio

    op = _build_op(mark=64486.5, sz=0.16, lever=3.0, ct_val=0.01)
    # 调用 sync_portfolio 内部函数 (mapping logic)
    notional_usd, margin_usd, ct_val = sync_portfolio._normalize_position(op)

    assert abs(notional_usd - 103.18) < 0.5, (
        f"notional={notional_usd} 应 ~103.18 (mark × sz × ct_val)"
    )
    assert abs(margin_usd - 34.39) < 0.5, f"margin={margin_usd} 应 ~34.39"
    assert abs(ct_val - 0.01) < 1e-9


def test_eth_short_notional_uses_ct_val():
    """ETH-USDT-SWAP: sz=1.0 张, ct_val=0.1 ETH/张, mark=3000, lever=3
    notional = 3000 × 1.0 × 0.1 = $300
    margin   = $300 / 3 = $100
    """
    from scripts import sync_portfolio

    op = _build_op(mark=3000.0, sz=1.0, lever=3.0, ct_val=0.1)
    op["instId"] = "ETH-USDT-SWAP"
    notional_usd, margin_usd, ct_val = sync_portfolio._normalize_position(op)

    assert abs(notional_usd - 300.0) < 0.1
    assert abs(margin_usd - 100.0) < 0.1
    assert abs(ct_val - 0.1) < 1e-9


def test_no_100x_overcount_regression():
    """v1.8.3 candidate #6 核心反例: 不能用 notional = mark × sz (会算大 100 倍)"""
    from scripts import sync_portfolio

    op = _build_op(mark=64486.5, sz=0.16, lever=3.0, ct_val=0.01)
    notional_usd, _, _ = sync_portfolio._normalize_position(op)
    # 旧公式: notional = 64486.5 × 0.16 = 10317.84 → 失败
    assert notional_usd < 200.0, "bug 回归: notional 算太大 (缺少 × ct_val)"
    assert notional_usd < 200.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
