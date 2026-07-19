# -*- coding: utf-8 -*-
"""
Market Constitution 增强功能测试

覆盖：
- 策略 B 启用
- 策略 C / D 配置
- 杠杆矩阵
- 黑名单 / 流动性配置
- 审计规则
"""

import json
from pathlib import Path

import pytest

from okx.code.config import Config, get_config

# cfg fixture 由 conftest.py 提供（共享）


class TestConstitutionConfig:
    """Constitution 配置项可正确加载"""

    def test_strategy_b_enabled(self, cfg):
        assert cfg.strategy_b_enabled is True

    def test_strategy_c_enabled(self, cfg):
        assert cfg.strategy_c_enabled is True
        assert cfg.strategy_c_bbw_period == 20
        # 2026-07-12 调整：从 0.025 改为 0.04（容易在震荡市触发）
        assert cfg.strategy_c_bbw_squeeze_threshold == 0.04
        assert cfg.strategy_c_volume_multiplier == 0.5

    def test_strategy_d_enabled(self, cfg):
        # v1.8.3+ (2026-07-19): D 策略永久禁用 (fragility_scan 全 timeframe 0 viable)
        assert cfg.strategy_d_enabled is False
        # threshold 仍保留 (配置块不删), 防 signal.py:746 AttributeError
        assert cfg.strategy_d_funding_extreme_threshold == 0.0001

    def test_leverage_matrix_btc(self, cfg):
        """v1.8.1 阶段 5.2: 锁杠杆 3x (路线图 micro-live 要求)"""
        btc = cfg.leverage_matrix_btc
        assert btc["min_leverage"] == 3
        assert btc["max_leverage"] == 3
        assert btc["hard_ceiling"] == 3
        assert btc["category"] == "mainstream"

    def test_leverage_matrix_eth(self, cfg):
        """v1.8.1 阶段 5.2: 锁杠杆 3x (路线图 micro-live 要求)"""
        eth = cfg.leverage_matrix_eth
        assert eth["min_leverage"] == 3
        assert eth["max_leverage"] == 3
        assert eth["hard_ceiling"] == 3

    def test_leverage_matrix_altcoin(self, cfg):
        alt = cfg.leverage_matrix_altcoin
        assert alt["min_leverage"] == 3
        assert alt["max_leverage"] == 5

    def test_get_leverage_matrix_for_symbol(self, cfg):
        """根据 symbol 选择对应矩阵（v1.8.1 BTC/ETH 均锁 3x）"""
        assert cfg.get_leverage_matrix_for_symbol("BTC-USDT-SWAP")["min_leverage"] == 3
        assert cfg.get_leverage_matrix_for_symbol("ETHUSDT")["min_leverage"] == 3
        assert cfg.get_leverage_matrix_for_symbol("SOL-USDT-SWAP")["max_leverage"] == 5
        assert cfg.get_leverage_matrix_for_symbol("DOGE-USDT-SWAP")["max_leverage"] == 5

    def test_blacklist_thresholds(self, cfg):
        assert cfg.blacklist_min_24h_volume_usdt == 50_000_000
        assert cfg.blacklist_max_funding_rate_abs == 0.001

    def test_audit_rules(self, cfg):
        assert cfg.audit_max_consecutive_losses == 3
        assert cfg.audit_lockout_duration_minutes == 30
        assert cfg.audit_fee_to_profit_ratio_threshold == 0.30
        assert cfg.audit_enable_meltdown_lock is True


