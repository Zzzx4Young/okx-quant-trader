# Fragility Scan: a-btc-wf-3m1m_w01

- **时间**: 2026-07-24 19:46:50
- **策略**: `A_EMA20_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **窗口**: 2024-11-25T15:00:00+00:00 → 2025-02-23T15:00:00+00:00 (ms: 1732546800000 → 1740322800000)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -0.577%

## Slippage 敏感性 (fee 固定 = 5.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +6.18% | +1.135 | +10.38% | 24 |  54.2% | $262.02 | $270.82 | ✅ |
| 10 | +0.05% | +0.134 | +12.74% | 24 |  54.2% | $521.95 | $260.89 | ✅ |
| 15 | -4.52% | -0.586 | +17.02% | 24 |  50.0% | $770.81 | $254.22 | ❌ |

## 结论

- 总扫描 cell 数: 3
- viable cells: **2 / 3** (67%)

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
    --buy-hold-ret -0.577 \
    --name a-btc-wf-3m1m_w01
```
