#!/usr/bin/env python3
"""
元学习建议器 - v1.0.2 Integrated
影子模式并行运行，输出建议动作与LinUCB对比分析
"""

import time
import random
import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("meta_learner_advisor")
except ImportError:
    import logging
    logger = logging.getLogger("meta_learner_advisor")

try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False


class AdvisorMode(Enum):
    """建议器模式"""
    SHADOW = "shadow"  # 影子模式（仅建议，不执行）
    SEMI_AUTO = "semi_auto"  # 半自动模式（小变动自动，大变动需确认）
    AUTO = "auto"  # 自动模式


@dataclass
class Advice:
    """建议"""
    timestamp: float = field(default_factory=time.time)
    advice_type: str = ""
    strategy_id: str = ""
    suggested_value: float = 0.0
    current_value: float = 0.0
    change: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    executed: bool = False
    execution_result: str = ""


@dataclass
class PerformanceComparison:
    """性能对比"""
    meta_advisor_return: float = 0.0
    linucb_return: float = 0.0
    difference: float = 0.0
    significance: float = 0.0
    sample_size: int = 0


class MetaLearnerAdvisor:
    """元学习建议器"""

    def __init__(self,
                 mode: AdvisorMode = AdvisorMode.SHADOW,
                 auto_threshold: float = 0.05,
                 required_shadow_days: int = 14):
        """
        初始化建议器

        Args:
            mode: 运行模式
            auto_threshold: 自动执行阈值（变动小于此值可自动执行）
            required_shadow_days: 影子模式运行天数
        """
        self.mode = mode
        self.auto_threshold = auto_threshold
        self.required_shadow_days = required_shadow_days

        # 建议历史
        self.advices: List[Advice] = []

        # 性能对比数据
        self.performance_data: List[Dict] = []

        # 状态
        self.start_time = time.time()
        self.days_in_shadow = 0

        logger.info(f"元学习建议器初始化完成: 模式={mode.value}, 自动阈值={auto_threshold}, 影子天数={required_shadow_days}")

    def observe_state(self, state: Dict) -> None:
        """
        观察当前状态

        Args:
            state: 状态向量
        """
        try:
            # 在实际实现中，这里会将状态输入到PPO模型
            # 当前为简化版，使用规则生成建议
            pass

        except Exception as e:
            logger.error(f"观察状态失败: {e}")

    def generate_weight_adjustment(self,
                                   strategy_id: str,
                                   current_weight: float,
                                   strategy_performance: Dict) -> Optional[Advice]:
        """
        生成权重调整建议

        Args:
            strategy_id: 策略ID
            current_weight: 当前权重
            strategy_performance: 策略性能数据

        Returns:
            建议对象
        """
        try:
            # 第一层防御：数据验证
            if not 0 <= current_weight <= 1:
                logger.warning(f"当前权重不在[0,1]范围内: {current_weight}")
                return None

            # 基于策略性能生成建议（简化版规则）
            sharpe = strategy_performance.get('sharpe_ratio', 0.0)
            win_rate = strategy_performance.get('win_rate', 0.0)

            # 规则1: 高Sharpe、高胜率 → 增加权重
            if sharpe > 1.0 and win_rate > 0.55:
                suggested_weight = min(current_weight + 0.05, 0.5)
                reason = f"策略表现优秀 (Sharpe={sharpe:.2f}, 胜率={win_rate:.2%})"

            # 规则2: 低Sharpe、低胜率 → 降低权重
            elif sharpe < 0.5 or win_rate < 0.45:
                suggested_weight = max(current_weight - 0.05, 0.05)
                reason = f"策略表现不佳 (Sharpe={sharpe:.2f}, 胜率={win_rate:.2%})"

            # 规则3: 表现中等 → 保持不变
            else:
                suggested_weight = current_weight
                reason = "策略表现稳定，保持当前权重"

            # 变动量
            change = suggested_weight - current_weight

            # 置信度（基于性能数据的稳定性）
            confidence = min(sharpe / 2.0, 0.9)

            # 创建建议
            advice = Advice(
                advice_type="WEIGHT_ADJUSTMENT",
                strategy_id=strategy_id,
                suggested_value=suggested_weight,
                current_value=current_weight,
                change=change,
                confidence=confidence,
                reason=reason
            )

            # 影子模式下不执行
            if self.mode == AdvisorMode.SHADOW:
                advice.executed = False
                advice.execution_result = "影子模式：仅记录，不执行"
            else:
                # 半自动或自动模式
                self._execute_advice(advice)

            self.advices.append(advice)

            logger.info(f"生成权重调整建议: {strategy_id}, {current_weight:.2f} → {suggested_weight:.2f}")

            # 广播事件
            if EVENT_BUS_AVAILABLE:
                bus = get_event_bus()
                bus.publish(
                    "meta.advice_generated",
                    {
                        "advice_type": "WEIGHT_ADJUSTMENT",
                        "strategy_id": strategy_id,
                        "change": change,
                        "mode": self.mode.value
                    },
                    source="meta_advisor"
                )

            return advice

        except Exception as e:
            logger.error(f"生成权重调整建议失败: {e}")
            return None

    def generate_stop_loss_adjustment(self,
                                      current_stop_loss: float,
                                      atr: float) -> Optional[Advice]:
        """
        生成止损调整建议

        Args:
            current_stop_loss: 当前止损乘数（如2.0表示2倍ATR）
            atr: ATR值

        Returns:
            建议对象
        """
        try:
            # 第二层防御：ATR检查
            if atr <= 0:
                logger.warning(f"ATR值无效: {atr}")
                return None

            # 规则：基于波动率动态调整止损
            # 高波动 → 提高止损倍数
            # 低波动 → 降低止损倍数

            if atr > 0.02:  # 高波动（2%以上）
                suggested_stop_loss = 2.5
                reason = f"高波动环境，提高止损容忍度 (ATR={atr:.4f})"

            elif atr < 0.005:  # 低波动（0.5%以下）
                suggested_stop_loss = 1.5
                reason = f"低波动环境，收紧止损 (ATR={atr:.4f})"

            else:
                suggested_stop_loss = 2.0
                reason = "波动率适中，保持默认止损"

            # 变动量
            change = suggested_stop_loss - current_stop_loss

            # 创建建议
            advice = Advice(
                advice_type="STOP_LOSS_ADJUSTMENT",
                suggested_value=suggested_stop_loss,
                current_value=current_stop_loss,
                change=change,
                confidence=0.7,
                reason=reason
            )

            # 影子模式下不执行
            if self.mode == AdvisorMode.SHADOW:
                advice.executed = False
                advice.execution_result = "影子模式：仅记录，不执行"
            else:
                self._execute_advice(advice)

            self.advices.append(advice)

            logger.info(f"生成止损调整建议: {current_stop_loss:.2f}x → {suggested_stop_loss:.2f}x ATR")

            return advice

        except Exception as e:
            logger.error(f"生成止损调整建议失败: {e}")
            return None

    def _execute_advice(self, advice: Advice) -> bool:
        """
        执行建议

        Args:
            advice: 建议对象

        Returns:
            是否执行成功
        """
        try:
            # 第三层防御：执行前检查
            if advice.confidence < 0.5:
                advice.executed = False
                advice.execution_result = "置信度不足，拒绝执行"
                return False

            # 半自动模式：小变动自动，大变动需人工确认
            if self.mode == AdvisorMode.SEMI_AUTO:
                change_abs = abs(advice.change)

                if change_abs <= self.auto_threshold:
                    # 小变动，自动执行
                    advice.executed = True
                    advice.execution_result = "半自动模式：小变动，自动执行"
                    logger.info(f"自动执行建议: {advice.advice_type}, 变动={advice.change:.4f}")
                else:
                    # 大变动，需人工确认
                    advice.executed = False
                    advice.execution_result = "半自动模式：大变动，需人工确认"
                    logger.warning(f"建议需人工确认: {advice.advice_type}, 变动={advice.change:.4f}")
                    return False

            # 自动模式：直接执行
            elif self.mode == AdvisorMode.AUTO:
                advice.executed = True
                advice.execution_result = "自动模式：直接执行"
                logger.info(f"自动执行建议: {advice.advice_type}, 变动={advice.change:.4f}")

            # 在实际系统中，这里会调用相应的执行接口
            # 例如：调整策略权重、修改止损参数等

            return True

        except Exception as e:
            logger.error(f"执行建议失败: {e}")
            advice.executed = False
            advice.execution_result = f"执行失败: {e}"
            return False

    def record_performance_comparison(self, meta_return: float, linucb_return: float) -> None:
        """
        记录性能对比

        Args:
            meta_return: 元学习建议器的收益率
            linucb_return: LinUCB的收益率
        """
        try:
            comparison = {
                'timestamp': time.time(),
                'meta_return': meta_return,
                'linucb_return': linucb_return,
                'difference': meta_return - linucb_return
            }

            self.performance_data.append(comparison)

            logger.debug(f"记录性能对比: Meta={meta_return:.4f}, LinUCB={linucb_return:.4f}, 差异={comparison['difference']:.4f}")

        except Exception as e:
            logger.error(f"记录性能对比失败: {e}")

    def analyze_significance(self, min_samples: int = 30) -> PerformanceComparison:
        """
        分析统计显著性

        Args:
            min_samples: 最小样本数

        Returns:
            性能对比结果
        """
        try:
            if len(self.performance_data) < min_samples:
                logger.warning(f"样本数不足: {len(self.performance_data)} < {min_samples}")
                return PerformanceComparison(sample_size=len(self.performance_data))

            # 计算累计收益
            total_meta = sum(d['meta_return'] for d in self.performance_data)
            total_linucb = sum(d['linucb_return'] for d in self.performance_data)

            # 计算差异
            difference = total_meta - total_linucb

            # 简化版显著性检验（基于样本数和差异）
            # 实际实现应使用t检验或bootstrap
            sample_size = len(self.performance_data)
            significance = min(abs(difference) * sample_size / 10.0, 1.0)

            comparison = PerformanceComparison(
                meta_advisor_return=total_meta,
                linucb_return=total_linucb,
                difference=difference,
                significance=significance,
                sample_size=sample_size
            )

            logger.info(f"性能对比分析: Meta={total_meta:.4f}, LinUCB={total_linucb:.4f}, 差异={difference:.4f}, 显著性={significance:.4f}")

            return comparison

        except Exception as e:
            logger.error(f"分析显著性失败: {e}")
            return PerformanceComparison()

    def can_upgrade_mode(self) -> Tuple[bool, str]:
        """
        检查是否可以升级模式（SHADOW → SEMI_AUTO → AUTO）

        Returns:
            (是否可升级, 原因)
        """
        try:
            # 影子模式 → 半自动模式
            if self.mode == AdvisorMode.SHADOW:
                # 检查运行天数
                days_elapsed = (time.time() - self.start_time) / 86400.0

                if days_elapsed < self.required_shadow_days:
                    return False, f"影子运行天数不足 ({days_elapsed:.1f} < {self.required_shadow_days})"

                # 检查性能对比
                comparison = self.analyze_significance()

                if comparison.sample_size < self.required_shadow_days:
                    return False, f"样本数不足 ({comparison.sample_size} < {self.required_shadow_days})"

                if comparison.significance < 0.7:
                    return False, f"性能差异不显著 (显著性={comparison.significance:.2f})"

                if comparison.difference <= 0:
                    return False, f"元学习未优于基准 (差异={comparison.difference:.4f})"

                return True, "满足升级条件"

            # 半自动模式 → 自动模式
            elif self.mode == AdvisorMode.SEMI_AUTO:
                # 检查半自动运行天数
                days_elapsed = (time.time() - self.start_time) / 86400.0

                if days_elapsed < self.required_shadow_days:
                    return False, f"半自动运行天数不足"

                return True, "满足升级条件"

            # 自动模式无需升级
            else:
                return False, "已是最高模式"

        except Exception as e:
            logger.error(f"检查升级条件失败: {e}")
            return False, f"检查失败: {e}"

    def upgrade_mode(self) -> bool:
        """
        升级运行模式

        Returns:
            是否升级成功
        """
        try:
            can_upgrade, reason = self.can_upgrade_mode()

            if not can_upgrade:
                logger.warning(f"无法升级模式: {reason}")
                return False

            old_mode = self.mode

            if self.mode == AdvisorMode.SHADOW:
                self.mode = AdvisorMode.SEMI_AUTO
            elif self.mode == AdvisorMode.SEMI_AUTO:
                self.mode = AdvisorMode.AUTO

            logger.info(f"模式升级成功: {old_mode.value} → {self.mode.value}")

            # 广播事件
            if EVENT_BUS_AVAILABLE:
                bus = get_event_bus()
                bus.publish(
                    "meta.mode_upgraded",
                    {
                        "old_mode": old_mode.value,
                        "new_mode": self.mode.value
                    },
                    source="meta_advisor"
                )

            return True

        except Exception as e:
            logger.error(f"升级模式失败: {e}")
            return False

    def get_statistics(self) -> Dict:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        try:
            total_advices = len(self.advices)
            executed_advices = sum(1 for a in self.advices if a.executed)

            # 按类型统计
            type_counts: Dict[str, int] = {}
            for advice in self.advices:
                type_counts[advice.advice_type] = type_counts.get(advice.advice_type, 0) + 1

            return {
                'mode': self.mode.value,
                'start_time': self.start_time,
                'days_in_shadow': (time.time() - self.start_time) / 86400.0,
                'total_advices': total_advices,
                'executed_advices': executed_advices,
                'execution_rate': executed_advices / total_advices if total_advices > 0 else 0.0,
                'advice_type_counts': type_counts,
                'performance_samples': len(self.performance_data)
            }

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}


