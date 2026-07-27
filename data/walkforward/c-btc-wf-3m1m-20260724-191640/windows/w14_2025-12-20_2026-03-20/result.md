# Fragility Scan: c-btc-wf-3m1m_w14

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-12-20T15:00:00+00:00 → 2026-03-20T15:00:00+00:00 (ms: 1766242800000 → 1774018800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -20.754%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -9.08% | -1.812 | +15.05% | 12 |  33.3% | $167.71 | $137.37 | ✅ |
| 10 | -13.04% | -2.613 | +18.86% | 12 |  25.0% | $335.24 | $131.02 | ✅ |
| 15 | -15.45% | -3.125 | +21.14% | 12 |  25.0% | $496.78 | $129.46 | ✅ |

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
    --buy-hold-ret -20.754 \
    --name c-btc-wf-3m1m_w14
```
