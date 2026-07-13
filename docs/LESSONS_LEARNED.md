# OKX 量化交易系统 — 经验教训与架构决策

> **版本**：v1.6（2026-07-13 23:02 归档）  
> **范围**：从 2026-06-28 v1.0 到 2026-07-12 v1.5 的完整开发历程  
> **定位**：补充 README（功能介绍）和 PROJECT-STRUCTURE（结构说明）未覆盖的"决策依据"和"踩坑复盘"

---

## 0. 阅读指南

- **看功能怎么用** → `README.md`
- **看代码怎么组织** → `PROJECT-STRUCTURE.md`
- **看交易流程怎么跑** → `WORKFLOW.md` / `docs/SIGNALS.md`
- **看为什么这么设计 + 踩过什么坑** → **本文件**

---

## 1. 演进时间线（轻量级里程碑）

| 版本 | 日期 | 核心变更 | 标志性事件 |
|------|------|----------|------------|
| v1.0 | 2026-06-28 | 初版：EMA20 + 下单链路 + CLI | 跑通单笔 demo 交易 |
| v1.1 | 2026-07-10 | P0 重构 + Constitution（4 策略 + 杠杆矩阵） | 删除 3 个并行入口，统一 `cli.py` |
| v1.2 | 2026-07-11 | 双模式凭据架构 + 签名 P0 修复 + 下单链路 bugC-G | LIVE/DEMO 凭据隔离，V5 API 私 API 6/6 通 |
| v1.3 | 2026-07-11 | 通知层 v1 + cron 调度 + watchdog | 7 类通知 mock E2E 全过，watchdog 健康 |
| v1.4 | 2026-07-11 | Market Constitution 完整实施 | 4 策略全启，风控全配 |
| **v1.5** | **2026-07-12** | **portfolio ↔ OKX 对账 + 三大 bug 修复 + Git 仓库** | **事故复盘 ETH short 误平，PnL 计算虚高 25 倍修正** |
| **v1.6** | **2026-07-13** | **Phase 1 回测引擎 + 4 个 OKX API 反直觉点** | **数据引擎跑通（15000 K线 + 292 funding），MVP 验证手续费 3.7% 本金** |

详细 commit 历史见 `git log`（2026-07-12 初始化）。

---

## 2. Bug 复盘集（核心章节）

> 每个 bug 一节：**症状 → 根因 → 修复 → 教训**。优先级按严重性递减。

### 🩸 Bug P0：API 签名三重错（2026-07-11）

**症状**：所有 OKX 私 API 调用返回 `50113 Invalid Sign`。

**根因**（三个独立错误叠加）：
1. 对 `secret` 先 `sha256()` 再 HMAC（OKX V5 不需要预哈希）
2. 返回 `hex` 编码（应为 `base64`）
3. 时间戳用 `%f` 6 位微秒（应为 3 位毫秒：`YYYY-MM-DDTHH:mm:ss.SSSZ`）

**修复**（`code/auth.py` 重写）：
```python
# 正确签名
digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), sha256).digest()
signature = base64.b64encode(digest).decode()
# 正确时间戳
timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
```

**教训**：
- **官方文档每个字段都要逐字核**：微秒 vs 毫秒、hex vs base64 这种 1 字节差异在文档里通常不强调，但 API 服务端严格按规范校验
- **签名逻辑单独隔离到 `auth.py`**：单一职责，改动半径小；后来所有 OKX 私 API 调用都通过这一个出口
- **第一次跑通前不算"完成"**：v1.0 跑了 2 周 demo 都没发现，因为一直用 GET 公开 API 没触发签名

---

### 🩸 Bug 0：模拟盘模式需额外 Header（2026-07-11，bugH）

**症状**：用 DEMO key + `OKX_TRADING_MODE=demo` 调用私 API，返回 `50101 APIKey does not match current environment` 或余额为 $0。

