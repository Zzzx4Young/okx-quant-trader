# -*- coding: utf-8 -*-
"""L4 Shadow Runner · backtest vs live signal-layer divergence 检测。

目的：在 signal 层（不是 trade/PnL 层）实时对比 backtest vs live 策略输出，
捕捉 divergence > threshold 即报警。这是"backtest 可信度"的根本验证。

MVP 范围 (Week 1)：
  - Strategy A only
  - BTC-USDT-SWAP only
  - 15m timeframe only
  - Console + JSON 输出（不做 Telegram/DB）

设计参考：LEAN Backtesting/Live unified engine · Freqtrade dry-run parity。

v1.9.0 ship (2026-08-03): 初版 MVP（comparator + reporter）
"""

from okx.code.shadow.comparator import SignalDivergence, compare_signals
from okx.code.shadow.reporter import report

__all__ = ["SignalDivergence", "compare_signals", "report"]