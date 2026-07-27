# Fragility Scan: a-btc-wf-3m1m_w05

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-03-25T15:00:00+00:00 → 2025-06-23T15:00:00+00:00 (ms: 1742914800000 → 1750690800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 15.499%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -10.97% | -1.831 | +21.81% | 16 |  37.5% | $260.23 | $203.52 | ❌ |
| 10 | -16.15% | -2.726 | +26.55% | 16 |  31.2% | $514.89 | $195.39 | ❌ |
| 15 | -19.74% | -3.327 | +29.88% | 16 |  31.2% | $758.50 | $192.00 | ❌ |

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
    --buy-hold-ret 15.499 \
    --name a-btc-wf-3m1m_w05
```