**根因**：仅设 `OKX_FLAG=1` 不够，OKX V5 模拟盘需要**额外的 HTTP header** `x-simulated-trading: 1`。

**修复**（`_http.py`）：在 demo 模式下自动注入 `x-simulated-trading: 1` header。

**教训**：
- **OKX LIVE/DEMO 是硬隔离的两套账户**：LIVE key 不能用于 demo 模式，反之亦然。账户、API key、passphrase 都是独立的
- **flags 不等于 headers**：环境变量是配置，HTTP header 是协议层细节，要分开处理
- **诊断账户状态用余额返回，不是 API 错误码**：API 错误可能误导（50101 是 "不匹配" 但其实是不存在），余额是终极真相

**实测验证补充（2026-07-13，Phase 1 数据引擎开发时）**：

V2.1 设计稿提出"双 header 防御"（同时发 `x-simulated-id: 1` 和 `x-simulated-trading: 1`）。我们用 `code/backtest/verify_headers.py` 跑了 4 场景矩阵验证：

| Header 组合 | 私 API 余额 | 公共 API ticker |
|---|---|---|
| 无 header | ❌ 50101 路由失败 | ✅ HTTP 200 |
| `x-simulated-id` 单发 | ❌ 50101 | ✅ HTTP 200 |
| `x-simulated-trading` 单发 | ✅ DEMO 77,171 USDT | ✅ HTTP 200 |
| 双 header (V2.1) | ✅ DEMO 77,171 USDT | ✅ HTTP 200 |

**实测发现**：
- ✅ `x-simulated-trading: 1` 是 OKX V5 唯一识别的 demo header
- ❌ `x-simulated-id` 在 OKX V5 **不被识别**（返回 50101）—— V2.1 文档假设有误
- ✅ 双 header 无害：OKX 接受 `x-simulated-id` 时只是忽略，不报错
- ✅ 公共 API 双 header 不破坏请求（HTTP 200）

**结论**：保留双发作为 forward-compat 防御（未来 OKX 可能切换 header），但更新文档明确"实测 OKX V5 只识别 `x-simulated-trading`，`x-simulated-id` 是无害的空跑"。**不要在生产环境只发 `x-simulated-id`**，会 100% 失败。

---

### 🩸 Bug 1：K线方向倒置（2026-07-12，最严重）

**症状**：system 13:17 自动平仓 ETH short（realized=+0.07 USDT）。但实际是新 EMA20=1801.27 > entry=1804.95 不应触发反向平仓。

**根因**：
OKX `/api/v5/market/candles` 默认返回 **newest → oldest**（倒序）。原 `runner.py` 趋势反转判定：
```python
current_ema = ema_vals[-1]  # ← 拿到的是最老那根，不是最新
```
EMA20 实际计算到的是最老一根 = **1797.54**，而当时新 EMA 是 **1801.27**。判定 `1801.91 > 1797.54 * 1.001 = 1799.34` 为 True → 误触发平仓。

**修复**（`code/market.py:get_candles`）：返回前 `list(reversed(...))`，统一为 oldest → newest。

**顺带修复**（一个抽象层修复，下游全部受益）：
- `signal.py: closes[-1]` 作 current_price → 现为最新 ✅
- `signal.py: ema_values[-1]` / `atr_values[-1]` / `rsi_values[-1]` → 现为最新 ✅
- 所有 `_atr` / `_rsi` / `_bollinger_bands` 本来对顺序敏感，现在顺序对了

**教训**（最重要）：
1. **抽象边界反一次，其他调用者不再背锅**：在 API client 层反转，让业务层用自然顺序（`[-1]` = 最新）
2. **同一逻辑跨多个调用点时，建一个抽象函数**：趋势反转判定在 runner 里出现 2 个分支都有同样 bug，差点只修一处
3. **OKX 接口都是倒序返回**：candles / ticker / bills 都要意识到方向——已成我们排查问题时的第一反应
4. **"系统交易" ≠ "无人值守"**：自动平仓也会杀错单，必须要有 portfolio 对账兜底（v1.5 之后）

