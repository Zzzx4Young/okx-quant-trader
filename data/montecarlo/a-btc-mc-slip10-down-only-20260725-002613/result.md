# Monte Carlo: a-btc-mc-slip10-down-only

- **时间**: 2026-07-24T16:26:13.555382+00:00
- **策略**: EMA_CROSSOVER
- **标的**: ?
- **样本**: 68 笔 net_pnl（来自 /home/zzzx47/.openclaw/workspace/okx/data/walkforward/a-btc-wf-3m1m-20260724-194650）
- **模拟**: 1000 次 bootstrap × 68 笔/次
- **初始资金**: $10000.00

## Final Equity 分布（USD）

| 5% 分位 | 50% 分位 (中位) | 95% 分位 | 均值 | 标准差 |
|---|---|---|---|---|
| $6625.86 | $9800.68 | $13198.16 | $9813.32 | $2021.20 |

**中位收益**: -1.99%

## Max Drawdown 分布

| 5% 分位 | 50% 分位 | 95% 分位 | 均值 |
|---|---|---|---|
| 8.97% | 19.40% | 40.07% | 21.37% |

**最坏 5% 情况至少回撤 ≥ 95% 分位 DD**（保守估计仍能承受的 max DD 阈值）

## Probability of Ruin

| 阈值 | 概率 |
|---|---|
| final < 50% initial | 0.3% |
| final < 30% initial | 0.0% |
| final < 10% initial | 0.0% |

## 结论

⚠️ **95% 分位 max DD > 30%**：最坏 5% 情况回撤较大，建议 Kelly 缩仓 + DD 熔断

## 复现命令

```bash
python3 -m okx.scripts.montecarlo \
    --walkforward-dir /home/zzzx47/.openclaw/workspace/okx/data/walkforward/a-btc-wf-3m1m-20260724-194650 \
    --initial-capital 10000.0 \
    --n-sims 1000 \
    --name a-btc-mc-slip10-down-only
```

raw: 完整分布存于 `meta.json`（1000 个 final_equity + max_dd 值）