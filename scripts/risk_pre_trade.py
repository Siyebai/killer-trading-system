#!/usr/bin/env python3
"""
开仓前风控规则
开仓前执行的风控检查，包括仓位限制、连续亏损、日亏损、频率限制等
"""

import time
from typing import Dict, Any, Tuple
from scripts.risk_base import RiskRule, RiskLevel

try:
    from enum import Enum
except ImportError:
    Enum = None


class MaxPositionSizeRule(RiskRule):
    """单笔最大仓位限制"""

    def __init__(self, max_position_pct: float = 0.10):
        """
        初始化

        Args:
            max_position_pct: 最大仓位百分比（默认10%）
        """
        super().__init__("max_position_size", level=RiskLevel.ERROR)
        self.max_pct = max_position_pct

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查单笔仓位是否超限

        Args:
            context: 包含 order_qty, price, equity 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        qty = context.get('order_qty', 0)
        price = context.get('price', 0)
        equity = context.get('equity', 1)

        if equity <= 0:
            return False, "权益为0或负数"

        position_value = qty * price
        position_pct = position_value / equity

        if position_pct > self.max_pct:
            self.record_violation(f"单笔仓位{position_pct:.2%} > {self.max_pct:.2%}")
            return False, f"单笔仓位{position_pct:.2%}超过最大限制{self.max_pct:.2%}"

        return True, ""


class ConsecutiveLossLimitRule(RiskRule):
    """连续亏损次数限制"""

    def __init__(self, max_consecutive_losses: int = 5, cooldown_seconds: int = 300):
        """
        初始化

        Args:
            max_consecutive_losses: 最大连续亏损次数
            cooldown_seconds: 触发后的冷却时间（秒）
        """
        super().__init__("consecutive_loss_limit", level=RiskLevel.ERROR)
        self.max_losses = max_consecutive_losses
        self.cooldown = cooldown_seconds
        self._loss_count = 0
        self._last_win_time = 0

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查连续亏损次数

        Args:
            context: 包含 consecutive_losses 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        consecutive_losses = context.get('consecutive_losses', self._loss_count)

        if consecutive_losses >= self.max_losses:
            if self.is_in_cooldown(self.cooldown):
                return False, f"连续亏损{consecutive_losses}次，冷却中（还需{self.cooldown - (time.time() - self.last_violation_time):.0f}秒）"
            else:
                # 冷却结束，重置计数
                self._loss_count = 0
                self.last_violation_time = 0

        return True, ""

    def update_trade_result(self, is_win: bool):
        """更新交易结果（由外部调用）"""
        if is_win:
            self._loss_count = 0
            self._last_win_time = time.time()
        else:
            self._loss_count += 1

    def reset(self):
        """重置状态"""
        super().reset()
        self._loss_count = 0
        self._last_win_time = 0


class DailyLossLimitRule(RiskRule):
    """单日最大亏损限制"""

    def __init__(self, max_daily_loss_pct: float = 0.025):
        """
        初始化

        Args:
            max_daily_loss_pct: 单日最大亏损百分比（默认2.5%）
        """
        super().__init__("daily_loss_limit", level=RiskLevel.CRITICAL)
        self.max_loss_pct = max_daily_loss_pct
        self._daily_pnl = 0.0
        self._initial_equity = 0.0
        self._last_reset_time = time.time()

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查单日亏损

        Args:
            context: 包含 daily_pnl, initial_equity 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        # 检查是否需要重置（新的一天）
        self._check_reset()

        daily_pnl = context.get('daily_pnl', self._daily_pnl)
        initial_equity = context.get('initial_equity', self._initial_equity)

        if initial_equity <= 0:
            return True, ""

        loss_pct = -daily_pnl / initial_equity if daily_pnl < 0 else 0

        if loss_pct >= self.max_loss_pct:
            self.record_violation(f"当日亏损{loss_pct:.2%}超过最大限制{self.max_loss_pct:.2%}")
            return False, f"当日亏损{loss_pct:.2%}超过最大限制{self.max_loss_pct:.2%}，停止交易"

        return True, ""

    def update_pnl(self, pnl: float, current_equity: float):
        """更新盈亏"""
        self._check_reset()

        if self._initial_equity == 0:
            self._initial_equity = current_equity

        self._daily_pnl += pnl

    def _check_reset(self):
        """检查是否需要重置（新的一天）"""
        now = time.time()
        # 简化：距离上次重置超过24小时
        if now - self._last_reset_time > 86400:
            self._daily_pnl = 0.0
            self._initial_equity = 0.0
            self._last_reset_time = now

    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        stats = super().get_stats()
        stats['daily_pnl'] = self._daily_pnl
        stats['initial_equity'] = self._initial_equity
        return stats


