# OKX Trading API v5 集成文档

> 文档版本：v5 | 更新时间：2026-06-07
> 官方文档：https://www.okx.com/docs-v5/en/

---

## 1. 概述

OKX API v5 提供 REST API 和 WebSocket API，支持以下交易品种：

| 品种 | 说明 |
|------|------|
| **Spot** | 现货交易 |
| **Margin** | 杠杆交易（逐仓/全仓） |
| **Futures** | 期货合约 |
| **Perpetual Swap** | 永续合约 |
| **Options** | 期权 |

**Base URL：**
- 正式环境：`https://www.okx.com`
- Demo/测试环境：`https://www.okx.com`（通过 `flag='1'` 切换）

---

## 2. API Key 获取

1. 注册 OKX 账户：https://www.okx.com/account/register
2. 申请 API Key：https://www.okx.com/account/users/myApi
3. 获取三个凭据：
   - **API Key** — 公钥
   - **Secret Key** — 私钥
   - **Passphrase** — 口令（创建时设置，**无法找回**，丢失需重新生成）

### 环境切换（flag 参数）
```
flag = '0'  → 正式交易
flag = '1'  → Demo交易（模拟盘）
```

---

## 3. 认证机制

OKX API v5 使用 HMAC SHA256 签名认证，每个请求需在 HTTP Header 中包含以下字段：

| Header 字段 | 说明 |
|-------------|------|
| `OK-ACCESS-KEY` | API Key |
| `OK-ACCESS-SIGN` | HMAC SHA256 签名（用 Secret Key 对 timestamp + method + path + body 加密） |
| `OK-ACCESS-TIMESTAMP` | 请求时间戳（UTC 时间，格式：`2026-06-07T09:00:00.000Z`） |
| `OK-ACCESS-PASSPHRASE` | 口令 |
| `Content-Type` | `application/json` |

### 签名算法（Python 示例）

```python
import hmac
import hashlib
import datetime

def generate_signature(timestamp, method, path, body, secret_key):
    message = timestamp + method + path + body
    mac = hashlib.sha256(secret_key.encode()).digest()
    signature = hmac.new(mac, message.encode(), hashlib.sha256).digest()
    return signature.hex()
```

---

## 4. REST API 端点

### 4.1 基础信息

所有端点基础路径：`https://www.okx.com`

时间端点（获取服务器时间）：
```
GET /api/v5/public/time
```

---

### 4.2 市场数据（Market Data）

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v5/market/tickers` | 所有交易对行情 |
| GET | `/api/v5/market/ticker` | 单个交易对行情 |
| GET | `/api/v5/market/books` | 订单簿 |
| GET | `/api/v5/market/books-lite` | 订单簿（轻量版） |
| GET | `/api/v5/market/candles` | K线数据（蜡烛图） |
| GET | `/api/v5/market/history-candles` | 历史K线 |
| GET | `/api/v5/market/trades` | 实时成交 |
| GET | `/api/v5/market/history-trades` | 历史成交 |
| GET | `/api/v5/market/index-tickers` | 指数行情 |
| GET | `/api/v5/market/index-candles` | 指数K线 |
| GET | `/api/v5/market/mark-price-candles` | 标记价格K线 |
| GET | `/api/v5/market/platform-24-volume` | 24小时交易量 |
| GET | `/api/v5/market/exchange-rate` | 汇率 |
| GET | `/api/v5/market/block-tickers` | 大宗行情 |
| GET | `/api/v5/market/block-trades` | 大宗成交 |

---

### 4.3 公开数据（Public Data）

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v5/public/instruments` | 交易对/合约信息 |
| GET | `/api/v5/public/delivery-exercise-history` | 交割/行权历史 |
| GET | `/api/v5/public/open-interest` | 未平仓量 |
| GET | `/api/v5/public/funding-rate` | 资金费率 |
| GET | `/api/v5/public/funding-rate-history` | 资金费率历史 |
| GET | `/api/v5/public/price-limit` | 限价 |
| GET | `/api/v5/public/estimated-price` | 预计交割价格 |
| GET | `/api/v5/public/mark-price` | 标记价格 |
| GET | `/api/v5/public/position-tiers` | 仓位档位 |
| GET | `/api/v5/public/opt-summary` | 期权greeks/IV摘要 |
| GET | `/api/v5/public/underlying` | 标的资产列表 |
| GET | `/api/v5/public/insurance-fund` | 保险基金 |
| GET | `/api/v5/public/liquidation-orders` | 强平订单 |
| GET | `/api/v5/public/time` | 系统时间 |

---

