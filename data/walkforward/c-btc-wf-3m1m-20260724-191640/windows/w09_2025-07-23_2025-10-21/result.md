# Fragility Scan: c-btc-wf-3m1m_w09

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-07-23T15:00:00+00:00 → 2025-10-21T15:00:00+00:00 (ms: 1753282800000 → 1761058800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -4.408%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +14.64% | +2.867 | +6.19% | 10 |  70.0% | $155.70 | $197.84 | ✅ |
| 10 | +11.65% | +2.232 | +6.66% | 10 |  70.0% | $318.32 | $188.07 | ✅ |
| 15 | +6.65% | +1.299 | +9.26% | 10 |  70.0% | $471.33 | $177.23 | ✅ |

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
    --buy-hold-ret -4.408 \
    --name c-btc-wf-3m1m_w09
```
