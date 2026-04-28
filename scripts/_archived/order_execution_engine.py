#!/usr/bin/env python3
"""
开单执行引擎（第4层：开单执行）
订单执行引擎 + 智能订单路由 + 滑点控制
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import pandas as pd


class OrderType(Enum):
    """订单类型"""
    MARKET = "MARKET"  # 市价单
    LIMIT = "LIMIT"  # 限价单
    STOP = "STOP"  # 止损单
    STOP_LIMIT = "STOP_LIMIT"  # 止损限价单
    TRAILING_STOP = "TRAILING_STOP"  # 跟踪止损单


class OrderSide(Enum):
    """订单方向"""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "PENDING"  # 待提交
    SUBMITTED = "SUBMITTED"  # 已提交
    FILLED = "FILLED"  # 已成交
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # 部分成交
    CANCELLED = "CANCELLED"  # 已取消
    REJECTED = "REJECTED"  # 已拒绝
    EXPIRED = "EXPIRED"  # 已过期


@dataclass
class Order:
    """订单"""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "GTC"  # GTC/IOC/FOK
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    create_time: float = field(default_factory=time.time)
    update_time: float = field(default_factory=time.time)
    fee: float = 0.0
    slippage: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'order_id': self.order_id,
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
            'create_time': self.create_time,
            'update_time': self.update_time,
            'fee': self.fee,
            'slippage': self.slippage
        }


@dataclass
class ExecutionResult:
    """执行结果"""
    order_id: str
    status: OrderStatus
    filled_quantity: float
    avg_fill_price: float
    execution_time: float
    fee: float
    slippage: float
    error_message: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            'order_id': self.order_id,
            'status': self.status.value,
            'filled_quantity': self.filled_quantity,
            'avg_fill_price': self.avg_fill_price,
            'execution_time': self.execution_time,
            'fee': self.fee,
            'slippage': self.slippage,
            'error_message': self.error_message
        }


@dataclass
class MarketData:
    """市场数据"""
    symbol: str
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    last_price: float
    volume_24h: float
    timestamp: float = field(default_factory=time.time)


class SlippageController:
    """滑点控制器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.max_slippage_pct = self.config.get('max_slippage_pct', 0.001)  # 0.1%
        self.expected_slippage_pct = self.config.get('expected_slippage_pct', 0.0005)  # 0.05%

    def calculate_slippage(self, order: Order, market_data: MarketData, execution_price: float) -> float:
        """计算滑点"""
        if order.side == OrderSide.BUY:
            expected_price = market_data.ask_price
        else:
            expected_price = market_data.bid_price

        if expected_price == 0:
            return 0.0

        slippage_pct = abs(execution_price - expected_price) / expected_price
        return slippage_pct

    def is_slippage_acceptable(self, order: Order, market_data: MarketData, execution_price: float) -> Tuple[bool, float]:
        """判断滑点是否可接受"""
        slippage_pct = self.calculate_slippage(order, market_data, execution_price)
        is_acceptable = slippage_pct <= self.max_slippage_pct

        return is_acceptable, slippage_pct

    def adjust_price_for_slippage(self, order: Order, market_data: MarketData) -> float:
        """为滑点调整价格"""
        if order.order_type == OrderType.MARKET:
            # 市价单，使用对手价
            if order.side == OrderSide.BUY:
                return market_data.ask_price
            else:
                return market_data.bid_price

        elif order.order_type == OrderType.LIMIT:
            # 限价单，预留滑点空间
            if order.side == OrderSide.BUY:
                adjusted_price = order.price * (1 + self.expected_slippage_pct)
            else:
                adjusted_price = order.price * (1 - self.expected_slippage_pct)
            return adjusted_price

        else:
            return order.price or market_data.last_price


