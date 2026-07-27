# Phase 4 Gate 7 · DEMO 滑点抽样报告

**标的**: `BTC-USDT-SWAP`
**时间**: 2026-07-18 06:33:26 UTC
**总笔数**: 100（市价 50% + 限价 50%）
**成交率**: 0.0% (0 / 100)

## 🚦 Release Gate 判定

- ❌ **avg_taker_slip_le_8bps**: `False`
- ❌ **p95_taker_slip_le_15bps**: `False`
- ❌ **fill_rate_ge_90pct**: `False`

## 📊 按订单类型统计

| 指标 | 市价 (Taker) | 限价 (Maker) |
|---|---|---|
| 成交笔数 | 0.00 | 0.00 |
| 成交率 | - | - |
| 平均绝对滑点 (bps) | - | - |
| 中位绝对滑点 | - | - |
| p95 绝对滑点 | - | - |
| p99 绝对滑点 | - | - |
| 最大绝对滑点 | - | - |
| 平均延迟 (ms) | - | - |
| p95 延迟 (ms) | - | - |

## ⚠️ 失败明细 (100 笔)

- idx=0 market/buy: 'list' object has no attribute 'get'
- idx=1 limit/buy: 'list' object has no attribute 'get'
- idx=2 market/sell: 'list' object has no attribute 'get'
- idx=3 limit/sell: 'list' object has no attribute 'get'
- idx=4 market/buy: 'list' object has no attribute 'get'
- idx=5 limit/buy: 'list' object has no attribute 'get'
- idx=6 market/sell: 'list' object has no attribute 'get'
- idx=7 limit/sell: 'list' object has no attribute 'get'
- idx=8 market/buy: 'list' object has no attribute 'get'
- idx=9 limit/buy: 'list' object has no attribute 'get'
- ...（共 100 笔失败，详见 records.json）
