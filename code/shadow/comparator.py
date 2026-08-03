# -*- coding: utf-8 -*-
"""
L4 Shadow Runner · comparator (v1.1 · 2026-08-03)

职责：比较 expected signals (backtest) vs actual signals (live)，
计算 divergence_score + alert_level。

v1.1 fixes (per self-audit):
  - Bug #1: 多 signal 场景用 zip-pair + count-mismatch penalty
  - Bug #2: confidence_diff 计入 divergence_score
  - Bug #3: leverage + size 字段纳入比对

设计要点：
  - 0-1 bounded divergence_score（0=identical, 1=完全分歧）
  - 多 signal 场景：max score across pairs + count-mismatch penalty
  - symbol mismatch 直接 1.0（不可比）
  - empty lists 视为 acceptable（两 regime 都拒入场 = 没信号合理）

Week 1 MVP (2026-08-03)：初版仅 signal 层。
Week 2+：trade-level replay + pnl-level divergence。
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from okx.code.signal import Signal


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

DEFAULT_WARN_THRESHOLD = 0.05   # 5%
DEFAULT_ALERT_THRESHOLD = 0.15  # 15%

PRICE_DIFF_NORM_BPS = 1000.0    # 1000bps = 10% price diff → price_component 1.0
CONFIDENCE_DIFF_NORM = 0.5      # confidence_diff ≥ 0.5 → confidence_component 1.0

# v1.1: weights sum to 1.0
DIRECTION_WEIGHT = 0.40
PRICE_WEIGHT = 0.25
CONFIDENCE_WEIGHT = 0.15
LEVERAGE_WEIGHT = 0.10
SIZE_WEIGHT = 0.10

COUNT_MISMATCH_PENALTY = 0.30  # multi-signal 场景：count 不一致加 0.3


# ──────────────────────────────────────────────────────────────
# Result dataclass
# ──────────────────────────────────────────────────────────────

@dataclass
class SignalDivergence:
    """comparator 输出：可序列化为 JSON，可喂给 reporter。"""
    direction_match: bool
    sl_diff_bps: float
    tp_diff_bps: float
    confidence_diff: float
    leverage_diff: int
    size_diff: float
    divergence_score: float    # [0, 1]
    alert_level: str           # "ok" / "warn" / "alert"
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "direction_match": self.direction_match,
            "sl_diff_bps": self.sl_diff_bps,
            "tp_diff_bps": self.tp_diff_bps,
            "confidence_diff": self.confidence_diff,
            "leverage_diff": self.leverage_diff,
            "size_diff": self.size_diff,
            "divergence_score": self.divergence_score,
            "alert_level": self.alert_level,
            "notes": self.notes,
        }


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _compare_pair(
    exp_sig: Signal,
    act_sig: Signal,
    slippage_bps: float,
) -> Tuple[float, list]:
    """单对 signal 比对 → (pair_score, pair_notes)."""
    pair_notes = []

    # ── Symbol mismatch → 不可比 → max score ──
    if exp_sig.symbol != act_sig.symbol:
        pair_notes.append(
            f"symbol_mismatch · expected={exp_sig.symbol} actual={act_sig.symbol}"
        )
        return 1.0, pair_notes

    # ── 5 维分量（每维 0-1）──
    # 1. direction
    direction_component = 0.0 if exp_sig.direction == act_sig.direction else 1.0
    if direction_component > 0:
        pair_notes.append(
            f"direction_mismatch · expected={exp_sig.direction} actual={act_sig.direction}"
        )

    # 2. price (sl/tp) diff in bps
    base = act_sig.entry_price if act_sig.entry_price > 0 else 1.0
    sl_diff_bps = abs(exp_sig.sl_price - act_sig.sl_price) / base * 10000.0
    tp_diff_bps = abs(exp_sig.tp_price - act_sig.tp_price) / base * 10000.0
    price_component_bps = max(sl_diff_bps, tp_diff_bps)
    price_component = min(price_component_bps / PRICE_DIFF_NORM_BPS, 1.0)
    if sl_diff_bps > slippage_bps * 2:
        pair_notes.append(
            f"sl_diff_exceeds_2x_slippage · diff={sl_diff_bps:.1f}bps slippage={slippage_bps:.1f}"
        )
    if tp_diff_bps > slippage_bps * 4:
        pair_notes.append(f"tp_diff_exceeds_4x_slippage · diff={tp_diff_bps:.1f}bps")

    # 3. confidence
    confidence_diff = abs(exp_sig.confidence - act_sig.confidence)
    confidence_component = min(confidence_diff / CONFIDENCE_DIFF_NORM, 1.0)

    # 4. leverage (v1.1: 加入比对)
    leverage_diff = abs(exp_sig.leverage - act_sig.leverage)
    leverage_component = 0.0 if leverage_diff == 0 else 1.0
    if leverage_component > 0:
        pair_notes.append(
            f"leverage_mismatch · expected={exp_sig.leverage} actual={act_sig.leverage}"
        )

    # 5. size (v1.1: 加入比对)
    size_diff = abs(exp_sig.size - act_sig.size)
    size_component = 0.0 if size_diff < 1e-9 else 1.0
    if size_component > 0:
        pair_notes.append(
            f"size_mismatch · expected={exp_sig.size} actual={act_sig.size}"
        )

    # ── Weighted score (v1.1: 5 维度) ──
    score = (
        direction_component * DIRECTION_WEIGHT
        + price_component * PRICE_WEIGHT
        + confidence_component * CONFIDENCE_WEIGHT
        + leverage_component * LEVERAGE_WEIGHT
        + size_component * SIZE_WEIGHT
    )
    score = min(max(score, 0.0), 1.0)

    return score, pair_notes


def _aggregate_pair_results(
    pair_scores: List[float],
    pair_notes_list: List[List[str]],
    sl_diff_bps_total: float,
    tp_diff_bps_total: float,
    confidence_diff_total: float,
    leverage_diff_total: int,
    size_diff_total: float,
) -> Tuple[float, List[str]]:
    """聚合多对结果 → (score, aggregated_notes).

    策略：max(pair_scores) + count_mismatch_penalty
    """
    if not pair_scores:
        return 0.0, []

    max_score = max(pair_scores)
    notes = []
    for i, pn in enumerate(pair_notes_list):
        for n in pn:
            notes.append(f"pair[{i}] {n}")
    return max_score, notes


# ──────────────────────────────────────────────────────────────
# Main API
# ──────────────────────────────────────────────────────────────

def compare_signals(
    expected: List[Signal],
    actual: List[Signal],
    *,
    slippage_bps: float = 5.0,
    warn_threshold: float = DEFAULT_WARN_THRESHOLD,
    alert_threshold: float = DEFAULT_ALERT_THRESHOLD,
) -> SignalDivergence:
    """比较 expected (backtest) vs actual (live) signal 列表 (v1.1)。

    Args:
        expected: backtest 模拟应该产生的 signals
        actual: live runner 实际产生的 signals
        slippage_bps: live 默认滑点（用于判定 "acceptable 偏差" 阈值，仅记入 notes）
        warn_threshold: divergence_score 超过 → alert_level = "warn"
        alert_threshold: divergence_score 超过 → alert_level = "alert"

    Returns:
        SignalDivergence 包含 score + alert_level + notes
    """
    notes: List[str] = []

    # ── Case 1: 都空 → acceptable ──
    if not expected and not actual:
        return SignalDivergence(
            direction_match=True,
            sl_diff_bps=0.0,
            tp_diff_bps=0.0,
            confidence_diff=0.0,
            leverage_diff=0,
            size_diff=0.0,
            divergence_score=0.0,
            alert_level="ok",
            notes=["no_signals_to_compare · both regimes rejected entry"],
        )

    # ── Case 2: 长度不匹配 → 一方有信号一方没有 ──
    if not expected or not actual:
        notes.append(
            f"length_mismatch · expected={len(expected)} actual={len(actual)}"
        )
        return SignalDivergence(
            direction_match=False,
            sl_diff_bps=0.0,
            tp_diff_bps=0.0,
            confidence_diff=0.0,
            leverage_diff=0,
            size_diff=0.0,
            divergence_score=1.0,
            alert_level="alert",
            notes=notes,
        )

    # ── Case 3+: 多 signal 场景 (v1.1: zip-pair) ──
    n_expected = len(expected)
    n_actual = len(actual)
    count_mismatch = (n_expected != n_actual)

    if count_mismatch:
        notes.append(
            f"signal_count_mismatch · expected={n_expected} actual={n_actual}"
        )
        # 额外信号 missing
        if n_expected > n_actual:
            for sig in expected[n_actual:]:
                notes.append(
                    f"missing_in_actual · {sig.direction} {sig.symbol} kline={sig.kline_time}"
                )
        else:
            for sig in actual[n_expected:]:
                notes.append(
                    f"missing_in_expected · {sig.direction} {sig.symbol} kline={sig.kline_time}"
                )

    n_pairs = min(n_expected, n_actual)
    pair_scores = []
    pair_notes_list = []
    # 累加 fields 取 max/总和 (这里用 max)
    sl_diff_bps_max = 0.0
    tp_diff_bps_max = 0.0
    confidence_diff_max = 0.0
    leverage_diff_max = 0
    size_diff_max = 0.0
    direction_match_overall = True

    for i in range(n_pairs):
        exp_sig = expected[i]
        act_sig = actual[i]
        pair_score, pair_notes = _compare_pair(exp_sig, act_sig, slippage_bps)
        pair_scores.append(pair_score)
        pair_notes_list.append(pair_notes)

        # 累加差异字段 (用 max 聚合)
        if exp_sig.symbol == act_sig.symbol:
            base = act_sig.entry_price if act_sig.entry_price > 0 else 1.0
            sl = abs(exp_sig.sl_price - act_sig.sl_price) / base * 10000.0
            tp = abs(exp_sig.tp_price - act_sig.tp_price) / base * 10000.0
            sl_diff_bps_max = max(sl_diff_bps_max, sl)
            tp_diff_bps_max = max(tp_diff_bps_max, tp)
            confidence_diff_max = max(
                confidence_diff_max, abs(exp_sig.confidence - act_sig.confidence)
            )
            leverage_diff_max = max(
                leverage_diff_max, abs(exp_sig.leverage - act_sig.leverage)
            )
            size_diff_max = max(size_diff_max, abs(exp_sig.size - act_sig.size))
            if exp_sig.direction != act_sig.direction:
                direction_match_overall = False

    # 聚合 score
    aggregated_score, aggregated_notes = _aggregate_pair_results(
        pair_scores, pair_notes_list,
        sl_diff_bps_max, tp_diff_bps_max,
        confidence_diff_max, leverage_diff_max, size_diff_max,
    )
    notes.extend(aggregated_notes)

    # count_mismatch penalty
    if count_mismatch:
        aggregated_score = min(aggregated_score + COUNT_MISMATCH_PENALTY, 1.0)

    # alert_level
    if aggregated_score >= alert_threshold:
        alert_level = "alert"
    elif aggregated_score >= warn_threshold:
        alert_level = "warn"
    else:
        alert_level = "ok"

    return SignalDivergence(
        direction_match=direction_match_overall,
        sl_diff_bps=round(sl_diff_bps_max, 4),
        tp_diff_bps=round(tp_diff_bps_max, 4),
        confidence_diff=round(confidence_diff_max, 4),
        leverage_diff=leverage_diff_max,
        size_diff=round(size_diff_max, 9),
        divergence_score=round(aggregated_score, 6),
        alert_level=alert_level,
        notes=notes,
    )
