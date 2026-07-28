"""fragility_scan with direction filter (Phase 3B Step B validation).

用法:
    bash run.sh scripts/fragility_scan_with_filter.py \
        --strategy A --symbol BTC-USDT-SWAP --bar 1h \
        --slippage-bps 5,10,15 --fee-bps 5.0 \
        --buy-hold-ret -6.49 --name a-btc-filtered

与 run.sh scripts/fragility_scan.py 唯一区别：monkey-patch STRATEGIES
用 wrapped version (signal_direction_filter.make_filtered_strategy)。

输出与原 fragility_scan 一致，只是 strategies 经过 direction × regime 过滤。

参考：
- code/signal_direction_filter.py (filter rules)
- data/phase3b/bootstrap_report_direction.md (Phase 3B Track A 分析)
"""
import sys
from pathlib import Path

# 让 okx 包可导入
_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))  # 项目根

# Monkey-patch：在 import fragility_scan 前替换 STRATEGIES
import okx.code.backtest.run_phase2_experiment as rpe
from okx.code.signal_direction_filter import make_filtered_strategy

# 保存原始 STRATEGIES（用于对比）
ORIGINAL_STRATEGIES = dict(rpe.STRATEGIES)
# 生成 wrapped 版本
rpe.STRATEGIES = {
    sid: make_filtered_strategy(sid, fn) for sid, fn in ORIGINAL_STRATEGIES.items()
}

# 现在 import fragility_scan（它会用 patched STRATEGIES）
from okx.scripts.fragility_scan import main  # noqa: E402

if __name__ == "__main__":
    main()