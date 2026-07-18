#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rotate_telegram_key.py —— Phase 4 Gate 8：Telegram Bot Token 安全隔离与轮换

═══════════════════════════════════════════════════════════════════
目的：在 LIVE 上线前，确保 Telegram Bot Token 不被泄露在历史聊天/
      代码仓库/.env 历史中，提供半自动化的轮换指引。
═══════════════════════════════════════════════════════════════════

⚠️ 关键安全原则：
  - 本脚本**不会**自动生成新 Token（Token 必须在 @BotFather 处由人手动生成）
  - 本脚本**会**扫描所有可能泄露点，给出轮换指引
  - 轮换后**必须**做连通性验证（推一条 test 消息）

流程：
  1. 扫描：找出当前 Token 在哪些位置出现（.env / openclaw.json / 日志）
  2. 报告：列出所有"暴露面"，给出风险等级
  3. 指引：打印"在 @BotFather 操作 X 步骤"
  4. 验证：用户更新 .env 后，运行 --verify 推送测试消息

CLI 例子：
  # 1. 扫描泄露面
  python3 -m okx.scripts.rotate_telegram_key --scan

  # 2. 验证当前 Token 连通性（不发消息，只查 getMe）
  python3 -m okx.scripts.rotate_telegram_key --verify

  # 3. 推送测试消息（轮换后必须）
  python3 -m okx.scripts.rotate_telegram_key --test-message
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Token 格式: <bot_id>:<64-char-hex>
TELEGRAM_BOT_TOKEN_RE = re.compile(r"\b(\d{8,10}:[A-Za-z0-9_-]{35,})\b")


# ──────────────── 扫描：找 Token 在哪些位置出现 ────────────────


def _read_safe(path: Path) -> Optional[str]:
    """读取文件，失败返回 None（不抛异常）"""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def scan_token_exposure(workspace_root: Path, token: Optional[str] = None) -> Dict[str, Any]:
    """
    扫描 Token 暴露面（不依赖 git，纯文件级扫描）

    :param workspace_root: workspace 根目录
    :param token: 已知 Token（用于精确匹配）；None = 用 regex 扫所有疑似 token
    :return: {
        "current_token": "...",  # 当前 .env 里的 token
        "exposures": [
            {"file": ".env", "line": 1, "context": "...", "risk": "high"},
            ...
        ],
        "summary": {"high": 2, "medium": 1, "low": 0},
    }
    """
    env_path = workspace_root / "okx" / ".env"
    env_content = _read_safe(env_path) or ""

    # 抽取当前 .env 里的 TELEGRAM_BOT_TOKEN
    current_token = None
    for line in env_content.splitlines():
        if line.strip().startswith("#"):
            continue
        if "TELEGRAM_BOT_TOKEN=" in line:
            current_token = line.split("=", 1)[1].strip()
            break

    target_token = token or current_token
    if not target_token:
        logger.warning("⚠️ 未找到 TELEGRAM_BOT_TOKEN（.env 缺失或未配置）")
        return {
            "current_token": None,
            "exposures": [],
            "summary": {"high": 0, "medium": 0, "low": 0, "skipped": "no token"},
        }

    # 截断 token 用于匹配（前 8 + 后 4 字符）
    token_prefix = target_token[:8]
    token_suffix = target_token[-4:]
    partial_re = re.compile(re.escape(token_prefix) + r".*?" + re.escape(token_suffix))

    exposures: List[Dict[str, Any]] = []

    # 扫描范围（排除 .git 和大目录）
    skip_dirs = {".git", "node_modules", "__pycache__", "data/market", "data/funding", ".venv"}
    skip_files = {".env.example"}  # 模板里有占位符，不算暴露

    for p in workspace_root.rglob("*"):
        if not p.is_file():
            continue
        if any(sd in p.parts for sd in skip_dirs):
            continue
        if p.name in skip_files:
            continue

        # 大文件跳过（> 5MB）
        try:
            if p.stat().st_size > 5 * 1024 * 1024:
                continue
        except Exception:
            continue

        content = _read_safe(p)
        if not content:
            continue

        # 用 partial token 匹配（避免完整 token 在内存里出现太多次）
        for i, line in enumerate(content.splitlines(), 1):
            if partial_re.search(line):
                risk = _assess_risk(p, line)
                # ⚠️ context 里也要 mask 完整 token（防报告泄露）
                masked_context = partial_re.sub(
                    f"{token_prefix}...{token_suffix}", line[:120]
                )
                exposures.append({
                    "file": str(p.relative_to(workspace_root)),
                    "line": i,
                    "context": masked_context,
                    "risk": risk,
                })

    summary = {"high": 0, "medium": 0, "low": 0}
    for e in exposures:
        summary[e["risk"]] += 1

    return {
        "current_token": current_token,
        "exposures": exposures,
        "summary": summary,
    }


