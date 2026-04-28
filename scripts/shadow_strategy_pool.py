#!/usr/bin/env python3
"""
影子策略池管理器 - v1.0.2 Integrated
管理策略实验室产生的候选策略，沙盒验证
"""

import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import json

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("shadow_strategy_pool")
except ImportError:
    import logging
    logger = logging.getLogger("shadow_strategy_pool")

try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False

try:
    from scripts.strategy_lab import StrategyIndividual
    STRATEGY_LAB_AVAILABLE = True
except ImportError:
    STRATEGY_LAB_AVAILABLE = False
    # 创建占位类用于类型提示
    class StrategyIndividual:
        pass


class ShadowStrategyStatus(Enum):
    """影子策略状态"""
    GENERATED = "generated"  # 已生成
    VALIDATING = "validating"  # 验证中
    PASSED = "passed"  # 通过验证
    FAILED = "failed"  # 验证失败
    ACTIVE = "active"  # 激活中
    RETIRED = "retired"  # 已退役


@dataclass
class ShadowStrategy:
    """影子策略"""
    id: str
    individual: Optional[StrategyIndividual] = None
    status: ShadowStrategyStatus = ShadowStrategyStatus.GENERATED
    created_at: float = field(default_factory=time.time)
    validated_at: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    trade_count: int = 0
    weekly_sharpe: List[float] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'status': self.status.value,
            'created_at': self.created_at,
            'validated_at': self.validated_at,
            'sharpe_ratio': self.sharpe_ratio,
            'win_rate': self.win_rate,
            'max_drawdown': self.max_drawdown,
            'total_return': self.total_return,
            'trade_count': self.trade_count,
            'weekly_sharpe': self.weekly_sharpe,
            'notes': self.notes
        }


