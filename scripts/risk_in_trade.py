#!/usr/bin/env python3
"""
持仓中风控规则
持仓中执行的风控检查，包括追踪止损、时间止损、波动率熔断等
"""

import time
import numpy as np
from typing import Dict, Any, Tuple

# 风控基类定义（避免循环导入）
class RiskLevel:
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class RiskRule:
    def __init__(self, name, enabled=True, level=RiskLevel.ERROR):
        self.name = name
        self.enabled = enabled
        self.level = level
        self.total_checks = 0


class TrailingStopRule(RiskRule):
    """追踪止损（动态移动止盈）"""

    def __init__(self, activation_pct: float = 0.005, trail_pct: float = 0.003):
        """
        初始化

        Args:
            activation_pct: 激活追踪止损的盈利百分比（默认0.5%）
            trail_pct: 追踪回撤百分比（默认0.3%）
        """
        super().__init__("trailing_stop", level=RiskLevel.ERROR)
        self.activation_pct = activation_pct
        self.trail_pct = trail_pct

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查追踪止损

        Args:
            context: 包含 entry_price, current_price, side, trailing_stop_price 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        entry_price = context.get('entry_price', 0)
        current_price = context.get('current_price', 0)
        side = context.get('side', 'BUY')
        trailing_stop_price = context.get('trailing_stop_price', None)

        if entry_price == 0 or current_price == 0:
            return True, ""

        # 计算当前盈利百分比
        if side == 'BUY':
            profit_pct = (current_price - entry_price) / entry_price
        else:
            profit_pct = (entry_price - current_price) / entry_price

        # 检查是否达到激活阈值
        if profit_pct > self.activation_pct:
            # 计算新的追踪止损价
            if side == 'BUY':
                new_stop = current_price * (1 - self.trail_pct)
                should_stop = trailing_stop_price is not None and current_price <= trailing_stop_price
            else:
                new_stop = current_price * (1 + self.trail_pct)
                should_stop = trailing_stop_price is not None and current_price >= trailing_stop_price

            # 更新追踪止损价
            if trailing_stop_price is None or (side == 'BUY' and new_stop > trailing_stop_price) or (side == 'SHORT' and new_stop < trailing_stop_price):
                context['trailing_stop_price'] = new_stop

            # 检查是否触发止损
            if should_stop:
                self.record_violation(f"追踪止损触发，当前价{current_price:.2f}，止损价{trailing_stop_price:.2f}")
                return False, f"追踪止损触发，盈利{profit_pct:.2%}后回撤超过{self.trail_pct:.2%}"

        return True, ""


class TimeStopRule(RiskRule):
    """时间止损（持仓超时未盈利）"""

    def __init__(self, max_holding_seconds: int = 7200, min_profit_pct: float = 0.001):
        """
        初始化

        Args:
            max_holding_seconds: 最大持仓时间（秒，默认2小时）
            min_profit_pct: 最小盈利百分比（默认0.1%）
        """
        super().__init__("time_stop", level=RiskLevel.WARNING)
        self.max_seconds = max_holding_seconds
        self.min_profit_pct = min_profit_pct

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查时间止损

        Args:
            context: 包含 entry_time, entry_price, current_price 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        entry_time = context.get('entry_time', 0)
        entry_price = context.get('entry_price', 0)
        current_price = context.get('current_price', 0)

        if entry_time == 0 or entry_price == 0:
            return True, ""

        now = time.time()
        holding_time = now - entry_time

        # 检查是否超时
        if holding_time > self.max_seconds:
            # 计算当前盈亏
            if current_price >= entry_price:
                unrealized_pnl_pct = (current_price - entry_price) / entry_price
            else:
                unrealized_pnl_pct = (entry_price - current_price) / entry_price

            # 检查是否达到最小盈利
            if unrealized_pnl_pct < self.min_profit_pct:
                self.record_violation(f"持仓超时{holding_time/3600:.1f}小时，盈利仅{unrealized_pnl_pct:.2%}")
                return False, f"持仓{holding_time/3600:.1f}小时未盈利（要求≥{self.min_profit_pct:.2%}），建议平仓"

        return True, ""


