# Monte Carlo: a-btc-mc-slip5-down-only

- **时间**: 2026-07-24T16:26:34.157838+00:00
- **策略**: EMA_CROSSOVER
- **标的**: ?
- **样本**: 68 笔 net_pnl（来自 /home/zzzx47/.openclaw/workspace/okx/data/walkforward/a-btc-wf-3m1m-20260724-194650）
- **模拟**: 1000 次 bootstrap × 68 笔/次
- **初始资金**: $10000.00

## Final Equity 分布（USD）

| 5% 分位 | 50% 分位 (中位) | 95% 分位 | 均值 | 标准差 |
|---|---|---|---|---|
| $8952.07 | $12370.89 | $15827.75 | $12368.20 | $2138.27 |

**中位收益**: +23.71%

## Max Drawdown 分布

| 5% 分位 | 50% 分位 | 95% 分位 | 均值 |
|---|---|---|---|
| 6.15% | 12.51% | 26.32% | 13.88% |

**最坏 5% 情况至少回撤 ≥ 95% 分位 DD**（保守估计仍能承受的 max DD 阈值）

## Probability of Ruin

| 阈值 | 概率 |
|---|---|
| final < 50% initial | 0.0% |
| final < 30% initial | 0.0% |
| final < 10% initial | 0.0% |

## 结论

✅ 中位正收益 + 破产概率低 + 回撤可控：策略统计上稳健（仍需 live observation 验证）

## 复现命令

```bash
python3 -m okx.scripts.montecarlo \
    --walkforward-dir /home/zzzx47/.openclaw/workspace/okx/data/walkforward/a-btc-wf-3m1m-20260724-194650 \
    --initial-capital 10000.0 \
    --n-sims 1000 \
    --name a-btc-mc-slip5-down-only
```

raw: 完整分布存于 `meta.json`（1000 个 final_equity + max_dd 值）