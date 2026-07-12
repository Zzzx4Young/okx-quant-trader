# Telegram 通知层 (Notifier)

> 版本：v1.0 | 创建：2026-07-11

OKX 交易系统的实时通知层。交易动作（开仓 / 平仓 / 部分平 / 错误）会实时推送到 Telegram，每日自动发送交易报告。

---

## 工作原理

```
Runner (okx/code/runner.py)
    │
    ├─ 开仓成功 ─────→ TelegramNotifier.notify_open() ─→ Telegram Bot API
    ├─ 平仓成功 ─────→ TelegramNotifier.notify_close() ─→ Telegram Bot API
    ├─ 部分平 ───────→ TelegramNotifier.notify_partial_close() ─→ Telegram Bot API
    └─ 异常 ─────────→ TelegramNotifier.notify_error() ─→ Telegram Bot API

daily_summary.py (cron)
    │
    └─ 每日报告 ─────→ TelegramNotifier.notify_daily_summary() ─→ Telegram Bot API
```

**特点**：
- 通知失败**不会阻塞交易**（所有 `notify_*` 都包了 try/except）
- 走 OKX 客户端的代理配置（WSL2 / 跨网场景适用）
- 同类错误自动去重（5 分钟内只发一次）
- 限频：1 秒最小间隔（防止触发 Telegram API 限制）

---

## 快速开始

### 1. 拿到 Bot Token 和 Chat ID

**Bot Token**（用 @BotFather 创建）：
1. Telegram 搜索 `@BotFather`，开始对话
2. 发送 `/newbot`
3. 按提示设置 bot name（任意）和 username（必须以 `bot` 结尾）
4. 复制返回的 token，形如：`123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`

**Chat ID**（接收消息的目标）：
- **个人 chat**：跟 bot 随便说一句，然后浏览器访问 `https://api.telegram.org/bot<TOKEN>/getUpdates`
- 在返回 JSON 里找 `chat.id`（个人是 9-10 位数字）
- **群组 chat**：把 bot 拉进群，群里发一条消息，同样用 `getUpdates` 查 `chat.id`（群是负数，开头是 `-`）

### 2. 配置 .env

编辑 `okx/.env`，添加：

```bash
# Telegram 通知（任选一组）
TELEGRAM_BOT_TOKEN=<your_bot_token_here>
TELEGRAM_CHAT_ID=<your_chat_id_here>
# TELEGRAM_ENABLED=true   # 默认 true，可省略
```

或者用 OKX 命名空间（避免污染全局）：

```bash
OKX_NOTIFIER_TELEGRAM_BOT_TOKEN=...
OKX_NOTIFIER_TELEGRAM_CHAT_ID=...
OKX_NOTIFIER_ENABLED=true
```

### 3. 测试

```bash
./run.sh scripts/test_notifier.py --type=basic
./run.sh scripts/test_notifier.py --type=all    # 发送 6 类测试消息
./run.sh scripts/test_notifier.py --dry-run     # 不真发，看格式
```

### 4. 接入每日报告（cron）

```bash
# 每天 UTC 15:00（北京时间 23:00）发当日报告
0 15 * * * cd /path/to/workspace && bash okx/run.sh okx/scripts/daily_summary.py >> okx/logs/daily_summary.log 2>&1
```

---

## 配置项

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | 无 | Bot Token（**必填**） |
| `TELEGRAM_CHAT_ID` | 无 | 目标 chat ID（**必填**） |
| `TELEGRAM_ENABLED` | `true` | 是否启用通知 |
| `OKX_NOTIFIER_TELEGRAM_BOT_TOKEN` | 无 | 同上，OKX 命名空间 |
| `OKX_NOTIFIER_TELEGRAM_CHAT_ID` | 无 | 同上 |
| `OKX_NOTIFIER_ENABLED` | `true` | 同上 |

### state/config.json

```json
{
  "notifier": {
    "enabled": true,
    "min_interval_sec": 1,
    "daily_summary_hour_utc": 15
  }
}
```

---

## 消息格式

### 开仓（绿色）
```
🟢 开仓 #BTC-USDT-SWAP

方向: 做多 (long)
入场价: 64,123.45
止损: 63,802.15 (-0.50%)
止盈: 64,940.96 (+1.27%)
杠杆: 5x isolated
数量: 100 张
保证金: 1,282.47 USDT
策略: EMA20_BREAKOUT
订单: 1234567890

⏰ 2026-07-11 05:30 UTC (北京 13:30)
```

