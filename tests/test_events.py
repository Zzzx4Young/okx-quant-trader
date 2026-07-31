# -*- coding: utf-8 -*-
"""
OKX 实时事件总线 + SSE tests —— v1.4 Phase 2 (P3#4-A)

覆盖:
  T1 Event.to_sse() 格式正确 (event: + data: + \\n\\n)
  T2 EventBus publish / subscribe round-trip
  T3 多 subscriber 都能收到同一 event
  T4 Slow consumer: full queue 时 drop (不阻塞 publisher)
  T5 Unsubscribe 后不再接收
  T6 publish_from_thread (跨线程) 写入 thread_queue
  T7 thread_queue 满时 drop (不阻塞)
  T8 drain_loop 把 thread_queue → asyncio.Queue 完整传递
  T9 drain_loop 持续运行不因单次 error 终止

跑测：bash run.sh -m pytest okx/tests/test_events.py -v
"""

import asyncio
import queue as thread_queue

import pytest

from okx.web.backend.events import (
    Event,
    EventBus,
    event_bus,
    make_event,
    publish_event,
)


# ──────────────── T1. Event.to_sse format ────────────────


def test_event_to_sse_basic_format():
    """T1: to_sse 应产生 SSE wire protocol (event: / data: / \\n\\n 终止)"""
    event = Event(event_type="cron_run", timestamp="2026-08-01T00:00:00Z", data={"x": 1})
    sse = event.to_sse()
    assert sse.startswith("event: cron_run\n"), f"missing 'event:' prefix: {sse!r}"
    assert 'data: ' in sse, f"missing 'data:' line: {sse!r}"
    assert sse.endswith("\n\n"), f"必须以 blank line 终止: {sse!r}"


def test_event_to_sse_data_is_valid_json():
    """T1: data 行必须是 valid JSON (含嵌套 data dict)"""
    import json
    event = Event(event_type="health_alert", timestamp="now", data={"level": "critical", "component": "logs/runner.log"})
    sse = event.to_sse()
    data_line = next(line for line in sse.split("\n") if line.startswith("data: "))
    payload = json.loads(data_line[len("data: "):])
    assert payload["event_type"] == "health_alert"
    assert payload["timestamp"] == "now"
    assert payload["data"]["level"] == "critical"
    assert payload["data"]["component"] == "logs/runner.log"


def test_make_event_uses_utc_now():
    """T1: make_event 自动填入 UTC ISO-8601 timestamp"""
    from datetime import datetime, timezone, timedelta

    before = datetime.now(timezone.utc)
    event = make_event("test", {"k": "v"})
    after = datetime.now(timezone.utc)

    ts = datetime.fromisoformat(event.timestamp)
    assert before - timedelta(seconds=1) <= ts <= after + timedelta(seconds=1)


# ──────────────── T2. Basic publish / subscribe ────────────────


@pytest.mark.asyncio
async def test_publish_subscribe_roundtrip():
    """T2: publish 后 subscriber 立即收到"""
    bus = EventBus()
    q = bus.subscribe()
    event = Event(event_type="test", timestamp="2026-08-01T00:00:00Z", data={"x": 1})

    await bus.publish(event)

    received = await asyncio.wait_for(q.get(), timeout=1.0)
    assert received.event_type == "test"
    assert received.data == {"x": 1}


# ──────────────── T3. Multiple subscribers ────────────────


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive():
    """T3: broadcast 语义, 所有 subscriber 都收到同一 event"""
    bus = EventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    q3 = bus.subscribe()

    event = Event(event_type="broadcast", timestamp="now", data={"k": "v"})
    await bus.publish(event)

    for q in [q1, q2, q3]:
        received = await asyncio.wait_for(q.get(), timeout=1.0)
        assert received.event_type == "broadcast"
        assert received.data == {"k": "v"}


# ──────────────── T4. Slow consumer drops (不阻塞) ────────────────


@pytest.mark.asyncio
async def test_slow_consumer_drops_events():
    """T4: subscriber queue 满时, publisher 不阻塞, 事件被 drop"""
    bus = EventBus(max_queue_size=2)
    q = bus.subscribe()

    # 发布 10 个事件, subscriber 不消费
    for i in range(10):
        await bus.publish(Event(event_type="e", timestamp="t", data={"i": i}))

    # 只保留 2 个 (max_queue_size=2)
    assert q.qsize() == 2

    stats = bus.get_stats()
    assert stats["dropped_slow_consumer"] == 8  # 10 - 2 = 8 dropped


# ──────────────── T5. Unsubscribe ────────────────


