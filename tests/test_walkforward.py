# -*- coding: utf-8 -*-
"""
test_walkforward.py —— walkforward 脚本的单元 + 端到端测试

覆盖：
1. generate_windows() —— 纯函数：基础生成、边界 (窗口>数据)、参数校验
2. compute_buy_hold_ret() —— 纯函数：基础/空/零价
3. run_walkforward() 端到端 —— 用小窗口配置验证输出结构

数值由 BacktestEngine 验证（本测试只验证 walkforward 的接口正确性）。

跑法：
  pytest okx/tests/test_walkforward.py -v
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

_HERE = Path(__file__).resolve()
# okx/tests/test_*.py → parents[2] 是 workspace/（含 okx/ 包）
_PROJECT_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from okx.scripts.walkforward import (
    generate_windows,
    compute_buy_hold_ret,
    WindowSpec,
    run_walkforward,
    _window_dir_label,
    _ms_to_iso,
)


# ────────────────────────────────────────────────────────────────────
# generate_windows()
# ────────────────────────────────────────────────────────────────────
class TestGenerateWindows:
    DAY_MS = 86400 * 1000

    def test_basic_1y_90d_30d(self):
        """1 年数据 + 90d 窗口 + 30d stride → 应有 10 个窗口。"""
        start = 0
        end = 365 * self.DAY_MS
        windows = generate_windows(start, end, window_days=90, stride_days=30)
        # 窗口在 start=0, 30, 60, ..., 270（最后 start=270 时 end=360 ≤ 365 ✓）
        # start=300 时 end=390 > 365 ✗ → 排除
        # 总数 = 270/30 + 1 = 10
        assert len(windows) == 10
        # 第一个窗口
        assert windows[0].idx == 0
        assert windows[0].start_ts == 0
        assert windows[0].end_ts == 90 * self.DAY_MS
        # 最后一个窗口
        assert windows[-1].idx == 9
        assert windows[-1].start_ts == 270 * self.DAY_MS
        assert windows[-1].end_ts == 360 * self.DAY_MS

    def test_window_equals_data_exactly_one_window(self):
        """窗口 == 数据范围 → 仅 1 个窗口。"""
        start = 0
        end = 90 * self.DAY_MS
        windows = generate_windows(start, end, window_days=90, stride_days=30)
        assert len(windows) == 1
        assert windows[0].start_ts == 0
        assert windows[0].end_ts == 90 * self.DAY_MS

    def test_window_larger_than_data_raises(self):
        """窗口 > 数据范围 → ValueError。"""
        start = 0
        end = 60 * self.DAY_MS
        with pytest.raises(ValueError, match="数据跨度.*小于窗口长度"):
            generate_windows(start, end, window_days=90, stride_days=30)

    def test_stride_zero_raises(self):
        """stride_days=0 → ValueError。"""
        with pytest.raises(ValueError, match="stride_days 必须 > 0"):
            generate_windows(0, 1000, window_days=10, stride_days=0)

    def test_stride_negative_raises(self):
        """stride_days=-1 → ValueError。"""
        with pytest.raises(ValueError, match="stride_days 必须 > 0"):
            generate_windows(0, 1000, window_days=10, stride_days=-1)

    def test_window_days_zero_raises(self):
        """window_days=0 → ValueError。"""
        with pytest.raises(ValueError, match="window_days 必须 > 0"):
            generate_windows(0, 1000, window_days=0, stride_days=10)

    def test_window_days_negative_raises(self):
        """window_days=-1 → ValueError。"""
        with pytest.raises(ValueError, match="window_days 必须 > 0"):
            generate_windows(0, 1000, window_days=-5, stride_days=10)

    def test_windows_sorted_ascending(self):
        """所有窗口按 start_ts 升序。"""
        start = 0
        end = 365 * self.DAY_MS
        windows = generate_windows(start, end, window_days=60, stride_days=20)
        for prev, curr in zip(windows, windows[1:]):
            assert curr.start_ts > prev.start_ts
            # stride 严格
            assert curr.start_ts - prev.start_ts == 20 * self.DAY_MS

    def test_windows_non_overlapping_by_default(self):
        """stride < window → 窗口重叠（默认行为，不阻止）。"""
        # 这是设计选择：stride < window 时相邻窗口会重叠
        # 例如 60d window / 20d stride → 40d 重叠
        start = 0
        end = 365 * self.DAY_MS
        windows = generate_windows(start, end, window_days=60, stride_days=20)
        # 验证重叠存在
        assert windows[1].start_ts < windows[0].end_ts  # 第二个窗口起点在第一个窗口内部
        assert len(windows) == (365 - 60) // 20 + 1


# ────────────────────────────────────────────────────────────────────
# compute_buy_hold_ret()
# ────────────────────────────────────────────────────────────────────
class TestComputeBuyHoldRet:
    def _make_klines(self, closes):
        return pd.DataFrame({
            "timestamp": list(range(len(closes))),
            "close": closes,
        })

    def test_simple_double(self):
        """100 → 200 = +100% (unleveraged)。"""
        k = self._make_klines([100.0, 150.0, 200.0])
        assert compute_buy_hold_ret(k) == 100.0

    def test_simple_halve(self):
        """200 → 100 = -50% (unleveraged)。"""
        k = self._make_klines([200.0, 150.0, 100.0])
        assert compute_buy_hold_ret(k) == -50.0

    def test_leverage_5x(self):
        """100 → 110 = +10% × 5x = +50%。"""
        k = self._make_klines([100.0, 110.0])
        assert compute_buy_hold_ret(k, leverage=5) == 50.0

    def test_empty_returns_zero(self):
        """空 DataFrame → 0.0（不崩）。"""
        k = self._make_klines([])
        assert compute_buy_hold_ret(k) == 0.0

    def test_single_row_returns_zero(self):
        """只有 1 行 → 0.0（无首末对比）。"""
        k = self._make_klines([100.0])
        assert compute_buy_hold_ret(k) == 0.0

    def test_zero_first_price_returns_zero(self):
        """首价为 0 → 0.0（防除零）。"""
        k = self._make_klines([0.0, 100.0])
        assert compute_buy_hold_ret(k) == 0.0

    def test_none_returns_zero(self):
        """None 输入 → 0.0。"""
        assert compute_buy_hold_ret(None) == 0.0


# ────────────────────────────────────────────────────────────────────
# _ms_to_iso() / _window_dir_label()
# ────────────────────────────────────────────────────────────────────
class TestHelpers:
    def test_ms_to_iso_format(self):
        """毫秒戳 → ISO 8601 格式（含时区）。"""
        # 2024-01-01T00:00:00Z = 1704067200000 ms
        iso = _ms_to_iso(1704067200000)
        assert iso.startswith("2024-01-01T00:00:00")
        assert "+00:00" in iso or "Z" in iso

    def test_window_dir_label_format(self):
        # 2024-01-01T00:00:00Z = 1704067200000 ms
        # + 90d (含 2024 闰年) = 2024-03-31T00:00:00Z = 1711920000000 ms
        # 实际 1711747200000 ms = 2024-03-29T00:00:00Z（闰年 Feb 29 让 90d 偏早一天）
        spec = WindowSpec(idx=0, start_ts=1704067200000, end_ts=1711747200000)
        label = _window_dir_label(spec)
        assert label == "w00_2024-01-01_2024-03-29"


# ────────────────────────────────────────────────────────────────────
# run_walkforward() 端到端
# ────────────────────────────────────────────────────────────────────
class TestRunWalkforwardEndToEnd:
    """用 BTC 1h 数据 + 30d/100d 配置（~6 窗口）做端到端测试。"""

    def test_creates_output_structure(self, tmp_path):
        """端到端：~6 窗口、每个窗口的 fragility_scan 全套文件 + walkforward meta/result。"""
        out_dir = tmp_path / "wf"
        summaries = run_walkforward(
            scan_name="test-wf",
            inst_id="BTC-USDT-SWAP",
            bar="1h",
            strategy_full="A_EMA20_BREAKOUT",
            slippage_bps_list=[5, 10],
            fee_bps_list=[5.5],
            leverage=5,
            initial_capital=10000.0,
            window_days=30,
            stride_days=100,
            out_dir=out_dir,
        )

        # 1. 返回 summaries
        assert len(summaries) >= 3  # 至少 3 个窗口
        assert all(s.total_cells == 2 for s in summaries)  # 2 cells × N windows
        assert all(s.bar_count > 0 for s in summaries)

        # 2. walkforward 级 meta.json + result.md
        assert (out_dir / "meta.json").exists()
        assert (out_dir / "result.md").exists()
        assert (out_dir / "walkforward.py").exists()

        meta = json.loads((out_dir / "meta.json").read_text())
        assert meta["scan_name"] == "test-wf"
        assert meta["symbol"] == "BTC-USDT-SWAP"
        assert meta["bar"] == "1h"
        assert meta["window_days"] == 30
        assert meta["stride_days"] == 100
        assert meta["n_windows"] == len(summaries)
        assert len(meta["windows"]) == len(summaries)
        assert "git_commit" in meta

        # 3. 每个窗口的 fragility_scan 全套产物
        windows_dir = out_dir / "windows"
        assert windows_dir.is_dir()
        window_subdirs = sorted(windows_dir.iterdir())
        assert len(window_subdirs) == len(summaries)

        for wdir in window_subdirs:
            assert (wdir / "meta.json").exists()
            assert (wdir / "result.md").exists()
            assert (wdir / "result.txt").exists()
            assert (wdir / "scan.py").exists()
            cells_dir = wdir / "cells"
            assert cells_dir.is_dir()
            # 2 cells (slip5_fee5p5, slip10_fee5p5)
            assert len(list(cells_dir.iterdir())) == 2
            # 每个 cell 含 equity + trades
            for cell_dir in cells_dir.iterdir():
                assert (cell_dir / "equity.parquet").exists()
                assert (cell_dir / "trades.parquet").exists()

    def test_result_md_contains_analysis(self, tmp_path):
        """result.md 包含跨窗口一致性分析和 per-window 表格。"""
        out_dir = tmp_path / "wf"
        run_walkforward(
            scan_name="test-wf-analysis",
            inst_id="BTC-USDT-SWAP",
            bar="1h",
            strategy_full="A_EMA20_BREAKOUT",
            slippage_bps_list=[5],
            fee_bps_list=[5.5],
            leverage=5,
            initial_capital=10000.0,
            window_days=30,
            stride_days=100,
            out_dir=out_dir,
        )
        md = (out_dir / "result.md").read_text()
        # 关键章节
        assert "# Walk-forward Analysis: test-wf-analysis" in md
        assert "## 跨窗口一致性" in md
        assert "Viable 窗口占比" in md
        assert "## Per-Window 详细" in md
        assert "## 结论" in md
        assert "复现命令" in md
