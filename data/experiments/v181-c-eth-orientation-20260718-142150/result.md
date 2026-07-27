# Fragility Scan: v181-c-eth-orientation

- **时间**: 2026-07-18 14:21:50
- **策略**: `C_VOLATILITY_BREAKOUT`
- **标的**: `ETH-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 30.0%

## 完整网格 (slippage × fee)

| metric \ axis | slip=5bps | slip=10bps | slip=15bps | slip=20bps |
|---|---|---|---|---|
| **fee=5.5bps** | -1.62% ❌ | -13.09% ❌ | -21.64% ❌ | -29.60% ❌ |
| **fee=7.0bps** | -2.89% ❌ | -14.20% ❌ | -22.63% ❌ | -30.48% ❌ |

**判定**: ✅ = viable (ret > buy-hold)；❌ = alpha 被成本吃掉

## Slippage 敏感性 (fee 固定 = 5.5bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -1.62% | +0.023 | +23.66% | 47 |  46.8% | $511.42 | $501.64 | ❌ |
| 10 | -13.09% | -0.383 | +28.65% | 47 |  44.7% | $981.68 | $462.06 | ❌ |
| 15 | -21.64% | -0.711 | +31.54% | 47 |  40.4% | $1398.59 | $434.12 | ❌ |
| 20 | -29.60% | -1.044 | +37.44% | 47 |  40.4% | $1813.90 | $416.93 | ❌ |

## Fee 敏感性 (slippage 固定 = 5bps)

| fee_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | viable |
|---|---|---|---|---|---|---|
| 5.5 | -1.62% | +0.023 | +23.66% | 47 |  46.8% | ❌ |
| 7.0 | -2.89% | -0.023 | +24.05% | 47 |  46.8% | ❌ |

## 结论

- 总扫描 cell 数: 8
- viable cells: **0 / 8** (0%)

→ **没有 viable cell**。策略 alpha 在测试成本范围内被完全吃掉。

---

**复现命令**:
```bash
python3 -m okx.scripts.fragility_scan \
    --strategy C \
    --symbol ETH-USDT-SWAP --bar 1h \
    --slippage-bps 5,10,15,20 \
    --fee-bps 5.5,7.0 \
    --leverage 5 \
    --buy-hold-ret 30.0 \
    --name v181-c-eth-orientation
```