def _assess_risk(file_path: Path, line: str) -> str:
    """评估单条暴露的风险等级"""
    rel = str(file_path)
    # .env 是 high（虽然 .gitignore 了，但备份/日志可能泄露）
    if rel.endswith(".env") or ".env." in rel:
        return "high"
    # 日志文件是 high（可能 sync 到云）
    if "/logs/" in rel or rel.endswith(".log"):
        return "high"
    # chat 历史 / markdown 含 token 字样是 high
    if rel.endswith(".md") and ("TELEGRAM_BOT_TOKEN" in line or "bot_token" in line.lower()):
        return "high"
    # .py 文件里写死 token 是 high
    if rel.endswith(".py"):
        return "high"
    # json 配置是 medium
    if rel.endswith(".json"):
        return "medium"
    # 其他 medium
    return "medium"


# ──────────────── 轮换指引 ────────────────


def print_rotation_guide() -> str:
    """打印 Telegram Bot Token 轮换指引（人工操作 @BotFather）"""
    return """
╔════════════════════════════════════════════════════════════════╗
║           Telegram Bot Token 轮换指引                          ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║  步骤 1：吊销旧 Token                                          ║
║    - 打开 Telegram，搜索 @BotFather                            ║
║    - 发送 /mybots                                              ║
║    - 选择你的 Bot                                             ║
║    - 点 "API Token" → "Revoke current token"                  ║
║    - 确认后 BotFather 会生成新 Token                           ║
║                                                                ║
║  步骤 2：更新 .env                                              ║
║    - 备份：cp okx/.env okx/.env.backup-$(date +%Y%m%d-%H%M%S)  ║
║    - 编辑 okx/.env                                            ║
║    - 替换 TELEGRAM_BOT_TOKEN=<新 Token>                       ║
║    - 检查 TELEGRAM_CHAT_ID 是否仍正确                          ║
║                                                                ║
║  步骤 3：清理历史暴露面                                          ║
║    - 如果 .env 曾被 git commit：git filter-branch 或 BFG       ║
║    - 如果日志泄露：截断/删除相关 log 行                         ║
║    - 如果 chat 历史泄露：本地搜索替换或删档                      ║
║                                                                ║
║  步骤 4：验证新 Token                                           ║
║    - python3 -m okx.scripts.rotate_telegram_key --verify       ║
║    - python3 -m okx.scripts.rotate_telegram_key --test-message ║
║                                                                ║
║  ⚠️  不要在脚本输出、commit message、聊天里粘贴 Token            ║
║  ⚠️  新旧 Token 不要并行使用超过 5 分钟（避免 race）            ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
"""


# ──────────────── 验证 ────────────────


