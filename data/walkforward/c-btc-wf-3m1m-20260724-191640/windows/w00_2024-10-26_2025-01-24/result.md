# Fragility Scan: c-btc-wf-3m1m_w00

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2024-10-26T15:00:00+00:00 → 2025-01-24T15:00:00+00:00 (ms: 1729954800000 → 1737730800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 58.276%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +4.33% | +1.892 | +2.35% | 3 |  66.7% | $37.79 | $56.07 | ❌ |
| 10 | +4.25% | +1.721 | +2.79% | 3 |  66.7% | $75.60 | $56.09 | ❌ |
| 15 | +4.17% | +1.520 | +3.07% | 3 |  66.7% | $113.43 | $56.11 | ❌ |

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
    --buy-hold-ret 58.276 \
    --name c-btc-wf-3m1m_w00
```
