#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("self_optimization_system")
except ImportError:
    import logging
    logger = logging.getLogger("self_optimization_system")
"""
自我优化系统（第10层：自我优化）
元学习系统 + 自动优化引擎 + 系统进化器
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import hashlib


class OptimizationType(Enum):
    """优化类型"""
    PARAMETER_TUNING = "PARAMETER_TUNING"  # 参数调优
    STRATEGY_EVOLUTION = "STRATEGY_EVOLUTION"  # 策略进化
    SYSTEM_CONFIG = "SYSTEM_CONFIG"  # 系统配置
    PERFORMANCE_BOOST = "PERFORMANCE_BOOST"  # 性能提升


@dataclass
class OptimizationTarget:
    """优化目标"""
    target_id: str
    metric_name: str  # 指标名称
    target_value: float  # 目标值
    current_value: float  # 当前值
    weight: float  # 权重
    direction: str  # 'maximize' or 'minimize'

    def gap(self) -> float:
        """差距"""
        if self.direction == 'maximize':
            return self.current_value - self.target_value
        else:
            return self.target_value - self.current_value

    def gap_pct(self) -> float:
        """差距百分比"""
        if self.target_value == 0:
            return 0.0

        return abs(self.gap()) / abs(self.target_value)

    def to_dict(self) -> Dict:
        return {
            'target_id': self.target_id,
            'metric_name': self.metric_name,
            'target_value': self.target_value,
            'current_value': self.current_value,
            'weight': self.weight,
            'direction': self.direction,
            'gap': self.gap(),
            'gap_pct': self.gap_pct()
        }


@dataclass
class OptimizationResult:
    """优化结果"""
    optimization_type: OptimizationType
    success: bool
    improvements: Dict[str, float]  # 指标改进
    config_changes: Dict[str, Any]  # 配置变更
    performance_delta: float  # 性能变化
    confidence: float  # 置信度
    execution_time: float  # 执行时间
    recommendations: List[str]  # 建议
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'optimization_type': self.optimization_type.value,
            'success': self.success,
            'improvements': self.improvements,
            'config_changes': self.config_changes,
            'performance_delta': self.performance_delta,
            'confidence': self.confidence,
            'execution_time': self.execution_time,
            'recommendations': self.recommendations,
            'details': self.details
        }


class MetaLearningSystem:
    """元学习系统"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.learning_rate = self.config.get('learning_rate', 0.1)

        # 学习历史
        self.learning_history: List[Dict] = []

    def learn_from_optimization(self, optimization_result: OptimizationResult):
        """从优化结果中学习"""
        learning_record = {
            'timestamp': time.time(),
            'optimization_type': optimization_result.optimization_type.value,
            'success': optimization_result.success,
            'performance_delta': optimization_result.performance_delta,
            'config_changes': optimization_result.config_changes.copy()
        }

        self.learning_history.append(learning_record)

        # 限制历史记录数量
        if len(self.learning_history) > 1000:
            self.learning_history.pop(0)

    def predict_optimization_effectiveness(self, optimization_type: OptimizationType, config_changes: Dict[str, Any]) -> float:
        """预测优化效果"""
        # 简化版：基于历史记录预测
        relevant_history = [
            record for record in self.learning_history
            if record['optimization_type'] == optimization_type.value
        ]

        if not relevant_history:
            return 0.5  # 默认置信度

        # 计算成功率
        success_count = sum(1 for record in relevant_history if record['success'])
        success_rate = success_count / len(relevant_history)

        return success_rate

    def get_best_practices(self, optimization_type: OptimizationType) -> List[Dict[str, Any]]:
        """获取最佳实践"""
        relevant_history = [
            record for record in self.learning_history
            if record['optimization_type'] == optimization_type.value and record['success']
        ]

        # 按性能提升排序
        sorted_history = sorted(relevant_history, key=lambda x: x['performance_delta'], reverse=True)

        return sorted_history[:10]