---

### 🩸 Bug 2：ctVal 没计入 PnL 计算（2026-07-12）

**症状**：`risk.calculate_pnl()` 虚高 PnL。如 0.55 张 ETH long，实际 PnL 应 = `price_diff * 0.55 * 0.1 = price_diff * 0.055`，但代码返回 `price_diff * 0.55`（按 25 倍计算）。

**根因**：OKX 永续合约 `ctVal` 表示**每张对应多少标的**（如 ETH-USDT-SWAP = 0.1 ETH）。原代码 `pnl = price_diff * size` 把 size 当成了 ETH 数量，**实际上 size 是张数**。

**修复**：
- `calculate_pnl(direction, entry, exit, size, ct_val=1.0)` 加 ct_val 参数
- `estimate_fee()` 同理
- 从 `/api/v5/public/instruments` 拿 ctVal，按 instId 缓存到 `public.py`

**教训**：
- **mock 测试无法覆盖这种"量纲错误"**：测试都是裸数字 `size=1`，没乘 ctVal，以为 `size` 就是 ETH
- **真实端到端测试不可替代**：v1.5 加了 `verify_order_chain.py` 专门跑"信号 → 风控 → 下单 → 持仓 → 平仓"全链路，下次重构前必跑
- **金融计算的"单位"必须显式**：在函数签名里写 `ct_val: float` 比让调用方算 `size * ct_val` 更安全

---

### 🩸 Bug 3：mgnMode 默认值导致跨模式报错（2026-07-12）

**症状**：`_close_position()` 调用 `close-position` API 时返回 `51023 Position doesn't exist`。

**根因**：config 默认 `margin_mode=isolated`，但手动开的仓位是 `cross`。OKX 要求 close-position 必须传**仓位实际的** mgnMode，不能用 config 默认。

**修复**（`runner.py:_close_position`）：
```python
mgn_mode = position.get("mgn_mode") or self._config.margin_mode
```
+ `portfolio.reconcile_with_okx()` 同步时拉 OKX 真实 mgnMode 写入 position。

**教训**：
- **配置默认值 ≠ 运行时真相**：手动操作会绕过 config，必须从实际数据源（OKX）拉真实状态
- **"local cache" 永远有 drift 风险**：portfolio.json 只是 cache，对账（reconcile）应该是 mandatory 步骤而不是可选优化

---

### 🩸 Bug 4-8：风控 + 下单链路（2026-07-11，bugA-G）

| Bug | 模块 | 症状 | 根因 | 修复 |
|-----|------|------|------|------|
| A | `risk.py` 净 RR 公式 | 下单前净 RR=0.6 也通过校验 | 没加手续费/滑点成本补偿 | 公式加 `cost_buffer = 0.002 * size * entry` |
| B | `risk.py` 白名单匹配 | `BTC-USDT-SWAP` 不在白名单 `BTC` 里 | 字符串精确匹配，缺规范化和前缀识别 | 白名单改 instId 前缀匹配 |
| C | `trade.py:set_leverage` | OKX 报 `posSide required` | 双向持仓模式漏传 `posSide` | 显式传 `posSide: long/short` |
| D | `utils.py:OKXError` | 业务层报错只显示 `[1] All operations failed` | 只检顶层 `code`，漏检 `data[].sCode` | 递归查 `data[]`，抛 `sCode` 真实错误 |
| E | `trade.py:place_order` | OKX 报 `54070 Parameter not supported` | 旧字段 `slTriggerPx/tpTriggerPx` 已废弃 | 改用 `attachAlgoOrds` 数组 |
| F | `trade.py:place_order` | `side=long` 被 OKX 拒绝 | OKX 接受 `buy/sell`，不接受 `long/short` | `utils.side_to_str()` 加 long→buy 翻译 |
| G | `runner.py` | 5 分钟下单逻辑没考虑 ticker 涨跌幅 | 单根 K 线大波动时入场点位差 | 引入 1m K 线二次确认 |

