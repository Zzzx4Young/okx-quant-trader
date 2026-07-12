# -*- coding: utf-8 -*-
"""
OKX 量化交易系统 — 核心代码包

推荐用法::

    from okx.code import OKXClient, Runner, Portfolio, RiskCalculator, SignalEngine
    from okx.code import get_config, TradeLogger, Config

CLI 运维入口（不 eager import，避免与 python -m okx.code.cli 冲突）::

    from okx.code import cli
    cli.run_heartbeat_check()

或直接 CLI::

    python -m okx.code.cli status
    python -m okx.code.cli run

要求从 okx/ 的父目录运行（run.sh 自动处理）。
"""

# 核心客户端
from ._http import HTTPClient
from .client import OKXClient
from .auth import Signer
from .utils import OKXError

# API 模块
from .market import MarketAPI
from .public import PublicAPI
from .trade import TradeAPI
from .account import AccountAPI
from .asset import AssetAPI
from .subaccount import SubAccountAPI

# 交易引擎
from .config import Config, load_config, get_config
from .portfolio import Portfolio
from .logger import TradeLogger
from .risk import RiskCalculator, RiskResult
from .signal import SignalEngine, Signal
from .runner import Runner

# 通知层
from .notifier import TelegramNotifier, NoopNotifier

__all__ = [
    # 核心客户端
    "OKXClient",
    "HTTPClient",
    "Signer",
    "OKXError",
    # API 模块
    "MarketAPI",
    "PublicAPI",
    "TradeAPI",
    "AccountAPI",
    "AssetAPI",
    "SubAccountAPI",
    # 交易引擎
    "Config",
    "load_config",
    "get_config",
    "Portfolio",
    "TradeLogger",
    "RiskCalculator",
    "RiskResult",
    "SignalEngine",
    "Signal",
    "Runner",
    # 通知层
    "TelegramNotifier",
    "NoopNotifier",
    # CLI 模块（不 eagerly import 子函数，避免与 python -m 冲突）
    "cli",
]