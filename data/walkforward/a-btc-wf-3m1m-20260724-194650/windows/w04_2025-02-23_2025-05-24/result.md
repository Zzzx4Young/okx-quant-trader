# Fragility Scan: a-btc-wf-3m1m_w04

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-02-23T15:00:00+00:00 → 2025-05-24T15:00:00+00:00 (ms: 1740322800000 → 1748098800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 14.084%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +3.09% | +0.825 | +8.00% | 7 |  57.1% | $93.04 | $91.26 | ❌ |
| 10 | +2.02% | +0.559 | +9.23% | 7 |  57.1% | $185.53 | $90.93 | ❌ |
| 15 | +0.95% | +0.305 | +10.46% | 7 |  57.1% | $277.46 | $90.61 | ❌ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **0 / 3** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy A \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15 \
    --fee-bps 5.0 \
    --leverage 5 \
    --buy-hold-ret 14.084 \
    --name a-btc-wf-3m1m_w04
```
