# -*- coding: utf-8 -*-
"""
OKX 交易配置加载器
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


class Config:
    """交易配置管理器（线程安全单例）"""

    _instance: Optional["Config"] = None
    _lock = threading.Lock()

    def __new__(cls, config_path: Optional[str] = None) -> "Config":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        if self._initialized:
            return
        self._initialized = True

        if config_path is None:
            base = Path(__file__).parent.parent
            config_path = base / "state" / "config.json"

        self._path = Path(config_path)
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """从文件加载配置"""
        if not self._path.exists():
            raise FileNotFoundError(f"Config file not found: {self._path}")
        with open(self._path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def reload(self) -> None:
        """重新从磁盘加载配置"""
        self._load()

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值，支持点号路径，如 'trading.timeframe'

        :param key: 配置路径
        :param default: 默认值
        :return: 配置值
        """
        keys = key.split(".")
        val = self._data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
            if val is None:
                return default
        return val

    # ---- Trading ----

    @property
    def timeframe(self) -> str:
        return self.get("trading.timeframe", "15m")

    @property
    def whitelist_symbols(self) -> List[str]:
        return self.get("trading.whitelist_symbols", ["BTCUSDT", "ETHUSDT"])

    @property
    def margin_mode(self) -> str:
        return self.get("trading.margin_mode", "isolated")

    @property
    def default_leverage_main(self) -> int:
        return self.get("trading.default_leverage_main", 5)

    @property
    def max_leverage_limit(self) -> int:
        return self.get("trading.max_leverage_limit", 10)

    @property
    def max_concurrent_positions(self) -> int:
        return self.get("trading.max_concurrent_positions", 3)

    @property
    def emergency_stop(self) -> bool:
        return self.get("trading.emergency_stop", False)

    @emergency_stop.setter
    def emergency_stop(self, value: bool) -> None:
        """设置紧急熔断开关，并持久化到文件"""
        self._data.setdefault("trading", {})["emergency_stop"] = value
        self._save()

    @property
    def demo_mode(self) -> bool:
        return self.get("trading.demo_mode", True)

    # ---- Risk ----

    @property
    def max_loss_percent_per_trade(self) -> float:
        return self.get("risk.max_loss_percent_per_trade", 2.0)

    @property
    def min_reward_risk_ratio(self) -> float:
        return self.get("risk.min_reward_risk_ratio", 1.5)

    @property
    def daily_max_loss_trades(self) -> int:
        return self.get("risk.daily_max_loss_trades", 3)

    @property
    def sl_buffer_percent(self) -> float:
        return self.get("risk.sl_buffer_percent", 0.5)

    @property
    def time_stop_hours(self) -> int:
        return self.get("risk.time_stop_hours", 2)

    # ---- Strategy A ----

    @property
    def strategy_a_enabled(self) -> bool:
        return self.get("strategy_a.enabled", True)

    @property
    def strategy_a_ema_period(self) -> int:
        return self.get("strategy_a.ema_period", 20)

    @property
    def strategy_a_kline_count(self) -> int:
        return self.get("strategy_a.kline_count_for_confirmation", 2)

    @property
    def strategy_a_volume_ratio(self) -> float:
        return self.get("strategy_a.volume_ratio_threshold", 1.2)

    @property
    def strategy_a_atr_period(self) -> int:
        return self.get("strategy_a.atr_period", 14)

    @property
    def atr_multiplier(self) -> float:
        return self.get("risk.atr_multiplier", 2.0)

    @property
    def strategy_a_rsi_period(self) -> int:
        return self.get("strategy_a.rsi_period", 14)

    @property
    def strategy_a_rsi_overbought(self) -> float:
        return self.get("strategy_a.rsi_overbought", 65.0)

    @property
    def strategy_a_rsi_oversold(self) -> float:
        return self.get("strategy_a.rsi_oversold", 35.0)

    # ---- Strategy B ----

    @property
    def strategy_b_enabled(self) -> bool:
        return self.get("strategy_b.enabled", False)

    @property
    def strategy_b_bb_period(self) -> int:
        return self.get("strategy_b.bb_period", 20)

    @property
    def strategy_b_bb_std(self) -> int:
        return self.get("strategy_b.bb_std", 2)

    @property
    def strategy_b_rsi_period(self) -> int:
        return self.get("strategy_b.rsi_period", 14)

    @property
    def strategy_b_rsi_overbought(self) -> float:
        return self.get("strategy_b.rsi_overbought", 70.0)

    @property
    def strategy_b_rsi_oversold(self) -> float:
        return self.get("strategy_b.rsi_oversold", 30.0)

    # ---- OpenClaw ----

    @property
    def heartbeat_interval_minutes(self) -> int:
        return self.get("openclaw.heartbeat_interval_minutes", 30)

    @property
    def trade_on_quarter(self) -> bool:
        return self.get("openclaw.trade_on_quarter", True)

    @property
    def quarterly_minutes(self) -> List[int]:
        return self.get("openclaw.quarterly_minutes", [0, 15, 30, 45])

    # ---- Notifier ----

    @property
    def notifier_enabled(self) -> bool:
        """通知层总开关（被环境变量 OKX_NOTIFIER_ENABLED=false 覆盖）"""
        env_override = os.getenv("OKX_NOTIFIER_ENABLED", "").lower()
        if env_override in ("0", "false", "no", "off"):
            return False
        return self.get("notifier.enabled", True)

    @property
    def notifier_min_interval_sec(self) -> int:
        """同类型消息发送间隔下限（防止限频）"""
        return int(self.get("notifier.min_interval_sec", 1))

    @property
    def notifier_daily_summary_hour(self) -> int:
        """每日报告发送小时（UTC）"""
        return int(self.get("notifier.daily_summary_hour_utc", 15))  # 北京 23:00

    # ---- Strategy C / D (新增 2026-07-11) ----

    @property
    def strategy_c_enabled(self) -> bool:
        return self.get("strategy_c.enabled", True)

    @property
    def strategy_c_bbw_period(self) -> int:
        return int(self.get("strategy_c.bbw_period", 20))

    @property
    def strategy_c_bbw_squeeze_threshold(self) -> float:
        """BBW 收缩阈值：低于此视为盘整"""
        return float(self.get("strategy_c.bbw_squeeze_threshold", 0.025))

    @property
    def strategy_c_breakout_buffer(self) -> float:
        return float(self.get("strategy_c.breakout_buffer", 0.005))

    @property
    def strategy_c_volume_multiplier(self) -> float:
        return float(self.get("strategy_c.volume_multiplier", 1.5))

    @property
    def strategy_d_enabled(self) -> bool:
        return self.get("strategy_d.enabled", True)

    @property
    def strategy_d_funding_extreme_threshold(self) -> float:
        """资金费率极值阈值（绝对值），例如 0.0005 = 0.05%"""
        return float(self.get("strategy_d.funding_extreme_threshold", 0.0005))

    @property
    def strategy_d_funding_history_lookback(self) -> int:
        return int(self.get("strategy_d.funding_history_lookback", 8))

    # ---- 杠杆矩阵 (Constitution §2) ----

    @property
    def leverage_matrix_btc(self) -> Dict[str, Any]:
        return self.get("leverage_matrix.BTC", {"min_leverage": 5, "max_leverage": 10, "hard_ceiling": 3, "atr_low": 80, "atr_high": 250})

    @property
    def leverage_matrix_eth(self) -> Dict[str, Any]:
        return self.get("leverage_matrix.ETH", {"min_leverage": 5, "max_leverage": 10, "hard_ceiling": 3, "atr_low": 5, "atr_high": 15})

    @property
    def leverage_matrix_altcoin(self) -> Dict[str, Any]:
        return self.get("leverage_matrix.altcoin_top50", {"min_leverage": 3, "max_leverage": 5, "hard_ceiling": 1})

    def get_leverage_matrix_for_symbol(self, symbol: str) -> Dict[str, Any]:
        """根据 symbol 获取适用的杠杆矩阵规则

        BTC/ETH 用主流币规则，其他币种默认 altcoin。
        """
        sym_upper = symbol.upper().replace("-", "").replace("/", "").replace("_", "")
        if "BTC" in sym_upper:
            return self.leverage_matrix_btc
        if "ETH" in sym_upper:
            return self.leverage_matrix_eth
        return self.leverage_matrix_altcoin

    # ---- 黑名单 / 流动性过滤 (Constitution §4) ----

    @property
    def blacklist_min_24h_volume_usdt(self) -> float:
        return float(self.get("blacklist.min_24h_volume_usdt", 50_000_000))

    @property
    def blacklist_max_funding_rate_abs(self) -> float:
        return float(self.get("blacklist.max_funding_rate_abs", 0.001))

    # ---- 审计规则 (Constitution §5) ----

    @property
    def audit_max_consecutive_losses(self) -> int:
        return int(self.get("audit.max_consecutive_losses", 3))

    @property
    def audit_lockout_duration_minutes(self) -> int:
        return int(self.get("audit.lockout_duration_minutes", 30))

    @property
    def audit_fee_to_profit_ratio_threshold(self) -> float:
        return float(self.get("audit.fee_to_profit_ratio_threshold", 0.30))

    @property
    def audit_enable_meltdown_lock(self) -> bool:
        return bool(self.get("audit.enable_meltdown_lock", True))

    # ---- Internal ----

    def _save(self) -> None:
        """保存配置到磁盘"""
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def __repr__(self) -> str:
        return f"<Config: {self._path}>"


# 全局单例访问函数
_config: Optional[Config] = None


def load_config(config_path: Optional[str] = None) -> Config:
    """加载配置"""
    global _config
    _config = Config(config_path)
    return _config


def get_config() -> Config:
    """获取已加载的配置（必须先调用 load_config）"""
    global _config
    if _config is None:
        base = Path(__file__).parent.parent
        _config = Config(base / "state" / "config.json")
    return _config
