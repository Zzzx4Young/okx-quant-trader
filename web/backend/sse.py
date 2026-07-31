# -*- coding: utf-8 -*-
"""
OKX SSE endpoints —— v1.4 Phase 2 (P3#4-A)

SSE (Server-Sent Events) endpoint for real-time event push to dashboard.
Wire format (per SSE spec):
    event: <event_type>
    data: <json_payload>

    (blank line terminates event)

Keepalive: 每 30s 发 ': keepalive' 防 proxy/nginx timeout。
Lifecycle: subscriber queue 在 finally 中 unsubscribe, 不泄漏。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/stream")
async def events_stream(since: Optional[str] = None):
    """SSE real-time event stream endpoint.

    客户端使用:
      const es = new EventSource('/api/events/stream');
      es.addEventListener('cron_run', (e) => {...});

    支持 since 参数: 客户端可以传 ISO timestamp, server 重放该时间点之后的事件
    (MVP: 暂不实现 replay, 保留接口位置)
    """
    from okx.web.backend.events import event_bus, make_event

    async def event_generator():
        # 初始 connected event (前端可以靠这个确认 SSE 链路建立)
        yield make_event("connected", {"status": "ok"}).to_sse()

        queue = event_bus.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event.to_sse()
                except asyncio.TimeoutError:
                    # Keepalive 防止 nginx/proxy 切断 idle 连接
                    yield ": keepalive\n\n"
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 proxy buffering
        },
    )


@router.get("/stats")
def events_stats():
    """Event bus 诊断 (供 dashboard 监控 bus 健康度).

    返回字段:
      - published: 总 publish 次数
      - delivered: 成功投递次数
      - dropped_slow_consumer: 因 subscriber queue 满而 drop 的事件数
      - dropped_thread_queue_full: 因 thread_queue 满而 drop 的事件数
      - subscribers: 当前活跃 subscriber 数
      - thread_queue_size: thread_queue 当前堆积量
    """
    from okx.web.backend.events import event_bus
    return {"ok": True, "stats": event_bus.get_stats()}
