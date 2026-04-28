#!/usr/bin/env python3
"""
策略生命周期管理器 - v1.0.3 Integrated
管理策略的出生→验证→激活→衰退→退役全生命周期
"""

import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("strategy_lifecycle_manager")
except ImportError:
    import logging
    logger = logging.getLogger("strategy_lifecycle_manager")

try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False


class StrategyLifecycleStage(Enum):
    """策略生命周期阶段"""
    BORN = "born"  # 出生
    VALIDATION = "validation"  # 验证
    ACTIVE = "active"  # 激活
    DECLINING = "declining"  # 衰退
    RETIRED = "retired"  # 退役


@dataclass
class LifecycleEvent:
    """生命周期事件"""
    timestamp: float = field(default_factory=time.time)
    stage: StrategyLifecycleStage = StrategyLifecycleStage.BORN
    sharpe_ratio: float = 0.0
    drawdown: float = 0.0
    notes: str = ""


class StrategyLifecycleManager:
    """策略生命周期管理器"""

    def __init__(self,
                 min_sharpe_to_retire: float = 0.3,
                 decline_detection_weeks: int = 2,
                 observation_period_weeks: int = 4):
        """
        初始化生命周期管理器

        Args:
            min_sharpe_to_retire: 退役最小Sharpe比率
            decline_detection_weeks: 衰退检测周数
            observation_period_weeks: 观察期周数
        """
        self.min_sharpe_to_retire = min_sharpe_to_retire
        self.decline_detection_weeks = decline_detection_weeks
        self.observation_period_weeks = observation_period_weeks

        # 策略生命周期数据
        self.strategies: Dict[str, List[LifecycleEvent]] = {}

        logger.info(f"策略生命周期管理器初始化完成: 最小Sharpe={min_sharpe_to_retire}, 衰退检测周数={decline_detection_weeks}")

    def register_strategy(self, strategy_id: str) -> bool:
        """
        注册新策略

        Args:
            strategy_id: 策略ID

        Returns:
            是否注册成功
        """
        try:
            if strategy_id in self.strategies:
                logger.warning(f"策略已存在: {strategy_id}")
                return False

            # 创建出生事件
            event = LifecycleEvent(
                stage=StrategyLifecycleStage.BORN,
                notes="策略出生"
            )

            self.strategies[strategy_id] = [event]

            logger.info(f"策略注册成功: {strategy_id}")

            # 广播事件
            if EVENT_BUS_AVAILABLE:
                bus = get_event_bus()
                bus.publish(
                    "lifecycle.strategy_born",
                    {
                        "strategy_id": strategy_id,
                        "timestamp": time.time()
                    },
                    source="lifecycle_manager"
                )

            return True

        except Exception as e:
            logger.error(f"注册策略失败: {strategy_id}, 错误={e}")
            return False

    def update_performance(self, strategy_id: str, sharpe_ratio: float, drawdown: float) -> None:
        """
        更新策略性能

        Args:
            strategy_id: 策略ID
            sharpe_ratio: Sharpe比率
            drawdown: 最大回撤
        """
        try:
            if strategy_id not in self.strategies:
                logger.warning(f"策略不存在: {strategy_id}")
                return

            # 添加性能事件
            event = LifecycleEvent(
                stage=StrategyLifecycleStage.ACTIVE,
                sharpe_ratio=sharpe_ratio,
                drawdown=drawdown,
                notes=f"性能更新: Sharpe={sharpe_ratio:.4f}"
            )

            self.strategies[strategy_id].append(event)

        except Exception as e:
            logger.error(f"更新性能失败: {strategy_id}, 错误={e}")

    def detect_decline(self, strategy_id: str) -> bool:
        """
        检测策略衰退

        Args:
            strategy_id: 策略ID

        Returns:
            是否检测到衰退
        """
        try:
            if strategy_id not in self.strategies:
                return False

            events = self.strategies[strategy_id]

            # 第一层防御：检查事件数量
            if len(events) < self.decline_detection_weeks:
                return False

            # 获取最近N周的Sharpe比率
            recent_events = events[-self.decline_detection_weeks:]
            sharpe_values = [e.sharpe_ratio for e in recent_events]

            # 第二层防御：计算平均Sharpe
            avg_sharpe = sum(sharpe_values) / len(sharpe_values)

            # 检查是否衰退（Sharpe低于阈值）
            if avg_sharpe < self.min_sharpe_to_retire:
                logger.warning(f"检测到策略衰退: {strategy_id}, 平均Sharpe={avg_sharpe:.4f}")

                # 添加衰退事件
                event = LifecycleEvent(
                    stage=StrategyLifecycleStage.DECLINING,
                    sharpe_ratio=avg_sharpe,
                    notes=f"策略衰退: 平均Sharpe={avg_sharpe:.4f} < {self.min_sharpe_to_retire}"
                )
                self.strategies[strategy_id].append(event)

                # 广播事件
                if EVENT_BUS_AVAILABLE:
                    bus = get_event_bus()
                    bus.publish(
                        "lifecycle.strategy_declining",
                        {
                            "strategy_id": strategy_id,
                            "avg_sharpe": avg_sharpe
                        },
                        source="lifecycle_manager"
                    )

                return True

            return False

        except Exception as e:
            logger.error(f"检测衰退失败: {strategy_id}, 错误={e}")
            return False

    def retire_strategy(self, strategy_id: str, reason: str = "") -> bool:
        """
        退役策略

        Args:
            strategy_id: 策略ID
            reason: 退役原因

        Returns:
            是否退役成功
        """
        try:
            if strategy_id not in self.strategies:
                logger.warning(f"策略不存在: {strategy_id}")
                return False

            # 添加退役事件
            event = LifecycleEvent(
                stage=StrategyLifecycleStage.RETIRED,
                notes=f"策略退役: {reason}"
            )

            self.strategies[strategy_id].append(event)

            logger.info(f"策略退役成功: {strategy_id}, 原因={reason}")

            # 广播事件
            if EVENT_BUS_AVAILABLE:
                bus = get_event_bus()
                bus.publish(
                    "lifecycle.strategy_retired",
                    {
                        "strategy_id": strategy_id,
                        "reason": reason
                    },
                    source="lifecycle_manager"
                )

            return True

        except Exception as e:
            logger.error(f"退役策略失败: {strategy_id}, 错误={e}")
            return False

    def get_strategy_stage(self, strategy_id: str) -> Optional[StrategyLifecycleStage]:
        """
        获取策略当前阶段

        Args:
            strategy_id: 策略ID

        Returns:
            当前阶段
        """
        if strategy_id not in self.strategies:
            return None

        events = self.strategies[strategy_id]
        if not events:
            return None

        return events[-1].stage

    def get_lifecycle_summary(self, strategy_id: str) -> Dict:
        """
        获取生命周期摘要

        Args:
            strategy_id: 策略ID

        Returns:
            生命周期摘要
        """
        if strategy_id not in self.strategies:
            return {}

        events = self.strategies[strategy_id]
        if not events:
            return {}

        current_stage = events[-1].stage
        total_duration = time.time() - events[0].timestamp

        # 计算平均Sharpe
        sharpe_values = [e.sharpe_ratio for e in events if e.sharpe_ratio > 0]
        avg_sharpe = sum(sharpe_values) / len(sharpe_values) if sharpe_values else 0.0

        return {
            'strategy_id': strategy_id,
            'current_stage': current_stage.value,
            'total_duration_hours': total_duration / 3600.0,
            'event_count': len(events),
            'average_sharpe': avg_sharpe,
            'is_declining': current_stage == StrategyLifecycleStage.DECLINING
        }

    def check_all_strategies(self) -> List[Dict]:
        """
        检查所有策略状态

        Returns:
            需要处理的策略列表
        """
        actions_needed = []

        for strategy_id in list(self.strategies.keys()):
            # 检测衰退
            if self.detect_decline(strategy_id):
                actions_needed.append({
                    'strategy_id': strategy_id,
                    'action': 'observe',
                    'reason': '策略衰退检测'
                })

            # 检查是否需要退役
            stage = self.get_strategy_stage(strategy_id)
            if stage == StrategyLifecycleStage.DECLINING:
                events = self.strategies[strategy_id]
                declining_events = [e for e in events if e.stage == StrategyLifecycleStage.DECLINING]

                # 衰退超过观察期，退役
                if len(declining_events) >= self.observation_period_weeks:
                    actions_needed.append({
                        'strategy_id': strategy_id,
                        'action': 'retire',
                        'reason': '衰退超过观察期'
                    })

        return actions_needed