**教训**：
- **OKX V5 是不断演进的**：半年内字段名（slTriggerPx → attachAlgoOrds）、参数（posSide 新增）、side 语义都改过，**对接任何交易所 API 都不能"一跑通就不管了"**
- **错误信息要看完整链**：HTTP 层 `code` + 业务层 `data[].sCode`，只解析顶层会丢失真因
- **测试覆盖的"边界"是真问题**：bugA-G 都是在 mock 测试里没构造过的真实场景（多笔风控对比、posSide、sCode 错误等）

---

### 🩸 Bug 9：watchdog 永远告警"Runner 未运行"（2026-07-11）

**症状**：`runner_watchdog.py` 一直报"heartbeat 文件不存在"，但 Runner 实际每 5 分钟跑一次。

**根因**：`cli.run_trading_cycle()` 之前不落盘 `last_workflow_result.json`，watchdog 没数据源。

**修复**：`cli.py` 末尾 `Path("state/last_workflow_result.json").write_text(json.dumps({...}))`。

**教训**：
- **运维脚本依赖"约定"的文件时，必须验证约定**：watchdog 第一次跑就发现没文件，应立即回头补 cli 落盘逻辑，而不是"先让 watchdog 容忍"
- **watchdog 的 false positive 比 false negative 危险**：永远告警 → 用户不再看 → 真告警也被忽略

---

### 🩸 Bug 10：OKX V5 API 反直觉细节（2026-07-13，Phase 1 数据引擎实战）

**症状**：开发 `code/backtest/fetch_klines.py` 和 `fetch_funding.py` 时遇到 3 个看似"按文档应该 work"但实测全错的细节，导致 fetch 全失败或只拉到最新 30 条数据。

**3 个发现合并**：

#### 发现 1：`bar` 参数大小写敏感（51000 Parameter bar error）

**症状**：传 `bar=1h` 给 `/api/v5/market/history-candles` → `51000 Parameter bar error`

**根因**：OKX V5 的 bar 参数规范：
- 分钟（m）：**小写** —— `1m`, `5m`, `15m`, `30m`
- 小时（H）/日（D）/周（W）：**大写** —— `1H`, `4H`, `1D`, `1W`

**实测**：传 `bar=1h` 失败，传 `bar=1H` 成功。文档里没强调大小写。

**修复**（`fetch_klines.py:24-37`）：
```python
def _normalize_bar(timeframe: str) -> str:
    tf = timeframe.strip()
    if tf.lower().endswith(("h", "d", "w")):
        return tf.upper()  # 1h → 1H
    elif tf.lower().endswith("m"):
        return tf.lower()  # 15m → 15m
    return tf
```

**教训**：OKX 文档没强调的"格式细节"几乎都是 bug 源。每次写 fetcher 前先用 5 行代码**实测**所有参数，不要相信"看起来合理"。

#### 发现 2：`history-candles` 实际返回 9 列（不是 8 列）

**症状**：用 8 列 DataFrame 构造 `pd.DataFrame(rows, columns=[...8 列...])` → `ValueError: 8 columns passed, passed data had 9 columns`

**根因**：OKX V5 history-candles 实际返回字段：
| Index | 字段 | 类型 |
|-------|------|------|
| 0 | ts | str(毫秒时间戳) |
| 1 | open | str |
| 2 | high | str |
| 3 | low | str |
| 4 | close | str |
| 5 | vol | str（基础币） |
| 6 | volCcy | str（计价币） |
| 7 | volQuote | str（USDT 名义） |
| 8 | **confirm** | str(0/1) **新增** |

第 9 列 `confirm` 在某些文档里没列出（可能 OKX 新加），但实测必返回。

**修复**（`fetch_klines.py:158-167`）：DataFrame 列名加 `"confirm"`，字段类型 int64。

