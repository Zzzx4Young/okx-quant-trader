# Fragility Scan: a-btc-wf-3m1m_w13

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-11-20T15:00:00+00:00 → 2026-02-18T15:00:00+00:00 (ms: 1763650800000 → 1771426800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -24.658%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +1.36% | +0.534 | +5.21% | 5 |  40.0% | $34.94 | $40.50 | ✅ |
| 10 | +1.07% | +0.424 | +5.93% | 5 |  40.0% | $69.80 | $40.46 | ✅ |
| 15 | +0.78% | +0.325 | +6.33% | 5 |  40.0% | $104.59 | $40.43 | ✅ |

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
    --buy-hold-ret -24.658 \
    --name a-btc-wf-3m1m_w13
```
