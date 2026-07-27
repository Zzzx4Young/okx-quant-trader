# Fragility Scan: a-btc-wf-3m1m_w10

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-08-22T15:00:00+00:00 → 2025-11-20T15:00:00+00:00 (ms: 1755874800000 → 1763650800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -22.793%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +2.40% | +0.586 | +10.15% | 13 |  46.2% | $169.65 | $158.06 | ✅ |
| 10 | -8.74% | -1.624 | +14.64% | 13 |  38.5% | $345.95 | $137.67 | ✅ |
| 15 | -12.86% | -2.272 | +17.93% | 13 |  38.5% | $520.03 | $129.46 | ✅ |

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
    --buy-hold-ret -22.793 \
    --name a-btc-wf-3m1m_w10
```
