# -*- coding: utf-8 -*-
"""
OKX 交易组合状态管理器

负责：
- 记录当前持仓（positions）
- 记录每日统计数据（daily_stats）
- 持久化到 state/portfolio.json
- 支持多交易对并发持仓
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional


class StrategyStats(NamedTuple):
    """策略历史统计 (Kelly Criterion sizing 决策输入, Constitution §3.2).

    由 Portfolio.get_strategy_stats() 返回。
    用于在 runner 里动态决定单笔仓位 size (而非默认 1% 本金)。
    """
    strategy: str          # strategy 名 (e.g. "BB_RSI_REVERSION")
    n: int                 # closed_trades count for this strategy
    win_rate: float        # wins / n (0.0-1.0)
    avg_win_usd: float     # 平均盈利笔 pnl (USD, 正数; 0 表示该策略从未盈利过)
    avg_loss_usd: float    # 平均亏损笔 |pnl| (USD, 正数; 0 表示该策略从未亏损过)


class Portfolio:
    """组合状态管理器（线程安全）"""

    def __init__(self, portfolio_path: Optional[str] = None):
        if portfolio_path is None:
            base = Path(__file__).parent.parent
            portfolio_path = str(base / "state" / "portfolio.json")
        self._path = Path(portfolio_path)
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """从磁盘加载状态"""
        if self._path.exists():
            with open(self._path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            self._validate_schema()
        else:
            self._data = self._default_state()

    def _validate_schema(self) -> None:
        """校验加载的 portfolio schema，缺失字段 fail-loud

        设计目的: sync 阶段如果 bug 丢字段，宁可启动失败也不要静默用错数据。
        —— 金融场景宁可 startup fail 也不要自动 reset (避免误抹历史)。

        :raises ValueError: schema 缺失关键字段
        """
        required_top = {
            "version", "updated_at", "positions", "daily_stats", "closed_positions"
        }
        missing_top = required_top - set(self._data.keys())
        if missing_top:
            raise ValueError(
                f"portfolio.json schema invalid: missing top-level keys {sorted(missing_top)}. "
                f"Found: {sorted(self._data.keys())}. "
                f"Refusing to start with potentially corrupted state. "
                f"Path: {self._path}"
            )

        required_daily = {
            "date", "total_trades", "loss_trades", "consecutive_losses",
            "total_pnl", "total_fee", "total_pnl_gross", "last_loss_at",
            "emergency_stop_triggered",
        }
        missing_daily = required_daily - set(self._data.get("daily_stats", {}).keys())
        if missing_daily:
            raise ValueError(
                f"portfolio.json daily_stats schema invalid: missing keys {sorted(missing_daily)}. "
                f"Found: {sorted(self._data.get('daily_stats', {}).keys())}. "
                f"Path: {self._path}"
            )

    def _default_state(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "updated_at": self._now_iso(),
            "positions": [],
            "daily_stats": {
                "date": self._today(),
                "total_trades": 0,
                "loss_trades": 0,
                "consecutive_losses": 0,
                "total_pnl": 0.0,
                "total_fee": 0.0,
                "total_pnl_gross": 0.0,
                "last_loss_at": None,
                "emergency_stop_triggered": False,
            },
            "closed_positions": [],
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _save(self) -> None:
        """持久化到磁盘"""
        self._data["updated_at"] = self._now_iso()
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    # ---- 持仓操作 ----

    def add_position(self, position: Dict[str, Any]) -> None:
        """
        添加新持仓

        :param position: 持仓字典，字段包括：
            symbol, direction, size, entry_price, leverage,
            sl_price, tp_price, order_id, trigger_strategy, opened_at
        """
        with self._lock:
            self._ensure_daily_reset()
            self._data["positions"].append(position)
            self._save()

    def update_position(
        self,
        symbol: str,
        order_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """
        更新指定持仓字段

        :param symbol: 交易对
        :param order_id: 订单 ID
        :param updates: 要更新的字段字典
        :return: 是否更新成功
        """
        with self._lock:
            for pos in self._data["positions"]:
                if pos.get("symbol") == symbol and pos.get("order_id") == order_id:
                    pos.update(updates)
                    self._save()
                    return True
            return False

    def close_position(self, symbol: str, order_id: str, pnl: float = 0.0) -> bool:
        """
        平仓并移出持仓列表

        :param symbol: 交易对
        :param order_id: 订单 ID
        :param pnl: 平仓盈亏
        :return: 是否平仓成功
        """
        with self._lock:
            self._ensure_daily_reset()
            positions = self._data["positions"]
            for i, pos in enumerate(positions):
                if pos.get("symbol") == symbol and pos.get("order_id") == order_id:
                    closed = positions.pop(i)
                    closed["closed_at"] = self._now_iso()
                    closed["realized_pnl"] = pnl
                    closed.setdefault("close_source", "system_close_position")
                    self._data["closed_positions"].append(closed)

                    # 更新日统计
                    stats = self._data["daily_stats"]
                    stats["total_trades"] += 1
                    if pnl < 0:
                        stats["loss_trades"] += 1
                        stats["consecutive_losses"] += 1
                    else:
                        stats["consecutive_losses"] = 0
                    stats["total_pnl"] = round(stats["total_pnl"] + pnl, 6)

                    self._save()
                    return True
            return False

    def partial_close_position(
        self,
        symbol: str,
        order_id: str,
        close_ratio: float,
        pnl: float = 0.0,
        updates: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        部分平仓：按比例减少持仓数量，更新止损等字段

        :param symbol: 交易对
        :param order_id: 订单 ID
        :param close_ratio: 平仓比例（0.0-1.0），如 0.3 表示平掉 30%
        :param pnl: 本次部分平仓的盈亏
        :param updates: 同时更新的字段（如 sl_price, tp_stage 等）
        :return: 是否成功
        """
        with self._lock:
            self._ensure_daily_reset()
            for pos in self._data["positions"]:
                if pos.get("symbol") == symbol and pos.get("order_id") == order_id:
                    old_size = float(pos.get("size", 0))
                    new_size = round(old_size * (1 - close_ratio), 8)

                    if new_size < 1:
                        # 剩余仓位不足 1 张，直接全平
                        return self.close_position(symbol, order_id, pnl)

                    pos["size"] = new_size
                    pos["margin"] = float(pos.get("margin", 0)) * (1 - close_ratio)

                    if updates:
                        pos.update(updates)

                    # 部分平仓也计入日统计
                    stats = self._data["daily_stats"]
                    stats["total_pnl"] = round(stats["total_pnl"] + pnl, 6)

                    self._save()
                    return True
            return False

    def close_all_positions(self, pnl_per_position: float = 0.0) -> List[Dict[str, Any]]:
        """
        平掉所有持仓

        :param pnl_per_position: 每个持仓的预估盈亏（实际以成交价计算）
        :return: 被平掉的持仓列表
        """
        with self._lock:
            self._ensure_daily_reset()
            closed = []
            for pos in self._data["positions"]:
                pos["closed_at"] = self._now_iso()
                pos["realized_pnl"] = pnl_per_position
                self._data["closed_positions"].append(pos)
                closed.append(pos)

            stats = self._data["daily_stats"]
            total_loss = pnl_per_position * len(closed)
            stats["total_trades"] += len(closed)
            if total_loss < 0:
                stats["loss_trades"] += len(closed)
                stats["consecutive_losses"] = len(closed)
            else:
                stats["consecutive_losses"] = 0
            stats["total_pnl"] = round(stats["total_pnl"] + total_loss, 6)
            stats["emergency_stop_triggered"] = True

            self._data["positions"] = []
            self._save()
            return closed

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取指定交易对的当前持仓"""
        with self._lock:
            for pos in self._data["positions"]:
                if pos.get("symbol") == symbol:
                    return pos
            return None

    def get_all_positions(self) -> List[Dict[str, Any]]:
        """获取所有当前持仓"""
        with self._lock:
            return list(self._data["positions"])

    def has_position(self, symbol: str) -> bool:
        """检查是否有指定交易对的持仓"""
        return self.get_position(symbol) is not None

    def position_count(self) -> int:
        """当前持仓数量"""
        with self._lock:
            return len(self._data["positions"])

    # ---- 每日统计 ----

    def get_daily_stats(self) -> Dict[str, Any]:
        """获取当日统计数据"""
        with self._lock:
            self._ensure_daily_reset()
            return dict(self._data["daily_stats"])

    def get_strategy_stats(self, strategy: str) -> Optional[StrategyStats]:
        """
        聚合策略历史统计 (Constitution §3.2 Kelly Criterion 决策输入, v1.8.2).

        从 closed_positions 过滤指定 strategy 的已平仓记录, 计算:
        - n: 该策略已平仓笔数
        - win_rate: 盈利笔数 / n (0.0-1.0)
        - avg_win_usd: 盈利笔平均 pnl (USD, 正数; 0 = 该策略从未盈利)
        - avg_loss_usd: 亏损笔平均 |pnl| (USD, 正数; 0 = 该策略从未亏损)

        :param strategy: 策略名 (与 closed_position["trigger_strategy"] 匹配)
        :return: StrategyStats if 至少 1 笔历史; None if 无历史
        """
        with self._lock:
            closed = self._data.get("closed_positions", [])
            my_trades = [
                c for c in closed
                if c.get("trigger_strategy") == strategy
            ]
            n = len(my_trades)
            if n == 0:
                return None

            # 优先取 realized_pnl (close_position 写入的路径)
            # 兼底 pnl (reconciliation 路径写入的)
            def _pnl(c: Dict[str, Any]) -> float:
                val = c.get("realized_pnl")
                if val is None:
                    val = c.get("pnl", 0.0)
                return float(val) if val is not None else 0.0

            wins = [_pnl(c) for c in my_trades if _pnl(c) > 0]
            losses = [abs(_pnl(c)) for c in my_trades if _pnl(c) < 0]

            win_rate = len(wins) / n
            avg_win_usd = (sum(wins) / len(wins)) if wins else 0.0
            avg_loss_usd = (sum(losses) / len(losses)) if losses else 0.0

            return StrategyStats(
                strategy=strategy,
                n=n,
                win_rate=win_rate,
                avg_win_usd=round(avg_win_usd, 6),
                avg_loss_usd=round(avg_loss_usd, 6),
            )

    def is_meltdown(self, max_consecutive_losses: int = 3) -> bool:
        """
        检查是否触发熔断（连续亏损达到上限）

        :param max_consecutive_losses: 最大允许连续亏损次数
        :return: 是否已熔断
        """
        with self._lock:
            self._ensure_daily_reset()
            return self._data["daily_stats"]["consecutive_losses"] >= max_consecutive_losses

    def get_last_loss_timestamp(self):
        """获取最后一次亏损的时间戳（用于冷静期判定）"""
        with self._lock:
            ts = self._data["daily_stats"].get("last_loss_at")
            if ts is None:
                return None
            from datetime import datetime
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                return None

    def _ensure_daily_reset(self) -> None:
        """检查是否跨日，跨日则重置日统计"""
        today = self._today()
        if self._data["daily_stats"]["date"] != today:
            self._data["daily_stats"] = {
                "date": today,
                "total_trades": 0,
                "loss_trades": 0,
                "consecutive_losses": 0,
                "total_pnl": 0.0,
                "total_fee": 0.0,
                "total_pnl_gross": 0.0,
                "last_loss_at": None,
                "emergency_stop_triggered": False,
            }

    # ---- 辅助查询 ----

    def get_positions_summary(self) -> Dict[str, Any]:
        """获取组合摘要"""
        with self._lock:
            positions = self._data["positions"]
            stats = self._data["daily_stats"]
            return {
                "position_count": len(positions),
                "symbols": [p["symbol"] for p in positions],
                "daily_pnl": stats["total_pnl"],
                "daily_trades": stats["total_trades"],
                "consecutive_losses": stats["consecutive_losses"],
                "emergency_stop": stats["emergency_stop_triggered"],
                "updated_at": self._data["updated_at"],
            }

    # ---- OKX 对账 ----

    def reconcile_with_okx(
        self,
        okx_positions: List[Dict[str, Any]],
        okx_history: Optional[List[Dict[str, Any]]] = None,
        ct_val_by_inst: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """以 OKX 真实持仓为准，重新对齐本地 portfolio。

        三种 reconcile 路径：
          - 本地有 / OKX 没有 → 视为外部平仓 → 归档到 closed_positions
          - 本地无 / OKX 有    → 手动开仓 → 按 0.3% SL + 1.5R 推荐加入 positions
          - 两边都有          → 检查 size/direction；一致保留，size 不一致归档旧的

        Returns:
          {
            "drift_detected": bool,
            "ghost_closed":   List[Dict],
            "new_synced":     List[Dict],
            "matched":        List[Dict],
            "mismatched":     List[Dict],
            "actions":        List[str],
            "local_position_count": int,
            "okx_position_count":   int,
          }
        """
        okx_history = okx_history or []
        ct_val_by_inst = ct_val_by_inst or {}
        with self._lock:
            self._ensure_daily_reset()
            now_str = self._now_iso()
            today = self._today()
            local_positions = list(self._data.get("positions", []))
            okx_by_key = {(p.get("instId"), p.get("posSide")): p for p in okx_positions}

            actions: List[str] = []
            ghost_closed: List[Dict[str, Any]] = []
            new_synced: List[Dict[str, Any]] = []
            matched: List[Dict[str, Any]] = []
            mismatched: List[Dict[str, Any]] = []

            daily = self._data["daily_stats"]
            # 如果本地 day 还没跨且今天不是 daily_stats 上的日期，重置到今天
            if daily.get("date") != today:
                daily["date"] = today
                daily["total_trades"] = 0
                daily["loss_trades"] = 0
                daily["consecutive_losses"] = 0
                daily["total_pnl"] = 0.0
                daily["total_fee"] = 0.0
                daily["total_pnl_gross"] = 0.0
                daily["last_loss_at"] = None
                daily["emergency_stop_triggered"] = False

            # ── 1. 遍历本地，匹配 / 归档 ──
            survivors: List[Dict[str, Any]] = []
            for lp in local_positions:
                norm_inst, pos_side = self._normalize_for_match(lp.get("symbol", ""), lp.get("direction"))
                key = (norm_inst, pos_side)

                if key not in okx_by_key:
                    # 外部已平 → 归档
                    close_info = self._extract_close_info(okx_history, lp)
                    realized = close_info.get("realized_pnl", 0.0) or 0.0
                    closed = dict(lp)
                    closed["closed_at"] = now_str
                    closed["realized_pnl"] = realized
                    closed["close_source"] = "external_close_detected_by_reconcile"
                    closed["close_meta"] = close_info
                    self._data["closed_positions"].append(closed)
                    ghost_closed.append(closed)

                    # 计入 daily（如果是今天）
                    close_ts = close_info.get("u_time")
                    close_date = (
                        datetime.fromtimestamp(close_ts).strftime("%Y-%m-%d")
                        if close_ts and close_ts > 0
                        else today
                    )
                    if daily["date"] != close_date:
                        # 跨日 → 那笔不计入今天的 daily
                        pass
                    else:
                        daily["total_trades"] += 1
                        if realized < 0:
                            daily["loss_trades"] += 1
                            daily["consecutive_losses"] += 1
                            daily["last_loss_at"] = now_str
                        else:
                            daily["consecutive_losses"] = 0
                        daily["total_pnl"] = round(daily["total_pnl"] + realized, 6)
                        daily["total_pnl_gross"] = round(daily["total_pnl_gross"] + realized, 6)
                        fee = close_info.get("fee")
                        if fee is not None:
                            daily["total_fee"] = round(daily["total_fee"] + fee, 6)

                    actions.append(
                        f"ghost → closed: {lp.get('symbol')} {lp.get('direction')} "
                        f"order_id={lp.get('order_id', '')} realized_pnl={realized:.6f}"
                    )
                    continue

                # 命中 OKX → 检查 size / direction 一致
                okx_p = okx_by_key[key]
                lp_sz = float(lp.get("size", 0) or 0)
                okx_sz = abs(float(okx_p.get("pos", 0) or 0))
                lp_dir = lp.get("direction")
                okx_dir = okx_p.get("posSide")

                if abs(lp_sz - okx_sz) < 1e-4 and lp_dir == okx_dir:
                    matched.append({"symbol": lp.get("symbol"), "size": lp_sz, "direction": lp_dir})
                    survivors.append(lp)
                else:
                    # size 不一致 → 归档旧的，从 OKX 拉新的
                    actions.append(
                        f"mismatch {lp.get('symbol')}: local {lp_dir} sz={lp_sz} "
                        f"vs OKX {okx_dir} sz={okx_sz} → archive local, rebuild from OKX"
                    )
                    closed = dict(lp)
                    closed["closed_at"] = now_str
                    closed["realized_pnl"] = 0.0
                    closed["close_source"] = "size_mismatch_replace"
                    self._data["closed_positions"].append(closed)
                    ghost_closed.append(closed)
                    mismatched.append({"local": lp, "okx": okx_p})

            # ── 2. 遍历 OKX，补齐本地缺失 ──
            existing_keys = set()
            for lp in survivors:
                norm_inst, pos_side = self._normalize_for_match(lp.get("symbol", ""), lp.get("direction"))
                existing_keys.add((norm_inst, pos_side))

            for op in okx_positions:
                key = (op.get("instId"), op.get("posSide"))
                if key in existing_keys:
                    continue

                entry = float(op.get("avgPx", 0) or 0)
                mark = float(op.get("markPx", 0) or 0) or entry
                sz = abs(float(op.get("pos", 0) or 0))
                lever = float(op.get("lever", 1) or 1)
                notional = mark * sz
                margin_est = round(notional / lever, 6) if lever > 0 else notional
                c_time_ms = int(op.get("cTime", 0) or 0)
                opened_iso = (
                    datetime.fromtimestamp(c_time_ms / 1000.0).isoformat(timespec="seconds")
                    if c_time_ms else now_str
                )
                pos_id = op.get("posId", "")
                direction = "long" if op.get("posSide") == "long" else "short"
                sl_tp = self._synthesize_sl_tp(entry, direction)
                ct_val = float(ct_val_by_inst.get(op.get("instId"), 1.0))

                new_pos = {
                    "symbol": (op.get("instId") or "").replace("-USDT-SWAP", "USDTSWAP"),
                    "direction": direction,
                    "entry_price": entry,
                    "size": sz,
                    "leverage": int(lever) if lever.is_integer() else lever,
                    "margin": margin_est,
                    "order_id": pos_id,
                    "opened_at": opened_iso,
                    "strategy": "EXTERNAL_WEB_SYNC",
                    "source": "okx_reconcile",
                    "sl_price": sl_tp["sl_price"],
                    "tp_price": sl_tp["tp_price"],
                    "tp_stage": 0,
                    "trigger_strategy": "EXTERNAL_WEB_SYNC",
                    "adl": op.get("adl", ""),
                    "mark_px_at_sync": mark,
                    "mgn_mode": op.get("mgnMode", "") or "",
                    "ct_val": ct_val,
                }
                survivors.append(new_pos)
                new_synced.append(new_pos)
                actions.append(
                    f"new → portfolio: {op.get('instId')} {direction} sz={sz} "
                    f"entry={entry:.4f} mark={mark:.4f} SL={sl_tp['sl_price']:.4f} TP={sl_tp['tp_price']:.4f}"
                )

            self._data["positions"] = survivors
            self._data["daily_stats"] = daily
            self._save()

            return {
                "drift_detected": bool(ghost_closed or new_synced or mismatched),
                "ghost_closed": ghost_closed,
                "new_synced": new_synced,
                "matched": matched,
                "mismatched": mismatched,
                "actions": actions,
                "local_position_count": len(survivors),
                "okx_position_count": len(okx_positions),
            }

    @staticmethod
    def _normalize_for_match(raw_symbol: str, direction: str) -> tuple:
        """把本地 symbol 归一到 (okx instId, posSide)。"""
        s = (raw_symbol or "").upper().replace("-", "").replace("/", "")
        for suffix in ("SWAP", "PERPETUAL", "PERP"):
            if s.endswith(suffix):
                s = s[: -len(suffix)]
                break
        if s.endswith("USDT") and len(s) > 4:
            base = s[:-4]
            inst_id = f"{base}-USDT-SWAP"
        else:
            inst_id = raw_symbol or ""
        pos_side = "long" if direction == "long" else "short"
        return inst_id, pos_side

    @staticmethod
    def _synthesize_sl_tp(entry: float, side: str, sl_pct: float = 0.003, rr: float = 1.5) -> Dict[str, float]:
        """按 Constitution 0.3% 止损 + 1.5R 推荐 SL/TP。
        long : SL = entry*(1-sl_pct), TP = entry*(1+sl_pct*rr)
        short: SL = entry*(1+sl_pct), TP = entry*(1-sl_pct*rr)
        """
        sl_distance = entry * sl_pct
        if side == "long":
            sl = entry - sl_distance
            tp = entry + sl_distance * rr
        else:
            sl = entry + sl_distance
            tp = entry - sl_distance * rr
        return {"sl_price": round(sl, 4), "tp_price": round(tp, 4)}

    @staticmethod
    def _extract_close_info(
        positions_history: List[Dict[str, Any]],
        local_pos: Dict[str, Any],
    ) -> Dict[str, Any]:
        """从 history 找匹配的已平仓记录，按 posId → instId+posSide → instId。"""
        inst_norm = (local_pos.get("symbol") or "").replace("USDTSWAP", "-USDT-SWAP")
        pos_side = "long" if local_pos.get("direction") == "long" else "short"
        order_id = local_pos.get("order_id", "")

        def _format(p: Dict) -> Dict[str, Any]:
            return {
                "close_avg_px": _safe_float(p.get("closeAvgPx")),
                "realized_pnl": _safe_float(p.get("realizedPnl")),
                "pnl": _safe_float(p.get("pnl")),
                "fee": _safe_float(p.get("fee")),
                "u_time": int(p.get("uTime", 0)) / 1000.0 if p.get("uTime") else None,
                "c_time": int(p.get("cTime", 0)) / 1000.0 if p.get("cTime") else None,
                "matched_by": f"history:{p.get('instId')}/{p.get('posSide')}",
            }

        def _safe_float(x, default=None):
            try:
                return float(x)
            except (TypeError, ValueError):
                return default

        if order_id and order_id != "web_manual":
            for p in positions_history:
                if p.get("posId") == order_id:
                    return _format(p)
        for p in positions_history:
            if p.get("instId") == inst_norm and p.get("posSide") == pos_side:
                return _format(p)
        for p in positions_history:
            if p.get("instId") == inst_norm:
                return _format(p)
        return {}

    def __repr__(self) -> str:
        return f"<Portfolio: {self.position_count()} positions>"
