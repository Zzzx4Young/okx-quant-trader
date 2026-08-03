# -*- coding: utf-8 -*-
"""L4 Shadow Runner · live signal reader。

读取 live runner 写入的 state/live_signals.jsonl，提取最近一个 signal
用于与 backtest "expected signal" 对比。

设计：
  - JSONL 格式（1 signal per line）
  - 读最后非空行（最新 signal）
  - STATE_DIR 可被 monkeypatch 覆盖（测试友好）
"""
import json
import sys
from pathlib import Path
from typing import Optional

# Setup path for okx package
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from okx.code.signal import Signal


# 默认与 runner._log_signal 同路径；测试可通过 monkeypatch 覆盖
# 注意: log_path 必须动态计算（monkeypatch STATE_DIR 才生效）
STATE_DIR = Path("state")


def load_last_live_signal() -> Optional[Signal]:
    """读取 state/live_signals.jsonl 最后非空行 → Signal。

    Returns:
        Signal (最新) or None (文件不存在 / 全空)
    """
    # 动态计算 log_path：让 monkeypatch STATE_DIR 在测试中生效
    log_path = STATE_DIR / "live_signals.jsonl"
    if not log_path.exists():
        return None

    last_line = None
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    last_line = line
    except Exception:
        return None

    if last_line is None:
        return None

    try:
        data = json.loads(last_line)
    except json.JSONDecodeError:
        return None

    return Signal(
        strategy=data["strategy"],
        symbol=data["symbol"],
        direction=data["direction"],
        entry_price=data["entry_price"],
        sl_price=data["sl_price"],
        tp_price=data["tp_price"],
        leverage=data["leverage"],
        size=data["size"],
        confidence=data["confidence"],
        reason=data["reason"],
        kline_time=data["kline_time"],
    )