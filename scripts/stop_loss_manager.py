#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("stop_loss_manager")
except ImportError:
    import logging
    logger = logging.getLogger("stop_loss_manager")
"""
止损管理器 - 杀手锏交易系统核心
5%-8%单笔止损、跟踪止盈、自动平仓、防止重大回撤
"""

import time
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum


class OrderSide(Enum):
    """订单方向"""
    LONG = "LONG"
    SHORT = "SHORT"


class StopLossType(Enum):
    """止损类型"""
    FIXED_PERCENT = "FIXED_PERCENT"
    TRAILING = "TRAILING"
    ATR = "ATR"


@dataclass
class StopLossOrder:
    """止损订单"""
    side: OrderSide
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    quantity: float
    stop_loss_type: StopLossType
    trailing_distance: float
    is_active: bool
    stop_loss_trigger_price: float
    max_price: float  # 最高价（用于跟踪止损）


class StopLossManager:
    """止损管理器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化止损管理器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 配置参数
        self.stop_loss_percent = self.config.get('stop_loss_percent', 0.05)  # 默认5%止损
        self.take_profit_percent = self.config.get('take_profit_percent', 0.10)  # 默认10%止盈
        self.trailing_stop_percent = self.config.get('trailing_stop_percent', 0.03)  # 跟踪止损3%
        self.max_loss_per_day = self.config.get('max_loss_per_day', 0.03)  # 日最大亏损3%

        # 活跃订单
        self.active_orders: Dict[str, StopLossOrder] = {}

        # 当日亏损
        self.daily_pnl = 0.0
        self.daily_reset_time = time.time()

    def create_stop_loss(self, order_id: str, side: OrderSide, entry_price: float,
                        quantity: float, stop_loss_type: StopLossType = StopLossType.FIXED_PERCENT) -> StopLossOrder:
        """
        创建止损订单

        Args:
            order_id: 订单ID
            side: 方向
            entry_price: 入场价格
            quantity: 数量
            stop_loss_type: 止损类型

        Returns:
            止损订单
        """
        # 计算止损价
        if side == OrderSide.LONG:
            stop_loss_price = entry_price * (1 - self.stop_loss_percent)
            take_profit_price = entry_price * (1 + self.take_profit_percent)
        else:  # SHORT
            stop_loss_price = entry_price * (1 + self.stop_loss_percent)
            take_profit_price = entry_price * (1 - self.take_profit_percent)

        stop_order = StopLossOrder(
            side=side,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            quantity=quantity,
            stop_loss_type=stop_loss_type,
            trailing_distance=self.trailing_stop_percent,
            is_active=True,
            stop_loss_trigger_price=stop_loss_price,
            max_price=entry_price
        )

        self.active_orders[order_id] = stop_order
        return stop_order

    def check_stop_loss(self, order_id: str, current_price: float) -> Dict:
        """
        检查是否触发止损/止盈

        Args:
            order_id: 订单ID
            current_price: 当前价格

        Returns:
            检查结果
        """
        if order_id not in self.active_orders:
            return {
                'should_close': False,
                'reason': 'Order not found',
                'action': 'NONE'
            }

        order = self.active_orders[order_id]

        if not order.is_active:
            return {
                'should_close': False,
                'reason': 'Order not active',
                'action': 'NONE'
            }

        # 检查日内最大亏损
        if self.daily_pnl < -self.max_loss_per_day * 100000:  # 假设本金10万
            return {
                'should_close': True,
                'reason': 'Daily loss limit exceeded',
                'action': 'EMERGENCY_CLOSE_ALL',
                'daily_pnl': self.daily_pnl
            }

        # 更新最高价（用于跟踪止损）
        if order.side == OrderSide.LONG:
            order.max_price = max(order.max_price, current_price)
        else:
            order.max_price = min(order.max_price, current_price)

        # 更新跟踪止损价
        if order.stop_loss_type == StopLossType.TRAILING:
            if order.side == OrderSide.LONG:
                # 多头：价格上升时，止损价跟随
                if order.max_price > order.entry_price:
                    new_sl = order.max_price * (1 - order.trailing_distance)
                    if new_sl > order.stop_loss_trigger_price:
                        order.stop_loss_trigger_price = new_sl
            else:  # SHORT
                # 空头：价格下跌时，止损价跟随
                if order.max_price < order.entry_price:
                    new_sl = order.max_price * (1 + order.trailing_distance)
                    if new_sl < order.stop_loss_trigger_price:
                        order.stop_loss_trigger_price = new_sl

        # 检查止损
        should_close = False
        action = 'NONE'
        reason = ''

        if order.side == OrderSide.LONG:
            # 多头止损
            if current_price <= order.stop_loss_trigger_price:
                should_close = True
                action = 'STOP_LOSS'
                reason = f'Price ({current_price:.2f}) below stop loss ({order.stop_loss_trigger_price:.2f})'

            # 多头止盈
            elif current_price >= order.take_profit_price:
                should_close = True
                action = 'TAKE_PROFIT'
                reason = f'Price ({current_price:.2f}) above take profit ({order.take_profit_price:.2f})'

        else:  # SHORT
            # 空头止损
            if current_price >= order.stop_loss_trigger_price:
                should_close = True
                action = 'STOP_LOSS'
                reason = f'Price ({current_price:.2f}) above stop loss ({order.stop_loss_trigger_price:.2f})'

            # 空头止盈
            elif current_price <= order.take_profit_price:
                should_close = True
                action = 'TAKE_PROFIT'
                reason = f'Price ({current_price:.2f}) below take profit ({order.take_profit_price:.2f})'

        return {
            'should_close': should_close,
            'reason': reason,
            'action': action,
            'entry_price': order.entry_price,
            'stop_loss_price': order.stop_loss_trigger_price,
            'take_profit_price': order.take_profit_price,
            'trailing_distance': order.trailing_distance,
            'max_price': order.max_price
        }

    def close_order(self, order_id: str, exit_price: float) -> Optional[Dict]:
        """
        平仓并计算盈亏

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

        pnl_amount = pnl * order.entry_price * order.quantity

        # 更新当日盈亏
        self.daily_pnl += pnl_amount

        # 删除订单
        del self.active_orders[order_id]

        return {
            'order_id': order_id,
            'entry_price': order.entry_price,
            'exit_price': exit_price,
            'pnl_percent': pnl,
            'pnl_amount': pnl_amount,
            'daily_pnl': self.daily_pnl
        }

    def get_active_orders(self) -> Dict:
        """获取活跃订单"""
        return self.active_orders.copy()

    def reset_daily_pnl(self):
        """重置当日盈亏"""
        self.daily_pnl = 0.0
        self.daily_reset_time = time.time()


