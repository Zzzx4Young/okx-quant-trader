# Fragility Scan: a-btc-wf-3m1m_w03

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-01-24T15:00:00+00:00 → 2025-04-24T15:00:00+00:00 (ms: 1737730800000 → 1745506800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -11.993%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +2.58% | +0.604 | +7.01% | 9 |  55.6% | $110.12 | $120.36 | ✅ |
| 10 | -1.68% | -0.220 | +8.59% | 9 |  55.6% | $223.86 | $113.57 | ✅ |
| 15 | -4.56% | -0.763 | +11.79% | 9 |  44.4% | $332.46 | $109.79 | ✅ |

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
    --buy-hold-ret -11.993 \
    --name a-btc-wf-3m1m_w03
```
