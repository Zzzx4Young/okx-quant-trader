import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from okx.strategy_adapter import Signal  # Phase 2 顶层模块（与 okx.code.backtest 并列）

@dataclass
class PositionTranche:
    """分批止盈仓位子份额状态"""
    target_price: float
    ratio: float
    is_executed: bool = False

class ActivePosition:
    """活跃持仓状态机"""
    def __init__(self, signal: Signal, entry_price_with_slippage: float, total_margin: float, leverage: float):
        self.symbol = signal.symbol
        self.direction = signal.direction
        self.entry_price = entry_price_with_slippage  # 已扣除滑点的真实入场价
        self.stop_loss = signal.stop_loss
        self.leverage = leverage
        self.initial_margin = total_margin
        
        # 初始总名义价值
        self.nominal_value = total_margin * leverage
        self.remaining_ratio = 1.0  # 剩余未平仓位比例
        
        # 构建 3 批独立的止盈份额
        self.tranches = [
            PositionTranche(target_price=target, ratio=ratio)
            for target, ratio in zip(signal.tp_targets, signal.tp_ratios)
        ]
        self.realized_pnl = 0.0

class BacktestEngine:
    """
    高精度量化回测撮合引擎 (v2.1)
    支持 3-10倍 杠杆、5 bps 双向滑点、动态结算区间资金费率磨损与分批止盈执行。
    """
    def __init__(self, config: Dict[str, Any], market_df: pd.DataFrame, funding_df: pd.DataFrame):
        self.config = config
        self.market_df = market_df.sort_values('timestamp').reset_index(drop=True)
        self.funding_df = funding_df.sort_values('fundingTime').reset_index(drop=True)
        
        # 加载核心参数
        self.initial_balance = config.get("initial_balance", 1000.0)
        self.slippage_bps = config.get("slippage_bps", 5) # 5 bps
        self.taker_fee_rate = config.get("fee_taker_bps", 5) / 10000.0 # Taker 手续费 5 bps
        self.maker_fee_rate = config.get("fee_maker_bps", 2) / 10000.0 # Maker 手续费 2 bps
        self.leverage = config.get("leverage", 5.0)
        self.risk_pct_per_trade = config.get("risk_pct_per_trade", 0.02) # 单笔最大风控2%

        # 初始化账户状态
        self.balance = self.initial_balance
        self.active_position: Optional[ActivePosition] = None
        self.trade_history = []

    def _apply_slippage(self, price: float, direction: str, is_entry: bool) -> float:
        """
        滑点计算模型：
        市价单开仓/市价止损时，遭受不利的价格偏差。
        """
        slippage_pct = (self.slippage_bps / 10000.0)
        if direction == "LONG":
            # 做多：买入价变贵 (入场变高，止损变低)
            return price * (1.0 + slippage_pct) if is_entry else price * (1.0 - slippage_pct)
        else:
            # 做空：卖出价变贱 (入场变低，止损变高)
            return price * (1.0 - slippage_pct) if is_entry else price * (1.0 + slippage_pct)

    def run(self, strategy_adapter: "StrategyAdapter", strategy_name: str, symbol: str) -> Dict[str, Any]:
        """
        执行双指针无未来函数的高精度回测主循环。
        """
        total_bars = len(self.market_df)
        if total_bars < 50:
            return {"error": "Insufficient data"}

        print(f"开始回测：标的={symbol} | 策略={strategy_name} | 杠杆={self.leverage}x | 初始资金={self.balance} USDT")

        # 主时间步长循环 (从第20根 K线开始，保证历史数据完整)
        for i in range(20, total_bars):
            # 获取当前时间步
            current_bar = self.market_df.iloc[i]
            prev_bar = self.market_df.iloc[i-1]
            
            t_curr = int(current_bar['timestamp'])
            t_prev = int(prev_bar['timestamp'])
            
            high_price = float(current_bar['high'])
            low_price = float(current_bar['low'])
            open_price = float(current_bar['open'])

            # ==========================================
            # 1. 资金费率结算 (基于 (t_prev, t_curr] 闭合区间结算成本)
            # ==========================================
            if self.active_position:
                # 检索并扣除该 K 线周期内的动态资金费率
                settlements = self.funding_df[
                    (self.funding_df['fundingTime'] > t_prev) & 
                    (self.funding_df['fundingTime'] <= t_curr)
                ]
                for _, s in settlements.iterrows():
                    rate = float(s['fundingRate'])
                    # 多头：rate > 0 扣减，rate < 0 盈利
                    # 空头：rate > 0 盈利，rate < 0 扣减
                    direction_multiplier = 1.0 if self.active_position.direction == "LONG" else -1.0
                    funding_fee = self.active_position.nominal_value * rate * direction_multiplier
                    
                    self.balance -= funding_fee
                    # 强平防线检测
                    if self.balance <= 0:
                        self._force_liquidation(t_curr)
                        break

            if self.balance <= 0:
                print("账户已归零，爆仓强制终止。")
                break

            # ==========================================
            # 2. 已持仓位的硬止损与分批止盈校验 (T 周期 K线内部撮合)
            # ==========================================
            if self.active_position:
                pos = self.active_position
                is_closed = False

                # A. 校验硬止损 (Stop Loss - 触发市价，扣除滑点与 Taker 手续费)
                is_sl_triggered = False
                if pos.direction == "LONG" and low_price <= pos.stop_loss:
                    is_sl_triggered = True
                elif pos.direction == "SHORT" and high_price >= pos.stop_loss:
                    is_sl_triggered = True

                if is_sl_triggered:
                    # 触发止损，扣除不利滑点
                    execution_price = self._apply_slippage(pos.stop_loss, pos.direction, is_entry=False)
                    # 计算最终的整体盈亏率
                    price_return = (execution_price - pos.entry_price) / pos.entry_price if pos.direction == "LONG" else (pos.entry_price - execution_price) / pos.entry_price
                    pnl = pos.nominal_value * price_return
                    
                    # 扣减 Taker 离场手续费
                    fee = pos.nominal_value * self.taker_fee_rate
                    self.balance += pnl - fee
                    
                    self.trade_history.append({
                        "type": "STOP_LOSS",
                        "price": execution_price,
                        "pnl": pnl - fee,
                        "timestamp": t_curr
                    })
                    self.active_position = None
                    is_closed = True

                # B. 校验 3 批限价止盈 (Take Profit - 触发限价，无滑点，扣除 Maker 手续费)
                if not is_closed:
                    for idx, tranche in enumerate(pos.tranches):
                        if tranche.is_executed:
                            continue
                        
                        is_tp_triggered = False
                        if pos.direction == "LONG" and high_price >= tranche.target_price:
                            is_tp_triggered = True
                        elif pos.direction == "SHORT" and low_price <= tranche.target_price:
                            is_tp_triggered = True

                        if is_tp_triggered:
                            # 部分止盈按 Maker 成交 (挂单成交无滑点)
                            execution_price = tranche.target_price
                            tranche_nominal = pos.nominal_value * tranche.ratio
                            
                            # 计算本批次利润
                            price_return = (execution_price - pos.entry_price) / pos.entry_price if pos.direction == "LONG" else (pos.entry_price - execution_price) / pos.entry_price
                            tranche_pnl = tranche_nominal * price_return
                            
                            # 扣除部分减仓的 Maker 手续费
                            tranche_fee = tranche_nominal * self.maker_fee_rate
                            self.balance += tranche_pnl - tranche_fee
                            pos.nominal_value -= tranche_nominal # 削减底层名义总持仓
                            pos.remaining_ratio -= tranche.ratio
                            tranche.is_executed = True

                            self.trade_history.append({
                                "type": f"TAKE_PROFIT_{idx+1}",
                                "price": execution_price,
                                "pnl": tranche_pnl - tranche_fee,
                                "timestamp": t_curr
                            })

                    # 如果 3 批分批止盈全部完成，仓位安全归零
                    if pos.remaining_ratio <= 1e-5:
                        self.active_position = None

            # ==========================================
            # 3. 信号检测与开仓决策 (严格基于历史 df.iloc[:i] 避免未来函数)
            # ==========================================
            if not self.active_position:
                df_history = self.market_df.iloc[:i]
                # 注入近期资金费率用于策略D的提取
                if 'funding_rate' not in df_history.columns:
                    # 模糊对齐历史资金费率（信号隔离：可见费率时间戳严格小于 t_prev）
                    df_history = pd.merge_asof(
                        df_history, 
                        self.funding_df.rename(columns={'fundingRate': 'funding_rate'}),
                        left_on='timestamp', 
                        right_on='fundingTime', 
                        direction='backward'
                    )

                signal = strategy_adapter.get_signal(strategy_name, df_history, symbol)
                
                if signal:
                    # 开仓逻辑：计算风控约束下的最适保证金大小
                    risk_amount = self.balance * self.risk_pct_per_trade
                    price_risk_pct = abs(signal.entry_price - signal.stop_loss) / signal.entry_price
                    
                    if price_risk_pct > 0:
                        # 理论需要的总仓位名义价值
                        target_nominal = risk_amount / price_risk_pct
                        # 根据杠杆折算所需实际持仓保证金
                        required_margin = target_nominal / self.leverage
                        
                        # 账户可用余额限制保护
                        margin_amount = min(required_margin, self.balance * 0.95) # 最高动用95%资金
                        
                        if margin_amount > 10.0: # 最低交易额度过滤
                            # 开仓采用市价吃单 (Taker)：扣除不利滑点
                            entry_price_with_slippage = self._apply_slippage(signal.entry_price, signal.direction, is_entry=True)
                            
                            # 扣减开仓 Taker 手续费
                            entry_fee = (margin_amount * self.leverage) * self.taker_fee_rate
                            self.balance -= entry_fee
                            
                            self.active_position = ActivePosition(
                                signal=signal,
                                entry_price_with_slippage=entry_price_with_slippage,
                                total_margin=margin_amount,
                                leverage=self.leverage
                            )
                            
                            self.trade_history.append({
                                "type": "ENTRY_" + signal.direction,
                                "price": entry_price_with_slippage,
                                "pnl": -entry_fee,
                                "timestamp": t_curr
                            })

        return self._generate_report()

    def _force_liquidation(self, timestamp: int):
        """异常强制平仓清算"""
        self.active_position = None
        self.balance = 0.0
        self.trade_history.append({
            "type": "LIQUIDATION",
            "price": 0.0,
            "pnl": 0.0,
            "timestamp": timestamp
        })

    def _generate_report(self) -> Dict[str, Any]:
        """计算核心回测报告指标"""
        trades_df = pd.DataFrame(self.trade_history)
        if len(trades_df) == 0:
            return {"status": "No trades executed"}

        total_pnl = self.balance - self.initial_balance
        pnl_pct = (total_pnl / self.initial_balance) * 100.0
        
        # 统计纯交易事件
        closed_trades = trades_df[trades_df['type'].str.contains('STOP_LOSS|TAKE_PROFIT')]
        win_count = len(closed_trades[closed_trades['pnl'] > 0])
        total_closed = len(closed_trades)
        win_rate = (win_count / total_closed * 100.0) if total_closed > 0 else 0.0

        return {
            "initial_balance": self.initial_balance,
            "final_balance": self.balance,
            "total_pnl_usdt": total_pnl,
            "return_pct": pnl_pct,
            "total_trades_count": total_closed,
            "win_rate_pct": win_rate,
            "trade_log": trades_df.to_dict(orient='records')
        }