#!/usr/bin/env python3
"""OKX Quant Trader — Web Dashboard Backend

Phase 2 endpoints (all read-only or in-memory inference):
- GET  /api/health
- GET  /api/portfolio   active + closed_recent + daily_stats + summary
- GET  /api/cron        heartbeat + last workflow + recent syncs + drift
- POST /api/query       natural-language → portfolio snapshot
                         (Phase 2b: real LLM via api.minimaxi.com if key set;
                          Phase 2a: keyword-routed fallback if no key)

Phase 2c production:
- If frontend/dist/ exists, mount StaticFiles at "/" so single uvicorn
  serves both /api/* and the React bundle on port 18787.

CONSTRAINTS (v1 LOCKED 2026-07-21):
- All GET endpoints are zero-side-effect file reads only.
- POST /api/query has no side effects — no OKX API calls, no writes.
- Drift threshold = 240s (matches MEMORY.md cron P0 lesson, MAX_WAIT_SECONDS).
- file_reader must NOT pipe JSON through head/tail (per 2026-07-21 daily log).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Layout: backend/app.py → okx/web/backend/ → okx/web/ → okx/
WEB_DIR = Path(__file__).resolve().parent         # okx/web/backend
OKX_ROOT = WEB_DIR.parent.parent                  # okx/
FRONTEND_DIR = WEB_DIR.parent / "frontend"        # okx/web/frontend
DIST_DIR = FRONTEND_DIR / "dist"                  # okx/web/frontend/dist
STATE_DIR = OKX_ROOT / "state"

DRIFT_THRESHOLD_SECONDS = 240  # MEMORY.md cron P0 lesson (effb148) → MAX_WAIT_SECONDS

# ─── LLM config (Phase 2b) ──────────────────────────────────────
LLM_BASE_URL = os.environ.get("OKX_WEB_LLM_BASE_URL", "https://api.minimaxi.com")
LLM_ENDPOINT_PATH = os.environ.get(
    "OKX_WEB_LLM_ENDPOINT_PATH", "/anthropic/v1/messages"
)
LLM_MODEL = os.environ.get("OKX_WEB_LLM_MODEL", "MiniMax-M3")
LLM_API_KEY = os.environ.get("OKX_WEB_LLM_API_KEY", "")
LLM_TIMEOUT_SECONDS = float(os.environ.get("OKX_WEB_LLM_TIMEOUT", "30"))
LLM_MAX_TOKENS = int(os.environ.get("OKX_WEB_LLM_MAX_TOKENS", "500"))

logger = logging.getLogger("okx-web")

app = FastAPI(title="OKX Web Dashboard", version="1.2.0")

_DEFAULT_CORS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    # Prod same-origin (no CORS needed). Listed for safety if accessed via 18787.
    "http://127.0.0.1:18787",
    "http://localhost:18787",
]
_extra = os.environ.get("OKX_WEB_CORS_ORIGINS", "")
if _extra:
    _DEFAULT_CORS.extend([o.strip() for o in _extra.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEFAULT_CORS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ───────── helpers ─────────

def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Safe loader. Returns None on missing/invalid JSON.

    Per 2026-07-21 daily log lesson: never wrap this with head/tail/cut.
    """
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None


def _parse_iso(s: Optional[str]) -> Optional[float]:
    if not s or not isinstance(s, str):
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _read_text(path: Path, limit: int = 4096) -> Optional[str]:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return f.read(limit)
    except OSError:
        return None


# ───────── LLM call (Phase 2b) ──────────────────────────────────

