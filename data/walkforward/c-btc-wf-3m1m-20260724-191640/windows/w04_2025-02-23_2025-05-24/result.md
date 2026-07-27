# Fragility Scan: c-btc-wf-3m1m_w04

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-02-23T15:00:00+00:00 → 2025-05-24T15:00:00+00:00 (ms: 1740322800000 → 1748098800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 14.084%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -15.51% | -3.665 | +21.85% | 13 |  23.1% | $209.04 | $139.70 | ❌ |
| 10 | -18.78% | -4.306 | +25.16% | 13 |  23.1% | $410.97 | $137.25 | ❌ |
| 15 | -21.93% | -4.814 | +28.99% | 13 |  23.1% | $606.02 | $134.86 | ❌ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **0 / 3** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy C \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15 \
    --fee-bps 5.0 \
    --leverage 5 \
    --buy-hold-ret 14.084 \
    --name c-btc-wf-3m1m_w04
```
