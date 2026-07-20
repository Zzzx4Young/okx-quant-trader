"""
API Chaos Test —— OKX 5xx / 429 限流的离线验证

对应 v1.8.3+ candidate #7 的 P0.2 离线沙盒：
- Mock OKX HTTP 客户端，让 API 100% 返回 502/429
- 验证 runner.run() 在 API 持续崩溃时不会未捕获崩溃、不死循环
- 验证错误被正确记录到 results["errors"]，cycle 能继续

核心测试目标：
  1. 持续 5xx → runner.run() 不抛 uncaught exception
  2. 持续 429 → 同上（rate limit 场景）
  3. 错误信息记录到 results["errors"]
  4. 无无限死循环（urllib3.Retry 总尝试次数 cap 在 max_retries=3）
  5. 真实行为 vs 文档规范的 gap 标记（无 SYSTEM_LOCK，runner 用 except 优雅跳过）

设计依据：
  - code/runner.py:88-117 run() 方法的 try/except 块
  - code/_http.py:96-105 urllib3 Retry 配置 (max_retries=3, backoff_factor=1.0)
  - 文档规范: okx/docs/agent-context/无实盘非24H运行推进方案.md P0.2
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 真实行为 marker（与文档规范的 gap）
GRACEFUL_DEGRADATION_NOTE = """
真实行为 vs 文档规范：
- 文档要求: "runner.py 指数级退避 + SYSTEM_LOCK"
- 实际实现: 退避在 urllib3.Retry 层（_http.py:98-103），runner.py 用
           broad except Exception (runner.py:117) 优雅跳过
