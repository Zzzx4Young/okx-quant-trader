# Fragility Scan: a-btc-wf-3m1m_w08

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-06-23T15:00:00+00:00 → 2025-09-21T15:00:00+00:00 (ms: 1750690800000 → 1758466800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 13.906%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -1.56% | -0.654 | +5.40% | 4 |  50.0% | $72.31 | $63.14 | ❌ |
| 10 | -2.57% | -1.017 | +6.51% | 4 |  50.0% | $143.87 | $62.68 | ❌ |
| 15 | -5.42% | -1.826 | +9.29% | 4 |  25.0% | $223.22 | $58.70 | ❌ |

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
    --buy-hold-ret 13.906 \
    --name a-btc-wf-3m1m_w08
```
