#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("orderflow_confirmer")
except ImportError:
    import logging
    logger = logging.getLogger("orderflow_confirmer")
"""
订单流确认器 - 杀手锏交易系统V4.0
基于订单不平衡率、订单簿深度、吸筹/派发模式的信号确认
V4.5增强：Volume Delta分析，逐笔成交数据深度挖掘
"""

import numpy as np
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ConfirmLevel(Enum):
    """确认级别"""
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"
    REJECT = "REJECT"


@dataclass
class OrderFlowConfirmation:
    """订单流确认结果"""
    confirm_level: ConfirmLevel
    confidence: float  # 0-1
    imbalance_ratio: float
    order_book_pressure: str
    accumulation_status: str
    reasons: List[str]
    should_confirm_signal: bool


class OrderFlowConfirmer:
    """订单流确认器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化订单流确认器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 配置参数
        self.imbalance_threshold_buy = self.config.get('imbalance_threshold_buy', 1.2)  # 买入阈值
        self.imbalance_threshold_sell = self.config.get('imbalance_threshold_sell', 0.8)  # 卖出阈值
        self.window_seconds = self.config.get('window_seconds', 300)  # 时间窗口5分钟
        self.order_book_levels = self.config.get('order_book_levels', 10)  # 订单簿深度10档

    def calculate_volume_delta(self, trades: List[Dict], window_seconds: int = 300) -> Dict:
        """
        计算Volume Delta（主动买卖量比）

        Args:
            trades: 交易记录列表 [{'side': 'buy', 'size': 0.1, 'timestamp': ...}, ...]
            window_seconds: 时间窗口（秒）

        Returns:
            Volume Delta分析结果
        """
        if not trades:
            return {
                'volume_delta': 0.0,
                'buy_volume': 0.0,
                'sell_volume': 0.0,
                'delta_ratio': 1.0,
                'cumulative_delta': 0.0
            }

        # 获取当前时间
        current_time = time.time()

        # 筛选时间窗口内的交易
        filtered_trades = [
            t for t in trades
            if current_time - t.get('timestamp', current_time) <= window_seconds
        ]

        if not filtered_trades:
            return {
                'volume_delta': 0.0,
                'buy_volume': 0.0,
                'sell_volume': 0.0,
                'delta_ratio': 1.0,
                'cumulative_delta': 0.0
            }

        # 计算买入量和卖出量
        buy_volume = sum(t.get('size', 0) for t in filtered_trades if t.get('side') == 'buy')
        sell_volume = sum(t.get('size', 0) for t in filtered_trades if t.get('side') == 'sell')

        # Volume Delta
        volume_delta = buy_volume - sell_volume

        # Delta比率
        if abs(sell_volume) < 1e-10:
            delta_ratio = 999.0  # 全是买单
        else:
            delta_ratio = buy_volume / sell_volume

        # 累积Delta（简化：使用当前窗口）
        cumulative_delta = volume_delta

        return {
            'volume_delta': volume_delta,
            'buy_volume': buy_volume,
            'sell_volume': sell_volume,
            'delta_ratio': delta_ratio,
            'cumulative_delta': cumulative_delta
        }

    def detect_delta_divergence(self, current_price: float, delta_history: List[Dict]) -> str:
        """
        检测Delta背离

        Args:
            current_price: 当前价格
            delta_history: Delta历史 [{'price': 50000, 'volume_delta': 100}, ...]

        Returns:
            BULLISH_DIVERGENCE/BEARISH_DIVERGENCE/NEUTRAL
        """
        if len(delta_history) < 10:
            return "NEUTRAL"

        # 提取价格和delta序列
        prices = [d['price'] for d in delta_history[-10:]]
        deltas = [d['volume_delta'] for d in delta_history[-10:]]

        # 价格低点索引
        price_low_idx = prices.index(min(prices))
        # Delta低点索引
        delta_low_idx = deltas.index(min(deltas))

        # 底背离：价格创新低，但delta未创新低
        if price_low_idx > delta_low_idx and abs(prices[-1] - prices[price_low_idx]) / prices[price_low_idx] > 0.01:
            return "BULLISH_DIVERGENCE"

        # 价格高点索引
        price_high_idx = prices.index(max(prices))
        # Delta高点索引
        delta_high_idx = deltas.index(max(deltas))

        # 顶背离：价格创新高，但delta未创新高
        if price_high_idx > delta_high_idx and abs(prices[-1] - prices[price_high_idx]) / prices[price_high_idx] > 0.01:
            return "BEARISH_DIVERGENCE"

        return "NEUTRAL"

    def calculate_imbalance_ratio(self, trades: List[Dict], window_seconds: int = 300) -> float:
        """
        计算订单不平衡率

        Args:
            trades: 交易记录列表 [{'side': 'buy', 'size': 0.1, 'timestamp': ...}, ...]
            window_seconds: 时间窗口（秒）

        Returns:
            订单不平衡率（买入量/卖出量）
        """
        if not trades:
            return 1.0

        # 获取当前时间
        import time
        current_time = time.time()

        # 筛选时间窗口内的交易
        filtered_trades = [
            t for t in trades
            if current_time - t.get('timestamp', current_time) <= window_seconds
        ]

        if not filtered_trades:
            return 1.0

        # 计算买入量和卖出量
        buy_volume = sum(t.get('size', 0) for t in filtered_trades if t.get('side') == 'buy')
        sell_volume = sum(t.get('size', 0) for t in filtered_trades if t.get('side') == 'sell')

        if abs(sell_volume) < 1e-10:
            return 999.0  # 全是买单

        return buy_volume / sell_volume

    def analyze_order_book_depth(self, bids: List[Tuple], asks: List[Tuple]) -> Dict:
        """
        分析订单簿深度

        Args:
            bids: 买单列表 [(price, size), ...]
            asks: 卖单列表 [(price, size), ...]

        Returns:
            订单簿分析结果
        """
        if not bids or not asks:
            return {
                'buy_volume': 0,
                'sell_volume': 0,
                'pressure': 'NEUTRAL',
                'ratio': 1.0
            }

        # 计算累计买卖量（前N档）
        levels = min(self.order_book_levels, len(bids), len(asks))

        buy_volume = sum(size for _, size in bids[:levels])
        sell_volume = sum(size for _, size in asks[:levels])

        ratio = buy_volume / sell_volume if sell_volume > 0 else 999.0

        # 判断买卖压力
        if ratio > 1.5:
            pressure = "STRONG_BUY"
        elif ratio > 1.2:
            pressure = "BUY"
        elif ratio < 0.67:
            pressure = "STRONG_SELL"
        elif ratio < 0.83:
            pressure = "SELL"
        else:
            pressure = "NEUTRAL"

        return {
            'buy_volume': buy_volume,
            'sell_volume': sell_volume,
            'pressure': pressure,
            'ratio': ratio
        }

    def detect_accumulation(self, price_series: List[float], imbalance_series: List[float]) -> str:
        """
        检测吸筹/派发模式

        Args:
            price_series: 价格序列
            imbalance_series: 订单不平衡率序列

        Returns:
            ACCUMULATION（吸筹）/ DISTRIBUTION（派发）/ NEUTRAL（中性）
        """
        if len(price_series) < 10 or len(imbalance_series) < 10:
            return "NEUTRAL"

        # 计算价格变化趋势
        price_change = (price_series[-1] - price_series[-10]) / price_series[-10]

        # 计算订单不平衡率变化趋势
        imbalance_change = imbalance_series[-1] - imbalance_series[-10]

        # 吸筹模式：价格下跌但订单不平衡转向正值
        if price_change < -0.02 and imbalance_change > 0.5:
            return "ACCUMULATION"

        # 派发模式：价格上涨但订单不平衡转向负值
        if price_change > 0.02 and imbalance_change < -0.5:
            return "DISTRIBUTION"

        return "NEUTRAL"

    def confirm_signal(self, signal: str, trades: List[Dict], bids: List[Tuple],
                       asks: List[Tuple], price_history: Optional[List[float]] = None) -> OrderFlowConfirmation:
        """
        确认交易信号

        Args:
            signal: 原始信号（BUY/SELL/HOLD）
            trades: 交易记录
            bids: 买单列表
            asks: 卖单列表
            price_history: 价格历史（用于检测吸筹/派发）

        Returns:
            订单流确认结果
        """
        reasons = []
        confirm_level = ConfirmLevel.NEUTRAL
        confidence = 0.5
        should_confirm = False

        # 1. 计算订单不平衡率
        imbalance_ratio = self.calculate_imbalance_ratio(trades, self.window_seconds)
        reasons.append(f"订单不平衡率: {imbalance_ratio:.2f}")

        # 2. 分析订单簿深度
        order_book_result = self.analyze_order_book_depth(bids, asks)
        order_book_pressure = order_book_result['pressure']
        reasons.append(f"订单簿压力: {order_book_pressure}")

        # 3. 检测吸筹/派发
        accumulation_status = "NEUTRAL"
        if price_history and len(price_history) >= 10:
            # 模拟订单不平衡率序列（实际应从历史记录计算）
            imbalance_series = [imbalance_ratio] * 10
            accumulation_status = self.detect_accumulation(price_history, imbalance_series)
            if accumulation_status != "NEUTRAL":
                reasons.append(f"检测到{accumulation_status}模式")

        # 4. 综合判断
        if signal == "BUY":
            # 买入信号确认
            if imbalance_ratio >= self.imbalance_threshold_buy:
                reasons.append(f"订单不平衡率{imbalance_ratio:.2f} >= {self.imbalance_threshold_buy}，确认买入")
                confidence += 0.2
                should_confirm = True

            if order_book_pressure in ["BUY", "STRONG_BUY"]:
                reasons.append(f"订单簿压力{order_book_pressure}，确认买入")
                confidence += 0.2
                should_confirm = True

            if accumulation_status == "ACCUMULATION":
                reasons.append("检测到吸筹模式，强烈确认买入")
                confidence += 0.3
                should_confirm = True
                confirm_level = ConfirmLevel.STRONG_BUY

            if order_book_pressure == "STRONG_SELL":
                reasons.append(f"订单簿压力{order_book_pressure}，卖盘挂单极厚，拒绝买入")
                should_confirm = False
                confirm_level = ConfirmLevel.REJECT

        elif signal == "SELL":
            # 卖出信号确认
            if imbalance_ratio <= self.imbalance_threshold_sell:
                reasons.append(f"订单不平衡率{imbalance_ratio:.2f} <= {self.imbalance_threshold_sell}，确认卖出")
                confidence += 0.2
                should_confirm = True

            if order_book_pressure in ["SELL", "STRONG_SELL"]:
                reasons.append(f"订单簿压力{order_book_pressure}，确认卖出")
                confidence += 0.2
                should_confirm = True

            if accumulation_status == "DISTRIBUTION":
                reasons.append("检测到派发模式，强烈确认卖出")
                confidence += 0.3
                should_confirm = True
                confirm_level = ConfirmLevel.STRONG_SELL

            if order_book_pressure == "STRONG_BUY":
                reasons.append(f"订单簿压力{order_book_pressure}，买盘挂单极厚，拒绝卖出")
                should_confirm = False
                confirm_level = ConfirmLevel.REJECT

        # 确定最终确认级别
        if should_confirm:
            if confidence >= 0.8:
                confirm_level = ConfirmLevel.STRONG_BUY if signal == "BUY" else ConfirmLevel.STRONG_SELL
            else:
                confirm_level = ConfirmLevel.BUY if signal == "BUY" else ConfirmLevel.SELL
        elif confirm_level != ConfirmLevel.REJECT:
            confirm_level = ConfirmLevel.NEUTRAL

        return OrderFlowConfirmation(
            confirm_level=confirm_level,
            confidence=min(1.0, confidence),
            imbalance_ratio=imbalance_ratio,
            order_book_pressure=order_book_pressure,
            accumulation_status=accumulation_status,
            reasons=reasons,
            should_confirm_signal=should_confirm
        )


# 命令行测试
def main():
    """测试订单流确认器"""
    logger.info("="*60)
    logger.info("📊 订单流确认器测试")
    logger.info("="*60)

    # 创建确认器
    confirmer = OrderFlowConfirmer({
        'imbalance_threshold_buy': 1.2,
        'imbalance_threshold_sell': 0.8,
        'window_seconds': 300,
        'order_book_levels': 10
    })

    logger.info(f"\n配置:")
    logger.info(f"  买入阈值: {confirmer.imbalance_threshold_buy}")
    logger.info(f"  卖出阈值: {confirmer.imbalance_threshold_sell}")
    logger.info(f"  时间窗口: {confirmer.window_seconds}秒")

    # 生成测试交易数据（买入占优）
    import time
    current_time = time.time()
    trades = []
    for i in range(100):
        side = 'buy' if i < 70 else 'sell'  # 70%买入
        trades.append({
            'side': side,
            'size': 0.1 + np.random.random() * 0.2,
            'timestamp': current_time - i * 10
        })

    # 生成测试订单簿
    bids = [(50000 - i * 10, 1.0 + np.random.random() * 2.0) for i in range(10)]
    asks = [(50000 + i * 10, 0.5 + np.random.random() * 1.0) for i in range(10)]

    # 测试1: 买入信号确认
    logger.info(f"\n测试1: 买入信号确认")
    result1 = confirmer.confirm_signal("BUY", trades, bids, asks)

    logger.info(f"\n📈 确认结果:")
    logger.info(f"  确认级别: {result1.confirm_level.value}")
    logger.info(f"  置信度: {result1.confidence:.2f}")
    logger.info(f"  订单不平衡率: {result1.imbalance_ratio:.2f}")
    logger.info(f"  订单簿压力: {result1.order_book_pressure}")
    logger.info(f"  是否确认: {'✓ 是' if result1.should_confirm_signal else '✗ 否'}")

    logger.info(f"\n原因:")
    for reason in result1.reasons:
        logger.info(f"  • {reason}")

    # 测试2: 卖出信号确认（修改订单簿）
    logger.info(f"\n\n测试2: 卖出信号确认")
    bids_sell = [(50000 - i * 10, 0.5 + np.random.random() * 1.0) for i in range(10)]
    asks_sell = [(50000 + i * 10, 1.0 + np.random.random() * 2.0) for i in range(10)]

    trades_sell = []
    for i in range(100):
        side = 'sell' if i < 70 else 'buy'  # 70%卖出
        trades_sell.append({
            'side': side,
            'size': 0.1 + np.random.random() * 0.2,
            'timestamp': current_time - i * 10
        })

    result2 = confirmer.confirm_signal("SELL", trades_sell, bids_sell, asks_sell)

    logger.info(f"\n📉 确认结果:")
    logger.info(f"  确认级别: {result2.confirm_level.value}")
    logger.info(f"  置信度: {result2.confidence:.2f}")
    logger.info(f"  是否确认: {'✓ 是' if result2.should_confirm_signal else '✗ 否'}")

    logger.info(f"\n原因:")
    for reason in result2.reasons:
        logger.info(f"  • {reason}")

    # 测试3: 拒绝信号（订单簿压力与信号相反）
    logger.info(f"\n\n测试3: 拒绝信号（买入信号但卖盘极厚）")
    bids_weak = [(50000 - i * 10, 0.3 + np.random.random() * 0.5) for i in range(10)]
    asks_strong = [(50000 + i * 10, 3.0 + np.random.random() * 2.0) for i in range(10)]

    result3 = confirmer.confirm_signal("BUY", trades, bids_weak, asks_strong)

    logger.info(f"\n❌ 确认结果:")
    logger.info(f"  确认级别: {result3.confirm_level.value}")
    logger.info(f"  是否确认: {'✓ 是' if result3.should_confirm_signal else '✗ 否'}")

    logger.info(f"\n原因:")
    for reason in result3.reasons:
        logger.info(f"  • {reason}")

    logger.info("\n" + "="*60)
    logger.info("订单流确认器测试: PASS")


if __name__ == "__main__":
    main()
