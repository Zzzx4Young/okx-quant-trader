#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金费率历史增量拉取 wrapper —— scripts/ 入口

用法：
    bash run.sh scripts/fetch_funding.py --inst-id BTC-USDT-SWAP
    bash run.sh scripts/fetch_funding.py --inst-id ETH-USDT-SWAP

设计原则：
- 薄 wrapper：source .env 后调 code.backtest.fetch_funding.fetch_funding()
- 增量更新（向更早拉取）：第二次跑只拉新区间
- 真实实现见 code/backtest/fetch_funding.py（包含分页/重试/对齐/压缩）

来源：v1.1 离线沙盒推进方案 P1.2（2026-07-20）
"""
import argparse
import os
import sys
from pathlib import Path

# 让脚本能被直接调用（python3 okx/scripts/xxx.py），无需依赖 run.sh 注入 PYTHONPATH
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # scripts/ → okx/ → workspace/
sys.path.insert(0, str(PROJECT_ROOT))


def _load_env(env_path: Path) -> None:
    """加载 .env 到 os.environ"""
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


def main():
    parser = argparse.ArgumentParser(
        description="资金费率增量拉取 wrapper（scripts/ 入口）"
    )
    parser.add_argument("--inst-id", required=True, help="如 BTC-USDT-SWAP")
    parser.add_argument("--days", type=int, default=90, help="首次拉取天数（增量时忽略）")
    args = parser.parse_args()

    # 加载 .env（OKX 凭据 + HTTPS_PROXY）
    env_path = SCRIPT_DIR.parent / ".env"
    _load_env(env_path)

    # 检查代理配置
    if not os.environ.get("HTTPS_PROXY") and not os.environ.get("https_proxy"):
        print("⚠️  HTTPS_PROXY 未配置；如在 GFW 环境可能连不上 OKX")

    print(f"🚀 Funding 拉取启动")
    print(f"   标的: {args.inst_id}")
    print(f"   首次天数: {args.days}（增量时忽略）")

    # 调真实实现
    from okx.code.backtest.fetch_funding import fetch_funding
    df = fetch_funding(args.inst_id, args.days, verbose=True)

    print(f"\n汇总: {len(df)} 条资金费率已缓存")


if __name__ == "__main__":
    sys.exit(main())