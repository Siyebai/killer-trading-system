#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("smart_order_router")
except ImportError:
    import logging
    logger = logging.getLogger("smart_order_router")
"""
智能订单路由 - V3.5核心模块
最优执行路径选择、流动性分析、价格影响优化
"""

import json
import numpy as np
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from decimal import Decimal
import heapq


@dataclass
class Exchange:
    """交易所信息"""
    exchange_id: str
    name: str
    fee_rate: float  # 手续费率
    liquidity_score: float  # 流动性评分 (0-1)
    latency_ms: float  # 延迟（毫秒）
    min_order_size: float  # 最小订单量
    max_order_size: float  # 最大订单量


@dataclass
class OrderPath:
    """订单路径"""
    exchanges: List[str]  # 交易所列表
    total_cost: float  # 总成本（含手续费）
    expected_slippage: float  # 预期滑点
    execution_time_ms: float  # 预期执行时间
    liquidity_utilization: float  # 流动性利用率


@dataclass
class MarketDepth:
    """市场深度"""
    exchange_id: str
    bids: List[tuple]  # [(price, size), ...]
    asks: List[tuple]


class SmartOrderRouter:
    """智能订单路由器"""

    def __init__(self):
        """初始化路由器"""
        self.exchanges: Dict[str, Exchange] = {}
        self.market_depths: Dict[str, MarketDepth] = {}

    def add_exchange(self, exchange: Exchange):
        """
        添加交易所

        Args:
            exchange: 交易所对象
        """
        self.exchanges[exchange.exchange_id] = exchange

    def update_market_depth(self, depth: MarketDepth):
        """
        更新市场深度

        Args:
            depth: 市场深度数据
        """
        self.market_depths[depth.exchange_id] = depth

    def calculate_price_impact(self, exchange_id: str, side: str,
                               size: float) -> float:
        """
        计算价格影响（滑点）

        Args:
            exchange_id: 交易所ID
            side: 方向（BUY/SELL）
            size: 订单大小

        Returns:
            价格影响（相对值）
        """
        if exchange_id not in self.market_depths:
            return 0.0

        depth = self.market_depths[exchange_id]

        if side == 'BUY':
            # 买单：从卖单簿匹配
            orders = depth.asks
        else:
            # 卖单：从买单簿匹配
            orders = depth.bids

        remaining_size = size
        total_cost = 0.0
        total_size = 0.0

        for price, available_size in orders:
            if remaining_size <= 0:
                break

            fill_size = min(remaining_size, available_size)
            total_cost += price * fill_size
            total_size += fill_size
            remaining_size -= fill_size

        if total_size == 0:
            return 0.0

        avg_price = total_cost / total_size
        best_price = orders[0][0] if orders else 0

        # 价格影响 = (平均价格 - 最优价格) / 最优价格
        price_impact = (avg_price - best_price) / best_price if best_price > 0 else 0

        return abs(price_impact)

    def calculate_execution_cost(self, exchange_id: str, side: str,
                                 size: float) -> float:
        """
        计算执行成本（手续费 + 滑点）

        Args:
            exchange_id: 交易所ID
            side: 方向
            size: 订单大小

        Returns:
            总成本比例
        """
        exchange = self.exchanges.get(exchange_id)
        if not exchange:
            return float('inf')

        # 手续费
        fee = exchange.fee_rate

        # 价格影响
        price_impact = self.calculate_price_impact(exchange_id, side, size)

        # 总成本
        total_cost = fee + price_impact

        return total_cost

    def find_optimal_single_exchange(self, symbol: str, side: str,
                                     size: float) -> Optional[OrderPath]:
        """
        寻找最优单一交易所

        Args:
            symbol: 交易对
            side: 方向
            size: 订单大小

        Returns:
            最优路径
        """
        best_path = None
        best_cost = float('inf')

        for exchange_id, exchange in self.exchanges.items():
            # 检查订单大小限制
            if size < exchange.min_order_size or size > exchange.max_order_size:
                continue

            # 计算执行成本
            cost = self.calculate_execution_cost(exchange_id, side, size)

            # 计算执行时间
            execution_time = exchange.latency_ms

            # 计算流动性利用率
            liquidity_util = size / (exchange.max_order_size if exchange.max_order_size > 0 else 1)

            # 评分：成本 + 时间惩罚 + 流动性惩罚
            score = cost + (execution_time / 10000) + (liquidity_util * 0.1)

            if score < best_cost:
                best_cost = score
                best_path = OrderPath(
                    exchanges=[exchange_id],
                    total_cost=cost,
                    expected_slippage=self.calculate_price_impact(exchange_id, side, size),
                    execution_time_ms=execution_time,
                    liquidity_utilization=liquidity_util
                )

        return best_path

    def find_optimal_split_order(self, symbol: str, side: str,
                                 size: float, max_splits: int = 3) -> OrderPath:
        """
        寻找最优拆单路径（动态规划）

        Args:
            symbol: 交易对
            side: 方向
            size: 订单大小
            max_splits: 最大拆分数量

        Returns:
            最优路径
        """
        # 简化实现：使用贪心算法拆单
        remaining_size = size
        paths = []

        while remaining_size > 0 and len(paths) < max_splits:
            # 找到当前最优的单一交易所
            path = self.find_optimal_single_exchange(symbol, side, remaining_size)

            if not path:
                break

            exchange_id = path.exchanges[0]
            exchange = self.exchanges[exchange_id]

            # 计算最优拆分大小
            optimal_size = min(remaining_size, exchange.max_order_size * 0.5)  # 不超过最大量的50%

            # 更新路径
            path.total_cost = self.calculate_execution_cost(exchange_id, side, optimal_size)
            path.expected_slippage = self.calculate_price_impact(exchange_id, side, optimal_size)
            path.liquidity_utilization = optimal_size / exchange.max_order_size

            paths.append(path)
            remaining_size -= optimal_size

        # 合并结果
        if not paths:
            return OrderPath(
                exchanges=[],
                total_cost=float('inf'),
                expected_slippage=1.0,
                execution_time_ms=float('inf'),
                liquidity_utilization=1.0
            )

        # 加权平均
        total_size = size
        avg_cost = sum(p.total_cost * (size / len(paths)) for p in paths) / total_size
        avg_slippage = sum(p.expected_slippage * (size / len(paths)) for p in paths) / total_size
        max_time = max(p.execution_time_ms for p in paths)
        max_util = max(p.liquidity_utilization for p in paths)

        return OrderPath(
            exchanges=[p.exchanges[0] for p in paths],
            total_cost=avg_cost,
            expected_slippage=avg_slippage,
            execution_time_ms=max_time,
            liquidity_utilization=max_util
        )

    def route_order(self, symbol: str, side: str, size: float,
                    allow_split: bool = True) -> Dict[str, Any]:
        """
        路由订单

        Args:
            symbol: 交易对
            side: 方向（BUY/SELL）
            size: 订单大小
            allow_split: 是否允许拆单

        Returns:
            路由结果
        """
        # 尝试单一交易所
        single_path = self.find_optimal_single_exchange(symbol, side, size)

        # 尝试拆单
        split_path = None
        if allow_split and size > 0.1:  # 只有订单较大时才拆单
            split_path = self.find_optimal_split_order(symbol, side, size)

        # 选择最优路径
        if split_path and split_path.total_cost < single_path.total_cost * 0.95:
            # 拆单成本降低超过5%，使用拆单
            optimal_path = split_path
            routing_type = "SPLIT"
        else:
            optimal_path = single_path
            routing_type = "SINGLE"

        return {
            'routing_type': routing_type,
            'optimal_path': {
                'exchanges': optimal_path.exchanges,
                'total_cost_pct': optimal_path.total_cost * 100,
                'expected_slippage_pct': optimal_path.expected_slippage * 100,
                'execution_time_ms': optimal_path.execution_time_ms,
                'liquidity_utilization_pct': optimal_path.liquidity_utilization * 100
            },
            'suggested_execution': [
                {
                    'exchange': ex,
                    'size': size / len(optimal_path.exchanges)
                } for ex in optimal_path.exchanges
            ]
        }

    def get_exchange_comparison(self, symbol: str, side: str,
                                size: float) -> List[Dict[str, Any]]:
        """
        获取交易所对比

        Args:
            symbol: 交易对
            side: 方向
            size: 订单大小

        Returns:
            交易所列表及其指标
        """
        comparison = []

        for exchange_id, exchange in self.exchanges.items():
            cost = self.calculate_execution_cost(exchange_id, side, size)
            slippage = self.calculate_price_impact(exchange_id, side, size)

            comparison.append({
                'exchange_id': exchange_id,
                'name': exchange.name,
                'fee_rate_pct': exchange.fee_rate * 100,
                'liquidity_score': exchange.liquidity_score,
                'latency_ms': exchange.latency_ms,
                'execution_cost_pct': cost * 100,
                'expected_slippage_pct': slippage * 100,
                'is_recommended': False
            })

        # 标记推荐交易所
        if comparison:
            min_cost = min(c['execution_cost_pct'] for c in comparison)
            for c in comparison:
                if c['execution_cost_pct'] <= min_cost * 1.05:
                    c['is_recommended'] = True

        # 按成本排序
        comparison.sort(key=lambda x: x['execution_cost_pct'])

        return comparison