class OrderRouter:
    """订单路由器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.prefer_maker = self.config.get('prefer_maker', False)

    def select_order_type(self, order: Order, market_data: MarketData, urgency: float = 0.5) -> OrderType:
        """选择订单类型"""
        # 高紧急度 → 市价单
        # 低紧急度 → 限价单

        if urgency >= 0.8:
            return OrderType.MARKET
        elif urgency >= 0.5:
            # 中等紧急度，根据市场深度决定
            depth_ratio = min(market_data.bid_size, market_data.ask_size) / market_data.volume_24h

            if depth_ratio > 0.001:  # 深度足够
                if self.prefer_maker:
                    return OrderType.LIMIT
                else:
                    return OrderType.MARKET
            else:
                return OrderType.MARKET
        else:
            return OrderType.LIMIT

    def route_order(self, order: Order, market_data: MarketData) -> Dict[str, Any]:
        """路由订单"""
        routing_decision = {
            'exchange': 'default',
            'price_adjustment': 0.0,
            'estimated_latency_ms': 100,
            'order_type_suggestion': order.order_type,
            'reason': 'default_routing'
        }

        # 简化版路由逻辑
        if self.prefer_maker and order.order_type == OrderType.LIMIT:
            routing_decision['reason'] = 'prefer_maker_order'

        return routing_decision


class OrderExecutionEngine:
    """订单执行引擎"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化订单执行引擎

        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.fee_rate = self.config.get('fee_rate', 0.001)  # 0.1%
        self.max_order_size = self.config.get('max_order_size', 1000.0)
        self.enable_large_order_split = self.config.get('enable_large_order_split', True)

        self.slippage_controller = SlippageController(self.config.get('slippage_config', {}))
        self.order_router = OrderRouter(self.config.get('routing_config', {}))

        self.active_orders: Dict[str, Order] = {}

    def create_order(self, order_request: Dict) -> Order:
        """创建订单"""
        order_id = f"order_{int(time.time())}_{len(self.active_orders)}"

        order = Order(
            order_id=order_id,
            symbol=order_request['symbol'],
            side=OrderSide(order_request['side']),
            order_type=OrderType(order_request.get('order_type', 'MARKET')),
            quantity=order_request['quantity'],
            price=order_request.get('price'),
            stop_price=order_request.get('stop_price'),
            time_in_force=order_request.get('time_in_force', 'GTC')
        )

        return order

    def submit_order(self, order: Order, market_data: MarketData) -> ExecutionResult:
        """提交订单"""
        try:
            # 路由决策
            routing_decision = self.order_router.route_order(order, market_data)

            # 调整价格
            execution_price = self.slippage_controller.adjust_price_for_slippage(order, market_data)

            # 模拟执行
            execution_time = time.time()

            # 检查滑点
            is_acceptable, slippage_pct = self.slippage_controller.is_slippage_acceptable(
                order, market_data, execution_price
            )

            if not is_acceptable:
                # 滑点过大，拒绝订单
                return ExecutionResult(
                    order_id=order.order_id,
                    status=OrderStatus.REJECTED,
                    filled_quantity=0.0,
                    avg_fill_price=0.0,
                    execution_time=execution_time,
                    fee=0.0,
                    slippage=slippage_pct,
                    error_message=f"滑点过大: {slippage_pct:.4%}"
                )

            # 执行订单
            if order.order_type == OrderType.MARKET:
                # 市价单直接成交
                result = self.execute_market_order(order, market_data, execution_price)
            else:
                # 限价单模拟成交
                result = self.execute_limit_order(order, market_data, execution_price)

            # 更新订单状态
            order.status = result.status
            order.filled_quantity = result.filled_quantity
            order.avg_fill_price = result.avg_fill_price
            order.update_time = execution_time
            order.fee = result.fee
            order.slippage = result.slippage

            # 保存到活跃订单
            if result.status in [OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED]:
                self.active_orders[order.order_id] = order

            return result

        except Exception as e:
            return ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.REJECTED,
                filled_quantity=0.0,
                avg_fill_price=0.0,
                execution_time=time.time(),
                fee=0.0,
                slippage=0.0,
                error_message=str(e)
            )

    def execute_market_order(self, order: Order, market_data: MarketData, execution_price: float) -> ExecutionResult:
        """执行市价单"""
        # 市价单立即成交
        filled_quantity = order.quantity

        # 计算费用
        fee = filled_quantity * execution_price * self.fee_rate

        # 计算滑点
        is_acceptable, slippage_pct = self.slippage_controller.is_slippage_acceptable(
            order, market_data, execution_price
        )

        return ExecutionResult(
            order_id=order.order_id,
            status=OrderStatus.FILLED,
            filled_quantity=filled_quantity,
            avg_fill_price=execution_price,
            execution_time=time.time(),
            fee=fee,
            slippage=slippage_pct
        )

    def execute_limit_order(self, order: Order, market_data: MarketData, execution_price: float) -> ExecutionResult:
        """执行限价单（模拟）"""
        # 模拟限价单可能部分成交
        fill_probability = 0.8  # 80%概率成交

        if np.random.random() < fill_probability:
            # 成交
            filled_quantity = order.quantity
            fee = filled_quantity * execution_price * self.fee_rate

            is_acceptable, slippage_pct = self.slippage_controller.is_slippage_acceptable(
                order, market_data, execution_price
            )

            return ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.FILLED,
                filled_quantity=filled_quantity,
                avg_fill_price=execution_price,
                execution_time=time.time(),
                fee=fee,
                slippage=slippage_pct
            )
        else:
            # 未成交
            return ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.SUBMITTED,
                filled_quantity=0.0,
                avg_fill_price=0.0,
                execution_time=time.time(),
                fee=0.0,
                slippage=0.0,
                error_message="限价单未成交"
            )

    def split_large_order(self, order: Order) -> List[Order]:
        """拆分大订单"""
        if not self.enable_large_order_split or order.quantity <= self.max_order_size:
            return [order]

        splits = []
        remaining_quantity = order.quantity

        while remaining_quantity > 0:
            split_quantity = min(remaining_quantity, self.max_order_size)

            split_order = Order(
                order_id=f"{order.order_id}_split_{len(splits)}",
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=split_quantity,
                price=order.price,
                stop_price=order.stop_price,
                time_in_force=order.time_in_force,
                status=OrderStatus.PENDING
            )

            splits.append(split_order)
            remaining_quantity -= split_quantity

        return splits

    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        if order_id in self.active_orders:
            order = self.active_orders[order_id]
            order.status = OrderStatus.CANCELLED
            order.update_time = time.time()
            return True
        return False

    def get_active_orders(self) -> List[Order]:
        """获取活跃订单"""
        return list(self.active_orders.values())