if __name__ == "__main__":
    # 测试代码
    print("测试元学习建议器...")

    advisor = MetaLearnerAdvisor(
        mode=AdvisorMode.SHADOW,
        auto_threshold=0.05,
        required_shadow_days=14
    )

    # 测试1: 生成权重调整建议（优秀表现）
    print("\n测试1: 生成权重调整建议（优秀表现）")
    advice = advisor.generate_weight_adjustment(
        strategy_id="strategy_trend",
        current_weight=0.4,
        strategy_performance={'sharpe_ratio': 1.5, 'win_rate': 0.60}
    )
    print(f"建议: {advice.current_value:.2f} → {advice.suggested_value:.2f}, 原因={advice.reason}")
    print(f"执行状态: {advice.executed}, 结果={advice.execution_result}")

    # 测试2: 生成权重调整建议（表现不佳）
    print("\n测试2: 生成权重调整建议（表现不佳）")
    advice = advisor.generate_weight_adjustment(
        strategy_id="strategy_mean_revert",
        current_weight=0.3,
        strategy_performance={'sharpe_ratio': 0.3, 'win_rate': 0.40}
    )
    print(f"建议: {advice.current_value:.2f} → {advice.suggested_value:.2f}, 原因={advice.reason}")

    # 测试3: 生成止损调整建议（高波动）
    print("\n测试3: 生成止损调整建议（高波动）")
    advice = advisor.generate_stop_loss_adjustment(
        current_stop_loss=2.0,
        atr=0.025
    )
    print(f"建议: {advice.current_value:.2f}x → {advice.suggested_value:.2f}x ATR, 原因={advice.reason}")

    # 测试4: 升级到半自动模式
    print("\n测试4: 检查是否可升级")
    can_upgrade, reason = advisor.can_upgrade_mode()
    print(f"是否可升级: {can_upgrade}, 原因={reason}")

    # 测试5: 模拟影子运行14天后升级
    print("\n测试5: 模拟影子运行后升级")
    advisor.start_time = time.time() - 15 * 86400  # 15天前

    # 模拟性能对比数据
    for _ in range(15):
        advisor.record_performance_comparison(
            meta_return=0.01,
            linucb_return=0.005
        )

    can_upgrade, reason = advisor.can_upgrade_mode()
    print(f"是否可升级: {can_upgrade}, 原因={reason}")

    if can_upgrade:
        advisor.upgrade_mode()
        print(f"升级后模式: {advisor.mode.value}")

        # 测试6: 半自动模式下的建议执行
        print("\n测试6: 半自动模式下的建议执行")
        advice = advisor.generate_weight_adjustment(
            strategy_id="strategy_trend",
            current_weight=0.4,
            strategy_performance={'sharpe_ratio': 1.5, 'win_rate': 0.60}
        )
        print(f"建议: {advice.current_value:.2f} → {advice.suggested_value:.2f}")
        print(f"执行状态: {advice.executed}, 结果={advice.execution_result}")

    # 测试7: 获取统计
    print("\n测试7: 获取统计")
    stats = advisor.get_statistics()
    print(f"统计信息: 模式={stats['mode']}, 建议数={stats['total_advices']}, 执行率={stats['execution_rate']:.2%}")

    print("\n测试通过！")
