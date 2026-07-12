#!/bin/bash
# OKX 交易系统启动脚本
# 功能：加载 .env 环境变量后运行 Python 程序
#
# 用法：
#   ./run.sh <cli_action>           # 运维命令：status / run / stop / resume / close-all / summary
#   ./run.sh scripts/xxx.py         # scripts/ 下的工具脚本
#   ./run.sh tests/test_xxx.py      # 单元测试
#   ./run.sh docs/examples/xxx.py   # 示例
#   ./run.sh -m okx.code.cli <arg>  # 透传 python -m

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"  # okx/ 的父目录（包根）

ENV_FILE="$SCRIPT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "错误: .env 文件不存在，请先运行: ./run.sh scripts/convert_env.py"
    exit 1
fi

# 加载 .env
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ -z "$line" ]] || [[ "$line" =~ ^[[:space:]]*# ]]; then
        continue
    fi
    if [[ "$line" =~ ^([A-Z_]+)=(.*)$ ]]; then
        export "${BASH_REMATCH[1]}=${BASH_REMATCH[2]}"
    fi
done < "$ENV_FILE"

# 校验：按 OKX_TRADING_MODE 选定对应凭据
MODE="${OKX_TRADING_MODE:-demo}"
case "$MODE" in
    live)
        if [ -z "$OKX_LIVE_API_KEY" ] || [ -z "$OKX_LIVE_API_SECRET" ] || [ -z "$OKX_LIVE_PASSPHRASE" ]; then
            echo "错误: 当前 OKX_TRADING_MODE=live，但 OKX_LIVE_API_KEY/SECRET/PASSPHRASE 至少有一个为空"
            exit 1
        fi
        ;;
    demo)
        if [ -z "$OKX_DEMO_API_KEY" ] || [ -z "$OKX_DEMO_API_SECRET" ] || [ -z "$OKX_DEMO_PASSPHRASE" ]; then
            # 向后兼容：旧的 OKX_API_* 在 demo 模式下也接受
            if [ -z "$OKX_API_KEY" ] || [ -z "$OKX_API_SECRET" ] || [ -z "$OKX_PASSPHRASE" ]; then
                echo "错误: 当前 OKX_TRADING_MODE=demo，但 OKX_DEMO_API_KEY/SECRET/PASSPHRASE 与 OKX_API_* 都缺失"
                exit 1
            fi
        fi
        ;;
    *)
        echo "错误: OKX_TRADING_MODE 必须是 live 或 demo，当前: '$MODE'"
        exit 1
        ;;
esac

# 暴露 mode 给 Python 子进程（_http.py 会再次读取）
export OKX_TRADING_MODE="$MODE"

cd "$PROJECT_ROOT"

# 让脚本能 import okx 包（否则 python3 okx/scripts/xxx.py 会找不到 okx）
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# CLI 快捷方式
CLI_ACTIONS="status close-all stop resume run summary"
if [[ $# -ge 1 ]] && [[ " $CLI_ACTIONS " == *" $1 "* ]]; then
    exec python3 -m okx.code.cli "$@"
fi

# 相对路径快捷方式：scripts/ tests/ docs/examples/ → 自动加 okx/ 前缀
if [[ $# -ge 1 && "$1" =~ ^(scripts|tests|docs/examples)/ ]]; then
    set -- "okx/$@"
fi

exec python3 "$@"