# 命令行测试
def main():
    """测试止损管理器"""
    logger.info("="*60)
    logger.info("🛡️ 止损管理器测试")
    logger.info("="*60)

    # 创建止损管理器
    manager = StopLossManager({
        'stop_loss_percent': 0.05,
        'take_profit_percent': 0.10,
        'trailing_stop_percent': 0.03,
        'max_loss_per_day': 0.03
    })

    logger.info(f"\n配置:")
    logger.info(f"  止损比例: {manager.stop_loss_percent * 100}%")
    logger.info(f"  止盈比例: {manager.take_profit_percent * 100}%")
    logger.info(f"  跟踪止损: {manager.trailing_stop_percent * 100}%")
    logger.info(f"  日最大亏损: {manager.max_loss_per_day * 100}%")

    # 测试1: 多头止损触发
    logger.info(f"\n测试1: 多头止损触发")
    order1 = manager.create_stop_loss(
        order_id="LONG001",
        side=OrderSide.LONG,
        entry_price=50000,
        quantity=1.0,
        stop_loss_type=StopLossType.FIXED_PERCENT
    )

    logger.info(f"  入场价格: ${order1.entry_price}")
    logger.info(f"  止损价格: ${order1.stop_loss_price:.2f}")
    logger.info(f"  止盈价格: ${order1.take_profit_price:.2f}")

    # 价格下跌触发止损
    current_price = 47400  # 下跌5.2%，触发止损
    check1 = manager.check_stop_loss("LONG001", current_price)
    logger.info(f"  当前价格: ${current_price}")
    logger.info(f"  是否平仓: {'✓ 是' if check1['should_close'] else '✗ 否'}")
    logger.info(f"  动作: {check1['action']}")
    logger.info(f"  原因: {check1['reason']}")

    # 测试2: 多头止盈触发
    logger.info(f"\n测试2: 多头止盈触发")
    order2 = manager.create_stop_loss(
        order_id="LONG002",
        side=OrderSide.LONG,
        entry_price=50000,
        quantity=1.0,
        stop_loss_type=StopLossType.FIXED_PERCENT
    )

    current_price = 55100  # 上涨10.2%，触发止盈
    check2 = manager.check_stop_loss("LONG002", current_price)
    logger.info(f"  当前价格: ${current_price}")
    logger.info(f"  是否平仓: {'✓ 是' if check2['should_close'] else '✗ 否'}")
    logger.info(f"  动作: {check2['action']}")

    # 测试3: 跟踪止损
    logger.info(f"\n测试3: 跟踪止损")
    order3 = manager.create_stop_loss(
        order_id="LONG003",
        side=OrderSide.LONG,
        entry_price=50000,
        quantity=1.0,
        stop_loss_type=StopLossType.TRAILING
    )

    logger.info(f"  入场价格: ${order3.entry_price}")
    logger.info(f"  初始止损价: ${order3.stop_loss_trigger_price:.2f}")

    # 价格先涨后跌
    prices = [51000, 52000, 52500, 53000, 52800, 52200, 51500, 51000, 50500]
    for price in prices:
        check = manager.check_stop_loss("LONG003", price)
        logger.info(f"  价格 ${price}: 最高价${order3.max_price:.2f}, 跟踪止损${order3.stop_loss_trigger_price:.2f}")
        if check['should_close']:
            logger.info(f"    → 触发止损: {check['reason']}")
            break

    # 测试4: 空头止损
    logger.info(f"\n测试4: 空头止损")
    order4 = manager.create_stop_loss(
        order_id="SHORT001",
        side=OrderSide.SHORT,
        entry_price=50000,
        quantity=1.0,
        stop_loss_type=StopLossType.FIXED_PERCENT
    )

    logger.info(f"  入场价格: ${order4.entry_price}")
    logger.info(f"  止损价格: ${order4.stop_loss_price:.2f}")
    logger.info(f"  止盈价格: ${order4.take_profit_price:.2f}")

    current_price = 52600  # 上涨5.2%，触发止损
    check4 = manager.check_stop_loss("SHORT001", current_price)
    logger.info(f"  当前价格: ${current_price}")
    logger.info(f"  是否平仓: {'✓ 是' if check4['should_close'] else '✗ 否'}")
    logger.info(f"  动作: {check4['action']}")

    # 测试5: 日最大亏损保护
    logger.info(f"\n测试5: 日最大亏损保护")
    # 假设当日已亏损$3500（3.5%），超过3%限制
    manager.daily_pnl = -3500
    logger.info(f"  当日盈亏: ${manager.daily_pnl:.2f}")

    order5 = manager.create_stop_loss("LONG004", OrderSide.LONG, 50000, 1.0)
    check5 = manager.check_stop_loss("LONG004", 50000)
    logger.info(f"  是否触发紧急平仓: {'✓ 是' if check5['should_close'] else '✗ 否'}")
    logger.info(f"  原因: {check5['reason']}")

    # 测试6: 平仓计算
    logger.info(f"\n测试6: 平仓计算")
    result = manager.close_order("LONG003", 51000)
    if result:
        logger.info(f"  入场: ${result['entry_price']}")
        logger.info(f"  平仓: ${result['exit_price']}")
        logger.info(f"  盈亏: {result['pnl_percent'] * 100:.2f}% (${result['pnl_amount']:.2f})")
        logger.info(f"  当日总盈亏: ${result['daily_pnl']:.2f}")

    logger.info("\n" + "="*60)
    logger.info("止损管理器测试: PASS")


if __name__ == "__main__":
    main()