**教训**：
- **永远用 `len(raw_page[0])` 探测实际列数**，不要照文档硬编码 8 列
- **新字段偷偷上线**：OKX 经常不预告加字段，老代码会突然炸

#### 发现 3：分页 cursor `after/`语义实测与文档相反 ⚠️ 最严重

**症状**：`fetch_funding.py` 跑了 30 页只拉到 129 条数据（实际应该 ≥ 270 条/90 天），全是最新数据；`fetch_klines.py` 全量模式只拉到 300 条（应该 2160 条/90 天 1h）

**根因**（实测矩阵）：

| API | before=过去 ts | before=未来 ts | after=过去 ts | after=未来 ts |
|-----|----------------|----------------|---------------|---------------|
| `history-candles` | 返回**最新**数据（参数忽略） | 返回空 | 返回 ts < after（**更老**） | 返回空 |
| `funding-rate-history` | 返回**最新**数据 | 返回空 | 返回 ts < after（**更老**） | 返回空 |

**实测结论**：
- ✅ `after=<ts>`：返回 ts **小于** after 的 limit 条记录（**更老的数据**）—— 与 OKX 官方文档"after: 请求此 ID 之后（更新的数据）"的描述**相反**
- ❌ `before=<ts>`：参数被忽略或语义相反，**永远不能用作分页 cursor**
- 文档描述与实测行为不一致（可能 OKX API 改了语义没更新文档，或文档翻译有问题）

**修复**（`fetch_klines.py:50-55` 和 `fetch_funding.py:38-43`）：
```python
# 正确的分页循环
cursor = start_ts_ms  # 起点 = now（最新时间）
while page_count < max_pages:
    raw_page = _fetch_page(market, inst_id, bar, after=cursor)
    if not raw_page: break
    all_pages.extend(raw_page)
    # 下一页面：after = 当前页最老一根的 ts（OKX 返回 newest → oldest）
    cursor = str(raw_page[-1][0])
```

**教训**（⭐ 量化工程铁律）：
- **永远不要相信"按文档应该 work"**：OKX API 文档经常与实际行为不符
- **第一次拉数据前，先用 3-5 个 cursor 值矩阵测试 before/after 真实语义**
- **分页循环必须测试"翻到最后一页"**：光看第一页正常不代表分页对（这次就是：第一页正常，第二页重复第一页）
- **建立 cursor 验证工具**：所有 fetcher 都应该接受 `--dry-run` 参数，打印实际拉到的 ts 范围供人工确认

#### Bug 10 综合教训

**写 OKX fetcher 前必做的 3 步验证**（v1.6 流程标准化）：
1. **先用 1 行调用测试参数**：bar 大小写、列数、字段类型 —— 不要看文档猜
2. **用 5 行代码矩阵测试 cursor 语义**：before/after 各自的 4 种组合
3. **加 dry-run 模式**：让 fetcher 打印实际拉到的 ts 范围，肉眼确认不是"假循环"

---

## 3. 架构决策记录（ADR 风格）

### ADR-001：API client 层做方向反转，不让业务层感知

**背景**：OKX K 线接口返回 newest → oldest。

**备选**：
- A. 业务层每次 `reversed()` → 调用点散落 5+ 处
- B. 数据结构统一（market 层反转一次）→ 业务层自然顺序 `[-1]` = 最新

**决策**：B

**后果**：v1.5 Bug 1 一次性修复下游 5 个隐含错误。**所有数据 API 都应该在出口层做方向/格式归一化**。

---

### ADR-002：凭据聚合到单 `.env`，双模式独立

**背景**：原结构有 `OKX_API_KEY` / `OKX_API_SECRET` / `OKX_API_PASSPHRASE`，只能存一组，无法同时持 LIVE + DEMO。

**备选**：
- A. 用两份 `.env`（`.env.live` / `.env.demo`）+ `OKX_ENV` 切换
- B. 单文件 + 前缀聚合：`OKX_LIVE_*` + `OKX_DEMO_*` + `OKX_TRADING_MODE`

