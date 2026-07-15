#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX API v5 使用示例

运行前请确保项目根 .env 中配置了正确的 API 凭据（参考 .env.example），或设置环境变量：
    export OKX_DEMO_API_KEY=your_api_key
    export OKX_DEMO_API_SECRET=your_secret_key
    export OKX_DEMO_PASSPHRASE=your_passphrase
    export OKX_TRADING_MODE=demo

执行方式：./run.sh docs/agent-context/basic_usage.py
"""

from okx.code import OKXClient


def main():
    client = OKXClient()

    # client = OKXClient(
    #     api_key="your_api_key",
    #     secret_key="your_secret_key",
    #     passphrase="your_passphrase",
    #     flag="1",
    # )

    print("=" * 50)
    print(f"OKX Client 初始化完成")
    print(f"  模拟盘: {client.demo}")
    print(f"  已配置交易凭据: {client.creds_provided}")
    print("=" * 50)

    # ── 市场数据（无需签名）─────────────────────────

    print("\n[市场数据] 获取 BTC-USDT 行情")
    ticker = client.market.get_ticker("BTC-USDT")
    print(f"  最新价: {ticker}")

    print("\n[市场数据] 获取订单簿")
    books = client.market.get_orderbook("BTC-USDT", depth=5)
    print(f"  买单前5档: {books.get('bids', [])[:5]}")
    print(f"  卖单前5档: {books.get('asks', [])[:5]}")

    print("\n[市场数据] 获取 1H K线")
    candles = client.market.get_candles("BTC-USDT", bar="1H", limit=5)
    print(f"  最近5根K线: {candles}")

    # ── 账户（需要签名）──────────────────────────────

    if not client.creds_provided:
        print("\n[账户] 未配置凭据，跳过账户操作")
        return

    print("\n[账户] 获取余额")
    balance = client.account.get_balance()
    print(f"  账户余额: {balance}")


if __name__ == "__main__":
    main()