@pytest.mark.asyncio
async def test_unsubscribe_stops_receiving():
    """T5: unsubscribe 后不再接收"""
    bus = EventBus()
    q = bus.subscribe()
    bus.unsubscribe(q)

    await bus.publish(Event(event_type="after_unsub", timestamp="t", data={}))
    assert q.qsize() == 0
    assert len(bus._subscribers) == 0


# ──────────────── T6. publish_from_thread (cross-thread) ────────────────


def test_publish_from_thread_writes_to_thread_queue():
    """T6: sync thread 发布到 thread_queue (异步 drainer 后续 flush)"""
    bus = EventBus()
    bus.publish_from_thread("test", {"i": 1})
    bus.publish_from_thread("test", {"i": 2})

    assert bus._thread_queue.qsize() == 2

    e1 = bus._thread_queue.get_nowait()
    e2 = bus._thread_queue.get_nowait()
    assert e1.event_type == "test" and e1.data == {"i": 1}
    assert e2.event_type == "test" and e2.data == {"i": 2}


def test_publish_from_thread_multiple_threads():
    """T6: 多线程并发 publish_from_thread, 全 thread-safe"""
    import threading

    bus = EventBus()

    def worker(n: int):
        for i in range(n):
            bus.publish_from_thread("worker", {"i": i})

    threads = [threading.Thread(target=worker, args=(50,)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 3 threads × 50 events = 150 (无丢失)
    assert bus._thread_queue.qsize() == 150


# ──────────────── T7. thread_queue 满时 drop ────────────────


def test_thread_queue_full_drops():
    """T7: thread_queue 满 (1000) 时, 后续 publish drop (不阻塞)"""
    bus = EventBus(max_thread_queue=10)  # 小队列 for test

    for i in range(20):
        bus.publish_from_thread("e", {"i": i})

    # 只有 10 个 (队列大小)
    assert bus._thread_queue.qsize() == 10
    stats = bus.get_stats()
    assert stats["dropped_thread_queue_full"] == 10


# ──────────────── T8. drain_loop 完整传递 ────────────────


@pytest.mark.asyncio
async def test_drain_loop_publishes_to_subscribers():
    """T8: drain_loop task 把 thread_queue → asyncio.Queue 完整传递"""
    bus = EventBus()
    loop = asyncio.get_running_loop()
    bus.start_drainer(loop)
    q = bus.subscribe()

    # 从 sync context 发布 (cron script 模式)
    bus.publish_from_thread("drained", {"hello": "world"})
    bus.publish_from_thread("drained", {"hello": "world2"})

    # 等待 drainer pick up (sleep 0.5s in drain_loop)
    await asyncio.sleep(0.7)

    # 验证 events 已传递到 subscriber
    assert q.qsize() >= 2
    e1 = await asyncio.wait_for(q.get(), timeout=2.0)
    assert e1.event_type == "drained"
    assert e1.data["hello"] in ("world", "world2")


# ──────────────── T9. drain_loop 持续运行不中断 ────────────────


@pytest.mark.asyncio
async def test_drain_loop_survives_publish_errors():
    """T9: drain_loop 即使遇到异常也不终止 (持续运行)"""
    bus = EventBus()
    loop = asyncio.get_running_loop()
    bus.start_drainer(loop)

    # 注入坏 event 到 thread_queue (手动, 绕过 publish)
    bus._thread_queue.put_nowait("not-an-event")

    # 等待 drainer 处理
    await asyncio.sleep(0.7)

    # drainer 应该还活着 (任务没 done)
    assert not bus._drainer_task.done(), "drainer task 不应因异常而终止"


# ──────────────── T10. stats 完整性 ────────────────


@pytest.mark.asyncio
async def test_stats_track_published_and_dropped():
    """T10: get_stats() 正确跟踪 published / delivered / dropped"""
    bus = EventBus(max_queue_size=1)
    q = bus.subscribe()

    # 发 5 个, queue 大小 1 → 4 个被 drop
    for i in range(5):
        await bus.publish(Event(event_type="e", timestamp="t", data={"i": i}))

    stats = bus.get_stats()
    assert stats["published"] == 5
    assert stats["delivered"] == 1
    assert stats["dropped_slow_consumer"] == 4
    assert stats["subscribers"] == 1
    assert stats["thread_queue_size"] == 0


# ──────────────── T11. global singleton ────────────────


def test_publish_event_singleton_helper():
    """T11: publish_event() 是 thread-safe helper, 用全局 singleton"""
    # 用之前清空 thread_queue (避免其他 test 污染)
    while not event_bus._thread_queue.empty():
        try:
            event_bus._thread_queue.get_nowait()
        except thread_queue.Empty:
            break

    publish_event("global_test", {"k": "v"})
    assert event_bus._thread_queue.qsize() == 1
    e = event_bus._thread_queue.get_nowait()
    assert e.event_type == "global_test"
    assert e.data == {"k": "v"}
