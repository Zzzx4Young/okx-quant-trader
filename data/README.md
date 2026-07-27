# data/ 科学输出目录

> v1.8.4 (commit `466c114`) 从 `docs/agent-context/` 迁出至顶级 tracked。
> **reproducibility 关键**: 跨 session 可重建，避免 baseline 错案（如 7-25 "590 passed" 误报）。

---

## 结构

| 子目录 | 大小 | 产出脚本 | 内容 | 何时查阅 |
|---|---|---|---|---|
| `walkforward/` | ~6.8 MB | `scripts/walkforward.py` | Phase 3A walkforward 18 windows × 2 strategies × 3 slippage cells (slip5/10/15 × fee5) | 写新策略 / 验证 v1.8.4 baseline |
| `phase3b/` | ~316 KB | `scripts/walkforward.py` + `tag_trades_by_regime` | Phase 3B regime-tagged bootstrap 输入 (561 A + 690 C trades) | 跑 Phase 3B bootstrap 验证 regime_filter |
| `montecarlo/` | ~332 KB | `scripts/montecarlo.py` | Phase 3C sensitivity analysis (6 run dirs: a/c-btc × slip10/5 × down-only) | slippage / fee 敏感性验证 |
| `experiments/` | ~2.6 MB | various (`scripts/diagnose_okx_demo.py`, `scripts/fragility_scan.py`, etc.) | 31 backtest experiment dirs (gate7 / v18 / kelly / diagnose) | 重做某个 experiment 时 |
| `funding/` | (legacy, pre-v1.8.4) | `scripts/fetch_funding.py` | 资金费率历史数据 | 历史回放 |
| `market/` | (legacy, pre-v1.8.4) | `scripts/fetch_klines.py` | K线/订单簿历史数据 | 历史回放 |

---

## 维护约定

- **tracked**: 所有文件 git tracked（除非 `docs/agent-context/` 在 .gitignore 里）。
  - `data/` 顶级 tracked（默认）
  - 旧 `docs/agent-context/{walkforward,phase3b,montecarlo,experiments}/` 已 gitignore
- **never edit by hand**: 任何 `.parquet` / `trades.json` 都是脚本产出。手改 = 失去 reproducibility。
- **cleanup only via scripts**: 重新生成走对应 scripts（`scripts/walkforward.py --name <run>` 等）

---

## V1 + V2 已删除

- `backtest_system_design_report.md` (V1) 和 `backtest_system_design_report_V2.md` (V2) 已删除（V2.1 canonical）
- Recovery 备份: `/tmp/dup-cleanup-2026-07-27/`（如需恢复: `mv /tmp/dup-cleanup-2026-07-27/*.md docs/agent-context/`）

---

## 跨 session 重现

工作树 wipe 后，1 小时左右可重建（取决于 walkforward 重跑数量）:

```bash
# 1. 拉 K 线 (~5min × 2 strategies)
python3 -m okx.scripts.fetch_klines --symbol BTC-USDT-SWAP --timeframe 1h --start 2024-10-01 --end 2026-06-30

# 2. 重跑 walkforward (~30min × 2 strategies)
python3 -m okx.scripts.walkforward --strategy A --symbol BTC-USDT-SWAP --timeframe 1h --window-days 90 --stride-days 30 --name a-btc-wf-3m1m
python3 -m okx.scripts.walkforward --strategy C --symbol BTC-USDT-SWAP --timeframe 1h --window-days 90 --stride-days 30 --name c-btc-wf-3m1m

# 3. 重跑 Phase 3B prep (~1min)
python3 data/phase3b/prep.py

# 4. 重跑 monte carlo (~5min)
python3 -m okx.scripts.montecarlo --walkforward-dir data/walkforward/a-btc-wf-3m1m-...
```

→ 输出应 bit-identical（除时间戳 + git_commit hash 外）

---

## 关联 commit 历史

| Commit | 描述 | 影响 |
|---|---|---|
| `4c8937b` | Phase 3A walkforward 基础设施（创建了 walkforward/） | source code only |
| `ee915c5` | Alert Source vs Strategy 重构 | source code only |
| `92f5128` | 7-25 P0 ship batch（CB + liveness + MC + tag_trades_by_regime） | source code only |
| `466c114` | **data 拆分**（本目录来源） | move 4 dirs from docs/agent-context/ → data/ |

`466c114` 之前的 `docs/agent-context/{walkforward,phase3b,montecarlo,experiments}/` 全部 gitignored（仅在 workspace 磁盘上）。commit 后正式 tracked，跨 session 可复现。