### 4.4 交易（Trade）

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v5/trade/order` |下单 |
| POST | `/api/v5/trade/batch-orders` | 批量下单 |
| POST | `/api/v5/trade/cancel-order` | 取消订单 |
| POST | `/api/v5/trade/cancel-batch-orders` | 批量取消 |
| POST | `/api/v5/trade/amend-order` | 修改订单 |
| POST | `/api/v5/trade/amend-batch-orders` | 批量修改 |
| POST | `/api/v5/trade/close-position` | 平仓 |
| GET | `/api/v5/trade/order` | 查询订单详情 |
| GET | `/api/v5/trade/orders-pending` | 查询未成交订单 |
| GET | `/api/v5/trade/orders-history` | 查询历史订单（近7天） |
| GET | `/api/v5/trade/orders-history-archive` | 查询历史订单（近3月） |
| GET | `/api/v5/trade/fills` | 查询成交明细 |
| GET | `/api/v5/trade/fills-history` | 查询历史成交 |
| POST | `/api/v5/trade/order-algo` | 下算法单（止损/止盈/冰山等） |
| POST | `/api/v5/trade/cancel-algos` | 取消算法单 |
| GET | `/api/v5/trade/orders-algo-pending` | 查询未触发算法单 |
| GET | `/api/v5/trade/orders-algo-history` | 查询算法单历史 |

#### 订单类型（ordType）

| ordType | 说明 |
|----------|------|
| `market` | 市价单 |
| `limit` | 限价单 |
| `post_only` | 只挂单（被动委托） |
| `fok` | Fill-Or-Kill（全成或全撤） |
| `ioc` | Immediate-Or-Cancel（立刻成交或取消） |
| `optimal_limit_ioc` | 市场IOC |
| `stop_market` | 止损市价单 |
| `stop_limit` | 止损限价单 |
| `take_profit` | 止盈单 |
| `move_order_stop` | 移动止损 |

#### 交易模式（tdMode）

| tdMode | 说明 |
|--------|------|
| `cross` | 全仓 |
| `isolated` | 逐仓 |
| `cash` | 现货 |

---

### 4.5 账户（Account）

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v5/account/balance` | 获取账户余额 |
| GET | `/api/v5/account/positions` | 获取持仓 |
| GET | `/api/v5/account/account-position-risk` | 账户/持仓风险 |
| GET | `/api/v5/account/config` | 账户配置信息 |
| POST | `/api/v5/account/set-position-mode` | 设置仓位模式（双向/单向） |
| POST | `/api/v5/account/set-leverage` | 设置杠杆倍数 |
| GET | `/api/v5/account/leverage-info` | 查询杠杆信息 |
| POST | `/api/v5/account/position/margin-balance` | 增加/减少保证金 |
| GET | `/api/v5/account/interest-accrued` | 利息应计 |
| GET | `/api/v5/account/interest-rate` | 利率查询 |
| GET | `/api/v5/account/trade-fee` | 手续费率 |
| GET | `/api/v5/account/max-withdrawal` | 最大可提金额 |
| GET | `/api/v5/account/bills` | 账单流水（近7天） |
| GET | `/api/v5/account/bills-archive` | 账单流水（近3月） |
| GET | `/api/v5/account/positions-history` | 持仓历史 |
| GET | `/api/v5/account/greeks` | Greeks信息（期权） |
| POST | `/api/v5/account/set-greeks` | 设置Greeks展示模式 |

---

### 4.6 资金（Asset / Funding）

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v5/asset/balances` | 资金余额 |
| POST | `/api/v5/asset/transfer` | 资金划转（现货/合约/杠杆等） |
| GET | `/api/v5/asset/transfer-state` | 划转状态 |
| GET | `/api/v5/asset/deposit-address` | 充值地址 |
| GET | `/api/v5/asset/withdrawal` | 提币 |
| GET | `/api/v5/asset/deposit-history` | 充值记录 |
| GET | `/api/v5/asset/withdrawal-history` | 提币记录 |
| GET | `/api/v5/asset/currencies` | 币种信息 |
| POST | `/api/v5/asset/withdrawal` | 提币 |
| POST | `/api/v5/asset/cancel-withdrawal` | 取消提币 |
| POST | `/api/v5/asset/convert-dust-assets` | dust币兑换 |
| GET | `/api/v5/asset/asset-valuation` | 资产估值 |

---

### 4.7 子账户（SubAccount）

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v5/account/subaccount/balances` | 子账户余额 |
| GET | `/api/v5/asset/subaccount/balances` | 子账户资产 |
| POST | `/api/v5/asset/subaccount/transfer` | 子账户划转 |
| GET | `/api/v5/users/subaccount/list` | 子账户列表 |
| POST | `/api/v5/users/subaccount/modify-apikey` | 修改子账户API Key |

---

## 5. Python SDK 使用

### 5.1 安装

```bash
pip install python-okx
```