class TestRiskDynamicLeverage:
    """risk.py 动态杠杆矩阵"""

    def test_default_leverage_btc_uses_matrix(self, cfg):
        """v1.8.1 阶段 5.2: BTC 默认锁 3x"""
        from okx.code.risk import RiskCalculator
        risk = RiskCalculator(cfg)
        lev = risk._get_default_leverage("BTCUSDT")
        assert lev == 3

    def test_default_leverage_eth_uses_matrix(self, cfg):
        """v1.8.1 阶段 5.2: ETH 默认锁 3x"""
        from okx.code.risk import RiskCalculator
        risk = RiskCalculator(cfg)
        lev = risk._get_default_leverage("ETHUSDT")
        assert lev == 3

    def test_default_leverage_altcoin(self, cfg):
        from okx.code.risk import RiskCalculator
        risk = RiskCalculator(cfg)
        lev = risk._get_default_leverage("SOL-USDT-SWAP")
        assert lev == 3  # 山寨币 min_leverage

    def test_calculate_dynamic_leverage_high_atr(self, cfg):
        """高 ATR → 用 min_leverage（v1.8.1 锁 3x）"""
        from okx.code.risk import RiskCalculator
        risk = RiskCalculator(cfg)
        # BTC atr_high = 250，传 300（高于 atr_high）→ 返回 min_lev
        lev = risk.calculate_dynamic_leverage("BTCUSDT", current_atr=300)
        assert lev == 3

    def test_calculate_dynamic_leverage_low_atr(self, cfg):
        """低 ATR → 用 max_leverage（v1.8.1 锁 3x）"""
        from okx.code.risk import RiskCalculator
        risk = RiskCalculator(cfg)
        # BTC atr_low = 80，传 50（低于 atr_low）→ 返回 max_lev
        lev = risk.calculate_dynamic_leverage("BTCUSDT", current_atr=50)
        assert lev == 3

    def test_calculate_dynamic_leverage_major_event(self, cfg):
        """重大事件 → 硬性熔断到 hard_ceiling"""
        from okx.code.risk import RiskCalculator
        risk = RiskCalculator(cfg)
        lev = risk.calculate_dynamic_leverage("BTCUSDT", current_atr=100, is_main_event=True)
        assert lev == 3  # BTC hard_ceiling = 3

    def test_calculate_dynamic_leverage_altcoin_high_vol_blocked(self, cfg):
        """高波动资产（max=0）→ 返回 0"""
        from okx.code.risk import RiskCalculator
        cfg._data["leverage_matrix"]["altcoin_top50"]["max_leverage"] = 0
        risk = RiskCalculator(cfg)
        lev = risk.calculate_dynamic_leverage("MEME-USDT-SWAP", current_atr=50)
        assert lev == 0


class TestPortfolioMeltdown:
    """portfolio.py 熔断机制"""

    def test_get_last_loss_timestamp_none(self, tmp_path):
        from okx.code.portfolio import Portfolio
        state_file = tmp_path / "portfolio.json"
        p = Portfolio(str(state_file))
        assert p.get_last_loss_timestamp() is None

    def test_daily_stats_has_last_loss_at(self, tmp_path):
        """daily_stats 默认应包含 last_loss_at 字段"""
        from okx.code.portfolio import Portfolio
        state_file = tmp_path / "portfolio.json"
        p = Portfolio(str(state_file))
        stats = p.get_daily_stats()
        assert "last_loss_at" in stats
        assert stats["last_loss_at"] is None
        assert "total_fee" in stats
        assert "total_pnl_gross" in stats


class TestStrategyCFramework:
    """策略 C：VOLATILITY_BREAKOUT 框架（不依赖真实 API）"""

    def test_strategy_c_check_disabled(self, cfg):
        """禁用时不返回信号"""
        from okx.code.signal import SignalEngine
        cfg._data["strategy_c"]["enabled"] = False
        se = SignalEngine(None, cfg)
        sig = se.check_volatility_breakout_signal("BTC-USDT-SWAP")
        assert sig is None

    def test_strategy_c_method_exists(self):
        """确认 check_volatility_breakout_signal 方法存在"""
        from okx.code.signal import SignalEngine
        assert hasattr(SignalEngine, "check_volatility_breakout_signal")


class TestStrategyDFramework:
    """策略 D：FUNDING_RATE_REVERSAL 框架"""

    def test_strategy_d_check_disabled(self, cfg):
        from okx.code.signal import SignalEngine
        cfg._data["strategy_d"]["enabled"] = False
        se = SignalEngine(None, cfg)
        sig = se.check_funding_rate_signal("BTC-USDT-SWAP")
        assert sig is None

    def test_strategy_d_method_exists(self):
        from okx.code.signal import SignalEngine
        assert hasattr(SignalEngine, "check_funding_rate_signal")


class TestMarketFilter:
    """market_filter.py 流动性过滤"""

    def test_filter_class_importable(self):
        from okx.code.market_filter import MarketFilter, FilterResult, get_filter
        assert MarketFilter is not None
        assert FilterResult is not None
        assert get_filter is not None

    def test_filter_cache_module_level(self):
        from okx.code import market_filter
        assert hasattr(market_filter, "_FILTER_CACHE")
        # 清空缓存避免影响后续测试
        market_filter._FILTER_CACHE["data"].clear()
        market_filter._FILTER_CACHE["expire_at"] = None


class TestConfigVersion:
    """config.json 版本升级到 1.1.0"""

    def test_config_version(self, real_config_dict):
        cfg = real_config_dict
        assert cfg["version"] == "1.1.0"
        # v1.8.3+ (2026-07-19): updated_at 推近到 D 禁用日
        assert cfg["updated_at"] == "2026-07-19"
        assert cfg["strategy_b"]["enabled"] is True
        assert cfg["strategy_c"]["enabled"] is True
        # D 禁用后配置块仍保留 (gate 必须存在 config 字段)
        assert cfg["strategy_d"]["enabled"] is False