# 命令行测试
def main():
    """测试智能订单路由"""
    # 创建路由器
    router = SmartOrderRouter()

    # 添加交易所
    exchanges = [
        Exchange('binance', 'Binance', fee_rate=0.001, liquidity_score=0.95,
                 latency_ms=50, min_order_size=0.001, max_order_size=10.0),
        Exchange('okx', 'OKX', fee_rate=0.0008, liquidity_score=0.85,
                 latency_ms=80, min_order_size=0.001, max_order_size=5.0),
        Exchange('bybit', 'Bybit', fee_rate=0.0006, liquidity_score=0.75,
                 latency_ms=60, min_order_size=0.001, max_order_size=3.0),
    ]

    for ex in exchanges:
        router.add_exchange(ex)

    # 更新市场深度
    for ex in exchanges:
        base_price = 50000
        bids = [(base_price - i*10, np.random.uniform(1, 5)) for i in range(10)]
        asks = [(base_price + i*10, np.random.uniform(1, 5)) for i in range(10)]
        depth = MarketDepth(ex.exchange_id, bids, asks)
        router.update_market_depth(depth)

    logger.info("="*60)
    logger.info("🔀 智能订单路由测试")
    logger.info("="*60)

    # 测试路由
    test_orders = [
        {'symbol': 'BTCUSDT', 'side': 'BUY', 'size': 0.5},
        {'symbol': 'BTCUSDT', 'side': 'SELL', 'size': 2.0},
    ]

    for order in test_orders:
        logger.info(f"\n{'='*60}")
        logger.info(f"订单: {order['side']} {order['size']} {order['symbol']}")
        logger.info(f"{'='*60}")

        # 交易所对比
        comparison = router.get_exchange_comparison(
            order['symbol'], order['side'], order['size']
        )
        logger.info(f"\n交易所对比:")
        logger.info(f"{'交易所':<10} {'手续费%':<10} {'流动性':<10} {'延迟(ms)':<10} {'成本%':<10} {'推荐'}")
        logger.info("-" * 60)
        for c in comparison:
            recommend = "✓" if c['is_recommended'] else " "
            logger.info((f"{c['name']:<10} {c['fee_rate_pct']:<10.3f} {c['liquidity_score']:<10.2f} ")
                  f"{c['latency_ms']:<10.0f} {c['execution_cost_pct']:<10.3f} {recommend}")

        # 智能路由
        result = router.route_order(
            order['symbol'], order['side'], order['size'], allow_split=True
        )

        logger.info(f"\n最优路由:")
        logger.info(f"  路由类型: {result['routing_type']}")
        logger.info(f"  交易所: {', '.join(result['optimal_path']['exchanges'])}")
        logger.info(f"  总成本: {result['optimal_path']['total_cost_pct']:.3f}%")
        logger.info(f"  预期滑点: {result['optimal_path']['expected_slippage_pct']:.3f}%")
        logger.info(f"  执行时间: {result['optimal_path']['execution_time_ms']:.0f}ms")
        logger.info(f"  流动性利用率: {result['optimal_path']['liquidity_utilization_pct']:.1f}%")

        logger.info(f"\n建议执行:")
        for exec_plan in result['suggested_execution']:
            logger.info(f"  {exec_plan['exchange']}: {exec_plan['size']:.3f}")

    logger.info(f"\n{'='*60}")
    logger.info("智能订单路由测试: PASS")


if __name__ == "__main__":
    main()
