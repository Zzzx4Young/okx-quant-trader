# Fragility Scan: d-btc-1h-baseline

- **时间**: 2026-07-19 16:20:55
- **策略**: `D_FUNDING_RATE_REVERSAL`
- **标的**: `BTC-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: N/A%

## Slippage 敏感性 (fee 固定 = 5.5bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 10 | +0.00% | +0.000 | -0.00% | 0 |   0.0% | $0.00 | $0.00 | ❌ |

## 结论

- 总扫描 cell 数: 1
- viable cells: **0 / 1** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy D \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 10 \
    --fee-bps 5.5 \
    --leverage 5 \
    --name d-btc-1h-baseline
```
