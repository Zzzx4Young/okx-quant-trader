# Fragility Scan: c-btc-wf-3m1m_w12

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-10-21T15:00:00+00:00 → 2026-01-19T15:00:00+00:00 (ms: 1761058800000 → 1768834800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -17.967%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -12.04% | -3.627 | +14.91% | 10 |  20.0% | $137.50 | $93.56 | ✅ |
| 10 | -14.25% | -4.204 | +17.11% | 10 |  20.0% | $271.94 | $92.40 | ✅ |
| 15 | -16.41% | -4.597 | +19.26% | 10 |  20.0% | $403.39 | $91.27 | ✅ |

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
    --buy-hold-ret -17.967 \
    --name c-btc-wf-3m1m_w12
```
