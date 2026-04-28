#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("order_execution_engine_v60")
except ImportError:
    import logging
    logger = logging.getLogger("order_execution_engine_v60")
"""
开单执行引擎 v1.0.2（第4层：开单执行）
v1.0.2 增强版：集成TTL超时撤单 + 幂等性控制 + 异步任务管理

核心升级：
1. clientOrderId 生成（幂等性键）
2. 重复订单检测（300秒TTL）
3. TTL超时撤单（默认800ms）
4. 异步任务管理（超时监控）
5. 订单状态完整跟踪
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import OrderedDict
import numpy as np


class OrderType(Enum):
    """订单类型"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderSide(Enum):
    """订单方向"""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """订单状态（完整生命周期）"""
    NEW = "NEW"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class Order:
    """订单数据结构"""
    client_order_id: str  # 客户端订单ID（幂等性键）
    exchange_order_id: Optional[str] = None  # 交易所订单ID
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.LIMIT
    quantity: float = 0.0
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "GTC"
    
    # 状态字段
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    fee: float = 0.0
    slippage: float = 0.0
    
    # 时间字段
    create_time: float = field(default_factory=time.time)
    submit_time: float = 0.0
    ack_time: float = 0.0
    fill_time: float = 0.0
    cancel_time: float = 0.0
    update_time: float = field(default_factory=time.time)
    
    # TTL字段
    ttl_ms: int = 800
    expire_time: float = 0.0
    
    # 元数据
    strategy_id: Optional[str] = None
    tags: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'client_order_id': self.client_order_id,
            'exchange_order_id': self.exchange_order_id,
            'symbol': self.symbol,
            'side': self.side.value,
            'order_type': self.order_type.value,
            'quantity': self.quantity,
            'price': self.price,
            'stop_price': self.stop_price,
            'time_in_force': self.time_in_force,
            'status': self.status.value,
            'filled_quantity': self.filled_quantity,
            'avg_fill_price': self.avg_fill_price,
            'fee': self.fee,
            'slippage': self.slippage,
            'create_time': self.create_time,
            'update_time': self.update_time,
            'ttl_ms': self.ttl_ms,
            'strategy_id': self.strategy_id
        }


@dataclass
class ExecutionResult:
    """执行结果"""
    client_order_id: str
    status: OrderStatus
    filled_quantity: float
    avg_fill_price: float
    execution_time: float
    fee: float
    slippage: float
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'client_order_id': self.client_order_id,
            'status': self.status.value,
            'filled_quantity': self.filled_quantity,
            'avg_fill_price': self.avg_fill_price,
            'execution_time': self.execution_time,
            'fee': self.fee,
            'slippage': self.slippage,
            'error_message': self.error_message
        }


class OrderDedupManager:
    """订单去重管理器"""
    
    def __init__(self, dedup_ttl_seconds: int = 300):
        """
        初始化去重管理器
        
        Args:
            dedup_ttl_seconds: 去重缓存TTL（秒）
        """
        self.dedup_ttl_seconds = dedup_ttl_seconds
        self.dedup_cache: OrderedDict[str, float] = OrderedDict()  # client_id -> expire_time
    
    def is_duplicate(self, client_order_id: str) -> bool:
        """
        检查是否重复订单
        
        Args:
            client_order_id: 客户端订单ID
        
        Returns:
            是否重复
        """
        now = time.time()
        
        # 清理过期缓存
        expired = [cid for cid, exp in self.dedup_cache.items() if exp < now]
        for cid in expired:
            del self.dedup_cache[cid]
        
        # 检查是否存在
        return client_order_id in self.dedup_cache
    
    def register(self, client_order_id: str):
        """
        注册订单ID
        
        Args:
            client_order_id: 客户端订单ID
        """
        expire_time = time.time() + self.dedup_ttl_seconds
        self.dedup_cache[client_order_id] = expire_time
    
    def clear_expired(self):
        """清理过期缓存"""
        now = time.time()
        expired = [cid for cid, exp in self.dedup_cache.items() if exp < now]
        for cid in expired:
            del self.dedup_cache[cid]


