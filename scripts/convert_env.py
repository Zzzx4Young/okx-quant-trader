#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置转换工具：将 docs/KEY.md 转换为 .env 文件（双模式版本）

支持 OKX_LIVE_* / OKX_DEMO_* 与 OKX_TRADING_MODE 的完整双模式凭据。

执行方式：./run.sh scripts/convert_env.py

v1.2: 增加 OKX_LIVE_* 与 OKX_DEMO_* 双模式；保留对旧 OKX_API_* 的兼容支持。
"""

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEY_MD_PATH = PROJECT_ROOT / "docs" / "KEY.md"
ENV_PATH = PROJECT_ROOT / ".env"


def parse_key_md(file_path: Path) -> dict:
    """解析 KEY.md 文件（注释行忽略）"""
    config = {}
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            # 去掉行尾注释
            line = line.split('#', 1)[0].rstrip()
            if not line.strip():
                continue
            match = re.match(r'^([A-Z_][A-Z0-9_]*)=(.*)$', line.strip())
            if match:
                key, value = match.groups()
                value = value.strip()
                if value:  # 跳过占位符
                    config[key] = value
    return config


def generate_env(config: dict) -> str:
    """生成 .env 文件内容（保留输入顺序，便于对比）"""
    lines = [
        "# OKX API 配置（请勿提交到版本控制）",
        "# 由 docs/KEY.md 自动生成，请勿手动编辑",
        "# 双模式：实盘 OKX_LIVE_* + 模拟 OKX_DEMO_*；OKX_TRADING_MODE 决定激活哪组",
        "",
    ]

    # 分组：live / demo / mode / 其他
    live_keys = [k for k in config if k.startswith("OKX_LIVE_")]
    demo_keys = [k for k in config if k.startswith("OKX_DEMO_")]
    legacy_keys = [k for k in config if k in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE", "OKX_FLAG")]
    mode_keys = [k for k in config if k == "OKX_TRADING_MODE"]
    other_keys = [k for k in config if k not in live_keys + demo_keys + legacy_keys + mode_keys]

    def render_section(title: str, items: list) -> list:
        out = [f"# ─── {title} ─{'─' * (60 - len(title))}"]
        for k in items:
            if k in config:
                out.append(f"{k}={config[k]}")
        out.append("")
        return out

    if live_keys:
        lines += render_section("实盘凭据（LIVE）", live_keys)
    if demo_keys:
        lines += render_section("模拟凭据（DEMO）", demo_keys)
    if legacy_keys:
        lines += render_section(
            "旧版兼容（仅 demo 模式生效；建议迁移后删除）",
            legacy_keys,
        )
    if mode_keys:
        lines += render_section("当前激活模式", mode_keys)
    if other_keys:
        lines += render_section("其他", other_keys)

    return "\n".join(lines)


def main():
    print(f"正在读取: {KEY_MD_PATH}")

    if not KEY_MD_PATH.exists():
        print(f"错误: 文件不存在 - {KEY_MD_PATH}")
        print("提示: cp docs/KEY.md.template docs/KEY.md 并填入凭据")
        sys.exit(1)

    config = parse_key_md(KEY_MD_PATH)

    if not config:
        print("错误: KEY.md 中未找到任何 KEY=VALUE 行")
        sys.exit(1)

    # 默认 mode
    if "OKX_TRADING_MODE" not in config:
        config["OKX_TRADING_MODE"] = "demo"
        print("提示: 未设置 OKX_TRADING_MODE，默认为 demo")

    # 检查激活模式对应凭据是否齐全
    mode = config["OKX_TRADING_MODE"]
    prefix = f"OKX_{mode.upper()}_"
    required = [f"{prefix}API_KEY", f"{prefix}API_SECRET", f"{prefix}PASSPHRASE"]
    missing = [k for k in required if not config.get(k)]
    legacy_fallback = (
        all(config.get(k) for k in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE"))
        if mode == "demo"
        else False
    )

    if missing and not legacy_fallback:
        print(f"错误: 当前模式 '{mode}' 缺少凭据: {', '.join(missing)}")
        if mode == "demo":
            print("提示: demo 模式临时接受旧的 OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE 回退")
        sys.exit(1)
    elif missing:
        print(f"提示: {mode} 模式缺 {len(missing)} 个新格式凭据，将用 OKX_API_* 旧值回退（仅 demo）")
    else:
        print(f"✓ {mode} 模式凭据齐全")

    env_content = generate_env(config)
    ENV_PATH.write_text(env_content, encoding='utf-8')

    # 强制收紧权限：仅用户可读写
    os.chmod(ENV_PATH, 0o600)

    print(f"✓ 已生成: {ENV_PATH}")
    print(f"✓ 配置项: {len(config)} 个")
    print(f"✓ 当前模式: {config['OKX_TRADING_MODE']}")
    print(f"\n提示: 现在可以使用 ./run.sh 来运行程序了")
    print(f"提示: 建议转换完成后执行 rm docs/KEY.md 删除明文配置（按 SECURITY.md 规范）")


if __name__ == "__main__":
    main()
