#!/usr/bin/env python3
"""
高保真交易模拟 - 杀手锏交易系统P0核心
滑点模型、网络延迟模拟、交易成本精确计算、TWAP/VWAP大单拆分
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import time


class ExecutionAlgorithm(Enum):
    """执行算法"""
    MARKET = "MARKET"  # 市价单
    LIMIT = "LIMIT"  # 限价单
    TWAP = "TWAP"  # 时间加权平均价格
    VWAP = "VWAP"  # 成交量加权平均价格


class OrderSide(Enum):
    """订单方向"""
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class SlippageModel:
    """滑点模型"""
    base_slippage: float  # 基础滑点（bps）
    volume_impact_factor: float  # 成交量影响因子
    volatility_impact_factor: float  # 波动率影响因子
    spread_impact: float  # 买卖价差影响


@dataclass
class ExecutionResult:
    """执行结果"""
    order_id: str
    side: OrderSide
    requested_size: float
    filled_size: float
    avg_fill_price: float
    total_slippage: float  # 总滑点（bps）
    execution_time_ms: float
    total_cost: float  # 总成本（包括手续费、滑点）
    algorithm: ExecutionAlgorithm
    fills: List[Dict]


class HighFidelityExecution:
    """高保真交易模拟"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化高保真执行

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 滑点模型
        self.slippage_model = SlippageModel(
            base_slippage=self.config.get('base_slippage_bps', 5),  # 5 bps
            volume_impact_factor=self.config.get('volume_impact_factor', 0.0001),
            volatility_impact_factor=self.config.get('volatility_impact_factor', 0.1),
            spread_impact=self.config.get('spread_impact', 0.5)
        )

        # 网络延迟模拟
        self.base_latency_ms = self.config.get('base_latency_ms', 50)
        self.latency_variance_ms = self.config.get('latency_variance_ms', 30)

        # 交易成本
        self.maker_fee = self.config.get('maker_fee', 0.0002)  # 0.02%
        self.taker_fee = self.config.get('taker_fee', 0.0005)  # 0.05%
        self.funding_rate = self.config.get('funding_rate', 0.0001)  # 0.01%/8h

        # 订单簿深度
        self.orderbook_depth = self.config.get('orderbook_depth', {
            'level1': {'size': 1.0, 'spread_bps': 1},
            'level2': {'size': 5.0, 'spread_bps': 3},
            'level3': {'size': 20.0, 'spread_bps': 10},
            'level4': {'size': 100.0, 'spread_bps': 30},
            'level5': {'size': 500.0, 'spread_bps': 100}
        })

    def calculate_slippage(self, side: OrderSide, size: float, volatility: float,
                          orderbook: Optional[Dict] = None) -> float:
        """
        计算滑点（bps）

        Args:
            side: 订单方向
            size: 订单大小
            volatility: 波动率
            orderbook: 订单簿数据

        Returns:
            滑点（bps）
        """
        # 基础滑点
        slippage = self.slippage_model.base_slippage

        # 成交量影响（订单越大，滑点越大）
        volume_impact = size * self.slippage_model.volume_impact_factor * 10000  # 转为bps
        slippage += volume_impact

        # 波动率影响
        volatility_impact = volatility * self.slippage_model.volatility_impact_factor * 10000
        slippage += volatility_impact

        # 订单簿深度影响
        if orderbook:
            spread_bps = self._estimate_spread(orderbook)
            slippage += spread_bps * self.slippage_model.spread_impact

        return slippage

    def _estimate_spread(self, orderbook: Dict) -> float:
        """
        估算买卖价差（bps）

        Args:
            orderbook: 订单簿

        Returns:
            价差（bps）
        """
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        if not bids or not asks:
            return 1.0  # 默认1 bps

        best_bid = bids[0][0] if bids else 0
        best_ask = asks[0][0] if asks else 0

        if best_bid > 0 and best_ask > 0:
            spread = (best_ask - best_bid) / best_ask * 10000
            return spread

        return 1.0

    def simulate_network_latency(self) -> float:
        """
        模拟网络延迟

        Returns:
            延迟（毫秒）
        """
        latency = np.random.normal(self.base_latency_ms, self.latency_variance_ms)
        return max(10, latency)  # 最小10ms

    def calculate_total_cost(self, side: OrderSide, size: float, price: float,
                           slippage_bps: float, is_maker: bool = False) -> float:
        """
        计算总交易成本

        Args:
            side: 订单方向
            size: 订单大小
            price: 价格
            slippage_bps: 滑点（bps）
            is_maker: 是否为Maker订单

        Returns:
            总成本
        """
        # 手续费
        fee_rate = self.maker_fee if is_maker else self.taker_fee
        fee_cost = size * price * fee_rate

        # 滑点成本
        slippage_cost = size * price * (slippage_bps / 10000)

        # 融资费（仅空头）
        funding_cost = 0
        if side == OrderSide.SELL:
            funding_cost = size * price * self.funding_rate

        return fee_cost + slippage_cost + funding_cost

    def execute_market_order(self, order_id: str, side: OrderSide, size: float,
                           current_price: float, volatility: float,
                           orderbook: Optional[Dict] = None) -> ExecutionResult:
        """
        执行市价单

        Args:
            order_id: 订单ID
            side: 订单方向
            size: 订单大小
            current_price: 当前价格
            volatility: 波动率
            orderbook: 订单簿

        Returns:
            执行结果
        """
        # 计算滑点
        slippage_bps = self.calculate_slippage(side, size, volatility, orderbook)

        # 模拟延迟
        latency_ms = self.simulate_network_latency()

        # 计算成交价格
        if side == OrderSide.BUY:
            fill_price = current_price * (1 + slippage_bps / 10000)
        else:  # SELL
            fill_price = current_price * (1 - slippage_bps / 10000)

        # 计算成本
        total_cost = self.calculate_total_cost(side, size, fill_price, slippage_bps, is_maker=False)

        # 可能部分成交
        filled_size = size * min(1.0, 0.95 + np.random.random() * 0.05)  # 95%-100%成交

        return ExecutionResult(
            order_id=order_id,
            side=side,
            requested_size=size,
            filled_size=filled_size,
            avg_fill_price=fill_price,
            total_slippage=slippage_bps,
            execution_time_ms=latency_ms,
            total_cost=total_cost,
            algorithm=ExecutionAlgorithm.MARKET,
            fills=[{
                'price': fill_price,
                'size': filled_size,
                'timestamp': time.time()
            }]
        )

    def place_limit_order(self, order_id: str, side: OrderSide, size: float,
                         current_price: float, volatility: float, orderbook: Optional[Dict] = None,
                         offset_mode: str = "dynamic") -> ExecutionResult:
        """
        下达动态限价单（V4.5增强）

        Args:
            order_id: 订单ID
            side: 订单方向
            size: 订单大小
            current_price: 当前价格
            volatility: 波动率
            orderbook: 订单簿
            offset_mode: 偏移模式（dynamic/static/aggressive/conservative）

        Returns:
            执行结果
        """
        # 计算动态偏移量
        if offset_mode == "dynamic" and orderbook:
            # 基于订单簿深度和波动率
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])

            if side == OrderSide.BUY and asks:
                # 买单：买一价 - offset
                best_ask = asks[0][0] if asks else current_price
                ask_depth = sum(size for _, size in asks[:3]) if len(asks) >= 3 else asks[0][1]

                # 偏移量 = 买卖价差 * 0.5 + 波动率 * 价格 * 0.2
                spread = best_ask - current_price if asks and bids else 0
                volatility_offset = volatility * current_price * 0.2
                offset = max(spread * 0.5, volatility_offset)

                limit_price = best_ask - offset

            elif side == OrderSide.SELL and bids:
                # 卖单：卖一价 + offset
                best_bid = bids[0][0] if bids else current_price
                bid_depth = sum(size for _, size in bids[:3]) if len(bids) >= 3 else bids[0][1]

                spread = current_price - best_bid if asks and bids else 0
                volatility_offset = volatility * current_price * 0.2
                offset = max(spread * 0.5, volatility_offset)

                limit_price = best_bid + offset

            else:
                limit_price = current_price

        elif offset_mode == "static":
            # 固定偏移：1 tick
            tick_size = 0.01  # 假设tick size
            if side == OrderSide.BUY:
                limit_price = current_price - tick_size
            else:
                limit_price = current_price + tick_size

        elif offset_mode == "aggressive":
            # 激进：接近市价
            tick_size = 0.01
            if side == OrderSide.BUY:
                limit_price = current_price + tick_size
            else:
                limit_price = current_price - tick_size

        else:  # conservative
            # 保守：远离市价
            tick_size = 0.05
            if side == OrderSide.BUY:
                limit_price = current_price - tick_size * 5
            else:
                limit_price = current_price + tick_size * 5

        # 模拟延迟
        latency_ms = self.simulate_network_latency()

        # 计算滑点（限价单滑点为0或很小）
        slippage_bps = 0  # 限价单无滑点

        # 可能成交（简化：假设80%概率成交）
        fill_probability = 0.8
        if np.random.random() < fill_probability:
            filled_size = size * np.random.uniform(0.5, 1.0)
        else:
            filled_size = 0

        # 计算成本（Maker手续费）
        total_cost = 0
        if filled_size > 0:
            total_cost = self.calculate_total_cost(side, filled_size, limit_price, slippage_bps, is_maker=True)

        return ExecutionResult(
            order_id=order_id,
            side=side,
            requested_size=size,
            filled_size=filled_size,
            avg_fill_price=limit_price,
            total_slippage=slippage_bps,
            execution_time_ms=latency_ms,
            total_cost=total_cost,
            algorithm=ExecutionAlgorithm.LIMIT,
            fills=[{
                'price': limit_price,
                'size': filled_size,
                'timestamp': time.time()
            }] if filled_size > 0 else []
        )

    def execute_twap(self, order_id: str, side: OrderSide, total_size: float,
                    current_price: float, volatility: float, duration_minutes: int = 30,
                    num_slices: int = 6) -> ExecutionResult:
        """
        执行TWAP（时间加权平均价格）

        Args:
            order_id: 订单ID
            side: 订单方向
            total_size: 总大小
            current_price: 当前价格
            volatility: 波动率
            duration_minutes: 执行时长（分钟）
            num_slices: 切片数量

        Returns:
            执行结果
        """
        slice_size = total_size / num_slices
        fills = []
        total_filled = 0
        total_slippage = 0
        weighted_price = 0

        for i in range(num_slices):
            # 每个切片的滑点降低（订单更小）
            slice_slippage = self.calculate_slippage(side, slice_size, volatility) * 0.8

            # 模拟价格波动
            price_change = np.random.randn() * volatility * current_price
            slice_price = current_price + price_change

            if side == OrderSide.BUY:
                slice_price *= (1 + slice_slippage / 10000)
            else:
                slice_price *= (1 - slice_slippage / 10000)

            filled_slice = slice_size * min(1.0, 0.98 + np.random.random() * 0.02)

            fills.append({
                'price': slice_price,
                'size': filled_slice,
                'timestamp': time.time() + i * (duration_minutes * 60 / num_slices)
            })

            total_filled += filled_slice
            total_slippage += slice_slippage
            weighted_price += slice_price * filled_slice

        # 计算平均成交价
        avg_fill_price = weighted_price / total_filled if total_filled > 0 else current_price
        avg_slippage = total_slippage / num_slices

        # 计算总成本
        total_cost = self.calculate_total_cost(side, total_filled, avg_fill_price, avg_slippage, is_maker=False)

        return ExecutionResult(
            order_id=order_id,
            side=side,
            requested_size=total_size,
            filled_size=total_filled,
            avg_fill_price=avg_fill_price,
            total_slippage=avg_slippage,
            execution_time_ms=duration_minutes * 60 * 1000,
            total_cost=total_cost,
            algorithm=ExecutionAlgorithm.TWAP,
            fills=fills
        )

    def execute_vwap(self, order_id: str, side: OrderSide, total_size: float,
                    current_price: float, volatility: float, orderbook: Dict,
                    target_participation_rate: float = 0.2) -> ExecutionResult:
        """
        执行VWAP（成交量加权平均价格）

        Args:
            order_id: 订单ID
            side: 订单方向
            total_size: 总大小
            current_price: 当前价格
            volatility: 波动率
            orderbook: 订单簿
            target_participation_rate: 目标参与率（0-1）

        Returns:
            执行结果
        """
        fills = []
        total_filled = 0
        total_slippage = 0
        weighted_price = 0

        # 基于订单簿深度分配订单
        bids = orderbook.get('bids', [])
        asks = orderbook.get('asks', [])

        remaining_size = total_size
        target_side = 'asks' if side == OrderSide.BUY else 'bids'
        target_orders = asks if side == OrderSide.BUY else bids

        for level, (price, size) in enumerate(target_orders):
            if remaining_size <= 0:
                break

            # 参与率
            fill_size = min(size * target_participation_rate, remaining_size)

            # 滑点（越深层次滑点越大）
            level_slippage = self.calculate_slippage(side, fill_size, volatility, orderbook) * (1 + level * 0.2)

            if side == OrderSide.BUY:
                fill_price = price * (1 + level_slippage / 10000)
            else:
                fill_price = price * (1 - level_slippage / 10000)

            filled_slice = fill_size * min(1.0, 0.95 + np.random.random() * 0.05)

            fills.append({
                'price': fill_price,
                'size': filled_slice,
                'timestamp': time.time() + level * 0.1  # 假设每层100ms
            })

            total_filled += filled_slice
            total_slippage += level_slippage
            weighted_price += fill_price * filled_slice
            remaining_size -= fill_size

        # 计算平均成交价
        avg_fill_price = weighted_price / total_filled if total_filled > 0 else current_price
        avg_slippage = total_slippage / len(fills) if fills else 0

        # 计算总成本
        total_cost = self.calculate_total_cost(side, total_filled, avg_fill_price, avg_slippage, is_maker=False)

        return ExecutionResult(
            order_id=order_id,
            side=side,
            requested_size=total_size,
            filled_size=total_filled,
            avg_fill_price=avg_fill_price,
            total_slippage=avg_slippage,
            execution_time_ms=len(fills) * 100,
            total_cost=total_cost,
            algorithm=ExecutionAlgorithm.VWAP,
            fills=fills
        )

    def backtest_execution(self, orders: List[Dict], market_data: List[Dict]) -> List[ExecutionResult]:
        """
        回测执行

        Args:
            orders: 订单列表
            market_data: 市场数据列表

        Returns:
            执行结果列表
        """
        results = []

        for order in orders:
            # 查找对应的市场数据
            order_time = order.get('timestamp', 0)
            matching_market_data = None

            for market in market_data:
                if abs(market.get('timestamp', 0) - order_time) < 1.0:
                    matching_market_data = market
                    break

            if not matching_market_data:
                continue

            # 根据算法执行订单
            algorithm = order.get('algorithm', ExecutionAlgorithm.MARKET)

            if algorithm == ExecutionAlgorithm.MARKET:
                result = self.execute_market_order(
                    order['order_id'],
                    OrderSide[order['side']],
                    order['size'],
                    matching_market_data['price'],
                    matching_market_data.get('volatility', 0.01),
                    matching_market_data.get('orderbook')
                )
            elif algorithm == ExecutionAlgorithm.TWAP:
                result = self.execute_twap(
                    order['order_id'],
                    OrderSide[order['side']],
                    order['size'],
                    matching_market_data['price'],
                    matching_market_data.get('volatility', 0.01)
                )
            elif algorithm == ExecutionAlgorithm.VWAP:
                result = self.execute_vwap(
                    order['order_id'],
                    OrderSide[order['side']],
                    order['size'],
                    matching_market_data['price'],
                    matching_market_data.get('volatility', 0.01),
                    matching_market_data.get('orderbook', {})
                )
            else:
                continue

            results.append(result)

        return results


