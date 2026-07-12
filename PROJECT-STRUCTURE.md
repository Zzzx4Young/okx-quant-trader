# OKX 量化交易系统 — 项目结构说明

> 生成时间：2026-07-10 | 项目版本：v1.1.0（P0 重构后）

---

## 目录总览

```
okx/
├── __init__.py                # 包根，__version__ = "1.1.0"
├── README.md                  # 用户文档（5 分钟上手）
├── PROJECT-STRUCTURE.md       # 本文件
├── run.sh                     # 启动脚本：加载 .env + 透传 Python
├── .env                       # API 凭据（不入版本控制）
├── .gitignore                 # 忽略 .env / __pycache__ / logs/*.log
│
├── code/                      # 核心代码包（okx.code）
├── scripts/                   # 运维工具脚本
├── tests/                     # 单元测试
├── prompts/                   # AI 决策 prompt
├── docs/                      # 技术文档
├── state/                     # 运行时状态
└── logs/                      # 交易日志
```

---

## code/ — 核心代码包

| 文件 | 行数 | 说明 |
|------|------|------|
| `__init__.py` | 70 | 包初始化，暴露顶层 API + `cli` 模块 |
| `_http.py` | 110 | 底层 `HTTPClient`：签名、JSON、重试、代理（拆出避免循环导入） |
| `client.py` | 65 | `OKXClient`：聚合所有 API 子模块（market/trade/account/...） |
| `cli.py` | 175 | 唯一 CLI 入口：`status / run / stop / resume / close-all / summary` |
| `auth.py` | 72 | OKX API v5 HMAC-SHA256 签名核心 |
| `utils.py` | 98 | 通用工具：错误处理、类型转换 |
| `config.py` | 238 | `Config` 单例：加载 `state/config.json`，提供类型化 property |
| `market.py` | 198 | 市场数据（行情、K线、订单簿、资金费率） |
| `public.py` | 244 | 公开数据（交易对信息、未平仓量、保险基金） |
| `trade.py` | 532 | 交易（下单、撤单、改单、批量） |
| `account.py` | 353 | 账户（余额、持仓、杠杆设置） |
| `asset.py` | 261 | 资金（充值、提币、划转） |
| `subaccount.py` | 123 | 子账户 |
| `portfolio.py` | 283 | 持仓状态管理 + 每日统计 + 熔断判定 |
| `logger.py` | 258 | 交易日志（`logs/trades/YYYY-MM-DD.csv`） |
| `risk.py` | 309 | `RiskCalculator`：2% 本金风险、ATR 止损、净盈亏比校验、杠杆硬上限 |
| `signal.py` | 590 | `SignalEngine`：EMA20 策略 + BB+RSI 策略 + 5 个技术指标辅助函数 |
| `runner.py` | 698 | `Runner`：交易周期调度（前置风控 → 平仓 → 信号检测 → 下单 → 状态更新） |

**包导入**：所有内部模块用相对导入（`from .client import OKXClient`），无 `sys.path` 黑魔法。

---

## scripts/ — 运维工具

| 文件 | 行数 | 说明 |
|------|------|------|
| `convert_env.py` | 65 | 将 `docs/KEY.md` 转换为 `.env` |
| `verify_env.py` | 50 | 验证 `.env` 是否正确加载（无网络请求） |
| `test_connection.py` | 130 | API 连通性 + 签名验证测试 |

**调用**：`./run.sh scripts/xxx.py`（run.sh 自动解析相对路径）

---

## tests/ — 单元测试

| 文件 | 行数 | 说明 |
|------|------|------|
| `__init__.py` | 0 | 包标记 |
| `test_risk.py` | — | `RiskCalculator` 覆盖（盈亏比、保底、净盈亏、杠杆拦截、保证金不足） |
| `test_signal.py` | — | `SignalEngine` 辅助函数（`_ema` / `_rsi` / `_atr` / `_bollinger_bands` / `_linear_slope`） |

**调用**：`pytest tests/ -v`

---

## prompts/ — AI 决策 prompt

| 文件 | 说明 |
|------|------|
| `JOB-DISCIPLINE.md` | 角色定义：定量规则驱动、零情绪、链式思考 |
| `trade-rule.md` | 决断准则：市场环境分类、动态杠杆矩阵、优先级 |

**为什么单列**：`docs/` 给人看，`prompts/` 给 LLM 看，避免 LLM 误把技术文档当 prompt 加载。

---

## docs/ — 技术文档

| 文件 | 行数 | 说明 |
|------|------|------|
| `OKX-API-v5-Trading-Documentation.md` | 436 | OKX API v5 集成参考 |
| `WORKFLOW.md` | 277 | 交易工作流定义 + 异常处理 + 恢复机制 |
| `SIGNALS.md` | 166 | 交易信号定义（策略 A 激活，策略 B 预留） |
| `SECURITY.md` | 259 | 凭据安全隔离方案 |
| `examples/basic_usage.py` | 60 | API 使用示例（market / account / trade） |

---

## state/ — 运行时状态

| 文件 | 说明 |
|------|------|
| `config.json` | 交易配置（时间框架、策略参数、风控阈值、emergency_stop） |
| `portfolio.json` | 持仓快照 + 每日统计 |
| `last_workflow_result.json` | 最近一次工作流执行结果（debug 用） |

`config.json` 变化会触发 `Config` 持久化（`emergency_stop.setter` 等）。

---

## logs/ — 交易日志

`logs/trades/YYYY-MM-DD.csv` 由 `logger.py` 生成，**唯一真实成交记录**。

---

## 数据流

```
docs/KEY.md
  → scripts/convert_env.py
    → .env
      → run.sh (加载环境变量)
        → Python 进程
          ↓
   code/_http.py (HTTPClient) ←→ OKX API v5
          ↓
   code/client.py (OKXClient) 聚合子模块
          ↓
   market / trade / account / ...
          ↓
   code/signal.py (SignalEngine) ← 市场数据
          ↓
   code/risk.py (RiskCalculator) ← 信号 + 余额
          ↓
   code/runner.py (Runner) → trade.place_order
          ↓
   code/portfolio.py → state/portfolio.json
   code/logger.py    → logs/trades/YYYY-MM-DD.csv
   code/cli.py       ← OpenClaw Heartbeat / Cron 调用
```

---

## 关键设计

1. **包结构**：`okx/` + `okx/code/` 都是合法 Python 包，从父目录运行即可 `from okx.code import OKXClient`
2. **凭据隔离**：`run.sh` 加载 `.env` → shell 环境变量 → `os.getenv` 读取
3. **统一入口**：CLI 唯一入口 `cli.py`，业务核心 `Runner.run()`
4. **风控前置**：`runner.py` 在下单前强制 `RiskCalculator` 校验
5. **状态持久化**：`config.json` / `portfolio.json` 自动 reload
6. **OpenClaw 集成**：`cli.py` 提供 status / run / stop / resume / close-all 5 个 action

---

## 变更记录

- **v1.1.0（2026-07-10）P0 重构**
  - 删除 3 个并行工作流入口（`workflow.py` / `run_workflow.py` / `run_workflow_offline.py`），统一为 `cli.py`
  - 合并 `client.py` + `client_okx.py`，拆出 `HTTPClient` 到 `_http.py`（解决循环导入）
  - 修 `__init__.py` 用相对导入，废弃 `bootstrap.py` 和所有 `sys.path` 黑魔法
  - 重分类目录：`scripts/` / `tests/` / `prompts/` / `docs/examples/`
  - 删 `setup.py`（死代码，依赖从未 install）
- **v1.0.0（2026-06-28）初版**
