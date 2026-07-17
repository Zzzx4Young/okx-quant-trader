# -*- coding: utf-8 -*-
"""
okx.scripts — 运维/监控脚本包

供内部模块相互 import（如 runner_watchdog → risk_monitor → risk_thresholds）。
外部调用仍走 `./run.sh scripts/xxx.py`。
"""