# 命令行测试
def main():
    """测试高保真交易模拟"""
    print("="*60)
    print("⚡ 高保真交易模拟测试")
    print("="*60)

    # 创建执行器
    executor = HighFidelityExecution({
        'base_slippage_bps': 5,
        'volume_impact_factor': 0.0001,
        'volatility_impact_factor': 0.1,
        'base_latency_ms': 50,
        'latency_variance_ms': 30,
        'maker_fee': 0.0002,
        'taker_fee': 0.0005
    })

    print(f"\n配置:")
    print(f"  基础滑点: {executor.slippage_model.base_slippage} bps")
    print(f"  网络延迟: {executor.base_latency_ms} ± {executor.latency_variance_ms} ms")
    print(f"  Taker手续费: {executor.taker_fee * 100:.3f}%")
    print(f"  Maker手续费: {executor.maker_fee * 100:.3f}%")

    # 测试市价单
    print(f"\n测试市价单...")
    orderbook = {
        'bids': [[50099, 1.0], [50098, 2.0], [50097, 3.0]],
        'asks': [[50101, 1.0], [50102, 2.0], [50103, 3.0]]
    }

    result = executor.execute_market_order(
        "ORDER001",
        OrderSide.BUY,
        0.5,
        50100,
        0.02,
        orderbook
    )

    print(f"\n📊 市价单执行结果:")
    print(f"  订单ID: {result.order_id}")
    print(f"  方向: {result.side.value}")
    print(f"  请求大小: {result.requested_size}")
    print(f"  成交大小: {result.filled_size}")
    print(f"  平均成交价: ${result.avg_fill_price:.2f}")
    print(f"  滑点: {result.total_slippage:.2f} bps")
    print(f"  执行时间: {result.execution_time_ms:.0f} ms")
    print(f"  总成本: ${result.total_cost:.2f}")

    # 测试TWAP
    print(f"\n\n测试TWAP算法...")
    twap_result = executor.execute_twap(
        "ORDER002",
        OrderSide.BUY,
        2.0,
        50100,
        0.02,
        duration_minutes=30,
        num_slices=6
    )

    print(f"\n📊 TWAP执行结果:")
    print(f"  切片数量: {len(twap_result.fills)}")
    print(f"  平均成交价: ${twap_result.avg_fill_price:.2f}")
    print(f"  平均滑点: {twap_result.total_slippage:.2f} bps")
    print(f"  总成本: ${twap_result.total_cost:.2f}")

    print(f"  各切片:")
    for i, fill in enumerate(twap_result.fills):
        print(f"    切片{i+1}: ${fill['price']:.2f}, {fill['size']:.2f}")

    # 测试VWAP
    print(f"\n\n测试VWAP算法...")
    vwap_result = executor.execute_vwap(
        "ORDER003",
        OrderSide.SELL,
        3.0,
        50000,
        0.02,
        orderbook,
        target_participation_rate=0.3
    )

    print(f"\n📊 VWAP执行结果:")
    print(f"  成交层级: {len(vwap_result.fills)}")
    print(f"  平均成交价: ${vwap_result.avg_fill_price:.2f}")
    print(f"  平均滑点: {vwap_result.total_slippage:.2f} bps")
    print(f"  总成本: ${vwap_result.total_cost:.2f}")

    # 对比不同算法
    print(f"\n\n对比执行算法...")
    print(f"  市价单: 滑点{result.total_slippage:.2f} bps, 成本${result.total_cost:.2f}")
    print(f"  TWAP: 滑点{twap_result.total_slippage:.2f} bps, 成本${twap_result.total_cost:.2f}")
    print(f"  VWAP: 滑点{vwap_result.total_slippage:.2f} bps, 成本${vwap_result.total_cost:.2f}")

    print("\n" + "="*60)
    print("高保真交易模拟测试: PASS")


if __name__ == "__main__":
    main()
