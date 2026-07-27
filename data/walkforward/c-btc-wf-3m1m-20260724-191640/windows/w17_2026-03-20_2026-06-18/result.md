# Fragility Scan: c-btc-wf-3m1m_w17

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2026-03-20T15:00:00+00:00 → 2026-06-18T15:00:00+00:00 (ms: 1774018800000 → 1781794800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -10.75%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +5.64% | +1.092 | +7.71% | 12 |  50.0% | $134.52 | $144.60 | ✅ |
| 10 | +2.47% | +0.542 | +10.21% | 12 |  41.7% | $270.94 | $140.24 | ✅ |
| 15 | +1.00% | +0.288 | +11.23% | 12 |  41.7% | $404.09 | $139.39 | ✅ |

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
    --buy-hold-ret -10.75 \
    --name c-btc-wf-3m1m_w17
```
