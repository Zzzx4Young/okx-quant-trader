#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 1 撮合引擎（V2.1 严格实现）

核心约束（V2.1 关键点）：
1. **Strict index loop**：i 时刻只能看 df.iloc[:i]，绝不用 df.iloc[i+1:]
2. **Close 信号 + 下根 Open 成交**：信号在 i-1 close 生成，成交在 i open
3. **半开区间 (t_prev, t_curr] 资金费率**：V2.1 关键点 1
4. **Funding 严格小于 (策略信号源)**：V2.1 关键点 3

Phase 1 MVP 简化：
- 单一策略：EMA crossover（简化版，不接全 Constitution）
- 固定杠杆 5x
- 简化 SL/TP（固定 2x ATR）
- 不做 funding 信号判定（仅成本扣除）
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pandas as pd
import numpy as np

from .data_loader import BacktestData


# ─── 数据结构 ───

@dataclass
class Position:
    """虚拟持仓"""
    direction: str  # "long" / "short"
    entry_price: float
    size: float          # 张数（ctVal=0.1 for ETH, 0.01 for BTC 等；MVP 用标的数近似）
    leverage: int
    margin: float        # 占用的保证金
    entry_ts: int
    sl_price: float
    tp_price: float
    strategy: str
    
    @property
    def nominal_value(self) -> float:
        """名义价值 = size × entry_price（用于 funding 扣除）"""
        return self.size * self.entry_price


@dataclass
class Trade:
    """完整交易记录"""
    entry_ts: int
    exit_ts: int
    direction: str
    entry_price: float
    exit_price: float
    size: float
    leverage: int
    margin: float
    gross_pnl: float         # 毛利（不含 funding 和 fee）
    funding_fee: float       # 累计 funding 成本（>0 = 支付）
    fee: float               # 手续费（开仓+平仓）
    net_pnl: float           # 净 PnL
    strategy: str
    exit_reason: str         # "tp" / "sl" / "signal_reverse" / "end_of_data"
    bars_held: int           # 持仓 K 线数


@dataclass
class BacktestResult:
    """回测结果"""
    inst_id: str
    timeframe: str
    start_ts: int
    end_ts: int
    initial_capital: float
    final_equity: float
    total_return_pct: float
    trades: List[Trade]
    equity_curve: List[Tuple[int, float]]    # [(ts, equity), ...]
    funding_paid_total: float
    fee_paid_total: float
    
    @property
    def n_trades(self) -> int:
        return len(self.trades)
    
    @property
    def win_rate(self) -> float:
        wins = [t for t in self.trades if t.net_pnl > 0]
        return len(wins) / self.n_trades if self.n_trades > 0 else 0.0
    
    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        equities = [e for _, e in self.equity_curve]
        peak = equities[0]
        max_dd = 0.0
        for e in equities:
            peak = max(peak, e)
            dd = (peak - e) / peak
            max_dd = max(max_dd, dd)
        return max_dd * 100


# ─── 撮合引擎 ───

