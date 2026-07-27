# Fragility Scan: v181-b-btc-section3

- **时间**: 2026-07-18 14:10:19
- **策略**: `B_BB_RSI_REVERSION`
- **标的**: `BTC-USDT-SWAP` (1h)
- **杠杆**: 5x
- **Buy-and-hold 参考**: 75.0%

## 完整网格 (slippage × fee)

| metric \ axis | slip=5bps | slip=10bps | slip=15bps | slip=20bps |
|---|---|---|---|---|
| **fee=5.5bps** | -34.33% ❌ | -42.53% ❌ | -49.10% ❌ | -58.20% ❌ |
| **fee=7.0bps** | -35.28% ❌ | -43.36% ❌ | -49.84% ❌ | -58.80% ❌ |

**判定**: ✅ = viable (ret > buy-hold)；❌ = alpha 被成本吃掉

## Slippage 敏感性 (fee 固定 = 5.5bps)

| slippage_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | slip_cost | fee_paid | viable |
|---|---|---|---|---|---|---|---|---|
| 5 | -34.33% | -1.693 | +38.37% | 45 |  26.7% | $537.43 | $393.81 | ❌ |
| 10 | -42.53% | -2.153 | +45.64% | 45 |  26.7% | $1011.62 | $365.54 | ❌ |
| 15 | -49.10% | -2.484 | +51.47% | 45 |  26.7% | $1435.03 | $343.08 | ❌ |
| 20 | -58.20% | -2.996 | +59.61% | 45 |  24.4% | $1812.51 | $311.70 | ❌ |

## Fee 敏感性 (slippage 固定 = 5bps)

| fee_bps | ret_pct | sharpe | maxDD_pct | trades | win_rate_pct | viable |
|---|---|---|---|---|---|---|
| 5.5 | -34.33% | -1.693 | +38.37% | 45 |  26.7% | ❌ |
| 7.0 | -35.28% | -1.749 | +39.10% | 45 |  26.7% | ❌ |

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
    --name v181-b-btc-section3
```
