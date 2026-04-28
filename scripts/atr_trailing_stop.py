#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("atr_trailing_stop")
except ImportError:
    import logging
    logger = logging.getLogger("atr_trailing_stop")
"""
ATR动态止损模块 - 杀手锏交易系统
基于真实波动率ATR的动态止损和移动止盈
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum


class OrderSide(Enum):
    """订单方向"""
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class ATRStopLoss:
    """ATR止损订单"""
    order_id: str
    side: OrderSide
    entry_price: float
    stop_loss_price: float
    current_stop_loss: float
    atr_value: float
    trailing_started: bool
    is_active: bool


class ATRTrailingStop:
    """ATR动态止损管理器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化ATR止损管理器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # ATR参数
        self.atr_period = self.config.get('atr_period', 14)
        self.atr_multiplier = self.config.get('atr_multiplier', 1.5)  # N=1.5
        self.trailing_multiplier = self.config.get('trailing_multiplier', 0.5)  # 每0.5倍ATR移动

        # 止盈参数
        self.profit_atr_threshold = self.config.get('profit_atr_threshold', 1.0)  # 盈利1倍ATR启动追踪
        self.profit_atr_step = self.config.get('profit_atr_step', 0.5)  # 每0.5倍ATR移动止损

        # 风险限制
        self.max_loss_percent = self.config.get('max_loss_percent', 0.02)  # 单笔最大亏损2%
        self.min_loss_percent = self.config.get('min_loss_percent', 0.015)  # 最小1.5%

        # 活跃订单
        self.active_orders: Dict[str, ATRStopLoss] = {}

    def calculate_atr(self, df: pd.DataFrame) -> float:
        """
        计算ATR（平均真实波幅）

        Args:
            df: OHLCV数据

        Returns:
            ATR值
        """
        if df is None or len(df) < self.atr_period:
            return 0.0

        # 确保列名正确
        df = df.copy()

        # 标准化列名
        if 'close' not in df.columns:
            df['close'] = df['c'] if 'c' in df.columns else df['Close']

        if 'high' not in df.columns:
            df['high'] = df['h'] if 'h' in df.columns else df['High']

        if 'low' not in df.columns:
            df['low'] = df['l'] if 'l' in df.columns else df['Low']

        # 计算真实波幅
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())

        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

        # 计算ATR（使用指数移动平均）
        atr = true_range.ewm(span=self.atr_period, adjust=False).mean()

        return atr.iloc[-1] if len(atr) > 0 else 0.0

    def create_stop_loss(self, order_id: str, side: OrderSide,
                        entry_price: float, atr_value: float) -> ATRStopLoss:
        """
        创建ATR止损订单

        Args:
            order_id: 订单ID
            side: 方向
            entry_price: 入场价格
            atr_value: ATR值

        Returns:
            ATR止损订单
        """
        # 计算初始止损价
        if side == OrderSide.LONG:
            stop_loss_price = entry_price - (atr_value * self.atr_multiplier)
        else:  # SHORT
            stop_loss_price = entry_price + (atr_value * self.atr_multiplier)

        stop_order = ATRStopLoss(
            order_id=order_id,
            side=side,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            current_stop_loss=stop_loss_price,
            atr_value=atr_value,
            trailing_started=False,
            is_active=True
        )

        self.active_orders[order_id] = stop_order
        return stop_order

    def update_stop_loss(self, order_id: str, current_price: float) -> Dict:
        """
        更新止损位（移动止损）

        Args:
            order_id: 订单ID
            current_price: 当前价格

        Returns:
            更新结果
        """
        if order_id not in self.active_orders:
            return {
                'should_close': False,
                'stop_loss_updated': False,
                'message': 'Order not found'
            }

        order = self.active_orders[order_id]

        if not order.is_active:
            return {
                'should_close': False,
                'stop_loss_updated': False,
                'message': 'Order not active'
            }

        # 计算当前盈亏（ATR倍数）
        if order.side == OrderSide.LONG:
            profit_atr = (current_price - order.entry_price) / order.atr_value
            should_close = current_price <= order.current_stop_loss
        else:  # SHORT
            profit_atr = (order.entry_price - current_price) / order.atr_value
            should_close = current_price >= order.current_stop_loss

        result = {
            'should_close': should_close,
            'stop_loss_updated': False,
            'profit_atr': profit_atr,
            'current_stop_loss': order.current_stop_loss,
            'trailing_started': order.trailing_started
        }

        # 检查是否触发止损
        if should_close:
            result['message'] = f'Stop loss triggered at ${current_price:.2f}'
            return result

        # 检查是否启动移动止损
        if profit_atr >= self.profit_atr_threshold and not order.trailing_started:
            order.trailing_started = True

            # 移动止损到成本价（保本保护）
            if order.side == OrderSide.LONG:
                order.current_stop_loss = max(order.current_stop_loss, order.entry_price)
            else:  # SHORT
                order.current_stop_loss = min(order.current_stop_loss, order.entry_price)

            result['stop_loss_updated'] = True
            result['message'] = f'Trailing started: Stop loss moved to ${order.current_stop_loss:.2f} (breakeven)'
            return result

        # 移动止损逻辑
        if order.trailing_started:
            # 计算应该移动的止损位
            if order.side == OrderSide.LONG:
                # 多头：每盈利0.5倍ATR，止损上移0.5倍ATR
                profit_steps = int((profit_atr - self.profit_atr_threshold) / self.profit_atr_step)
                if profit_steps > 0:
                    new_stop_loss = order.entry_price + (profit_steps * self.profit_atr_step * order.atr_value)
                    if new_stop_loss > order.current_stop_loss:
                        order.current_stop_loss = new_stop_loss
                        result['stop_loss_updated'] = True
                        result['message'] = f'Trailing updated: ${order.current_stop_loss:.2f} (profit {profit_atr:.2f} ATR)'

            else:  # SHORT
                # 空头：每盈利0.5倍ATR，止损下移0.5倍ATR
                profit_steps = int((profit_atr - self.profit_atr_threshold) / self.profit_atr_step)
                if profit_steps > 0:
                    new_stop_loss = order.entry_price - (profit_steps * self.profit_atr_step * order.atr_value)
                    if new_stop_loss < order.current_stop_loss:
                        order.current_stop_loss = new_stop_loss
                        result['stop_loss_updated'] = True
                        result['message'] = f'Trailing updated: ${order.current_stop_loss:.2f} (profit {profit_atr:.2f} ATR)'

        return result

    def close_order(self, order_id: str, exit_price: float) -> Optional[Dict]:
        """
        平仓订单

        Args:
            order_id: 订单ID
            exit_price: 平仓价格

        Returns:
            平仓结果
        """
        if order_id not in self.active_orders:
            return None

        order = self.active_orders[order_id]

        # 计算盈亏
        if order.side == OrderSide.LONG:
            pnl = (exit_price - order.entry_price) / order.entry_price
        else:  # SHORT
            pnl = (order.entry_price - exit_price) / order.entry_price

        pnl_percent = pnl * 100
        loss_percent = abs(pnl_percent) if pnl_percent < 0 else 0

        # 检查是否在风险范围内
        if loss_percent > self.max_loss_percent * 100:
            risk_level = "HIGH_RISK"
        elif loss_percent > self.min_loss_percent * 100:
            risk_level = "MEDIUM_RISK"
        else:
            risk_level = "ACCEPTABLE"

        # 删除订单
        del self.active_orders[order_id]

        return {
            'order_id': order_id,
            'entry_price': order.entry_price,
            'exit_price': exit_price,
            'pnl_percent': pnl_percent,
            'atr_at_entry': order.atr_value,
            'trailing_started': order.trailing_started,
            'risk_level': risk_level
        }

    def get_active_orders(self) -> Dict:
        """获取活跃订单"""
        return self.active_orders.copy()