class VolatilityBreakerRule(RiskRule):
    """波动率熔断（价格剧烈波动时暂停交易）"""

    def __init__(self, max_volatility_threshold: float = 0.02, window_size: int = 5):
        """
        初始化

        Args:
            max_volatility_threshold: 最大波动率阈值（默认2%）
            window_size: 波动率计算窗口（默认5根K线）
        """
        super().__init__("volatility_breaker", level=RiskLevel.ERROR)
        self.max_threshold = max_volatility_threshold
        self.window_size = window_size
        self._price_history: list = []

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查波动率熔断

        Args:
            context: 包含 current_price 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        current_price = context.get('current_price', 0)

        if current_price == 0:
            return True, ""

        # 添加到历史
        self._price_history.append(current_price)

        # 保持窗口大小
        if len(self._price_history) > self.window_size:
            self._price_history.pop(0)

        # 计算波动率
        if len(self._price_history) >= self.window_size:
            prices = np.array(self._price_history)
            returns = np.diff(prices) / prices[:-1]
            volatility = np.std(returns)

            if volatility > self.max_threshold:
                self.record_violation(f"波动率{volatility:.2%}超过阈值{self.max_threshold:.2%}")
                return False, f"市场波动率{volatility:.2%}过高，暂停交易"

        return True, ""


class ExtremePriceMoveRule(RiskRule):
    """极端价格变动检测"""

    def __init__(self, max_single_move_pct: float = 0.01):
        """
        初始化

        Args:
            max_single_move_pct: 单次最大变动百分比（默认1%）
        """
        super().__init__("extreme_price_move", level=RiskLevel.WARNING)
        self.max_move_pct = max_single_move_pct
        self._last_price = 0.0

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查极端价格变动

        Args:
            context: 包含 current_price 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        current_price = context.get('current_price', 0)

        if current_price == 0 or self._last_price == 0:
            self._last_price = current_price
            return True, ""

        # 计算变动百分比
        move_pct = abs(current_price - self._last_price) / self._last_price

        # 更新最后价格
        self._last_price = current_price

        if move_pct > self.max_move_pct:
            self.record_violation(f"价格变动{move_pct:.2%}超过阈值{self.max_move_pct:.2%}")
            return False, f"价格剧烈变动{move_pct:.2%}，市场不稳定"

        return True, ""


class GapRiskRule(RiskRule):
    """跳空风险检测（价格跳空）"""

    def __init__(self, max_gap_pct: float = 0.015):
        """
        初始化

        Args:
            max_gap_pct: 最大跳空百分比（默认1.5%）
        """
        super().__init__("gap_risk", level=RiskLevel.WARNING)
        self.max_gap_pct = max_gap_pct
        self._last_close_price = 0.0

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查跳空风险

        Args:
            context: 包含 current_price, previous_close_price 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        current_price = context.get('current_price', 0)
        previous_close = context.get('previous_close_price', self._last_close_price)

        if current_price == 0 or previous_close == 0:
            self._last_close_price = current_price
            return True, ""

        # 计算跳空百分比
        gap_pct = abs(current_price - previous_close) / previous_close

        # 更新最后收盘价
        self._last_close_price = current_price

        if gap_pct > self.max_gap_pct:
            self.record_violation(f"价格跳空{gap_pct:.2%}超过阈值{self.max_gap_pct:.2%}")
            return False, f"市场跳空{gap_pct:.2%}，谨慎交易"

        return True, ""


class AdverseSelectionRule(RiskRule):
    """逆向选择风险（成交在不利位置）"""

    def __init__(self, max_adverse_slippage: float = 0.002):
        """
        初始化

        Args:
            max_adverse_slippage: 最大不利滑点（默认0.2%）
        """
        super().__init__("adverse_selection", level=RiskLevel.WARNING)
        self.max_slippage = max_adverse_slippage

    async def check(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        检查逆向选择风险

        Args:
            context: 包含 entry_price, expected_price, side 等

        Returns:
            (是否通过, 原因)
        """
        self.total_checks += 1

        entry_price = context.get('entry_price', 0)
        expected_price = context.get('expected_price', entry_price)
        side = context.get('side', 'BUY')

        if entry_price == 0 or expected_price == 0:
            return True, ""

        # 计算不利滑点
        if side == 'BUY':
            slippage_pct = (entry_price - expected_price) / expected_price
        else:
            slippage_pct = (expected_price - entry_price) / expected_price

        # 只考虑不利滑点（正数）
        adverse_slippage = max(0, slippage)

        if adverse_slippage > self.max_slippage:
            self.record_violation(f"不利滑点{adverse_slippage:.2%}超过阈值{self.max_slippage:.2%}")
            return False, f"成交滑点{adverse_slippage:.2%}过大，可能存在逆向选择"

        return True, ""
