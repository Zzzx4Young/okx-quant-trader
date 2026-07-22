#!/usr/bin/env python3
"""OKX Quant Trader — Web Dashboard Backend

v1.3 endpoints (2026-07-22):
- GET  /api/health
- GET  /api/portfolio   active + closed_recent + daily_stats + summary + risk_metrics
- GET  /api/cron        heartbeat + last workflow + recent syncs + drift (3-state)
- POST /api/query       natural-language → portfolio snapshot
                         (Phase 2b: real LLM via api.minimaxi.com if key set;
                          Phase 2a: keyword-routed fallback if no key)

Production:
- Single uvicorn on 127.0.0.1:18787 serves /api/* + React bundle from
  frontend/dist/ (mounted via StaticFiles when dist/ exists).

v1.3 ARCHITECTURAL CHANGE (Nixil approved 2026-07-22):
- /api/portfolio now reads OKX V5 GET endpoints to compute risk_metrics
  (equity, notional, concentration, min liq distance). 60s file cache at
  state/risk_metrics_cache.json.
- v1 LOCKED "zero-side-effect file reads only" principle SUPERSEDED for
  /api/portfolio — see WEB_DASHBOARD_DESIGN.md §10 (v1.3 changelog).
- All other endpoints unchanged.

CONSTRAINTS:
- All OKX calls are GET-only (read-only). No orders, no position changes.
- Local cache writes are bounded (60s TTL, single file).
- Drift threshold = 240s (matches MEMORY.md cron P0 lesson, MAX_WAIT_SECONDS).
- file_reader must NOT pipe JSON through head/tail (per 2026-07-21 daily log).
- POST /api/query has no side effects on OKX — may invoke external LLM.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

app = FastAPI(title="OKX Web Dashboard", version="1.3.0")

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


# ───────── OKX V5 client (2026-07-22 · F: portfolio risk metrics) ─────────
# Reads equity + positions from OKX to compute:
#   - equity_usd, gross/net_notional_usd, gross/net_leverage
#   - inst_concentration, strategy_concentration, min_liq_distance_pct
# Read-only OKX GETs + 60s file cache. Graceful degradation if creds missing.

OKX_API_BASE = "https://www.okx.com"
RISK_METRICS_TTL_SECONDS = 60
RISK_METRICS_CACHE_FILE = STATE_DIR / "risk_metrics_cache.json"

# ─── Cron jobs snapshot (2026-07-22 · H6: expose OpenClaw cron state) ───
# `openclaw cron list --json` returns full job state (name, schedule, payload,
# delivery, lastRunAtMs/lastRunStatus/lastDurationMs/state.consecutiveErrors,
# nextRunAtMs). Each job's "最近一次执行的结果" lives here — no need to call
# `cron runs --id` per job (would add 7 subprocesses for 6 jobs).
CRON_CACHE_TTL_SECONDS = 60
CRON_CACHE_FILE = STATE_DIR / "cron_cache.json"
OPENCLAW_BIN = shutil.which("openclaw") or "/home/zzzx47/.npm-global/bin/openclaw"
# nvm-managed node binary — systemd PATH doesn't include it, so #!/usr/bin/env
# node in the openclaw script fails. Invoke node directly, bypassing shebang.
NODE_BIN = (
    shutil.which("node")
    or "/home/zzzx47/.nvm/versions/node/v22.23.1/bin/node"
)


def _okx_creds() -> Optional[Dict[str, Any]]:
    """Read OKX API credentials from env. Picks LIVE_ vs DEMO_ based on OKX_TRADING_MODE.

    Returns None if creds incomplete (graceful: backend still serves portfolio, just no metrics).
    """
    mode = os.environ.get("OKX_TRADING_MODE", "demo").lower()
    if mode == "live":
        key = os.environ.get("OKX_LIVE_API_KEY")
        secret = os.environ.get("OKX_LIVE_API_SECRET")
        passphrase = os.environ.get("OKX_LIVE_PASSPHRASE")
        is_demo = False
    else:
        key = os.environ.get("OKX_DEMO_API_KEY")
        secret = os.environ.get("OKX_DEMO_API_SECRET")
        passphrase = os.environ.get("OKX_DEMO_PASSPHRASE")
        is_demo = True
    missing = [
        name for name, val in (
            ("OKX_DEMO_API_KEY" if is_demo else "OKX_LIVE_API_KEY", key),
            ("OKX_DEMO_API_SECRET" if is_demo else "OKX_LIVE_API_SECRET", secret),
            ("OKX_DEMO_PASSPHRASE" if is_demo else "OKX_LIVE_PASSPHRASE", passphrase),
        ) if not val
    ]
    if missing:
        logger.warning(
            "OKX creds incomplete (mode=%s, missing=%s). risk_metrics will be unavailable. "
            "Hint: run-prod.sh sources ../.env; verify OKX_TRADING_MODE + OKX_DEMO_* are set.",
            mode, missing,
        )
        return None
    return {"key": key, "secret": secret, "passphrase": passphrase, "is_demo": is_demo}


def _okx_sign(timestamp: str, method: str, path: str, body: str, secret: str) -> str:
    msg = f"{timestamp}{method.upper()}{path}{body}"
    mac = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("utf-8")


def _okx_get(path: str) -> Optional[Dict[str, Any]]:
    """Authenticated GET to OKX V5. Returns parsed JSON on success, None on failure.

    Retries up to 3 times on transient network errors (SSL EOF / connection reset /
    read timeout). OKX endpoint commonly hits SSL EOF on cold connections; per
    OpenClaw runtime note 2026-07-22, auto-retry succeeds. Hard API errors
    (code != "0") do not retry — caller decides whether to surface.
    """
    creds = _okx_creds()
    if creds is None:
        return None
    # OKX V5 expects `YYYY-MM-DDTHH:mm:ss.SSSZ` (Zulu, not +00:00).
    # Python's isoformat produces +00:00, which differs at the byte level
    # → signature mismatch → 401. Match OKX format exactly.
    _now = datetime.now(timezone.utc)
    ts = _now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{_now.microsecond // 1000:03d}Z"
    sig = _okx_sign(ts, "GET", path, "", creds["secret"])
    headers = {
        "OK-ACCESS-KEY": creds["key"],
        "OK-ACCESS-SIGN": sig,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": creds["passphrase"],
        "Content-Type": "application/json",
    }
    if creds["is_demo"]:
        headers["x-simulated-trading"] = "1"

    transient_errors = (
        httpx.RemoteProtocolError,
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.ConnectTimeout,
    )
    last_err: Optional[Exception] = None
    for attempt in range(1, 4):  # 1, 2, 3
        try:
            r = httpx.get(f"{OKX_API_BASE}{path}", headers=headers, timeout=10.0)
            r.raise_for_status()
            data = r.json()
            if data.get("code") == "0":
                if attempt > 1:
                    logger.info("OKX %s succeeded on attempt %d", path, attempt)
                return data
            logger.warning(
                "OKX %s API error code=%s msg=%s (no retry)",
                path, data.get("code"), data.get("msg"),
            )
            return None
        except transient_errors as e:
            last_err = e
            logger.warning(
                "OKX %s transient error attempt %d/3: %s",
                path, attempt, type(e).__name__,
            )
            if attempt < 3:
                import time as _t
                _t.sleep(0.5 * (2 ** (attempt - 1)))  # 0.5s, 1.0s
        except Exception as e:
            logger.warning("OKX %s unexpected error: %s", path, e)
            return None
    logger.error("OKX %s failed after 3 attempts: %s", path, last_err)
    return None


def _load_risk_cache() -> Optional[Dict[str, Any]]:
    return _load_json(RISK_METRICS_CACHE_FILE)


def _save_risk_cache(payload: Dict[str, Any]) -> None:
    try:
        RISK_METRICS_CACHE_FILE.write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        logger.warning("Failed to save risk metrics cache: %s", e)


def _compute_risk_metrics(
    balance_data: List[Dict[str, Any]],
    positions_data: List[Dict[str, Any]],
    strategy_by_inst: Dict[str, str],
) -> Dict[str, Any]:
    """Pure compute: balance + OKX positions + strategy lookup → metrics dict.

    Args:
        balance_data: OKX /api/v5/account/balance response 'data' array.
        positions_data: OKX /api/v5/account/positions?instType=SWAP response 'data' array.
        strategy_by_inst: {normalized_inst_id: strategy_name} from local portfolio.json.
    """
    # Equity + account-level IMR + total unrealized PnL from balance endpoint.
    # Note: ?ccy=USDT returns ONE account-level entry in data[] (no top-level
    # 'ccy' field on the entry itself). USDT lives in entry.details[]. So we
    # iterate data[0] directly without checking b.get("ccy") == "USDT".
    equity = 0.0
    account_used_margin: float = 0.0
    unrealized_pnl: float = 0.0
    if balance_data:
        b = balance_data[0]
        v = b.get("totalEq")
        if v not in (None, ""):
            try:
                equity = float(v)
            except (ValueError, TypeError):
                pass
        for d in b.get("details", []) or []:
            if (d.get("ccy") or "").upper() == "USDT":
                for src_field, dst in (("imr", "account_used_margin"), ("upl", "unrealized_pnl")):
                    v2 = d.get(src_field)
                    if v2 not in (None, ""):
                        try:
                            if dst == "account_used_margin":
                                account_used_margin = float(v2)
                            else:
                                unrealized_pnl = float(v2)
                        except (ValueError, TypeError):
                            pass

    # Per-position notional + liq distance, joined with local strategy.
    margin_used_total: float = 0.0
    unrealized_pnl_per_position: Dict[str, float] = {}
    inst_totals: Dict[str, float] = {}
    strat_totals: Dict[str, float] = {}
    gross_notional = 0.0
    net_notional = 0.0
    min_liq_pct: Optional[float] = None
    min_liq_symbol: Optional[str] = None

    def _f(v: Any) -> float:
        if v is None or v == "":
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0

    for p in positions_data:
        size = _f(p.get("pos"))  # signed (+long, -short)
        ct_val = _f(p.get("ctVal"))
        mark_px = _f(p.get("markPx"))
        # liqPx is empty string "" for cross-margin positions (account-level
        # liquidation, no per-position liq px). Match risk_monitor pattern:
        # _safe_float(..., default=0.0) or None  → None means skip liq calc.
        _raw_liq = p.get("liqPx")
        try:
            liq_px = float(_raw_liq) if _raw_liq not in (None, "") else None
        except (ValueError, TypeError):
            liq_px = None
        inst_id = (p.get("instId") or "").upper().replace("-", "")
        if size == 0:
            continue
        # Prefer OKX-provided notionalUsd (more accurate, handles all cases).
        # Fall back to |pos| * ctVal * markPx only if notionalUsd is missing.
        okx_notional = _f(p.get("notionalUsd"))
        if okx_notional > 0:
            notional = okx_notional
        elif ct_val > 0 and mark_px > 0:
            notional = abs(size) * ct_val * mark_px
        else:
            continue
        gross_notional += notional
        net_notional += size * ct_val * mark_px  # signed notional (signed)
        inst_totals[inst_id] = inst_totals.get(inst_id, 0.0) + notional
        strategy = strategy_by_inst.get(inst_id, "UNKNOWN")
        strat_totals[strategy] = strat_totals.get(strategy, 0.0) + notional
        if liq_px is not None and mark_px > 0:
            liq_pct = abs(mark_px - liq_px) / mark_px
            if min_liq_pct is None or liq_pct < min_liq_pct:
                min_liq_pct = liq_pct
                min_liq_symbol = p.get("instId")
        # Per-position margin (live from OKX). For cross-margin accounts OKX
        # returns per-position margin=0 (margin is account-level). Sum then
        # understates true used margin for cross positions — but still more
        # accurate than stale local portfolio.json (had 3248 USDT for ~353 USDT
        # notional). Future: query /api/v5/account/balance for account-level.
        margin_used_total += _f(p.get("margin"))
        # Per-position unrealized PnL (upl field). Surfaced to /api/portfolio
        # so frontend Active Positions table can show per-position uPnL.
        _raw_upl = p.get("upl")
        _upl_val: Optional[float] = None
        if _raw_upl not in (None, ""):
            try:
                _upl_val = float(_raw_upl)
            except (ValueError, TypeError):
                _upl_val = None
        if _upl_val is not None:
            unrealized_pnl_per_position[inst_id] = _upl_val

    # Concentration: largest single contributor / total.
    top_inst_id, top_inst_val = (
        max(inst_totals.items(), key=lambda kv: kv[1]) if inst_totals else (None, 0.0)
    )
    top_strat, top_strat_val = (
        max(strat_totals.items(), key=lambda kv: kv[1]) if strat_totals else (None, 0.0)
    )
    inst_conc = (top_inst_val / gross_notional) if gross_notional > 0 else 0.0
    strat_conc = (top_strat_val / gross_notional) if gross_notional > 0 else 0.0

    return {
        "equity_usd": round(equity, 4),
        "gross_notional_usd": round(gross_notional, 4),
        "net_notional_usd": round(net_notional, 4),
        "gross_leverage": round(gross_notional / equity, 6) if equity > 0 else 0.0,
        "net_leverage": round(abs(net_notional) / equity, 6) if equity > 0 else 0.0,
        "margin_used_usd": round(margin_used_total, 4),
        "account_used_margin_usd": round(account_used_margin, 4),
        "unrealized_pnl_usd": round(unrealized_pnl, 4),
        "unrealized_pnl_per_position": {k: round(v, 4) for k, v in unrealized_pnl_per_position.items()},
        "inst_concentration": round(inst_conc, 6),
        "inst_concentration_symbol": top_inst_id,
        "strategy_concentration": round(strat_conc, 6),
        "strategy_concentration_name": top_strat,
        "min_liq_distance_pct": round(min_liq_pct, 6) if min_liq_pct is not None else None,
        "min_liq_distance_symbol": min_liq_symbol,
    }


def _fetch_risk_metrics(strategy_by_inst: Dict[str, str]) -> Dict[str, Any]:
    """Fetch+cache risk metrics. source ∈ {okx_live, cache_fresh, cache_stale, unavailable}.

    Strategy:
      1. Try cache: if <60s old → cache_fresh
      2. Else fetch OKX balance + positions
      3. If fetch ok → compute + save + return okx_live
      4. If fetch failed but cache exists → cache_stale (with old data)
      5. If fetch failed and no cache → unavailable
    """
    now = datetime.now(timezone.utc)
    cache = _load_risk_cache()
    cache_data = cache.get("data") if cache else None
    cache_fetched = cache.get("fetched_at") if cache else None

    if cache_data and cache_fetched:
        try:
            ts = datetime.fromisoformat(cache_fetched.replace("Z", "+00:00"))
            if (now - ts).total_seconds() < RISK_METRICS_TTL_SECONDS:
                return {**cache_data, "source": "cache_fresh"}
        except (ValueError, TypeError):
            pass

    balance = _okx_get("/api/v5/account/balance?ccy=USDT")
    positions = _okx_get("/api/v5/account/positions?instType=SWAP")

    if balance is None or positions is None:
        if cache_data:
            return {**cache_data, "source": "cache_stale"}
        return {"source": "unavailable", "error": "OKX API failed and no cache"}

    metrics = _compute_risk_metrics(
        balance.get("data", []) or [],
        positions.get("data", []) or [],
        strategy_by_inst,
    )
    _save_risk_cache({"data": metrics, "fetched_at": now.isoformat()})
    return {**metrics, "source": "okx_live"}

def _fetch_cron_snapshot() -> Dict[str, Any]:
    """Fetch+cache cron jobs from OpenClaw scheduler via CLI subprocess.

    Source ∈ {okx_live, cache_fresh, cache_stale, unavailable}.
    Caches 60s to avoid hammering openclaw CLI on every 10s poll.
    Returns dict with "jobs" (list of cron job state) + "source" (string).
    """
    cache = _load_json(CRON_CACHE_FILE)
    now = datetime.now(timezone.utc)
    if cache and cache.get("fetched_at"):
        try:
            ts = datetime.fromisoformat(cache["fetched_at"].replace("Z", "+00:00"))
            if (now - ts).total_seconds() < CRON_CACHE_TTL_SECONDS:
                return {
                    "jobs": cache.get("jobs", []),
                    "source": "cache_fresh",
                }
        except (ValueError, TypeError):
            pass

    try:
        r = subprocess.run(
            [NODE_BIN, OPENCLAW_BIN, "cron", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            logger.warning("openclaw cron list failed: rc=%s stderr=%s", r.returncode, r.stderr[:200])
            if cache and cache.get("jobs"):
                return {"jobs": cache["jobs"], "source": "cache_stale"}
            return {"jobs": [], "source": "unavailable", "error": f"openclaw rc={r.returncode}"}
        jobs = json.loads(r.stdout).get("jobs", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        logger.warning("openclaw cron list error: %s", e)
        if cache and cache.get("jobs"):
            return {"jobs": cache["jobs"], "source": "cache_stale"}
        return {"jobs": [], "source": "unavailable", "error": str(e)}

    # Enrich each job with its last-run summary (the human-readable "result
    # content" the user wants to see). Per-job subprocess; cached together
    # with the job list for 60s. 6 subprocesses × ~100ms = ~600ms total.
    for job in jobs:
        try:
            r2 = subprocess.run(
                [NODE_BIN, OPENCLAW_BIN, "cron", "runs", "--id", job["id"]],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r2.returncode != 0:
                job["last_run_summary"] = None
                continue
            entries = json.loads(r2.stdout).get("entries", [])
            if entries:
                last = entries[0]  # newest first
                summary = last.get("summary", "") or ""
                # Truncate to 1500 chars to keep payload manageable;
                # full text still readable in dashboard via expand (future).
                if len(summary) > 1500:
                    summary = summary[:1500] + "\n\n[…truncated]"
                job["last_run_summary"] = summary
                job["last_run_at"] = last.get("tsIso") or last.get("ts")
                job["last_run_duration_ms"] = last.get("durationMs")
                job["last_run_model"] = last.get("model")
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            logger.warning("cron runs --id %s failed: %s", job.get("id"), e)
            job["last_run_summary"] = None

    _save_json_cache(CRON_CACHE_FILE, {"jobs": jobs, "fetched_at": now.isoformat()})
    return {"jobs": jobs, "source": "okx_live"}


def _save_json_cache(path: Path, payload: Dict[str, Any]) -> None:
    """Write JSON cache file; ignore errors (transparent cache write)."""
    try:
        path.write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        logger.warning("Failed to write cache %s: %s", path, e)


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
        "version": "1.3.0",
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

    # Risk metrics (F: 2026-07-22): equity + concentration + liq distance.
    # Builds strategy lookup from local portfolio.json (OKX API doesn't return strategy).
    strategy_by_inst: Dict[str, str] = {}
    for p in positions:
        sym = (p.get("symbol") or "").upper().replace("-", "")
        strat = p.get("strategy") or "UNKNOWN"
        if sym:
            strategy_by_inst[sym] = strat
    risk_metrics = _fetch_risk_metrics(strategy_by_inst)

    # Enrich active positions with live OKX unrealized PnL (G5: 2026-07-22).
    # upl_per_position maps normalized inst_id (BTCUSDTSWAP) → upl USDT.
    _upl_map = risk_metrics.get("unrealized_pnl_per_position", {}) or {}
    for slot in active_slim:
        sym_norm = (slot.get("symbol") or "").upper().replace("-", "")
        if sym_norm in _upl_map:
            slot["unrealized_pnl_usd"] = _upl_map[sym_norm]

    # Margin (P0 fix 2026-07-22): prefer live OKX over stale local portfolio.json.
    # Local margin was 3248 USDT (wrong) for ~353 USDT notional — portfolio.json
    # margin field didn't update on size_mismatch_replace syncs. Live OKX is
    # same source as risk_metrics (consistency) + reflects current state.
    # Fallback: when OKX unavailable, use local sum with explicit "stale" marker.
    if risk_metrics.get("account_used_margin_usd") is not None and risk_metrics.get("source") != "unavailable":
        margin_used = risk_metrics["account_used_margin_usd"]
        _src = risk_metrics["source"]
        margin_source = f"{_src}_imr"
    elif risk_metrics.get("margin_used_usd") is not None and risk_metrics.get("source") != "unavailable":
        margin_used = risk_metrics["margin_used_usd"]
        _src = risk_metrics["source"]
        margin_source = f"{_src}_per_pos_sum"
    else:
        margin_used = total_margin_used  # local fallback
        margin_source = "local_sync_stale"

    return {
        "updated_at": pf.get("updated_at"),
        "version": pf.get("version"),
        "active_count": len(active_slim),
        "closed_count": len(closed),
        "daily_stats": daily,
        "summary": {
            "total_margin_used": round(margin_used, 4),
            "margin_source": margin_source,
            "unrealized_pnl": risk_metrics.get("unrealized_pnl_usd"),
            "daily_pnl": daily.get("total_pnl"),
            "daily_trades": daily.get("total_trades"),
            "consecutive_losses": daily.get("consecutive_losses"),
            "emergency_stop": daily.get("emergency_stop_triggered", False),
        },
        "risk_metrics": risk_metrics,
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
    drift_status: str = "unknown"  # "unknown" | "on_time" | "early" | "late"
    drift_fallback_used: bool = False
    if boundary_ts is not None and last_run_ts is not None:
        drift_seconds = round(last_run_ts - boundary_ts, 2)
        # |drift| > threshold means runner skipped spinlock (either side):
        #   drift < -threshold → ran WAY BEFORE boundary (wait too long → fallback)
        #   drift >  threshold → ran WAY AFTER  boundary (boundary passed → fallback)
        # 2026-07-22 fix (E): previous `drift > threshold` missed early-side
        # fallback (real case: last_run 20:02 vs boundary 21:00 → drift=-3448).
        if abs(drift_seconds) > DRIFT_THRESHOLD_SECONDS:
            drift_fallback_used = True
            drift_status = "late" if drift_seconds > 0 else "early"
        else:
            drift_fallback_used = False
            drift_status = "on_time"

    probe_dir = STATE_DIR / "health_probe"
    probe_files: List[str] = []
    if probe_dir.exists() and probe_dir.is_dir():
        probe_files = sorted(p.name for p in probe_dir.iterdir() if p.is_file())
    probe_log_text = (
        _read_text(probe_dir / "probe.log", limit=4096)
        if "probe.log" in probe_files
        else None
    )

    # Cron jobs snapshot (H6: 2026-07-22): scheduled tasks + last execution.
    cron_snapshot = _fetch_cron_snapshot()

    return {
        "now": datetime.now().astimezone().isoformat(timespec="seconds"),
        "drift": {
            "threshold_seconds": DRIFT_THRESHOLD_SECONDS,
            "drift_seconds": drift_seconds,
            "drift_status": drift_status,
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
        "cron_jobs": cron_snapshot.get("jobs", []),
        "cron_source": cron_snapshot.get("source", "unavailable"),
        "cron_error": cron_snapshot.get("error"),
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
                "version": "1.3.0-phase2b",
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
        "version": "1.3.0-phase2a-stub",
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
