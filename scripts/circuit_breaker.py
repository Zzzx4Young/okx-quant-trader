# -*- coding: utf-8 -*-
"""
Drawdown + Consecutive Loss Circuit Breaker（P0 防守层）

设计目标：
    在 Regime Filter（择时闸）之外加一层"事中防御"——
    当账户处于严重亏损状态时，自动拒绝开新仓，等人工 review。

触发维度：
    1. max_drawdown_pct   净值回撤（peak → current）超过阈值
    2. consecutive_loss_days  连续亏损日数超过阈值

数据来源：
    - 实时 equity：state/risk_metrics_cache.json（由 risk_monitor.py fetch_snapshot 写入）
    - 连续亏损日数：code/portfolio.py Portfolio.is_meltdown(max_consecutive_losses)
    - 本地状态：state/circuit_breaker_state.json（peak_equity + 历史记录）

State schema（version=1.0.0）：
    {
        "version": "1.0.0",
        "peak_equity_usd": float,
        "peak_recorded_at": iso,
        "last_equity_usd": float,
        "last_checked_at": iso,
        "meltdown_history": [
            {"at": iso, "type": "drawdown"|"consecutive_loss",
             "current_value": float, "threshold": float,
             "level": "warning"|"critical",
             "action": "skip_signal",
             "note": str}
        ]
    }

失效语义（fail-closed）：
    - 读不到 risk_metrics_cache.json → 默认阻断 + log
    - 读不到本 state 文件 → 启动时直接初始化 peak = current equity
    - API 异常 → 复用 last_known peak，标 warning 但不阻断

测试入口：tests/test_circuit_breaker.py
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


# ──────────── 阈值常量 ────────────

# 与 risk_thresholds.py 分离：circuit breaker 是 **结构性硬阻断**（不是即时告警）
# critical 阈值直接 skip signal + 写 heartbeat
@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Circuit breaker 阈值配置

    默认值（基于 demo 实证 + BTC-only 5x leverage 经验）：
        - max_drawdown_warn 10%：连续回撤但 Kelly 还能恢复，警告
        - max_drawdown_crit 20%：必须人工 review，阻断新信号
        - consec_loss_warn   3 天：观察，警告
        - consec_loss_crit   5 天：连续 5 天净亏，阻断

    风险偏好：宁可早停，不可深套
    """
    max_drawdown_warn_pct: float = 0.10
    max_drawdown_crit_pct: float = 0.20
    consec_loss_warn: int = 3
    consec_loss_crit: int = 5

    def crit_breached(self, current_dd_pct: float, consec_loss: int) -> bool:
        return (current_dd_pct >= self.max_drawdown_crit_pct
                or consec_loss >= self.consec_loss_crit)


DEFAULT_CONFIG = CircuitBreakerConfig()


# ──────────── 数据结构 ────────────

@dataclass
class CircuitBreakerState:
    """持久化状态（写 state/circuit_breaker_state.json）"""
    peak_equity_usd: float
    peak_recorded_at: str
    last_equity_usd: float
    last_checked_at: str
    meltdown_history: list = field(default_factory=list)
    config: dict = field(default_factory=lambda: {
        "max_drawdown_warn_pct": DEFAULT_CONFIG.max_drawdown_warn_pct,
        "max_drawdown_crit_pct": DEFAULT_CONFIG.max_drawdown_crit_pct,
        "consec_loss_warn": DEFAULT_CONFIG.consec_loss_warn,
        "consec_loss_crit": DEFAULT_CONFIG.consec_loss_crit,
    })

    @property
    def current_drawdown_pct(self) -> float:
        """当前回撤（positive = 在亏损区间）"""
        if self.peak_equity_usd <= 0:
            return 0.0
        return max(0.0, (self.peak_equity_usd - self.last_equity_usd) / self.peak_equity_usd)


@dataclass
class CircuitBreakerDecision:
    """单次 check 的决策结果（signal_runner 调用方使用）"""
    skip_signal: bool
    reason: str
    level: str  # "ok" | "warning" | "critical"
    current_dd_pct: float
    current_equity_usd: float
    peak_equity_usd: float
    consec_loss_days: int
    triggered_rules: list = field(default_factory=list)  # list of strings


# ──────────── 文件路径解析 ────────────

def _state_dir() -> Path:
    """解析 state 目录（与 Portfolio/Config 一致）"""
    # circuit_breaker.py 在 okx/scripts/ → state/ 在 okx/state/
    return Path(__file__).resolve().parent.parent / "state"


