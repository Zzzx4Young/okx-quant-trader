"""pytest 配置"""
import warnings
import pytest

# 过滤 pytest 内部关于 file handle 关闭的警告
# （来自 cfg fixture 复制 config.json 后未显式关闭文件句柄）
warnings.filterwarnings(
    "ignore",
    category=pytest.PytestUnraisableExceptionWarning,
)