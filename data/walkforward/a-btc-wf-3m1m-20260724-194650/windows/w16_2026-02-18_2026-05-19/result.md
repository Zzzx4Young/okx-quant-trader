# Fragility Scan: a-btc-wf-3m1m_w16

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2026-02-18T15:00:00+00:00 → 2026-05-19T15:00:00+00:00 (ms: 1771426800000 → 1779202800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 13.046%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +5.89% | +1.829 | +4.91% | 3 |  66.7% | $19.46 | $27.01 | ❌ |
| 10 | +5.79% | +1.799 | +4.91% | 3 |  66.7% | $38.89 | $26.99 | ❌ |
| 15 | +5.70% | +1.771 | +4.91% | 3 |  66.7% | $58.30 | $26.98 | ❌ |

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
    --buy-hold-ret 13.046 \
    --name a-btc-wf-3m1m_w16
```
