# v1.7 Fragility Scan —— C strategy 真实成本敏感性

> **本目录是 v1.7 release 的关键决策证据**：证明 C_VOLATILITY_BREAKOUT 的 +2.87% alpha 在真实交易成本下仍然成立（slippage ≤ 10bps + taker fee ≤ 7bps）。**结论已并入 README 风险段 + 文档 §4.1**，这里是 raw 数据 + 复现脚本。

## 📁 文件

| 文件 | 内容 |
|---|---|
| `scan.py` | 复现脚本（112 行 Python）：对 C 策略在 4 个 slippage × 4 个 fee × 2 个 symbol = 10 次回测 |
| `result.txt` | 上次运行（2026-07-16 00:39）的完整输出 |

## 🔁 复现命令

```bash
cd /home/zzzx47/.openclaw/workspace
python3 -u okx/data/experiments/v17-fragility/scan.py > okx/data/experiments/v17-fragility/result.txt
```

依赖：
- 本地 1h K 线缓存（`okx/data/market/{BTC,ETH}-USDT-SWAP/1h.parquet`，已 gitignore，不打 OKX API）
- `okx` Python 包（项目根 import）
- 111/111 tests 通过

## 🎯 扫描轴

| 轴 | 范围 | 数量 |
|---|---|---|
| Slippage（BTC, fee=5.5bps）| 5 / 10 / 15 / 20 bps | 4 跑 |
| Fee（BTC, slip=10bps）| 4.5 / 5.5 / 7.0 / 8.5 bps | 4 跑 |
| ETH 复测 | slip=5 / 10 bps | 2 跑 |

## 📊 关键结论（详细数据见 result.txt）

- **C 的 alpha 活门：slippage ≤ 10bps**（slip 5 → +2.59%；slip 10 → -5.48%；slip 15 → -8.94% 直接穿）
- **fee 容忍度 ≤ 7bps**（4.5-7.0bps viable；8.5bps 破）
- **ETH 比 BTC 更耐滑点**（slip 10 仍 +14.67pp vs ETH 现货），但绝对收益仍负

→ **直接对应 `data/Phase 2 Experimental Evaluation.md` §4.1 的 4 条上 LIVE 硬性门**：

1. market slippage ≤ 10bps
2. taker fee ≤ 7bps
3. 仅 BTC-USDT-SWAP 上线，ETH 默认 disable
4. 初始仓位 ≤ 协议最大 × 30%

## ⚠️ 已知陷阱

- `BacktestResult.metrics()` 返回的 `_pct` 字段**已是百分比形式**（如 `total_return_pct = 2.87`），不要 `×100`
- `win_rate` 是 **property** 返回 fraction（0.44），要 ×100 才得到百分比
- 跑前清 pycache：`find . -name __pycache__ -type d -exec rm -rf {} +`
- 数据是确定性的（同代码 + 同数据 = 同输出），但 K 线数据如果升级 cache 会变，重跑时建议带时间戳

## 📅 版本历史

| 时间 | 事件 |
|---|---|
| 2026-07-16 00:39 | v1.7 首次扫描，bug fix（×100 多余乘法）后输出正确 |
| 2026-07-16 01:12 | 移到 `data/experiments/v17-fragility/` 入仓 |