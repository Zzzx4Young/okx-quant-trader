# Fragility Scan: mvp-persist-test

- **时间**: 2026-07-23 22:16:06
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 50.0%

## Slippage 敏感性 (fee 固定 = 4.5bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +1.40% | +0.129 | +10.90% | 20 |  40.0% | $205.95 | $172.75 | ❌ |

## 结论

- 总扫描 cell 数: 1
- viable cells: **0 / 1** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy A \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5 \
    --fee-bps 4.5 \
    --leverage 5 \
    --buy-hold-ret 50.0 \
    --name mvp-persist-test
```
