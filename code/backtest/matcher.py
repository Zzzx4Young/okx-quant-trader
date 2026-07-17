#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测撮合引擎（Phase 1 + Phase 2 增量合并）

═══ 严格 V2.1 时间轴（Phase 1 不变）═══
1. **Strict index loop**：i 时刻只能看 df.iloc[:i]，绝不用 df.iloc[i+1:]
2. **Close 信号 + 下根 Open 成交**：信号在 i-1 close 生成，成交在 i open
3. **半开区间 (t_prev, t_curr] 资金费率**：V2.1 关键点 1
4. **Funding 严格小于 (策略信号源)**：V2.1 关键点 3

═══ Phase 2 增强（高杠杆短线 1:1 镜像）═══
- 3 批独立 PositionTranche（Reduce-only）：每批 target_price + ratio，可独立成交
- Tranche 命中后 position.current_size 同步缩减 → 下 bar funding 自动按新 nominal
- 5bps Taker 滑点（Entry + SL）：买高卖低不利偏移
- TP 按 Maker 无滑点成交（按目标价精确 fill）
- SL 优先于 TP 同 bar 冲突（保守派原则）
- Trade 全生命周期：fills 列表记录 entry + tp_1/2/3 + sl/exit 每笔成交

参考设计：`okx/code/reference/matcher.py`
依赖文档：`okx/docs/backtest_system_design_report_V2.1.md`
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any, Callable

import pandas as pd
import numpy as np

from .data_loader import BacktestData
from . import metrics as _metrics


# ─── 数据结构 ───

@dataclass
class PositionTranche:
    """3 批独立止盈位置（reduce-only）"""
    target_price: float
    ratio: float                    # 0.3 / 0.3 / 0.4
    executed: bool = False
    executed_at_ts: Optional[int] = None


@dataclass
class FillEvent:
    """单次成交事件（entry / 部分 TP / 全平 SL）"""
    fill_type: str                  # "entry" / "tp_1" / "tp_2" / "tp_3" / "sl" / "signal_reverse" / "end_of_data"
    fill_price: float               # 实际成交价（TP/Maker 无滑点；Entry/SL/Taker 已含滑点）
    fill_size: float                # 本次成交合约张数
    fill_ts: int
    nominal_value: float            # 本次成交名义价值
    tranche_ratio: Optional[float] = None


@dataclass
class Position:
    """虚拟持仓（Phase 2：支持 3 批独立止盈 + 当前 size 动态缩减）"""
    direction: str                  # "long" / "short"
    entry_price: float              # 计划入场价（不含滑点）
    entry_fill_price: float         # 实际入场价（含 5bps Taker 滑点）
    initial_size: float             # 入场时合约张数
    current_size: float             # 剩余合约张数（tranche 命中后递减，0 = 全平）
    leverage: int
    margin: float
    entry_ts: int
    sl_price: float
    tranches: List[PositionTranche] = field(default_factory=list)
    strategy: str = ""
    
    @property
    def nominal_value(self) -> float:
        """当前名义价值（已按 tranche 折扣），用于 funding 扣除 — Phase 2 关键"""
        return self.current_size * self.entry_fill_price


