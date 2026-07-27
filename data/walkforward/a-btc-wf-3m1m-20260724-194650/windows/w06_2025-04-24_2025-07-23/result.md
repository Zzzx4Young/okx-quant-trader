# Fragility Scan: a-btc-wf-3m1m_w06

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-04-24T15:00:00+00:00 → 2025-07-23T15:00:00+00:00 (ms: 1745506800000 → 1753282800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 27.307%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -10.32% | -2.861 | +14.37% | 9 |  33.3% | $141.28 | $99.90 | ❌ |
| 10 | -14.13% | -3.720 | +18.10% | 9 |  22.2% | $282.84 | $93.81 | ❌ |
| 15 | -16.44% | -4.178 | +20.51% | 9 |  22.2% | $418.91 | $92.42 | ❌ |

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
    --buy-hold-ret 27.307 \
    --name a-btc-wf-3m1m_w06
```
