# Monte Carlo: c-btc-mc-slip10

- **时间**: 2026-07-24T15:27:30.936112+00:00
- **策略**: EMA_CROSSOVER
- **标的**: ?
- **样本**: 230 笔 net_pnl（来自 /home/zzzx47/.openclaw/workspace/okx/data/walkforward/c-btc-wf-3m1m-20260724-191640）
- **模拟**: 1000 次 bootstrap × 230 笔/次
- **初始资金**: $10000.00

## Final Equity 分布（USD）

| 5% 分位 | 50% 分位 (中位) | 95% 分位 | 均值 | 标准差 |
|---|---|---|---|---|
| $-3657.39 | $2325.68 | $9030.05 | $2523.64 | $3822.39 |

**中位收益**: -76.74%

## Max Drawdown 分布

| 5% 分位 | 50% 分位 | 95% 分位 | 均值 |
|---|---|---|---|
| 36.21% | 85.39% | 138.96% | 86.23% |

**最坏 5% 情况至少回撤 ≥ 95% 分位 DD**（保守估计仍能承受的 max DD 阈值）

## Probability of Ruin

| 阈值 | 概率 |
|---|---|
| final < 50% initial | 74.4% |
| final < 30% initial | 55.9% |
| final < 10% initial | 36.7% |

## 结论

⚠️ **P(final < 50%) > 5%**：策略破产风险显著，不建议无熔断器运行

## 复现命令

```bash
python3 -m okx.scripts.montecarlo \
    --walkforward-dir /home/zzzx47/.openclaw/workspace/okx/data/walkforward/c-btc-wf-3m1m-20260724-191640 \
    --initial-capital 10000.0 \
    --n-sims 1000 \
    --name c-btc-mc-slip10
```

raw: 完整分布存于 `meta.json`（1000 个 final_equity + max_dd 值）