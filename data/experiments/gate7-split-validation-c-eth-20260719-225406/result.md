# Fragility Scan: gate7-split-validation-c-eth

- **时间**: 2026-07-19 22:54:06
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `ETH-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: N/A%

## Slippage 敏感性 (fee 固定 = 5.5bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -1.62% | +0.023 | +23.66% | 47 |  46.8% | $511.42 | $501.64 | ❌ |
| 8 | -9.46% | -0.256 | +27.47% | 47 |  44.7% | $800.96 | $474.36 | ❌ |
| 12 | -16.89% | -0.526 | +29.82% | 47 |  42.6% | $1150.20 | $447.81 | ❌ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **0 / 3** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy C \
    --symbol ETH-USDT-SWAP --bar 1h \
    --slippage-bps 5,8,12 \
    --fee-bps 5.5 \
    --leverage 5 \
    --name gate7-split-validation-c-eth
```
