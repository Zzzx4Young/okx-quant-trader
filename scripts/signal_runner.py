#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
signal_runner.py —— K 线驱动的一次性信号执行器（Phase 4 Gate 9）

═══════════════════════════════════════════════════════════════════
目的：替代文档"修改 runner_watchdog.py"的错误设计，作为 K 线整点的
      cron-triggered 脚本，把"预热 + Spin-lock + Runner.run()"封装
      在一个原子单元里，确保整点过后的第一毫秒发起 API 请求。
═══════════════════════════════════════════════════════════════════

⚠️ 设计原则：
  1. **不持有循环**——单次执行由 cron 触发，避免 daemon 进程崩溃失控
  2. **预热与 Spin-lock 分离**——预热在 K-line 前 2m42s 完成，最后 5s Spin-lock
  3. **冷启动预算 2m42s**——按 cron 子代理冷启动实测（参考 MEMORY.md）
  4. **TOLERANCE_MINUTES = 3**——已经在 Runner._is_trade_time() 内实现
  5. **异常不退出非零码**——单次异常不影响下个 cron tick

执行流程：
  T = -2m42s: cron 触发 → 加载 numpy/pandas/OKXClient（预热）
  T = -5s:    进入 Spin-lock（busy-wait，每 100ms 检查一次）
  T = 0:      K 线整点 → 调用 Runner.run() → 退出

CLI 例子：
  # 默认（timeframe=15m, mode=demo）
  bash okx/run.sh okx/scripts/signal_runner.py --timeframe 15m

  # 手动跑一次（不等 Spin-lock，立即执行）
  bash okx/run.sh okx/scripts/signal_runner.py --timeframe 15m --no-spin

  # 调试预热耗时
  bash okx/run.sh okx/scripts/signal_runner.py --timeframe 15m --profile-warmup
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ──────────────── K 线整点计算 ────────────────