class PositionManager:
    """持仓管理器"""

    def __init__(self):
        self.positions: Dict[str, Dict] = {}

    def update_position(self, order: Order, result: ExecutionResult):
        """更新持仓"""
        symbol = order.symbol

        if symbol not in self.positions:
            self.positions[symbol] = {
                'quantity': 0.0,
                'avg_entry_price': 0.0,
                'total_cost': 0.0,
                'total_fee': 0.0,
                'realized_pnl': 0.0
            }

        position = self.positions[symbol]

        if result.status == OrderStatus.FILLED:
            if order.side == OrderSide.BUY:
                # 买入
                old_quantity = position['quantity']
                old_avg_price = position['avg_entry_price']

                new_quantity = result.filled_quantity
                new_avg_price = result.avg_fill_price

                # 更新平均成本
                total_quantity = old_quantity + new_quantity
                if total_quantity > 0:
                    position['avg_entry_price'] = (
                        (old_quantity * old_avg_price + new_quantity * new_avg_price) /
                        total_quantity
                    )
                position['quantity'] = total_quantity
                position['total_cost'] += new_quantity * new_avg_price

            else:
                # 卖出
                if result.filled_quantity <= position['quantity']:
                    # 平仓
                    realized_pnl = result.filled_quantity * (
                        result.avg_fill_price - position['avg_entry_price']
                    )
                    position['realized_pnl'] += realized_pnl
                    position['quantity'] -= result.filled_quantity

                    # 如果完全平仓，重置平均价格
                    if position['quantity'] <= 0:
                        position['quantity'] = 0.0
                        position['avg_entry_price'] = 0.0
                else:
                    # 超卖（做空）
                    position['quantity'] -= result.filled_quantity
                    position['avg_entry_price'] = result.avg_fill_price

            position['total_fee'] += result.fee

    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓"""
        return self.positions.get(symbol)

    def get_all_positions(self) -> Dict[str, Dict]:
        """获取所有持仓"""
        return self.positions.copy()


def main():
    parser = argparse.ArgumentParser(description="开单执行引擎（第4层：开单执行）")
    parser.add_argument("--action", choices=["submit", "cancel", "status", "test"], default="test", help="操作类型")
    parser.add_argument("--order", help="订单JSON")
    parser.add_argument("--order_id", help="订单ID")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r') as f:
                config = json.load(f)

        # 创建执行引擎
        engine = OrderExecutionEngine(config)
        position_manager = PositionManager()

        print("=" * 70)
        print("✅ 杀手锏交易系统 - 开单执行引擎（第4层：开单执行）")
        print("=" * 70)

        if args.action == "submit":
            # 提交订单
            if not args.order:
                print("错误: 请提供订单数据")
                sys.exit(1)

            order_request = json.loads(args.order)
            order = engine.create_order(order_request)

            # 模拟市场数据
            market_data = MarketData(
                symbol=order_request['symbol'],
                bid_price=order_request.get('price', 50000.0) * 0.999,
                ask_price=order_request.get('price', 50000.0) * 1.001,
                bid_size=1000.0,
                ask_size=1000.0,
                last_price=order_request.get('price', 50000.0),
                volume_24h=1000000.0
            )

            # 执行订单
            print(f"\n[订单提交] 订单ID: {order.order_id}")
            print(f"[订单提交] 品种: {order.symbol}")
            print(f"[订单提交] 方向: {order.side.value}")
            print(f"[订单提交] 类型: {order.order_type.value}")
            print(f"[订单提交] 数量: {order.quantity}")

            result = engine.submit_order(order, market_data)

            print(f"\n[执行结果] 状态: {result.status.value}")
            print(f"[执行结果] 成交数量: {result.filled_quantity}")
            print(f"[执行结果] 成交价格: {result.avg_fill_price}")
            print(f"[执行结果] 手续费: {result.fee}")
            print(f"[执行结果] 滑点: {result.slippage:.4%}")

            if result.error_message:
                print(f"[执行结果] 错误: {result.error_message}")

            # 更新持仓
            position_manager.update_position(order, result)

            output = {
                "status": "success",
                "order": order.to_dict(),
                "result": result.to_dict(),
                "position": position_manager.get_position(order.symbol)
            }

        elif args.action == "cancel":
            # 取消订单
            if not args.order_id:
                print("错误: 请提供订单ID")
                sys.exit(1)

            success = engine.cancel_order(args.order_id)

            output = {
                "status": "success",
                "cancelled": success,
                "order_id": args.order_id
            }

        elif args.action == "status":
            # 查询订单状态
            active_orders = engine.get_active_orders()

            output = {
                "status": "success",
                "active_orders": [order.to_dict() for order in active_orders]
            }

        elif args.action == "test":
            # 测试模式
            # 测试市价买单
            test_order_request = {
                'symbol': 'BTCUSDT',
                'side': 'BUY',
                'order_type': 'MARKET',
                'quantity': 0.1
            }

            order = engine.create_order(test_order_request)

            market_data = MarketData(
                symbol='BTCUSDT',
                bid_price=50000.0,
                ask_price=50010.0,
                bid_size=1000.0,
                ask_size=1000.0,
                last_price=50005.0,
                volume_24h=1000000.0
            )

            result = engine.submit_order(order, market_data)

            # 测试限价卖单
            sell_order_request = {
                'symbol': 'BTCUSDT',
                'side': 'SELL',
                'order_type': 'LIMIT',
                'quantity': 0.05,
                'price': 50100.0
            }

            sell_order = engine.create_order(sell_order_request)
            sell_result = engine.submit_order(sell_order, market_data)

            # 测试大订单拆分
            large_order_request = {
                'symbol': 'BTCUSDT',
                'side': 'BUY',
                'order_type': 'MARKET',
                'quantity': 1500.0
            }

            large_order = engine.create_order(large_order_request)
            splits = engine.split_large_order(large_order)

            output = {
                "status": "success",
                "test_market_order": {
                    "order": order.to_dict(),
                    "result": result.to_dict()
                },
                "test_limit_order": {
                    "order": sell_order.to_dict(),
                    "result": sell_result.to_dict()
                },
                "test_large_order_split": {
                    "original_quantity": large_order.quantity,
                    "split_count": len(splits),
                    "splits": [s.to_dict() for s in splits]
                }
            }

        print(f"\n{'=' * 70}")
        print(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        import traceback
        print(json.dumps({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
