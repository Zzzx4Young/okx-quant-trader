"""Signal direction filter — Phase 3B Track A implementation.

Motivation (2026-07-28 Phase 3B bootstrap):
- Strategy A in DOWN regime (165 LONG vs 39 SHORT):
  - LONG mean: +$13.02/trade ✅
  - SHORT mean: -$23.67/trade ❌ (39 trades × -$24 = -$923)
  → A's "alpha in DOWN" comes from LONG, not SHORT
- Strategy C in SIDE regime (138 LONG vs 138 SHORT):
  - LONG mean: +$6.78/trade (CI crosses 0, noise)
  - SHORT mean: +$27.47/trade ✅ (CI mostly positive)
  → C's "alpha in SIDE" comes from SHORT only

This module implements a direction filter that:
1. Computes current BTC regime (DOWN/UP/SIDE)
2. Rejects signals whose direction is historically unprofitable in that regime

Design: fail-closed (rejection = no trade). When in doubt, reject.

Reference:
- data/phase3b/bootstrap_report_direction.md (full analysis)
- code/regime_filter.py::recommended_strategy() (regime computation)
"""
from typing import Callable, Optional

from okx.code.regime_filter import recommended_strategy


# ────────────────────────────────────────────────────────────────────
# Direction × Regime rules (2026-07-28 Phase 3B data-mining)
# ────────────────────────────────────────────────────────────────────
#
# Key: regime string returned by recommended_strategy()
#   - "A" → DOWN regime (90d_ret < -5% AND ema_ratio < 1.0)
#   - "UP" → strong UP regime (90d_ret > +10% AND ema_ratio > 1.02)
#   - "SIDE" → other / mixed
#   - None → data insufficient
#
# Value: list of allowed directions in that regime
#   - [] = reject all (existing baseline behavior)
#   - ["long"] = only LONG allowed
#   - ["short"] = only SHORT allowed
#   - ["long", "short"] = both allowed (no filter)
#
DIRECTION_REGIME_RULES: dict[str, dict[Optional[str], list[str]]] = {
    # Strategy A: alpha source is LONG in DOWN (拒 SHORT in DOWN)
    "A_EMA20_BREAKOUT": {
        "A": ["long"],       # DOWN: 只接 LONG，拒 SHORT（历史 -$24/trade）
        "UP": [],            # UP: 全部拒（baseline 一致 · Phase 3A 也拒 UP）
        "SIDE": [],          # SIDE: 全部拒（baseline 一致）
        None: [],            # 数据不足：拒
    },
    # Strategy C: alpha source is SHORT in SIDE (拒 LONG in SIDE)
    "C_VOLATILITY_BREAKOUT": {
        "A": [],             # DOWN: 拒（C in A regime CI 完全负 · Phase 3B 验证）
        "UP": [],            # UP: 全部拒（baseline 一致）
        "SIDE": ["short"],   # SIDE: 只接 SHORT，拒 LONG（LONG CI [-30, +46] noise）
        None: [],            # 数据不足：拒
    },
    # Strategy B: Kelly 永久禁用，保持完全拒
    "B_BB_RSI_REVERSION": {
        "A": [],
        "UP": [],
        "SIDE": [],
        None: [],
    },
    # Strategy D: soft-removed，保持完全拒
    "D_FUNDING_RATE_REVERSAL": {
        "A": [],
        "UP": [],
        "SIDE": [],
        None: [],
    },
}


def is_direction_allowed(strategy_id: str, regime: Optional[str], direction: str) -> bool:
    """检查 strategy × regime 下 direction 是否允许入场。

    :param strategy_id: 策略全名（STRATEGIES dict key）
    :param regime: regime_filter 推荐输出 ("A" / "UP" / "SIDE" / None)
    :param direction: "long" / "short"
    :return: True 表示允许入场，False 表示拒
    """
    rules = DIRECTION_REGIME_RULES.get(strategy_id, {})
    allowed = rules.get(regime, [])
    return direction in allowed


# ────────────────────────────────────────────────────────────────────
# Strategy function wrapper
# ────────────────────────────────────────────────────────────────────

def make_filtered_strategy(strategy_id: str, base_strategy: Callable) -> Callable:
    """包装 strategy function，注入 direction × regime filter。

    BacktestEngine 通过 signal_provider 调用 strategy function:
        signal = provider(klines, i, indicators, position, funding, inst_id)
        signal ∈ {"long", "short", "close", None}

    本 wrapper 在原始 signal 基础上加 direction filter:
        1. 调 base_strategy 得到原始 signal
        2. 若 signal 不是 long/short → 直接返回（None / close 不需过滤）
        3. 调 recommended_strategy() 计算当前 regime
        4. 查 DIRECTION_REGIME_RULES 判断 direction 是否允许
        5. 不允许 → 返回 None（拒入场）

    Performance note: 每次 bar 调用都 recompute regime（O(N) per bar）。
    Total: O(N²) per backtest. 对 ~600 bars 是 ~360k ops，秒级可接受。
    """
    def wrapper(klines, i, indicators, position, funding, inst_id):
        base_signal = base_strategy(klines, i, indicators, position, funding, inst_id)

        # 只过滤 long/short 信号；close / None 透传
        if base_signal not in ("long", "short"):
            return base_signal

        # 计算当前 regime（用截至 i bar 的历史 klines）
        try:
            regime_str, _, _ = recommended_strategy(klines.iloc[: i + 1])
        except Exception:
            # 任何异常 → fail-closed：拒
            return None

        # 应用 direction filter
        if not is_direction_allowed(strategy_id, regime_str, base_signal):
            return None

        return base_signal

    return wrapper


__all__ = [
    "DIRECTION_REGIME_RULES",
    "is_direction_allowed",
    "make_filtered_strategy",
]