#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_live_shadow.py · L4 Shadow Runner 集成入口

目的：单周期运行 backtest vs live signal 对比。
- 读 state/live_signals.jsonl → actual signal
- 跑 SignalEngine.check_ema20_signal（mock market for MVP）→ expected signal
- compare_signals(expected, actual)
- report(console + JSON log) → state/shadow_logs/

用法：
  ./run.sh scripts/run_live_shadow.py
  或
  PYTHONPATH=.. python3 scripts/run_live_shadow.py

MVP 范围（Week 1）：
  - Strategy A only
  - BTC-USDT-SWAP only
  - Mock K-lines（待 D5+ 后接真实 historical data）
  - Console + JSON 输出

v1.0 ship (2026-08-03): 初版 end-to-end 集成
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

# Setup path: scripts/ -> okx/ -> workspace/
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from okx.code.shadow.comparator import compare_signals
from okx.code.shadow.live_runner import load_last_live_signal
from okx.code.shadow.reporter import report
from okx.code.signal import Signal, SignalEngine


def build_synthetic_klines(n: int = 120, base: float = 50000.0):
    """构造合成 K-lines（mock backtest 用）。

    Week 1 MVP：用合成数据测试 end-to-end pipeline。
    Week 2+：接真实 historical K-lines (cached parquet)。
    """
    candles = []
    for i in range(n):
        ts = i * 3600000
        if i < 90:
            close = base + ((i * 7) % 21 - 10)
            high = close + 15
            low = close - 15
            vol = 800 + ((i * 13) % 200)
        else:
            close = base + (i - 90) * 30
            high = close + 60
            low = close - 60
            vol = 1500 + (i - 90) * 80
        candles.append([ts, base, high, low, close, vol, str(base), str(base)])
    return candles


def get_expected_signal() -> Signal | None:
    """Week 1 MVP：用合成 K-lines 跑 SignalEngine.check_ema20_signal。

    Week 2+：接 `code/backtest/data_loader.load(symbol, bar)` 真实数据。
    """
    market = MagicMock()
    market.get_candles.return_value = build_synthetic_klines()
    engine = SignalEngine(market_api=market, config=None)
    return engine.check_ema20_signal("BTC-USDT-SWAP", None)


def atomic_write_text(path: Path, content: str) -> None:
    """Atomic write pattern (per MEMORY/OKX.md portfolio atomic write).

    写入流程：
      1. 写临时文件（os.O_CREAT|O_TRUNC|O_WRONLY）
      2. fsync 刷盘
      3. os.replace 原子 rename

    失败语义：
      - 写入过程中抛异常 → 清理 tmp 文件 + re-raise
      - 替换成功 → 原文件保留（除非本次是新文件创建）

    Args:
        path: 目标文件路径
        content: 写入内容（str）
    """
    tmp_path = Path(str(path) + ".tmp")
    try:
        fd = os.open(
            str(tmp_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o644,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            # 写失败：确保 fd 关闭（fdopen 在 with 退出时会关）
            raise
    except Exception:
        # 清理 tmp 文件，避免污染
        try:
            os.unlink(str(tmp_path))
        except OSError:
            pass
        raise

    # 原子 rename
    os.replace(tmp_path, path)


def main():
    """单周期：expected vs actual → compare → report + log。"""
    expected_signal = get_expected_signal()
    actual_signal = load_last_live_signal()

    expected_list = [expected_signal] if expected_signal else []
    actual_list = [actual_signal] if actual_signal else []

    divergence = compare_signals(expected_list, actual_list)

    # Console 输出
    print(report(divergence, mode="console"))
    print()

    # JSON log → 使用脚本所在位置的绝对路径（不依赖 cwd）
    # scripts/run_live_shadow.py → parents[1] = okx/ (state/ 的实际位置)
    project_root = Path(__file__).resolve().parents[1]
    log_dir = project_root / "state" / "shadow_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    log_file = log_dir / f"shadow_{divergence.alert_level}_{timestamp}.json"
    # atomic write: 防止脚本崩溃时留下 partial JSON
    atomic_write_text(log_file, report(divergence, mode="json"))

    # exit code: 0 if ok/warn, 1 if alert (供 cron 可监控)
    return 0 if divergence.alert_level in ("ok", "warn") else 1


if __name__ == "__main__":
    sys.exit(main())