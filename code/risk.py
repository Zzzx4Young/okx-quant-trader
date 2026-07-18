# -*- coding: utf-8 -*-
"""
OKX 交易风控计算器

负责：
- 计算最大可开仓位（基于 2% 本金风险）
- 计算止盈/止损价格
- 校验杠杆倍数（硬上限 10x）
- 盈亏比校验
"""

from typing import Any, Dict, NamedTuple, Optional

from .config import get_config


class RiskResult(NamedTuple):
    """风控计算结果"""
    max_size: float          # 最大可开仓位（张数）
    max_margin: float        # 最大保证金（USDT）
    sl_price: float          # 止损价
    tp_price: float          # 止盈价
    sl_distance: float       # 止损距离（%）
    tp_distance: float       # 止盈距离（%）
    reward_risk_ratio: float # 盈亏比
    leverage_used: int       # 实际使用杠杆
    passed: bool             # 是否通过风控
    reason: str              # 未通过原因（passed=False 时）


class RiskCalculator:
    """风控计算器"""

    # 硬上限杠杆（任何情况下不可突破）
    HARD_LEVERAGE_LIMIT = 10

    def __init__(self, config: Optional[Any] = None):
        self._config = config or get_config()

    def calculate_position_size(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        available_balance: float,
        leverage: Optional[int] = None,
        sl_price: Optional[float] = None,
    ) -> RiskResult:
        """
        计算最大可开仓位及止盈止损

        :param symbol: 交易对，如 'BTCUSDT'
        :param direction: 'long' 或 'short'
        :param entry_price: 参考入场价格
        :param available_balance: 账户可用余额（USDT）
        :param leverage: 指定杠杆（None 则使用默认）
        :param sl_price: 指定止损价（None 则自动计算）
        :return: RiskResult
        """
        # 获取配置参数
        max_loss_pct = self._config.max_loss_percent_per_trade / 100.0
        min_rr = self._config.min_reward_risk_ratio
        sl_buffer = self._config.sl_buffer_percent / 100.0
        hard_limit = self.HARD_LEVERAGE_LIMIT

        # 确定杠杆
        if leverage is None:
            leverage = self._get_default_leverage(symbol)
        leverage = int(leverage)

        # ── 硬性拦截：杠杆超过上限 ──
        if leverage > hard_limit:
            return RiskResult(
                max_size=0.0,
                max_margin=0.0,
                sl_price=0.0,
                tp_price=0.0,
                sl_distance=0.0,
                tp_distance=0.0,
                reward_risk_ratio=0.0,
                leverage_used=leverage,
                passed=False,
                reason=f"杠杆 {leverage}x 超过硬上限 {hard_limit}x，已拦截",
            )

        # ── 计算止损价（支持 ATR 动态止损） ──
        if sl_price is None:
            sl_buffer_pct = sl_buffer  # 固定百分比保底
            if direction == "long":
                sl_price = entry_price * (1 - sl_buffer_pct)
            else:
                sl_price = entry_price * (1 + sl_buffer_pct)

        # ── 计算止损距离 ──
        sl_distance = abs(entry_price - sl_price) / entry_price

        # ── 止损距离下限保底（不低于 0.3%，防止 ATR 极小时止损过窄） ──
        min_sl_distance = 0.003
        if sl_distance < min_sl_distance:
            sl_distance = min_sl_distance
            if direction == "long":
                sl_price = entry_price * (1 - sl_distance)
            else:
                sl_price = entry_price * (1 + sl_distance)

        # ── 校验止损距离不能为 0 ──
        if sl_distance <= 0:
            return RiskResult(
                max_size=0.0,
                max_margin=0.0,
                sl_price=sl_price,
                tp_price=0.0,
                sl_distance=0.0,
                tp_distance=0.0,
                reward_risk_ratio=0.0,
                leverage_used=leverage,
                passed=False,
                reason="止损距离为 0，无法计算仓位",
            )

        # ── 计算交易成本（开仓 + 平仓各一次） ──
        # Taker 手续费率
        fee_rate = self._config.get("risk.taker_fee_rate", 0.00055)
        # 滑点估算（basis points → 比率）
        slippage_bps = self._config.get("risk.slippage_bps", 5)
        slippage_rate = slippage_bps / 10000.0

        # 总交易成本 = (手续费 + 滑点) × 2（一进一出）
        total_cost_rate = (fee_rate + slippage_rate) * 2

        # ── 计算止盈价（净盈亏比 ≥ min_rr） ──
        # 关键：tp_distance 必须提前补偿成本，否则按"名义 RR = min_rr"算出来的 tp
        # 扣费后永远不达标（典型净 RR ≈ 0.76，远小于 1.5）。
        #
        # 推导：
        #   net_rr = (tp - total_cost) / (sl + total_cost) ≥ min_rr
        #   ⇒ tp ≥ min_rr × sl + total_cost × (1 + min_rr)
        #   ⇒ tp_distance ≥ min_rr × sl_distance + total_cost_rate × (1 + min_rr)
        tp_distance = sl_distance * min_rr + total_cost_rate * (1 + min_rr)
        if direction == "long":
            tp_price = entry_price * (1 + tp_distance)
        else:
            tp_price = entry_price * (1 - tp_distance)

        # 净盈亏距离
        net_tp_distance = tp_distance - total_cost_rate
        net_sl_distance = sl_distance + total_cost_rate

        if net_tp_distance <= 0:
            return RiskResult(
                max_size=0.0,
                max_margin=0.0,
                sl_price=round(sl_price, 8),
                tp_price=round(tp_price, 8),
                sl_distance=round(sl_distance, 6),
                tp_distance=round(tp_distance, 6),
                reward_risk_ratio=0.0,
                leverage_used=min(leverage, hard_limit),
                passed=False,
                reason=f"扣除交易成本后净止盈为负（成本 {total_cost_rate*100:.3f}% > 止盈 {tp_distance*100:.3f}%）",
            )

        net_rr = net_tp_distance / net_sl_distance

        # 浮点容差：补偿后的 tp_distance 在数学上使 net_rr == min_rr 恒等，
        # 但浮点运算可能得到 1.4999999999999998。用 EPSILON 避免误判。
        NET_RR_EPSILON = 1e-9
        if net_rr < min_rr - NET_RR_EPSILON:
            return RiskResult(
                max_size=0.0,
                max_margin=0.0,
                sl_price=round(sl_price, 8),
                tp_price=round(tp_price, 8),
                sl_distance=round(sl_distance, 6),
                tp_distance=round(tp_distance, 6),
                reward_risk_ratio=round(net_rr, 2),
                leverage_used=min(leverage, hard_limit),
                passed=False,
                reason=f"净盈亏比 {net_rr:.2f} < {min_rr}（扣费前 {tp_distance/sl_distance:.2f}，成本 {total_cost_rate*100:.3f}%）",
            )

        # ── 计算最大允许亏损金额（账户 2%） ──
        max_loss_amount = available_balance * max_loss_pct

        # ── 计算最大可开仓位 ──
        # 核心公式：单笔最大亏损金额 = 仓位价值 × 止损距离
        #   max_loss_amount = (max_size × entry_price) × sl_distance
        #   → max_size = max_loss_amount / (entry_price × sl_distance)
        #
        # 杠杆只影响保证金需求，不影响仓位大小计算：
        #   margin = 仓位价值 / 杠杆 = (max_size × entry_price) / leverage
        max_size_raw = max_loss_amount / (entry_price * sl_distance)

        # ── 计算所需保证金 ──
        actual_margin = (max_size_raw * entry_price) / leverage

        # ── 保证金不足检查 ──
        if actual_margin > available_balance:
            # 余额不够开满风控允许的仓位，按余额上限缩减
            max_size_raw = (available_balance * leverage) / entry_price
            actual_margin = available_balance

        # ── 最终杠杆校验 ──
        actual_leverage = leverage

        # ── 盈亏比校验（使用净盈亏比 + 浮点容差） ──
        if net_rr < min_rr - NET_RR_EPSILON:
            return RiskResult(
                max_size=round(max_size_raw, 6),
                max_margin=round(actual_margin, 4),
                sl_price=round(sl_price, 8),
                tp_price=round(tp_price, 8),
                sl_distance=round(sl_distance, 6),
                tp_distance=round(tp_distance, 6),
                reward_risk_ratio=round(net_rr, 2),
                leverage_used=min(leverage, hard_limit),
                passed=False,
                reason=f"净盈亏比 {net_rr:.2f} < {min_rr}，不满足最小盈亏比要求",
            )

        return RiskResult(
            max_size=round(max_size_raw, 6),
            max_margin=round(actual_margin, 4),
            sl_price=round(sl_price, 8),
            tp_price=round(tp_price, 8),
            sl_distance=round(sl_distance, 6),
            tp_distance=round(tp_distance, 6),
            reward_risk_ratio=round(net_rr, 2),
            leverage_used=min(leverage, hard_limit),
            passed=True,
            reason="通过风控",
        )

    def calculate_kelly_size(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        current_atr_ratio: float = 1.0,
        current_equity: float = 10000.0,
        leverage: int = 1,
        sl_distance_pct: float = 0.005,
        min_trades_for_kelly: int = 30,
        fractional_kelly: float = 0.25,
        volatility_dampen_threshold: float = 1.5,
        volatility_dampen_factor: float = 0.7,
    ) -> tuple[float, str]:
        """
        计算 Kelly Criterion 动态仓位 size (Constitution §3.2, v1.8.2)。

        经典 Kelly 公式:
            f* = (p × b - q) / b
            其中 p = 胜率, q = 1 - p, b = 平均盈利 / 平均亏损

        Fractional Kelly (默认 1/4): 防过激 — 真实市场不完全满足 Kelly 假设。

        Hard cap: max_loss_percent_per_trade (Constitution §5, v1.8.1 = 1% 本金/笔)。

        关键行为:
            1. Negative Kelly (期望值为负) → 返回 (0.0, reason), 由 caller 拒绝开仓
            2. 数据不足 (avg_loss == 0) → fallback 到 hard cap (保守)
            3. 高波动 (atr_ratio ≥ threshold) → × dampen_factor (缩仓)
            4. Kelly 超出 hard cap → clip 到 hard cap (不破 Constitution §5)

        入参:
            win_rate: 历史胜率 (0.0-1.0)
            avg_win: 平均盈利 (USD, 正数; 0 = 从未盈利样本)
            avg_loss: 平均亏损绝对值 (USD, 正数; 0 = 无亏损历史)
            current_atr_ratio: 当前 ATR / 20-period 中位数 (1.0 = 中位数)
            current_equity: 当前账户净值 (USDT)
            leverage: 杠杆倍数
            sl_distance_pct: SL 距离 (0.005 = 0.5%)

        可选:
            min_trades_for_kelly: 启用 Kelly 需历史 trade 数 (默认 30, 由 caller 检查)
            fractional_kelly: Fractional Kelly 比例 (默认 0.25)
            volatility_dampen_threshold: 高波动阈值 (默认 1.5, atr_ratio 单位)
            volatility_dampen_factor: 高波动下缩仓乘数 (默认 0.7)

        返回:
            (size_usd, reason):
              - size_usd: 建议 margin amount (USD), 已受 hard cap 约束
              - reason: 决策原因 (供 logging/audit, 不超过 ~120 字符)
        """
        # ── 入参校验 ──
        if not (0.0 <= win_rate <= 1.0):
            return 0.0, f"invalid_win_rate_{win_rate:.4f}_not_in_[0,1]"
        if avg_win < 0 or avg_loss < 0:
            return 0.0, "invalid_avg_win_or_loss_negative"
        if current_equity <= 0:
            return 0.0, f"invalid_equity_{current_equity:.2f}_non_positive"
        if leverage < 1:
            return 0.0, f"invalid_leverage_{leverage}_must_be_>=_1"
        if sl_distance_pct <= 0:
            return 0.0, f"invalid_sl_distance_{sl_distance_pct}_non_positive"
        if not (0.0 < fractional_kelly <= 1.0):
            return 0.0, f"invalid_fractional_kelly_{fractional_kelly}_not_in_(0,1]"

        # ── Hard cap (Constitution §5: 1% 本金/笔, v1.8.1) ──
        max_loss_pct = self._config.max_loss_percent_per_trade / 100.0
        hard_cap = current_equity * max_loss_pct

        # ── 数据不足: 无亏损历史 → fallback 到 hard cap (保守) ──
        # 解释: Kelly b = avg_win / avg_loss, avg_loss = 0 数学上爆掉。
        #       全胜样本 (avg_loss = 0) 不能用 Kelly, 一律走 1% 本金硬上限。
        if avg_loss <= 0:
            return hard_cap, "no_loss_history_fallback_to_hard_cap_1pct"

        # ── 经典 Kelly 公式 ──
        b = avg_win / avg_loss
        p = win_rate
        q = 1.0 - p
        f_full = (p * b - q) / b

        # ── Negative Kelly: 期望值为负, 拒绝开仓 (Kelly 的精髓是"不赌坏赌局") ──
        if f_full <= 0:
            return 0.0, (
                f"negative_EV_kelly={f_full:.4f}_WR={win_rate:.2%}_b={b:.2f}"
            )

        # ── Fractional Kelly ──
        f_fractional = fractional_kelly * f_full

        # ── 波动率调整 ──
        vol_note = ""
        if current_atr_ratio >= volatility_dampen_threshold:
            f_fractional *= volatility_dampen_factor
            vol_note = f"high_vol_{current_atr_ratio:.2f}x_dampen_{volatility_dampen_factor:.2f}"

        # ── 应用到 equity ──
        size_usd = f_fractional * current_equity

        # ── Hard cap (Constitution §5 不破) ──
        capped = False
        if size_usd > hard_cap:
            size_usd = hard_cap
            capped = True

        # ── Reason 字符串 (供 logging) ──
        reason_parts = []
        if capped:
            reason_parts.append(
                f"capped_at_max_loss_{self._config.max_loss_percent_per_trade:.1f}pct_"
                f"(Kelly_wants_{f_fractional*100:.2f}pct_×_equity)"
            )
        else:
            reason_parts.append(
                f"kelly_{fractional_kelly:.2f}_of_{f_full*100:.2f}pct_full"
            )
        if vol_note:
            reason_parts.append(vol_note)

        return size_usd, " | ".join(reason_parts)

    def validate_leverage(self, leverage: int, symbol: str) -> tuple[bool, str]:
        """
        校验杠杆是否合法

        :param leverage: 请求的杠杆倍数
        :param symbol: 交易对
        :return: (是否合法, 原因)
        """
        hard_limit = self.HARD_LEVERAGE_LIMIT
        default_leverage = self._get_default_leverage(symbol)

        if leverage > hard_limit:
            return False, f"杠杆 {leverage}x 超过硬上限 {hard_limit}x，已拦截"
        if leverage < 1:
            return False, f"杠杆必须 ≥ 1x，当前为 {leverage}x"
        if leverage > default_leverage * 2:
            return False, f"杠杆 {leverage}x 超过默认杠杆 {default_leverage}x 的 2 倍，请确认"
        return True, "合法"

    def calculate_breakeven_price(self, entry_price: float, direction: str, fee: float = 0.0) -> float:
        """
        计算盈亏平衡价格（含手续费）

        :param entry_price: 开仓均价
        :param direction: 'long' 或 'short'
        :param fee: 预估手续费
        :return: 盈亏平衡价格
        """
        if direction == "long":
            return entry_price * (1 + fee)
        else:
            return entry_price * (1 - fee)

    def calculate_pnl(
        self,
        direction: str,
        entry_price: float,
        exit_price: float,
        size: float,
        ct_val: float = 1.0,
    ) -> tuple[float, float]:
        """
        计算盈亏

        :param direction: 'long' 或 'short'
        :param entry_price: 开仓均价
        :param exit_price: 平仓价格
        :param size: 合约张数（如 0.55 张）
        :param ct_val: 每张合约对应的标的资产数量（OKX 字段 ctVal，
                       如 ETH-USDT-SWAP=0.1 → 每张合约 0.1 ETH）。
                       默认为 1.0（为向后兼容）；实盘应从 instrument 信息传入。
        :return: (盈亏金额 USDT, ROE %)
        """
        if direction == "long":
            pnl = (exit_price - entry_price) * size * ct_val
        else:
            pnl = (entry_price - exit_price) * size * ct_val

        margin = entry_price * size * ct_val  # 名义价值 / leverage 为保证金近似
        roe = (pnl / margin * 100) if margin > 0 else 0.0
        return round(pnl, 4), round(roe, 4)

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """归一化交易对名：提取基础币+报价币（忽略大小写、分隔符、后缀）

        支持以下格式 → 统一为 "BASEUSDT"：
        - BTCUSDT
        - BTC-USDT
        - BTC/USDT
        - BTC_USDT
        - BTC-USDT-SWAP / BTC-USDT-PERP / BTC-USDT-FUTURES
        """
        s = symbol.upper().replace("-", "").replace("/", "").replace("_", "").replace(" ", "")
        # 去掉常见永续/合约后缀
        for suffix in ("SWAP", "PERPETUAL", "PERP", "FUTURES", "FUTURE"):
            if s.endswith(suffix):
                s = s[: -len(suffix)]
                break
        return s

    def _get_default_leverage(self, symbol: str) -> int:
        """获取交易对的默认杠杆

        Constitution §2 动态杠杆矩阵：
        - BTC/ETH: 5-10x (主流币)
        - 山寨币 TOP50: 3-5x
        - 高波动: 0x (禁止)

        同时根据 ATR 动态调整：ATR 越大、杠杆越低。
        """
        matrix = self._config.get_leverage_matrix_for_symbol(symbol)
        min_lev = matrix.get("min_leverage", 5)
        max_lev = matrix.get("max_leverage", 10)

        # 高波动资产: 禁止使用杠杆
        if max_lev == 0:
            return 1  # 返回 1x，但 risk 会被下面的 audit 逻辑拦截

        # 根据 ATR 动态调整（如果传入了 ATR）
        atr = getattr(self, "_current_atr", None)
        atr_low = matrix.get("atr_low")
        atr_high = matrix.get("atr_high")
        if atr and atr_low and atr_high:
            if atr >= atr_high:
                # 高波动：使用 min_leverage
                return min_lev
            elif atr <= atr_low:
                # 低波动：可以使用 max_leverage
                return max_lev
            else:
                # 中间范围：线性插值
                ratio = (atr - atr_low) / (atr_high - atr_low)
                return int(round(max_lev - (max_lev - min_lev) * ratio))

        # 默认返回 min_leverage（更保守）
        return min_lev

    def calculate_dynamic_leverage(
        self, symbol: str, current_atr: float, is_main_event: bool = False
    ) -> int:
        """计算动态杠杆（公开接口，调用方可以传入实时 ATR）

        :param symbol: 交易对
        :param current_atr: 当前 ATR14
        :param is_main_event: 是否面临重大事件（如美联储决议）
        :return: 推荐杠杆倍数
        """
        self._current_atr = current_atr
        matrix = self._config.get_leverage_matrix_for_symbol(symbol)
        min_lev = matrix.get("min_leverage", 5)
        max_lev = matrix.get("max_leverage", 10)

        # 高波动资产: 禁止使用杠杆
        if max_lev == 0:
            return 0

        # 重大事件：硬性熔断，降至 hard_ceiling
        if is_main_event:
            return matrix.get("hard_ceiling", 3)

        lev = self._get_default_leverage(symbol)
        # 锁定在矩阵范围内
        return max(min_lev, min(max_lev, lev))

    # ─────────────────────────────────────────────────────────────
    # Constitution §3：跨策略冲突过滤 (A↔B 趋势 vs 反转)
    # ─────────────────────────────────────────────────────────────
    #
    # 路线图阶段 3.1（okx/docs/agent-context/okx量化合约交易指南.md）：
    # - 趋势策略 A 发出做多，震荡策略 B 同时发出做空 → 强制过滤
    # - 强趋势 (ATR/median 高) 时屏蔽 B（趋势里 B 反转会被甩）
    # - 极窄震荡 (ATR/median 低) 时屏蔽 A（震荡里 A 假突破多）
    #
    # 设计：pure function。所有依赖（recent_signals / atr_ratio）从外部注入，
    # 方便单测 + 不污染 risk 内部状态。调用方（runner）维护最近 N 分钟信号窗口。

    # 策略的市场制度分类（用于规则 2/3）
    STRATEGY_REGIME = {
        "EMA20_BREAKOUT": "trend_follow",       # A：右侧趋势
        "BB_RSI_REVERSION": "mean_reversion",   # B：左侧反转
        "VOLATILITY_BREAKOUT": "volatility",    # C：波动率爆发（独立）
        "FUNDING_RATE_REVERSAL": "funding",     # D：资金费率（独立）
    }

    # 默认阈值（可被 Config 覆盖）
    DEFAULT_TREND_HIGH_RATIO = 1.5    # ATR/median ≥ 1.5 视为强趋势
    DEFAULT_TREND_LOW_RATIO = 0.7     # ATR/median ≤ 0.7 视为窄幅震荡
    DEFAULT_CONFLICT_WINDOW_MIN = 60  # 同 symbol 反向信号冲突时间窗口（分钟）

    def check_strategy_conflict(
        self,
        new_signal: Any,                     # Signal 对象（避免循环 import）
        recent_signals: list,                # 同 symbol 最近 N 分钟信号列表（不含 new_signal）
        atr_ratio: Optional[float] = None,   # 当前 ATR / 20-period ATR 中位数；None = 未知
        trend_high_ratio: Optional[float] = None,
        trend_low_ratio: Optional[float] = None,
        conflict_window_min: Optional[int] = None,
    ) -> Optional[str]:
        """Constitution §3 跨策略冲突过滤

        检查 new_signal 是否应该被 Constitution 过滤。三条规则：

        规则 1：方向冲突 — 同 symbol 在 conflict_window_min 内有反向策略信号
                → 保留 confidence 高的；相等时 trend_follow (A) 优先于 mean_reversion (B)

        规则 2：趋势动能过强 — atr_ratio ≥ trend_high_ratio
                → 屏蔽 mean_reversion 策略（B 在强趋势里反转会被甩）

        规则 3：窄幅震荡 — atr_ratio ≤ trend_low_ratio
                → 屏蔽 trend_follow 策略（A 在震荡里假突破多）

        策略 C / D 不受规则 2/3 影响（volatility / funding 各自独立判定）。

        :param new_signal: 待检查的 Signal 对象
        :param recent_signals: 同一 symbol 的最近 N 分钟历史信号列表
        :param atr_ratio: 当前 ATR / 20-period ATR 中位数；None 时规则 2/3 不触发
        :param trend_high_ratio: 强趋势阈值（默认 1.5）
        :param trend_low_ratio: 窄幅阈值（默认 0.7）
        :param conflict_window_min: 冲突时间窗口（默认 60 分钟）
        :return: None = 通过；str = 拒绝原因
        """
        if new_signal is None:
            return None

        high_th = trend_high_ratio if trend_high_ratio is not None else self.DEFAULT_TREND_HIGH_RATIO
        low_th = trend_low_ratio if trend_low_ratio is not None else self.DEFAULT_TREND_LOW_RATIO
        window_min = conflict_window_min if conflict_window_min is not None else self.DEFAULT_CONFLICT_WINDOW_MIN

        new_strategy = getattr(new_signal, "strategy", None)
        new_regime = self.STRATEGY_REGIME.get(new_strategy)

        # ── 规则 2：强趋势 → 屏蔽 B (mean_reversion) ──
        if atr_ratio is not None and atr_ratio >= high_th and new_regime == "mean_reversion":
            return (
                f"Constitution §3 规则 2：强趋势 (ATR/median={atr_ratio:.2f} ≥ {high_th}) "
                f"屏蔽 {new_strategy} 反转信号 — 趋势里反转易被甩"
            )

        # ── 规则 3：窄幅震荡 → 屏蔽 A (trend_follow) ──
        if atr_ratio is not None and atr_ratio <= low_th and new_regime == "trend_follow":
            return (
                f"Constitution §3 规则 3：窄幅震荡 (ATR/median={atr_ratio:.2f} ≤ {low_th}) "
                f"屏蔽 {new_strategy} 突破信号 — 震荡里假突破多"
            )

        # ── 规则 1：同 symbol 反向策略冲突 ──
        # C / D 不参与冲突比较（独立判定，不互斥）
        if new_regime not in ("trend_follow", "mean_reversion"):
            return None

        # 按 kline_time 过滤窗口
        try:
            new_ts = self._parse_kline_time(getattr(new_signal, "kline_time", None))
        except Exception:
            new_ts = None

        for prev in recent_signals:
            if prev is None:
                continue
            prev_strategy = getattr(prev, "strategy", None)
            prev_regime = self.STRATEGY_REGIME.get(prev_strategy)
            # 只比较 A↔B (trend_follow ↔ mean_reversion)
            if prev_regime not in ("trend_follow", "mean_reversion"):
                continue
            # 必须 regime 互补（趋势 vs 反转）+ 方向相反
            if prev_regime == new_regime:
                continue
            if getattr(prev, "direction", None) == getattr(new_signal, "direction", None):
                continue
            # 时间窗口检查
            if new_ts is not None:
                try:
                    prev_ts = self._parse_kline_time(getattr(prev, "kline_time", None))
                except Exception:
                    prev_ts = None
                if prev_ts is not None and abs((new_ts - prev_ts).total_seconds()) > window_min * 60:
                    continue
            # 进入冲突：旧信号已下单，新信号被拒绝（避免多空互殴）
            new_conf = getattr(new_signal, "confidence", 0.0)
            prev_conf = getattr(prev, "confidence", 0.0)
            if new_conf > prev_conf:
                verdict = "新信号 conf 更高"
            else:
                verdict = "新信号 conf 不占优"
            return (
                f"Constitution §3 规则 1：同 symbol 反向冲突 — "
                f"拒绝新信号 {new_strategy} {new_signal.direction} (conf={new_conf:.2f})，"
                f"保留旧信号 {prev_strategy} {prev.direction} (conf={prev_conf:.2f}) "
                f"[{verdict}，避免多空互弒]"
            )

        return None

    @staticmethod
    def _parse_kline_time(ts_str):
        """解析 kline_time 字符串为 timezone-aware datetime。失败返回 None。

        支持 ISO 8601 with 'Z' suffix 或 timezone offset。
        """
        if not ts_str:
            return None
        from datetime import datetime, timezone
        s = str(ts_str).strip()
        # 替换 Z 为 +00:00
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def estimate_fee(self, price: float, size: float, ct_val: float = 1.0, taker: bool = True) -> float:
        """
        估算手续费

        :param price: 价格
        :param size: 合约张数
        :param ct_val: 每张合约对应的标的资产数量（OKX ctVal 字段）
        :param taker: 是否为 Taker（市价单为 Taker）
        :return: 预估手续费（USDT）
        """
        fee_rate = 0.00055 if taker else 0.00030  # OKX Taker 0.055% / Maker 0.030%
        return round(price * size * ct_val * fee_rate, 4)