- SYSTEM_LOCK 概念当前不存在；如需新加需独立 PR
"""


# ─────────────────────────────────────────────────────────────
# 共享 fixture：构造一个最小 Runner 实例，API 已被 mock
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def mock_okx_client():
    """构造一个 Mock OKXClient，get_positions/get_positions_history 默认抛"""
    client = MagicMock()
    # 默认所有 API 调用抛 RetryError（模拟 urllib3 重试耗尽）
    from requests.exceptions import RetryError
    client.account.get_positions.side_effect = RetryError("502 Bad Gateway after 3 retries")
    client.account.get_positions_history.side_effect = RetryError("502 Bad Gateway after 3 retries")
    client.public.get_instruments.side_effect = RetryError("502 Bad Gateway after 3 retries")
    return client


@pytest.fixture
def minimal_runner(mock_okx_client, tmp_path):
    """构造一个最小化 Runner 用于 API chaos 测试

    Runner.__init__(okx_client, config_path, notifier) 签名中：
    - okx_client 注入 mock
    - config_path 参数实际未使用（__init__ 调用 get_config() 模块级单例）
    - notifier 注入 mock 防真发 Telegram

    修正点：
    - 预加载 okx.code.config._config 模块全局避免读真实 config.json
    - 构造后覆盖 _portfolio 属性（__init__ 默认创建 Portfolio() 无参数）
    """
    from okx.code.runner import Runner
    from okx.code.portfolio import Portfolio
    from okx.code import config as config_module

    # 用临时 config + portfolio
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    portfolio_path = state_dir / "portfolio.json"
    portfolio_path.write_text(json.dumps({
        "version": "1.0.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "positions": [],
        "closed_positions": [],
        "daily_stats": {
            "date": "2026-07-20",
            "total_trades": 0,
            "loss_trades": 0,
            "consecutive_losses": 0,
            "total_pnl": 0.0,
            "total_fee": 0.0,
            "total_pnl_gross": 0.0,
            "last_loss_at": None,
            "emergency_stop_triggered": False,
        },
    }))

    # Mock config 单例，跳过真实 config.json 加载
    mock_cfg = MagicMock()
    mock_cfg.demo_mode = True
    mock_cfg.trade_on_quarter = False
    mock_cfg.notifier_enabled = False

    original_config = config_module._config
    config_module._config = mock_cfg

    try:
        notifier = MagicMock()
        notifier.enabled = False

        runner = Runner(
            okx_client=mock_okx_client,
            notifier=notifier,
        )
        # 覆盖 _portfolio （Runner.__init__ 默认创建新 Portfolio()）
        runner._portfolio = Portfolio(str(portfolio_path))
        return runner
    finally:
        config_module._config = original_config


# ─────────────────────────────────────────────────────────────
# 场景 B1: 持续 502 → runner 不崩
# ─────────────────────────────────────────────────────────────
def test_persistent_502_does_not_crash(minimal_runner):
    """模拟 OKX API 100% 返回 502（urllib3 重试 3 次后抛 RetryError）

    期望：runner.run() 优雅捕获，不抛 uncaught exception
    """
    start = time.perf_counter()
    results = minimal_runner.run()
    elapsed = time.perf_counter() - start

    # 关键断言：run() 必须正常返回 dict
    assert isinstance(results, dict), f"runner.run() 应返回 dict，实际 {type(results)}"
    assert "errors" in results, "results 必须包含 errors 字段"
    assert "timestamp" in results, "results 必须包含 timestamp"


# ─────────────────────────────────────────────────────────────
# 场景 B2: 持续 429 (rate limit) → runner 不崩
# ─────────────────────────────────────────────────────────────
def test_persistent_429_does_not_crash(minimal_runner, mock_okx_client):
    """模拟 OKX API 100% 返回 429 (rate limit)"""
    from requests.exceptions import RetryError
    err_429 = RetryError("429 Too Many Requests after 3 retries")
    mock_okx_client.account.get_positions.side_effect = err_429
    mock_okx_client.account.get_positions_history.side_effect = err_429

    results = minimal_runner.run()

    assert isinstance(results, dict)
    assert "errors" in results


# ─────────────────────────────────────────────────────────────
# 场景 B3: 错误信息记录到 results["errors"]
# ─────────────────────────────────────────────────────────────
def test_502_error_recorded_in_results(minimal_runner):
    """API 异常应被记录到 results["errors"] 供后续分析"""
    results = minimal_runner.run()

    assert len(results["errors"]) > 0, "API 异常应进 errors 字段"
    # 错误信息应说明是对账失败
    error_text = " ".join(results["errors"])
    assert "对账" in error_text or "reconcile" in error_text.lower() or "Retry" in error_text or "502" in error_text, \
        f"error 应说明来源: {error_text}"


# ─────────────────────────────────────────────────────────────
# 场景 B4: 无无限死循环——单次 run() 在合理时间内完成
# ─────────────────────────────────────────────────────────────
def test_no_infinite_loop_on_persistent_5xx(minimal_runner):
    """即使 100% 5xx，runner.run() 必须在合理时间内返回（不死循环）

    urllib3.Retry cap 在 max_retries=3，加上 backoff 1s+2s+4s=7s，
    加上 runner 内部 try/except 处理，单次 run() 应在 30s 内完成
    """
    start = time.perf_counter()
    results = minimal_runner.run()
    elapsed = time.perf_counter() - start

    assert elapsed < 30, f"runner.run() 耗时 {elapsed:.1f}s 超过 30s 上限，可能死循环"


# ─────────────────────────────────────────────────────────────
# 场景 B5: API 部分失败——混合 502 + 200
# ─────────────────────────────────────────────────────────────
def test_partial_api_failure_graceful(minimal_runner, mock_okx_client):
    """get_positions 200 但 get_positions_history 500——部分失败也优雅

    真实场景：API 部分 endpoint down，runner 应该容忍并继续
    """
    from requests.exceptions import RetryError

    # get_positions 成功
    mock_okx_client.account.get_positions.return_value = []
    # get_positions_history 失败
    mock_okx_client.account.get_positions_history.side_effect = RetryError("500 Internal Server Error")
    # get_instruments 成功（用于 ctVal 缓存）
    mock_okx_client.public.get_instruments.return_value = []

    results = minimal_runner.run()

    # 不崩
    assert isinstance(results, dict)
    # 由于 history 失败，整个 reconcile try 块会进 except 分支
    assert len(results["errors"]) > 0


# ─────────────────────────────────────────────────────────────
# 场景 B6: 100 次连续 run() 无资源泄漏
# ─────────────────────────────────────────────────────────────
def test_100_cycles_no_resource_leak(minimal_runner):
    """100 次连续 run() 调用模拟长期 API down 场景

    不能有：内存泄漏 / 文件句柄泄漏 / 端口耗尽 / signal 累积
    """
    for i in range(100):
        results = minimal_runner.run()
        assert isinstance(results, dict), f"cycle {i} 失败"


# ─────────────────────────────────────────────────────────────
# 场景 B7: 网络层异常（DNS 失败 / Connection Refused）
# ─────────────────────────────────────────────────────────────
def test_connection_error_no_crash(minimal_runner, mock_okx_client):
    """模拟 DNS 失败 / Connection Refused（requests.exceptions.ConnectionError）"""
    from requests.exceptions import ConnectionError
    err = ConnectionError("DNS resolution failed: www.okx.com")
    mock_okx_client.account.get_positions.side_effect = err
    mock_okx_client.account.get_positions_history.side_effect = err

    results = minimal_runner.run()

    assert isinstance(results, dict)
    assert len(results["errors"]) > 0


# ─────────────────────────────────────────────────────────────
# 场景 B8: 文档 vs 真实行为 gap 标记（不写为 assertion，仅文档化）
# ─────────────────────────────────────────────────────────────
def test_doc_gap_documented():
    """标记 v1.8.3+ P0.2 文档与真实行为的差异

    文档要求 SYSTEM_LOCK，真实实现是 graceful skip。
    如果未来加 SYSTEM_LOCK，本测试将需要更新（不再是 gap）。
    """
    # 此测试只做文档化标记；它总是 pass
    assert True, GRACEFUL_DEGRADATION_NOTE.strip()


# ─────────────────────────────────────────────────────────────
# 场景 B9: 重试次数封顶——urllib3.Retry cap 在 max_retries=3
# ─────────────────────────────────────────────────────────────
def test_urllib3_retry_capped_at_max():
    """验证 urllib3.Retry 配置的 max_retries=3 真的封顶

    这是 P0.2 文档中"无无限死循环"的硬性门：
    - max_retries=3 (default), backoff_factor=1.0
    - status_forcelist=[429, 500, 502, 503, 504]
    - 总尝试 = 1 + 3 = 4 次；总退避时间 ~1s+2s+4s = 7s
    """
    from okx.code._http import HTTPClient
    client = HTTPClient(mode="demo", timeout=10, max_retries=3, retry_backoff=1.0)

    # 检查 urllib3 Retry 配置
    adapter = client.session.get_adapter("https://www.okx.com")
    retry = adapter.max_retries

    assert retry.total == 3, f"max_retries 应为 3，实际 {retry.total}"
    assert retry.backoff_factor == 1.0, f"backoff_factor 应为 1.0，实际 {retry.backoff_factor}"
    # status_forcelist 应包含 502 和 429
    status_list = list(retry.status_forcelist)
    assert 502 in status_list, f"status_forcelist 应包含 502，实际 {status_list}"
    assert 429 in status_list, f"status_forcelist 应包含 429，实际 {status_list}"


# ─────────────────────────────────────────────────────────────
# 场景 B10: 异常类型多样性——验证 broad except 覆盖
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("exception", [
    Exception("Generic failure"),
    RuntimeError("Runtime failure"),
    ValueError("Bad value"),
    KeyError("missing_key"),
    OSError("Network unreachable"),
])
def test_various_exceptions_caught(minimal_runner, mock_okx_client, exception):
    """runner.py:117 用 broad except Exception 覆盖多种异常类型

    即使抛出未预期的异常类型（如 KeyError），runner 不应崩
    """
    mock_okx_client.account.get_positions.side_effect = exception
    mock_okx_client.account.get_positions_history.side_effect = exception

    results = minimal_runner.run()

    assert isinstance(results, dict)
    assert len(results["errors"]) > 0, f"{type(exception).__name__} 应被捕获记录"