def _state_file() -> Path:
    return _state_dir() / "circuit_breaker_state.json"


def _risk_metrics_cache() -> Path:
    return _state_dir() / "risk_metrics_cache.json"


# ──────────── 核心逻辑 ────────────

def load_state() -> Optional[CircuitBreakerState]:
    """读 state 文件，缺失返回 None"""
    p = _state_file()
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return CircuitBreakerState(
            peak_equity_usd=float(d["peak_equity_usd"]),
            peak_recorded_at=d["peak_recorded_at"],
            last_equity_usd=float(d["last_equity_usd"]),
            last_checked_at=d["last_checked_at"],
            meltdown_history=d.get("meltdown_history", []),
            config=d.get("config", {}),
        )
    except Exception as e:
        logger.warning(f"circuit_breaker state 读取失败 ({e}) → 视为未初始化")
        return None


def save_state(state: CircuitBreakerState) -> None:
    """原子写 state 文件（避免 signal_runner 被异常中断时数据损坏）"""
    p = _state_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "version": "1.0.0",
            "peak_equity_usd": state.peak_equity_usd,
            "peak_recorded_at": state.peak_recorded_at,
            "last_equity_usd": state.last_equity_usd,
            "last_checked_at": state.last_checked_at,
            "meltdown_history": state.meltdown_history,
            "config": state.config,
        }, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def read_current_equity() -> Optional[float]:
    """从 risk_metrics_cache.json 读取当前 equity（fail-closed: 读不到返回 None）"""
    p = _risk_metrics_cache()
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        eq = data.get("data", {}).get("equity_usd")
        return float(eq) if eq is not None and eq > 0 else None
    except Exception as e:
        logger.warning(f"risk_metrics_cache 读取失败: {e}")
        return None


def check(
    equity_usd: float,
    consec_loss_days: int,
    state: Optional[CircuitBreakerState] = None,
    config: CircuitBreakerConfig = DEFAULT_CONFIG,
    now_iso: Optional[str] = None,
) -> tuple[CircuitBreakerDecision, CircuitBreakerState]:
    """单次 circuit breaker check

    :param equity_usd: 当前账户净值（USD）
    :param consec_loss_days: 连续亏损日数（≥0）
    :param state: 现有 state；None = 自动 load
    :param config: 阈值配置（默认 10/20% DD，3/5 consec loss）
    :param now_iso: 测试用时间戳（默认 = now UTC）
    :return: (decision, new_state) —— 调用方写 new_state 持久化
    """
    now = now_iso or datetime.now(timezone.utc).isoformat()
    st = state if state is not None else (load_state() or _init_state(equity_usd, now))

    # 更新 peak: high water mark 模式（只升不降）
    new_peak = max(st.peak_equity_usd, equity_usd)
    peak_updated = new_peak > st.peak_equity_usd
    st.peak_equity_usd = new_peak
    if peak_updated:
        st.peak_recorded_at = now
    st.last_equity_usd = equity_usd
    st.last_checked_at = now

    # 计算回撤
    current_dd = st.current_drawdown_pct

    # 评估
    triggered = []
    level = "ok"
    reason_parts = []

    # 1. 净值回撤
    if current_dd >= config.max_drawdown_crit_pct:
        triggered.append(f"drawdown={current_dd*100:.1f}% >= crit {config.max_drawdown_crit_pct*100:.0f}%")
        reason_parts.append(f"DD {current_dd*100:.1f}% ≥ {config.max_drawdown_crit_pct*100:.0f}% (crit)")
        level = "critical"
    elif current_dd >= config.max_drawdown_warn_pct:
        triggered.append(f"drawdown={current_dd*100:.1f}% >= warn {config.max_drawdown_warn_pct*100:.0f}%")
        reason_parts.append(f"DD {current_dd*100:.1f}% ≥ {config.max_drawdown_warn_pct*100:.0f}% (warn)")
        level = "warning"

    # 2. 连续亏损
    if consec_loss_days >= config.consec_loss_crit:
        triggered.append(f"consec_loss={consec_loss_days} >= crit {config.consec_loss_crit}")
        reason_parts.append(f"连亏 {consec_loss_days} 天 ≥ {config.consec_loss_crit} (crit)")
        level = "critical"
    elif consec_loss_days >= config.consec_loss_warn:
        if level != "critical":
            level = "warning"
        triggered.append(f"consec_loss={consec_loss_days} >= warn {config.consec_loss_warn}")
        reason_parts.append(f"连亏 {consec_loss_days} 天 ≥ {config.consec_loss_warn} (warn)")

    # 决策
    skip = level == "critical"

    # 记录历史（每次 critical 都打点；warning 不打点避免噪声）
    if skip:
        st.meltdown_history.append({
            "at": now,
            "type": "drawdown" if current_dd >= config.max_drawdown_crit_pct else "consecutive_loss",
            "current_value": current_dd if current_dd >= config.max_drawdown_crit_pct else consec_loss_days,
            "threshold": config.max_drawdown_crit_pct if current_dd >= config.max_drawdown_crit_pct else config.consec_loss_crit,
            "level": "critical",
            "action": "skip_signal",
            "note": f"equity={equity_usd:.2f} peak={new_peak:.2f} consec_loss={consec_loss_days}",
        })
        # 防止 history 无限增长：保留最近 50 条
        st.meltdown_history = st.meltdown_history[-50:]

    reason = "ok"
    if level == "warning":
        reason = "warn: " + "; ".join(reason_parts)
    elif level == "critical":
        reason = "BLOCKED: " + "; ".join(reason_parts)
    else:
        reason = "ok"

    return CircuitBreakerDecision(
        skip_signal=skip,
        reason=reason,
        level=level,
        current_dd_pct=current_dd,
        current_equity_usd=equity_usd,
        peak_equity_usd=new_peak,
        consec_loss_days=consec_loss_days,
        triggered_rules=triggered,
    ), st


