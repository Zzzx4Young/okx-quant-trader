# -*- coding: utf-8 -*-
"""
OKX 交易信号引擎

负责：
- 从市场数据计算技术指标（EMA20）
- 生成标准化的 signal dict
- 信号过滤与校验
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import get_config
from .market import MarketAPI


class Signal:
    """标准化信号对象"""

    def __init__(
        self,
        strategy: str,
        symbol: str,
        direction: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        leverage: int,
        size: float,
        confidence: float,
        reason: str,
        kline_time: str,
    ):
        self.strategy = strategy
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.sl_price = sl_price
        self.tp_price = tp_price
        self.leverage = leverage
        self.size = size
        self.confidence = confidence
        self.reason = reason
        self.kline_time = kline_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "sl_price": self.sl_price,
            "tp_price": self.tp_price,
            "leverage": self.leverage,
            "size": self.size,
            "confidence": self.confidence,
            "reason": self.reason,
            "kline_time": self.kline_time,
        }

    def __repr__(self) -> str:
        return (
            f"<Signal {self.symbol} {self.direction} "
            f"entry={self.entry_price} sl={self.sl_price} tp={self.tp_price} "
            f"leverage={self.leverage}x>"
        )


class SignalEngine:
    """
    策略信号引擎

    支持策略：
    - EMA20_BREAKOUT（已激活）
    - BB_RSI_REVERSION（预留，暂不激活）
    """

    def __init__(self, market_api: MarketAPI, config: Optional[Any] = None):
        self._market = market_api
        self._config = config or get_config()

    # ---- EMA20 策略 ----

    def check_ema20_signal(
        self,
        symbol: str,
        current_position_direction: Optional[str] = None,
    ) -> Optional[Signal]:
        """
        检查 EMA20 均线突破信号

        :param symbol: 交易对，如 'BTCUSDT'
        :param current_position_direction: 当前持仓方向（None 表示无持仓）
        :return: Signal 或 None（无信号）
        """
        if not self._config.strategy_a_enabled:
            return None

        timeframe = self._config.timeframe
        ema_period = self._config.strategy_a_ema_period
        confirm_count = self._config.strategy_a_kline_count
        vol_ratio = self._config.strategy_a_volume_ratio

        # 获取最近 K 线数据（多取几根用于计算 EMA）
        candles = self._market.get_candles(symbol, bar=timeframe, limit=ema_period + confirm_count + 5)
        if not candles or len(candles) < ema_period + confirm_count:
            return None

        # 解析 K 线数据
        # OKX K线格式: [ts, open, high, low, close, vol, volCcy, volQuote]
        closes = [float(c[4]) for c in candles]  # 收盘价列表
        volumes = [float(c[5]) for c in candles]  # 成交量列表
        highs = [float(c[2]) for c in candles]    # 最高价列表
        lows = [float(c[3]) for c in candles]     # 最低价列表
        last_time = candles[-1][0]  # 最后一根 K 线时间戳

        # ── 计算 ATR14 ──
        atr_period = self._config.strategy_a_atr_period
        atr_values = self._atr(highs, lows, closes, period=atr_period)
        current_atr = atr_values[-1] if atr_values else None

        # ── 计算 RSI14 ──
        rsi_period = self._config.get("strategy_a.rsi_period", 14)
        rsi_overbought = self._config.get("strategy_a.rsi_overbought", 65)
        rsi_oversold = self._config.get("strategy_a.rsi_oversold", 35)
        rsi_values = self._rsi(closes, period=rsi_period)
        current_rsi = rsi_values[-1] if rsi_values else None

        # ── 计算 EMA20 ──
        ema_values = self._ema(closes, period=ema_period)
        if not ema_values or len(ema_values) < confirm_count + 1:
            return None

        current_price = closes[-1]
        current_ema = ema_values[-1]

        # ── 方向判断 ──
        # 最近 confirm_count 根 K 线收盘价
        recent_closes = closes[-(confirm_count):]
        recent_ema_values = ema_values[-(confirm_count):]

        # 检查是否连续高于/低于 EMA
        all_above = all(c > e for c, e in zip(recent_closes, recent_ema_values))
        all_below = all(c < e for c, e in zip(recent_closes, recent_ema_values))

        # EMA 方向（3 根 K 线线性回归斜率，替代简单 prev < current）
        ema_turning_up = False
        ema_turning_down = False
        if len(ema_values) >= 3:
            recent_3_ema = ema_values[-3:]
            slope = self._linear_slope(recent_3_ema)
            prev_slope = self._linear_slope(ema_values[-4:-1]) if len(ema_values) >= 4 else 0

            # 上翘：斜率为正 且 前一斜率为负或平（由降转升）
            ema_turning_up = slope > 0 and prev_slope <= 0 and all_above
            # 下拐：斜率为负 且 前一斜率为正或平（由升转降）
            ema_turning_down = slope < 0 and prev_slope >= 0 and all_below

        # ── 量价配合 ──
        avg_vol = sum(volumes[-6:-1]) / 5  # 前5根平均成交量
        signal_vol = volumes[-1]
        vol_ok = signal_vol >= avg_vol * vol_ratio

        # ── 生成信号 ──
        direction = None
        reason = ""

        if current_position_direction != "long" and all_above and ema_turning_up and vol_ok:
            # RSI 过滤：做多时不追超买
            if current_rsi is not None and current_rsi >= rsi_overbought:
                pass  # RSI 过高，跳过
            else:
                direction = "long"
                rsi_note = f" RSI={current_rsi:.1f}" if current_rsi else ""
                reason = f"EMA20上穿 + 放量突破（成交量 {signal_vol/avg_vol:.1f}x 均量{rsi_note}）"
        elif current_position_direction != "short" and all_below and ema_turning_down and vol_ok:
            # RSI 过滤：做空时不追超卖
            if current_rsi is not None and current_rsi <= rsi_oversold:
                pass  # RSI 过低，跳过
            else:
                direction = "short"
                rsi_note = f" RSI={current_rsi:.1f}" if current_rsi else ""
                reason = f"EMA20下穿 + 放量突破（成交量 {signal_vol/avg_vol:.1f}x 均量{rsi_note}）"

        if direction is None:
            return None

        # ── 计算止损止盈（ATR 动态止损） ──
        atr_multiplier = self._config.atr_multiplier  # 默认 2.0
        min_rr = self._config.min_reward_risk_ratio

        if current_atr and current_atr > 0:
            # 动态止损 = ATR × 倍数
            sl_distance_atr = current_atr * atr_multiplier

            # 保底：止损距离不低于 0.5%（防止 ATR 极小时止损过窄）
            sl_distance_min = current_price * (self._config.sl_buffer_percent / 100.0)
            sl_distance = max(sl_distance_atr, sl_distance_min)
        else:
            # ATR 计算失败时回退到固定百分比
            sl_distance = current_price * (self._config.sl_buffer_percent / 100.0)

        if direction == "long":
            sl_price = current_price - sl_distance
            tp_price = current_price + sl_distance * min_rr
        else:
            sl_price = current_price + sl_distance
            tp_price = current_price - sl_distance * min_rr

        confidence = self._calc_confidence(direction, all_above, all_below, vol_ok, avg_vol, signal_vol, current_rsi, rsi_overbought, rsi_oversold)

        kline_time = datetime.fromtimestamp(int(last_time) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return Signal(
            strategy="EMA20_BREAKOUT",
            symbol=symbol,
            direction=direction,
            entry_price=round(current_price, 8),
            sl_price=round(sl_price, 8),
            tp_price=round(tp_price, 8),
            leverage=self._get_leverage(symbol),
            size=0.0,  # 由 risk.py 重新计算
            confidence=round(confidence, 3),
            reason=reason,
            kline_time=kline_time,
        )

    def check_bb_rsi_signal(
        self,
        symbol: str,
        current_position_direction: Optional[str] = None,
    ) -> Optional[Signal]:
        """
        检查布林带 + RSI 均值回归信号（策略 B）

        做空条件：
        1. RSI(14) > 超买阈值（70）
        2. 收盘价刺破布林带上轨
        3. 出现反转 K 线（流星线/看跌吞没）

        做多条件：
        1. RSI(14) < 超卖阈值（30）
        2. 收盘价刺破布林带下轨
        3. 出现反转 K 线（锤子线/看涨吞没）

        :param symbol: 交易对
        :param current_position_direction: 当前持仓方向
        :return: Signal 或 None
        """
        if not self._config.strategy_b_enabled:
            return None

        timeframe = self._config.timeframe
        bb_period = self._config.strategy_b_bb_period
        bb_std = self._config.strategy_b_bb_std
        rsi_period = self._config.strategy_b_rsi_period
        rsi_overbought = self._config.strategy_b_rsi_overbought
        rsi_oversold = self._config.strategy_b_rsi_oversold

        candles = self._market.get_candles(symbol, bar=timeframe, limit=bb_period + 10)
        if not candles or len(candles) < bb_period + 2:
            return None

        closes = [float(c[4]) for c in candles]
        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]
        volumes = [float(c[5]) for c in candles]
        last_time = candles[-1][0]

        # v1.8 Fix A: 趋势过滤需要 200 根 K 线，确保足够回溯
        if len(closes) < 200:
            return None  # 不足 200 根不开 B 策略 (v1.8)

        # ── 计算布林带 ──
        bb_bands = self._bollinger_bands(closes, period=bb_period, std_dev=bb_std)
        if not bb_bands:
            return None

        upper_band, middle_band, lower_band = bb_bands[-1]
        prev_upper, prev_middle, prev_lower = bb_bands[-2]

        current_price = closes[-1]
        prev_close = closes[-2]
        current_high = highs[-1]
        current_low = lows[-1]

        # ── 计算 RSI ──
        rsi_values = self._rsi(closes, period=rsi_period)
        current_rsi = rsi_values[-1] if rsi_values else None
        if current_rsi is None:
            return None

        # ── 反转 K 线形态检测 ──
        # 看跌反转：流星线（上影线 > 实体 ×2）或 看跌吞没（当前实体覆盖前一根且方向反）
        bearish_reversal = False
        current_body = abs(current_price - closes[-2]) if len(closes) >= 2 else 0
        upper_shadow = current_high - max(current_price, prev_close) if len(closes) >= 2 else 0
        if current_body > 0 and upper_shadow > current_body * 2:
            bearish_reversal = True  # 流星线
        if len(closes) >= 2 and prev_close < closes[-2] and current_price < prev_close:
            bearish_reversal = True  # 看跌吞没简化

        # 看涨反转：锤子线（下影线 > 实体 ×2）或 看涨吞没
        bullish_reversal = False
        lower_shadow = min(current_price, prev_close) - current_low if len(closes) >= 2 else 0
        if current_body > 0 and lower_shadow > current_body * 2:
            bullish_reversal = True  # 锤子线
        if len(closes) >= 2 and prev_close > closes[-2] and current_price > prev_close:
            bullish_reversal = True  # 看涨吞没简化

        # ── 生成信号 ──
        direction = None
        reason = ""

        if (
            current_position_direction != "short"
            and current_rsi > rsi_overbought
            and current_price > upper_band
            and bearish_reversal
        ):
            direction = "short"
            reason = f"BB上轨突破 + RSI超买({current_rsi:.1f}) + 反转K线"

        elif (
            current_position_direction != "long"
            and current_rsi < rsi_oversold
            and current_price < lower_band
            and bullish_reversal
        ):
            direction = "long"
            reason = f"BB下轨突破 + RSI超卖({current_rsi:.1f}) + 反转K线"

        # v1.8 Fix A: EMA50/EMA200 趋势过滤（与 backtest 对齐）
        # - 多头趋势 (ema50 > ema200) → 禁多（反趋势吃不到大牛）
        # - 空头趋势 (ema50 < ema200) → 禁空（反趋势吃不到大熊）
        if direction is not None:
            ema50 = self._ema(closes, period=50)
            ema200 = self._ema(closes, period=200)
            if ema50 and ema200:
                curr_ema50 = ema50[-1]
                curr_ema200 = ema200[-1]
                if curr_ema50 is not None and curr_ema200 is not None:
                    bull = curr_ema50 > curr_ema200
                    bear = curr_ema50 < curr_ema200
                    if direction == "long" and bull:
                        direction = None  # 多头期禁多
                    elif direction == "short" and bear:
                        direction = None  # 空头期禁空

        if direction is None:
            return None

        # ── 止损止盈 ──
        if direction == "long":
            sl_price = lower_band  # 止损在布林带下轨
            tp_price = middle_band  # 止盈在布林带中轨
        else:
            sl_price = upper_band  # 止损在布林带上轨
            tp_price = middle_band  # 止盈在布林带中轨

        # 盈亏比校验
        sl_dist = abs(current_price - sl_price)
        tp_dist = abs(tp_price - current_price)
        if sl_dist <= 0 or tp_dist / sl_dist < 1.0:
            return None  # 盈亏比不足

        confidence = 0.6
        if abs(current_rsi - (rsi_overbought if direction == "short" else rsi_oversold)) > 10:
            confidence += 0.15  # RSI 极端
        if current_rsi > 80 or current_rsi < 20:
            confidence += 0.10  # RSI 极端值

        kline_time = datetime.fromtimestamp(int(last_time) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return Signal(
            strategy="BB_RSI_REVERSION",
            symbol=symbol,
            direction=direction,
            entry_price=round(current_price, 8),
            sl_price=round(sl_price, 8),
            tp_price=round(tp_price, 8),
            leverage=self._get_leverage(symbol),
            size=0.0,
            confidence=round(confidence, 3),
            reason=reason,
            kline_time=kline_time,
        )

    @staticmethod
    def _bollinger_bands(
        closes: List[float], period: int = 20, std_dev: float = 2.0
    ) -> List[tuple]:
        """
        计算布林带

        :param closes: 收盘价列表
        :param period: 中轨周期
        :param std_dev: 标准差倍数
        :return: [(upper, middle, lower), ...] 列表
        """
        if len(closes) < period:
            return []

        bands = []
        for i in range(period - 1, len(closes)):
            window = closes[i - period + 1: i + 1]
            middle = sum(window) / period
            variance = sum((x - middle) ** 2 for x in window) / period
            std = variance ** 0.5
            bands.append((middle + std_dev * std, middle, middle - std_dev * std))

        return bands

    # ---- 辅助方法 ----

    @staticmethod
    def _atr(highs: List[float], lows: List[float], closes: List[float], period: int) -> List[float]:
        """
        计算平均真实波幅（ATR）

        :param highs: 最高价列表
        :param lows: 最低价列表
        :param closes: 收盘价列表
        :param period: ATR 周期
        :return: ATR 值列表（长度 = len(closes) - period）
        """
        if len(closes) < period + 1:
            return []

        # 计算真实波幅序列
        tr_list = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_list.append(tr)

        if len(tr_list) < period:
            return []

        # 第一个 ATR = 前 period 个 TR 的简单平均
        atr = [sum(tr_list[:period]) / period]
        for i in range(period, len(tr_list)):
            atr.append((atr[-1] * (period - 1) + tr_list[i]) / period)

        return atr

    @staticmethod
    def _linear_slope(data: List[float]) -> float:
        """
        计算简单线性回归斜率

        :param data: 数值列表
        :return: 斜率（正=上升，负=下降）
        """
        n = len(data)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(data) / n
        numerator = sum((i - x_mean) * (data[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return 0.0
        return numerator / denominator

    @staticmethod
    def _rsi(closes: List[float], period: int = 14) -> List[float]:
        """
        计算相对强弱指数（RSI）

        :param closes: 收盘价列表
        :param period: RSI 周期
        :return: RSI 值列表（长度 = len(closes) - period）
        """
        if len(closes) < period + 1:
            return []

        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(d, 0) for d in deltas]
        losses = [abs(min(d, 0)) for d in deltas]

        # 初始平均
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        rsi_values = []
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

            if avg_loss == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_values.append(100 - (100 / (1 + rs)))

        return rsi_values

    @staticmethod
    def _ema(data: List[float], period: int) -> List[float]:
        """
        计算指数移动平均线（EMA）

        :param data: 价格列表
        :param period: 周期
        :return: EMA 值列表
        """
        if len(data) < period:
            return []
        k = 2 / (period + 1)
        ema = [sum(data[:period]) / period]
        for price in data[period:]:
            ema.append(price * k + ema[-1] * (1 - k))
        return ema

    def _calc_confidence(
        self,
        direction: str,
        all_above: bool,
        all_below: bool,
        vol_ok: bool,
        avg_vol: float,
        signal_vol: float,
        rsi: Optional[float] = None,
        rsi_overbought: float = 65.0,
        rsi_oversold: float = 35.0,
    ) -> float:
        """
        计算信号置信度 0.0 ~ 1.0
        """
        score = 0.5  # 基础分

        if all_above or all_below:
            score += 0.15  # 趋势确认
        if vol_ok:
            score += 0.15  # 量价配合
            vol_ratio = signal_vol / avg_vol if avg_vol > 0 else 1.0
            if vol_ratio >= 2.0:
                score += 0.10

        # RSI 辅助评分
        if rsi is not None:
            if direction == "long" and rsi_oversold < rsi < 50:
                score += 0.10  # 做多时 RSI 在超卖-中性区间，信号更强
            elif direction == "short" and 50 < rsi < rsi_overbought:
                score += 0.10  # 做空时 RSI 在中性-超买区间，信号更强

        return max(0.0, min(1.0, score))

    def _get_leverage(self, symbol: str) -> int:
        """获取交易对默认杠杆"""
        whitelist = [s.upper() for s in self._config.whitelist_symbols]
        symbol_key = symbol.upper().replace("-USDT", "").replace("USDT", "")
        if symbol_key in [k.upper() for k in whitelist]:
            return self._config.default_leverage_main
        return 3

    def check_all_symbols(
        self,
        positions: List[Dict[str, Any]],
    ) -> List[Signal]:
        """
        检查所有白名单交易对，生成信号列表

        按策略顺序尝试：A (趋势) → B (震荡反转) → C (波动率突破) → D (资金费率)
        任一策略出信号即采用，避免重复信号。

        :param positions: 当前持仓列表（用于判断已有持仓方向）
        :return: 信号列表（可能为空）
        """
        signals = []
        whitelist = self._config.whitelist_symbols

        # 构建已有持仓的 symbol → direction 映射
        pos_map = {p["symbol"]: p["direction"] for p in positions}

        for symbol in whitelist:
            inst_id = symbol if "-" in symbol else f"{symbol[:-4]}-{symbol[-4:]}"
            if "-" not in inst_id:
                inst_id = f"{symbol[:-4]}-{symbol[-4:]}"

            direction = pos_map.get(inst_id) or pos_map.get(symbol)

            # 策略 A（趋势跟踪）
            signal = self.check_ema20_signal(inst_id, direction)
            if signal:
                signals.append(signal)
                continue

            # 策略 B（震荡市反转）
            signal = self.check_bb_rsi_signal(inst_id, direction)
            if signal:
                signals.append(signal)
                continue

            # 策略 C（波动率盘整后突破）
            signal = self.check_volatility_breakout_signal(inst_id, direction)
            if signal:
                signals.append(signal)
                continue

            # 策略 D（资金费率极端反转）
            signal = self.check_funding_rate_signal(inst_id, direction)
            if signal:
                signals.append(signal)

        return signals

    def check_volatility_breakout_signal(
        self,
        symbol: str,
        current_position_direction: Optional[str] = None,
    ) -> Optional[Signal]:
        """
        检查波动率盘整后突破信号（策略 C）

        逻辑：
        1. 计算布林带宽度 (BBW) = (upper - lower) / middle
        2. 当 BBW < squeeze_threshold 时，视为波动率盘整期
        3. 当前收盘价突破 BB 上轨/下轨 → 爆发信号
        4. 量能放大确认（volume_multiplier）
        5. RSI 在中性区（不追超买/超卖）

        :return: Signal 或 None
        """
        if not self._config.strategy_c_enabled:
            return None

        timeframe = self._config.timeframe
        bb_period = self._config.strategy_c_bbw_period
        squeeze_threshold = self._config.strategy_c_bbw_squeeze_threshold
        vol_multi = self._config.strategy_c_volume_multiplier
        rsi_low = self._config.get("strategy_c.rsi_neutral_low", 40)
        rsi_high = self._config.get("strategy_c.rsi_neutral_high", 60)

        candles = self._market.get_candles(symbol, bar=timeframe, limit=bb_period + 5)
        if not candles or len(candles) < bb_period + 2:
            return None

        closes = [float(c[4]) for c in candles]
        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]
        volumes = [float(c[5]) for c in candles]
        last_time = candles[-1][0]

        # 计算布林带
        bb_bands = self._bollinger_bands(closes, period=bb_period, std_dev=2.0)
        if not bb_bands or len(bb_bands) < 2:
            return None

        current_price = closes[-1]
        upper, middle, lower = bb_bands[-1]
        prev_upper, prev_middle, prev_lower = bb_bands[-2]

        # BBW = (upper - lower) / middle
        current_bbw = (upper - lower) / middle if middle > 0 else 1.0
        prev_bbw = (prev_upper - prev_lower) / prev_middle if prev_middle > 0 else 1.0

        # 盘整判定：BBW < squeeze_threshold（最近两根 K 线都低于）
        is_squeeze = current_bbw < squeeze_threshold and prev_bbw < squeeze_threshold
        if not is_squeeze:
            return None

        # 量能验证
        avg_vol = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else volumes[-1]
        vol_ok = volumes[-1] >= avg_vol * vol_multi

        # RSI 检查（在中性区）
        rsi_values = self._rsi(closes, period=14)
        current_rsi = rsi_values[-1] if rsi_values else 50
        rsi_neutral = rsi_low <= current_rsi <= rsi_high

        direction = None
        reason = ""

        if current_position_direction != "long" and current_price > upper and vol_ok and rsi_neutral:
            direction = "long"
            reason = f"波动率盘整后突破上轨 (BBW={current_bbw:.4f} 量能{volumes[-1]/avg_vol:.1f}x RSI={current_rsi:.1f})"
        elif current_position_direction != "short" and current_price < lower and vol_ok and rsi_neutral:
            direction = "short"
            reason = f"波动率盘整后跌破下轨 (BBW={current_bbw:.4f} 量能{volumes[-1]/avg_vol:.1f}x RSI={current_rsi:.1f})"

        if direction is None:
            return None

        # 止损止盈
        atr_values = self._atr(highs, lows, closes, period=14)
        current_atr = atr_values[-1] if atr_values else None
        atr_multiplier = self._config.atr_multiplier
        min_rr = self._config.min_reward_risk_ratio

        if current_atr and current_atr > 0:
            sl_distance = max(current_atr * atr_multiplier, current_price * 0.005)
        else:
            sl_distance = current_price * 0.005

        if direction == "long":
            sl_price = current_price - sl_distance
            tp_price = current_price + sl_distance * min_rr
        else:
            sl_price = current_price + sl_distance
            tp_price = current_price - sl_distance * min_rr

        kline_time = datetime.fromtimestamp(int(last_time) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return Signal(
            strategy="VOLATILITY_BREAKOUT",
            symbol=symbol,
            direction=direction,
            entry_price=round(current_price, 8),
            sl_price=round(sl_price, 8),
            tp_price=round(tp_price, 8),
            leverage=self._get_leverage(symbol),
            size=0.0,
            confidence=0.70,
            reason=reason,
            kline_time=kline_time,
        )

    def check_funding_rate_signal(
        self,
        symbol: str,
        current_position_direction: Optional[str] = None,
    ) -> Optional[Signal]:
        """
        资金费率极端反转信号（策略 D）

        逻辑：
        1. 查询当前 funding rate
        2. 若 |funding| > extreme_threshold 且持续多期
        3. 反向开仓（多付息 → 做空；空付息 → 做多）
        4. RSI 反向确认（多付息时 RSI 应超买；空付息时 RSI 应超卖）

        :return: Signal 或 None
        """
        if not self._config.strategy_d_enabled:
            return None

        threshold = self._config.strategy_d_funding_extreme_threshold

        try:
            # 当前资金费率
            current_funding_resp = self._market.get_funding_rate(symbol)
            if not current_funding_resp:
                return None
            current_funding_rate = float(current_funding_resp[0].get("fundingRate", 0))

            # 历史资金费率（验证持续性）
            history = self._market.get_funding_rate_history(
                symbol, limit=self._config.strategy_d_funding_history_lookback
            )
            if not history or len(history) < 3:
                return None
        except Exception:
            return None

        # 至少一半历史都是同向极值才算"持续"
        same_sign_count = sum(
            1 for h in history
            if (float(h.get("fundingRate", 0)) > 0) == (current_funding_rate > 0)
            and abs(float(h.get("fundingRate", 0))) > threshold * 0.5
        )
        if same_sign_count < len(history) * 0.5:
            return None

        if abs(current_funding_rate) < threshold:
            return None

        # 计算 RSI 反向确认
        timeframe = self._config.timeframe
        candles = self._market.get_candles(symbol, bar=timeframe, limit=30)
        if not candles or len(candles) < 20:
            return None
        closes = [float(c[4]) for c in candles]
        rsi_values = self._rsi(closes, period=14)
        current_rsi = rsi_values[-1] if rsi_values else 50

        direction = None
        reason = ""

        # 资金费率 > 0：多头付息，市场过热 → 做空
        if (
            current_position_direction != "short"
            and current_funding_rate > threshold
            and current_rsi > self._config.get("strategy_d.rsi_overbought", 75)
        ):
            direction = "short"
            reason = f"资金费率过热反转 (funding={current_funding_rate*100:.4f}% RSI={current_rsi:.1f})"

        # 资金费率 < 0：空头付息，市场过冷 → 做多
        elif (
            current_position_direction != "long"
            and current_funding_rate < -threshold
            and current_rsi < self._config.get("strategy_d.rsi_oversold", 25)
        ):
            direction = "long"
            reason = f"资金费率过冷反转 (funding={current_funding_rate*100:.4f}% RSI={current_rsi:.1f})"

        if direction is None:
            return None

        # 止损止盈
        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]
        atr_values = self._atr(highs, lows, closes, period=14)
        current_atr = atr_values[-1] if atr_values else None
        atr_multiplier = self._config.atr_multiplier
        min_rr = self._config.min_reward_risk_ratio
        last_time = candles[-1][0]

        if current_atr and current_atr > 0:
            sl_distance = max(current_atr * atr_multiplier, closes[-1] * 0.005)
        else:
            sl_distance = closes[-1] * 0.005

        current_price = closes[-1]
        if direction == "long":
            sl_price = current_price - sl_distance
            tp_price = current_price + sl_distance * min_rr
        else:
            sl_price = current_price + sl_distance
            tp_price = current_price - sl_distance * min_rr

        kline_time = datetime.fromtimestamp(int(last_time) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return Signal(
            strategy="FUNDING_RATE_REVERSAL",
            symbol=symbol,
            direction=direction,
            entry_price=round(current_price, 8),
            sl_price=round(sl_price, 8),
            tp_price=round(tp_price, 8),
            leverage=self._get_leverage(symbol),
            size=0.0,
            confidence=0.65,
            reason=reason,
            kline_time=kline_time,
        )
