#!/usr/bin/env python3
"""
订单簿实时接入 - Phase 6 核心组件
从Binance WebSocket接收L2订单簿数据，实时计算微观结构指标
"""

import time
import json
import asyncio
import threading
from typing import Dict, List, Optional, Deque
from collections import deque, defaultdict
from dataclasses import dataclass, field
from enum import Enum
import numpy as np

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("orderbook_feeder")
except ImportError:
    import logging
    logger = logging.getLogger("orderbook_feeder")

# 导入事件总线
try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False


class Side(Enum):
    """订单方向"""
    BID = "bid"
    ASK = "ask"


@dataclass
class OrderLevel:
    """订单簿层级"""
    price: float
    quantity: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            'price': self.price,
            'quantity': self.quantity,
            'timestamp': self.timestamp
        }


@dataclass
class OrderBookSnapshot:
    """订单簿快照"""
    symbol: str
    bids: List[OrderLevel] = field(default_factory=list)
    asks: List[OrderLevel] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    last_update_id: int = 0

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'bids': [level.to_dict() for level in self.bids[:10]],  # 仅保留前10档
            'asks': [level.to_dict() for level in self.asks[:10]],
            'timestamp': self.timestamp,
            'last_update_id': self.last_update_id
        }


@dataclass
class MicrostructureMetrics:
    """微观结构指标"""
    symbol: str
    timestamp: float = field(default_factory=time.time)
    mid_price: float = 0.0
    spread: float = 0.0
    spread_bps: float = 0.0
    bid_ask_imbalance: float = 0.0
    orderbook_slope: float = 0.0
    depth_ratio: float = 0.0
    volume_weighted_price: float = 0.0
    volatility: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp,
            'mid_price': self.mid_price,
            'spread': self.spread,
            'spread_bps': self.spread_bps,
            'bid_ask_imbalance': self.bid_ask_imbalance,
            'orderbook_slope': self.orderbook_slope,
            'depth_ratio': self.depth_ratio,
            'volume_weighted_price': self.volume_weighted_price,
            'volatility': self.volatility
        }