class OrderFrequencyLimitRule(RiskRule):
    """订单频率限制"""

    def __init__(self, max_orders_per_minute: int = 30):
        """
        初始化

        Args:
            max_orders_per_minute: 每分钟最大订单数
        """
        super().__init__("order_frequency_limit", level=RiskLevel.ERROR)
        self.max_orders = max_orders_per_minute
        self._order_times: list = []

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查订单频率

        Args:
            context: 包含 timestamp 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        now = time.time()

        # 清理超过1分钟的记录
        self._order_times = [t for t in self._order_times if now - t < 60]

        if len(self._order_times) >= self.max_orders:
            self.record_violation(f"订单频率{len(self._order_times)}次/分钟超过限制{self.max_orders}次/分钟")
            return False, f"订单频率{len(self._order_times)}次/分钟超过限制{self.max_orders}次/分钟，请稍后再试"

        # 记录此次订单
        self._order_times.append(now)

        return True, ""

    def reset(self):
        """重置状态"""
        super().reset()
        self._order_times = []


class MaxDrawdownLimitRule(RiskRule):
    """最大回撤限制"""

    def __init__(self, max_drawdown_pct: float = 0.10):
        """
        初始化

        Args:
            max_drawdown_pct: 最大回撤百分比（默认10%）
        """
        super().__init__("max_drawdown_limit", level=RiskLevel.CRITICAL)
        self.max_drawdown_pct = max_drawdown_pct
        self._peak_equity = 0.0

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查当前回撤

        Args:
            context: 包含 current_equity, peak_equity 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        current_equity = context.get('current_equity', 0)
        peak_equity = context.get('peak_equity', self._peak_equity)

        if current_equity > peak_equity:
            self._peak_equity = current_equity
            return True, ""

        if peak_equity <= 0:
            return True, ""

        current_drawdown = (peak_equity - current_equity) / peak_equity

        if current_drawdown >= self.max_drawdown_pct:
            self.record_violation(f"当前回撤{current_drawdown:.2%}超过最大限制{self.max_drawdown_pct:.2%}")
            return False, f"当前回撤{current_drawdown:.2%}超过最大限制{self.max_drawdown_pct:.2%}，触发硬熔断"

        return True, ""

    def update_equity(self, equity: float):
        """更新权益"""
        if equity > self._peak_equity:
            self._peak_equity = equity


class CorrelationLimitRule(RiskRule):
    """相关性限制（避免同时开仓高度相关的品种）"""

    def __init__(self, max_correlated_positions: int = 3):
        """
        初始化

        Args:
            max_correlated_positions: 最大相关持仓数
        """
        super().__init__("correlation_limit", level=RiskLevel.WARNING)
        self.max_positions = max_correlated_positions
        self._correlation_matrix = {
            'BTCUSDT': ['ETHUSDT', 'BNBUSDT'],
            'ETHUSDT': ['BTCUSDT', 'BNBUSDT'],
            'BNBUSDT': ['BTCUSDT', 'ETHUSDT']
        }

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查相关性

        Args:
            context: 包含 symbol, current_positions 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        symbol = context.get('symbol', '')
        current_positions = context.get('current_positions', {})

        # 获取相关品种
        correlated_symbols = self._correlation_matrix.get(symbol, [])

        # 统计当前相关持仓数
        correlated_count = sum(
            1 for pos_symbol in current_positions.keys()
            if pos_symbol in correlated_symbols
        )

        if correlated_count >= self.max_positions:
            self.record_violation(f"相关持仓{correlated_count}个超过限制{self.max_positions}个")
            return False, f"相关品种{correlated_symbols}已持仓{correlated_count}个，超过限制{self.max_positions}个"

        return True, ""


class LiquidityCheckRule(RiskRule):
    """流动性检查（确保市场深度足够）"""

    def __init__(self, min_orderbook_depth: float = 10000.0):
        """
        初始化

        Args:
            min_orderbook_depth: 最小订单簿深度（USDT）
        """
        super().__init__("liquidity_check", level=RiskLevel.ERROR)
        self.min_depth = min_orderbook_depth

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查市场流动性

        Args:
            context: 包含 bid_size, ask_size 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        bid_size = context.get('bid_size', 0)
        ask_size = context.get('ask_size', 0)

        min_depth = min(bid_size, ask_size)

        if min_depth < self.min_depth:
            self.record_violation(f"市场深度{min_depth:.2f}低于最低要求{self.min_depth:.2f}")
            return False, f"市场深度{min_depth:.2f} USDT低于最低要求{self.min_depth:.2f} USDT，流动性不足"

        return True, ""
