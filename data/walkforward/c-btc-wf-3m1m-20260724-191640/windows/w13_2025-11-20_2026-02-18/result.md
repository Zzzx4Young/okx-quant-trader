# Fragility Scan: c-btc-wf-3m1m_w13

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-11-20T15:00:00+00:00 → 2026-02-18T15:00:00+00:00 (ms: 1763650800000 → 1771426800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -24.658%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -11.62% | -2.066 | +19.13% | 18 |  33.3% | $284.49 | $221.60 | ✅ |
| 10 | -18.50% | -3.182 | +25.44% | 18 |  27.8% | $566.77 | $204.11 | ✅ |
| 15 | -22.54% | -3.899 | +29.08% | 18 |  27.8% | $831.45 | $199.47 | ✅ |

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
    --buy-hold-ret -24.658 \
    --name c-btc-wf-3m1m_w13
```
