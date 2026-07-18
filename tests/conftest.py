"""pytest 配置"""
import json
import warnings
from pathlib import Path

import pytest

# 过滤 pytest 内部关于 file handle 关闭的警告
# （来自 cfg fixture 复制 config.json 后未显式关闭文件句柄）
warnings.filterwarnings(
    "ignore",
    category=pytest.PytestUnraisableExceptionWarning,
)


# ─────────────────────────────────────────────────────────────
# 共享 fixtures
# ─────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REAL_CFG = _PROJECT_ROOT / "state" / "config.json"


@pytest.fixture
def cfg(tmp_path):
    """从真实 config.json 复制一份到 tmp_path 并加载为 Config 实例。

    用途：避免直接污染 state/config.json；同时 reset Config 单例。
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    test_cfg = state_dir / "config.json"
    test_cfg.write_text(_REAL_CFG.read_text())

    from okx.code.config import Config
    Config._instance = None
    return Config(str(test_cfg))


@pytest.fixture
def real_config_dict():
    """直接读取真实 state/config.json 字典（不实例化 Config），用于校验版本/字段。"""
    return json.loads(_REAL_CFG.read_text())