class BacktestEngine:
    """
    回测撮合引擎（V2.1 严格实现）

    使用示例：
        data = data_loader.load("BTC-USDT-SWAP", "1h", start_ts=..., end_ts=...)
        engine = BacktestEngine(data, initial_capital=10000)
        result = engine.run()
    """
    
    # 默认参数（Phase 1 MVP）
    DEFAULT_LEVERAGE = 5
    DEFAULT_TAKER_FEE = 0.0005       # 5 bps = 0.05% taker
    DEFAULT_RISK_PCT = 0.02          # 2% 账户风险
    DEFAULT_SL_ATR_MULT = 2.0        # 止损 = 2x ATR
    DEFAULT_TP_RR = 1.5              # 止盈 / 止损 = 1.5
    DEFAULT_EMA_FAST = 8
    DEFAULT_EMA_SLOW = 21
    DEFAULT_ATR_PERIOD = 14
    
    def __init__(
        self,
        data: BacktestData,
        initial_capital: float = 10000.0,
        leverage: int = DEFAULT_LEVERAGE,
        taker_fee: float = DEFAULT_TAKER_FEE,
        risk_per_trade: float = DEFAULT_RISK_PCT,
    ):
        self.data = data
        self.initial_capital = initial_capital
        self.equity = initial_capital
        self.leverage = leverage
        self.taker_fee = taker_fee
        self.risk_per_trade = risk_per_trade
        
        # 状态
        self.position: Optional[Position] = None
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[int, float]] = []
        self.funding_paid_total = 0.0
        self.fee_paid_total = 0.0
        self.current_funding_paid = 0.0  # 当前持仓期间累计 funding
    
    def run(self) -> BacktestResult:
        """
        运行回测（严格 V2.1 时间轴）

        Loop 步骤（每个 i ∈ [1, N)）：
        1. 资金费率结算：半开区间 (t_{i-1}, t_i]
        2. 检查止损：用 i-1 时刻的 low/high 触发（不是 i 时刻！）
        3. 检查止盈：用 i-1 时刻的 high/low 触发
        4. 用 df.iloc[:i] 计算 EMA crossover 信号（strict index）
        5. 信号撮合：在 i 时刻的 open 成交
        6. 记录净值（含未实现盈亏）
        """
        klines = self.data.klines
        funding_df = self.data.funding
        n = len(klines)
        
        for i in range(1, n):
            curr = klines.iloc[i]
            prev = klines.iloc[i-1]
            t_curr = int(curr.timestamp)
            t_prev = int(prev.timestamp)
            
            # ── Step 1: 资金费率结算（半开区间 V2.1 关键点 1）──
            if self.position is not None and not funding_df.empty:
                # V2.1 成本扣除规则：fundingTime in (t_prev, t_curr]
                in_bar = funding_df[
                    (funding_df["fundingTime_aligned"] > t_prev) &
                    (funding_df["fundingTime_aligned"] <= t_curr)
                ]
                for _, ev in in_bar.iterrows():
                    fee = self._calc_funding_fee(
                        nominal=self.position.nominal_value,
                        rate=ev.fundingRate,
                        direction=self.position.direction,
                    )
                    self.equity -= fee
                    self.funding_paid_total += fee
                    self.current_funding_paid += fee
            
            # ── Step 2: 检查止损（用 prev bar 的极值触发）──
            if self.position is not None:
                exit_reason = self._check_sl_tp(prev, curr)
                if exit_reason is not None:
                    self._close_position(
                        exit_price=float(curr.open),
                        exit_ts=t_curr,
                        reason=exit_reason,
                        bars_held=i - self._position_entry_index,
                    )
            
            # ── Step 3: 用 [0..i] 生成信号（strict index loop）──
            signal = self._generate_signal(i) if i >= self.DEFAULT_EMA_SLOW else None
            
            # ── Step 4: 信号撮合 ──
            if signal is not None:
                if signal == "long" and self.position is None:
                    self._open_position(
                        direction="long",
                        entry_price=float(curr.open),
                        entry_ts=t_curr,
                        prev_bar=prev,
                        curr_bar=curr,
                        strategy="EMA_CROSSOVER",
                        entry_index=i,
                    )
                elif signal == "short" and self.position is None:
                    self._open_position(
                        direction="short",
                        entry_price=float(curr.open),
                        entry_ts=t_curr,
                        prev_bar=prev,
                        curr_bar=curr,
                        strategy="EMA_CROSSOVER",
                        entry_index=i,
                    )
                elif signal == "close" and self.position is not None:
                    # 反向信号 → 平仓（不开新仓，留给后续 bar）
                    self._close_position(
                        exit_price=float(curr.open),
                        exit_ts=t_curr,
                        reason="signal_reverse",
                        bars_held=i - self._position_entry_index,
                    )
            
            # ── Step 5: 记录净值 ──
            mark = float(curr.close)
            unrealized = self._unrealized_pnl(mark) if self.position is not None else 0.0
            self.equity_curve.append((t_curr, self.equity + unrealized))
        
        # ── 末尾：强制平仓（如有持仓）──
        if self.position is not None:
            last = klines.iloc[-1]
            self._close_position(
                exit_price=float(last.close),
                exit_ts=int(last.timestamp),
                reason="end_of_data",
                bars_held=n - 1 - self._position_entry_index,
            )
            # 重写最后一根的净值（已平仓，无 unrealized）
            self.equity_curve[-1] = (int(last.timestamp), self.equity)
        
        # ── 返回结果 ──
        total_return = (self.equity - self.initial_capital) / self.initial_capital * 100
        
        return BacktestResult(
            inst_id=self.data.inst_id,
            timeframe=self.data.timeframe,
            start_ts=int(klines.iloc[0].timestamp),
            end_ts=int(klines.iloc[-1].timestamp),
            initial_capital=self.initial_capital,
            final_equity=self.equity,
            total_return_pct=total_return,
            trades=self.trades,
            equity_curve=self.equity_curve,
            funding_paid_total=self.funding_paid_total,
            fee_paid_total=self.fee_paid_total,
        )
    
    # ─── 策略（最简 EMA crossover） ───
    
    def _generate_signal(self, i: int) -> Optional[str]:
        """
        生成信号（V2.1 strict index：用 df.iloc[:i] 计算）
        
        简化 EMA crossover：
        - EMA8 上穿 EMA21 → long
        - EMA8 下穿 EMA21 → short
        - 反向穿越 → close（仅平仓）
        """
        closes = self.data.klines["close"].iloc[:i].values
        if len(closes) < self.DEFAULT_EMA_SLOW + 1:
            return None
        
        ema_fast = self._ema(closes, self.DEFAULT_EMA_FAST)
        ema_slow = self._ema(closes, self.DEFAULT_EMA_SLOW)
        
        # 当前 bar（i-1）刚走完，所以用 i-1 时刻的 EMA 判断
        curr_fast = ema_fast[-1]
        curr_slow = ema_slow[-1]
        prev_fast = ema_fast[-2]
        prev_slow = ema_slow[-2]
        
        # 金叉：fast 从下方穿越 slow
        long_signal = prev_fast <= prev_slow and curr_fast > curr_slow
        # 死叉：fast 从上方穿越 slow
        short_signal = prev_fast >= prev_slow and curr_fast < curr_slow
        
        if long_signal:
            return "long"
        if short_signal:
            return "short"
        # 反向穿越（如持 long 时 short 信号触发）→ 平仓
        if self.position is not None:
            if self.position.direction == "long" and short_signal:
                return "close"
            if self.position.direction == "short" and long_signal:
                return "close"
        return None
    
    # ─── 仓位管理 ───
    
    def _open_position(
        self, direction: str, entry_price: float, entry_ts: int,
        prev_bar, curr_bar, strategy: str, entry_index: int,
    ):
        """开仓（简化版：2% 风险原则 + ATR 止损）"""
        # ATR 用 prev_bar 的 ATR（已完全收盘）
        atr = self._atr(self.data.klines.iloc[:entry_index])
        if atr is None or atr <= 0:
            return
        
        sl_distance = max(atr * self.DEFAULT_SL_ATR_MULT, entry_price * 0.005)
        tp_distance = sl_distance * self.DEFAULT_TP_RR
        
        if direction == "long":
            sl_price = entry_price - sl_distance
            tp_price = entry_price + tp_distance
        else:
            sl_price = entry_price + sl_distance
            tp_price = entry_price - tp_distance
        
        # 仓位大小：2% 风险原则
        # 风险金额 = equity × 2%；每张合约风险 = sl_distance × size
        risk_amount = self.equity * self.risk_per_trade
        size = risk_amount / sl_distance if sl_distance > 0 else 0
        
        # 限制：不超过可用保证金的 leverage 倍
        max_size_by_margin = (self.equity * self.leverage) / entry_price
        size = min(size, max_size_by_margin)
        
        if size <= 0:
            return
        
        margin = (size * entry_price) / self.leverage
        fee = size * entry_price * self.taker_fee
        self.equity -= fee
        self.fee_paid_total += fee
        
        self.position = Position(
            direction=direction,
            entry_price=entry_price,
            size=size,
            leverage=self.leverage,
            margin=margin,
            entry_ts=entry_ts,
            sl_price=sl_price,
            tp_price=tp_price,
            strategy=strategy,
        )
        self._position_entry_index = entry_index
        self.current_funding_paid = 0.0
    
    def _close_position(
        self, exit_price: float, exit_ts: int, reason: str, bars_held: int,
    ):
        """平仓"""
        if self.position is None:
            return
        
        pos = self.position
        # PnL = (exit - entry) × size × direction_sign
        if pos.direction == "long":
            gross_pnl = (exit_price - pos.entry_price) * pos.size
        else:
            gross_pnl = (pos.entry_price - exit_price) * pos.size
        
        fee = pos.size * exit_price * self.taker_fee
        net_pnl = gross_pnl - fee - self.current_funding_paid
        
        self.equity += gross_pnl
        self.equity -= fee
        self.fee_paid_total += fee
        
        trade = Trade(
            entry_ts=pos.entry_ts,
            exit_ts=exit_ts,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            size=pos.size,
            leverage=pos.leverage,
            margin=pos.margin,
            gross_pnl=gross_pnl,
            funding_fee=self.current_funding_paid,
            fee=fee,
            net_pnl=net_pnl,
            strategy=pos.strategy,
            exit_reason=reason,
            bars_held=bars_held,
        )
        self.trades.append(trade)
        self.position = None
    
    # ─── 辅助 ───
    
    def _check_sl_tp(self, prev, curr) -> Optional[str]:
        """
        检查 SL/TP 触发：用 prev bar 的 high/low 触发（不是 curr！）
        成交价用 curr.open（i 时刻成交）
        """
        if self.position is None:
            return None
        prev_high = float(prev.high)
        prev_low = float(prev.low)
        if self.position.direction == "long":
            if prev_low <= self.position.sl_price:
                return "sl"
            if prev_high >= self.position.tp_price:
                return "tp"
        else:  # short
            if prev_high >= self.position.sl_price:
                return "sl"
            if prev_low <= self.position.tp_price:
                return "tp"
        return None
    
    def _calc_funding_fee(self, nominal: float, rate: float, direction: str) -> float:
        """
        计算单笔资金费率（>0 = 从账户扣除）

        多头：rate > 0 支付，rate < 0 收取
        空头：rate > 0 收取，rate < 0 支付
        """
        sign = 1.0 if direction == "long" else -1.0
        # fee > 0 = 账户付出；fee < 0 = 账户收取
        return nominal * rate * sign
    
    def _unrealized_pnl(self, mark_price: float) -> float:
        if self.position is None:
            return 0.0
        if self.position.direction == "long":
            return (mark_price - self.position.entry_price) * self.position.size
        else:
            return (self.position.entry_price - mark_price) * self.position.size
    
    # ─── 指标计算（numpy 向量化）───
    
    @staticmethod
    def _ema(data: np.ndarray, period: int) -> np.ndarray:
        if len(data) < period:
            return np.array([])
        k = 2 / (period + 1)
        ema = np.empty(len(data) - period + 1)
        ema[0] = data[:period].mean()
        for i in range(period, len(data)):
            ema[i - period + 1] = data[i] * k + ema[i - period] * (1 - k)
        return ema
    
    def _atr(self, df: pd.DataFrame) -> Optional[float]:
        """用 df 计算 ATR（last value）"""
        if len(df) < self.DEFAULT_ATR_PERIOD + 1:
            return None
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        trs = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )
        if len(trs) < self.DEFAULT_ATR_PERIOD:
            return None
        return float(trs[-self.DEFAULT_ATR_PERIOD:].mean())


__all__ = ["BacktestEngine", "BacktestResult", "Position", "Trade"]