# Phase 4 Gate 7 · DEMO 滑点抽样报告

**标的**: `BTC-USDT-SWAP`
**时间**: 2026-07-18 06:42:17 UTC
**总笔数**: 20（市价 50% + 限价 50%）
**成交率**: 70.0% (14 / 20)

## 🚦 Release Gate 判定

- ✅ **avg_taker_slip_le_8bps**: `True`
- ✅ **p95_taker_slip_le_15bps**: `True`
- ❌ **fill_rate_ge_90pct**: `False`

## 📊 按订单类型统计

| 指标 | 市价 (Taker) | 限价 (Maker) |
|---|---|---|
| 成交笔数 | 10.00 | 4.00 |
| 成交率 | 1.00 | 0.40 |
| 平均绝对滑点 (bps) | 5.42 | 0.43 |
| 中位绝对滑点 | 5.80 | 0.13 |
| p95 绝对滑点 | 8.81 | 1.46 |
| p99 绝对滑点 | 8.81 | 1.46 |
| 最大绝对滑点 | 8.81 | 1.46 |
| 平均延迟 (ms) | 168.40 | 243.00 |
| p95 延迟 (ms) | 193.00 | 394.00 |

## ⚠️ 失败明细 (6 笔)

- idx=1 limit/buy: no fill
- idx=5 limit/buy: no fill
- idx=9 limit/buy: no fill
- idx=13 limit/buy: no fill
- idx=17 limit/buy: no fill
- idx=19 limit/sell: no fill
