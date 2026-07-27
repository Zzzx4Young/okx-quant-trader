# Fragility Scan: a-btc-wf-3m1m_w11

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-09-21T15:00:00+00:00 → 2025-12-20T15:00:00+00:00 (ms: 1758466800000 → 1766242800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -23.677%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +5.96% | +1.595 | +5.30% | 10 |  50.0% | $122.90 | $130.85 | ✅ |
| 10 | -1.43% | -0.269 | +6.57% | 10 |  50.0% | $249.48 | $122.69 | ✅ |
| 15 | -2.92% | -0.624 | +7.46% | 10 |  50.0% | $371.46 | $121.69 | ✅ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **3 / 3** (100%)

→ 所有 cell viable。策略对成本不敏感。**可以直接进入下一阶段评估**。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy A \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15 \
    --fee-bps 5.0 \
    --leverage 5 \
    --buy-hold-ret -23.677 \
    --name a-btc-wf-3m1m_w11
```
