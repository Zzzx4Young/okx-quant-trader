# Fragility Scan: c-btc-LIVE-gate

- **时间**: 2026-07-18 11:57:14
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -6.49%

## 完整网格 (slippage × fee)

| metric \ axis | slip=5bps | slip=10bps | slip=15bps | slip=20bps |
|---|---|---|---|---|
| **fee=4.5bps** | +3.15% ✅ | -4.98% ✅ | -8.46% ❌ | -13.07% ❌ |
| **fee=5.5bps** | +2.59% ✅ | -5.48% ✅ | -8.94% ❌ | -13.53% ❌ |
| **fee=7.0bps** | +1.75% ✅ | -6.24% ✅ | -9.67% ❌ | -14.22% ❌ |
| **fee=8.5bps** | +0.92% ✅ | -6.99% ❌ | -10.39% ❌ | -14.90% ❌ |

**判定**: ✅ = viable (ret > buy-hold)；❌ = alpha 被成本吃掉

## Slippage 敏感性 (fee 固定 = 4.5bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | +3.15% | +0.223 | +17.24% | 25 |  44.0% | $292.62 | $255.29 | ✅ |
| 10 | -4.98% | -0.197 | +21.91% | 25 |  36.0% | $578.90 | $240.08 | ✅ |
| 15 | -8.46% | -0.366 | +24.14% | 25 |  36.0% | $855.36 | $236.72 | ❌ |
| 20 | -13.07% | -0.598 | +27.38% | 25 |  36.0% | $1122.63 | $231.21 | ❌ |

## Fee 敏感性 (slippage 固定 = 5bps)

| fee_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | viable |
|---|---|---|---|---|---|---|
| 4.5 | +3.15% | +0.223 | +17.24% | 25 |  44.0% | ✅ |
| 5.5 | +2.59% | +0.193 | +17.42% | 25 |  44.0% | ✅ |
| 7.0 | +1.75% | +0.148 | +17.69% | 25 |  44.0% | ✅ |
| 8.5 | +0.92% | +0.103 | +17.96% | 25 |  44.0% | ✅ |

## 结论

- 总扫描 cell 数: 16
- viable cells: **7 / 16** (44%)

→ 部分 cell viable。**注意 viable 边界**：ret=0 时的 slippage/fee 上限是上 LIVE 的硬性门。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy C \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15,20 \
    --fee-bps 4.5,5.5,7.0,8.5 \
    --leverage 5 \
    --buy-hold-ret -6.49 \
    --name c-btc-LIVE-gate
```