def verify_token_via_get_me(token: str, timeout: int = 10) -> Dict[str, Any]:
    """通过 getMe API 验证 Token 连通性（不发送消息）"""
    import urllib.request
    import urllib.error

    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                result = data["result"]
                return {
                    "ok": True,
                    "bot_id": result.get("id"),
                    "bot_username": result.get("username"),
                    "first_name": result.get("first_name"),
                    "can_join_groups": result.get("can_join_groups"),
                }
            return {"ok": False, "error": data.get("description", "unknown")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_test_message(token: str, chat_id: str, text: Optional[str] = None) -> Dict[str, Any]:
    """推送测试消息到指定 chat_id"""
    import urllib.request
    import urllib.error
    import urllib.parse

    if text is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        text = f"✅ Token 轮换验证\n时间: {ts}\n发送方: rotate_telegram_key.py"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                return {"ok": True, "message_id": data["result"]["message_id"]}
            return {"ok": False, "error": data.get("description", "unknown")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ──────────────── 报告 ────────────────


def format_scan_report(scan_result: Dict[str, Any]) -> str:
    """格式化扫描报告"""
    lines = []
    lines.append("# Telegram Bot Token 暴露面扫描报告")
    lines.append("")
    lines.append(f"**扫描时间**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    token = scan_result.get("current_token")
    if token:
        # 只显示前 8 + 后 4
        masked = f"{token[:8]}...{token[-4:]}"
        lines.append(f"**当前 Token**: `{masked}` (长度 {len(token)})")
    else:
        lines.append(f"**当前 Token**: ❌ 未配置")

    lines.append("")
    lines.append("## 🚦 暴露面风险分布")
    s = scan_result.get("summary", {})
    if isinstance(s, dict) and "high" in s:
        lines.append(f"- 🔴 high: **{s['high']}** 处")
        lines.append(f"- 🟡 medium: **{s['medium']}** 处")
        lines.append(f"- 🟢 low: **{s['low']}** 处")
    lines.append("")

    exposures = scan_result.get("exposures", [])
    if not exposures:
        lines.append("✅ **未发现暴露**")
        return "\n".join(lines)

    # 按风险分组展示
    for risk_level in ["high", "medium", "low"]:
        risk_exposures = [e for e in exposures if e["risk"] == risk_level]
        if not risk_exposures:
            continue
        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}[risk_level]
        lines.append(f"## {emoji} {risk_level.upper()} 风险 ({len(risk_exposures)} 处)")
        for e in risk_exposures[:20]:  # 最多展示 20
            lines.append(f"- `{e['file']}:{e['line']}`: {e['context']}")
        if len(risk_exposures) > 20:
            lines.append(f"- ...（共 {len(risk_exposures)} 处，仅展示前 20）")
        lines.append("")

    return "\n".join(lines)


# ──────────────── CLI ────────────────


def main():
    parser = argparse.ArgumentParser(description="Phase 4 Gate 8 Telegram Key 安全隔离与轮换")
    parser.add_argument("--scan", action="store_true", help="扫描 Token 暴露面")
    parser.add_argument("--verify", action="store_true", help="验证当前 Token 连通性（getMe）")
    parser.add_argument("--test-message", action="store_true", help="推送测试消息")
    parser.add_argument("--guide", action="store_true", help="打印轮换指引")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    workspace_root = Path("/home/zzzx47/.openclaw/workspace")

    # 默认动作：scan
    if not any([args.scan, args.verify, args.test_message, args.guide]):
        args.scan = True

    if args.scan:
        result = scan_token_exposure(workspace_root)
        if args.json:
            import json
            # 隐藏完整 token，只保留 masked
            if result.get("current_token"):
                t = result["current_token"]
                result["current_token_masked"] = f"{t[:8]}...{t[-4:]}"
                result.pop("current_token")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_scan_report(result))

        # high 暴露 → 给指引
        s = result.get("summary", {})
        if isinstance(s, dict) and s.get("high", 0) > 0:
            print("\n⚠️  发现 HIGH 风险暴露，请执行轮换指引：")
            print("    python3 -m okx.scripts.rotate_telegram_key --guide")

    if args.verify:
        env_path = workspace_root / "okx" / ".env"
        env_content = _read_safe(env_path) or ""
        token = None
        for line in env_content.splitlines():
            if line.strip().startswith("#"):
                continue
            if "TELEGRAM_BOT_TOKEN=" in line:
                token = line.split("=", 1)[1].strip()
                break

        if not token:
            print("❌ .env 中未配置 TELEGRAM_BOT_TOKEN")
            sys.exit(1)

        result = verify_token_via_get_me(token)
        if result["ok"]:
            print(f"✅ Token 连通: @{result.get('bot_username', '?')} (id={result.get('bot_id')})")
        else:
            print(f"❌ Token 验证失败: {result['error']}")
            sys.exit(2)

    if args.test_message:
        env_path = workspace_root / "okx" / ".env"
        env_content = _read_safe(env_path) or ""
        token = chat_id = None
        for line in env_content.splitlines():
            if line.strip().startswith("#"):
                continue
            if "TELEGRAM_BOT_TOKEN=" in line:
                token = line.split("=", 1)[1].strip()
            elif "TELEGRAM_CHAT_ID=" in line:
                chat_id = line.split("=", 1)[1].strip()

        if not token or not chat_id:
            print("❌ .env 中 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未配置")
            sys.exit(1)

        result = send_test_message(token, chat_id)
        if result["ok"]:
            print(f"✅ 测试消息已推送: message_id={result['message_id']}")
        else:
            print(f"❌ 推送失败: {result['error']}")
            sys.exit(2)

    if args.guide:
        print(print_rotation_guide())


if __name__ == "__main__":
    main()