# Phase 4 Gate 7 · DEMO 滑点抽样报告

**标的**: `ETH-USDT-SWAP`
**时间**: 2026-07-19 14:15:28 UTC
**总笔数**: 100（市价 50% + 限价 50%）
**成交率**: 50.0% (50 / 100)

## 🚦 Release Gate 判定

- ✅ **avg_taker_slip_le_8bps**: `True`
- ✅ **p95_taker_slip_le_15bps**: `True`
- ❌ **fill_rate_ge_90pct**: `False`

## 📊 按订单类型统计

| 指标 | 市价 (Taker) | 限价 (Maker) |
|---|---|---|
| 成交笔数 | 50.00 | 0.00 |
| 成交率 | 1.00 | - |
| 平均绝对滑点 (bps) | 0.14 | - |
| 中位绝对滑点 | 0.03 | - |
| p95 绝对滑点 | 0.64 | - |
| p99 绝对滑点 | 2.40 | - |
| 最大绝对滑点 | 2.40 | - |
| 平均延迟 (ms) | -73.28 | - |
| p95 延迟 (ms) | 219.00 | - |

## ⚠️ 失败明细 (50 笔)

- idx=1 limit/buy: no fill
- idx=3 limit/sell: no fill
- idx=5 limit/buy: no fill
- idx=7 limit/sell: no fill
- idx=9 limit/buy: no fill
- idx=11 limit/sell: no fill
- idx=13 limit/buy: no fill
- idx=15 limit/sell: no fill
- idx=17 limit/buy: no fill
- idx=19 limit/sell: no fill
- ...（共 50 笔失败，详见 records.json）
