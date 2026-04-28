#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("risk_circuit_breaker")
except ImportError:
    import logging
    logger = logging.getLogger("risk_circuit_breaker")
"""
分级熔断器
实现软熔断（暂停开新仓）和硬熔断（平仓所有持仓+断开连接）
"""

import time
from enum import Enum
from typing import Dict, Any, Optional


class BreakerLevel(Enum):
    """熔断等级"""
    NORMAL = 0    # 正常运行
    SOFT = 1      # 软熔断：暂停开新仓
    HARD = 2      # 硬熔断：平仓所有持仓+断开连接


class CircuitBreaker:
    """分级熔断器"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化熔断器

        Args:
            config: 配置字典
                - soft_breaker_threshold: 软熔断回撤阈值（默认5%）
                - hard_breaker_threshold: 硬熔断回撤阈值（默认10%）
                - soft_cooldown_seconds: 软熔断冷却时间（默认600秒）
                - hard_cooldown_seconds: 硬熔断冷却时间（默认3600秒）
                - max_consecutive_violations: 最大连续违规次数（默认3次）
        """
        self.soft_threshold = config.get('soft_breaker_threshold', 0.05)
        self.hard_threshold = config.get('hard_breaker_threshold', 0.10)
        self.soft_cooldown = config.get('soft_cooldown_seconds', 600)
        self.hard_cooldown = config.get('hard_cooldown_seconds', 3600)
        self.max_consecutive_violations = config.get('max_consecutive_violations', 3)

        self.level = BreakerLevel.NORMAL
        self._expire_time = 0
        self._consecutive_violations = 0
        self._last_violation_time = 0
        self._trigger_history: list = []

        self._peak_equity = 0.0
        self._initial_equity = 0.0

    def update(self, current_drawdown: float, current_equity: Optional[float] = None):
        """
        更新熔断器状态

        Args:
            current_drawdown: 当前回撤
            current_equity: 当前权益（可选）
        """
        now = time.time()

        # 更新最高权益
        if current_equity is not None:
            if current_equity > self._peak_equity:
                self._peak_equity = current_equity

        # 检查是否已过期
        if now >= self._expire_time:
            self.reset()
            return

        # 检查硬熔断
        if current_drawdown >= self.hard_threshold and self.level != BreakerLevel.HARD:
            self._trigger(BreakerLevel.HARD, f"回撤{current_drawdown:.2%}达到硬熔断阈值{self.hard_threshold:.2%}")

        # 检查软熔断
        elif current_drawdown >= self.soft_threshold and self.level == BreakerLevel.NORMAL:
            self._trigger(BreakerLevel.SOFT, f"回撤{current_drawdown:.2%}达到软熔断阈值{self.soft_threshold:.2%}")

    def trigger_soft(self, reason: str = ""):
        """
        手动触发软熔断

        Args:
            reason: 触发原因
        """
        self._trigger(BreakerLevel.SOFT, reason or "手动触发软熔断")

    def trigger_hard(self, reason: str = ""):
        """
        手动触发硬熔断

        Args:
            reason: 触发原因
        """
        self._trigger(BreakerLevel.HARD, reason or "手动触发硬熔断")

    def _trigger(self, level: BreakerLevel, reason: str):
        """
        内部触发熔断

        Args:
            level: 熔断等级
            reason: 触发原因
        """
        now = time.time()
        self.level = level

        # 设置过期时间
        if level == BreakerLevel.HARD:
            self._expire_time = now + self.hard_cooldown
        else:
            self._expire_time = now + self.soft_cooldown

        # 记录触发历史
        trigger_record = {
            'level': level.value,
            'reason': reason,
            'time': now,
            'expire_time': self._expire_time
        }
        self._trigger_history.append(trigger_record)

        # 限制历史记录数量
        if len(self._trigger_history) > 100:
            self._trigger_history.pop(0)

        # 更新连续违规次数
        if now - self._last_violation_time < 300:  # 5分钟内的违规算连续
            self._consecutive_violations += 1
        else:
            self._consecutive_violations = 1

        self._last_violation_time = now

        logger.info(f"[熔断器] {level.name}熔断触发: {reason}")
        logger.info(f"[熔断器] 冷却时间: {self._expire_time - now:.0f}秒")

    def reset(self):
        """重置熔断器"""
        self.level = BreakerLevel.NORMAL
        self._expire_time = 0
        self._consecutive_violations = 0
        self._last_violation_time = 0

    def is_allowed(self, action: str) -> bool:
        """
        检查操作是否允许

        Args:
            action: 操作类型（open_position/close_position/all）

        Returns:
            是否允许
        """
        now = time.time()

        # 检查是否已过期
        if now >= self._expire_time and self.level != BreakerLevel.NORMAL:
            logger.info(f"[熔断器] 冷却结束，恢复{self.level.name}熔断")
            self.reset()
            return True

        if self.level == BreakerLevel.HARD:
            # 硬熔断：禁止所有操作
            return False
        elif self.level == BreakerLevel.SOFT:
            # 软熔断：只允许平仓
            if action == "open_position":
                return False
            elif action == "close_position":
                return True
            else:
                return False

        return True

    def get_status(self) -> Dict[str, Any]:
        """获取熔断器状态"""
        now = time.time()
        remaining_time = max(0, self._expire_time - now) if self._expire_time > 0 else 0

        return {
            'level': self.level.value,
            'level_name': self.level.name,
            'remaining_seconds': remaining_time,
            'consecutive_violations': self._consecutive_violations,
            'peak_equity': self._peak_equity,
            'initial_equity': self._initial_equity,
            'trigger_count': len(self._trigger_history),
            'last_trigger': self._trigger_history[-1] if self._trigger_history else None
        }

    def get_trigger_history(self, limit: int = 10) -> list:
        """获取触发历史"""
        return self._trigger_history[-limit:]

    def should_auto_close_all(self) -> bool:
        """是否应该自动平仓所有持仓"""
        return self.level == BreakerLevel.HARD

    def should_disconnect(self) -> bool:
        """是否应该断开连接"""
        return self.level == BreakerLevel.HARD

    def __str__(self) -> str:
        status = self.get_status()
        return f"CircuitBreaker[{status['level_name']}] (remaining={status['remaining_seconds']:.0f}s)"