**决策**：B

**后果**：
- ✅ 切换模式不需要复制凭据，demo 验证 → live 部署无缝
- ✅ 单文件便于 gitignore + 备份策略统一
- ⚠️ LIVE 和 DEMO 必须严格隔离，不能互相覆盖

---

### ADR-003：Portfolio 对账作为 mandatory 步骤

**背景**：手动开仓 + 系统平仓的混合操作导致 local portfolio 与 OKX 漂移。

**备选**：
- A. 禁止手动操作（不现实）
- B. runner 启动时自动 reconcile，drift 通知
- C. 完全相信本地，不对账

**决策**：B + 手动 `sync_portfolio.py` CLI

**后果**：
- ✅ 凌晨 01:51 手动开仓 + 13:04 手动开 short 都被正确归档，daily_stats 准确
- ✅ drift 立即触发 Telegram 告警
- ⚠️ 每次 runner 启动多 ~3s（拉 OKX positions + history）

---

### ADR-004：通知层独立模块，不嵌入业务逻辑

**背景**：交易流程要不要内联发送通知？

**备选**：
- A. 业务代码直接调 `requests.post(telegram_api)` → 失败阻塞交易
- B. 独立 `notifier.py`，失败不阻塞，去重 + 分类

**决策**：B

**后果**：
- ✅ 通知失败（5min dedup + NoopNotifier fallback）不影响下单
- ✅ 7 类事件（开/平/部分平/错误/日报/心跳/action_result）独立测试
- ✅ Mock Telegram server E2E 7/7 全过

---

### ADR-005：4 策略 + Constitution（明文风控准则）

**背景**：单一 EMA20 策略在震荡市被反复止损。

**备选**：
- A. 单策略 + 调参
- B. 多策略组合 + Constitution 强制规则（杠杆矩阵 / 熔断 / 流动性过滤）

**决策**：B

**策略矩阵**：
- A `EMA20_BREAKOUT`：趋势市右侧
- B `BB_RSI_REVERSION`：震荡市左侧
- C `VOLATILITY_BREAKOUT`：波动率盘整后爆发
- D `FUNDING_RATE_REVERSAL`：资金费率极端反转

**Constitution 关键规则**：
- 杠杆矩阵（BTC/ETH 5-10x 按 ATR 动态，山寨币 3-5x，高波动 0x）
- 不确定性决策树（HOLD 优先 / 追单禁止）
- 熔断冷静期（连亏 3 次 → 30 min cooldown）
- 流动性/黑名单过滤（24h 量 < 5000万 USDT 或 |funding|>0.1% 拦截）

---

## 4. 核心设计原则（从 bug 复盘中提炼）

### 原则 1：抽象边界做归一化

> API client 层 / 数据层 / 通用工具层应该把"外部世界的不一致"在边界处抹平，业务层永远用自然、最常见的形式。

- K 线方向：API client 层反转，业务层 `[-1]` = 最新
- 时间戳：HTTP 层统一 ISO8601 UTC，业务层不感知时区
- 错误处理：utils 层递归 `data[].sCode`，业务层只看 `raise OKXError`

### 原则 2：相同逻辑建抽象函数

> 同一概念在多个调用点出现时，立刻抽函数。否则一处改完另一处忘记，bug 永存。

- `side_to_str()` 统一 buy/sell 翻译
- `portfolio.reconcile_with_okx()` 统一 3 种 reconcile 路径
- `RiskCalculator.calculate_pnl()` 统一 ctVal 处理

### 原则 3：mock 测试无法替代真实端到端

> 凡是涉及"量纲、单位、时序"的逻辑，mock 几乎必漏。必须有真实 E2E 脚本（哪怕是 demo 模式）。

- `scripts/verify_order_chain.py`：信号 → 风控 → 下单 → 持仓 → 平仓
- `scripts/test_connection.py`：公+私 API 连通性
- `scripts/sync_portfolio.py`：手动对账演练