async def _call_llm(query: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call MiniMax-M3 (Anthropic-messages API) for natural-language query.

    Returns {"answer": str, "intent": str|None} on success, None on failure.
    Caller falls back to keyword stub on None.
    """
    if not LLM_API_KEY:
        return None

    system_prompt = (
        "你是 OKX 量化交易 dashboard 的 AI 助手。请根据提供的 portfolio 上下文,简洁回答用户的提问。"
        "如果上下文不含答案,直接说不知道,不要编造数据。"
        "用纯文本格式回答(不要 markdown 加粗),数字保留 4 位小数。"
    )
    user_msg = (
        f"User query:\n{query}\n\n"
        f"Portfolio context (JSON):\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2, default=str)}"
    )

    url = f"{LLM_BASE_URL.rstrip('/')}{LLM_ENDPOINT_PATH}"
    headers = {
        "x-api-key": LLM_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": LLM_MODEL,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_msg}],
        "max_tokens": LLM_MAX_TOKENS,
    }

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            r = await client.post(url, headers=headers, json=body)
        if r.status_code != 200:
            logger.warning(
                "[query] LLM upstream non-200: %s body=%s",
                r.status_code, r.text[:500],
            )
            return None
        data = r.json()
        # Anthropic messages API: content is a list of blocks.
        content = data.get("content") or []
        text = ""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text += block.get("text", "")
        if not text:
            return None
        return {"answer": text.strip(), "model": data.get("model", LLM_MODEL)}
    except (httpx.HTTPError, ValueError, KeyError) as e:
        logger.warning("[query] LLM call failed: %s", e)
        return None


# ───────── GET /api/health ─────────

@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "okx-web",
        "version": "1.2.0",
        "phase": "2c-prod",
        "now": datetime.now().astimezone().isoformat(timespec="seconds"),
        "llm": {
            "configured": bool(LLM_API_KEY),
            "model": LLM_MODEL,
            "base": LLM_BASE_URL,
        },
        "paths": {
            "STATE_DIR": str(STATE_DIR),
            "STATE_DIR_exists": STATE_DIR.exists(),
            "DIST_DIR": str(DIST_DIR),
            "DIST_DIR_exists": DIST_DIR.exists(),
        },
    }


# ───────── GET /api/portfolio ─────────

@app.get("/api/portfolio")
async def portfolio() -> Dict[str, Any]:
    pf_path = STATE_DIR / "portfolio.json"
    pf = _load_json(pf_path)
    if pf is None:
        raise HTTPException(
            status_code=503,
            detail=f"portfolio.json missing or invalid at {pf_path}",
        )

    positions = pf.get("positions", [])
    closed = pf.get("closed_positions", [])
    daily = pf.get("daily_stats", {})

    active_slim = [
        {
            "symbol": p.get("symbol"),
            "direction": p.get("direction"),
            "entry_price": p.get("entry_price"),
            "size": p.get("size"),
            "leverage": p.get("leverage"),
            "margin": p.get("margin"),
            "sl_price": p.get("sl_price"),
            "tp_price": p.get("tp_price"),
            "strategy": p.get("strategy"),
            "trigger_strategy": p.get("trigger_strategy"),
            "opened_at": p.get("opened_at"),
            "mark_px_at_sync": p.get("mark_px_at_sync"),
            "mgn_mode": p.get("mgn_mode"),
        }
        for p in positions
    ]
    closed_recent = [
        {
            "symbol": p.get("symbol"),
            "direction": p.get("direction"),
            "entry_price": p.get("entry_price"),
            "size": p.get("size"),
            "leverage": p.get("leverage"),
            "strategy": p.get("strategy"),
            "closed_at": p.get("closed_at"),
            "realized_pnl": p.get("realized_pnl"),
            "close_source": p.get("close_source"),
        }
        for p in closed[-20:]
    ]
    total_margin_used = sum((p.get("margin") or 0) for p in positions)

    return {
        "updated_at": pf.get("updated_at"),
        "version": pf.get("version"),
        "active_count": len(active_slim),
        "closed_count": len(closed),
        "daily_stats": daily,
        "summary": {
            "total_margin_used": round(total_margin_used, 4),
            "daily_pnl": daily.get("total_pnl"),
            "daily_trades": daily.get("total_trades"),
            "consecutive_losses": daily.get("consecutive_losses"),
            "emergency_stop": daily.get("emergency_stop_triggered", False),
        },
        "active": active_slim,
        "closed_recent": closed_recent,
    }


# ───────── GET /api/cron ─────────

@app.get("/api/cron")
async def cron_status() -> Dict[str, Any]:
    hb = _load_json(STATE_DIR / "signal_runner.heartbeat") or {}
    last_wf = _load_json(STATE_DIR / "last_workflow_result.json") or {}
    sync_hist = _load_json(STATE_DIR / "sync_history.json") or []

    boundary_ts = _parse_iso(hb.get("boundary"))
    last_run_ts = _parse_iso(hb.get("last_run_at"))
    drift_seconds: Optional[float] = None
    if boundary_ts is not None and last_run_ts is not None:
        drift_seconds = round(last_run_ts - boundary_ts, 2)
    drift_fallback_used = (
        drift_seconds is not None and drift_seconds > DRIFT_THRESHOLD_SECONDS
    )

    probe_dir = STATE_DIR / "health_probe"
    probe_files: List[str] = []
    if probe_dir.exists() and probe_dir.is_dir():
        probe_files = sorted(p.name for p in probe_dir.iterdir() if p.is_file())
    probe_log_text = (
        _read_text(probe_dir / "probe.log", limit=4096)
        if "probe.log" in probe_files
        else None
    )

    return {
        "now": datetime.now().astimezone().isoformat(timespec="seconds"),
        "drift": {
            "threshold_seconds": DRIFT_THRESHOLD_SECONDS,
            "drift_seconds": drift_seconds,
            "fallback_used": drift_fallback_used,
            "boundary": hb.get("boundary"),
            "last_run_at": hb.get("last_run_at"),
        },
        "heartbeat": {
            "last_run_at": hb.get("last_run_at"),
            "timeframe": hb.get("timeframe"),
            "warmup_ms": hb.get("warmup_ms"),
            "signal_triggered": hb.get("signal_triggered"),
            "errors_count": hb.get("errors_count"),
        },
        "last_workflow": {
            "success": last_wf.get("success"),
            "open_tick": last_wf.get("open_results", {}).get("tick"),
            "signal_triggered": last_wf.get("open_results", {}).get("signal_triggered"),
            "reconcile": last_wf.get("open_results", {}).get("reconcile"),
            "errors": last_wf.get("open_results", {}).get("errors"),
            "timestamp": last_wf.get("open_results", {}).get("timestamp"),
        },
        "recent_syncs": sync_hist[-10:] if isinstance(sync_hist, list) else [],
        "health_probe": {
            "files": probe_files,
            "probe_log_text": probe_log_text,
        },
    }


# ───────── POST /api/query ─────────

class QueryIn(BaseModel):
    query: str


def _keyword_route(query: str, active: list, daily: Dict[str, Any]) -> Dict[str, Any]:
    """Phase 2a keyword-routed fallback when LLM not configured or fails."""
    text_lower = query.lower()
    if "btc" in text_lower or "比特币" in query:
        intent = "btc_positions"
        btc = [p for p in active if (p.get("symbol") or "").startswith("BTC")]
        if btc:
            syms = ", ".join((p.get("symbol") or "?") for p in btc)
            answer = f"找到 {len(btc)} 笔 BTC 仓位:{syms}"
        else:
            answer = "当前无 BTC 仓位"
        extras: Dict[str, Any] = {"positions": btc}
    elif "eth" in text_lower or "以太" in query:
        intent = "eth_positions"
        eth = [p for p in active if (p.get("symbol") or "").startswith("ETH")]
        syms = ", ".join((p.get("symbol") or "?") for p in eth)
        answer = f"当前有 {len(eth)} 笔 ETH 仓位:{syms}" if eth else "当前无 ETH 仓位"
        extras = {"positions": eth}
    elif "pnl" in text_lower or "盈亏" in query or "profit" in text_lower:
        intent = "daily_pnl"
        pnl = daily.get("total_pnl")
        trades = daily.get("total_trades")
        answer = f"今日 PnL: {pnl} USDT,trades={trades}"
        extras = {"daily_stats": daily}
    elif "策略" in query or "strategy" in text_lower:
        intent = "strategies"
        strat_count: Dict[str, int] = {}
        for p in active:
            s = p.get("strategy") or "UNKNOWN"
            strat_count[s] = strat_count.get(s, 0) + 1
        if strat_count:
            answer = "; ".join(f"{k}={v}" for k, v in strat_count.items())
        else:
            answer = "无 active 仓位"
        extras = {"by_strategy": strat_count}
    elif "持仓" in query or "position" in text_lower:
        intent = "all_positions"
        answer = f"当前 {len(active)} 笔 active 仓位"
        extras = {"positions": active}
    else:
        intent = "fallback_stub"
        answer = (
            f"[Phase 2a stub] 收到 query '{query}' 但未匹配关键词(BTC/ETH/PnL/策略/持仓)。"
            "Phase 2b 接入 LLM 后可支持自然语言理解。"
        )
        extras = {"hint": "Phase 2a 支持: BTC / ETH / PnL / 策略 / 关键词"}
    return {"intent": intent, "answer": answer, "extras": extras}


@app.post("/api/query")
async def query(req: QueryIn) -> Dict[str, Any]:
    """Natural-language → portfolio snapshot (Phase 2b: LLM with stub fallback)."""
    text = (req.query or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="query is required")

    pf = _load_json(STATE_DIR / "portfolio.json")
    if pf is None:
        raise HTTPException(status_code=503, detail="portfolio.json not available")
    active = pf.get("positions", [])
    daily = pf.get("daily_stats", {})

    # ── Try Phase 2b LLM path if key configured ──
    if LLM_API_KEY:
        ctx = {
            "active_positions": active,
            "closed_recent_tail": pf.get("closed_positions", [])[-5:],
            "daily_stats": daily,
            "updated_at": pf.get("updated_at"),
        }
        llm_result = await _call_llm(text, ctx)
        if llm_result:
            return {
                "ok": True,
                "intent": "llm_v2b",
                "query": text,
                "answer": llm_result["answer"],
                "extras": {
                    "source": "llm",
                    "model": llm_result.get("model", LLM_MODEL),
                },
                "version": "1.2.0-phase2b",
            }
        # LLM failed → fall through to stub with note.

    # ── Phase 2a keyword stub (fallback) ──
    routed = _keyword_route(text, active, daily)
    extras = dict(routed["extras"])
    if LLM_API_KEY:
        # Key set but LLM failed — annotate.
        extras["llm_fallback_note"] = (
            "OKX_WEB_LLM_API_KEY configured but LLM call failed; "
            "returned keyword-routed fallback."
        )
    return {
        "ok": True,
        "intent": routed["intent"],
        "query": text,
        "answer": routed["answer"],
        "extras": extras,
        "version": "1.2.0-phase2a-stub",
    }


# ───────── Phase 2c: serve static bundle in prod ─────────
# Mount AFTER all routes so /api/* takes precedence over StaticFiles catch-all.

if DIST_DIR.exists() and DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="static")
    logger.info("[okx-web] mounted StaticFiles at / from %s", DIST_DIR)
else:
    logger.info(
        "[okx-web] %s not found — running API-only (Vite dev mode expected)",
        DIST_DIR,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=os.environ.get("OKX_WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("OKX_WEB_PORT", "18787")),
        reload=False,   # prod: no reload (systemd manages restarts)
    )
