# Fragility Scan: c-btc-wf-3m1m_w05

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-03-25T15:00:00+00:00 → 2025-06-23T15:00:00+00:00 (ms: 1742914800000 → 1750690800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 15.499%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -17.05% | -3.267 | +20.85% | 18 |  27.8% | $207.09 | $151.59 | ❌ |
| 10 | -20.06% | -3.872 | +23.87% | 18 |  27.8% | $407.11 | $148.86 | ❌ |
| 15 | -24.39% | -4.688 | +28.12% | 18 |  22.2% | $603.67 | $142.95 | ❌ |

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
    --buy-hold-ret 15.499 \
    --name c-btc-wf-3m1m_w05
```
