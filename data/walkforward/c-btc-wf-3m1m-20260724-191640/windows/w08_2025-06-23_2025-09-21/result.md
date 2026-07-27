# Fragility Scan: c-btc-wf-3m1m_w08

- **时间**: 2026-07-24 19:16:40
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-06-23T15:00:00+00:00 → 2025-09-21T15:00:00+00:00 (ms: 1750690800000 → 1758466800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 13.906%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +3.38% | +2.095 | +2.25% | 1 | 100.0% | $9.22 | $18.44 | ❌ |
| 10 | +3.45% | +2.024 | +2.25% | 1 | 100.0% | $18.43 | $18.45 | ❌ |
| 15 | +3.52% | +1.788 | +2.25% | 1 | 100.0% | $27.65 | $18.46 | ❌ |

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
    --buy-hold-ret 13.906 \
    --name c-btc-wf-3m1m_w08
```