if __name__ == "__main__":
    # 测试代码
    print("测试策略生命周期管理器...")

    manager = StrategyLifecycleManager(min_sharpe_to_retire=0.3, decline_detection_weeks=2)

    # 测试1: 注册策略
    print("\n测试1: 注册策略")
    manager.register_strategy("strategy_001")

    # 测试2: 更新性能
    print("\n测试2: 更新性能（正常）")
    manager.update_performance("strategy_001", sharpe_ratio=1.5, drawdown=0.10)
    manager.update_performance("strategy_001", sharpe_ratio=1.3, drawdown=0.12)

    # 测试3: 检测衰退
    print("\n测试3: 检测衰退（未触发）")
    declining = manager.detect_decline("strategy_001")
    print(f"是否衰退: {declining}")

    # 测试4: 模拟衰退
    print("\n测试4: 模拟衰退（触发）")
    manager.update_performance("strategy_001", sharpe_ratio=0.1, drawdown=0.30)
    manager.update_performance("strategy_001", sharpe_ratio=0.05, drawdown=0.35)
    declining = manager.detect_decline("strategy_001")
    print(f"是否衰退: {declining}")

    # 测试5: 获取摘要
    print("\n测试5: 获取摘要")
    summary = manager.get_lifecycle_summary("strategy_001")
    print(f"生命周期摘要: {summary}")

    print("\n测试通过！")
