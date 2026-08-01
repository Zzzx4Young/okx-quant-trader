# -*- coding: utf-8 -*-
"""
杠杆锁 3x TDD 测试套件 (Phase 5.2 micro-live lock)

════════════════════════════════════════════════════════════════════
本套件目的: 锁定"BTC/ETH 实际杠杆 = 3x" 的合约, 防止未来回归。

════════════════════════════════════════════════════════════════════
教训 (2026-08-01 TDD 复盘):

第一次写这测试时, 我犯了"看 5 行代码就推断因果"的错 ——
以为 signal._get_leverage 对白名单返回 default_leverage_main (=5),
实际运行发现 symbol_key 转换让 whitelist 永远 miss, fallback 返回 3。

→ 如果不跑测试直接"修", 我会给一个已经正确的系统加冗余 cap。

本套件的正确用法:
  Layer 1: 钉住"实际行为 = 3x" 的合约, 防止未来被改回 5
  Layer 2: 钉住"signal.leverage 字段 = 3" 的下游消费
  Layer 3: 文档化"default_leverage_main = 5 是 dead code" 这个发现
════════════════════════════════════════════════════════════════════
"""
from unittest.mock import MagicMock

import pytest

from okx.code.config import Config
from okx.code.signal import SignalEngine, Signal


# ──────────── Fixtures ────────────

@pytest.fixture(autouse=True)
def reset_config_singleton():
    """每个测试前重置 Config 单例, 避免跨测试污染"""
    Config._instance = None
    yield
    Config._instance = None


# ──────────── Layer 1: 实际生效的合约 — BTC/ETH 永远是 3x ────────────

class TestLeverageContractEnforced:
    """
    Phase 5.2 micro-live 合约:
    BTC/ETH 实际发给 OKX 的杠杆必须是 3x, 不是 5x。

    实现机制 (当前):
      signal._get_leverage(symbol) 对生产路径下的 BTC-USDT-SWAP / ETH-USDT-SWAP
      因为 whitelist symbol_key 转换永远 miss, fallback 返回 3。

    这个测试守住这个事实。如果有人将来"修复"了 whitelist 匹配逻辑,
    但忘记加 cap, 测试会 fail (从 3 变 5), 立即暴露 regression。
    """

    def test_btc_production_symbol_get_leverage_is_3(self, cfg):
        """BTC-USDT-SWAP (check_all_symbols 实际传入的 symbol) → 3"""
        engine = SignalEngine(market_api=MagicMock(), config=cfg)
        lev = engine._get_leverage("BTC-USDT-SWAP")
        assert lev == 3, (
            f"BTC 实际杠杆必须 = 3 (Phase 5.2), got {lev}. "
            f"如果 got 5, 说明 whitelist 匹配逻辑被错误修复且未加 cap"
        )

    def test_eth_production_symbol_get_leverage_is_3(self, cfg):
        engine = SignalEngine(market_api=MagicMock(), config=cfg)
        lev = engine._get_leverage("ETH-USDT-SWAP")
        assert lev == 3, f"ETH 实际杠杆必须 = 3, got {lev}"

    def test_btc_canonical_symbol_get_leverage_is_3(self, cfg):
        """防御性: 即使有人将来用 'BTCUSDT' (whitelist 格式) 调, 也必须 = 3

        这是 forward-compatible 测试 — 防止"修复 whitelist 匹配 + 忘 cap"
        这种最常见的 future regression
        """
        engine = SignalEngine(market_api=MagicMock(), config=cfg)
        lev = engine._get_leverage("BTCUSDT")
        # 不管 whitelist 匹不匹配, 都必须 ≤ hard_ceiling (BTC = 3)
        assert lev <= cfg.leverage_matrix_btc["hard_ceiling"], (
            f"BTC leverage 必须 ≤ hard_ceiling=3, got {lev}"
        )

    def test_eth_canonical_symbol_get_leverage_is_3(self, cfg):
        engine = SignalEngine(market_api=MagicMock(), config=cfg)
        lev = engine._get_leverage("ETHUSDT")
        assert lev <= cfg.leverage_matrix_eth["hard_ceiling"]


# ──────────── Layer 2: Signal 实例化后 leverage 字段是 3 ────────────

class TestSignalInstanceLeverageContract:
    """模拟生产 signal 创建路径, signal.leverage 字段必须 = 3"""

    def test_btc_signal_leverage_field_is_3(self, cfg):
        engine = SignalEngine(market_api=MagicMock(), config=cfg)
        lev = engine._get_leverage("BTC-USDT-SWAP")
        signal = Signal(
            strategy="EMA20_BREAKOUT",
            symbol="BTC-USDT-SWAP",
            direction="long",
            entry_price=50000.0,
            sl_price=49500.0,
            tp_price=51000.0,
            leverage=lev,
            size=1.0,
            confidence=0.8,
            reason="test",
            kline_time="1234567890",
        )
        assert signal.leverage == 3, (
            f"signal.leverage 必须 = 3 (Phase 5.2), got {signal.leverage}"
        )


# ──────────── Layer 3: 文档化 dead code ────────────

class TestDeadCodeDocumented:
    """
    发现 (2026-08-01 TDD 复盘):
      trading.default_leverage_main = 5 是 dead code —
      _get_leverage 的 whitelist 匹配逻辑因为 symbol_key 转换永远 miss,
      fallback 总是返回 3, 所以 default_leverage_main 从未被读取。

    修复 dead code 有两个选项:
      (A) 删掉 default_leverage_main 配置 + 简化 _get_leverage
      (B) 修复 symbol_key 转换让 whitelist 匹得上, 然后加 hard_ceiling cap

    本测试钉住"如果选了 (B), 必须加 cap" 这个约束。
    """

    def test_default_leverage_main_is_currently_unused(self, cfg):
        """文档测试: 当前 default_leverage_main=5 永远不被读取

        这不是要修的 bug, 是要 keep 的 invariant ——
        如果这个 test FAIL 了, 说明 _get_leverage 的 symbol 转换逻辑被改了,
        此时必须确保新逻辑仍然 cap 到 hard_ceiling (见下方 test)。
        """
        engine = SignalEngine(market_api=MagicMock(), config=cfg)
        default = cfg.default_leverage_main  # = 5

        # 如果 whitelist 匹配真的生效, _get_leverage 应该返回 5
        # 但因为 symbol_key 转换 miss, 实际返回 3 (fallback)
        lev = engine._get_leverage("BTC-USDT-SWAP")

        assert lev != default, (
            f"dead code invariant 失败: _get_leverage 返回 {lev} = default_leverage_main "
            f"({default})。这说明 whitelist 匹配逻辑已改, 必须确保新逻辑 cap 到 hard_ceiling"
        )
        assert lev == 3, (
            f"invariant 失败: 期望 _get_leverage 走 fallback=3, got {lev}"
        )



