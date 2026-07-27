# Phase 4 Gate 7 · DEMO 滑点抽样报告

**标的**: `BTC-USDT-SWAP`
**时间**: 2026-07-19 13:32:48 UTC
**总笔数**: 100（市价 50% + 限价 50%）
**成交率**: 65.0% (65 / 100)

## 🚦 Release Gate 判定

- ✅ **avg_taker_slip_le_8bps**: `True`
- ✅ **p95_taker_slip_le_15bps**: `True`
- ❌ **fill_rate_ge_90pct**: `False`

## 📊 按订单类型统计

| 指标 | 市价 (Taker) | 限价 (Maker) |
|---|---|---|
| 成交笔数 | 50.00 | 15.00 |
| 成交率 | 1.00 | 0.30 |
| 平均绝对滑点 (bps) | 1.42 | 0.61 |
| 中位绝对滑点 | 0.90 | 0.00 |
| p95 绝对滑点 | 4.81 | 2.59 |
| p99 绝对滑点 | 5.14 | 2.59 |
| 最大绝对滑点 | 5.14 | 2.59 |
| 平均延迟 (ms) | -206.76 | -94.47 |
| p95 延迟 (ms) | 160.00 | 402.00 |

## ⚠️ 失败明细 (35 笔)

- idx=1 limit/buy: no fill
- idx=5 limit/buy: no fill
- idx=9 limit/buy: no fill
- idx=11 limit/sell: no fill
- idx=13 limit/buy: no fill
- idx=17 limit/buy: no fill
- idx=21 limit/buy: no fill
- idx=25 limit/buy: no fill
- idx=27 limit/sell: no fill
- idx=29 limit/buy: no fill
- ...（共 35 笔失败，详见 records.json）
