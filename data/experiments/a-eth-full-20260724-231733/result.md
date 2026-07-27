# Fragility Scan: a-eth-full

- **时间**: 2026-07-24 23:17:33
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `ETH-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: N/A%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -12.18% | -0.619 | +20.42% | 32 |  34.4% | $209.25 | $181.87 | ❌ |
| 10 | -15.99% | -0.812 | +23.72% | 32 |  34.4% | $413.05 | $177.18 | ❌ |
| 15 | -19.74% | -1.016 | +27.13% | 32 |  34.4% | $612.77 | $173.01 | ❌ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **0 / 3** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy A \
    --symbol ETH-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15 \
    --fee-bps 5.0 \
    --leverage 5 \
    --name a-eth-full
```
