# -*- coding: utf-8 -*-
"""
OKX 仓位风险监控阈值 + 数据结构

设计原则：
  - 纯数据/常量层，零外部依赖 → 单测友好
  - direction="high" 触发条件：value >= threshold
  - direction="low"  触发条件：value <= threshold
  - 数值默认按 demo 账户规模（$50k-$100k USD）调校
    真实 LIVE 上线前需根据账户规模重评（v1.7 fragility 文档建议）

使用：
    from okx.scripts.risk_thresholds import RISK_THRESHOLDS, PositionRisk, RiskMetrics
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ──────────── 阈值定义 ────────────


@dataclass(frozen=True)
class RiskThreshold:
    """单一风险指标的阈值定义"""

    warn: float
    crit: float
    direction: str  # "high"=超过触发；"low"=低于触发
    description: str = ""
    # ──── structural 标记 ────
    # True 表示该指标属于"结构性失衡"（如集中度），不是当下爆仓风险。
    # watchdog 会把 structural issue 走"只写日志不发 Telegram"路径，
    # 避免反复报同一类非即时风险。默认 False（保留即时告警语义）。
    structural: bool = False


# 阈值常量（按 demo 账户调校，单一值起步，跑 1 周根据数据再调）
RISK_THRESHOLDS: Dict[str, RiskThreshold] = {
    # 毛杠杆倍数：总名义 / 账户净值
    "gross_leverage": RiskThreshold(
        warn=3.0, crit=5.0, direction="high",
        description="毛杠杆倍数（总名义敞口 / 账户净值）",
    ),
    # 净敞口倍数：净名义 / 账户净值（绝对值）
    "net_leverage": RiskThreshold(
        warn=2.0, crit=4.0, direction="high",
        description="净敞口倍数",
    ),
    # 总 uPnL 占净值比例（负数 = 浮亏）
    "upl_pct": RiskThreshold(
        warn=-0.05, crit=-0.10, direction="low",
        description="总未实现盈亏占净值比例",
    ),
    # 单标的敞口占比（结构性失衡，非即时爆仓风险）
    "inst_concentration": RiskThreshold(
        warn=0.50, crit=0.70, direction="high",
        description="单标的（BTC/ETH等）敞口占总名义比例",
        structural=True,
    ),
    # 单策略敞口占比（结构性失衡）
    "strategy_concentration": RiskThreshold(
        warn=0.60, crit=0.80, direction="high",
        description="单策略（A/B/C/D）敞口占总名义比例",
        structural=True,
    ),
    # 最小强平距离（占 markPx 比例）
    "liq_proximity_pct": RiskThreshold(
        warn=0.10, crit=0.05, direction="low",
        description="最小强平距离（占当前价比例，越小越危险）",
    ),
    # SL 已走比例（接近止损）
    "sl_consumed_pct": RiskThreshold(
        warn=0.70, crit=0.90, direction="high",
        description="止损已走比例（|markPx - avgPx| / |slPx - avgPx|）",
    ),
    # 净值缓冲比例（可用保证金 / 净值）
    "min_equity_buffer": RiskThreshold(
        warn=0.30, crit=0.15, direction="low",
        description="净值缓冲比例（可用保证金 / 账户净值）",
    ),
}


def get_threshold(name: str) -> RiskThreshold:
    """按名取阈值，找不到抛 KeyError（fail loud，避免静默漏检）"""
    if name not in RISK_THRESHOLDS:
        raise KeyError(f"未知风险指标: {name}（已知: {list(RISK_THRESHOLDS.keys())}）")
    return RISK_THRESHOLDS[name]


# ──────────── 数据结构 ────────────


@dataclass
class PositionRisk:
    """单仓位风险快照（从 OKX position API 转换）"""

    inst_id: str                          # e.g. BTC-USDT-SWAP
    pos_side: str                         # long / short / net
    size: float                           # 持仓张数（带正负号：正=多，负=空）
    ct_val: float                         # 合约面值（每张多少标的）
    avg_px: float                         # 开仓均价
    mark_px: float                        # 当前标记价
    upl: float                            # 未实现盈亏（API 直接返回，USDT）
    margin: float                         # 占用保证金（USDT）
    liq_px: Optional[float]               # 强平价（API 返回，None 表示无法计算）
    leverage: float                       # 实际杠杆
    strategy: str                         # 策略名（从本地 portfolio 匹配）
    sl_px: Optional[float] = None         # 止损价（OKX attachAlgoOrds）
    tp_px: Optional[float] = None         # 止盈价
    notional_usd: float = 0.0             # 名义价值 = |size| * ct_val * mark_px
    upl_pct_of_margin: float = 0.0        # uPnL / margin（仓位级）

    def __post_init__(self) -> None:
        # notional = |size| * ctVal * markPx
        self.notional_usd = abs(self.size) * self.ct_val * self.mark_px
        if self.margin > 0:
            self.upl_pct_of_margin = self.upl / self.margin

    @property
    def is_long(self) -> bool:
        return self.pos_side == "long" or (self.pos_side == "net" and self.size > 0)

    @property
    def liq_distance_pct(self) -> Optional[float]:
        """到强平价的距离占 markPx 比例（None 表示无法计算）"""
        if self.liq_px is None or self.liq_px <= 0 or self.mark_px <= 0:
            return None
        return abs(self.mark_px - self.liq_px) / self.mark_px

    @property
    def sl_consumed_pct(self) -> Optional[float]:
        """SL 已走比例：|markPx - avgPx| / |slPx - avgPx|（None=无 SL）"""
        if self.sl_px is None or self.sl_px <= 0 or self.avg_px <= 0:
            return None
        total_dist = abs(self.sl_px - self.avg_px)
        if total_dist <= 0:
            return None
        moved_dist = abs(self.mark_px - self.avg_px)
        return min(moved_dist / total_dist, 1.0)


@dataclass
class RiskMetrics:
    """聚合风险指标（一次评估的全账户视图）"""

    equity_usd: float = 0.0               # 账户总净值（USD）
    used_margin_usd: float = 0.0          # 已用保证金

    # ── 杠杆与敞口 ──
    total_notional_usd: float = 0.0       # 总名义价值
    net_notional_usd: float = 0.0         # 净名义（有方向）
    gross_leverage: float = 0.0           # 毛杠杆 = total_notional / equity
    net_leverage: float = 0.0             # 净杠杆 = |net_notional| / equity

    # ── uPnL ──
    total_upl_usd: float = 0.0            # 总 uPnL（USDT）
    upl_pct: float = 0.0                  # 总 uPnL / equity

    # ── 集中度 ──
    inst_concentration: float = 0.0       # 最大单标的占比
    inst_concentration_target: str = ""   # 哪个标的（e.g. BTC-USDT-SWAP）
    strategy_concentration: float = 0.0   # 最大单策略占比
    strategy_concentration_target: str = ""

    # ── 强平 ──
    min_liq_distance_pct: float = 1.0     # 最小强平距离（占 markPx），1.0 = 无持仓
    min_liq_target: str = ""              # 哪个仓位

    # ── SL ──
    max_sl_consumed_pct: float = 0.0      # SL 走得最远的仓位
    max_sl_target: str = ""

    # ── 缓冲 ──
    equity_buffer_pct: float = 1.0        # (equity - used_margin) / equity，1.0 = 无持仓

    # ── 持仓状态 ──
    position_count: int = 0
    position_breakdown: Dict[str, float] = field(default_factory=dict)  # inst_id -> notional
    strategy_breakdown: Dict[str, float] = field(default_factory=dict)  # strategy -> notional

    # ── API 状态 ──
    api_status: str = "ok"                # ok / degraded / failed
    api_error: str = ""                   # API 失败原因


@dataclass
class RiskIssue:
    """单个风险告警（一条检查的输出）"""

    check: str           # 检查项名（RISK_THRESHOLDS 的 key 或 Layer 1 检查名）
    level: str           # "warning" / "critical"
    message: str         # 用户可见描述
    metric_value: float = 0.0   # 当前指标值
    threshold: float = 0.0      # 触发的阈值
    direction: str = ""         # "high" / "low"


@dataclass
class WatchdogReport:
    """一次 watchdog 执行的总输出"""

    timestamp_utc: str
    mode: str                       # "live" / "demo"
    metrics: RiskMetrics
    issues: List[RiskIssue]         # 所有 Layer 1+2 触发的问题
    api_status: str                 # ok / degraded / failed

    @property
    def has_critical(self) -> bool:
        return any(i.level == "critical" for i in self.issues)

    @property
    def has_warning(self) -> bool:
        return any(i.level == "warning" for i in self.issues)

    @property
    def is_healthy(self) -> bool:
        """健康 = 无任何 issue 且 API 状态 ok"""
        return not self.issues and self.api_status == "ok"