class OrderBookFeeder:
    """订单簿数据接收器"""

    def __init__(self, symbol: str, depth: int = 20):
        """
        初始化订单簿接收器

        Args:
            symbol: 交易对
            depth: 订单簿深度
        """
        self.symbol = symbol
        self.depth = depth

        # 订单簿状态
        self.bids: List[OrderLevel] = []
        self.asks: List[OrderLevel] = []
        self.last_update_id = 0
        self.is_synced = False

        # 历史数据（用于计算波动率等）
        self.mid_price_history: Deque[float] = deque(maxlen=100)
        self.spread_history: Deque[float] = deque(maxlen=100)

        # WebSocket连接
        self.ws_task: Optional[asyncio.Task] = None
        self.is_running = False

        # 回调函数
        self.snapshot_callbacks: List[callable] = []
        self.metrics_callbacks: List[callable] = []

    def add_snapshot_callback(self, callback: callable) -> None:
        """添加快照回调"""
        self.snapshot_callbacks.append(callback)

    def add_metrics_callback(self, callback: callable) -> None:
        """添加指标回调"""
        self.metrics_callbacks.append(callback)

    async def connect(self) -> None:
        """连接Binance WebSocket"""
        self.is_running = True

        # 构造WebSocket URL
        ws_url = f"wss://stream.binance.com:9443/ws/{self.symbol.lower()}@depth20@100ms"

        logger.info(f"连接订单簿WebSocket: {ws_url}")

        # 模拟WebSocket连接（实际实现需要使用websockets库）
        # 这里仅展示框架
        try:
            # 模拟接收数据
            while self.is_running:
                await asyncio.sleep(0.1)

                # 模拟接收订单簿更新
                await self._process_orderbook_update(self._generate_mock_update())

        except Exception as e:
            logger.error(f"WebSocket连接异常: {e}")
            self.is_running = False

    def _generate_mock_update(self) -> Dict:
        """生成模拟订单簿更新"""
        mid_price = 50000.0 + np.random.randn() * 100

        # 生成bids
        bids = []
        for i in range(self.depth):
            price = mid_price - (i + 1) * 0.5 + np.random.randn() * 0.1
            quantity = abs(np.random.randn()) * 10 + 0.5
            bids.append({'price': price, 'quantity': quantity})

        # 生成asks
        asks = []
        for i in range(self.depth):
            price = mid_price + (i + 1) * 0.5 + np.random.randn() * 0.1
            quantity = abs(np.random.randn()) * 10 + 0.5
            asks.append({'price': price, 'quantity': quantity})

        return {
            'lastUpdateId': int(time.time() * 1000),
            'bids': bids,
            'asks': asks
        }

    async def _process_orderbook_update(self, update: Dict) -> None:
        """
        处理订单簿更新

        Args:
            update: 订单簿更新数据
        """
        try:
            # 第一层防御：数据校验
            if 'bids' not in update or 'asks' not in update:
                logger.warning("无效的订单簿更新: 缺少bids或asks")
                return

            # 更新bids
            self.bids = [OrderLevel(price=b[0], quantity=b[1]) for b in update['bids'][:self.depth]]
            self.bids.sort(key=lambda x: x.price, reverse=True)  # 降序

            # 更新asks
            self.asks = [OrderLevel(price=a[0], quantity=a[1]) for a in update['asks'][:self.depth]]
            self.asks.sort(key=lambda x: x.price)  # 升序

            self.last_update_id = update.get('lastUpdateId', 0)
            self.is_synced = True

            # 第二层防御：计算微观结构指标
            metrics = self._calculate_metrics()

            # 第三层防御：触发回调
            if self.bids and self.asks:
                snapshot = OrderBookSnapshot(
                    symbol=self.symbol,
                    bids=self.bids.copy(),
                    asks=self.asks.copy(),
                    timestamp=time.time(),
                    last_update_id=self.last_update_id
                )

                for callback in self.snapshot_callbacks:
                    try:
                        callback(snapshot)
                    except Exception as e:
                        logger.error(f"快照回调异常: {e}")

                for callback in self.metrics_callbacks:
                    try:
                        callback(metrics)
                    except Exception as e:
                        logger.error(f"指标回调异常: {e}")

                # 广播事件（Phase 5.6新增）
                if EVENT_BUS_AVAILABLE:
                    self._publish_orderbook_update_event(snapshot, metrics)

        except Exception as e:
            logger.error(f"处理订单簿更新异常: {e}")

    def _calculate_metrics(self) -> MicrostructureMetrics:
        """
        计算微观结构指标

        Returns:
            微观结构指标
        """
        try:
            # 第一层防御：数据存在性检查
            if not self.bids or not self.asks:
                return MicrostructureMetrics(symbol=self.symbol)

            # 基础价格
            best_bid = self.bids[0].price
            best_ask = self.asks[0].price
            mid_price = (best_bid + best_ask) / 2.0

            # 计算价差
            spread = best_ask - best_bid
            spread_bps = (spread / mid_price) * 10000 if mid_price > 0 else 0.0

            # 第二层防御：除零保护
            total_bid_vol = sum(b.quantity for b in self.bids)
            total_ask_vol = sum(a.quantity for a in self.asks)

            # 买卖不平衡
            bid_ask_imbalance = (total_bid_vol - total_ask_vol) / max(0.01, total_bid_vol + total_ask_vol)

            # 订单簿斜率（前5档）
            if len(self.bids) >= 5 and len(self.asks) >= 5:
                bid_prices = [b.price for b in self.bids[:5]]
                ask_prices = [a.price for a in self.asks[:5]]
                bid_slope = (bid_prices[0] - bid_prices[4]) / 4 if bid_prices[4] > 0 else 0.0
                ask_slope = (ask_prices[4] - ask_prices[0]) / 4 if ask_prices[0] > 0 else 0.0
                orderbook_slope = (bid_slope + ask_slope) / 2.0
            else:
                orderbook_slope = 0.0

            # 深度比率
            depth_ratio = total_bid_vol / max(0.01, total_ask_vol)

            # 成交量加权价格
            if total_bid_vol + total_ask_vol > 0:
                vwap = (
                    sum(b.price * b.quantity for b in self.bids) +
                    sum(a.price * a.quantity for a in self.asks)
                ) / (total_bid_vol + total_ask_vol)
            else:
                vwap = mid_price

            # 波动率（基于历史中间价）
            self.mid_price_history.append(mid_price)
            if len(self.mid_price_history) >= 20:
                volatility = np.std(list(self.mid_price_history)) / max(0.01, mid_price)
            else:
                volatility = 0.0

            return MicrostructureMetrics(
                symbol=self.symbol,
                timestamp=time.time(),
                mid_price=mid_price,
                spread=spread,
                spread_bps=spread_bps,
                bid_ask_imbalance=bid_ask_imbalance,
                orderbook_slope=orderbook_slope,
                depth_ratio=depth_ratio,
                volume_weighted_price=vwap,
                volatility=volatility
            )

        except Exception as e:
            logger.error(f"计算微观结构指标异常: {e}")
            return MicrostructureMetrics(symbol=self.symbol)

    def _publish_orderbook_update_event(self, snapshot: OrderBookSnapshot, metrics: MicrostructureMetrics) -> None:
        """
        广播订单簿更新事件

        Args:
            snapshot: 订单簿快照
            metrics: 微观结构指标
        """
        try:
            event_bus = get_event_bus()
            event_bus.publish(
                "market.orderbook_update",
                {
                    "symbol": self.symbol,
                    "timestamp": snapshot.timestamp,
                    "mid_price": metrics.mid_price,
                    "spread_bps": metrics.spread_bps,
                    "bid_ask_imbalance": metrics.bid_ask_imbalance,
                    "depth_ratio": metrics.depth_ratio,
                    "volatility": metrics.volatility,
                    "snapshot": snapshot.to_dict()
                },
                source="orderbook_feeder"
            )
        except Exception as e:
            logger.error(f"订单簿更新事件广播失败: {e}")

    def get_snapshot(self) -> Optional[OrderBookSnapshot]:
        """获取当前快照"""
        if not self.bids or not self.asks:
            return None

        return OrderBookSnapshot(
            symbol=self.symbol,
            bids=self.bids.copy(),
            asks=self.asks.copy(),
            timestamp=time.time(),
            last_update_id=self.last_update_id
        )

    def get_metrics(self) -> Optional[MicrostructureMetrics]:
        """获取当前指标"""
        if not self.bids or not self.asks:
            return None

        return self._calculate_metrics()

    def stop(self) -> None:
        """停止接收"""
        self.is_running = False
        logger.info(f"订单簿接收器已停止: {self.symbol}")


if __name__ == "__main__":
    # 测试代码
    async def test_callback(snapshot: OrderBookSnapshot):
        print(f"收到订单簿快照: {snapshot.symbol}, "
              f"mid={(snapshot.bids[0].price + snapshot.asks[0].price)/2:.2f}")

    feeder = OrderBookFeeder("BTCUSDT", depth=20)
    feeder.add_snapshot_callback(test_callback)

    # 运行10秒
    print("启动订单簿接收器（模拟模式）...")
    asyncio.run(asyncio.wait_for(feeder.connect(), timeout=10.0))

    metrics = feeder.get_metrics()
    if metrics:
        print(f"\n微观结构指标:")
        print(json.dumps(metrics.to_dict(), indent=2, ensure_ascii=False))