### 平仓（💰 盈利 / 💸 亏损）
```
💰 平仓 #BTC-USDT-SWAP

原因: TP触发
盈亏: +45.20 USDT
收益率: +3.52%

⏰ 2026-07-11 06:00 UTC (北京 14:00)
```

### 部分平仓
```
📊 部分平仓 #BTC-USDT-SWAP

原因: TP-1:1（第一批 30%）
平仓比例: 30%
本次盈亏: +15.20 USDT (+1.20%)
新止损: 64,123.45
止盈阶段: TP-1

⏰ 2026-07-11 06:00 UTC (北京 14:00)
```

### 错误
```
⚠️ 交易系统错误

下单 #BTC-USDT-SWAP
[51008] Order failed. Your available USDT balance is insufficient

⏰ 2026-07-11 05:30 UTC (北京 13:30)
```

### 每日报告
```
📈 每日交易报告 (2026-07-11)

📊 交易统计
  开仓: 3 笔
  平仓: 2 笔
  ├─ 盈利: 1 笔
  └─ 亏损: 1 笔

💰 盈亏
  总盈亏: +50.0000 USDT
  手续费: 1.6000 USDT
  净盈亏: +49.1700 USDT
  胜率: 50.0%

🎯 策略分布
  EMA20_BREAKOUT: 2 次

⏰ 2026-07-11 23:00 UTC (北京 07:00)
```

---

## API 文档

### `TelegramNotifier`

```python
from okx.code.notifier import TelegramNotifier

# 从环境变量构造
n = TelegramNotifier.from_env()  # 自动读 TELEGRAM_* 或 OKX_NOTIFIER_*

# 或直接构造
n = TelegramNotifier(
    bot_token="<your_bot_token_here>",
    chat_id="<your_chat_id_here>",
    proxy_url="http://127.0.0.1:<port>",  # 可选，例如 WSL2 走本地代理
    enabled=True,
    min_interval_sec=1,
)

# 通用发送
ok = n.send("Hello <b>World</b>")  # 返回 True/False

# 业务事件
n.notify_open(position_dict)        # 开仓
n.notify_close(close_result_dict)   # 平仓
n.notify_partial_close(partial_dict)  # 部分平
n.notify_error(error_msg, context="...", dedup_key="...")  # 错误（自动去重）
n.notify_daily_summary(stats_dict)  # 每日报告
n.notify_heartbeat(status_dict)     # 心跳/状态
```

### 静默通知（不推送）

```python
n.send("深夜心跳报告", silent=True)  # 收到但不响铃/不弹通知
```

---

## 测试场景覆盖

✅ 单元测试：`tests/test_utils.py` 等
✅ 集成测试：`scripts/test_notifier.py --type=all`
✅ 端到端测试：mock Telegram server，验证 7 类消息（basic / open / close_profit / close_loss / partial / error / daily）
✅ Daily summary 测试：mock 真实 CSV 数据，验证胜率/策略分布/持仓统计

---

## 故障排查

### 1. 通知没收到
- 检查 `.env` 里 token 和 chat_id 是否正确
- 浏览器访问 `https://api.telegram.org/bot<TOKEN>/getMe` 应该返回 bot 信息
- 浏览器访问 `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=test` 应该收到 "test"
- 检查 `OPENCLAW_*_PROXY` env 是否设置（WSL2 下 OKX 走代理，Telegram 也走）

### 2. 通知被限频
- Telegram 限制：同一 chat 每秒最多 1 条消息
- 同 bot 给不同 chat：30 条/秒
- 如触发限频，HTTP 429 错误，Notifer 会记录日志但不抛错
- 调整 `notifier.min_interval_sec` 到 2 或更高

### 3. 错误消息没自动去重
- 默认同类型错误 5 分钟内只发一次（key = error_msg 前 50 字符）
- 自定义 `dedup_key` 参数可精细控制

### 4. 每日报告 cron 没跑
- 检查 cron 服务：`crontab -l | grep daily_summary`
- 检查日志：`tail -n 50 okx/logs/daily_summary.log`
- 手动测试：`./run.sh scripts/daily_summary.py --print`

---

## 下一步

- ✅ 通知层 v1（基础事件）
- ⏳ 接入 cron 每 5 分钟自动跑 Runner（next）
- ⏳ Watchdog：cron 超过 N 分钟没跑 → 发告警
- ⏳ 行情异动提醒（非交易信号，只是价格大幅波动提示）
- ⏳ 多用户支持（不同 chat_id 收不同事件）