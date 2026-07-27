# Fragility Scan: gate7-split-validation-c-btc

- **时间**: 2026-07-19 22:25:13
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -6.49%

## Slippage 敏感性 (fee 固定 = 5.5bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +2.59% | +0.193 | +17.42% | 25 |  44.0% | $291.81 | $311.23 | ✅ |
| 8 | -2.48% | -0.069 | +21.16% | 25 |  40.0% | $467.50 | $300.51 | ✅ |
| 12 | -6.88% | -0.293 | +22.97% | 25 |  36.0% | $688.65 | $291.07 | ❌ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **2 / 3** (67%)

→ 部分 cell viable。**注意 viable 边界**：ret=0 时的 slippage/fee 上限是上 LIVE 的硬性门。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy C \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5,8,12 \
    --fee-bps 5.5 \
    --leverage 5 \
    --buy-hold-ret -6.49 \
    --name gate7-split-validation-c-btc
```
