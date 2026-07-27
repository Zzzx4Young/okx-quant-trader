# Fragility Scan: a-btc-wf-3m1m_w07

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-05-24T15:00:00+00:00 → 2025-08-22T15:00:00+00:00 (ms: 1748098800000 → 1755874800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 6.837%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -4.29% | -0.876 | +10.28% | 12 |  41.7% | $194.32 | $158.54 | ❌ |
| 10 | -7.14% | -1.488 | +12.60% | 12 |  41.7% | $382.83 | $155.70 | ❌ |
| 15 | -9.93% | -1.988 | +14.99% | 12 |  41.7% | $565.66 | $152.92 | ❌ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **0 / 3** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy A \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15 \
    --fee-bps 5.0 \
    --leverage 5 \
    --buy-hold-ret 6.837 \
    --name a-btc-wf-3m1m_w07
```
