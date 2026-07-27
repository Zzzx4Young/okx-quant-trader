# Fragility Scan: c-slippage-fee-matrix-v1

- **时间**: 2026-07-20 20:40:28
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `BTC-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: -6.49%

## 完整网格 (slippage × fee)

| metric \ axis | slip=2bps | slip=5bps | slip=8bps | slip=10bps | slip=15bps |
|---|---|---|---|---|---|
| **fee=2.0bps** | +8.06% ✅ | +4.57% ✅ | -0.63% ✅ | -3.70% ✅ | -7.23% ❌ |
| **fee=5.0bps** | +6.29% ✅ | +2.87% ✅ | -2.22% ✅ | -5.23% ✅ | -8.70% ❌ |
| **fee=8.0bps** | +4.54% ✅ | +1.19% ✅ | -3.79% ✅ | -6.74% ❌ | -10.15% ❌ |

**判定**: ✅ = viable (ret > buy-hold)；❌ = alpha 被成本吃掉

## Slippage 敏感性 (fee 固定 = 2.0bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 2 | +8.06% | +0.488 | +14.39% | 25 |  44.0% | $118.21 | $117.05 | ✅ |
| 5 | +4.57% | +0.297 | +16.79% | 25 |  44.0% | $294.67 | $114.19 | ✅ |
| 8 | -0.63% | +0.026 | +20.59% | 25 |  40.0% | $472.01 | $110.23 | ✅ |
| 10 | -3.70% | -0.131 | +21.50% | 25 |  36.0% | $582.80 | $107.36 | ✅ |
| 15 | -7.23% | -0.303 | +23.75% | 25 |  36.0% | $861.09 | $105.85 | ❌ |

## Fee 敏感性 (slippage 固定 = 2bps)

| fee_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | viable |
|---|---|---|---|---|---|---|
| 2.0 | +8.06% | +0.488 | +14.39% | 25 |  44.0% | ✅ |
| 5.0 | +6.29% | +0.395 | +14.96% | 25 |  44.0% | ✅ |
| 8.0 | +4.54% | +0.301 | +15.53% | 25 |  44.0% | ✅ |

## 结论

- 总扫描 cell 数: 15
- viable cells: **11 / 15** (73%)

→ 部分 cell viable。**注意 viable 边界**：ret=0 时的 slippage/fee 上限是上 LIVE 的硬性门。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy C \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 2,5,8,10,15 \
    --fee-bps 2.0,5.0,8.0 \
    --leverage 5 \
    --buy-hold-ret -6.49 \
    --name c-slippage-fee-matrix-v1
```