> GitHub: https://github.com/okxapi/python-okx

### 5.2 初始化

```python
from okx import Account, Trade, Market

# 方法1：直接填入
account = Account.AccountAPI(
    api_key="your-api-key",
    api_secret_key="your-secret-key",
    passphrase="your-passphrase",
    flag="1"  # 0=实盘, 1=模拟盘
)

# 方法2：使用 .env（推荐）
# OKX_API_KEY=xxx
# OKX_API_SECRET=xxx
# OKX_PASSPHRASE=xxx
# OKX_FLAG=1
```

### 5.3 交易示例

```python
from okx import Trade

trade = Trade.TradeAPI(api_key, secret_key, passphrase, flag="1")

# 下单
result = trade.place_order(
    instId="BTC-USDT",      # 交易对
    tdMode="cross",         # 全仓
    side="buy",             # 买入
    ordType="limit",        # 限价单
    sz="0.01",             # 数量
    px="50000"             # 价格
)
print(result)

# 取消订单
trade.cancel_order(instId="BTC-USDT", ordId="订单ID")

# 查询未成交订单
trade.get_order_list(instType="SPOT")

# 市价买入
trade.place_order(instId="BTC-USDT", tdMode="cash", side="buy",
                 ordType="market", sz="100")
```

### 5.4 市场数据示例

```python
from okx import Market

market = Market.MarketAPI()

# 订单簿
books = market.get_orderbook(instId="BTC-USDT", sz="20")

# K线
candles = market.get_candles(instId="BTC-USDT", bar="1m")

# 成交
trades = market.get_trades(instId="BTC-USDT")
```

### 5.5 账户示例

```python
from okx import Account

account = Account.AccountAPI(api_key, secret_key, passphrase, flag="1")

# 余额
balance = account.get_account_balance()

# 持仓
positions = account.get_positions(instType="SPOT")

# 设置杠杆
account.set_leverage(lever="10", mgnMode="isolated", instId="BTC-USDT-SWAP")
```

---

## 6. WebSocket API

### 6.1 连接地址

| 环境 | 地址 |
|------|------|
| 正式 | `wss://ws.okx.com:8443/ws/v5/business` |
| Demo | `wss://wspub.okx.com:8443/ws/v5/business` |

### 6.2 公共频道（无需认证）

| 频道 | 说明 |
|------|------|
| `tickers` | 全量行情 |
| `ticker` | 单交易对行情 |
| `books` | 订单簿 |
| `books-lite` | 订单簿（轻量） |
| `trades` | 实时成交 |
| `candles` | K线 |
| `index-tickers` | 指数行情 |
| `mark-price-candles` | 标记价格K线 |

### 6.3 私有频道（需认证）

| 频道 | 说明 |
|------|------|
| `orders` | 订单更新 |
| `positions` | 持仓更新 |
| `account` | 账户更新 |
| `balance_and_position` | 余额和持仓 |

### 6.4 Python WebSocket 示例

```python
import json
from okx import WebSocket

def handle_message(message):
    print(json.loads(message))

ws = WebSocket.WebSocketAPI(
    api_key=api_key,
    api_secret_key=secret_key,
    passphrase=passphrase,
    domain="https://www.okx.com"
)

# 订阅公共频道
ws.subscribe(
    channel=["ticker.BTC-USDT"],
    callback=handle_message
)

# 订阅私有频道
ws.subscribe(
    channel=["orders.BTC-USDT"],
    callback=handle_message
)
```

---

## 7. 核心参数速查

### instType（品种类型）

| 值 | 说明 |
|----|------|
| `SPOT` | 现货 |
| `MARGIN` | 杠杆 |
| `SWAP` | 永续合约 |
| `FUTURES` | 期货 |
| `OPTION` | 期权 |

### posSide（持仓方向）

| 值 | 说明 |
|----|------|
| `long` | 多头 |
| `short` | 空头 |
| `net` | 净持仓（单向模式） |

### side（方向）

| 值 | 说明 |
|----|------|
| `buy` | 买入/做多 |
| `sell` | 卖出/做空 |

---

## 8. 错误码

| 错误码 | 说明 |
|--------|------|
| `58001` | 无效签名 |
| `5811` | API Key无效 |
| `5812` | 无效口令 |
| `5830` | 余额不足 |
| `51008` | 订单价格超出限制 |
| `51109` | 数量过小 |
| `53000` | 账户被限制交易 |

---

## 9. 参考链接

| 资源 | 链接 |
|------|------|
| 官方文档 | https://www.okx.com/docs-v5/en/ |
| Python SDK | https://github.com/okxapi/python-okx |
| API申请 | https://www.okx.com/account/users/myApi |
| 官方API协议 | https://www.okx.com/docs-v5/legal/ |
