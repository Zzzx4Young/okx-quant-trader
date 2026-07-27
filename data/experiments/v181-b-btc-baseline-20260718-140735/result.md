# Fragility Scan: v181-b-btc-baseline

- **时间**: 2026-07-18 14:07:35
- **策略**: `B_BB_RSI_REVERSION`
- **标的**: `BTC-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 75.0%

## 完整网格 (slippage × fee)

| metric \ axis | slip=5bps | slip=10bps | slip=15bps | slip=20bps |
|---|---|---|---|---|
| **fee=5.5bps** | -24.27% ❌ | -31.12% ❌ | -36.57% ❌ | -41.61% ❌ |
| **fee=7.0bps** | -25.04% ❌ | -31.81% ❌ | -37.21% ❌ | -42.20% ❌ |

**判定**: ✅ = viable (ret > buy-hold)；❌ = alpha 被成本吃掉

## Slippage 敏感性 (fee 固定 = 5.5bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -24.27% | -1.327 | +33.96% | 36 |  27.8% | $392.05 | $289.60 | ❌ |
| 10 | -31.12% | -1.709 | +39.27% | 36 |  27.8% | $752.69 | $273.36 | ❌ |
| 15 | -36.57% | -1.989 | +43.46% | 36 |  27.8% | $1084.48 | $260.41 | ❌ |
| 20 | -41.61% | -2.232 | +47.99% | 36 |  27.8% | $1389.59 | $248.19 | ❌ |

## Fee 敏感性 (slippage 固定 = 5bps)

| fee_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | viable |
|---|---|---|---|---|---|---|
| 5.5 | -24.27% | -1.327 | +33.96% | 36 |  27.8% | ❌ |
| 7.0 | -25.04% | -1.373 | +34.36% | 36 |  27.8% | ❌ |

## 结论

- 总扫描 cell 数: 8
- viable cells: **0 / 8** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy B \
    --symbol BTC-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15,20 \
    --fee-bps 5.5,7.0 \
    --leverage 5 \
    --buy-hold-ret 75.0 \
    --name v181-b-btc-baseline
```
