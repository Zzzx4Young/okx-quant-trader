#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX 双模式凭据审计脚本（v1.2）

用途：检查 OKX_LIVE_* / OKX_DEMO_* 配置的完整性与格式合理性
不做任何网络请求，只做静态分析

用法：
    ./run.sh scripts/audit_credentials.py
    ./run.sh scripts/audit_credentials.py --json
"""

import os
import re
import sys
import json
import stat
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


# OKX V5 凭据的常见格式特征
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32,}$")

PLACEHOLDER_TOKENS = (
    "__TBD", "TBD_", "TBA_", "YOUR_", "PLACEHOLDER",
    "your_", "Provide", "ProvideVia", "Provide_via",
)


def _is_placeholder(value: str) -> bool:
    if not value:
        return True
    upper = value.upper()
    return any(tok.upper() in upper for tok in PLACEHOLDER_TOKENS)


def _check_field(name: str, value: str) -> dict:
    """检查单个字段"""
    result = {"field": name, "present": False, "valid_format": False, "is_placeholder": False, "length": 0}

    if value is None:
        result["reason"] = "env var not set"
        return result

    value = value.strip()
    result["length"] = len(value)

    if not value:
        result["reason"] = "empty value"
        return result

    result["present"] = True

    if _is_placeholder(value):
        result["is_placeholder"] = True
        result["reason"] = "placeholder detected (needs real value)"
        return result

    # 字段级格式检查
    if name.endswith("API_KEY"):
        if UUID_RE.match(value):
            result["valid_format"] = True
            result["format"] = "UUID (OKX V5 标准)"
        else:
            result["format"] = "格式不符 OKX UUID (xxxx-xxxx-xxxx-xxxx-xxxx)"
            result["reason"] = "may not be a valid OKX api_key"
    elif name.endswith("API_SECRET"):
        if HEX32_RE.match(value):
            result["valid_format"] = True
            result["format"] = "32+ hex chars (OKX V5 标准)"
        else:
            result["format"] = "格式不符 hex32 (32 位十六进制)"
            result["reason"] = "may not be a valid OKX api_secret"
    elif name.endswith("PASSPHRASE"):
        # passphrase 用户自定义，宽松校验
        if 4 <= len(value) <= 64:
            result["valid_format"] = True
            result["format"] = f"{len(value)} 字符（OKX 用户自定义，无标准格式）"
        else:
            result["format"] = f"{len(value)} 字符（过短或过长，正常 4-64）"
            result["reason"] = "passphrase length unusual"
    return result


def audit_mode(mode: str, env: dict) -> dict:
    """审计单个 mode 的三件套"""
    prefix = f"OKX_{mode.upper()}_"
    keys = [f"{prefix}API_KEY", f"{prefix}API_SECRET", f"{prefix}PASSPHRASE"]
    return {
        "mode": mode,
        "fields": {k.replace(prefix, ""): _check_field(k, env.get(k)) for k in keys},
        "complete": False,  # 下方汇总
    }


def main():
    # 加载 .env
    env = dict(os.environ)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    report = {
        "env_file": str(ENV_FILE),
        "env_file_exists": ENV_FILE.exists(),
        "env_file_permissions": None,
        "mode_selector": env.get("OKX_TRADING_MODE", "(not set)"),
        "modes": {},
        "legacy_vars": {},
        "suspicious_files": [],
        "summary": {"ready_to_run": False, "blocking_issues": []},
    }

    # 1. .env 权限检查
    if ENV_FILE.exists():
        st = ENV_FILE.stat()
        mode_bits = stat.S_IMODE(st.st_mode)
        report["env_file_permissions"] = oct(mode_bits)
        if mode_bits & 0o077:
            report["suspicious_files"].append(
                f".env 权限 {oct(mode_bits)} 不是 0600（其他用户可读！）"
            )

    # 2. mode 选择器
    mode_sel = env.get("OKX_TRADING_MODE", "").strip().lower()
    if mode_sel not in ("live", "demo"):
        report["summary"]["blocking_issues"].append(
            f"OKX_TRADING_MODE='{mode_sel}' 不是 live 或 demo"
        )

    # 3. 双 mode 审计
    for mode in ("live", "demo"):
        result = audit_mode(mode, env)
        # 计算 complete
        all_ok = all(
            f["present"] and f["valid_format"] and not f["is_placeholder"]
            for f in result["fields"].values()
        )
        result["complete"] = all_ok
        report["modes"][mode] = result

    # 4. legacy 兼容变量
    legacy_keys = ["OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE", "OKX_FLAG"]
    for k in legacy_keys:
        if k in env and env[k]:
            report["legacy_vars"][k] = {
                "present": True,
                "length": len(env[k]),
                "is_placeholder": _is_placeholder(env[k]),
            }

    # 5. 总结
    active_mode = mode_sel if mode_sel in ("live", "demo") else "demo"
    active = report["modes"].get(active_mode, {})
    if active.get("complete"):
        report["summary"]["ready_to_run"] = True
    else:
        for fname, f in active.get("fields", {}).items():
            if not f["present"]:
                report["summary"]["blocking_issues"].append(
                    f"[{active_mode}] {fname}: 未配置"
                )
            elif f["is_placeholder"]:
                report["summary"]["blocking_issues"].append(
                    f"[{active_mode}] {fname}: 占位符，需补真实值"
                )
            elif not f["valid_format"]:
                report["summary"]["blocking_issues"].append(
                    f"[{active_mode}] {fname}: {f.get('reason', '格式异常')}"
                )

    # 6. 查 MEMORY.md 是否含 secret（精确上下文搜索）
    mem_path = PROJECT_ROOT.parent / "MEMORY.md"
    if mem_path.exists():
        mem_content = mem_path.read_text(encoding="utf-8")
        # 只匹配出现在凭据关键词附近的 UUID/hex（避免误报 sessionId 等）
        # 模式：关键词前后 30 字符内有 UUID 或 32+ hex
        cred_keywords = (
            r"(?:OKX_API_KEY|OKX_API_SECRET|OKX_PASSPHRASE|"
            r"api_key|secret_key|secretKey|apiSecret|api_key|passphrase)"
        )
        # 在关键词上下文里找 UUID 或 hex32
        pattern = re.compile(
            cred_keywords + r".{0,40}?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32,})",
            re.IGNORECASE | re.DOTALL,
        )
        leaks = pattern.findall(mem_content)
        if leaks:
            report["suspicious_files"].append(
                f"MEMORY.md 中检测到疑似明文凭据（{len(leaks)} 处，关键词上下文）"
            )

    # 输出
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        # 人读输出
        print("=" * 70)
        print(f"  OKX 双模式凭据审计报告")
        print("=" * 70)
        print()
        print(f"📁 .env: {report['env_file']}")
        print(f"   存在: {'✓' if report['env_file_exists'] else '✗'}")
        print(f"   权限: {report['env_file_permissions'] or '(文件不存在)'}"
              f" {'⚠️  应为 0o600' if report['env_file_permissions'] and report['env_file_permissions'] != '0o600' else '✓'}")
        print()
        print(f"🎚️  当前激活模式: OKX_TRADING_MODE = {report['mode_selector']!r}")
        print()

        for mode in ("live", "demo"):
            m = report["modes"][mode]
            icon = "✓" if m["complete"] else "✗"
            print(f"── {icon} {mode.upper()} 模式  ──")
            for fname, f in m["fields"].items():
                if not f["present"]:
                    mark = "⚠️ 未配置"
                elif f["is_placeholder"]:
                    mark = "🔸 占位符"
                elif not f["valid_format"]:
                    mark = "❓ 格式可疑"
                else:
                    mark = "✓ 正常"
                # 脱敏显示
                if f["present"]:
                    v = env.get(f"OKX_{mode.upper()}_{fname}", "")
                    disp = v[:4] + "…" + v[-4:] if len(v) > 8 else "***"
                else:
                    disp = "(空)"
                print(f"  OKX_{mode.upper()}_{fname:13s} {mark:14s} 长度={f['length']:<3}  值={disp}")
                if f.get("reason") and not f["valid_format"]:
                    print(f"      ⚠️ {f['reason']}")
                if f.get("format") and f["valid_format"]:
                    print(f"      格式: {f['format']}")
            print()

        if report["legacy_vars"]:
            print("── 📜 旧版兼容变量（OKX_API_*） ──")
            for k, info in report["legacy_vars"].items():
                if info["is_placeholder"]:
                    print(f"  {k}: 占位符")
                else:
                    print(f"  {k}: 已配置（长度={info['length']}）")
            print("  ℹ️  旧变量在 demo 模式下仍生效；建议迁移完成后删除")
            print()

        if report["suspicious_files"]:
            print("── ⚠️  安全警告 ──")
            for w in report["suspicious_files"]:
                print(f"  • {w}")
            print()

        print("── 📋 总结 ──")
        if report["summary"]["ready_to_run"]:
            print(f"  ✅ 当前 mode={active_mode} 的三件套齐全，可以联调（需网络通畅）")
        else:
            print(f"  ❌ 当前 mode={active_mode} 凭据不完整，无法联调")
        if report["summary"]["blocking_issues"]:
            print(f"  待解决：")
            for issue in report["summary"]["blocking_issues"]:
                print(f"    • {issue}")
        print()

    sys.exit(0 if report["summary"]["ready_to_run"] else 1)


if __name__ == "__main__":
    main()