@dataclass
class Trade:
    """完整交易记录（一笔 entry → 多次 fill → 全 close 的整条生命周期）"""
    entry_ts: int
    exit_ts: int
    direction: str
    entry_price: float              # 计划 entry
    entry_fill_price: float         # 实际 entry（含滑点）
    initial_size: float
    leverage: int
    margin: float
    gross_pnl: float                # 总毛利（不含 funding/fee/slippage）
    funding_fee: float              # 累计 funding 成本
    fee: float                      # 累计手续费
    slippage_cost: float            # 累计滑点成本
    net_pnl: float                  # 净 PnL
    strategy: str
    exit_reason: str                # "all_tp_hit" / "sl_full" / "signal_reverse" / "end_of_data"
    bars_held: int
    fills: List[FillEvent] = field(default_factory=list)
    
    @property
    def n_tranche_fills(self) -> int:
        return sum(1 for f in self.fills if f.fill_type.startswith("tp_"))
    
    @property
    def exit_price(self) -> Optional[float]:
        """向后兼容 Phase 1 字段：返回最后一次 fill 的成交价"""
        if not self.fills:
            return None
        return self.fills[-1].fill_price
    
    @property
    def avg_exit_price(self) -> Optional[float]:
        """加权平均 exit price（按各 fill size 加权）"""
        if not self.fills:
            return None
        # Skip the entry fill; only consider exit-side fills
        exit_fills = [f for f in self.fills if f.fill_type != "entry"]
        if not exit_fills:
            return None
        total_nominal = sum(f.fill_size * f.fill_price for f in exit_fills)
        total_size = sum(f.fill_size for f in exit_fills)
        return total_nominal / total_size if total_size > 0 else None


@dataclass
class BacktestResult:
    """回测结果聚合"""
    inst_id: str
    timeframe: str
    start_ts: int
    end_ts: int
    initial_capital: float
    final_equity: float
    total_return_pct: float
    trades: List[Trade]
    equity_curve: List[Tuple[int, float]]
    funding_paid_total: float
    fee_paid_total: float
    slippage_cost_total: float
    
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
    
    @property
    def total_tranche_fills(self) -> int:
        return sum(t.n_tranche_fills for t in self.trades)
    
    def metrics(self, risk_free_rate: float = 0.0) -> Dict[str, float]:
        """计算 Sharpe / Sortino / MaxDD / Calmar 等机构级指标"""
        return _metrics.compute_all_metrics(
            equity_curve=self.equity_curve,
            initial_capital=self.initial_capital,
            trades=self.trades,
            risk_free_rate=risk_free_rate,
        )


# ─── 撮合引擎 ───