### 原则 4：local cache 必须有 reconcile 兜底

> 任何本地状态（portfolio.json / config.json / cache）都有 drift 风险。**reconcile 不应该是可选优化**。

- Runner 启动第一步调 `reconcile_with_okx()`
- drift 立即通知 + audit log（`state/sync_history.json`）

### 原则 5：凭据永远不进 LLM 上下文

> 见 `docs/SECURITY.md` "LLM 不接触明文" 章节。核心：
- `.env` chmod 600 + gitignore
- 任何 chat / 文档 / 测试中都不能出现真值
- 占位符用 `<your_*_here>` 或 `<port>`

---

## 5. 测试经验

### 测试金字塔现状

- **单元测试**：98/98 ✓（`tests/test_risk.py` + `test_signal.py` + `test_constitution.py`）
- **集成测试**：mock Telegram server E2E 7/7 ✓（`scripts/test_notifier.py`）
- **真实端到端**：`scripts/verify_order_chain.py` + `test_connection.py`（demo 模式）

### 踩过的坑

- **mock 隐藏了 ctVal bug**：测试都是裸数字 `size=1`，没乘 ctVal。**教训：金融测试必须显式写"标的数 = 张数 × ctVal"**
- **mock 隐藏了 K线方向 bug**：测试直接喂 `closes=[100,101,102,...]`，没区分方向。**教训：fixture 应该写真实 OKX 响应（带方向）**
- **5 个 xfail 测试在 bugA/B 修复后被取消**：说明 xfail 是"承认 bug"的合规做法，但要及时清理

### 测试覆盖空白

- ⚠️ 资金费率结算（每 8h）单元测试缺失
- ⚠️ 4 策略 ABCD 端到端信号测试缺失（只有单指标测试）
- ⚠️ portfolio 持久化原子性测试缺失（写一半崩溃场景）

---

## 6. 运维经验

### 6.1 OKX API 调用细节

| 坑 | 现象 | 解决 |
|----|------|------|
| 签名三重错 | 50113 Invalid Sign | 见 Bug P0 |
| 模拟盘 header | 50101 env mismatch | 加 `x-simulated-trading: 1`（实测 `x-simulated-id` 不被识别，见 Bug 0 补充） |
| `bar` 参数大小写 | 51000 Parameter bar error | 1H/1D/1W 大写，1m/5m/15m 小写（见 Bug 10.1） |
| `history-candles` 9 列 | ValueError 8 vs 9 columns | 含 `confirm` 字段，详见 Bug 10.2 |
| 分页 cursor 语义反转 | 第一页正常后面循环重复 | 实测 `after=<ts>` 才是向前翻页，`before` 无效（见 Bug 10.3） |
| posSide 漏传 | posSide required | 双向持仓必传 |
| sCode 漏检 | 只看到 `[1] All operations failed` | 递归 `data[]` |
| 字段废弃 | 54070 Parameter not supported | 改 `attachAlgoOrds` |
| side 翻译 | long/short 拒绝 | 调 place_order 前 `side_to_str()` |
| LIVE/DEMO 硬隔离 | 50101 cross-env | 两套独立账户 + 独立 API key |

### 6.1.1 OKX fetcher 开发铁律（v1.6 沉淀）

> 所有写 OKX fetcher（拉数据）的人都必须遵守：

1. **先用 5 行代码矩阵测 cursor 语义**：before/after × 过去/未来 ts × 2 个 endpoint
2. **第一次拉数据前，探测实际列数**：`len(raw[0])` 不要看文档猜
3. **加 `--dry-run` 模式**：打印实际拉到的 ts 范围，肉眼确认不是"假循环"
4. **复用 `code/backtest/verify_headers.py`** 验证双 header 兼容性（不要假设）