class AutoOptimizer:
    """自动优化引擎"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.max_iterations = self.config.get('max_iterations', 100)
        self.tolerance = self.config.get('tolerance', 0.01)

    def optimize_parameters(self, current_config: Dict[str, Any], targets: List[OptimizationTarget]) -> OptimizationResult:
        """优化参数"""
        start_time = time.time()

        # 简化版：网格搜索
        best_config = current_config.copy()
        best_score = self.evaluate_config(current_config, targets)

        # 参数搜索空间
        search_space = self.define_search_space(current_config)

        # 网格搜索
        for iteration in range(min(self.max_iterations, 50)):
            # 采样新配置
            new_config = self.sample_config(current_config, search_space)
            score = self.evaluate_config(new_config, targets)

            if score > best_score:
                best_score = score
                best_config = new_config.copy()

        # 计算改进
        original_score = self.evaluate_config(current_config, targets)
        performance_delta = best_score - original_score

        # 配置变更
        config_changes = {}
        for key, value in best_config.items():
            if key in current_config and value != current_config[key]:
                config_changes[key] = {
                    'from': current_config[key],
                    'to': value
                }

        # 建议
        recommendations = []
        if performance_delta > 0:
            recommendations.append(f"优化成功，性能提升{performance_delta:.4f}")
        elif performance_delta < -self.tolerance:
            recommendations.append("优化后性能下降，建议回滚")
        else:
            recommendations.append("性能无明显变化，当前配置已接近最优")

        return OptimizationResult(
            optimization_type=OptimizationType.PARAMETER_TUNING,
            success=performance_delta > 0,
            improvements={'score_improvement': performance_delta},
            config_changes=config_changes,
            performance_delta=performance_delta,
            confidence=min(iteration / self.max_iterations, 1.0),
            execution_time=time.time() - start_time,
            recommendations=recommendations,
            details={'best_score': best_score, 'original_score': original_score}
        )

    def define_search_space(self, config: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
        """定义搜索空间"""
        search_space = {}

        # 定义可优化参数的范围
        for key, value in config.items():
            if isinstance(value, (int, float)):
                # 简化版：使用±20%的搜索空间
                lower = value * 0.8
                upper = value * 1.2
                search_space[key] = (lower, upper)

        return search_space

    def sample_config(self, base_config: Dict[str, Any], search_space: Dict[str, Tuple[float, float]]) -> Dict[str, Any]:
        """采样配置"""
        new_config = base_config.copy()

        for key, (lower, upper) in search_space.items():
            new_config[key] = np.random.uniform(lower, upper)

        return new_config

    def evaluate_config(self, config: Dict[str, Any], targets: List[OptimizationTarget]) -> float:
        """评估配置"""
        # 简化版：基于目标差距计算得分
        total_score = 0.0
        total_weight = 0.0

        for target in targets:
            gap_pct = target.gap_pct()
            weight = target.weight

            # 得分计算：差距越小，得分越高
            score = 1.0 / (1.0 + gap_pct * 10)

            total_score += score * weight
            total_weight += weight

        return total_score / total_weight if total_weight > 0 else 0.0


class SystemEvolver:
    """系统进化器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

        # 进化历史
        self.evolution_history: List[Dict] = []
        self.generation = 0

    def evolve_system(self, current_performance: Dict[str, Any], targets: List[OptimizationTarget]) -> OptimizationResult:
        """进化系统"""
        start_time = time.time()

        self.generation += 1

        # 分析当前性能
        performance_analysis = self.analyze_performance(current_performance, targets)

        # 生成进化策略
        evolution_strategies = self.generate_evolution_strategies(performance_analysis)

        # 选择最佳策略
        best_strategy = evolution_strategies[0] if evolution_strategies else {
            'type': 'no_action',
            'description': '无需进化',
            'config_changes': {}
        }

        # 执行进化
        config_changes = best_strategy['config_changes']
        performance_delta = self.estimate_performance_delta(best_strategy, current_performance)

        # 记录进化历史
        evolution_record = {
            'generation': self.generation,
            'timestamp': time.time(),
            'performance': current_performance.copy(),
            'strategy': best_strategy,
            'performance_delta': performance_delta
        }

        self.evolution_history.append(evolution_record)

        return OptimizationResult(
            optimization_type=OptimizationType.SYSTEM_CONFIG,
            success=performance_delta > 0,
            improvements={'performance_delta': performance_delta},
            config_changes=config_changes,
            performance_delta=performance_delta,
            confidence=best_strategy.get('confidence', 0.5),
            execution_time=time.time() - start_time,
            recommendations=[best_strategy['description']],
            details={
                'generation': self.generation,
                'evolution_strategy': best_strategy,
                'performance_analysis': performance_analysis
            }
        )

    def analyze_performance(self, current_performance: Dict[str, Any], targets: List[OptimizationTarget]) -> Dict[str, Any]:
        """分析性能"""
        analysis = {
            'overall_gap': 0.0,
            'critical_issues': [],
            'improvement_areas': []
        }

        for target in targets:
            gap = target.gap()
            gap_pct = target.gap_pct()

            if gap_pct > 0.3:  # 超过30%差距
                analysis['critical_issues'].append({
                    'metric': target.metric_name,
                    'gap_pct': gap_pct,
                    'current': target.current_value,
                    'target': target.target_value
                })

            if gap_pct > 0.1:  # 超过10%差距
                analysis['improvement_areas'].append({
                    'metric': target.metric_name,
                    'gap_pct': gap_pct
                })

            analysis['overall_gap'] += abs(gap_pct) * target.weight

        return analysis

    def generate_evolution_strategies(self, performance_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成进化策略"""
        strategies = []

        # 基于关键问题生成策略
        for issue in performance_analysis['critical_issues']:
            metric = issue['metric']

            if 'win_rate' in metric:
                strategies.append({
                    'type': 'boost_win_rate',
                    'description': '提升胜率：优化信号质量，收紧入场条件',
                    'config_changes': {
                        'signal_threshold': {'from': 0.5, 'to': 0.65},
                        'min_confidence': {'from': 0.6, 'to': 0.75}
                    },
                    'confidence': 0.8
                })

            elif 'sharpe_ratio' in metric:
                strategies.append({
                    'type': 'boost_sharpe',
                    'description': '提升夏普比率：降低波动率，优化风险调整收益',
                    'config_changes': {
                        'risk_limit': {'from': 0.02, 'to': 0.015},
                        'position_size': {'from': 0.1, 'to': 0.08}
                    },
                    'confidence': 0.7
                })

            elif 'drawdown' in metric:
                strategies.append({
                    'type': 'reduce_drawdown',
                    'description': '降低回撤：收紧止损，降低仓位',
                    'config_changes': {
                        'stop_loss_pct': {'from': 0.02, 'to': 0.015},
                        'max_position_size': {'from': 0.2, 'to': 0.15}
                    },
                    'confidence': 0.9
                })

        # 如果没有关键问题，生成通用优化策略
        if not strategies and performance_analysis['improvement_areas']:
            strategies.append({
                'type': 'general_optimization',
                'description': '通用优化：微调参数，提升整体性能',
                'config_changes': {},
                'confidence': 0.5
            })

        return strategies

    def estimate_performance_delta(self, strategy: Dict[str, Any], current_performance: Dict[str, Any]) -> float:
        """估计性能变化"""
        # 简化版：基于策略置信度估计
        confidence = strategy.get('confidence', 0.5)

        # 随机扰动
        delta = np.random.uniform(-0.1, 0.1) * confidence

        return delta


class SelfOptimizationSystem:
    """自我优化系统"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化自我优化系统

        Args:
            config: 配置字典
        """
        self.config = config or {}

        self.meta_learning_system = MetaLearningSystem(self.config.get('meta_learning_config', {}))
        self.auto_optimizer = AutoOptimizer(self.config.get('optimizer_config', {}))
        self.system_evolver = SystemEvolver(self.config.get('evolver_config', {}))

        # 当前配置
        self.current_config = self.config.get('current_config', {})

    def set_current_config(self, config: Dict[str, Any]):
        """设置当前配置"""
        self.current_config = config.copy()

    def optimize(self, optimization_type: OptimizationType, targets: List[OptimizationType], current_performance: Optional[Dict] = None) -> OptimizationResult:
        """执行优化"""
        logger.info(f"[优化开始] 优化类型: {optimization_type.value}")

        start_time = time.time()

        if optimization_type == OptimizationType.PARAMETER_TUNING:
            # 参数调优
            result = self.auto_optimizer.optimize_parameters(self.current_config, targets)

        elif optimization_type == OptimizationType.SYSTEM_CONFIG:
            # 系统配置优化
            if not current_performance:
                current_performance = self.get_current_performance()

            result = self.system_evolver.evolve_system(current_performance, targets)

        else:
            # 其他优化类型（简化版）
            result = OptimizationResult(
                optimization_type=optimization_type,
                success=False,
                improvements={},
                config_changes={},
                performance_delta=0.0,
                confidence=0.0,
                execution_time=time.time() - start_time,
                recommendations=['暂不支持此优化类型'],
                details={}
            )

        # 学习优化结果
        self.meta_learning_system.learn_from_optimization(result)

        # 更新当前配置
        if result.success and result.config_changes:
            self.apply_config_changes(result.config_changes)

        logger.info(f"[优化完成] 成功: {result.success}")
        logger.info(f"[优化结果] 性能变化: {result.performance_delta:.4f}")
        logger.info(f"[优化结果] 置信度: {result.confidence:.2%}")

        return result

    def apply_config_changes(self, config_changes: Dict[str, Any]):
        """应用配置变更"""
        for key, change_info in config_changes.items():
            if isinstance(change_info, dict) and 'to' in change_info:
                self.current_config[key] = change_info['to']
            else:
                self.current_config[key] = change_info

    def get_current_config(self) -> Dict[str, Any]:
        """获取当前配置"""
        return self.current_config.copy()

    def get_optimization_history(self) -> List[Dict]:
        """获取优化历史"""
        return self.meta_learning_system.learning_history.copy()

    def get_evolution_history(self) -> List[Dict]:
        """获取进化历史"""
        return self.system_evolver.evolution_history.copy()

    def get_optimization_summary(self) -> Dict[str, Any]:
        """获取优化摘要"""
        return {
            'current_config': self.current_config,
            'optimization_history_size': len(self.meta_learning_system.learning_history),
            'evolution_generation': self.system_evolver.generation,
            'best_practices': self.meta_learning_system.get_best_practices(OptimizationType.PARAMETER_TUNING)
        }


def main():
    parser = argparse.ArgumentParser(description="自我优化系统（第10层：自我优化）")
    parser.add_argument("--action", choices=["optimize", "config", "history", "summary", "test"], default="test", help="操作类型")
    parser.add_argument("--optimization_type", choices=["PARAMETER_TUNING", "STRATEGY_EVOLUTION", "SYSTEM_CONFIG", "PERFORMANCE_BOOST"], help="优化类型")
    parser.add_argument("--targets", help="优化目标JSON")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r') as f:
                config = json.load(config)

        # 创建自我优化系统
        optimization_system = SelfOptimizationSystem(config)

        logger.info("=" * 70)
        logger.info("✅ 杀手锏交易系统 - 自我优化系统（第10层：自我优化）")
        logger.info("=" * 70)

        if args.action == "optimize":
            # 执行优化
            if not args.optimization_type:
                logger.info("错误: 请指定优化类型")
                sys.exit(1)

            optimization_type = OptimizationType(args.optimization_type)

            # 加载优化目标
            if args.targets:
                targets_data = json.loads(args.targets)
                targets = [OptimizationTarget(**t) for t in targets_data]
            else:
                # 默认目标
                targets = [
                    OptimizationTarget(
                        target_id='win_rate',
                        metric_name='win_rate',
                        target_value=0.65,
                        current_value=0.55,
                        weight=0.4,
                        direction='maximize'
                    ),
                    OptimizationTarget(
                        target_id='sharpe_ratio',
                        metric_name='sharpe_ratio',
                        target_value=1.5,
                        current_value=0.8,
                        weight=0.3,
                        direction='maximize'
                    ),
                    OptimizationTarget(
                        target_id='max_drawdown',
                        metric_name='max_drawdown',
                        target_value=0.1,
                        current_value=0.15,
                        weight=0.3,
                        direction='minimize'
                    )
                ]

            result = optimization_system.optimize(optimization_type, targets)

            logger.info(f"\n[优化详情]")
            logger.info(f"  配置变更: {json.dumps(result.config_changes, ensure_ascii=False, indent=2)}")
            logger.info(f"  建议:")
            for rec in result.recommendations:
                logger.info(f"    - {rec}")

            output = {
                "status": "success",
                "optimization_result": result.to_dict()
            }

        elif args.action == "config":
            # 获取当前配置
            current_config = optimization_system.get_current_config()

            output = {
                "status": "success",
                "current_config": current_config
            }

        elif args.action == "history":
            # 获取优化历史
            optimization_history = optimization_system.get_optimization_history()
            evolution_history = optimization_system.get_evolution_history()

            output = {
                "status": "success",
                "optimization_history": optimization_history,
                "evolution_history": evolution_history
            }

        elif args.action == "summary":
            # 优化摘要
            summary = optimization_system.get_optimization_summary()

            output = {
                "status": "success",
                "summary": summary
            }

        elif args.action == "test":
            # 测试模式
            # 设置当前配置
            test_config = {
                'signal_threshold': 0.5,
                'min_confidence': 0.6,
                'risk_limit': 0.02,
                'position_size': 0.1,
                'stop_loss_pct': 0.02,
                'max_position_size': 0.2
            }

            optimization_system.set_current_config(test_config)

            # 设置优化目标
            targets = [
                OptimizationTarget(
                    target_id='win_rate',
                    metric_name='win_rate',
                    target_value=0.65,
                    current_value=0.55,
                    weight=0.4,
                    direction='maximize'
                ),
                OptimizationTarget(
                    target_id='sharpe_ratio',
                    metric_name='sharpe_ratio',
                    target_value=1.5,
                    current_value=0.8,
                    weight=0.3,
                    direction='maximize'
                ),
                OptimizationTarget(
                    target_id='max_drawdown',
                    metric_name='max_drawdown',
                    target_value=0.1,
                    current_value=0.15,
                    weight=0.3,
                    direction='minimize'
                )
            ]

            # 测试参数调优
            param_result = optimization_system.optimize(OptimizationType.PARAMETER_TUNING, targets)

            # 测试系统配置优化
            current_performance = {
                'win_rate': 0.55,
                'sharpe_ratio': 0.8,
                'max_drawdown': 0.15
            }

            config_result = optimization_system.optimize(OptimizationType.SYSTEM_CONFIG, targets, current_performance)

            # 获取摘要
            summary = optimization_system.get_optimization_summary()

            output = {
                "status": "success",
                "test_parameter_tuning": param_result.to_dict(),
                "test_system_config": config_result.to_dict(),
                "test_summary": summary
            }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        import traceback
        logger.error((json.dumps({)
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
