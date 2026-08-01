# -*- coding: utf-8 -*-
"""
test_leverage_lock.py 自身价值审计 (TDD 自检)

2026-08-01 session: 重写第一版后, 我意识到以下问题:

Issue 1: test_if_whitelist_match_works_must_still_cap_at_hard_ceiling
  capped = min(cfg.default_leverage_main, hard_ceiling)  # always 3
  assert capped == 3
  → 测试的是 Python 的 min() 函数, 不是 production 代码.
  → 任何 cfg.default_leverage_main=5, hard_ceiling=3 都会 pass
  → 这个测试没有任何价值, 必须删除.

Issue 2: test_btc_set_leverage_receives_3x_not_5x (Layer 4)
  mock_account.set_leverage(lever=str(signal.leverage))
  assert mock_account.set_leverage.call_args.kwargs["lever"] == "3"
  → 整个"流程"都是我自己手写的 mock 调用, 没经过任何 production 代码.
  → signal.leverage = engine._get_leverage("BTC-USDT-SWAP") = 3
  → mock 直接收到 '3' 因为我们传了 signal.leverage (来自 Layer 1 已测过的函数)
  → 这个测试等于 "str(3) == '3'", 没有测试任何 production 路径.
  → 与 Layer 1 测试重复, 必须删除.

Issue 3: 测试私有方法 (_get_leverage) — implementation coupling.
  → 接受作为实用主义: tests 守住的是合约 (BTC 永远是 3x), 即使当前通过
    private method 测试. 如果将来 refactor 改方法名, 测试会 break, 但
    那时可以更新 test — 这是 acceptable maintenance cost.

本测试套件: 删除 Issue 1 + 2, 验证剩余 Layer 1+2+3 仍 GREEN.
"""
import subprocess
import sys
from pathlib import Path


def test_issue1_test_should_be_removed():
    """Issue 1 测试不应存在 (测试 Python min, 无价值)"""
    test_file = Path(__file__).resolve().parent / "test_leverage_lock.py"
    content = test_file.read_text()
    assert "test_if_whitelist_match_works_must_still_cap_at_hard_ceiling" not in content, (
        "低价值测试: capped = min(...) 永远为 3, 测试 Python min() 不是 production. "
        "必须从 test_leverage_lock.py 删除"
    )


def test_issue2_test_should_be_removed():
    """Issue 2 测试不应存在 (整个流程是 mock 调用, 无 production code path)"""
    test_file = Path(__file__).resolve().parent / "test_leverage_lock.py"
    content = test_file.read_text()
    assert "test_btc_set_leverage_receives_3x_not_5x" not in content, (
        "低价值测试: mock 流程 = 'str(3) == \"3\"', 重复 Layer 1. "
        "必须从 test_leverage_lock.py 删除"
    )


def test_leverage_lock_still_has_meaningful_layers():
    """保留 Layer 1 (合约), 2 (下游), 3 (invariant) — 都是有 bug-catching 价值的测试"""
    test_file = Path(__file__).resolve().parent / "test_leverage_lock.py"
    content = test_file.read_text()

    # 必须保留的 Layer 1 合约测试
    assert "test_btc_production_symbol_get_leverage_is_3" in content
    assert "test_eth_production_symbol_get_leverage_is_3" in content
    # 必须保留的 Layer 2 下游测试
    assert "test_btc_signal_leverage_field_is_3" in content
    # 必须保留的 Layer 3 invariant 测试 (钉住 default_leverage_main=5 永远不被读)
    assert "test_default_leverage_main_is_currently_unused" in content