**反例**：V2.1 文档假设 `x-simulated-id` 和 `x-simulated-trading` 都生效，实测只有一个生效。**任何文档假设都要 1 行代码验证后再用**。

### 6.2 环境与部署

- **systemd service 不继承 bash env**：必须在 unit file 加 `Environment=KEY=VALUE`
- **bash `run.sh` 加载 `.env` 会覆盖外部 inline 传参**：测试时用单独 Python 子进程
- **NO_PROXY 来源不一定是 `~/.bashrc`**：可能是 `~/.config/systemd/user/<service>.service`，改时要两处都改
- **OKX V5 模拟盘独立子账户**：起始虚拟资金（1 BTC + 100 OKB + 5000 USDT + 1 ETH），不能用 LIVE key 替代

### 6.3 Cron 调度

- **OpenClaw cron 子代理冷启动 ~2m42s**：任何依赖"实时分钟"判定的逻辑要容忍 3 分钟窗口
- **`_is_trade_time()` 容忍窗口 = 3 分钟**：runner.py 默认值，单元测试覆盖
- **`delivery.announce` 必须显式给 channel + to**：漏 `to` 报 `Delivering to Telegram requires target`
- **高频任务用 Linux crontab**（每 5min Runner），LLM 任务用 OpenClaw cron（日报/分析）
- **`last_workflow_result.json` 必须每次落盘**：watchdog 依赖，缺失会一直误告警

---

## 7. 未解的待办与未来风险

### ⚠️ 已知待办

1. **资金费率结算测试缺失**：每 8h 结算逻辑没单测，依赖 demo 模式观察
2. **4 策略 ABCD 端到端测试缺失**：只有单指标测试，组合信号没覆盖
3. **portfolio 持久化原子性**：写一半崩溃场景未测试（应该有 write-to-temp + rename）
4. **实盘账户入金**：当前 demo 跑，实盘余额 ≈ 0，无法真实验证下单链路
5. **OKX secretKey 轮换**：Telegram 历史已暴露，建议 24h 内禁用旧 key

### 🚨 未来风险

| 风险 | 触发条件 | 缓解策略 |
|------|----------|----------|
| OKX API V6 升级 | OKX 弃用 V5 | 关注 changelog，模块化封装减少改动半径 |
| 极端行情熔断失效 | BTC 单日 -30% | Constitution 加 "日亏损 5% 全停" 规则 |
| 资金费率长期负 | 多年熊市 | Strategy D 适配反向（long bias 改 short bias） |
| Telegram API 限流 | 高频告警 | notifier.py 已实现 5min dedup + 批量推送 |
| Demo 模式与 live 行为差异 | OKX 内部测试 | verify_order_chain.py 必须两套都跑 |
| 多用户共用 .env | Nixil 多人协作 | 当前单用户，未来加 mode 隔离（live/demo 不同文件） |

---

## 8. 经验教训的元教训

> 如果只能从 v1.0 → v1.5 这两周学一件事，那件事是：

**金融系统的 bug 不是 bug，是事故。** 一行 K 线方向错误可以让系统在 13 分钟内"自动平仓"一笔不该平的仓位；ctVal 漏乘可以让 PnL 报告虚高 25 倍；sCode 不递归可以让"余额不足"看起来像"参数错误"。每一个看起来"小"的 bug，在真实资金上都可能放大成事故。

所以 v1.5 之后的优先级排序：

1. **真实 E2E 测试 > mock 单元测试**（mock 隐藏了所有 P0 bug）
2. **本地状态 reconcile > 状态持久化**（cache 永远会漂移）
3. **运维可观测性 > 功能完整性**（watchdog + 通知是风控最后一公里）
4. **架构边界归一化 > 业务逻辑正确**（边界错了业务再对也错）

---

_文档维护：每次发现新 bug 或重要 ADR 时更新本文件。_
_最后更新：2026-07-13 23:02（v1.6 归档，新增 Bug 10 + Header 实测 + OKX fetcher 开发铁律）_