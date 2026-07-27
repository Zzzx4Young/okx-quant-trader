# Fragility Scan: c-btc-wf-3m1m_w01

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2024-11-25T15:00:00+00:00 → 2025-02-23T15:00:00+00:00 (ms: 1732546800000 → 1740322800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -0.577%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -4.59% | -0.660 | +15.82% | 23 |  43.5% | $252.37 | $224.78 | ❌ |
| 10 | -9.39% | -1.448 | +18.94% | 23 |  39.1% | $492.28 | $215.39 | ❌ |
| 15 | -12.59% | -1.927 | +20.72% | 23 |  39.1% | $725.18 | $211.14 | ❌ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **0 / 3** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy C \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15 \
    --fee-bps 5.0 \
    --leverage 5 \
    --buy-hold-ret -0.577 \
    --name c-btc-wf-3m1m_w01
```
