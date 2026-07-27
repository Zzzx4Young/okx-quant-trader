# Fragility Scan: a-btc-wf-3m1m_w00

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2024-10-26T15:00:00+00:00 → 2025-01-24T15:00:00+00:00 (ms: 1729954800000 → 1737730800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 58.276%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -1.16% | -0.299 | +5.74% | 5 |  40.0% | $88.01 | $77.98 | ❌ |
| 10 | -2.33% | -0.654 | +6.22% | 5 |  40.0% | $175.04 | $77.38 | ❌ |
| 15 | -3.49% | -0.753 | +7.16% | 5 |  40.0% | $261.11 | $76.78 | ❌ |

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
    --buy-hold-ret 58.276 \
    --name a-btc-wf-3m1m_w00
```
