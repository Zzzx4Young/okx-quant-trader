# Fragility Scan: a-btc-full

- **时间**: 2026-07-24 23:18:05
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: N/A%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +1.21% | +0.119 | +10.93% | 20 |  40.0% | $205.77 | $191.77 | ✅ |
| 10 | -1.35% | -0.016 | +11.94% | 20 |  40.0% | $406.57 | $189.32 | ❌ |
| 15 | -3.85% | -0.135 | +12.94% | 20 |  40.0% | $602.49 | $186.90 | ❌ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **1 / 3** (33%)

→ 部分 cell viable。**注意 viable 边界**：ret=0 时的 slippage/fee 上限是上 LIVE 的硬性门。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy A \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15 \
    --fee-bps 5.0 \
    --leverage 5 \
    --name a-btc-full
```
