#!/usr/bin/env python3
"""portfolio ↔ OKX 手动对账工具

按 OKX 真实持仓强制对齐本地 portfolio：

  - 本地有 / OKX 没有  → 视为外部平仓，归档到 closed_positions，记录 realized_pnl
  - 本地无 / OKX 有   → 新增到 positions，按当前 markPx + 推算 SL/TP 写入
  - 两边都有         → 不动（如果不是同一笔则报警）

用法：
  bash run.sh scripts/sync_portfolio.py [--dry-run] [--reason "..."]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from okx.code.client import OKXClient  # noqa


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _load(path: Path) -> Dict:
    with open(path) as f:
        return json.load(f)


def _save(path: Path, data: Dict) -> None:
    data["updated_at"] = _now_iso()
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _normalize_local_symbol(raw: str) -> str:
    """去掉横杠、统一后缀、得到 "BTC" / "ETH" / base symbol。OKX instId 在主流程构造。"""
    s = raw.upper().replace("-", "").replace("/", "").replace("_", "")
    for suffix in ("SWAP", "PERPETUAL", "PERP"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s


def _extract_close_avg(
    positions_history: List[Dict],
    local_pos: Dict,
) -> Dict[str, Any]:
    """从 positions-history 中找出对应 local_pos 的平仓价 / realizedPnl。

    匹配优先级：
      1. posId 直接匹配（system 开的仓有 order_id == posId）
      2. instId + posSide 匹配（web_manual / 外部开仓）
      3. instId + 反向 posSide 匹配（兜底）
    """
    inst_norm = (local_pos.get("symbol") or "").replace("USDTSWAP", "-USDT-SWAP")
    pos_side = "long" if local_pos.get("direction") == "long" else "short"
    order_id = local_pos.get("order_id", "")

    # 1) posId 精确
    if order_id and order_id != "web_manual":
        for p in positions_history:
            if p.get("posId") == order_id:
                return _format_close(p)

    # 2) instId + posSide
    for p in positions_history:
        if p.get("instId") == inst_norm and p.get("posSide") == pos_side:
            return _format_close(p)

    # 3) 兜底：相同 instId
    for p in positions_history:
        if p.get("instId") == inst_norm:
            return _format_close(p)
    return {}


def _format_close(p: Dict) -> Dict[str, Any]:
    return {
        "close_avg_px": _safe_float(p.get("closeAvgPx")),
        "realized_pnl": _safe_float(p.get("realizedPnl")),
        "pnl": _safe_float(p.get("pnl")),
        "fee": _safe_float(p.get("fee")),
        "u_time": int(p.get("uTime", 0)) / 1000.0 if p.get("uTime") else None,
        "c_time": int(p.get("cTime", 0)) / 1000.0 if p.get("cTime") else None,
        "matched_by": f"history:{p.get('instId')}/{p.get('posSide')}",
    }


def _synthesize_sl_tp(entry: float, side: str, sl_pct: float = 0.003, rr: float = 1.5) -> Dict[str, float]:
    """按 Constitution 默认 0.3% 止损 + 1.5R 推荐 SL/TP。

    long : SL = entry * (1 - sl_pct) ; TP = entry * (1 + sl_pct * rr)
    short: SL = entry * (1 + sl_pct) ; TP = entry * (1 - sl_pct * rr)
    """
    sl_distance = entry * sl_pct
    if side == "long":
        sl = entry - sl_distance
        tp = entry + sl_distance * rr
    else:  # short → SL 在上方，TP 在下方
        sl = entry + sl_distance
        tp = entry - sl_distance * rr
    return {"sl_price": round(sl, 4), "tp_price": round(tp, 4)}


def reconcile(
    local: Dict,
    okx_positions: List[Dict],
    dry_run: bool = False,
    now_str: Optional[str] = None,
    okx_history_provider=None,
    ct_val_by_inst: Optional[Dict[str, float]] = None,
) -> Dict:
    """核心对账逻辑。

    返回结构：
      {
        "drift_detected": bool,
        "actions": [str, ...],
        "ghost_closed": [...],   # 写入 closed_positions
        "new_synced":   [...],   # 写入 positions
        "matched":      [...],
        "mismatched":   [...],   # 同 inst 但方向/size 不一致
      }
    """
    now_str = now_str or _now_iso()
    today = _today()
    ct_val_by_inst = ct_val_by_inst or {}
    local_positions = local.get("positions", [])
    okx_by_inst_side = {(p.get("instId"), p.get("posSide")): p for p in okx_positions}

    actions: List[str] = []
    ghost_closed: List[Dict] = []
    new_synced: List[Dict] = []
    matched: List[Dict] = []
    mismatched: List[Dict] = []

    daily = local.setdefault("daily_stats", {
        "date": today, "total_trades": 0, "loss_trades": 0,
        "consecutive_losses": 0, "total_pnl": 0.0,
        "total_fee": 0.0, "total_pnl_gross": 0.0,
        "last_loss_at": None, "emergency_stop_triggered": False,
    })

    # ── 1. 处理本地有 / OKX 无 → 归档 ──
    survivors: List[Dict] = []
    for lp in local_positions:
        norm = _normalize_local_symbol(lp.get("symbol", ""))
        if norm.endswith("USDT") and len(norm) > 4:
            norm_inst = f"{norm[:-4]}-USDT-SWAP"
        else:
            norm_inst = lp.get("symbol", "")
        pos_side = "long" if lp.get("direction") == "long" else "short"
        key = (norm_inst, pos_side)

        if key not in okx_by_inst_side:
            # 本地有，OKX 无 → 归档为已平仓
            order_id = lp.get("order_id", "")
            close_info = _extract_close_avg(
                okx_history_provider() if okx_history_provider else [],
                lp,
            )

            realized = close_info.get("realized_pnl", 0.0) if close_info.get("realized_pnl") is not None else 0.0
            closed = dict(lp)
            closed["closed_at"] = now_str
            closed["realized_pnl"] = realized
            closed["close_source"] = "external_close_detected_by_sync"
            closed["close_meta"] = close_info

            local.setdefault("closed_positions", []).append(closed)
            ghost_closed.append(closed)
            actions.append(
                f"ghost → closed: {lp.get('symbol')} {lp.get('direction')} "
                f"order_id={order_id} realized_pnl={realized}"
            )

            # 更新 daily stats（如果是今天平的）
            close_dt = close_info.get("u_time")
            if close_dt:
                close_date = datetime.fromtimestamp(close_dt).strftime("%Y-%m-%d")
            else:
                close_date = today

            if close_date == daily.get("date") or close_date == today:
                # daily date 需要跨日对齐
                if daily.get("date") != today and close_date == today:
                    daily["date"] = today
                    daily["total_trades"] = 0
                    daily["loss_trades"] = 0
                    daily["consecutive_losses"] = 0
                    daily["total_pnl"] = 0.0
                    daily["total_fee"] = 0.0
                    daily["total_pnl_gross"] = 0.0
                    daily["last_loss_at"] = None
                    daily["emergency_stop_triggered"] = False
                daily["total_trades"] = daily.get("total_trades", 0) + 1
                if realized < 0:
                    daily["loss_trades"] = daily.get("loss_trades", 0) + 1
                    daily["consecutive_losses"] = daily.get("consecutive_losses", 0) + 1
                    daily["last_loss_at"] = now_str
                else:
                    daily["consecutive_losses"] = 0
                daily["total_pnl"] = round(daily.get("total_pnl", 0.0) + realized, 6)
                daily["total_pnl_gross"] = round(daily.get("total_pnl_gross", 0.0) + realized, 6)
                if close_info.get("fee") is not None:
                    daily["total_fee"] = round(daily.get("total_fee", 0.0) + close_info["fee"], 6)
        else:
            # 本地有，OKX 也有 → 检查 size / direction 一致
            okx_p = okx_by_inst_side[key]
            lp_sz = _safe_float(lp.get("size"))
            okx_sz = abs(_safe_float(okx_p.get("pos")))
            lp_dir = lp.get("direction")
            okx_dir = okx_p.get("posSide")

            if abs(lp_sz - okx_sz) < 0.0001 and lp_dir == okx_dir:
                matched.append({"symbol": lp.get("symbol"), "size": lp_sz, "direction": lp_dir})
                survivors.append(lp)
            else:
                # 同 inst+side 但 size 差太多 → 把本地当 stale，归档；下面的 loop 会从 OKX 拉新
                actions.append(
                    f"mismatch local {lp.get('symbol')} {lp_dir} sz={lp_sz} "
                    f"vs OKX {okx_dir} sz={okx_sz} → 归档旧的，从 OKX 重建"
                )
                closed = dict(lp)
                closed["closed_at"] = now_str
                closed["realized_pnl"] = 0.0
                closed["close_source"] = "size_mismatch_replace"
                local.setdefault("closed_positions", []).append(closed)
                ghost_closed.append(closed)
                mismatched.append({"local": lp, "okx": okx_p})

    local["positions"] = survivors

    # ── 2. 处理 OKX 有 / 本地无 → 新增 ──
    existing_local_keys = set()
    for lp in local["positions"]:
        norm = _normalize_local_symbol(lp.get("symbol", ""))
        if norm.endswith("USDT") and len(norm) > 4:
            norm_inst = f"{norm[:-4]}-USDT-SWAP"
        else:
            norm_inst = lp.get("symbol", "")
        pos_side = "long" if lp.get("direction") == "long" else "short"
        existing_local_keys.add((norm_inst, pos_side))

    for op in okx_positions:
        key = (op.get("instId"), op.get("posSide"))
        if key in existing_local_keys:
            continue

        entry = _safe_float(op.get("avgPx"))
        mark = _safe_float(op.get("markPx")) or entry
        sz = abs(_safe_float(op.get("pos")))
        lever = _safe_float(op.get("lever"), 1.0)
        # cross 模式 margin OKX 不返回 → 用 notional/leverage 估值
        notional = mark * sz
        margin_est = round(notional / lever, 6) if lever > 0 else notional
        c_time_ms = int(op.get("cTime", 0))
        opened_iso = (
            datetime.fromtimestamp(c_time_ms / 1000.0).isoformat(timespec="seconds")
            if c_time_ms else now_str
        )
        pos_id = op.get("posId", "")
        direction = "long" if op.get("posSide") == "long" else "short"

        # ── P0-4 fix (2026-07-15): 外部 / Web 手动开仓不合成 SL/TP ──
        # 24h 内踩过两次同款 footgun（-3.3189 + -0.671 = -3.99 USDT 损失）
        # 根因：_synthesize_sl_tp 给外部手动仓套 0.3% SL，runner 不分 strategy 一律自动平仓
        # 修复：A+C 双锁 ——
        #   (A) sentinel: sl_price=0 / tp_price=0（物理防呆，runner 见 0 跳过）
        #   (C) 显式 strategy 名 MANUAL_NO_AUTO_CLOSE（逻辑隔离，便于 audit / dashboard）
        # 白名单兼容旧名 EXTERNAL_WEB_SYNC（历史 closed_positions 已使用）

        new_pos = {
            "symbol": op.get("instId").replace("-USDT-SWAP", "USDTSWAP"),
            "direction": direction,
            "entry_price": entry,
            "size": sz,
            "leverage": int(lever) if lever.is_integer() else lever,
            "margin": margin_est,
            "order_id": pos_id,
            "opened_at": opened_iso,
            "strategy": "MANUAL_NO_AUTO_CLOSE",  # was: "EXTERNAL_WEB_SYNC"
            "source": "okx_sync_reconcile",
            "sl_price": 0.0,  # 哨兵值 — runner 见 0 跳过 SL 检查
            "tp_price": 0.0,  # 哨兵值 — runner 见 0 跳过 TP 检查
            "tp_stage": 0,
            "trigger_strategy": "MANUAL_NO_AUTO_CLOSE",  # was: "EXTERNAL_WEB_SYNC"
            "adl": op.get("adl", ""),
            "mark_px_at_sync": mark,
            "mgn_mode": op.get("mgnMode", "") or "",
            "ct_val": float(ct_val_by_inst.get(op.get("instId"), 1.0)),
            "is_manual": True,  # 显式标记
        }
        local["positions"].append(new_pos)
        new_synced.append(new_pos)
        actions.append(
            f"new → portfolio: {op.get('instId')} {direction} sz={sz} "
            f"entry={entry} mark={mark} strategy=MANUAL_NO_AUTO_CLOSE "
            f"SL=0 TP=0 (哨兵值 - 手动仓位不自动管，参见 runner.check_and_close_positions 白名单)"
        )

    local["daily_stats"] = daily

    return {
        "drift_detected": bool(ghost_closed or new_synced or mismatched),
        "actions": actions,
        "ghost_closed": ghost_closed,
        "new_synced": new_synced,
        "matched": matched,
        "mismatched": mismatched,
        "local_position_count": len(local.get("positions", [])),
        "okx_position_count": len(okx_positions),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync portfolio with OKX actual positions.")
    parser.add_argument("--dry-run", action="store_true", help="show what would change but don't write")
    parser.add_argument("--reason", default="manual_sync", help="reason tag for this sync event")
    args = parser.parse_args()

    portfolio_path = PROJECT_ROOT / "okx" / "state" / "portfolio.json"
    if not portfolio_path.exists():
        print(f"[error] portfolio.json not found at {portfolio_path}", file=sys.stderr)
        return 1

    print("[sync] connecting to OKX (demo)...")
    client = OKXClient(mode="demo")
    print("[sync] fetching positions...")
    okx_positions = client.account.get_positions(inst_type="SWAP")
    print(f"[sync] OKX has {len(okx_positions)} active positions")

    print("[sync] fetching positions history...")
    history_cache = client.account.get_positions_history(limit="20")

    print("[sync] fetching instruments (ctVal)...")
    inst_cache = client.public.get_instruments(inst_type="SWAP")
    ct_val_by_inst = {inst["instId"]: float(inst.get("ctVal") or 1.0) for inst in inst_cache}
    print(f"[sync] cached ctVal for {len(ct_val_by_inst)} instruments")

    def _history_for():
        return history_cache

    print(f"[sync] loading {portfolio_path}...")
    local = _load(portfolio_path)
    print(f"[sync] local has {len(local.get('positions', []))} positions")

    result = reconcile(
        local,
        okx_positions,
        dry_run=args.dry_run,
        okx_history_provider=_history_for,
        ct_val_by_inst=ct_val_by_inst,
    )
    result["reason"] = args.reason

    print()
    print("=" * 60)
    print("Sync result:")
    print("=" * 60)
    print(f"  drift_detected: {result['drift_detected']}")
    print(f"  ghost_closed:   {len(result['ghost_closed'])}")
    print(f"  new_synced:     {len(result['new_synced'])}")
    print(f"  matched:        {len(result['matched'])}")
    print(f"  mismatched:     {len(result['mismatched'])}")
    print(f"  → local now has {result['local_position_count']}, OKX has {result['okx_position_count']}")
    if result["actions"]:
        print()
        print("Actions:")
        for a in result["actions"]:
            print(f"  • {a}")

    if args.dry_run:
        print()
        print("[dry-run] no changes written.")
        return 0

    if result["drift_detected"]:
        # 备份
        backup_path = portfolio_path.with_suffix(
            f".json.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        with open(backup_path, "w") as f:
            json.dump(_load(portfolio_path), f, ensure_ascii=False, indent=2)
        # 更新 sync log
        sync_log = portfolio_path.parent / "sync_history.json"
        log_entry = {
            "at": _now_iso(),
            "reason": args.reason,
            "drift_detected": result["drift_detected"],
            "ghost_closed_count": len(result["ghost_closed"]),
            "new_synced_count": len(result["new_synced"]),
            "actions": result["actions"],
        }
        log_data = []
        if sync_log.exists():
            try:
                log_data = _load(sync_log)
                if not isinstance(log_data, list):
                    log_data = []
            except Exception:
                log_data = []
        log_data.append(log_entry)
        with open(sync_log, "w") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        # 写 portfolio
        _save(portfolio_path, local)
        print(f"[sync] backup saved to {backup_path}")
        print(f"[sync] sync_history updated")
        print(f"[sync] portfolio.json updated ✓")
    else:
        print("[sync] no drift, nothing to do")

    return 0


if __name__ == "__main__":
    sys.exit(main())
