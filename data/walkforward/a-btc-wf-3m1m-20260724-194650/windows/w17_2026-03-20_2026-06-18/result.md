# Fragility Scan: a-btc-wf-3m1m_w17

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2026-03-20T15:00:00+00:00 → 2026-06-18T15:00:00+00:00 (ms: 1774018800000 → 1781794800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -10.75%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +1.96% | +0.507 | +10.72% | 8 |  37.5% | $93.94 | $102.28 | ✅ |
| 10 | +1.03% | +0.310 | +11.59% | 8 |  37.5% | $187.13 | $101.82 | ✅ |
| 15 | -1.32% | -0.177 | +13.79% | 8 |  37.5% | $283.21 | $98.95 | ✅ |

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
    --buy-hold-ret -10.75 \
    --name a-btc-wf-3m1m_w17
```
