# Fragility Scan: b-eth-v18-fixa-slip

- **时间**: 2026-07-18 01:18:43
- **策略**: `B_BB_RSI_REVERSION`
- **标的**: `ETH-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -7.42%

## Slippage 敏感性 (fee 固定 = 5.5bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -26.58% | -1.839 | +32.08% | 32 |  28.1% | $234.66 | $177.88 | ❌ |
| 10 | -31.09% | -2.122 | +36.23% | 32 |  25.0% | $459.02 | $171.80 | ❌ |
| 15 | -35.43% | -2.372 | +40.34% | 32 |  21.9% | $675.82 | $166.25 | ❌ |
| 20 | -38.51% | -2.584 | +43.27% | 32 |  21.9% | $881.54 | $162.40 | ❌ |

## 结论

- 总扫描 cell 数: 4
- viable cells: **0 / 4** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy B \
    --symbol ETH-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15,20 \
    --fee-bps 5.5 \
    --leverage 5 \
    --buy-hold-ret -7.42 \
    --name b-eth-v18-fixa-slip
```