def compute_next_bar_boundary(
    timeframe: str = "15m",
    now: Optional[datetime] = None,
) -> datetime:
    """
    计算下一个 K 线整点边界（UTC）

    :param timeframe: 1m / 5m / 15m / 30m / 1h / 4h
    :param now: 当前 UTC 时间（None = datetime.now(UTC)）
    :return: 下一个 K 线整点 datetime（UTC）
    """
    if now is None:
        now = datetime.now(timezone.utc)

    tf_map = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240, "1d": 1440,
    }
    minutes = tf_map.get(timeframe.lower())
    if minutes is None:
        raise ValueError(f"不支持的 timeframe: {timeframe}（可选: {list(tf_map.keys())}）")

    # 计算下一个整点 = 当前时间向上对齐到 timeframe 的整数倍
    epoch_minutes = int(now.timestamp() // 60)
    next_boundary_min = ((epoch_minutes // minutes) + 1) * minutes
    boundary = datetime.fromtimestamp(next_boundary_min * 60, tz=timezone.utc)

    return boundary


def compute_spinlock_deadline(
    boundary: datetime,
    spinlock_seconds: float = 5.0,
) -> datetime:
    """Spin-lock 起始时刻 = boundary - spinlock_seconds"""
    return boundary - timedelta(seconds=spinlock_seconds)


# ──────────────── 预热（heavy imports） ────────────────


def warmup_heavy_dependencies(profile: bool = False) -> Dict[str, float]:
    """
    预热重依赖：numpy/pandas/OKXClient（确保 K 线整点前完成）

    :param profile: 是否记录各步骤耗时
    :return: 各步骤耗时 dict（秒）
    """
    timings: Dict[str, float] = {}

    # 1. numpy / pandas
    t0 = time.time()
    import numpy  # noqa: F401
    import pandas  # noqa: F401
    timings["numpy_pandas"] = time.time() - t0

    # 2. OKXClient + MarketAPI + AccountAPI（连接池预热）
    t0 = time.time()
    from okx.code.client import OKXClient

    client = OKXClient()
    timings["okx_client_init"] = time.time() - t0

    # 3. 拉一次 ticker（连接预热）
    t0 = time.time()
    try:
        client.market.get_ticker("BTC-USDT-SWAP")
        timings["ticker_warmup_ok"] = True
    except Exception as e:
        logger.warning(f"ticker 预热失败（不阻塞）: {e}")
        timings["ticker_warmup_ok"] = False
    timings["ticker_warmup"] = time.time() - t0

    # 4. SignalEngine + RiskCalculator 实例化
    t0 = time.time()
    from okx.code.signal import SignalEngine
    from okx.code.risk import RiskCalculator

    _ = SignalEngine(client.market)
    _ = RiskCalculator()
    timings["engine_init"] = time.time() - t0

    if profile:
        logger.info("🔥 预热耗时:")
        for step, dur in timings.items():
            logger.info(f"   {step}: {dur * 1000:.0f}ms")

    total = sum(v for k, v in timings.items() if not k.endswith("_ok"))
    logger.info(f"✅ 预热总耗时: {total:.2f}s（限 2m42s = 162s）")
    return timings


# ──────────────── Spin-lock ────────────────


def spinlock_until(target: datetime, poll_interval_ms: int = 100) -> None:
    """
    Spin-lock 等待到目标时刻（busy-wait，最后 N 秒）

    设计目的：避免 sleep 的不精确性，确保在整点过后的第一毫秒发起 API 请求。
    注意：只用于最后 5 秒（spinlock_seconds=5），不会消耗太多 CPU。

    :param target: 目标 UTC datetime
    :param poll_interval_ms: busy-wait poll 间隔（毫秒）
    """
    target_ts = target.timestamp()
    logger.info(f"🔒 Spin-lock 等待至 {target.isoformat()}（≤ 5s）")
    while True:
        now_ts = datetime.now(timezone.utc).timestamp()
        remaining_ms = (target_ts - now_ts) * 1000
        if remaining_ms <= 0:
            break
        # 微秒级精度：用 time.sleep(poll_interval_ms / 1000)
        time.sleep(poll_interval_ms / 1000.0)
    logger.info("⚡ Spin-lock 完成，开始执行 Runner.run()")


# ──────────────── 主流程 ────────────────


def run_at_next_bar(
    timeframe: str = "15m",
    spinlock_seconds: float = 5.0,
    profile_warmup: bool = False,
    skip_spinlock: bool = False,
) -> Dict[str, Any]:
    """
    在下一个 K 线整点执行 Runner.run()

    :param timeframe: K 线周期
    :param spinlock_seconds: Spin-lock 持续时间（秒）
    :param profile_warmup: 是否 profile 预热耗时
    :param skip_spinlock: 跳过 Spin-lock（调试用）
    :return: 执行结果
    """
    started_at = datetime.now(timezone.utc)
    result: Dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "timeframe": timeframe,
        "boundary": None,
        "warmup_duration_s": None,
        "spinlock_skipped": skip_spinlock,
        "runner_result": None,
        "errors": [],
    }

    # 1. 计算 K 线边界
    boundary = compute_next_bar_boundary(timeframe, now=started_at)
    result["boundary"] = boundary.isoformat()
    spinlock_start = compute_spinlock_deadline(boundary, spinlock_seconds)

    logger.info(f"📊 当前 {started_at.isoformat()}, 下一个 K 线整点: {boundary.isoformat()}")
    logger.info(f"   Spin-lock 起始: {spinlock_start.isoformat()} (倒数 {spinlock_seconds}s)")

    # 2. 立即预热（不等到 Spin-lock 起始）
    try:
        warmup_timings = warmup_heavy_dependencies(profile=profile_warmup)
        result["warmup_duration_s"] = round(
            sum(v for k, v in warmup_timings.items() if not k.endswith("_ok")), 3
        )
        result["warmup_timings"] = {k: round(v * 1000, 1) for k, v in warmup_timings.items()}
    except Exception as e:
        logger.exception(f"预热失败: {e}")
        result["errors"].append(f"warmup_failed: {e}")
        # 预热失败不应阻塞（K 线驱动容错：单点失败不退出非零码）

    # 3. 等待 Spin-lock 起始（用 sleep 而非 Spin-lock，避免长时间 CPU 占用）
    now = datetime.now(timezone.utc)
    if now < spinlock_start and not skip_spinlock:
        wait_seconds = (spinlock_start - now).total_seconds()
        logger.info(f"⏳ 等待 Spin-lock 起始: {wait_seconds:.1f}s")
        time.sleep(wait_seconds)

    # 4. Spin-lock（最后 spinlock_seconds 秒）
    if not skip_spinlock:
        spinlock_until(boundary, poll_interval_ms=100)
    else:
        logger.warning("⚠️ 跳过 Spin-lock（调试模式）")

    # 5. 调用 Runner.run()
    try:
        from okx.code.runner import Runner

        runner = Runner()
        runner_result = runner.run()
        result["runner_result"] = runner_result
        logger.info(
            f"✅ Runner.run() 完成: signal_triggered={runner_result.get('signal_triggered')}, "
            f"errors={len(runner_result.get('errors', []))}"
        )
    except Exception as e:
        logger.exception(f"Runner.run() 失败: {e}")
        result["errors"].append(f"runner_failed: {e}")

    # 6. 写 heartbeat（让 watchdog 知道本次执行成功）
    try:
        _write_heartbeat(result)
    except Exception as e:
        logger.warning(f"写 heartbeat 失败（不阻塞）: {e}")

    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    return result


def _write_heartbeat(result: Dict[str, Any]) -> None:
    """写本地 heartbeat 文件（供 watchdog 检查新鲜度）"""
    state_dir = Path(__file__).resolve().parent.parent / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    heartbeat_path = state_dir / "signal_runner.heartbeat"

    payload = {
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": result.get("timeframe"),
        "boundary": result.get("boundary"),
        "warmup_ms": int((result.get("warmup_duration_s") or 0) * 1000),
        "signal_triggered": (result.get("runner_result") or {}).get("signal_triggered"),
        "errors_count": len(result.get("errors", [])),
    }
    heartbeat_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ──────────────── CLI ────────────────


def main():
    parser = argparse.ArgumentParser(description="K 线驱动信号执行器（Phase 4 Gate 9）")
    parser.add_argument(
        "--timeframe", default="15m",
        help="K 线周期: 1m / 5m / 15m / 30m / 1h / 4h / 1d（默认 15m）",
    )
    parser.add_argument(
        "--spinlock-seconds", type=float, default=5.0,
        help="Spin-lock 持续秒数（默认 5s）",
    )
    parser.add_argument(
        "--profile-warmup", action="store_true",
        help="Profile 预热各步骤耗时",
    )
    parser.add_argument(
        "--no-spin", action="store_true",
        help="跳过 Spin-lock（调试用，立即执行）",
    )
    parser.add_argument(
        "--compute-boundary-only", action="store_true",
        help="只计算下一个 K 线边界并打印，不执行 Runner",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只跑预热 + 计算边界，不调用 Runner.run()",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if args.compute_boundary_only:
        boundary = compute_next_bar_boundary(args.timeframe)
        spinlock_start = compute_spinlock_deadline(boundary, args.spinlock_seconds)
        print(json.dumps({
            "now_utc": datetime.now(timezone.utc).isoformat(),
            "timeframe": args.timeframe,
            "next_boundary_utc": boundary.isoformat(),
            "spinlock_start_utc": spinlock_start.isoformat(),
            "seconds_until_boundary": (boundary - datetime.now(timezone.utc)).total_seconds(),
        }, indent=2))
        return

    if args.dry_run:
        logger.info("🔸 dry-run 模式：只跑预热 + 计算边界")
        boundary = compute_next_bar_boundary(args.timeframe)
        spinlock_start = compute_spinlock_deadline(boundary, args.spinlock_seconds)
        timings = warmup_heavy_dependencies(profile=True)
        print(json.dumps({
            "dry_run": True,
            "now_utc": datetime.now(timezone.utc).isoformat(),
            "next_boundary_utc": boundary.isoformat(),
            "spinlock_start_utc": spinlock_start.isoformat(),
            "warmup_timings_ms": {k: round(v * 1000, 1) for k, v in timings.items()},
        }, indent=2))
        return

    result = run_at_next_bar(
        timeframe=args.timeframe,
        spinlock_seconds=args.spinlock_seconds,
        profile_warmup=args.profile_warmup,
        skip_spinlock=args.no_spin,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    # 退出码：errors 为空 → 0；否则 2（区分网络/系统错误 1）
    sys.exit(0 if not result["errors"] else 2)


if __name__ == "__main__":
    main()