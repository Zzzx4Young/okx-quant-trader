# Agent Context Index

> **本目录是为 AI agent 准备的参考上下文**，不是给人类的用户文档。
> 用户文档见 `docs/`（SIGNALS / WORKFLOW / NOTIFIER / BACKTEST_DESIGN 等）。
> Constitution / 角色定义见 `prompts/`（JOB-DISCIPLINE / trade-rule）。

## 📁 文件清单与用途

| 文件 | 容量 | 用途 | 何时查阅 |
|---|---|---|---|
| `basic_usage.py` | 1.9KB | OKX V5 API 最简使用示例（公共 + 私有端点） | AI 第一次接触 OKXClient 接口时 |
| `backtest_system_design_report_V2.1.md` | 15KB | **回测引擎 v2.1 设计稿（最新）** | 涉及撮合/性能/Tranche fill 时优先看 |
| `backtest_system_design_report_V2.md` | 41KB | v2 详细设计文档（演进记录） | 需要了解 v2 设计权衡/历史决策时 |
| `backtest_system_design_report.md` | 37KB | v1 原始设计（已废弃，保留作历史） | 仅追溯回测系统演化时 |

## 🎯 优先级建议（节省 token）

1. **新任务（涉及回测改动）**：先看 V2.1（短）+ basic_usage 看 API 用法
2. **debug 实盘 vs 回测不一致**：V2.1 + V2 对比，重点看 Phase 2 撮合逻辑
3. **理解 OKXClient**：直接 `from okx.code import OKXClient` + 跑 basic_usage.py 比读文档更直接

## ⚠️ 内容时效注意

- **V2.1 = 当前真相**：代码实现以 `code/backtest/*.py` 为准，文档略有时延
- **V1/V2 = 设计稿**：可能与最终代码有差异（实现过程中发现 bug 修复了文档没回写）
- 涉及代码变更时**以代码为权威**，文档为参考
