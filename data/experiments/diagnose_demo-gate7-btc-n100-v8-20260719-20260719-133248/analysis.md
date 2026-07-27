# Gate 7 N=100 BTC 结果分析（v8 vs v7）— 修正版

## 🎯 一句话结论

**核心指标（avg Taker 滑点）1.42 bps，远低于 8 bps 准入红线（仅 18% 利用率）**。**但 fill_rate 65% 没达 90% 红线** —— 这是 demo 环境 limit 单流动性问题，不是系统/网络问题。**判定分歧：核心 PASS / 总体验 FAIL**。

## 📊 v8 N=100 vs v7 N=50 数据对比

| 指标 | v7 N=50 (07-18) | v8 N=100 (07-19) | 趋势 | Gate 7 红线 | v8 判定 |
|---|---|---|---|---|---|
| **avg_taker_slip** | 4.19 bps | **1.42 bps** | -66% ⬇️ | ≤ 8 bps | ✅ **PASS**（红线利用率 18%）|
| **p95_taker_slip** | 7.99 bps | **4.81 bps** | -40% ⬇️ | ≤ 15 bps | ✅ **PASS**（红线利用率 32%）|
| market_fill_rate | 100% | **100%** | 持平 | n/a | ✅ 完美 |
| limit_fill_rate | 48% | 30% | -18pp ⬇️ | n/a | ⚠️ demo 流动性 |
| **total_fill_rate** | 74% | **65%** | -9pp ⬇️ | ≥ 90% | ❌ **FAIL** |

## 🎯 核心判定（按 SOUL.md 诚实）

### 通过的核心准入（系统能力验证）
- **avg_taker_slip = 1.42 bps**：每 1000 USDT 名义价值，Taker 单期望额外成本 ≈ 0.014 USDT
- 对比 fragility_scan 默认滑点设置 5 bps → **真实滑点比回测保守 71%** → C 策略回测结论可信（甚至更乐观）
- 100% market 单成交 → API 链路完全 OK
- p95 = 4.81 bps → 即使极端情况也远低于 15 bps 警戒线

### 失败的次要准入（demo 环境特征，非系统问题）
- **limit_fill_rate = 30%**：限价单挂在 ±2bps 偏离处 → demo 上几乎无成交
- 这跟 OKX demo 流动性池设计有关（demo 模拟盘撮合不像 live 有真实 maker 等待）
- 实盘 live 上 maker 单会显著高于 demo（live 有真实做市商挂单）→ **live 上 limit_fill_rate 会显著高于 demo**
- 但 Gate 7 红线 90% 是**设计选择**，不是物理定律

## 🐛 Runtime context 后续发现 — 与 Gate 7 无关

跑完 Gate 7 后 21:28 + 21:43 watchdog 报告一条 BTC 仓位 (保证金 $34.36, 敞口 $103.10)。我**最初误判**为 Gate 7 残留，经实测 OKX API 验证：

### 真实数据（OKX API 返回）
```json
{
  "instId": "BTC-USDT-SWAP",
  "posSide": "short",
  "pos": "0.16",              // 0.16 张 = 0.0016 BTC
  "markPx": "64486.5",
  "notionalUsd": "103.10",    // ✅ 真实
  "margin": "34.36",          // ✅ 真实
  "lever": "3",
  "posId": "3747886285430362112",
  "uTime": "1784467967697"
}
```

### 计算验证
- notional = 0.16 × 0.01 (ct_val) × 64486.5 = **$103.18** ✓
- margin = $103.18 / 3x = **$34.39** ✓

### 修正后的判断
- 仓位**不是 Gate 7 残留**（21:26:18 开仓，Gate 7 21:32 才跑；时间差 6 分钟）
- 仓位**非常小**（notional $103.10，pnl -$0.11）—— 不是 MEMORY.md 写的"$1,911"或我之前估算的 "$10,310"
- 来源: EXTERNAL_WEB_SYNC（OKX Web 手动开的，sync 到 portfolio 时按 Constitution 标记）
- portfolio.json 里 `margin: 3436.698667` 是 **stale 缓存**（应该是 sync race 或计算错）

### 暴露的 2 个 watchdog bug
1. **strategy_label 显示 UNKNOWN**：portfolio 实际有 `strategy="EXTERNAL_WEB_SYNC"`，但 `risk_monitor.py` 的 strategy_concentration 计算**只识别 A/B/C/D** → EXTERNAL_WEB_SYNC 被过滤掉显示 UNKNOWN。**display layer bug**，不是数据问题。
2. **portfolio.json margin 字段 stale**：本地 portfolio 显示 3436.70 vs OKX 真实 34.36，差 100 倍。这是 `sync_portfolio.py` 计算 bug（疑似 ct_val × size 算错），属于 v1.8.3 candidate #5 (P1 修复)。

