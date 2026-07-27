# Fragility Scan: a-btc-wf-3m1m_w12

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-10-21T15:00:00+00:00 → 2026-01-19T15:00:00+00:00 (ms: 1761058800000 → 1768834800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -17.967%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +3.16% | +1.015 | +6.63% | 6 |  50.0% | $55.30 | $55.65 | ✅ |
| 10 | -0.45% | -0.067 | +7.85% | 6 |  50.0% | $113.53 | $52.86 | ✅ |
| 15 | -1.16% | -0.271 | +8.49% | 6 |  50.0% | $169.86 | $52.73 | ✅ |

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
    --buy-hold-ret -17.967 \
    --name a-btc-wf-3m1m_w12
```
