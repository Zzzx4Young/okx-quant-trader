# -*- coding: utf-8 -*-
"""
共享事中防御 gate（circuit_breaker + regime_filter）

历史与动机（避免再次漂移）：
    2026-07-24 P0 — circuit_breaker 闸加到 signal_runner.py cron 路径
    2026-07-25 P0 — 同一组闸加到 runner.py（生产 hot path：5min bash okx/run.sh run）
                  ⚠️ 但 signal_runner.py ⊕ runner.py 在 4 个点上漂移：
                     1) result key 名：regime_decision vs regime
                     2) cb block 时 write_heartbeat() 在 runner 路径不见（生产路径告警可见性回归）
                     3) cb result 缺 triggered_rules 字段（debug ergonomics）
                     4) cb ok/warn/block emoji 日志在 runner 路径不见（运维 grep 成本）
    2026-07-26    — 抽本模块 run_pre_signal_gates()，两入口共用同一 source of truth。
                     上述 4 处漂移全部修复（详见 okx/docs/LESSONS_LEARNED.md gates 段）。

调用点：
    - Runner._pre_signal_gates()    → 5min 生产 cron `bash okx/run.sh run`
    - signal_runner.run_at_next_bar() → 旧 hourly cron（offline 保留路径）

设计原则：
    - 纯函数：除 logger 与 circuit_breaker.save_state (gate 内部 state 持久化)
             外不写 I/O。Heartbeat 写 (Telegram / state/signal_runner.heartbeat)
             是 caller (signal_runner) 的 cron 报告职责，不在此模块。
    - Fail-open：任一闸异常 → log warning → continue；不因基础设施故障禁所有交易。
    - 单一 schema：两端都用 result["regime"] / result["circuit_breaker"]，不再有
                  decision / non-decision 两套命名。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

# 用模块引用而非 `from X import Y`：让 unittest.mock.patch() 在源模块的属性上
# patch 时能真的透过（每次属性访问都查源模块，本地不再 bind 一次性）。
from . import regime_filter as _regime_filter
from .backtest import data_loader as _data_loader
from . import portfolio as _portfolio
from okx.scripts import circuit_breaker as _cb

logger = logging.getLogger(__name__)


__all__ = [
    "run_pre_signal_gates",
    "_run_circuit_breaker_subgate",  # exposed for tests via mock
    "_run_regime_filter_subgate",    # exposed for tests via mock
]


def _run_circuit_breaker_subgate() -> Optional[Dict[str, Any]]:
    """跑 circuit_breaker 闸（cheap：JSON read ~ms）。

    :return: 决策 dict 含 level/skip_signal/reason/dd/equity/peak/consec_loss_days/
              triggered_rules；None 表示 fail-open（equity 不可读或异常）。
    """
    try:
        equity = _cb.read_current_equity()
        if equity is None:
            logger.warning("circuit_breaker: equity 不可读 → skip (fail-open)")
            return None

        portfolio = _portfolio.Portfolio()
        closed_positions = portfolio._data.get("closed_positions", [])
        consec_loss = _cb.compute_consecutive_losses(closed_positions)

        cb_decision, cb_state = _cb.check(
            equity_usd=equity,
            consec_loss_days=consec_loss,
        )
        _cb.save_state(cb_state)

        out: Dict[str, Any] = {
            "level": cb_decision.level,
            "skip_signal": cb_decision.skip_signal,
            "reason": cb_decision.reason,
            "current_dd_pct": round(cb_decision.current_dd_pct * 100, 2),
            "current_equity_usd": round(cb_decision.current_equity_usd, 2),
            "peak_equity_usd": round(cb_decision.peak_equity_usd, 2),
            "consec_loss_days": cb_decision.consec_loss_days,
            "triggered_rules": list(cb_decision.triggered_rules),  # 漂移修复 #3
        }
        # 漂移修复 #4：emoji 日志三档 (block / warn / ok)
        if cb_decision.skip_signal:
            logger.warning(
                f"🛑 circuit_breaker 阻断: {cb_decision.reason} | "
                f"equity=${cb_decision.current_equity_usd:.2f} "
                f"peak=${cb_decision.peak_equity_usd:.2f}"
            )
        elif cb_decision.level == "warning":
            logger.warning(
                f"⚠️ circuit_breaker 警告: {cb_decision.reason} | "
                f"DD={cb_decision.current_dd_pct*100:.1f}% / "
                f"连亏={cb_decision.consec_loss_days}天"
            )
        else:
            logger.info(
                f"🛡️ circuit_breaker 通过: "
                f"DD={cb_decision.current_dd_pct*100:.2f}% / "
                f"连亏={cb_decision.consec_loss_days}天"
            )
        return out
    except Exception as e:
        logger.exception(f"circuit_breaker 检查失败 (fail-open): {e}")
        return None


def _run_regime_filter_subgate() -> Optional[Dict[str, Any]]:
    """跑 regime_filter 闸（medium：load BTC 1h klines ~100ms + EMA 计算）。

    :return: 决策 dict 含 strategy/reason/features.{ret_90d_pct/ema50/ema200/
              ema_ratio/bars}；None 表示 fail-open（异常）。
    """
    try:
        btc_data = _data_loader.load("BTC-USDT-SWAP", "1h")
        regime_strategy, regime_reason, regime_feats = _regime_filter.recommended_strategy(btc_data.klines)

        out: Dict[str, Any] = {
            "strategy": regime_strategy,
            "reason": regime_reason,
            "features": {
                "ret_90d_pct": regime_feats.get("ret_90d_pct"),
                "ema50": regime_feats.get("ema50"),
                "ema200": regime_feats.get("ema200"),
                "ema_ratio": regime_feats.get("ema_ratio"),
                "bars": regime_feats.get("bars"),
            },
        }

        ret = regime_feats.get("ret_90d_pct")
        ratio = regime_feats.get("ema_ratio")
        ret_str = f"{ret:+.1f}%" if ret is not None else "N/A"
        ratio_str = f"{ratio:.3f}" if ratio is not None else "N/A"

        if regime_strategy is None:
            logger.info(
                f"🚦 regime_filter 拒入场: {regime_reason} | "
                f"ret={ret_str}, EMA ratio={ratio_str}"
            )
        else:
            logger.info(
                f"🚦 regime_filter 通过: 推荐 = {regime_strategy} | {regime_reason}"
            )
        return out
    except Exception as e:
        logger.exception(f"regime_filter 检查失败 (fail-open): {e}")
        return None


def run_pre_signal_gates() -> Dict[str, Any]:
    """事中防御 gate 共享入口（双闸顺序：circuit_breaker → regime_filter）。

    Result schema (统一):
        {
            "passed":           bool,
            "stage":            "pre_signal_gates"
                              | "circuit_breaker_blocked"
                              | "regime_skipped",
            "reason":           str | None,  # 阻断原因（passed=False 时填）
            "circuit_breaker":  Dict | None, # 含 triggered_rules
            "regime":           Dict | None, # 含 strategy / reason / features（漂移修复 #1）
            "errors":           List[str],   # 闸内异常累计（fail-open evidence）
        }

    短路：circuit_breaker 阻断时不跑 regime_filter（cheap first 防 hot-path 拉长）。

    失败语义：
        - 任一闸内部异常 → fail-open → 视同该闸"无意见"，continue 跑下一闸
        - 任一闸返回明确"拒" → 立刻阻断 (passed=False)，不再跑后续闸
        - 两闸全 pass → passed=True；caller 自行决定后续 (Runner.run() / 等等)
    """
    result: Dict[str, Any] = {
        "passed": True,
        "stage": "pre_signal_gates",
        "reason": None,
        "circuit_breaker": None,
        "regime": None,
        "errors": [],
    }

    # ── ① circuit_breaker（cheap：JSON read ~ms）──
    try:
        cb = _run_circuit_breaker_subgate()
        if cb is not None:
            result["circuit_breaker"] = cb
            if cb["skip_signal"]:
                result["passed"] = False
                result["stage"] = "circuit_breaker_blocked"
                result["reason"] = f"circuit_breaker: {cb['reason']}"
                return result  # 短路：阻断时不再走 regime_filter（hot-path 优化）
    except Exception as e:
        # _run_circuit_breaker_subgate 已 log + return None；到达此分支说明 wrapper 本身崩
        logger.exception(f"circuit_breaker wrapper 异常 (fail-open): {e}")
        result["errors"].append(f"circuit_breaker_failed: {e}")

    # ── ② regime_filter（medium：load BTC 1h klines ~100ms）──
    try:
        regime = _run_regime_filter_subgate()
        if regime is not None:
            result["regime"] = regime
            if regime["strategy"] is None:
                result["passed"] = False
                result["stage"] = "regime_skipped"
                result["reason"] = f"regime_filter: {regime['reason']}"
                return result
    except Exception as e:
        logger.exception(f"regime_filter wrapper 异常 (fail-open): {e}")
        result["errors"].append(f"regime_filter_failed: {e}")

    return result
