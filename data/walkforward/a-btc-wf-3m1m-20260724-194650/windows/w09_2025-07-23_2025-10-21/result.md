# Fragility Scan: a-btc-wf-3m1m_w09

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2025-07-23T15:00:00+00:00 → 2025-10-21T15:00:00+00:00 (ms: 1753282800000 → 1761058800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -4.408%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -4.14% | -0.804 | +12.14% | 12 |  41.7% | $200.97 | $166.34 | ✅ |
| 10 | -6.88% | -1.320 | +15.18% | 12 |  41.7% | $397.46 | $164.50 | ❌ |
| 15 | -9.55% | -1.813 | +17.46% | 12 |  41.7% | $589.57 | $162.69 | ❌ |

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
    --buy-hold-ret -4.408 \
    --name a-btc-wf-3m1m_w09
```