class OrderExecutionEnginev1.0.2:
    """
    订单执行引擎 v1.0.2
    
    核心功能：
    1. 幂等性控制（clientOrderId）
    2. TTL超时撤单
    3. 异步任务管理
    4. 完整订单状态跟踪
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化执行引擎
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        
        # 核心参数
        self.ttl_ms = self.config.get('ttl_ms', 800)  # 默认800ms TTL
        self.dedup_ttl_seconds = self.config.get('dedup_ttl_seconds', 300)  # 去重缓存TTL
        self.fee_rate = self.config.get('fee_rate', 0.001)
        self.max_order_size = self.config.get('max_order_size', 1000.0)
        
        # 去重管理器
        self.dedup_manager = OrderDedupManager(self.dedup_ttl_seconds)
        
        # 订单存储
        self.orders: Dict[str, Order] = {}  # client_order_id -> Order
        self.pending_orders: Dict[str, asyncio.Task] = {}  # client_order_id -> Task
        
        # 统计数据
        self.stats = {
            'total_orders': 0,
            'filled_orders': 0,
            'cancelled_orders': 0,
            'rejected_orders': 0,
            'expired_orders': 0,
            'duplicate_rejected': 0
        }
    
    def generate_client_order_id(
        self,
        symbol: str,
        side: OrderSide,
        strategy_id: Optional[str] = None
    ) -> str:
        """
        生成唯一的clientOrderId
        
        格式：pt_{symbol}_{side}_{timestamp}_{uuid}
        
        Args:
            symbol: 交易品种
            side: 订单方向
            strategy_id: 策略ID
        
        Returns:
            唯一的clientOrderId
        """
        timestamp = int(time.time() * 1000)
        uid = uuid.uuid4().hex[:8]
        return f"pt_{symbol}_{side.value}_{timestamp}_{uid}"
    
    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
        strategy_id: Optional[str] = None
    ) -> Optional[ExecutionResult]:
        """
        提交订单（v1.0.2增强版）
        
        Args:
            symbol: 交易品种
            side: 订单方向
            order_type: 订单类型
            quantity: 数量
            price: 价格
            stop_price: 止损价
            client_order_id: 客户端订单ID（可选，不提供则自动生成）
            strategy_id: 策略ID
        
        Returns:
            执行结果
        """
        # 生成clientOrderId
        if not client_order_id:
            client_order_id = self.generate_client_order_id(symbol, side, strategy_id)
        
        # 检查重复
        if self.dedup_manager.is_duplicate(client_order_id):
            self.stats['duplicate_rejected'] += 1
            return ExecutionResult(
                client_order_id=client_order_id,
                status=OrderStatus.REJECTED,
                filled_quantity=0.0,
                avg_fill_price=0.0,
                execution_time=time.time(),
                fee=0.0,
                slippage=0.0,
                error_message=f"Duplicate order: {client_order_id}"
            )
        
        # 注册去重
        self.dedup_manager.register(client_order_id)
        
        # 创建订单
        order = Order(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            ttl_ms=self.ttl_ms,
            strategy_id=strategy_id,
            status=OrderStatus.NEW
        )
        
        # 保存订单
        self.orders[client_order_id] = order
        self.stats['total_orders'] += 1
        
        # 提交订单
        result = await self._execute_order(order)
        
        # 限价单启动超时监控
        if order_type == OrderType.LIMIT and result.status == OrderStatus.ACKNOWLEDGED:
            task = asyncio.create_task(self._auto_cancel_on_ttl(client_order_id))
            self.pending_orders[client_order_id] = task
        
        return result
    
    async def _execute_order(self, order: Order) -> ExecutionResult:
        """
        执行订单（模拟）
        
        Args:
            order: 订单对象
        
        Returns:
            执行结果
        """
        order.status = OrderStatus.SUBMITTING
        order.submit_time = time.time()
        
        # 模拟网络延迟
        await asyncio.sleep(0.01)
        
        # 模拟订单确认
        order.status = OrderStatus.ACKNOWLEDGED
        order.ack_time = time.time()
        
        # 模拟成交（简化版）
        if order.order_type == OrderType.MARKET:
            # 市价单直接成交
            execution_price = order.price or 50000.0
            order.status = OrderStatus.FILLED
            order.filled_quantity = order.quantity
            order.avg_fill_price = execution_price
            order.fill_time = time.time()
            
            # 计算费用和滑点
            order.fee = order.filled_quantity * execution_price * self.fee_rate
            order.slippage = 0.0  # 市价单滑点简化为0
            
            self.stats['filled_orders'] += 1
            
            return ExecutionResult(
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_quantity=order.filled_quantity,
                avg_fill_price=order.avg_fill_price,
                execution_time=order.fill_time,
                fee=order.fee,
                slippage=order.slippage
            )
        else:
            # 限价单返回确认，等待后续成交或超时
            return ExecutionResult(
                client_order_id=order.client_order_id,
                status=OrderStatus.ACKNOWLEDGED,
                filled_quantity=0.0,
                avg_fill_price=0.0,
                execution_time=order.ack_time,
                fee=0.0,
                slippage=0.0
            )
    
    async def _auto_cancel_on_ttl(self, client_order_id: str):
        """
        TTL超时自动撤单
        
        Args:
            client_order_id: 客户端订单ID
        """
        try:
            await asyncio.sleep(self.ttl_ms / 1000.0)
            
            if client_order_id in self.orders:
                order = self.orders[client_order_id]
                
                # 只有未成交的订单才撤单
                if order.status == OrderStatus.ACKNOWLEDGED:
                    await self.cancel_order(client_order_id)
        except asyncio.CancelledError:
            # 任务被取消，正常情况
            pass
        except Exception as e:
            logger.error(f"Error in TTL cancel task: {e}")
    
    async def cancel_order(self, client_order_id: str) -> bool:
        """
        取消订单
        
        Args:
            client_order_id: 客户端订单ID
        
        Returns:
            是否成功
        """
        if client_order_id not in self.orders:
            return False
        
        order = self.orders[client_order_id]
        
        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]:
            return False
        
        # 取消超时监控任务
        if client_order_id in self.pending_orders:
            task = self.pending_orders[client_order_id]
            task.cancel()
            del self.pending_orders[client_order_id]
        
        # 更新状态
        order.status = OrderStatus.CANCELLED
        order.cancel_time = time.time()
        
        self.stats['cancelled_orders'] += 1
        
        return True
    
    def get_order(self, client_order_id: str) -> Optional[Order]:
        """获取订单"""
        return self.orders.get(client_order_id)
    
    def get_active_orders(self) -> List[Order]:
        """获取活跃订单"""
        active_statuses = [
            OrderStatus.NEW, OrderStatus.SUBMITTING, 
            OrderStatus.ACKNOWLEDGED, OrderStatus.PARTIALLY_FILLED
        ]
        return [order for order in self.orders.values() if order.status in active_statuses]
    
    def get_stats(self) -> Dict:
        """获取统计数据"""
        return self.stats.copy()
    
    async def cleanup(self):
        """清理资源"""
        # 取消所有待处理任务
        for task in self.pending_orders.values():
            task.cancel()
        self.pending_orders.clear()
        
        # 清理过期缓存
        self.dedup_manager.clear_expired()


def main():
    """命令行测试"""
    parser = argparse.ArgumentParser(description="订单执行引擎 v1.0.2 测试")
    parser.add_argument('--action', choices=['submit', 'cancel', 'stats', 'cleanup'], default='submit')
    parser.add_argument('--symbol', type=str, default='BTCUSDT')
    parser.add_argument('--side', type=str, default='BUY', choices=['BUY', 'SELL'])
    parser.add_argument('--quantity', type=float, default=0.001)
    parser.add_argument('--price', type=float, default=50000.0)
    parser.add_argument('--client_order_id', type=str)
    
    args = parser.parse_args()
    
    # 创建执行引擎
    config = {
        'ttl_ms': 800,
        'dedup_ttl_seconds': 300,
        'fee_rate': 0.0004
    }
    engine = OrderExecutionEnginev1.0.2(config)
    
    if args.action == 'submit':
        async def test_submit():
            result = await engine.submit_order(
                symbol=args.symbol,
                side=OrderSide(args.side),
                order_type=OrderType.LIMIT,
                quantity=args.quantity,
                price=args.price,
                client_order_id=args.client_order_id
            )
            logger.info(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            logger.info(f"\n活跃订单: {len(engine.get_active_orders())}")
            logger.info(f"统计: {engine.get_stats()}")
        
        asyncio.run(test_submit())
    
    elif args.action == 'cancel':
        if not args.client_order_id:
            logger.info("Error: --client_order_id is required for cancel action")
            sys.exit(1)
        
        async def test_cancel():
            success = await engine.cancel_order(args.client_order_id)
            logger.info(f"Cancel result: {success}")
            logger.info(f"统计: {engine.get_stats()}")
        
        asyncio.run(test_cancel())
    
    elif args.action == 'stats':
        logger.info(json.dumps(engine.get_stats(), indent=2))
    
    elif args.action == 'cleanup':
        async def test_cleanup():
            await engine.cleanup()
            logger.info("Cleanup completed")
        
        asyncio.run(test_cleanup())


if __name__ == "__main__":
    main()
