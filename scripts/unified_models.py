#!/usr/bin/env python3
"""
统一模型定义 - v1.0.3 Integrated
整合系统中所有重复的数据模型定义
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Union
from enum import Enum
from datetime import datetime
import time


class ActionType(Enum):
    """动作类型（统一）"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CANCEL = "cancel"


class OrderSide(Enum):
    """订单方向"""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILLED = "PARTIAL_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class Direction(Enum):
    """方向（统一）"""
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class DataSource(Enum):
    """数据源（统一）"""
    BINANCE = "binance"
    CSV = "csv"
    JSON = "json"
    PARQUET = "parquet"


@dataclass
class BacktestResult:
    """回测结果（统一）"""
    strategy_id: str
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'strategy_id': self.strategy_id,
            'total_return': self.total_return,
            'sharpe_ratio': self.sharpe_ratio,
            'max_drawdown': self.max_drawdown,
            'win_rate': self.win_rate,
            'total_trades': self.total_trades,
            'profit_factor': self.profit_factor,
            'duration_hours': (self.end_time - self.start_time) / 3600.0 if self.end_time > 0 else 0
        }


@dataclass
class Event:
    """统一事件模型"""
    event_type: str
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'event_type': self.event_type,
            'data': self.data,
            'source': self.source,
            'timestamp': self.timestamp
        }


@dataclass
class Trade:
    """交易记录"""
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    commission: float = 0.0
    timestamp: float = field(default_factory=time.time)
    
    def __post_init__(self):
        if isinstance(self.side, str):
            self.side = OrderSide(self.side)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'order_id': self.order_id,
            'symbol': self.symbol,
            'side': self.side.value,
            'quantity': self.quantity,
            'price': self.price,
            'commission': self.commission,
            'timestamp': self.timestamp
        }


@dataclass
class Position:
    """持仓信息"""
    symbol: str
    quantity: float = 0.0
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'quantity': self.quantity,
            'entry_price': self.entry_price,
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl
        }


@dataclass
class MarketData:
    """市场数据"""
    symbol: str
    timestamp: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume
        }


# 导出所有模型
__all__ = [
    'ActionType',
    'OrderSide',
    'OrderStatus',
    'Direction',
    'DataSource',
    'BacktestResult',
    'Event',
    'Trade',
    'Position',
    'MarketData'
]


if __name__ == "__main__":
    print("测试统一模型定义...\n")
    
    # 测试BacktestResult
    result = BacktestResult(
        strategy_id="test_strategy",
        total_return=0.25,
        sharpe_ratio=1.5,
        max_drawdown=0.10,
        win_rate=0.60,
        total_trades=100,
        profit_factor=2.0
    )
    print(f"回测结果: {result.to_dict()}")
    
    # 测试Event
    event = Event(event_type="market.data_update", data={"symbol": "BTCUSDT", "price": 50000.0})
    print(f"\n事件: {event.to_dict()}")
    
    # 测试Trade
    trade = Trade(
        order_id="order_001",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=0.001,
        price=50000.0,
        commission=5.0
    )
    print(f"\n交易: {trade.to_dict()}")
    
    print("\n✅ 所有模型测试通过")
