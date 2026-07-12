# -*- coding: utf-8 -*-
"""
OKX 交易日志记录器

将每笔交易成交记录写入 logs/trades/YYYY-MM-DD.csv
"""

import csv
import os
import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List, Optional


class TradeLogger:
    """交易日志写入器（线程安全）"""

    CSV_HEADERS = [
        "timestamp",
        "symbol",
        "direction",
        "action",          # OPEN / CLOSE
        "price",
        "size",
        "leverage",
        "margin",
        "order_id",
        "strategy",
        "pnl",             # 平仓盈亏（仅 CLOSE）
        "roe_percent",     # 盈亏百分比（仅 CLOSE）
        "fee",             # 手续费
        "slippage",        # 滑点估算
        "pnl_net",         # 净盈亏（pnl - fee - slippage）
        "note",
    ]

    def __init__(self, log_dir: Optional[str] = None):
        if log_dir is None:
            base = Path(__file__).parent.parent
            log_dir = str(base / "logs" / "trades")
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._daily_path: Optional[Path] = None
        self._ensure_today_file()

    def _today_csv(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _today_path(self) -> Path:
        return self._log_dir / f"{self._today_csv()}.csv"

    def _ensure_today_file(self) -> None:
        """确保今日 CSV 文件存在且有表头"""
        path = self._today_path()
        if path != self._daily_path:
            # 跨日了，重置
            self._daily_path = path
            if not path.exists():
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=self.CSV_HEADERS)
                    writer.writeheader()

    def log(
        self,
        symbol: str,
        direction: str,
        action: str,
        price: float,
        size: float,
        leverage: int,
        order_id: str,
        strategy: str,
        margin: float = 0.0,
        pnl: float = 0.0,
        roe_percent: float = 0.0,
        fee: float = 0.0,
        slippage: float = 0.0,
        note: str = "",
    ) -> str:
        """
        记录一笔交易

        :param symbol: 交易对，如 'BTCUSDT'
        :param direction: 'long' 或 'short'
        :param action: 'OPEN' 或 'CLOSE'
        :param price: 成交价格
        :param size: 成交数量（合约张数）
        :param leverage: 杠杆倍数
        :param order_id: 订单 ID
        :param strategy: 策略名称
        :param margin: 保证金
        :param pnl: 平仓盈亏（OPEN 时为 0）
        :param roe_percent: 收益率百分比（OPEN 时为 0）
        :param fee: 手续费
        :param slippage: 滑点估算
        :param note: 备注
        :return: 写入的 CSV 行内容
        """
        with self._lock:
            self._ensure_today_file()
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            pnl_net = round(pnl - fee - slippage, 6)

            row = {
                "timestamp": timestamp,
                "symbol": symbol,
                "direction": direction,
                "action": action,
                "price": self._round_price(price),
                "size": self._round_size(size),
                "leverage": leverage,
                "margin": self._round_price(margin),
                "order_id": order_id,
                "strategy": strategy,
                "pnl": round(pnl, 4),
                "roe_percent": round(roe_percent, 4),
                "fee": round(fee, 4),
                "slippage": round(slippage, 6),
                "pnl_net": round(pnl_net, 4),
                "note": note,
            }

            with open(self._daily_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.CSV_HEADERS)
                writer.writerow(row)

            return timestamp

    def log_open(
        self,
        symbol: str,
        direction: str,
        price: float,
        size: float,
        leverage: int,
        order_id: str,
        strategy: str,
        margin: float,
        fee: float = 0.0,
        slippage: float = 0.0,
        note: str = "",
    ) -> str:
        """快捷方法：记录开仓"""
        return self.log(
            symbol=symbol,
            direction=direction,
            action="OPEN",
            price=price,
            size=size,
            leverage=leverage,
            order_id=order_id,
            strategy=strategy,
            margin=margin,
            fee=fee,
            slippage=slippage,
            note=note,
        )

    def log_close(
        self,
        symbol: str,
        direction: str,
        price: float,
        size: float,
        leverage: int,
        order_id: str,
        strategy: str,
        margin: float,
        pnl: float,
        roe_percent: float,
        fee: float,
        slippage: float,
        note: str = "",
    ) -> str:
        """快捷方法：记录平仓"""
        return self.log(
            symbol=symbol,
            direction=direction,
            action="CLOSE",
            price=price,
            size=size,
            leverage=leverage,
            order_id=order_id,
            strategy=strategy,
            margin=margin,
            pnl=pnl,
            roe_percent=roe_percent,
            fee=fee,
            slippage=slippage,
            note=note,
        )

    def read_today(self) -> List[Dict[str, str]]:
        """读取今日所有交易记录"""
        with self._lock:
            self._ensure_today_file()
            rows = []
            with open(self._daily_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
            return rows

    def get_daily_summary(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        获取指定日期的交易汇总

        :param date: 日期字符串，None 表示今日
        :return: 包含总交易次数、盈亏、手续费等统计
        """
        if date is None:
            date = self._today_csv()
        path = self._log_dir / f"{date}.csv"
        if not path.exists():
            return {"date": date, "total_trades": 0, "pnl_net": 0.0}

        total_trades = 0
        pnl_net = 0.0
        total_fee = 0.0
        total_pnl = 0.0
        opens = 0
        closes = 0

        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_trades += 1
                pnl_net += float(row.get("pnl_net", 0))
                total_fee += float(row.get("fee", 0))
                total_pnl += float(row.get("pnl", 0))
                if row.get("action") == "OPEN":
                    opens += 1
                elif row.get("action") == "CLOSE":
                    closes += 1

        return {
            "date": date,
            "total_trades": total_trades,
            "opens": opens,
            "closes": closes,
            "pnl_gross": round(total_pnl, 4),
            "total_fee": round(total_fee, 4),
            "pnl_net": round(pnl_net, 4),
        }

    @staticmethod
    def _round_price(price: float) -> float:
        return round(price, 8)

    @staticmethod
    def _round_size(size: float) -> float:
        return round(size, 8)

    def __repr__(self) -> str:
        return f"<TradeLogger: {self._log_dir}>"
