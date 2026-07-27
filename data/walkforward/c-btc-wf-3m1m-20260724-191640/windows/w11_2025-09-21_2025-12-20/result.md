# Fragility Scan: c-btc-wf-3m1m_w11

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-09-21T15:00:00+00:00 → 2025-12-20T15:00:00+00:00 (ms: 1758466800000 → 1766242800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -23.677%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -13.02% | -2.559 | +16.59% | 19 |  31.6% | $276.76 | $213.51 | ✅ |
| 10 | -18.07% | -3.549 | +21.35% | 19 |  31.6% | $540.74 | $203.72 | ✅ |
| 15 | -21.83% | -4.174 | +24.88% | 19 |  31.6% | $794.34 | $199.36 | ✅ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **3 / 3** (100%)

→ 所有 cell viable。策略对成本不敏感。**可以直接进入下一阶段评估**。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy C \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15 \
    --fee-bps 5.0 \
    --leverage 5 \
    --buy-hold-ret -23.677 \
    --name c-btc-wf-3m1m_w11
```