def _init_state(equity_usd: float, now_iso: str) -> CircuitBreakerState:
    """首次启动：peak = current equity"""
    return CircuitBreakerState(
        peak_equity_usd=equity_usd,
        peak_recorded_at=now_iso,
        last_equity_usd=equity_usd,
        last_checked_at=now_iso,
    )


def compute_consecutive_losses(closed_positions: Iterable[dict]) -> int:
    """跨日连续亏损计数（从 closed_positions 推算，不是从 daily_stats）

    portfolio.py 的 daily_stats.consecutive_losses 是 daily reset —— 跨日会归零，
    对风控不利。防守从 closed_positions 推算跨日的连续亏损，被一笔盈利打断。

    :param closed_positions: portfolio._data['closed_positions']（dict[]）
    :return: 当前连亏笔数（含当日，不含今日以前未完结的）
    """
    sorted_pos = sorted(
        (p for p in closed_positions if p.get("closed_at")),
        key=lambda p: p["closed_at"],
        reverse=True,  # newest first
    )
    count = 0
    for p in sorted_pos:
        if (p.get("realized_pnl") or 0) < 0:
            count += 1
        else:
            break
    return count


# ──────────── CLI 调试 ────────────


def main() -> None:
    """CLI: 显示当前状态 + 单次 check"""
    import argparse
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")



    parser = argparse.ArgumentParser(description="Circuit breaker 状态 + 单次 check")
    parser.add_argument("--equity-usd", type=float, default=None,
                        help="手动指定 equity（不指定则从 risk_metrics_cache.json 读）")
    parser.add_argument("--consec-loss", type=int, default=0, help="手动指定连亏天数")
    args = parser.parse_args()

    equity = args.equity_usd if args.equity_usd is not None else read_current_equity()
    if equity is None:
        print("❌ 无法获取 equity（risk_metrics_cache.json 缺失或 equity=0）")
        sys.exit(2)

    decision, new_state = check(equity, args.consec_loss)
    print(json.dumps({
        "decision": {
            "skip_signal": decision.skip_signal,
            "level": decision.level,
            "reason": decision.reason,
            "current_dd_pct": round(decision.current_dd_pct * 100, 2),
            "current_equity_usd": round(decision.current_equity_usd, 2),
            "peak_equity_usd": round(decision.peak_equity_usd, 2),
            "consec_loss_days": decision.consec_loss_days,
            "triggered_rules": decision.triggered_rules,
        },
        "state": {
            "peak_equity_usd": round(new_state.peak_equity_usd, 2),
            "peak_recorded_at": new_state.peak_recorded_at,
            "last_checked_at": new_state.last_checked_at,
            "meltdown_history_count": len(new_state.meltdown_history),
        },
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