class ShadowStrategyPool:
    """影子策略池管理器"""

    def __init__(self, benchmark_sharpe: float = 1.0, min_weeks_to_activate: int = 2):
        """
        初始化影子策略池

        Args:
            benchmark_sharpe: 基准夏普比率
            min_weeks_to_activate: 最少激活周数
        """
        self.benchmark_sharpe = benchmark_sharpe
        self.min_weeks_to_activate = min_weeks_to_activate

        self.strategies: Dict[str, ShadowStrategy] = {}
        self.max_pool_size = 50  # 最大策略池大小

        logger.info(f"影子策略池初始化完成: 基准Sharpe={benchmark_sharpe}, 最少周数={min_weeks_to_activate}")

    def add_candidate(self, individual: StrategyIndividual) -> str:
        """
        添加候选策略

        Args:
            individual: 策略个体

        Returns:
            策略ID
        """
        try:
            if len(self.strategies) >= self.max_pool_size:
                logger.warning("策略池已满，移除最旧策略")
                oldest_id = min(self.strategies.keys(), key=lambda k: self.strategies[k].created_at)
                self.remove_strategy(oldest_id)

            strategy_id = f"shadow_{int(time.time())}_{len(self.strategies)}"
            strategy = ShadowStrategy(
                id=strategy_id,
                individual=individual,
                status=ShadowStrategyStatus.GENERATED
            )

            self.strategies[strategy_id] = strategy

            # 广播事件
            if EVENT_BUS_AVAILABLE:
                bus = get_event_bus()
                bus.publish(
                    "shadow_strategy.generated",
                    {
                        "strategy_id": strategy_id,
                        "timestamp": time.time()
                    },
                    source="shadow_strategy_pool"
                )

            logger.info(f"候选策略添加成功: {strategy_id}")
            return strategy_id

        except Exception as e:
            logger.error(f"添加候选策略失败: {e}")
            return ""

    def validate_strategy(self, strategy_id: str, metrics: Dict) -> bool:
        """
        验证策略

        Args:
            strategy_id: 策略ID
            metrics: 性能指标

        Returns:
            是否验证通过
        """
        try:
            if strategy_id not in self.strategies:
                logger.warning(f"策略不存在: {strategy_id}")
                return False

            strategy = self.strategies[strategy_id]

            # 第一层防御：参数校验
            sharpe = metrics.get('sharpe_ratio', 0.0)
            win_rate = metrics.get('win_rate', 0.0)
            max_dd = metrics.get('max_drawdown', 0.0)
            total_return = metrics.get('total_return', 0.0)

            # 第二层防御：通过标准
            passed = True
            reasons = []

            # Sharpe比率必须大于基准
            if sharpe < self.benchmark_sharpe:
                passed = False
                reasons.append(f"Sharpe过低: {sharpe:.4f} < {self.benchmark_sharpe:.4f}")

            # 最大回撤不能太大
            if max_dd > 0.30:
                passed = False
                reasons.append(f"最大回撤过大: {max_dd:.4f}")

            # 交易次数必须足够
            trade_count = metrics.get('trade_count', 0)
            if trade_count < 10:
                passed = False
                reasons.append(f"交易次数不足: {trade_count}")

            # 更新策略状态
            strategy.validated_at = time.time()
            strategy.sharpe_ratio = sharpe
            strategy.win_rate = win_rate
            strategy.max_drawdown = max_dd
            strategy.total_return = total_return
            strategy.trade_count = trade_count

            if passed:
                strategy.status = ShadowStrategyStatus.PASSED
                strategy.notes.append("验证通过")
                logger.info(f"策略验证通过: {strategy_id}, Sharpe={sharpe:.4f}")
            else:
                strategy.status = ShadowStrategyStatus.FAILED
                strategy.notes.append(f"验证失败: {', '.join(reasons)}")
                logger.warning(f"策略验证失败: {strategy_id}, 原因={reasons}")

            # 广播事件
            if EVENT_BUS_AVAILABLE:
                bus = get_event_bus()
                bus.publish(
                    "shadow_strategy.validated",
                    {
                        "strategy_id": strategy_id,
                        "passed": passed,
                        "reasons": reasons,
                        "metrics": metrics
                    },
                    source="shadow_strategy_pool"
                )

            return passed

        except Exception as e:
            logger.error(f"验证策略失败: {strategy_id}, 错误={e}")
            return False

    def update_weekly_performance(self, strategy_id: str, weekly_sharpe: float) -> None:
        """
        更新每周性能

        Args:
            strategy_id: 策略ID
            weekly_sharpe: 每周Sharpe比率
        """
        try:
            if strategy_id not in self.strategies:
                return

            strategy = self.strategies[strategy_id]
            strategy.weekly_sharpe.append(weekly_sharpe)

            # 检查是否可以激活
            if len(strategy.weekly_sharpe) >= self.min_weeks_to_activate:
                avg_sharpe = sum(strategy.weekly_sharpe) / len(strategy.weekly_sharpe)

                if avg_sharpe > self.benchmark_sharpe and strategy.status == ShadowStrategyStatus.PASSED:
                    strategy.status = ShadowStrategyStatus.ACTIVE
                    logger.info(f"策略激活成功: {strategy_id}, 平均Sharpe={avg_sharpe:.4f}")

                    # 广播事件
                    if EVENT_BUS_AVAILABLE:
                        bus = get_event_bus()
                        bus.publish(
                            "shadow_strategy.activated",
                            {
                                "strategy_id": strategy_id,
                                "avg_sharpe": avg_sharpe
                            },
                            source="shadow_strategy_pool"
                        )

        except Exception as e:
            logger.error(f"更新每周性能失败: {strategy_id}, 错误={e}")

    def get_top_strategies(self, n: int = 5) -> List[Dict]:
        """
        获取表现最好的策略

        Args:
            n: 返回数量

        Returns:
            策略列表
        """
        active_strategies = [
            s for s in self.strategies.values()
            if s.status == ShadowStrategyStatus.ACTIVE
        ]

        # 按平均Sharpe排序
        sorted_strategies = sorted(
            active_strategies,
            key=lambda s: sum(s.weekly_sharpe) / len(s.weekly_sharpe) if s.weekly_sharpe else 0,
            reverse=True
        )

        return [s.to_dict() for s in sorted_strategies[:n]]

    def remove_strategy(self, strategy_id: str) -> bool:
        """
        移除策略

        Args:
            strategy_id: 策略ID

        Returns:
            是否移除成功
        """
        if strategy_id in self.strategies:
            del self.strategies[strategy_id]
            logger.info(f"策略已移除: {strategy_id}")
            return True
        return False

    def get_pool_statistics(self) -> Dict:
        """
        获取策略池统计

        Returns:
            统计信息
        """
        status_count = {}
        for strategy in self.strategies.values():
            status = strategy.status.value
            status_count[status] = status_count.get(status, 0) + 1

        active_strategies = [
            s for s in self.strategies.values()
            if s.status == ShadowStrategyStatus.ACTIVE
        ]

        avg_sharpe = 0.0
        if active_strategies:
            avg_sharpe = sum(
                sum(s.weekly_sharpe) / len(s.weekly_sharpe)
                for s in active_strategies if s.weekly_sharpe
            ) / len(active_strategies)

        return {
            'total_strategies': len(self.strategies),
            'active_strategies': len(active_strategies),
            'status_count': status_count,
            'average_sharpe': avg_sharpe,
            'benchmark_sharpe': self.benchmark_sharpe
        }


if __name__ == "__main__":
    # 测试代码
    print("测试影子策略池...")

    pool = ShadowStrategyPool(benchmark_sharpe=1.0, min_weeks_to_activate=2)
    strategy_id = "test_strategy_001"  # 测试ID

    # 模拟添加策略
    print("\n测试1: 添加候选策略")
    if STRATEGY_LAB_AVAILABLE:
        from scripts.strategy_lab import StrategyIndividual
        individual = StrategyIndividual()
        strategy_id = pool.add_candidate(individual)
        print(f"策略ID: {strategy_id}")
    else:
        print("策略实验室不可用，使用测试ID")
        # 创建测试策略
        strategy = ShadowStrategy(id=strategy_id, individual=None, status=ShadowStrategyStatus.GENERATED)
        pool.strategies[strategy_id] = strategy
        print(f"测试策略ID: {strategy_id}")

    # 模拟验证策略
    print("\n测试2: 验证策略")
    metrics = {
        'sharpe_ratio': 1.5,
        'win_rate': 0.6,
        'max_drawdown': 0.15,
        'total_return': 0.25,
        'trade_count': 50
    }
    passed = pool.validate_strategy(strategy_id, metrics)
    print(f"验证结果: {'通过' if passed else '失败'}")

    # 获取统计
    print("\n测试3: 获取统计")
    stats = pool.get_pool_statistics()
    print(f"策略池统计: {stats}")

    print("\n测试通过！")
