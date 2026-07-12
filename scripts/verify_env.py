#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX 配置验证脚本（简化版）
用途：验证环境变量是否正确加载，不进行网络请求

执行方式：./run.sh scripts/verify_env.py
"""

import os


def verify_env() -> bool:
    """验证环境变量是否正确加载"""
    print("=" * 50)
    print("OKX 配置验证")
    print("=" * 50)

    api_key = os.getenv("OKX_API_KEY")
    secret_key = os.getenv("OKX_API_SECRET")
    passphrase = os.getenv("OKX_PASSPHRASE")
    flag = os.getenv("OKX_FLAG", "1")

    print(f"\n配置检查:")
    print(f"  OKX_API_KEY: {'✓ 已配置' if api_key else '✗ 未配置'}")
    print(f"  OKX_API_SECRET: {'✓ 已配置' if secret_key else '✗ 未配置'}")
    print(f"  OKX_PASSPHRASE: {'✓ 已配置' if passphrase else '✗ 未配置'}")
    print(f"  OKX_FLAG: {flag} ({'模拟盘' if flag == '1' else '实盘'})")

    if not all([api_key, secret_key, passphrase]):
        print("\n✗ 错误: 缺少必需的环境变量")
        print("  请运行: python3 scripts/convert_env.py")
        return False

    print("\n" + "=" * 50)
    print("✓ 配置验证通过")
    print("=" * 50)
    return True


if __name__ == "__main__":
    import sys
    sys.exit(0 if verify_env() else 1)