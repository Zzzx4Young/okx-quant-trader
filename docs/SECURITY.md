# OKX 凭据安全隔离方案（v1.2 双模式）

## 核心目标

**不让 LLM 看到明文密钥，同时程序能正常使用凭据**

支持双模式（实盘 + 模拟）凭据管理。

---

## 方案架构

```
docs/KEY.md  (用户维护) → .env (程序使用) → 环境变量 → _http.py → OKX API
   │                          │
   │                          │
   └─ OKX_LIVE_*              └─ 按 OKX_TRADING_MODE 选 OKX_LIVE_*
      OKX_DEMO_*                                或 OKX_DEMO_*
      OKX_TRADING_MODE
```

---

## 双模式凭据

### 设计动机

OKX V5 的实盘和模拟盘（Demo Trading）是**两套独立的 API Key**：
- 实盘 key 在主账户创建
- 模拟 key 在 https://www.okx.com/demotrading 子账户创建
- 两者 api_key / secret / passphrase **完全独立**

所以必须保存两组凭据，并通过 `OKX_TRADING_MODE` 切换当前激活的那一组。

### 变量命名约定

| 变量名 | 含义 |
|--------|------|
| `OKX_LIVE_API_KEY` / `OKX_LIVE_API_SECRET` / `OKX_LIVE_PASSPHRASE` | 实盘凭据 |
| `OKX_DEMO_API_KEY` / `OKX_DEMO_API_SECRET` / `OKX_DEMO_PASSPHRASE` | 模拟凭据 |
| `OKX_TRADING_MODE` | 当前激活模式：`live` 或 `demo`（默认 `demo`） |

### 旧版兼容

为不破坏既有调用，保留旧变量作为回退：

| 旧变量 | 新变量（demo 模式） |
|--------|---------------------|
| `OKX_API_KEY` | `OKX_DEMO_API_KEY` |
| `OKX_API_SECRET` | `OKX_DEMO_API_SECRET` |
| `OKX_PASSPHRASE` | `OKX_DEMO_PASSPHRASE` |
| `OKX_FLAG` | （自动按 mode 推断） |

**回退规则**：仅在 `mode=demo` 且 `OKX_DEMO_*` 缺失时才用旧变量兜底。迁移完成后建议删除旧行。

---

## 工作流程

### 1. 配置存储（用户侧）

**docs/KEY.md** - 用户维护的配置文件

```bash
# ─── 实盘凭据（LIVE） ──────
OKX_LIVE_API_KEY=<key>
OKX_LIVE_API_SECRET=<secret>
OKX_LIVE_PASSPHRASE=<实盘密钥>

# ─── 模拟凭据（DEMO） ──────
OKX_DEMO_API_KEY=<demo key>
OKX_DEMO_API_SECRET=<demo secret>
OKX_DEMO_PASSPHRASE=<demo passphrase>

OKX_TRADING_MODE=demo
```

- 用户手动填写或更新
- 配置完成后可以移除（程序不依赖此文件）
- 将来如需更新配置，从 `docs/KEY.md.template` 重新创建
- **LLM 不直接读取此文件的内容**

### 2. 配置转换（一次性）

```bash
./run.sh scripts/convert_env.py
```

功能：
- 读取 `docs/KEY.md`
- 生成 `.env` 文件（环境变量格式，分组清晰）
- 自动收紧权限到 `0600`
- 检查当前 mode 对应凭据是否齐全
- LLM 只需要知道"运行转换脚本"，不需要知道文件内容

### 3. 安全隔离（运行时）

**run.sh** - 启动脚本（关键）

```bash
# 加载 .env
# 校验 OKX_TRADING_MODE 对应凭据
# 导出供子进程使用
```

**隔离机制：**

| 层级 | 隔离方式 | LLM 能看到吗 |
|------|---------|-------------|
| 配置源 | docs/KEY.md | ✗ 主动不读取 |
| 运行配置 | .env | ✗ 仅 chmod 600，LLM 不主动读取 |
| 程序使用 | 环境变量 | ✗ 通过 os.getenv() 读取 |
| API 调用 | HTTP headers | ✗ 程序内部使用 |

### 4. 程序使用（自动）

`code/_http.py` 的解析顺序：

```python
# 1. 显式参数 (api_key/secret_key/passphrase/mode) — 覆盖
# 2. env OKX_TRADING_MODE → 选前缀 OKX_LIVE_* 或 OKX_DEMO_*
# 3. (仅 demo 模式) 兜底读取 OKX_API_*
```

---

## 使用示例

### 双模式切换

```bash
# 默认是 demo（OKX_TRADING_MODE=demo），无需额外操作
./run.sh run

# 切到实盘：编辑 .env → OKX_TRADING_MODE=live → 重启
sed -i 's/^OKX_TRADING_MODE=.*/OKX_TRADING_MODE=live/' okx/.env
./run.sh run
```

### LLM 端（无需知道密钥）

```bash
# 运行任何 Python 程序，密钥按当前 mode 自动加载
./run.sh scripts/test_connection.py
./run.sh code/runner.py
```

### 人工端（配置更新）

```bash
# 1. 从模板创建配置文件（首次或重新配置时）
cp docs/KEY.md.template docs/KEY.md
vim docs/KEY.md

# 2. 重新生成 .env
./run.sh scripts/convert_env.py

# 3. 测试配置
./run.sh scripts/test_connection.py

# 4. （强烈建议）移除包含明文的 KEY.md
rm docs/KEY.md
```

---

## 安全保障

### 1. 多层隔离

- LLM 读取控制：LLM 主动不读取 KEY.md 或 .env
- 文件权限：`.env` 自动 `chmod 600`
- 环境变量：凭据只在进程内存中存在

### 2. 最小权限原则

- LLM 只知道：需要运行 `./run.sh` 程序
- LLM 不知道：API Key / Secret / Passphrase 的具体值
- 程序知道：从环境变量读取凭据并使用

### 3. 可审计性

```bash
# 检查 .env 是否存在 + 权限
ls -la .env     # 期望 -rw------- (0600)

# 检查环境变量是否加载（不显示值）
env | grep OKX_ | sed 's/=.*/=***/'

# 测试配置（验证 mode 选择 + 凭据齐全）
./run.sh scripts/test_connection.py
```

---

## 优势

✓ **零泄露**：LLM 不接触明文凭据
✓ **自动化**：程序自动从环境变量读取
✓ **双模式**：同套代码支持 live / demo 无缝切换
✓ **零迁移**：旧 OKX_API_* 仍可用，逐步迁移
✓ **标准化**：使用 .env 格式，符合业界惯例

---

## 流程总结

```
用户更新 docs/KEY.md (LIVE + DEMO 两组)
      ↓
./run.sh scripts/convert_env.py (生成 .env)
      ↓
OKX_TRADING_MODE=live|demo 选定当前模式
      ↓
./run.sh scripts/test_connection.py  (测试)
      ↓
./run.sh  (运行交易策略)
      ↓
程序按 mode 选对应 OKX_LIVE_* / OKX_DEMO_* → 调用 OKX API
```

---

**核心思想：LLM 只负责"调程序"，不负责"传密钥"**
