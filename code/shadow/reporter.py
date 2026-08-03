# -*- coding: utf-8 -*-
"""
L4 Shadow Runner · reporter

职责：格式化 SignalDivergence 输出为 console / json 字符串。
Week 1 MVP：console 用 emoji + 关键字段，json 完整输出。
Week 2+：加 Telegram alert + DB persistence。
"""
import json
from typing import Literal

from okx.code.shadow.comparator import SignalDivergence


# ──────────────────────────────────────────────────────────────
# Emoji per alert level
# ──────────────────────────────────────────────────────────────

_EMOJI = {
    "ok": "✅",
    "warn": "⚠️",
    "alert": "🔴",
}


def report(
    divergence: SignalDivergence,
    *,
    mode: Literal["console", "json"] = "console",
) -> str:
    """格式化 divergence 输出。

    Args:
        divergence: comparator 的输出
        mode: "console" (human-readable) | "json" (machine-readable)

    Returns:
        formatted string
    """
    if mode == "json":
        return _report_json(divergence)
    return _report_console(divergence)


def _report_console(d: SignalDivergence) -> str:
    emoji = _EMOJI.get(d.alert_level, "❓")
    lines = [
        f"{emoji} L4 Shadow Runner · divergence report",
        f"   alert_level:      {d.alert_level}",
        f"   divergence_score: {d.divergence_score:.4f}",
        f"   direction_match:  {d.direction_match}",
        f"   sl_diff_bps:      {d.sl_diff_bps:.2f}",
        f"   tp_diff_bps:      {d.tp_diff_bps:.2f}",
        f"   confidence_diff:  {d.confidence_diff:.4f}",
    ]
    if d.notes:
        lines.append("   notes:")
        for n in d.notes:
            lines.append(f"     - {n}")
    return "\n".join(lines)


def _report_json(d: SignalDivergence) -> str:
    return json.dumps(d.to_dict(), indent=2, ensure_ascii=False)