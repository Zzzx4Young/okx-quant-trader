# Fragility Scan: a-btc-wf-3m1m_w15

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2026-01-19T15:00:00+00:00 → 2026-04-19T15:00:00+00:00 (ms: 1768834800000 → 1776610800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -18.498%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +4.92% | +1.123 | +5.21% | 9 |  44.4% | $63.55 | $72.77 | ✅ |
| 10 | +1.17% | +0.332 | +8.28% | 9 |  44.4% | $130.48 | $67.63 | ✅ |
| 15 | +0.41% | +0.184 | +8.90% | 9 |  44.4% | $194.85 | $67.31 | ✅ |

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
    --buy-hold-ret -18.498 \
    --name a-btc-wf-3m1m_w15
```
