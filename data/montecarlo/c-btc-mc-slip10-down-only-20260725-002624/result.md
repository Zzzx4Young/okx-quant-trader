# Monte Carlo: c-btc-mc-slip10-down-only

- **时间**: 2026-07-24T16:26:24.287498+00:00
- **策略**: EMA_CROSSOVER
- **标的**: ?
- **样本**: 101 笔 net_pnl（来自 /home/zzzx47/.openclaw/workspace/okx/data/walkforward/c-btc-wf-3m1m-20260724-191640）
- **模拟**: 1000 次 bootstrap × 101 笔/次
- **初始资金**: $10000.00

## Final Equity 分布（USD）

| 5% 分位 | 50% 分位 (中位) | 95% 分位 | 均值 | 标准差 |
|---|---|---|---|---|
| $277.58 | $4148.22 | $8289.26 | $4241.03 | $2460.65 |

**中位收益**: -58.52%

## Max Drawdown 分布

| 5% 分位 | 50% 分位 | 95% 分位 | 均值 |
|---|---|---|---|
| 30.43% | 64.46% | 99.70% | 64.12% |

**最坏 5% 情况至少回撤 ≥ 95% 分位 DD**（保守估计仍能承受的 max DD 阈值）

## Probability of Ruin

| 阈值 | 概率 |
|---|---|
| final < 50% initial | 62.8% |
| final < 30% initial | 31.2% |
| final < 10% initial | 9.1% |

## 结论

⚠️ **P(final < 50%) > 5%**：策略破产风险显著，不建议无熔断器运行

## 复现命令

```bash
python3 -m okx.scripts.montecarlo \
    --walkforward-dir /home/zzzx47/.openclaw/workspace/okx/data/walkforward/c-btc-wf-3m1m-20260724-191640 \
    --initial-capital 10000.0 \
    --n-sims 1000 \
    --name c-btc-mc-slip10-down-only
```

raw: 完整分布存于 `meta.json`（1000 个 final_equity + max_dd 值）