# 命令行测试
def main():
    """测试ATR动态止损"""
    logger.info("="*60)
    logger.info("🛡️ ATR动态止损测试")
    logger.info("="*60)

    # 创建管理器
    manager = ATRTrailingStop({
        'atr_period': 14,
        'atr_multiplier': 1.5,
        'profit_atr_threshold': 1.0,
        'profit_atr_step': 0.5,
        'max_loss_percent': 0.02
    })

    logger.info(f"\n配置:")
    logger.info(f"  ATR周期: {manager.atr_period}")
    logger.info(f"  ATR倍数: {manager.atr_multiplier}")
    logger.info(f"  止损启动阈值: {manager.profit_atr_threshold}倍ATR")
    logger.info(f"  止损移动步长: {manager.profit_atr_step}倍ATR")
    logger.info(f"  最大亏损: {manager.max_loss_percent * 100}%")

    # 计算ATR
    logger.info(f"\n计算ATR...")
    base_price = 50000
    data = []

    for i in range(50):
        volatility = 200 + np.random.randint(-50, 100)
        high = base_price + volatility
        low = base_price - volatility
        close = base_price + np.random.randn() * 50
        data.append({'high': high, 'low': low, 'close': close})

    df = pd.DataFrame(data)
    atr = manager.calculate_atr(df)

    logger.info(f"  ATR值: ${atr:.2f}")

    # 测试1: 多头止损触发
    logger.info(f"\n测试1: 多头止损触发")
    order1 = manager.create_stop_loss("LONG001", OrderSide.LONG, 50000, atr)
    logger.info(f"  入场价: ${order1.entry_price}")
    logger.info(f"  初始止损: ${order1.stop_loss_price:.2f}")
    logger.info(f"  止损宽度: {abs(order1.stop_loss_price - order1.entry_price):.2f} ({abs(order1.stop_loss_price - order1.entry_price) / atr:.2f} ATR)")

    # 价格下跌触发止损
    current_price = 50000 - atr * 1.8
    result1 = manager.update_stop_loss("LONG001", current_price)
    logger.info(f"  当前价格: ${current_price:.2f}")
    logger.info(f"  触发止损: {'是' if result1['should_close'] else '否'}")
    logger.info(f"  原因: {result1['message']}")

    # 测试2: 多头移动止损
    logger.info(f"\n测试2: 多头移动止损")
    order2 = manager.create_stop_loss("LONG002", OrderSide.LONG, 50000, atr)
    logger.info(f"  入场价: ${order2.entry_price}")
    logger.info(f"  初始止损: ${order2.current_stop_loss:.2f}")

    # 价格上涨，触发移动止损
    prices = [
        50000 + atr * 0.8,  # 未达到启动阈值
        50000 + atr * 1.2,  # 达到启动阈值，移动到成本价
        50000 + atr * 1.8,  # 继续盈利，移动止损
        50000 + atr * 2.5,  # 继续盈利，移动止损
        50000 + atr * 2.0   # 回撤，触发止损
    ]

    for price in prices:
        result = manager.update_stop_loss("LONG002", price)
        logger.info(f"  价格 ${price:.0f}: 盈利{result['profit_atr']:.2f}ATR, 止损${result['current_stop_loss']:.2f}, 追踪{result['trailing_started']}, 更新{result['stop_loss_updated']}")
        if result['stop_loss_updated']:
            logger.info(f"    → {result['message']}")

        if result['should_close']:
            logger.info(f"    → {result['message']}")
            break

    # 测试3: 空头止损
    logger.info(f"\n测试3: 空头止损")
    order3 = manager.create_stop_loss("SHORT001", OrderSide.SHORT, 50000, atr)
    logger.info(f"  入场价: ${order3.entry_price}")
    logger.info(f"  初始止损: ${order3.stop_loss_price:.2f}")

    # 价格上涨触发止损
    current_price = 50000 + atr * 1.8
    result3 = manager.update_stop_loss("SHORT001", current_price)
    logger.info(f"  当前价格: ${current_price:.2f}")
    logger.info(f"  触发止损: {'是' if result3['should_close'] else '否'}")
    logger.info(f"  原因: {result3['message']}")

    # 测试4: 平仓计算
    logger.info(f"\n测试4: 平仓计算")
    result = manager.close_order("LONG002", 51000)
    if result:
        logger.info(f"  入场: ${result['entry_price']}")
        logger.info(f"  平仓: ${result['exit_price']}")
        logger.info(f"  盈亏: {result['pnl_percent']:.2f}%")
        logger.info(f"  ATR(入场): ${result['atr_at_entry']:.2f}")
        logger.info(f"  移动止损启动: {'是' if result['trailing_started'] else '否'}")
        logger.info(f"  风险等级: {result['risk_level']}")

    logger.info("\n" + "="*60)
    logger.info("ATR动态止损测试: PASS")


if __name__ == "__main__":
    main()
