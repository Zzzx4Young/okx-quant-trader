# Phase 4 Gate 7 · DEMO 滑点抽样报告

**标的**: `BTC-USDT-SWAP`
**时间**: 2026-07-18 06:51:12 UTC
**总笔数**: 50（市价 50% + 限价 50%）
**成交率**: 74.0% (37 / 50)

## 🚦 Release Gate 判定

- ✅ **avg_taker_slip_le_8bps**: `True`
- ✅ **p95_taker_slip_le_15bps**: `True`
- ❌ **fill_rate_ge_90pct**: `False`

## 📊 按订单类型统计

| 指标 | 市价 (Taker) | 限价 (Maker) |
|---|---|---|
| 成交笔数 | 25.00 | 12.00 |
| 成交率 | 1.00 | 0.48 |
| 平均绝对滑点 (bps) | 4.19 | 2.26 |
| 中位绝对滑点 | 4.55 | 1.83 |
| p95 绝对滑点 | 7.99 | 5.80 |
| p99 绝对滑点 | 8.48 | 5.80 |
| 最大绝对滑点 | 8.48 | 5.80 |
| 平均延迟 (ms) | 186.12 | 343.17 |
| p95 延迟 (ms) | 200.00 | 1453.00 |

## ⚠️ 失败明细 (13 笔)

- idx=1 limit/buy: no fill
- idx=5 limit/buy: no fill
- idx=9 limit/buy: no fill
- idx=13 limit/buy: no fill
- idx=17 limit/buy: no fill
- idx=21 limit/buy: no fill
- idx=25 limit/buy: no fill
- idx=29 limit/buy: no fill
- idx=33 limit/buy: no fill
- idx=37 limit/buy: no fill
- ...（共 13 笔失败，详见 records.json）
