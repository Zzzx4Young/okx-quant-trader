# Fragility Scan: a-btc-wf-3m1m_w02

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2024-12-25T15:00:00+00:00 → 2025-03-25T15:00:00+00:00 (ms: 1735138800000 → 1742914800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -10.917%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +1.33% | +0.357 | +9.31% | 18 |  50.0% | $203.27 | $207.24 | ✅ |
| 10 | -4.07% | -0.633 | +11.24% | 18 |  50.0% | $406.03 | $198.33 | ✅ |
| 15 | -8.01% | -1.309 | +15.15% | 18 |  44.4% | $599.75 | $192.51 | ✅ |

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
    --buy-hold-ret -10.917 \
    --name a-btc-wf-3m1m_w02
```