class BacktestEngine:
    """
    回测撮合引擎（Phase 1 + Phase 2）
    
    使用：
        data = data_loader.load(...)
        engine = BacktestEngine(data, initial_capital=10000)
        result = engine.run()
    """
    
    # Phase 1 默认 + Phase 2 新增
    DEFAULT_LEVERAGE = 5
    DEFAULT_TAKER_FEE = 0.0005              # 5 bps = 0.05% taker
    DEFAULT_SLIPPAGE_BPS = 5                # Phase 2：Taker 滑点（Entry + SL 不利偏移）
    DEFAULT_TP_PARTIAL_RATIOS = (0.3, 0.3, 0.4)  # 3 批减仓比例
    DEFAULT_TP_PARTIAL_RR = (1.0, 1.5, 2.5)     # 3 批 TP 对应 R 倍数
    DEFAULT_RISK_PCT = 0.02
    DEFAULT_SL_ATR_MULT = 2.0
    DEFAULT_TP_RR = 1.5                     # Phase 1 单 TP 时用，Phase 2 默认忽略
    DEFAULT_EMA_FAST = 8
    DEFAULT_EMA_SLOW = 21
    DEFAULT_ATR_PERIOD = 14
    
    def __init__(
        self,
        data: BacktestData,
        initial_capital: float = 10000.0,
        leverage: int = DEFAULT_LEVERAGE,
        taker_fee: float = DEFAULT_TAKER_FEE,
        slippage_bps: int = DEFAULT_SLIPPAGE_BPS,           # Phase 2
        tp_partial_ratios: Tuple[float, ...] = DEFAULT_TP_PARTIAL_RATIOS,  # Phase 2
        tp_partial_rr: Tuple[float, ...] = DEFAULT_TP_PARTIAL_RR,           # Phase 2
        risk_per_trade: float = DEFAULT_RISK_PCT,
        signal_provider: Optional[Callable] = None,           # Phase 2: 可插拔策略信号
    ):
        self.data = data
        self.initial_capital = initial_capital
        self.equity = initial_capital
        self.leverage = leverage
        self.taker_fee = taker_fee
        self.slippage_bps = slippage_bps
        self.slippage = slippage_bps / 10000.0               # Phase 2
        self.tp_partial_ratios = tp_partial_ratios            # Phase 2
        self.tp_partial_rr = tp_partial_rr                    # Phase 2
        self.risk_per_trade = risk_per_trade
        self.signal_provider = signal_provider                 # Phase 2: 外部策略信号函数（None=默认EMA crossover）
        
        # 预计算指标（O(n) 一次，避免 _generate_signal 重复计算变 O(n²)）
        self._indicators = self._compute_indicators()
        
        # 状态
        self.position: Optional[Position] = None
        self.current_trade: Optional[Trade] = None  # Phase 2：累积 fill 事件
        self.current_funding_paid = 0.0
        self.current_slippage_cost = 0.0
        self.current_fee = 0.0
        self._pending_exit_reason: Optional[str] = None  # Phase 2：position 关闭后的 exit reason
        
        self.trades: List[Trade] = []
        self.equity_curve: List[Tuple[int, float]] = []
        self.funding_paid_total = 0.0
        self.fee_paid_total = 0.0
        self.slippage_cost_total = 0.0                        # Phase 2
    
    # ─── 核心运行循环 ───
    
    def run(self) -> BacktestResult:
        """
        运行回测（V2.1 严格 + Phase 2 增强）
        
        Loop 步骤（每个 i ∈ [1, N)）：
        1. 资金费率结算：用 position.nominal_value（已按 tranche 折扣）
        2. Phase 2：检查 SL + 3 批 tranche（用 prev bar high/low）
           - SL 命中 → 全平（5bps 滑点）
           - Tranche 命中 → 减仓 + 折扣 future funding nominal
        3. 仓位全平 → finalize Trade 归档
        4. 信号检测（strict index loop）
        5. 信号撮合（在 i 时刻 open 成交 + 5bps entry 滑点）
        6. 记录净值
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
            # Phase 2：用 current_size 反映 tranche 折扣（已在前 bar 处理过）
            if self.position is not None and not funding_df.empty:
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
                    if self.balance_is_zero():
                        self._force_liquidation(t_curr)
                        break
            
            if self.position is None and self.current_trade is None:
                # 爆仓或已平仓，继续到下一根
                pass
            
            # ── Step 2: Phase 2：SL + 3 批 tranche TP 检查 ──
            if self.position is not None:
                fills = self._process_fills(prev=prev, curr=curr, t_curr=t_curr)
                for fill in fills:
                    self._record_fill(fill)
                
                # Position 全平（SL hit / all TP hit / signal_reverse）→ finalize
                if self.position is None and self.current_trade is not None:
                    self._finalize_trade(
                        reason=self._pending_exit_reason or "all_tp_hit",
                        exit_ts=t_curr,
                        exit_idx=i,
                    )
            
            # ── Step 3: 信号检测（strict index loop）──
            signal = self._generate_signal(i) if i >= self.DEFAULT_EMA_SLOW else None
            
            # ── Step 4: 信号撮合 ──
            if signal is not None:
                if signal in ("long", "short") and self.position is None:
                    self._open_position(
                        direction=signal,
                        entry_price=float(curr.open),
                        entry_ts=t_curr,
                        prev_bar=prev,
                        curr_bar=curr,
                        strategy="EMA_CROSSOVER",
                        entry_index=i,
                    )
                elif signal == "close" and self.position is not None:
                    # 反向信号 → 全平 at curr.open（保守不计滑点）
                    self._full_close_at_price(
                        exit_price=float(curr.open),
                        exit_ts=t_curr,
                        reason="signal_reverse",
                        exit_idx=i,
                        apply_slippage=False,
                    )
            
            # ── Step 5: 记录净值（含未实现盈亏）──
            mark = float(curr.close)
            unrealized = self._unrealized_pnl(mark) if self.position is not None else 0.0
            self.equity_curve.append((t_curr, self.equity + unrealized))
        
        # ── 末尾：如有持仓则强平 ──
        if self.position is not None:
            last = klines.iloc[-1]
            self._full_close_at_price(
                exit_price=float(last.close),
                exit_ts=int(last.timestamp),
                reason="end_of_data",
                exit_idx=n - 1,
                apply_slippage=False,
            )
            if self.equity_curve:
                self.equity_curve[-1] = (int(last.timestamp), self.equity)
        
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
            slippage_cost_total=self.slippage_cost_total,
        )
    
    # ─── 策略（最简 EMA crossover 占位，Phase 3 接 ABCD adapter）───
    
    def _compute_indicators(self) -> Dict[str, pd.Series]:
        """
        预计算所有可能用到的指标。O(n) 一次。
        避免 _generate_signal 每根 bar 重算（O(n²) 卡死）。
        """
        df = self.data.klines
        closes = df["close"]
        highs = df["high"]
        lows = df["low"]
        
        # EMA（pandas vectorized）
        ema_8 = closes.ewm(span=8, adjust=False).mean()
        ema_20 = closes.ewm(span=20, adjust=False).mean()
        # v1.8: trend filter for 反趋势策略 (B · BB_RSI_REVERSION)
        ema_50 = closes.ewm(span=50, adjust=False).mean()
        ema_200 = closes.ewm(span=200, adjust=False).mean()
        
        # RSI(14)
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / (avg_loss + 1e-12)
        rsi_14 = 100 - (100 / (1 + rs))
        
        # Bollinger Bands(20, 1.4σ)
        bb_ma = closes.rolling(20).mean()
        bb_std = closes.rolling(20).std()
        bb_upper = bb_ma + 1.4 * bb_std
        bb_lower = bb_ma - 1.4 * bb_std
        bbw = (4 * bb_std) / (bb_ma + 1e-12)
        
        # 近 5 根 high/low
        high_5 = highs.rolling(5).max()
        low_5 = lows.rolling(5).min()
        
        return {
            "ema_8": ema_8,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "ema_200": ema_200,
            "rsi_14": rsi_14,
            "bb_ma_20": bb_ma,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "bbw": bbw,
            "high_5": high_5,
            "low_5": low_5,
        }
    
    def _generate_signal(self, i: int) -> Optional[str]:
        """V2.1 strict index：信号在 i-1 close 生成，成交在 i open。
        signal_provider 优先使用（ABCD adapter），否则默认 EMA crossover。"""
        
        # 优先：外部 signal_provider（新接口）
        if self.signal_provider is not None:
            return self.signal_provider(
                self.data.klines, i, self._indicators,
                self.position, self.data.funding, self.data.inst_id
            )
        
        # 默认：EMA crossover（用缓存指标，O(1) 每 bar）
        if i < self.DEFAULT_EMA_SLOW + 1:
            return None
        
        ema_fast = self._indicators["ema_8"]
        ema_slow = self._indicators["ema_20"]
        
        curr_fast = ema_fast.iloc[i-1]
        curr_slow = ema_slow.iloc[i-1]
        prev_fast = ema_fast.iloc[i-2]
        prev_slow = ema_slow.iloc[i-2]
        
        long_signal = prev_fast <= prev_slow and curr_fast > curr_slow
        short_signal = prev_fast >= prev_slow and curr_fast < curr_slow
        
        if long_signal:
            return "long"
        if short_signal:
            return "short"
        if self.position is not None:
            if self.position.direction == "long" and short_signal:
                return "close"
            if self.position.direction == "short" and long_signal:
                return "close"
        return None
    
    # ─── Phase 2：滑点应用 ───
    
    def _apply_slippage(self, price: float, direction: str, is_entry: bool) -> float:
        """
        Taker 滑点（5bps 不利偏移）：
        - 做多 entry：买高 → price × (1 + slip)
        - 做多 SL exit：卖低 → price × (1 - slip)
        - 做空 entry：卖低 → price × (1 - slip)
        - 做空 SL exit：买高 → price × (1 + slip)
        
        TP 路径不走这里（Maker 无滑点）。
        """
        if direction == "long":
            # entry 买高 / SL 卖低
            return price * (1 + self.slippage) if is_entry else price * (1 - self.slippage)
        else:
            # entry 卖低 / SL 买高
            return price * (1 - self.slippage) if is_entry else price * (1 + self.slippage)
    
    # ─── 开仓（Phase 2：滑点 + 3 批 tranche）───
    
    def _open_position(
        self, direction: str, entry_price: float, entry_ts: int,
        prev_bar, curr_bar, strategy: str, entry_index: int,
    ):
        atr = self._atr(self.data.klines.iloc[:entry_index])
        if atr is None or atr <= 0:
            return
        
        sl_distance = max(atr * self.DEFAULT_SL_ATR_MULT, entry_price * 0.005)
        
        if direction == "long":
            sl_price = entry_price - sl_distance
        else:
            sl_price = entry_price + sl_distance
        
        # 仓位大小：2% 风险原则
        risk_amount = self.equity * self.risk_per_trade
        size = risk_amount / sl_distance if sl_distance > 0 else 0
        max_size_by_margin = (self.equity * self.leverage) / entry_price
        size = min(size, max_size_by_margin)
        
        if size <= 0:
            return
        
        margin = (size * entry_price) / self.leverage
        
        # ── Phase 2-1: 入场滑点（Taker 5bps 不利偏移）──
        entry_fill_price = self._apply_slippage(entry_price, direction, is_entry=True)
        slip_cost = abs(entry_fill_price - entry_price) * size
        self.equity -= slip_cost
        self.slippage_cost_total += slip_cost
        self.current_slippage_cost = slip_cost
        
        # ── Phase 2-2: 3 批独立 tranche（基于 entry_fill_price 算 R-distance）──
        risk_dist = abs(entry_fill_price - sl_price)
        tranches = []
        for ratio, rr in zip(self.tp_partial_ratios, self.tp_partial_rr):
            if direction == "long":
                tp_price = entry_fill_price + risk_dist * rr
            else:
                tp_price = entry_fill_price - risk_dist * rr
            tranches.append(PositionTranche(target_price=tp_price, ratio=ratio))
        
        self.position = Position(
            direction=direction,
            entry_price=entry_price,
            entry_fill_price=entry_fill_price,
            initial_size=size,
            current_size=size,
            leverage=self.leverage,
            margin=margin,
            entry_ts=entry_ts,
            sl_price=sl_price,
            tranches=tranches,
            strategy=strategy,
        )
        
        # 入场 fee（Taker）
        entry_fee = size * entry_fill_price * self.taker_fee
        self.equity -= entry_fee
        self.fee_paid_total += entry_fee
        self.current_fee = entry_fee
        
        # 启动新 trade 记录
        self._pending_exit_reason = None
        self.current_funding_paid = 0.0
        self.current_trade = Trade(
            entry_ts=entry_ts,
            exit_ts=entry_ts,
            direction=direction,
            entry_price=entry_price,
            entry_fill_price=entry_fill_price,
            initial_size=size,
            leverage=self.leverage,
            margin=margin,
            gross_pnl=0.0,
            funding_fee=0.0,
            fee=entry_fee,
            slippage_cost=slip_cost,
            net_pnl=-entry_fee - slip_cost,
            strategy=strategy,
            exit_reason="open",
            bars_held=0,
        )
        self.current_trade.fills.append(FillEvent(
            fill_type="entry",
            fill_price=entry_fill_price,
            fill_size=size,
            fill_ts=entry_ts,
            nominal_value=size * entry_fill_price,
        ))
    
    # ─── Phase 2 核心：fill 处理（SL + 3 批 tranche）───
    
    def _process_fills(self, prev, curr, t_curr: int) -> List[FillEvent]:
        """
        检查 SL 和 3 批 tranche 是否触发（用 prev bar high/low 触发判定）。
        
        返回 fill 事件列表。
        规则（保守派）：
        - SL 优先于 TP（一旦 SL 触发 → 整笔全平，tranches 全清，不检查 TP）
        - 多个 tranche 同 bar 触发 → 全记录（每个独立 fill）
        """
        if self.position is None:
            return []
        
        pos = self.position
        fills: List[FillEvent] = []
        prev_high = float(prev.high)
        prev_low = float(prev.low)
        
        # ── A. SL 检查（Taker，市价，5bps 滑点）──
        sl_hit = (
            (pos.direction == "long" and prev_low <= pos.sl_price) or
            (pos.direction == "short" and prev_high >= pos.sl_price)
        )
        
        if sl_hit:
            exit_fill = self._apply_slippage(pos.sl_price, pos.direction, is_entry=False)
            slip_cost_here = abs(exit_fill - pos.sl_price) * pos.current_size
            self.equity -= slip_cost_here
            self.slippage_cost_total += slip_cost_here
            self.current_slippage_cost += slip_cost_here
            
            fills.append(FillEvent(
                fill_type="sl",
                fill_price=exit_fill,
                fill_size=pos.current_size,
                fill_ts=t_curr,
                nominal_value=pos.current_size * exit_fill,
            ))
            self._pending_exit_reason = "sl_full"
            return fills  # SL = full close, 不再检查 tranche
        
        # ── B. 3 批 tranche TP 检查（Maker，无滑点，按目标价 fill）──
        for idx, tranche in enumerate(pos.tranches):
            if tranche.executed:
                continue
            
            tp_hit = (
                (pos.direction == "long" and prev_high >= tranche.target_price) or
                (pos.direction == "short" and prev_low <= tranche.target_price)
            )
            
            if not tp_hit:
                continue
            
            tranche.executed = True
            tranche.executed_at_ts = t_curr
            
            tranche_size = pos.initial_size * tranche.ratio
            tranche_nominal = tranche_size * pos.entry_fill_price
            
            # 关键：缩减小 current_size → 下 bar funding 自动 recalculating
            pos.current_size -= tranche_size
            if pos.current_size < 1e-9:
                pos.current_size = 0
            
            # Tranche fill fee（Taker 同档；OKX maker 2bps 更优；本阶段统一 taker 简化）
            tranche_fee = tranche_nominal * self.taker_fee
            self.equity -= tranche_fee
            self.fee_paid_total += tranche_fee
            self.current_fee += tranche_fee
            
            fills.append(FillEvent(
                fill_type=f"tp_{idx+1}",
                fill_price=tranche.target_price,
                fill_size=tranche_size,
                fill_ts=t_curr,
                nominal_value=tranche_nominal,
                tranche_ratio=tranche.ratio,
            ))
        
        # 全部 tranche 都执行完 → all_tp_hit
        if pos.current_size == 0:
            self._pending_exit_reason = "all_tp_hit"
        
        return fills
    
    # ─── fill 记录 + trade finalize ───
    
    def _record_fill(self, fill: FillEvent):
        """把 fill 累加到 current_trade.fills 并计入 gross_pnl"""
        if self.current_trade is None:
            return
        
        self.current_trade.fills.append(fill)
        
        pos = self.position
        if pos is not None:
            # 该 fill 的 PnL 贡献
            if pos.direction == "long":
                gross = (fill.fill_price - pos.entry_fill_price) * fill.fill_size
            else:
                gross = (pos.entry_fill_price - fill.fill_price) * fill.fill_size
            self.current_trade.gross_pnl += gross
            
            # 资金回流（用户视角：close 减仓时 gain 释放回账户）
            # net cashflow = gross PnL - fee（已扣）- slippage（已扣）
            # 但 self.equity 已连续扣过 fee/slip；这里只把 gross 回收
            self.equity += gross
            
            # 如果是 SL fill → 仓位全平，标记给外层 finalize（修 Bug 1）
            if fill.fill_type == "sl":
                self.position = None
    
    def _finalize_trade(self, reason: str, exit_ts: int, exit_idx: int):
        """trade 收尾：累计 funding + 算 net_pnl + 归档"""
        if self.current_trade is None:
            return
        
        trade = self.current_trade
        trade.funding_fee = self.current_funding_paid
        trade.slippage_cost = self.current_slippage_cost
        trade.exit_ts = exit_ts
        trade.exit_reason = reason
        if trade.fills:
            trade.bars_held = max(0, exit_idx - trade.entry_ts // 3600000 if isinstance(trade.entry_ts, int) and exit_idx else 0)
        trade.net_pnl = trade.gross_pnl - trade.fee - trade.funding_fee
        
        self.trades.append(trade)
        self.current_trade = None
        self.position = None
        self._pending_exit_reason = None
        self.current_funding_paid = 0.0
        self.current_slippage_cost = 0.0
        self.current_fee = 0.0
    
    def _full_close_at_price(
        self, exit_price: float, exit_ts: int, reason: str, exit_idx: int,
        apply_slippage: bool = False,
    ):
        """
        信号反转 / 末尾强平：全仓 close at 指定价。
        apply_slippage=False 默认（保守派：反转信号不算滑点，因为是市价但非 break-out）
        """
        if self.position is None or self.current_trade is None:
            return
        
        pos = self.position
        if apply_slippage:
            exit_fill = self._apply_slippage(exit_price, pos.direction, is_entry=False)
            slip_cost = abs(exit_fill - exit_price) * pos.current_size
            self.equity -= slip_cost
            self.slippage_cost_total += slip_cost
            self.current_slippage_cost += slip_cost
        else:
            exit_fill = exit_price
        
        self.current_trade.fills.append(FillEvent(
            fill_type=reason,
            fill_price=exit_fill,
            fill_size=pos.current_size,
            fill_ts=exit_ts,
            nominal_value=pos.current_size * exit_fill,
        ))
        
        # Gross PnL
        if pos.direction == "long":
            gross = (exit_fill - pos.entry_fill_price) * pos.current_size
        else:
            gross = (pos.entry_fill_price - exit_fill) * pos.current_size
        self.current_trade.gross_pnl += gross
        self.equity += gross
        
        # 标记为全平（current_size=0），触发 finalize
        pos.current_size = 0
        self._pending_exit_reason = reason
        self._finalize_trade(reason=reason, exit_ts=exit_ts, exit_idx=exit_idx)
    
    def _force_liquidation(self, timestamp: int):
        """账户归零爆仓"""
        if self.position is not None:
            pos = self.position
            if self.current_trade is not None:
                self.current_trade.fills.append(FillEvent(
                    fill_type="liquidation",
                    fill_price=float(pos.entry_fill_price),
                    fill_size=pos.current_size,
                    fill_ts=timestamp,
                    nominal_value=pos.current_size * pos.entry_fill_price,
                ))
            self._pending_exit_reason = "liquidation"
            self._finalize_trade(reason="liquidation", exit_ts=timestamp, exit_idx=-1)
        self.equity = 0.0
    
    def balance_is_zero(self) -> bool:
        return self.equity <= 0 and self.position is not None
    
    # ─── 辅助 ───
    
    def _calc_funding_fee(self, nominal: float, rate: float, direction: str) -> float:
        sign = 1.0 if direction == "long" else -1.0
        return nominal * rate * sign
    
    def _unrealized_pnl(self, mark_price: float) -> float:
        if self.position is None:
            return 0.0
        if self.position.direction == "long":
            return (mark_price - self.position.entry_fill_price) * self.position.current_size
        else:
            return (self.position.entry_fill_price - mark_price) * self.position.current_size
    
    # ─── 指标计算 ───
    
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


__all__ = [
    "BacktestEngine", "BacktestResult",
    "Position", "PositionTranche", "FillEvent", "Trade",
]
