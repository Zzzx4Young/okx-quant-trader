# -*- coding: utf-8 -*-
"""
Portfolio 原子写测试 —— P0-2 修复 (2026-07-31)

触发背景：
- LESSONS_LEARNED.md §7.1 #3: portfolio 持久化原子性 — 写一半崩溃场景未测试
- okx/problem.md P-3: code/portfolio.py:146-149 直接 json.dump，无 write-to-temp + os.replace
- 历史佐证: state/portfolio.json.bak-20260724-231941-circuit（circuit_breaker 触发时 dump 的截断文件）

当前 bug：
    with open(self._path, "w", encoding="utf-8") as f:   # 立即 truncate 原文件到 0 bytes
        json.dump(self._data, f, indent=2, ...)            # 写一半崩溃 → 截断 JSON

修复目标（write-to-temp + os.replace）：
    1. tmp = same_dir / f".{name}.{pid}.tmp"  （同目录，保证 os.replace 原子）
    2. write tmp + flush + fsync
    3. os.replace(tmp, self._path)  ← 原子 rename，原文件始终可读
    4. 异常路径 cleanup tmp

测试覆盖（TDD red-green）：
    T1 正常 _save → 文件可解析
    T2 崩溃中写盘 → 原文件保留（关键！）
    T3 os.replace 失败（磁盘满） → tmp 清理 + 原文件保留
    T4 成功 _save 后无 .tmp 残留
    T5 部分写入后 _load 读到原数据（模拟进程重启）

跑测：bash run.sh -m pytest okx/tests/test_portfolio_atomic.py -v
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from okx.code.portfolio import Portfolio


# ──────────────── Fixtures ────────────────


@pytest.fixture
def portfolio_path(tmp_path) -> Path:
    """临时 portfolio.json 路径"""
    return tmp_path / "portfolio.json"


def _valid_state() -> dict:
    """最小有效 portfolio schema（满足 _validate_schema）"""
    return {
        "version": "1.0.0",
        "updated_at": "2026-07-31T00:00:00Z",
        "positions": [
            {
                "symbol": "BTC-USDT-SWAP",
                "direction": "long",
                "size": 0.1,
                "order_id": "test-original-001",
            }
        ],
        "daily_stats": {
            "date": "2026-07-31",
            "total_trades": 0,
            "loss_trades": 0,
            "consecutive_losses": 0,
            "total_pnl": 0.0,
            "total_fee": 0.0,
            "total_pnl_gross": 0.0,
            "last_loss_at": None,
            "emergency_stop_triggered": False,
        },
        "closed_positions": [],
    }


def _init_portfolio_with_state(portfolio_path: Path) -> Portfolio:
    """初始化一个含 1 个 BTC 仓位的 portfolio"""
    portfolio_path.write_text(json.dumps(_valid_state(), indent=2), encoding="utf-8")
    return Portfolio(portfolio_path=str(portfolio_path))


# ──────────────── T1. 正常 _save ────────────────


def test_save_writes_valid_json(portfolio_path):
    """T1: 正常 _save → portfolio.json 存在 + JSON 合法 + 内容可读"""
    pf = Portfolio(portfolio_path=str(portfolio_path))
    pf._data["positions"].append({
        "symbol": "ETH-USDT-SWAP",
        "direction": "short",
        "size": 1.0,
        "order_id": "test-new-001",
    })
    pf._save()

    # 文件存在
    assert portfolio_path.exists(), "_save 后 portfolio.json 必须存在"
    # JSON 合法
    data = json.loads(portfolio_path.read_text(encoding="utf-8"))
    assert "positions" in data
    assert len(data["positions"]) == 1
    assert data["positions"][0]["symbol"] == "ETH-USDT-SWAP"


# ──────────────── T2. 崩溃中写盘 → 原文件保留（核心 bug） ────────────────


def test_crash_mid_write_preserves_original_file(portfolio_path):
    """T2: 崩溃中写盘 → 原 portfolio.json 必须保留（不被 truncate）

    当前 bug 模拟：
      with open(path, "w") as f:    # ← 立即 truncate 到 0 bytes
          json.dump(...)             # 写一半崩溃 → 截断 JSON 落盘

    原子写修复后：
      任何时刻崩溃，portfolio.json 要么是旧版本（完整），要么是新版本（完整），
      绝不可能是"半写"的中间态。
    """
    # 1. 准备有效的原文件
    portfolio_path.write_text(json.dumps(_valid_state(), indent=2), encoding="utf-8")
    original_content = portfolio_path.read_text(encoding="utf-8")
    original_size = portfolio_path.stat().st_size

    # 2. 加载 + 修改（准备触发 _save）
    pf = Portfolio(portfolio_path=str(portfolio_path))
    pf._data["positions"].append({
        "symbol": "ETH-USDT-SWAP",
        "direction": "short",
        "size": 1.0,
        "order_id": "test-crash-001",
    })

    # 3. 模拟 json.dump 写一半崩溃（写到一半后抛 OSError）
    def crash_dump(*args, **kwargs):
        f = args[1]  # json.dump(obj, file, ...) 第二个参数是 file handle
        f.write('{"version": "1.0.0", "updat')  # 截断的不完整 JSON
        raise OSError("模拟崩溃: SIGKILL / OOM mid-write")

    # 4. 触发 _save, 期待 OSError
    with patch("okx.code.portfolio.json.dump", side_effect=crash_dump):
        with pytest.raises(OSError):
            pf._save()

    # 5. 关键断言: 原文件完整保留
    actual_content = portfolio_path.read_text(encoding="utf-8")
    assert actual_content == original_content, (
        "原 portfolio.json 被破坏！原子写必须保证原文件始终可读。\n"
        f"  期望长度: {len(original_content)} bytes\n"
        f"  实际长度: {len(actual_content)} bytes\n"
        f"  实际内容前 200 字符: {actual_content[:200]!r}"
    )
    assert portfolio_path.stat().st_size == original_size, (
        f"原文件 size {portfolio_path.stat().st_size} != 原始 {original_size} → 被 truncate 了"
    )


# ──────────────── T3. os.replace 失败（磁盘满）→ tmp 清理 ────────────────


def test_disk_full_cleans_tmp_and_preserves_original(portfolio_path):
    """T3: os.replace 失败（磁盘满 / 权限错）→ tmp 文件清理 + 原文件保留

    修复后实现路径：
      write tmp + fsync + os.replace  ← 这一步失败
      except: os.unlink(tmp) + raise

    必须满足：
      A. 原 portfolio.json 完整
      B. 无任何 .tmp / .portfolio* 残留（避免下次 _save 混乱）
    """
    portfolio_path.write_text(json.dumps(_valid_state(), indent=2), encoding="utf-8")
    original_content = portfolio_path.read_text(encoding="utf-8")

    pf = Portfolio(portfolio_path=str(portfolio_path))
    pf._data["positions"].append({
        "symbol": "ETH-USDT-SWAP",
        "direction": "long",
        "size": 0.5,
        "order_id": "test-disk-full-001",
    })

    # 模拟 os.replace 失败（磁盘满 / 权限错）
    with patch("okx.code.portfolio.os.replace",
               side_effect=OSError("No space left on device")):
        with pytest.raises(OSError):
            pf._save()

    # A. 原文件保留
    assert portfolio_path.read_text(encoding="utf-8") == original_content, (
        "原文件被破坏！原子写失败时必须保留原文件"
    )

    # B. tmp 文件清理（关键！否则下次 _save 会混乱或被读到残缺数据）
    tmp_files = (
        list(portfolio_path.parent.glob("*.tmp")) +
        list(portfolio_path.parent.glob(".portfolio*")) +
        list(portfolio_path.parent.glob("portfolio.json.*"))
    )
    assert not tmp_files, (
        f"残留 tmp / dotfile: {tmp_files}。原子写失败必须清理 tmp 否则下次 _save 异常"
    )


# ──────────────── T4. 成功 _save 后无 .tmp 残留 ────────────────


def test_no_tmp_leftover_after_successful_save(portfolio_path):
    """T4: 成功 _save 后无任何 tmp / dotfile 残留（happy path 清洁度）"""
    pf = Portfolio(portfolio_path=str(portfolio_path))
    pf._data["positions"].append({
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "size": 0.1,
        "order_id": "test-clean-001",
    })
    pf._save()

    # 查所有可能的残留模式
    leftovers = (
        list(portfolio_path.parent.glob("*.tmp")) +
        list(portfolio_path.parent.glob(".portfolio*")) +
        list(portfolio_path.parent.glob("portfolio.json.*"))
    )
    assert not leftovers, (
        f"_save 成功后残留文件: {leftovers}。原子写必须在 os.replace 后清理 tmp"
    )


# ──────────────── T5. 部分写入后 _load 读到原数据（进程重启场景） ────────────────


def test_load_after_atomic_failure_recovers_original(portfolio_path):
    """T5: 原子写失败后，重新 _load 必须读到原始数据（模拟进程重启）

    当前 bug 场景:
      _save 写到一半崩溃 → portfolio.json = 截断 JSON
      重启 → _load → json.load() 抛 JSONDecodeError → Portfolio __init__ 抛异常
      → 系统启动失败（虽然有 _validate_schema，但 schema 检查在 _load 之后）

    修复后场景:
      _save 写到一半崩溃 → portfolio.json = 原始完整 JSON（未被 truncate）
      重启 → _load → 读到原数据 → 正常运行
    """
    portfolio_path.write_text(json.dumps(_valid_state(), indent=2), encoding="utf-8")
    original_positions_count = len(json.loads(portfolio_path.read_text())["positions"])

    pf = Portfolio(portfolio_path=str(portfolio_path))
    pf._data["positions"].append({
        "symbol": "ETH-USDT-SWAP",
        "direction": "long",
        "size": 0.5,
        "order_id": "test-recover-001",
    })

    # 模拟崩溃
    def crash_dump(*args, **kwargs):
        f = args[1]
        f.write('{"positions": [{"symbol": "BTC-USDT-SWAP"')  # 截断
        raise OSError("崩溃 mid-write")

    with patch("okx.code.portfolio.json.dump", side_effect=crash_dump):
        with pytest.raises(OSError):
            pf._save()

    # 模拟进程重启: 重新 Portfolio()
    pf2 = Portfolio(portfolio_path=str(portfolio_path))

    # 关键断言: 加载到的是原数据，不是截断的 JSON
    assert len(pf2._data["positions"]) == original_positions_count, (
        f"_load 应该读到原数据（{original_positions_count} 个 BTC 仓位），"
        f"但实际读到 {len(pf2._data['positions'])} 个 → "
        f"portfolio.json 状态: {portfolio_path.read_text()[:100]!r}"
    )
    # 验证 order_id 是原始的（不是 ETH 那笔）
    assert pf2._data["positions"][0]["order_id"] == "test-original-001", (
        f"_load 读到的 order_id 应该是原始 'test-original-001', "
        f"实际 {pf2._data['positions'][0]['order_id']!r} → "
        f"说明 portfolio.json 是截断 JSON 不是原子保留"
    )


# ──────────────── T6. 并发写盘 — lock 保证线程安全（既有契约不能破坏） ────────────────


def test_concurrent_saves_thread_safe(portfolio_path):
    """T6: 并发 _save → JSON 始终可解析（既有 lock 契约不能被原子写破坏）

    这是回归测试：原子写实现不能打破现有的 self._lock 保证。
    """
    import threading

    pf = Portfolio(portfolio_path=str(portfolio_path))

    def writer(symbol_prefix: str, n_writes: int = 20):
        for i in range(n_writes):
            with pf._lock:
                pf._data["positions"].append({
                    "symbol": f"{symbol_prefix}-USDT-SWAP",
                    "direction": "long",
                    "size": float(i),
                    "order_id": f"{symbol_prefix}-{i}",
                })
                pf._save()

    threads = [
        threading.Thread(target=writer, args=(f"SYM{i}",))
        for i in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # JSON 必须完整可解析（如果中途 truncate，json.load 会抛异常）
    data = json.loads(portfolio_path.read_text(encoding="utf-8"))
    assert isinstance(data["positions"], list), (
        f"_save 中途被 truncate，positions 不是 list: {type(data.get('positions'))}"
    )
    # 期望: 3 thread × 20 writes = 60 个 positions
    assert len(data["positions"]) == 60, (
        f"期望 60 个 positions（3 thread × 20 writes），实际 {len(data['positions'])}"
    )
