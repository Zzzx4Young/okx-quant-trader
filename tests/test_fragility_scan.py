# -*- coding: utf-8 -*-
"""
test_fragility_scan.py —— CLI smoke tests

不是数值测试（数值由 BacktestEngine 验证），是 CLI 接口 + 输出格式的烟雾测试：
1. CLI 参数解析 + 策略缩写展开
2. viability() 判定逻辑（vs buy-hold / vs zero baseline）
3. result.md / result.txt / meta.json 全部写出
4. 失败时 exit code != 0

跑法：
  pytest okx/tests/test_fragility_scan.py -v
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
# okx/tests/test_*.py → parents[2] 是 workspace/（含 okx/ 包）
_PROJECT_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from okx.scripts import fragility_scan as fs


# ────────────────────────────────────────────────────────────────────
# 单元测试（不实际跑回测，只测逻辑）
# ────────────────────────────────────────────────────────────────────

class TestStrategyResolve:
    def test_short_alias(self):
        assert fs.resolve_strategy("A") == "A_EMA20_BREAKOUT"
        assert fs.resolve_strategy("B") == "B_BB_RSI_REVERSION"
        assert fs.resolve_strategy("C") == "C_VOLATILITY_BREAKOUT"
        assert fs.resolve_strategy("D") == "D_FUNDING_RATE_REVERSAL"

    def test_full_name(self):
        assert fs.resolve_strategy("A_EMA20_BREAKOUT") == "A_EMA20_BREAKOUT"

    def test_case_insensitive_alias(self):
        assert fs.resolve_strategy("c") == "C_VOLATILITY_BREAKOUT"

    def test_unknown_raises(self):
        with pytest.raises(SystemExit):
            fs.resolve_strategy("Z_NOT_EXIST")


class TestCalibrationDefaults:
    """Phase 6.2 摩擦回写：从 config.risk.calibration 读取 Gate 7 实测值"""

    def test_load_calibration_returns_empty_when_no_config(self, tmp_path, monkeypatch):
        """config.json 缺失时返回空 dict，不报错"""
        import okx.scripts.fragility_scan as fs
        # 模拟 _PROJECT_ROOT 指向 tmp_path（不存在 state/config.json）
        monkeypatch.setattr(fs, "_PROJECT_ROOT", tmp_path)
        result = fs.load_calibration_defaults()
        assert result == {}

    def test_load_calibration_returns_calibration_block(self, monkeypatch, tmp_path):
        """正常路径：返回 risk.calibration 子树"""
        import okx.scripts.fragility_scan as fs
        cfg = {
            "risk": {
                "calibration": {
                    "real_measured_taker_slippage_bps": 5.42,
                    "real_measured_taker_fee_bps": 5.0,
                    "sample_size": 50,
                }
            }
        }
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("ignored")  # placeholder; real cfg loaded below
        # 模拟使用真实 config.json 路径
        real_cfg = tmp_path / "okx" / "state" / "config.json"
        real_cfg.parent.mkdir(parents=True, exist_ok=True)
        real_cfg.write_text(__import__("json").dumps(cfg))
        monkeypatch.setattr(fs, "_PROJECT_ROOT", tmp_path)
        result = fs.load_calibration_defaults()
        assert result["real_measured_taker_slippage_bps"] == 5.42
        assert result["real_measured_taker_fee_bps"] == 5.0
        assert result["sample_size"] == 50


class TestParseLists:
    def test_int_list(self):
        assert fs.parse_int_list("5,10,15,20") == [5, 10, 15, 20]
        assert fs.parse_int_list("5") == [5]

    def test_float_list(self):
        assert fs.parse_float_list("4.5,5.5,7.0,8.5") == [4.5, 5.5, 7.0, 8.5]

    def test_whitespace_tolerated(self):
        assert fs.parse_float_list(" 4.5 , 5.5 ") == [4.5, 5.5]


class TestViability:
    def test_vs_buy_hold_viable(self):
        """策略 ret = -5%，buy-hold = -10% → 跑赢 → viable"""
        assert fs.viability(-5.0, buy_hold_ret_pct=-10.0) is True

    def test_vs_buy_hold_not_viable(self):
        """策略 ret = -10%，buy-hold = -5% → 跑输 → not viable"""
        assert fs.viability(-10.0, buy_hold_ret_pct=-5.0) is False

    def test_vs_zero_baseline(self):
        """buy_hold 未指定 → viable = ret > 0"""
        assert fs.viability(0.5, buy_hold_ret_pct=None) is True
        assert fs.viability(-0.1, buy_hold_ret_pct=None) is False
        assert fs.viability(0.0, buy_hold_ret_pct=None) is False  # 严格 > 0

    def test_marker(self):
        assert fs.viability_marker(1.0, -5.0) == "✅"
        assert fs.viability_marker(-10.0, -5.0) == "❌"


# ────────────────────────────────────────────────────────────────────
# 集成测试（真跑一次 mini scan）
# ────────────────────────────────────────────────────────────────────

@pytest.mark.slow
class TestCLIRun:
    """mini smoke test：1 cell 真跑回测，验证输出结构完整。

    跳过条件：缺 K 线数据（tests/conftest.py 通常会 prepare fixture）。
    """

    def test_mini_scan_produces_expected_files(self, tmp_path):
        out_root = tmp_path / "experiments"
        cmd = [
            sys.executable, "-m", "okx.scripts.fragility_scan",
            "--strategy", "C",
            "--symbol", "BTC-USDT-SWAP",
            "--bar", "1h",
            "--slippage-bps", "10",  # 单 cell，避免耗时长
            "--fee-bps", "5.5",
            "--buy-hold-ret", "-6.49",
            "--name", "test-mini",
            "--out-root", str(out_root),
        ]
        # subprocess 用 cwd=_PROJECT_ROOT 即可，Python 从 cwd 找 okx 包
        # 不需要显式设 PYTHONPATH（容易引发其他 import 冲突）
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_PROJECT_ROOT))
        assert result.returncode == 0, f"CLI failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

        # 验证产物
        dirs = list(out_root.glob("test-mini-*"))
        assert len(dirs) == 1, f"应只有 1 个输出目录，实际 {len(dirs)}"
        out_dir = dirs[0]

        for fname in ("result.md", "result.txt", "meta.json", "scan.py"):
            assert (out_dir / fname).exists(), f"缺少 {fname}"

        # 验证 meta.json 可解析
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["strategy"] == "C_VOLATILITY_BREAKOUT"
        assert meta["symbol"] == "BTC-USDT-SWAP"
        assert meta["buy_hold_ret_pct"] == -6.49
        assert len(meta["grid"]) == 1  # 单 cell
        cell = meta["grid"][0]
        assert cell["slippage_bps"] == 10
        assert cell["fee_bps"] == 5.5
        # 数字合理性（v17-fragility 已知 slip=10/fee=5.5 时 ret ≈ -5.48%）
        assert -10.0 < cell["ret_pct"] < -3.0, f"ret_pct 异常：{cell['ret_pct']}"

    def test_unknown_strategy_exits_nonzero(self):
        cmd = [
            sys.executable, "-m", "okx.scripts.fragility_scan",
            "--strategy", "Z_INVALID",
            "--symbol", "BTC-USDT-SWAP",
            "--slippage-bps", "5",
            "--fee-bps", "5.5",
            "--name", "test-bad",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_PROJECT_ROOT))
        assert result.returncode != 0
        assert "未知策略" in result.stderr or "未知策略" in result.stdout

    def test_empty_lists_exits_nonzero(self):
        cmd = [
            sys.executable, "-m", "okx.scripts.fragility_scan",
            "--strategy", "C",
            "--symbol", "BTC-USDT-SWAP",
            "--slippage-bps", "",
            "--fee-bps", "5.5",
            "--name", "test-empty",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_PROJECT_ROOT))
        assert result.returncode != 0
