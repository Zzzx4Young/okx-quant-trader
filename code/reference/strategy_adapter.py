from dataclasses import dataclass
from typing import Optional, Dict, List, Any
import pandas as pd
import numpy as np

@dataclass
class Signal:
    """标准交易信号数据类"""
    symbol: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    tp_targets: List[float]       # 三批止盈的目标价格
    tp_ratios: List[float]        # 三批止盈对应的仓位比例 (如 [0.3, 0.3, 0.4])
    strategy_name: str
    timestamp_ms: int

class StrategyAdapter:
    """
    策略适配器：
    统一封装 EMA20_BREAKOUT, BB_RSI_REVERSION, VOLATILITY_BREAKOUT, FUNDING_RATE_REVERSAL 四大策略。
    从数据序列中提炼出标准交易信号，并计算 3 批止盈止损条件。
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.tp_partial_ratios = config.get("tp_partial_ratios", [0.3, 0.3, 0.4])
        self.tp_partial_rr = config.get("tp_partial_rr", [1.0, 1.5, 2.5])

    def get_signal(self, strategy_name: str, df_history: pd.DataFrame, symbol: str) -> Optional[Signal]:
        """
        根据不同的策略名称，调用对应的计算逻辑，并输出标准的分批止盈止损信号。
        """
        if len(df_history) < 20: # 保证基础计算周期
            return None

        # 提取当前K线收盘时间戳（毫秒级整数）
        current_bar = df_history.iloc[-1]
        timestamp_ms = int(current_bar['timestamp'])
        close_price = float(current_bar['close'])

        direction = None
        stop_loss = 0.0

        # ==========================================
        # 策略 A: EMA20_BREAKOUT (趋势突破)
        # ==========================================
        if strategy_name == "EMA20_BREAKOUT":
            # 模拟信号逻辑（此处在实盘中复用 signal.py 算法）
            ema20 = df_history['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            prev_close = df_history['close'].iloc[-2]
            prev_ema = df_history['close'].ewm(span=20, adjust=False).mean().iloc[-2]
            
            # 价格放量突破 EMA20
            if prev_close < prev_ema and close_price > ema20:
                direction = "LONG"
                # 止损设在 EMA20 下方 0.5% 或前一根K线最低点
                stop_loss = min(ema20 * 0.995, float(df_history['low'].iloc[-2]))
            elif prev_close > prev_ema and close_price < ema20:
                direction = "SHORT"
                stop_loss = max(ema20 * 1.005, float(df_history['high'].iloc[-2]))

        # ==========================================
        # 策略 B: BB_RSI_REVERSION (震荡均值回归)
        # ==========================================
        elif strategy_name == "BB_RSI_REVERSION":
            # 简单计算布林带与 RSI
            closes = df_history['close']
            ma20 = closes.rolling(20).mean().iloc[-1]
            std20 = closes.rolling(20).std().iloc[-1]
            upper_band = ma20 + 2 * std20
            lower_band = ma20 - 2 * std20
            
            # 计算简单 RSI-14
            delta = closes.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean().iloc[-1]
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean().iloc[-1]
            rs = gain / (loss + 1e-9)
            rsi = 100 - (100 / (1 + rs))

            if close_price <= lower_band and rsi < 30:
                direction = "LONG"
                stop_loss = close_price * 0.99  # 固定 1% 止损
            elif close_price >= upper_band and rsi > 70:
                direction = "SHORT"
                stop_loss = close_price * 1.01

        # ==========================================
        # 策略 C: VOLATILITY_BREAKOUT (波动率爆发)
        # ==========================================
        elif strategy_name == "VOLATILITY_BREAKOUT":
            # 计算 ATR (真实波幅) 与价格窄幅盘整
            highs = df_history['high']
            lows = df_history['low']
            closes = df_history['close']
            
            tr = pd.concat([highs - lows, abs(highs - closes.shift(1)), abs(lows - closes.shift(1))], axis=1).max(axis=1)
            atr14 = tr.rolling(14).mean()
            
            # 如果当前波动率处于近 100 期的极低水平，则判定为窄幅盘整后爆发
            if atr14.iloc[-1] < atr14.rolling(100).quantile(0.2).iloc[-1]:
                # 顺势突破前 5 根 K 线高点入场
                highest_5 = highs.iloc[-6:-1].max()
                lowest_5 = lows.iloc[-6:-1].min()
                if close_price > highest_5:
                    direction = "LONG"
                    stop_loss = lowest_5
                elif close_price < lowest_5:
                    direction = "SHORT"
                    stop_loss = highest_5

        # ==========================================
        # 策略 D: FUNDING_RATE_REVERSAL (资金费率反转)
        # ==========================================
        elif strategy_name == "FUNDING_RATE_REVERSAL":
            # 注意：此处输入数据通常需拼接 funding 费率数据
            # 仅在检测到极端资金费率时反向开仓 (多空情绪博弈)
            if 'funding_rate' in df_history.columns:
                last_rate = df_history['funding_rate'].iloc[-1]
                # 当年化资金费率极其畸高时（如多头单次扣费 0.1% 以上）
                if last_rate > 0.001:  
                    direction = "SHORT" # 做空极端情绪
                    stop_loss = close_price * 1.008  # 窄幅止损
                elif last_rate < -0.001:
                    direction = "LONG"
                    stop_loss = close_price * 0.992

        if direction and stop_loss > 0:
            # 严格计算风险距离 R (Risk Distance)
            risk_dist = abs(close_price - stop_loss)
            if risk_dist <= 0:
                return None

            # 计算 3 批分批止盈目标价格
            tp_targets = []
            for rr in self.tp_partial_rr:
                if direction == "LONG":
                    tp_price = close_price + (risk_dist * rr)
                else:
                    tp_price = close_price - (risk_dist * rr)
                tp_targets.append(tp_price)

            return Signal(
                symbol=symbol,
                direction=direction,
                entry_price=close_price,
                stop_loss=stop_loss,
                tp_targets=tp_targets,
                tp_ratios=self.tp_partial_ratios,
                strategy_name=strategy_name,
                timestamp_ms=timestamp_ms
            )

        return None