# -*- coding: utf-8 -*-
"""
Portfolio._validate_schema() 单元测试

覆盖场景:
- 完整 schema → 通过
- 缺顶层字段 → fail-loud
- 缺 daily_stats 字段 → fail-loud
- 不存在的路径 → 走 default_state (不 raise)
"""

import json
from pathlib import Path
import pytest

from okx.code.portfolio import Portfolio


def _write_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _valid_state() -> dict:
    return {
        "version": "1.0.0",
        "updated_at": "2026-07-19T00:00:00Z",
        "positions": [],
        "daily_stats": {
            "date": "2026-07-19",
            "total_trades": 0,
            "loss_trades": 0,
            "consecutive_losses": 0,
            "total_pnl": 0.0,
            "total_fee": 0.0,
            "total_pnl_gross": 0.0,
            "last_loss_at": None,
            "emergency_stop_triggered": False,
        },
        "closed_positions": [],
    }


def test_load_with_complete_schema_succeeds(tmp_path):
    """完整 schema 应通过 validation"""
    p = tmp_path / "portfolio.json"
    _write_state(p, _valid_state())
    pf = Portfolio(portfolio_path=str(p))
    assert pf._data["version"] == "1.0.0"
    assert pf._data["daily_stats"]["total_pnl"] == 0.0


def test_load_missing_top_level_keys_raises(tmp_path):
    """缺顶层字段应 fail-loud（防 sync bug 静默丢字段）"""
    p = tmp_path / "portfolio-bad.json"
    _write_state(p, {"version": "1.0.0", "positions": []})  # 缺 3 个字段
    with pytest.raises(ValueError, match="missing top-level keys"):
        Portfolio(portfolio_path=str(p))


def test_load_missing_daily_stats_keys_raises(tmp_path):
    """缺 daily_stats 字段应 fail-loud"""
    bad = _valid_state()
    bad["daily_stats"] = {"date": "2026-07-19", "total_trades": 0}  # 缺 7 个
    p = tmp_path / "portfolio-bad-daily.json"
    _write_state(p, bad)
    with pytest.raises(ValueError, match="daily_stats schema invalid"):
        Portfolio(portfolio_path=str(p))


def test_load_nonexistent_path_uses_default_state(tmp_path):
    """文件不存在 → 走 default_state (不应 raise, 这是 cold-start 路径)"""
    p = tmp_path / "does-not-exist.json"
    pf = Portfolio(portfolio_path=str(p))
    assert pf._data["version"] == "1.0.0"
    assert pf._data["positions"] == []
    assert pf._data["daily_stats"]["total_trades"] == 0


def test_validation_error_message_includes_path(tmp_path):
    """错误信息应包含 path (方便定位是哪个 portfolio 损坏)"""
    p = tmp_path / "specific-bad-portfolio.json"
    _write_state(p, {"version": "1.0.0"})
    with pytest.raises(ValueError, match="specific-bad-portfolio"):
        Portfolio(portfolio_path=str(p))
