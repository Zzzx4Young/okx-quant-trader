# -*- coding: utf-8 -*-
"""
OKX 实时事件总线 + SSE broadcast —— v1.4 Phase 2 (P3#4-A)

设计目标:
- asyncio.Queue per SSE connection (slow consumer 不阻塞 publisher)
- 跨线程 event publish: cron scripts (sync) → FastAPI event loop (async)
- Bounded queue (max 100 events per connection, 1000 thread_queue) 防内存泄漏
- 自动清理 dead connection (try/finally unsubscribe)
- 缺失 FastAPI event loop 时 thread_queue 累积 → 启动后批量 flush

用法:
  # Backend cron script (sync context):
  from okx.web.backend.events import publish_event
  publish_event("cron_run", {"cron_name": "okx-daily-heartbeat", "status": "ok"})

  # FastAPI SSE endpoint (async context):
  from okx.web.backend.events import event_bus, Event
  queue = event_bus.subscribe()
  try:
      while True:
          event = await queue.get()
          yield event.to_sse()
  finally:
      event_bus.unsubscribe(queue)

跑测：bash run.sh -m pytest okx/tests/test_events.py -v
"""

from __future__ import annotations

import asyncio
import json
import queue as thread_queue
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set


# ──────────────── Event dataclass ────────────────


@dataclass
class Event:
    """SSE event payload

    :param event_type: 'cron_run' | 'portfolio_update' | 'health_alert' | 'connected' | ...
    :param timestamp: ISO-8601 UTC timestamp
    :param data: event payload (JSON-serializable dict)
    """
    event_type: str
    timestamp: str
    data: Dict[str, Any]

    def to_sse(self) -> str:
        """Format as SSE wire protocol

        Format:
            event: <event_type>
            data: <json_payload>

            (blank line terminates event)
        """
        return f"event: {self.event_type}\ndata: {json.dumps(asdict(self), ensure_ascii=False)}\n\n"


def make_event(event_type: str, data: Dict[str, Any]) -> Event:
    """Convenience: create Event with current UTC timestamp."""
    return Event(
        event_type=event_type,
        timestamp=datetime.now(timezone.utc).isoformat(),
        data=data,
    )


# ──────────────── EventBus ────────────────


class EventBus:
    """SSE event bus with asyncio.Queue per connection.

    Architecture:
        [Cron thread (sync)]
            ↓ publish_from_thread()
        [thread_queue.Queue (maxsize=1000)]  ← buffer cross-thread events
            ↓ drain_loop() (background task in FastAPI event loop)
        [asyncio.Queue per subscriber (maxsize=100)]  ← per-connection bounded
            ↓ queue.get()
        [SSE endpoint generator]

    Key properties:
    - Slow consumer (full asyncio.Queue) → events dropped (not blocked)
    - thread_queue full → events dropped (not blocked)
    - FastAPI not running → events accumulate in thread_queue, flushed on next drain
    """

    def __init__(self, max_queue_size: int = 100, max_thread_queue: int = 1000):
        self._subscribers: Set[asyncio.Queue] = set()
        self._max_queue_size = max_queue_size
        self._thread_queue: thread_queue.Queue = thread_queue.Queue(maxsize=max_thread_queue)
        self._drainer_task: Optional[asyncio.Task] = None
        self._stats = {
            "published": 0,
            "delivered": 0,
            "dropped_slow_consumer": 0,
            "dropped_thread_queue_full": 0,
        }

    # ─── Async API (in FastAPI event loop) ───

    async def publish(self, event: Event) -> None:
        """Publish event to all async subscribers (drops for full queues)."""
        self._stats["published"] += 1
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
                self._stats["delivered"] += 1
            except asyncio.QueueFull:
                self._stats["dropped_slow_consumer"] += 1

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to events. Returns asyncio.Queue (caller must unsubscribe)."""
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Unsubscribe queue (call in finally block)."""
        self._subscribers.discard(q)

    def start_drainer(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start background drainer task (called from FastAPI startup event)."""
        if self._drainer_task is None or self._drainer_task.done():
            self._drainer_task = loop.create_task(self._drain_loop())

    async def _drain_loop(self) -> None:
        """Background task: drain thread_queue → asyncio subscribers."""
        while True:
            try:
                event = self._thread_queue.get_nowait()
            except thread_queue.Empty:
                await asyncio.sleep(0.5)
                continue
            except Exception:
                await asyncio.sleep(1.0)
                continue
            await self.publish(event)

    # ─── Sync API (from cron threads) ───

    def publish_from_thread(self, event_type: str, data: Dict[str, Any]) -> None:
        """Thread-safe publish from any thread (e.g., cron scripts)."""
        event = make_event(event_type, data)
        try:
            self._thread_queue.put_nowait(event)
        except thread_queue.Full:
            self._stats["dropped_thread_queue_full"] += 1

    # ─── Diagnostics ───

    def get_stats(self) -> Dict[str, Any]:
        """Return event bus stats (for monitoring/dashboard)."""
        return {
            **self._stats,
            "subscribers": len(self._subscribers),
            "thread_queue_size": self._thread_queue.qsize(),
        }


# ──────────────── Global singleton ────────────────


event_bus = EventBus()


def publish_event(event_type: str, data: Dict[str, Any]) -> None:
    """Convenience: thread-safe publish from any context (sync or async)."""
    event_bus.publish_from_thread(event_type, data)