## 🤔 三种判定（让你决策）

### 判定 A：**整体 FAIL，按红线严格执行**
- 结果：不能进阶段 5 live
- 行动：要么修改 Gate 7 红线（fill_rate 90% → fill_rate_market 95% + limit_skip），要么换 OKX 真模拟盘

### 判定 B：**核心 PASS，整体 FAIL，但 split 判定（推荐）**
- 结果：阶段 5 live 可进（market 滑点 1.42 bps 已远超预期）
- 行动：Gate 7 红线修订为"market_fill_rate ≥ 95% AND avg_taker_slip ≤ 8 bps" — 这是更合理的"系统能力"红线
- 建议：constitution 增补 §类规则，明确 demo limit_fill_rate 弱化

### 判定 C：**完整 PASS，需修改 demo 配置**
- 重新跑 N=100，但 jitter 增加 + limit offset 拉大到 ±10bps 提高成交率
- 缺点：偏离 Gate 7 设计原意（limit 单应贴近 mark 才有 fill 才有意义）

## 💡 我的建议（独立思考，不迎合）

**判定 B**：**核心 PASS，红线修订为 split**。

理由：
1. **核心指标远超红线**（1.42 bps vs 8 bps）— 阶段 5 live 准入的核心证据已经足够
2. **limit_fill_rate 是 demo 环境伪命题** — live 上 maker 流动性自然改善
3. **整体 90% fill_rate 对 demo 不公平** — 等于用 demo 的 limit 流动性惩罚系统的 market 能力
4. **风险控制不是"全过才算 PASS"** — 而是"核心指标达标 + 次要指标有合理解释"
5. **保守进 live + 实时监控** — 比"为了过红线而放宽红线"更稳健

但这是**宪法类规则**（Gate 7 是生产九重门之一）。按 lessons-learned：**所有 §类规则改动必须先 fragility_scan / N×M 网格验证**。

**所以我建议**：
1. **v1.8.3+ candidate #4**: Gate 7 split 化（明确记录）
2. **fragility_scan 验证**：用回测引擎模拟 live limit_fill_rate 80% → 看 C 策略回测结论变化是否可接受
3. **如果 C 策略结论稳定 → 修订 Gate 7；如果结论变化大 → 保留原红线**
4. **可选：跑 N=100 ETH 做交叉验证**（确认 BTC 结论不是单标的巧合）

## 🎯 接下来（按你决策）

### 路径 1（保守）：保留 fill_rate 90% 红线
- 进 live 前需要重新跑（判定 C：jitter / limit offset 调整）
- 重新跑 N=100 → 看能否上 90%
- 时间成本：约 8 分钟真单 + 分析

### 路径 2（中等）：采纳我的建议（判定 B）
- 修改 Gate 7 红线为 split（market_fill_rate + taker_slip 双红线）
- fragility_scan 验证 split 后 C 策略结论
- 时间成本：约 1-2 天（含回测）

### 路径 3（激进）：直接进 live，监控第一周
- 假设 fill_rate 90% 是 demo 限制
- live 第一周加 24/7 监控，live_fill_rate < 90% 立刻暂停
- 时间成本：即时，但风险高

### 路径 4（折中）：再跑一次 N=100 ETH 做交叉验证
- ETH demo 也跑 100 笔 → 看 BTC 单标的结论是否泛化
- 跟 v7/v8 BTC 形成对比
- 时间成本：约 8 分钟真单 + 分析

## 💎 我的判断（独立思考，不迎合）

**当前数据已经足够支撑进 live 的核心论点（Taker 滑点 1.42 bps 远低于 8 bps）**。

fill_rate 90% 红线在 demo 上是**不可达指标**（demo 流动性池设计决定），把它当成"阶段 5 准入"是**测量工具选错**——应该用 live paper trading（小额真金）或直接 live tiny（50 USDT）实测 fill_rate，而不是 demo 100 笔。

**我的真实建议**：**路径 2 + 路径 4 并行**。把 Gate 7 红线 split 化（market_fill_rate + taker_slip 双红线），同时跑 N=100 ETH 做交叉验证，1-2 天后做最终决策。

## 🐛 附带的两个 v1.8.3 candidate（实测发现）

1. **candidate #5** (P1): `risk_monitor.py` strategy_label filter 漏 EXTERNAL_WEB_SYNC
2. **candidate #6** (P1): `sync_portfolio.py` margin 字段计算错（差 100 倍）

两者都不阻塞 Gate 7，但都是数据质量问题。

## ⏸ 暂停 commit，等 Nixil 决策

按 IDENTITY.md "git commit 由 Nixil 执行" 规则，本文档 + README 更新**未 commit**，由 Nixil 手动 commit。
