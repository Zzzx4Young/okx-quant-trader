# -*- coding: utf-8 -*-
"""
OKX 交易工作流执行器 (Runner)

负责：
- 判断当前是否到达 15 分钟 K 线结算点
- 风控前置检查（emergency_stop / 熔断 / 持仓上限）
- 调用信号引擎获取信号
- 调用风控计算器计算仓位
- 执行下单
- 更新持仓状态
- 记录交易日志
"""

import time
import os
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import get_config
from .client import OKXClient
from .portfolio import Portfolio
from .logger import TradeLogger
from .risk import RiskCalculator
from .signal import SignalEngine, Signal
from .notifier import TelegramNotifier, NoopNotifier

logger = logging.getLogger(__name__)


class Runner:
    """
    交易工作流执行器

    使用方式::

        runner = Runner()
        result = runner.run()  # 在 Heartbeat 中调用
    """

    def __init__(
        self,
        okx_client: Optional[OKXClient] = None,
        config_path: Optional[str] = None,
        notifier: Optional[Any] = None,
    ):
        self._client = okx_client or OKXClient()
        self._config = get_config()
        self._portfolio = Portfolio()
        self._logger = TradeLogger()
        self._risk = RiskCalculator(self._config)
        self._signal = SignalEngine(self._client.market)
        # 通知层：默认从 env 读 Telegram 凭据；不启用时返回 NoopNotifier
        if notifier is not None:
            self._notifier = notifier
        else:
            env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
            self._notifier = TelegramNotifier.from_env(env_path) if self._config.notifier_enabled else NoopNotifier()

        # Constitution §3 跨策略冲突过滤：按 symbol 维护最近信号窗口
        # 用于 A↔B 同 symbol 反向信号的时间窗口检测（默认 60 分钟）
        self._recent_signals: Dict[str, deque] = {}

    def run(self) -> Dict[str, Any]:
        """
        执行一次完整的工作流

        :return: 执行结果字典
        """
        start_time = datetime.now(timezone.utc)
        results = {
            "timestamp": start_time.isoformat(),
            "tick": True,
            "signals_checked": False,
            "signal_triggered": None,
            "actions": [],
            "errors": [],
        }

        # ── -1. portfolio ↔ OKX 对账（修复鬼记录 / 补齐手动仓位） ──
        try:
            okx_positions = self._client.account.get_positions(inst_type="SWAP")
            okx_history = self._client.account.get_positions_history(limit="20")
            # ctVal 缓存（用于 PnL/仓位/手续费多倍计）
            ct_val_by_inst = {}
            try:
                instruments = self._client.public.get_instruments(inst_type="SWAP")
                ct_val_by_inst = {
                    inst["instId"]: float(inst.get("ctVal") or 1.0)
                    for inst in instruments
                }
            except Exception as ie:
                logger.warning(f"获取 ctVal 缓存失败（不阻塞）: {ie}")
            recon = self._portfolio.reconcile_with_okx(
                okx_positions, okx_history, ct_val_by_inst=ct_val_by_inst
            )
            results["reconcile"] = {
                "drift_detected": recon["drift_detected"],
                "ghost_closed": len(recon["ghost_closed"]),
                "new_synced": len(recon["new_synced"]),
                "matched": len(recon["matched"]),
                "mismatched": len(recon["mismatched"]),
                "actions": recon["actions"][:10],  # 防爆炸
            }
            if recon["drift_detected"]:
                try:
                    self._notifier.notify_drift(recon)
                except Exception as ne:
                    logger.warning(f"notifier.notify_drift failed: {ne}")
        except Exception as e:
            results["errors"].append(f"对账失败（不阻塞）: {e}")
            logger.warning(f"reconcile 跳过: {e}")

        # ── 0. 检查是否到达交易时间点 ──
        if not self._is_trade_time():
            results["tick"] = False
            results["reason"] = "非交易时间点（K线未走完）"
            return results

        # ── 1. 前置风控检查 ──
        risk_check = self._pre_risk_check()
        if not risk_check["passed"]:
            results["risk_check"] = risk_check
            return results

        # ── 2. 获取当前持仓 ──
        positions = self._portfolio.get_all_positions()
        results["positions"] = self._portfolio.get_positions_summary()

        # ── 3. 检查所有白名单交易对信号 ──
        signals = self._signal.check_all_symbols(positions)
        results["signals_checked"] = True
        results["signal_count"] = len(signals)

        if not signals:
            results["signal_triggered"] = False
            return results

        # ── 4. 处理每个信号 ──
        for signal in signals:
            action = self._process_signal(signal)
            results["actions"].append(action)

            if action.get("status") == "success":
                results["signal_triggered"] = True
            else:
                results["errors"].append(action.get("error", "Unknown error"))

        # 如果没有成功信号，也标记
        if results["signal_triggered"] is None:
            results["signal_triggered"] = False

        return results

    def _is_trade_time(self) -> bool:
        """判断最近 quarter 时刻是否在容忍窗口内（容忍调度抖动）

        原逻辑只用 datetime.now().minute，cron 子代理冷启动 ~2.7 分钟时会错过 quarter。
        新逻辑：只要最近的 quarter 时刻距离现在 ≤ TOLERANCE_MINUTES 分钟即算。

        :return: True 表示该扫描信号
        """
        if not self._config.trade_on_quarter:
            return True

        # 容忍窗口（实测 cron 冷启动 2m42s，留 3 分钟缓冲）
        TOLERANCE_MINUTES = 3

        now = datetime.now(timezone.utc)
        current_minute = now.minute
        quarterly = self._config.quarterly_minutes

        # 路径 1：当下就在 quarter 分钟（最理想）
        if current_minute in quarterly:
            return True

        # 路径 2：刚过去的 quarter 在容忍窗口内（用于补偿 cron 冷启动抖动）
        # 计算"距离最近的过去 quarter 多少分钟"
        # (current - q) % 60 = q 距今的分钟数（0..59）
        for q in quarterly:
            minutes_since_q = (current_minute - q) % 60
            if 0 < minutes_since_q <= TOLERANCE_MINUTES:
                return True

        return False

    def _pre_risk_check(self) -> Dict[str, Any]:
        """
        前置风控检查

        :return: {"passed": bool, "reason": str}
        """
        # ── 紧急熔断 ──
        if self._config.emergency_stop:
            return {
                "passed": False,
                "stage": "emergency_stop",
                "reason": "emergency_stop=true，人工熔断已激活，拒绝所有交易",
            }

        # ── 连续亏损熔断 (Constitution §5) ──
        max_consec = self._config.audit_max_consecutive_losses
        if self._portfolio.is_meltdown(max_consec):
            # 检查冷静期是否已过
            last_loss_ts = self._portfolio.get_last_loss_timestamp()
            if last_loss_ts:
                from datetime import datetime, timezone, timedelta
                lockout_mins = self._config.audit_lockout_duration_minutes
                cooldown_end = last_loss_ts + timedelta(minutes=lockout_mins)
                now = datetime.now(timezone.utc)
                if now < cooldown_end:
                    remaining = (cooldown_end - now).total_seconds() / 60
                    return {
                        "passed": False,
                        "stage": "meltdown_cooldown",
                        "reason": f"连续 {max_consec} 次亏损熔断中，冷静期剩余 {remaining:.0f} 分钟",
                    }

        # ── 持仓上限检查 ──
        if self._portfolio.position_count() >= self._config.max_concurrent_positions:
            return {
                "passed": False,
                "stage": "position_limit",
                "reason": f"已达最大持仓数 {self._config.max_concurrent_positions}，禁止新开仓",
            }

        # ── 流动性 / 黑名单过滤 (Constitution §4) ──
        try:
            from .market_filter import MarketFilter
            mf = MarketFilter(self._client, self._config)
            blacklist = mf.filter_whitelist(self._config.whitelist_symbols)
            if blacklist:
                symbols = ", ".join(blacklist.keys())
                return {
                    "passed": False,
                    "stage": "blacklist",
                    "reason": f"{symbols} 被流动性/黑名单过滤拦截，本轮跳过",
                }
        except Exception as e:
            logger.warning(f"流动性检查失败（不阻塞交易）: {e}")

        # ── 手续费占比审计 (Constitution §5) ──
        if self._config.audit_enable_meltdown_lock:
            # ✅ v1.8.3 修复：之前是 `self._portfolio.daily_stats`（属性访问），
            # 但 Portfolio 类只暴露 get_daily_stats() 方法，self._data["daily_stats"] 是 dict key。
            # 这个 bug 被端到端验证（mock datetime 到 1h K 线边界）首次触发，
            # 之前因 blacklist bug 导致 signals_checked=false 早退，从未走到这一行。
            daily = self._portfolio.get_daily_stats()
            if daily:
                pnl_gross = daily.get("total_pnl_gross", 0) or daily.get("total_pnl", 0)
                total_fee = daily.get("total_fee", 0) or daily.get("fees", 0)
                if pnl_gross > 0 and total_fee > 0:
                    ratio = total_fee / pnl_gross
                    threshold = self._config.audit_fee_to_profit_ratio_threshold
                    if ratio > threshold:
                        logger.warning(
                            f"当日手续费/盈利比 = {ratio:.2%} > {threshold:.0%}，需要提高开仓阈值"
                        )

        return {"passed": True}

    def _conflict_check(self, signal: Signal) -> Optional[str]:
        """不确定性决策树 (Constitution §3)

        检查信号是否有内部冲突。如果有冲突，返回放弃原因；否则返回 None。

        冲突场景 1：技术指标矛盾
        冲突场景 2：方向正确但脱离最佳入场点（> 1%）
        """
        if signal is None:
            return None

        # 场景 1：技术指标矛盾检测
        # Strategy A/B/C/D 的 reason 字段中已经隐含了置信度
        # 如果 confidence < 0.5，认为指标不一致
        if signal.confidence < 0.5:
            return f"不确定性决策树 HOLD：信号置信度 {signal.confidence:.2f} < 0.5，放弃交易"

        # 场景 2：方向正确但脱离最佳入场点
        # 比较当前价与最近 20 根 K 线的最低/最高
        try:
            timeframe = self._config.timeframe
            candles = self._client.market.get_candles(signal.symbol, bar=timeframe, limit=20)
            if candles:
                closes = [float(c[4]) for c in candles]
                if signal.direction == "long":
                    best_entry = min(closes)
                else:
                    best_entry = max(closes)
                deviation = abs(signal.entry_price - best_entry) / best_entry
                if deviation > 0.01:
                    return f"方向正确但脱离最佳入场点 {deviation:.2%} > 1%，严禁追单"
        except Exception as e:
            logger.warning(f"冲突检测 - 入场点检查失败: {e}")

        return None

    # ─────────────────────────────────────────────────────────────
    # Constitution §3 跨策略冲突过滤 helper
    # ─────────────────────────────────────────────────────────────

    def _get_recent_signals(self, symbol: str) -> list:
        """返回同 symbol 在 conflict_window_min 内的历史信号。

        自动丢弃过期信号并重构 deque（仅在有过期项时重构，避免热点路径开销）。
        """
        if symbol not in self._recent_signals:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=self._risk.DEFAULT_CONFLICT_WINDOW_MIN
        )
        result = []
        expired = 0
        for sig in self._recent_signals[symbol]:
            try:
                sig_ts = self._risk._parse_kline_time(getattr(sig, "kline_time", None))
                if sig_ts is None or sig_ts >= cutoff:
                    result.append(sig)
                else:
                    expired += 1
            except Exception:
                result.append(sig)
        if expired > 0:
            self._recent_signals[symbol] = deque(result, maxlen=100)
        return result

    def _record_signal(self, signal) -> None:
        """记录信号到最近窗口。None 信号忽略。

        调用时机：signal 成功下单后（不记录被拒绝的信号）。
        """
        if signal is None:
            return
        sym = getattr(signal, "symbol", None)
        if not sym:
            return
        if sym not in self._recent_signals:
            self._recent_signals[sym] = deque(maxlen=100)
        self._recent_signals[sym].append(signal)

    def _get_atr_ratio(self, symbol: str) -> Optional[float]:
        """计算 current_ATR / median_ATR 比值（衡量趋势/震荡动能）。

        返回 None 时表示数据不足或计算失败（调用方应跳过规则 2/3）。
        """
        try:
            timeframe = self._config.timeframe
            candles = self._client.market.get_candles(symbol, bar=timeframe, limit=20)
            if not candles or len(candles) < 15:
                return None
            atr_period = 14
            trs = []
            for i in range(1, len(candles)):
                high = float(candles[i][2])
                low = float(candles[i][3])
                prev_close = float(candles[i - 1][4])
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                trs.append(tr)
            if len(trs) < atr_period:
                return None
            atr_values = []
            for i in range(atr_period - 1, len(trs)):
                window = trs[i - atr_period + 1:i + 1]
                atr_values.append(sum(window) / atr_period)
            if not atr_values:
                return None
            current_atr = atr_values[-1]
            sorted_atrs = sorted(atr_values)
            n = len(sorted_atrs)
            if n % 2 == 0:
                median_atr = (sorted_atrs[n // 2 - 1] + sorted_atrs[n // 2]) / 2
            else:
                median_atr = sorted_atrs[n // 2]
            if median_atr <= 0:
                return None
            return current_atr / median_atr
        except Exception as e:
            logger.warning(f"计算 ATR ratio 失败 [{symbol}]: {e}")
            return None

    def _strategy_conflict_check(self, signal) -> Optional[str]:
        """Constitution §3 跨策略冲突过滤包装（调用 risk.check_strategy_conflict）。

        顺序：先做跨策略 A↔B 冲突检查 → 再做不确定性决策树检查。
        """
        if signal is None:
            return None
        recent = self._get_recent_signals(signal.symbol)
        atr_ratio = self._get_atr_ratio(signal.symbol)
        return self._risk.check_strategy_conflict(
            new_signal=signal,
            recent_signals=recent,
            atr_ratio=atr_ratio,
        )

    def _kelly_sizing_decision(
        self,
        signal,
        equity: float,
    ) -> tuple:
        """
        Constitution §3.2 Kelly Criterion 动态仓位决策 thin wrapper (v1.8.2).

        顺序：在 §3 跨策略冲突检查 + 不确定性决策树检查之后,
        获取余额后、调 calculate_position_size 之前.

        收集 inputs:
          - strategy_stats: 从 self._portfolio.get_strategy_stats(signal.strategy) 聚合
          - atr_ratio: 从 self._get_atr_ratio(signal.symbol) 取
          - leverage: signal.leverage 或 risk._get_default_leverage(symbol)
          - sl_distance_pct: config.sl_buffer_percent / 100 (默认 0.5%)
          - min_trades_for_kelly: config.kelly.min_trades_for_kelly (默认 30)

        调用 self._risk.kelly_sizing_decision() 返回 (status, max_loss_pct, reason).
        runner 根据 status 决定:
          - "fallback_max_loss_pct": 用 config 默认 1% 本金
          - "reject_negative_ev": 拒绝开仓
          - "kelly_active": 临时覆盖 config.max_loss_percent_per_trade 为 max_loss_pct

        :param signal: Signal 对象
        :param equity: 账户可用余额 (USDT)
        :return: (status, max_loss_pct_or_None, reason)
        """
        if signal is None:
            return ("fallback_max_loss_pct", None, "no_signal_in_runner_kelly")

        # ── 拉 strategy stats ──
        strategy_stats = None
        if self._portfolio is not None:
            try:
                strategy_stats = self._portfolio.get_strategy_stats(signal.strategy)
            except Exception as e:
                logger.warning(f"拉取 strategy stats 失败 [{signal.strategy}]: {e}")

        # ── 拉 atr_ratio (跟 §3 跨策略冲突过滤共用) ──
        atr_ratio = self._get_atr_ratio(signal.symbol)

        # ── 拉 leverage (signal.leverage 优先) ──
        leverage = signal.leverage
        if not leverage:
            try:
                leverage = self._risk._get_default_leverage(signal.symbol)
            except Exception:
                leverage = 3  # v1.8.1 默认锁 = 3x

        # ── 拉 min_trades_for_kelly (default 30) ──
        min_trades = 30
        try:
            kelly_cfg = self._risk._config.kelly
            if isinstance(kelly_cfg, dict):
                min_trades = kelly_cfg.get("min_trades_for_kelly", 30)
        except Exception:
            pass

        # ── 拉 sl_distance_pct (默认 = config.sl_buffer_percent / 100) ──
        sl_distance_pct = 0.005
        try:
            sl_buffer = getattr(self._risk._config, "sl_buffer_percent", 0.5)
            sl_distance_pct = float(sl_buffer) / 100.0
            if sl_distance_pct <= 0:
                sl_distance_pct = 0.005
        except Exception:
            pass

        # ── 委托给 risk.kelly_sizing_decision 纯决策包装 ──
        try:
            return self._risk.kelly_sizing_decision(
                strategy_stats=strategy_stats,
                equity=equity,
                atr_ratio=atr_ratio,
                leverage=int(leverage) if leverage else 3,
                sl_distance_pct=sl_distance_pct,
                min_trades_for_kelly=int(min_trades),
            )
        except Exception as e:
            # 任何 Kelly 计算异常 → 默认路径 (fallback)
            logger.warning(f"Kelly 决策异常 [{signal.strategy}/{signal.symbol}]: {e}")
            return ("fallback_max_loss_pct", None, f"kelly_decision_error_fallback|{type(e).__name__}")

    def _process_signal(self, signal: Signal) -> Dict[str, Any]:
        """
        处理单个信号：风控计算 → 下单 → 更新状态 → 记录日志

        :param signal: Signal 对象
        :return: 操作结果
        """
        result = {
            "signal": signal.to_dict(),
            "status": "pending",
        }

        # ── Constitution §3 跨策略冲突过滤 (A↔B) ──
        strategy_conflict_reason = self._strategy_conflict_check(signal)
        if strategy_conflict_reason:
            result["status"] = "rejected"
            result["reason"] = strategy_conflict_reason
            logger.info(f"信号被跨策略冲突过滤拒绝: {strategy_conflict_reason}")
            return result

        # ── 不确定性决策树 (Constitution §3) ──
        conflict_reason = self._conflict_check(signal)
        if conflict_reason:
            result["status"] = "rejected"
            result["reason"] = conflict_reason
            logger.info(f"信号被不确定性决策树拒绝: {conflict_reason}")
            return result

        # ── 获取账户余额 ──
        try:
            balance_resp = self._client.account.get_balance()
            # 解析余额（OKX 返回格式）
            details = balance_resp.get("details", []) or []
            usdt_balance = 0.0
            for d in details:
                if d.get("ccy") == "USDT":
                    usdt_balance = float(d.get("availBal", 0))
                    break
            result["avail_balance"] = usdt_balance
        except Exception as e:
            result["status"] = "error"
            result["error"] = f"获取余额失败: {e}"
            return result

        if usdt_balance <= 0:
            result["status"] = "error"
            result["error"] = f"可用余额不足: {usdt_balance}"
            return result

        # ── Constitution §3.2 Kelly Criterion 动态仓位决策 (v1.8.2) ──
        kelly_status, kelly_max_loss_pct, kelly_reason = self._kelly_sizing_decision(
            signal=signal,
            equity=usdt_balance,
        )
        if kelly_status == "reject_negative_ev":
            result["status"] = "rejected"
            result["reason"] = kelly_reason
            logger.info(f"信号被 Kelly 拒绝 (negative EV): {kelly_reason}")
            return result

        # ── Kelly 调整 max_loss_pct (临时改 risk config, 计算后还原) ──
        original_max_loss_pct = self._risk._config.max_loss_percent_per_trade
        kelly_applied = False
        if (
            kelly_status == "kelly_active"
            and kelly_max_loss_pct is not None
            and kelly_max_loss_pct < original_max_loss_pct - 1e-9
        ):
            self._risk._config.max_loss_percent_per_trade = kelly_max_loss_pct
            kelly_applied = True
            logger.info(
                f"Kelly: {signal.strategy}/{signal.symbol} max_loss_pct "
                f"{original_max_loss_pct:.3f}% -> {kelly_max_loss_pct:.3f}% "
                f"({kelly_reason})"
            )
            result["kelly_decision"] = {
                "status": kelly_status,
                "applied_max_loss_pct": kelly_max_loss_pct,
                "reason": kelly_reason,
            }
        elif kelly_status == "kelly_active":
            # kelly wants ≥ hard_cap (已是 hard_cap 边缘), 不改 config
            result["kelly_decision"] = {
                "status": kelly_status,
                "applied_max_loss_pct": kelly_max_loss_pct,
                "reason": kelly_reason + "|not_applied_pct_>=_hard_cap",
            }
        else:
            # fallback_max_loss_pct → caller 用 config 默认 1%
            result["kelly_decision"] = {
                "status": kelly_status,
                "applied_max_loss_pct": original_max_loss_pct,
                "reason": kelly_reason,
            }

        try:
            # ── 风控计算仓位 ──
            risk_result = self._risk.calculate_position_size(
                symbol=signal.symbol,
                direction=signal.direction,
                entry_price=signal.entry_price,
                available_balance=usdt_balance,
                leverage=signal.leverage,
            )
        finally:
            # 还原 config.max_loss_percent_per_trade (避免污染同 runner 后续信号)
            if kelly_applied:
                self._risk._config.max_loss_percent_per_trade = original_max_loss_pct

        result["risk"] = {
            "max_size": risk_result.max_size,
            "max_margin": risk_result.max_margin,
            "sl_price": risk_result.sl_price,
            "tp_price": risk_result.tp_price,
            "rr_ratio": risk_result.reward_risk_ratio,
            "passed": risk_result.passed,
            "reason": risk_result.reason,
        }

        if not risk_result.passed:
            result["status"] = "rejected"
            result["error"] = risk_result.reason
            return result

        # 最小下单量检查（OKX 永续合约最小 1 张）
        if risk_result.max_size < 1:
            result["status"] = "rejected"
            result["error"] = f"计算仓位 {risk_result.max_size} < 1，不满足最小下单量"
            return result

        # ── 设置杠杆 ──
        try:
            inst_id = signal.symbol
            mgn_mode = self._config.margin_mode
            self._client.account.set_leverage(
                lever=str(signal.leverage),
                mgn_mode=mgn_mode,
                inst_id=inst_id,
                pos_side=signal.direction,  # 双向持仓模式（long_short_mode）必须传 posSide
            )
        except Exception as e:
            result["status"] = "error"
            result["error"] = f"设置杠杆失败: {e}"
            return result

        # ── 下单 ──
        try:
            order_resp = self._client.trade.place_order(
                inst_id=signal.symbol,
                side=signal.direction,
                pos_side=signal.direction,  # 双向持仓模式必须传 posSide
                ord_type="market",  # 信号触发后用市价快速进场
                sz=str(int(risk_result.max_size)),  # 取整
                td_mode=mgn_mode,
                sl_trigger_px=str(risk_result.sl_price),
                sl_ord_px=str(risk_result.sl_price),
                tp_trigger_px=str(risk_result.tp_price),
                tp_ord_px=str(risk_result.tp_price),
            )

            # 解析订单响应
            if isinstance(order_resp, list):
                order_data = order_resp[0] if order_resp else {}
            else:
                order_data = order_resp or {}

            order_id = order_data.get("ordId", "")
            fills = order_data.get("fills", []) or []
            avg_price = 0.0
            if fills:
                avg_price = float(fills[0].get("px", signal.entry_price))

            result["order"] = {
                "order_id": order_id,
                "avg_price": avg_price,
                "filled_sz": int(risk_result.max_size),
            }

        except Exception as e:
            result["status"] = "error"
            result["error"] = f"下单失败: {e}"
            return result

        # ── 更新持仓状态 ──
        position_record = {
            "symbol": signal.symbol,
            "direction": signal.direction,
            "size": risk_result.max_size,
            "entry_price": avg_price or signal.entry_price,
            "leverage": signal.leverage,
            "sl_price": risk_result.sl_price,
            "tp_price": risk_result.tp_price,
            "order_id": order_id,
            "trigger_strategy": signal.strategy,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "margin": risk_result.max_margin,
            "tp_stage": 0,  # 止盈阶段：0=未触发, 1=第一批, 2=第二批
            "note": signal.reason,
        }

        self._portfolio.add_position(position_record)

        # Constitution §3：记录信号到最近窗口（供后续信号做跨策略冲突检查）
        self._record_signal(signal)

        # ── 记录开仓日志 ──
        fee = self._risk.estimate_fee(
            price=avg_price or signal.entry_price,
            size=risk_result.max_size,
            taker=True,
        )

        self._logger.log_open(
            symbol=signal.symbol,
            direction=signal.direction,
            price=avg_price or signal.entry_price,
            size=risk_result.max_size,
            leverage=signal.leverage,
            order_id=order_id,
            strategy=signal.strategy,
            margin=risk_result.max_margin,
            fee=fee,
            note=signal.reason,
        )

        result["status"] = "success"
        result["position_record"] = position_record

        # 发送开仓通知（最佳努力，失败不抛错）
        try:
            self._notifier.notify_open(position_record)
        except Exception as e:
            logger.warning(f"notifier.notify_open failed: {e}")

        return result

    def _normalize_position_symbol(self, symbol: str) -> str:
        """把 portfolio 里存的 symbol 转成 OKX API 格式
        
        Portfolio 里可能存 'ETHUSDTSWAP'（无分隔符）或 'ETH-USDT-SWAP'（OKX 标准）。
        这里统一转成 OKX 格式。
        """
        s = symbol.upper().replace('-', '').replace('/', '').replace('_', '')
        # 去除常见永续后缀
        for suffix in ('SWAP', 'PERPETUAL', 'PERP', 'FUTURES', 'FUTURE'):
            if s.endswith(suffix):
                s = s[: -len(suffix)]
                break
        # 重新组装为 OKX 格式 (BASE-USDT-SWAP)
        if s.endswith('USDT') and len(s) > 4:
            base = s[:-4]
            return f"{base}-USDT-SWAP"
        return symbol  # 兜底返回原值

    @staticmethod
    def _filter_skip_positions(positions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """白名单 + 哨兵值双重过滤（P0-4 fix: 2026-07-15）

        防止手动 / 外部同步仓位被系统自动平仓：
        - C 防线：strategy 名命中白名单 → HOLD_MANUAL
        - A 防线：sl_price=0 + tp_price=0 哨兵值 → HOLD_NO_PROTECTION（即便白名单被绕过，仍能拦截）

        :param positions: 原始持仓列表
        :return: (kept_positions, skipped_actions) — skipped_actions 是 dict 列表，
                 可直接 append 到 results["updated"]
        """
        NO_AUTO_CLOSE_STRATEGIES = {"MANUAL_NO_AUTO_CLOSE", "EXTERNAL_WEB_SYNC"}
        kept: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for pos in positions:
            strategy = pos.get("strategy") or pos.get("strategy_name", "")
            try:
                sl = float(pos.get("sl_price", 0.0) or 0.0)
            except (TypeError, ValueError):
                sl = 0.0
            try:
                tp = float(pos.get("tp_price", 0.0) or 0.0)
            except (TypeError, ValueError):
                tp = 0.0

            if strategy in NO_AUTO_CLOSE_STRATEGIES:
                # C 防线：策略名命中白名单 → 显式跳过 + 日志记录
                skipped.append({
                    "symbol": pos["symbol"],
                    "action": "HOLD_MANUAL",
                    "reason": f"strategy={strategy} 跳过自动 SL/TP 管理（手动/外部仓）",
                })
                continue
            if sl <= 0 and tp <= 0:
                # A 防线：哨兵值 → 物理防呆（即便白名单被绕过，仍能拦截）
                skipped.append({
                    "symbol": pos["symbol"],
                    "action": "HOLD_NO_PROTECTION",
                    "reason": "sl_price=0 + tp_price=0 哨兵值，判定为无自动保护单，跳过托管",
                })
                continue
            kept.append(pos)
        return kept, skipped

    def check_and_close_positions(self) -> Dict[str, Any]:
        """
        检查当前持仓是否触发止盈/止损/趋势反转，必要时平仓

        止盈采用三批分级策略：
          - 第一批：盈亏比达 1:1 → 平 30%，止损上移至盈亏平衡
          - 第二批：盈亏比达 1.5:1 → 平 30%，止损上移至 1:1 位置
          - 第三批：剩余 40% 追踪止盈，止损跟随 EMA20 或 ATR

        在每次 Heartbeat 进入时调用

        :return: 处理结果
        """
        results = {"closed": [], "updated": [], "errors": []}
        positions = self._portfolio.get_all_positions()

        if not positions:
            return results

        # ── 0. 白名单 + 哨兵值双重防呆 (P0-4 fix: 2026-07-15) ──
        # A+C 双锁：sentinel sl_price=0/tp_price=0（物理防呆）+ strategy 白名单（逻辑隔离）
        # 24h 内连踩两次同款 footgun（-3.3189 + -0.671 = -3.99 USDT 损失）
        positions, skipped_actions = Runner._filter_skip_positions(positions)
        results["updated"].extend(skipped_actions)
        if not positions:
            return results

        # 获取所有持仓的当前行情（symbol 转 OKX 格式）
        tickers = {}
        for pos in positions:
            try:
                okx_symbol = self._normalize_position_symbol(pos["symbol"])
                ticker_data = self._client.market.get_ticker(okx_symbol)
                # get_ticker 返回 List[Dict]，取第一个元素
                ticker = ticker_data[0] if ticker_data else {}
                tickers[pos["symbol"]] = ticker
            except Exception as e:
                results["errors"].append(f"获取 {pos['symbol']} 行情失败: {e}")

        for pos in positions:
            symbol = pos["symbol"]
            okx_symbol = self._normalize_position_symbol(pos["symbol"])
            direction = pos["direction"]
            sl_price = float(pos["sl_price"])
            tp_price = float(pos["tp_price"])
            entry_price = float(pos["entry_price"])
            tp_stage = int(pos.get("tp_stage", 0))  # 0=未止盈, 1=第一批, 2=第二批

            if symbol not in tickers:
                continue

            current_price = float(tickers[symbol].get("last", 0))
            if current_price <= 0:
                continue

            # 计算当前盈亏比
            sl_distance = abs(entry_price - sl_price)
            if sl_distance <= 0:
                sl_distance = entry_price * 0.005  # 保底

            if direction == "long":
                current_rr = (current_price - entry_price) / sl_distance
            else:
                current_rr = (entry_price - current_price) / sl_distance

            should_close_all = False
            close_reason = ""
            should_partial = False
            partial_ratio = 0.0
            partial_reason = ""
            sl_update = None
            tp_stage_update = tp_stage

            # ── 止损检查（任何阶段都执行） ──
            if direction == "long" and current_price <= sl_price:
                should_close_all = True
                close_reason = "SL触发（做多止损）"
            elif direction == "short" and current_price >= sl_price:
                should_close_all = True
                close_reason = "SL触发（做空止损）"

            # ── 三批分级止盈 ──
            elif tp_stage == 0 and current_rr >= 1.0:
                # 第一批：盈亏比 1:1 → 平 30%
                should_partial = True
                partial_ratio = 0.3
                partial_reason = "TP-1:1（第一批 30%）"
                # 止损上移至盈亏平衡
                if direction == "long":
                    sl_update = entry_price  # 盈亏平衡
                else:
                    sl_update = entry_price
                tp_stage_update = 1

            elif tp_stage == 1 and current_rr >= 1.5:
                # 第二批：盈亏比 1.5:1 → 平 30%
                should_partial = True
                partial_ratio = 0.3
                partial_reason = "TP-1.5:1（第二批 30%）"
                # 止损上移至 1:1 位置
                if direction == "long":
                    sl_update = entry_price + sl_distance  # 1:1 盈利位置
                else:
                    sl_update = entry_price - sl_distance
                tp_stage_update = 2

            elif tp_stage == 2:
                # 第三批：剩余 40% 追踪止盈
                # 趋势反转检测：EMA20 vs ticker 实时价
                # 重要：当前价直接从 ticker.last 取，EMA 用最近的 K 线计算。
                # get_candles 已返回 oldest → newest，所以 [-1] 是最新值。
                try:
                    candles = self._client.market.get_candles(
                        okx_symbol, bar=self._config.timeframe, limit=25
                    )
                    if candles and len(candles) >= 22:
                        closes_check = [float(c[4]) for c in candles]  # oldest → newest
                        if len(closes_check) >= 22:
                            ema_vals = SignalEngine._ema(closes_check, period=20)
                            current_ema = ema_vals[-1]  # ← 最新 EMA
                            # 当前实时价 vs EMA 比较（左右各 2 根）
                            if direction == "long":
                                # 做多：实时价显著低于 EMA → 趋势反转
                                # 加 0.1% 容差避免波动误触发
                                if current_price < current_ema * 0.999:
                                    should_close_all = True
                                    close_reason = f"趋势反转（实时价 {current_price:.2f} < EMA20 {current_ema:.2f}，做多平仓）"
                            elif direction == "short":
                                if current_price > current_ema * 1.001:
                                    should_close_all = True
                                    close_reason = f"趋势反转（实时价 {current_price:.2f} > EMA20 {current_ema:.2f}，做空平仓）"
                except Exception as e:
                    results["errors"].append(f"{symbol} 趋势反转检测失败: {e}")

            # ── 趋势反转检测（所有阶段）─
            if not should_close_all and tp_stage < 2:
                try:
                    candles = self._client.market.get_candles(
                        okx_symbol, bar=self._config.timeframe, limit=25
                    )
                    if candles and len(candles) >= 22:
                        closes_check = [float(c[4]) for c in candles]
                        if len(closes_check) >= 22:
                            ema_vals = SignalEngine._ema(closes_check, period=20)
                            current_ema = ema_vals[-1]  # ← 最新 EMA
                            if direction == "long" and current_price < current_ema * 0.999:
                                should_close_all = True
                                close_reason = f"趋势反转（实时价 {current_price:.2f} < EMA20 {current_ema:.2f}，做多平仓）"
                            elif direction == "short" and current_price > current_ema * 1.001:
                                should_close_all = True
                                close_reason = f"趋势反转（实时价 {current_price:.2f} > EMA20 {current_ema:.2f}，做空平仓）"
                except Exception as e:
                    results["errors"].append(f"{symbol} 趋势反转检测失败: {e}")

            # ── SL/TP 触发判断（用 ticker 实时价，不依赖 K 线 close）─
            if not should_close_all:
                if direction == "long" and current_price <= sl_price:
                    should_close_all = True
                    close_reason = f"SL 触发（实时价 {current_price:.2f} ≤ SL {sl_price:.2f}）"
                elif direction == "short" and current_price >= sl_price:
                    should_close_all = True
                    close_reason = f"SL 触发（实时价 {current_price:.2f} ≥ SL {sl_price:.2f}）"
                elif direction == "long" and current_price >= tp_price:
                    should_close_all = True
                    close_reason = f"TP 触发（实时价 {current_price:.2f} ≥ TP {tp_price:.2f}）"
                elif direction == "short" and current_price <= tp_price:
                    should_close_all = True
                    close_reason = f"TP 触发（实时价 {current_price:.2f} ≤ TP {tp_price:.2f}）"

            # ── 时间止损（持仓超时且盈亏比未达 1:1） ──
            if not should_close_all:
                try:
                    opened_at = pos.get("opened_at", "")
                    if opened_at:
                        # 处理多种格式：ISO 字符串 或毫秒时间戳
                        if opened_at.replace(".", "").isdigit():
                            # 纯数字字符串（毫秒时间戳）
                            opened_dt = datetime.fromtimestamp(int(opened_at) / 1000, tz=timezone.utc)
                        else:
                            opened_dt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
                        elapsed = (datetime.now(timezone.utc) - opened_dt).total_seconds() / 3600
                        time_stop_h = self._config.time_stop_hours

                        if elapsed >= time_stop_h and current_rr < 1.0:
                            should_close_all = True
                            close_reason = f"时间止损（持仓 {elapsed:.1f}h ≥ {time_stop_h}h 且盈亏比 {current_rr:.2f} < 1.0）"
                except Exception as e:
                    results["errors"].append(f"{symbol} 时间止损检测失败: {e}")

            # ── 执行操作 ──
            if should_close_all:
                close_result = self._close_position(pos, current_price, close_reason)
                results["closed"].append(close_result)
            elif should_partial:
                # 部分平仓
                partial_result = self._partial_close(
                    pos, current_price, partial_ratio, partial_reason,
                    sl_update=sl_update, tp_stage=tp_stage_update,
                )
                results["updated"].append(partial_result)
            else:
                results["updated"].append({
                    "symbol": symbol,
                    "current_price": current_price,
                    "current_rr": round(current_rr, 3),
                    "tp_stage": tp_stage,
                    "action": "HOLD",
                })

        return results

    def _partial_close(
        self,
        position: Dict[str, Any],
        current_price: float,
        close_ratio: float,
        reason: str,
        sl_update: Optional[float] = None,
        tp_stage: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        执行部分平仓

        :param position: 持仓记录
        :param current_price: 当前价格
        :param close_ratio: 平仓比例（0.0-1.0）
        :param reason: 平仓原因
        :param sl_update: 止损价更新
        :param tp_stage: 止盈阶段更新
        :return: 操作结果
        """
        result = {
            "symbol": position["symbol"],
            "reason": reason,
            "close_ratio": close_ratio,
            "status": "pending",
        }

        try:
            current_size = float(position.get("size", 0))
            close_size = max(1, int(current_size * close_ratio))  # 至少平 1 张

            # 调用 OKX 部分平仓接口
            close_side = "sell" if position["direction"] == "long" else "buy"
            close_resp = self._client.trade.place_order(
                inst_id=self._normalize_position_symbol(position["symbol"]),
                side=close_side,
                pos_side=position["direction"],  # 双向持仓模式必须传 posSide
                ord_type="market",
                sz=str(close_size),
                td_mode=self._config.margin_mode,
                reduce_only=True,
            )

            # 计算部分平仓盈亏
            pnl, roe = self._risk.calculate_pnl(
                direction=position["direction"],
                entry_price=position["entry_price"],
                exit_price=current_price,
                size=close_size,
            )

            fee = self._risk.estimate_fee(
                price=current_price,
                size=close_size,
                taker=True,
            )

            order_id = ""
            if isinstance(close_resp, list) and close_resp:
                order_id = close_resp[0].get("ordId", "")
            elif isinstance(close_resp, dict):
                order_id = close_resp.get("ordId", "")

            # 记录部分平仓日志
            self._logger.log_close(
                symbol=position["symbol"],
                direction=position["direction"],
                price=current_price,
                size=close_size,
                leverage=position["leverage"],
                order_id=order_id,
                strategy=position.get("trigger_strategy", ""),
                margin=position.get("margin", 0) * close_ratio,
                pnl=pnl,
                roe_percent=roe,
                fee=fee,
                slippage=0.0,
                note=f"{reason} (部分平仓 {close_ratio*100:.0f}%)",
            )

            # 更新持仓：减少仓位 + 更新止损/止盈阶段
            updates = {}
            if sl_update is not None:
                updates["sl_price"] = sl_update
            if tp_stage is not None:
                updates["tp_stage"] = tp_stage

            self._portfolio.partial_close_position(
                symbol=position["symbol"],
                order_id=position["order_id"],
                close_ratio=close_ratio,
                pnl=pnl,
                updates=updates if updates else None,
            )

            result["status"] = "success"
            result["pnl"] = pnl
            result["roe"] = roe
            result["new_sl"] = sl_update
            result["new_tp_stage"] = tp_stage

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _close_position(
        self,
        position: Dict[str, Any],
        current_price: float,
        reason: str,
    ) -> Dict[str, Any]:
        """
        执行平仓

        :param position: 持仓记录
        :param current_price: 当前价格
        :param reason: 平仓原因
        :return: 平仓结果
        """
        result = {"symbol": position["symbol"], "reason": reason, "status": "pending"}

        try:
            close_resp = self._client.trade.close_position(
                inst_id=self._normalize_position_symbol(position["symbol"]),
                pos_side=position["direction"],
                mgn_mode=position.get("mgn_mode") or self._config.margin_mode,
            )

            # 计算盈亏（ct_val 来自 OKX instruments.ctVal，存于 position 中）
            ct_val = float(position.get("ct_val") or 1.0)
            pnl, roe = self._risk.calculate_pnl(
                direction=position["direction"],
                entry_price=position["entry_price"],
                exit_price=current_price,
                size=position["size"],
                ct_val=ct_val,
            )

            fee = self._risk.estimate_fee(
                price=current_price,
                size=position["size"],
                ct_val=ct_val,
                taker=True,
            )

            order_id = ""
            if isinstance(close_resp, list) and close_resp:
                order_id = close_resp[0].get("ordId", "")
            elif isinstance(close_resp, dict):
                order_id = close_resp.get("ordId", "")

            # 记录日志
            self._logger.log_close(
                symbol=position["symbol"],
                direction=position["direction"],
                price=current_price,
                size=position["size"],
                leverage=position["leverage"],
                order_id=order_id,
                strategy=position["trigger_strategy"],
                margin=position.get("margin", 0),
                pnl=pnl,
                roe_percent=roe,
                fee=fee,
                slippage=0.0,
                note=reason,
            )

            # 更新组合状态
            self._portfolio.close_position(
                symbol=position["symbol"],
                order_id=position["order_id"],
                pnl=pnl,
            )

            result["status"] = "success"
            result["pnl"] = pnl
            result["roe"] = roe

            # 发送平仓通知
            try:
                self._notifier.notify_close(result)
            except Exception as e:
                logger.warning(f"notifier.notify_close failed: {e}")

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def __repr__(self) -> str:
        return f"<Runner: {self._config.timeframe}>"
