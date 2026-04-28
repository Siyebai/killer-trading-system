#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("experience_learning")
except ImportError:
    import logging
    logger = logging.getLogger("experience_learning")
"""
经验学习系统（第8层：学习经验）
经验累积系统 + 策略优化器 + 参数调优器
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import pandas as pd
from collections import defaultdict


class LearningType(Enum):
    """学习类型"""
    PARAMETER_OPTIMIZATION = "PARAMETER_OPTIMIZATION"  # 参数优化
    STRATEGY_SELECTION = "STRATEGY_SELECTION"  # 策略选择
    PATTERN_RECOGNITION = "PATTERN_RECOGNITION"  # 模式识别
    ADAPTIVE_LEARNING = "ADAPTIVE_LEARNING"  # 自适应学习


@dataclass
class Experience:
    """经验"""
    experience_id: str
    context: Dict[str, Any]  # 上下文（市场状态、策略参数等）
    action: Dict[str, Any]  # 采取的行动（策略选择、参数配置等）
    outcome: Dict[str, Any]  # 结果（盈亏、胜率等）
    timestamp: float = field(default_factory=time.time)
    score: float = 0.0  # 经验评分
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'experience_id': self.experience_id,
            'context': self.context,
            'action': self.action,
            'outcome': self.outcome,
            'timestamp': self.timestamp,
            'score': self.score,
            'tags': self.tags
        }


@dataclass
class LearningResult:
    """学习结果"""
    learning_type: LearningType
    best_params: Dict[str, Any]
    improved_score: float
    improvement_pct: float
    confidence: float
    recommendations: List[Dict[str, Any]]
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'learning_type': self.learning_type.value,
            'best_params': self.best_params,
            'improved_score': self.improved_score,
            'improvement_pct': self.improvement_pct,
            'confidence': self.confidence,
            'recommendations': self.recommendations,
            'details': self.details
        }


class ExperienceAccumulator:
    """经验累积器"""

    def __init__(self, max_experiences: int = 10000):
        self.max_experiences = max_experiences
        self.experiences: List[Experience] = []
        self.context_index: Dict[str, List[int]] = defaultdict(list)

    def add_experience(self, experience: Experience):
        """添加经验"""
        experience.score = self.calculate_experience_score(experience)

        self.experiences.append(experience)

        # 建立索引
        for tag in experience.tags:
            self.context_index[tag].append(len(self.experiences) - 1)

        # 限制数量
        if len(self.experiences) > self.max_experiences:
            self.experiences.pop(0)
            # 重建索引
            self.rebuild_index()

    def calculate_experience_score(self, experience: Experience) -> float:
        """计算经验评分"""
        score = 0.0

        # 盈亏评分
        pnl = experience.outcome.get('pnl', 0)
        score += np.tanh(pnl / 1000) * 0.5

        # 胜率评分
        win_rate = experience.outcome.get('win_rate', 0.5)
        score += (win_rate - 0.5) * 0.3

        # 夏普比率评分
        sharpe = experience.outcome.get('sharpe_ratio', 0)
        score += np.tanh(sharpe / 2) * 0.2

        return max(-1.0, min(1.0, score))

    def rebuild_index(self):
        """重建索引"""
        self.context_index.clear()
        for i, exp in enumerate(self.experiences):
            for tag in exp.tags:
                self.context_index[tag].append(i)

    def get_similar_experiences(self, context: Dict[str, Any], top_k: int = 10) -> List[Experience]:
        """获取相似经验"""
        # 简化版相似度计算
        similarities = []

        for i, exp in enumerate(self.experiences):
            similarity = self.calculate_similarity(context, exp.context)
            similarities.append((i, similarity))

        # 排序并返回top_k
        similarities.sort(key=lambda x: x[1], reverse=True)
        top_indices = [idx for idx, _ in similarities[:top_k]]

        return [self.experiences[idx] for idx in top_indices]

    def calculate_similarity(self, context1: Dict[str, Any], context2: Dict[str, Any]) -> float:
        """计算相似度"""
        # 简化版相似度
        similar_keys = set(context1.keys()) & set(context2.keys())

        if not similar_keys:
            return 0.0

        matches = 0
        for key in similar_keys:
            if context1[key] == context2[key]:
                matches += 1

        return matches / len(similar_keys)

    def get_experiences_by_tag(self, tag: str) -> List[Experience]:
        """按标签获取经验"""
        indices = self.context_index.get(tag, [])
        return [self.experiences[idx] for idx in indices]

    def get_best_actions(self, context: Dict[str, Any], top_k: int = 5) -> List[Dict[str, Any]]:
        """获取最佳行动"""
        similar_experiences = self.get_similar_experiences(context, top_k)

        # 按评分排序
        sorted_experiences = sorted(similar_experiences, key=lambda x: x.score, reverse=True)

        return [exp.action for exp in sorted_experiences]


class ParameterOptimizer:
    """参数优化器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.max_iterations = self.config.get('max_iterations', 100)
        self.population_size = self.config.get('population_size', 20)

    def optimize(self, experiences: List[Experience], param_space: Dict[str, Tuple[float, float]]) -> LearningResult:
        """优化参数"""
        # 使用简化版贝叶斯优化
        best_params = {}
        best_score = -float('inf')

        # 初始随机采样
        for _ in range(min(50, self.max_iterations)):
            params = self.sample_params(param_space)

            # 从相似经验中评估参数
            score = self.evaluate_params(params, experiences)

            if score > best_score:
                best_score = score
                best_params = params.copy()

        # 局部搜索
        for _ in range(self.max_iterations - 50):
            params = self.local_search(best_params, param_space)
            score = self.evaluate_params(params, experiences)

            if score > best_score:
                best_score = score
                best_params = params.copy()

        # 计算改进
        baseline_score = np.mean([exp.score for exp in experiences]) if experiences else 0
        improvement = best_score - baseline_score
        improvement_pct = (improvement / abs(baseline_score) * 100) if baseline_score != 0 else 0

        return LearningResult(
            learning_type=LearningType.PARAMETER_OPTIMIZATION,
            best_params=best_params,
            improved_score=best_score,
            improvement_pct=improvement_pct,
            confidence=min(len(experiences) / 100, 1.0),
            recommendations=[{'param': k, 'value': v} for k, v in best_params.items()],
            details={
                'baseline_score': baseline_score,
                'evaluated_configs': self.max_iterations
            }
        )

    def sample_params(self, param_space: Dict[str, Tuple[float, float]]) -> Dict[str, float]:
        """采样参数"""
        params = {}
        for param_name, (min_val, max_val) in param_space.items():
            params[param_name] = np.random.uniform(min_val, max_val)
        return params

    def local_search(self, current_params: Dict[str, float], param_space: Dict[str, Tuple[float, float]], step_size: float = 0.1) -> Dict[str, float]:
        """局部搜索"""
        new_params = {}
        for param_name, value in current_params.items():
            min_val, max_val = param_space[param_name]

            # 随机方向
            delta = np.random.uniform(-step_size, step_size)
            new_value = value * (1 + delta)
            new_value = max(min_val, min(max_val, new_value))

            new_params[param_name] = new_value

        return new_params

    def evaluate_params(self, params: Dict[str, float], experiences: List[Experience]) -> float:
        """评估参数"""
        # 简化评估：从匹配参数的经验中获取平均评分
        matching_experiences = []

        for exp in experiences:
            # 检查参数是否匹配
            match = True
            for param_name, param_value in params.items():
                exp_value = exp.action.get(param_name)
                if exp_value is None or abs(exp_value - param_value) > 0.2:
                    match = False
                    break

            if match:
                matching_experiences.append(exp)

        if not matching_experiences:
            return 0.0

        # 返回平均评分
        return np.mean([exp.score for exp in matching_experiences])


class StrategySelector:
    """策略选择器"""

    def __init__(self):
        pass

    def select_strategy(self, experiences: List[Experience], context: Dict[str, Any]) -> LearningResult:
        """选择策略"""
        # 按策略分组
        strategy_groups: Dict[str, List[Experience]] = defaultdict(list)

        for exp in experiences:
            strategy = exp.action.get('strategy', 'unknown')
            strategy_groups[strategy].append(exp)

        # 评估每个策略
        strategy_scores = {}
        for strategy, group_experiences in strategy_groups.items():
            if group_experiences:
                strategy_scores[strategy] = np.mean([exp.score for exp in group_experiences])
            else:
                strategy_scores[strategy] = 0.0

        # 选择最佳策略
        if not strategy_scores:
            best_strategy = 'default'
            best_score = 0.0
        else:
            best_strategy = max(strategy_scores.items(), key=lambda x: x[1])
            best_strategy = best_strategy[0]
            best_score = strategy_scores[best_strategy]

        return LearningResult(
            learning_type=LearningType.STRATEGY_SELECTION,
            best_params={'strategy': best_strategy},
            improved_score=best_score,
            improvement_pct=0.0,
            confidence=len(strategy_groups.get(best_strategy, [])) / max(len(experiences), 1),
            recommendations=[{'action': 'select_strategy', 'value': best_strategy}],
            details={'strategy_scores': strategy_scores}
        )


class PatternRecognizer:
    """模式识别器"""

    def __init__(self):
        pass

    def recognize_patterns(self, experiences: List[Experience]) -> List[Dict[str, Any]]:
        """识别模式"""
        patterns = []

        # 识别高胜率模式
        high_win_rate_experiences = [exp for exp in experiences if exp.outcome.get('win_rate', 0) > 0.7]

        if high_win_rate_experiences:
            # 分析共同特征
            common_features = self.analyze_common_features(high_win_rate_experiences)

            patterns.append({
                'type': 'high_win_rate',
                'features': common_features,
                'count': len(high_win_rate_experiences)
            })

        # 识别高盈亏比模式
        high_profit_factor_experiences = [exp for exp in experiences if exp.outcome.get('profit_factor', 0) > 2.0]

        if high_profit_factor_experiences:
            common_features = self.analyze_common_features(high_profit_factor_experiences)

            patterns.append({
                'type': 'high_profit_factor',
                'features': common_features,
                'count': len(high_profit_factor_experiences)
            })

        return patterns

    def analyze_common_features(self, experiences: List[Experience]) -> Dict[str, Any]:
        """分析共同特征"""
        # 简化版：统计出现频率最高的特征
        feature_counts: Dict[str, Any] = defaultdict(lambda: defaultdict(int))

        for exp in experiences:
            for key, value in exp.context.items():
                feature_counts[key][value] += 1

        common_features = {}
        for key, value_counts in feature_counts.items():
            # 选择出现频率最高的值
            most_common = max(value_counts.items(), key=lambda x: x[1])
            common_features[key] = most_common[0]

        return common_features


class ExperienceLearningSystem:
    """经验学习系统"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化经验学习系统

        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.max_experiences = self.config.get('max_experiences', 10000)

        self.accumulator = ExperienceAccumulator(self.max_experiences)
        self.parameter_optimizer = ParameterOptimizer(self.config.get('optimizer_config', {}))
        self.strategy_selector = StrategySelector()
        self.pattern_recognizer = PatternRecognizer()

    def add_experience(self, experience: Experience):
        """添加经验"""
        self.accumulator.add_experience(experience)

    def learn(self, learning_type: LearningType, context: Optional[Dict] = None) -> LearningResult:
        """学习"""
        experiences = self.accumulator.experiences

        if not experiences:
            return LearningResult(
                learning_type=learning_type,
                best_params={},
                improved_score=0.0,
                improvement_pct=0.0,
                confidence=0.0,
                recommendations=[],
                details={'message': '没有足够的经验进行学习'}
            )

        if learning_type == LearningType.PARAMETER_OPTIMIZATION:
            # 参数优化
            param_space = {
                'stop_loss_pct': (0.01, 0.05),
                'take_profit_pct': (0.01, 0.10),
                'confidence_threshold': (0.5, 0.9)
            }

            return self.parameter_optimizer.optimize(experiences, param_space)

        elif learning_type == LearningType.STRATEGY_SELECTION:
            # 策略选择
            return self.strategy_selector.select_strategy(experiences, context or {})

        elif learning_type == LearningType.PATTERN_RECOGNITION:
            # 模式识别
            patterns = self.pattern_recognizer.recognize_patterns(experiences)

            return LearningResult(
                learning_type=LearningType.PATTERN_RECOGNITION,
                best_params={},
                improved_score=0.0,
                improvement_pct=0.0,
                confidence=len(experiences) / self.max_experiences,
                recommendations=[{'pattern': p} for p in patterns],
                details={'patterns': patterns}
            )

        else:
            return LearningResult(
                learning_type=learning_type,
                best_params={},
                improved_score=0.0,
                improvement_pct=0.0,
                confidence=0.0,
                recommendations=[],
                details={'message': '不支持的学习类型'}
            )

    def get_recommendations(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取推荐"""
        # 从相似经验中获取最佳行动
        best_actions = self.accumulator.get_best_actions(context, top_k=3)

        recommendations = []
        for action in best_actions:
            recommendations.append({
                'action': action,
                'confidence': 0.8
            })

        return recommendations

    def get_learning_summary(self) -> Dict[str, Any]:
        """获取学习摘要"""
        return {
            'total_experiences': len(self.accumulator.experiences),
            'avg_score': np.mean([exp.score for exp in self.accumulator.experiences]) if self.accumulator.experiences else 0.0,
            'best_score': max([exp.score for exp in self.accumulator.experiences]) if self.accumulator.experiences else 0.0,
            'worst_score': min([exp.score for exp in self.accumulator.experiences]) if self.accumulator.experiences else 0.0,
            'top_tags': [
                (tag, len(indices))
                for tag, indices in sorted(self.accumulator.context_index.items(), key=lambda x: len(x[1]), reverse=True)[:10]
            ]
        }


def main():
    parser = argparse.ArgumentParser(description="经验学习系统（第8层：学习经验）")
    parser.add_argument("--action", choices=["learn", "add_experience", "recommend", "summary", "test"], default="test", help="操作类型")
    parser.add_argument("--experience", help="经验数据JSON")
    parser.add_argument("--context", help="上下文JSON")
    parser.add_argument("--learning_type", choices=["PARAMETER_OPTIMIZATION", "STRATEGY_SELECTION", "PATTERN_RECOGNITION"], help="学习类型")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r') as f:
                config = json.load(config)

        # 创建经验学习系统
        learning_system = ExperienceLearningSystem(config)

        logger.info("=" * 70)
        logger.info("✅ 杀手锏交易系统 - 经验学习系统（第8层：学习经验）")
        logger.info("=" * 70)

        if args.action == "add_experience":
            # 添加经验
            if not args.experience:
                logger.info("错误: 请提供经验数据")
                sys.exit(1)

            experience_data = json.loads(args.experience)
            experience = Experience(**experience_data)

            learning_system.add_experience(experience)

            output = {
                "status": "success",
                "message": "经验已添加",
                "experience_id": experience.experience_id
            }

        elif args.action == "learn":
            # 学习
            if not args.learning_type:
                logger.info("错误: 请指定学习类型")
                sys.exit(1)

            learning_type = LearningType(args.learning_type)
            context = json.loads(args.context) if args.context else {}

            logger.info(f"\n[学习开始] 学习类型: {learning_type.value}")

            result = learning_system.learn(learning_type, context)

            logger.info(f"\n[学习完成]")
            logger.info(f"  最佳参数: {result.best_params}")
            logger.info(f"  改进评分: {result.improved_score:.4f}")
            logger.info(f"  改进幅度: {result.improvement_pct:.2%}")
            logger.info(f"  置信度: {result.confidence:.2%}")

            if result.recommendations:
                logger.info(f"\n[推荐行动]")
                for i, rec in enumerate(result.recommendations, 1):
                    logger.info(f"  {i}. {rec}")

            output = {
                "status": "success",
                "learning_result": result.to_dict()
            }

        elif args.action == "recommend":
            # 获取推荐
            if not args.context:
                logger.info("错误: 请提供上下文")
                sys.exit(1)

            context = json.loads(args.context)
            recommendations = learning_system.get_recommendations(context)

            output = {
                "status": "success",
                "recommendations": recommendations
            }

        elif args.action == "summary":
            # 学习摘要
            summary = learning_system.get_learning_summary()

            output = {
                "status": "success",
                "summary": summary
            }

        elif args.action == "test":
            # 测试模式
            # 生成测试经验数据
            test_experiences = []
            base_time = time.time() - 86400 * 30

            for i in range(100):
                is_profit = np.random.random() > 0.4
                win_rate = np.random.uniform(0.3, 0.8)

                experience = Experience(
                    experience_id=f'exp_{i}',
                    context={
                        'market': 'BTCUSDT',
                        'timeframe': '1h',
                        'trend': 'bullish' if np.random.random() > 0.5 else 'bearish'
                    },
                    action={
                        'strategy': 'trend_following' if i % 3 == 0 else 'mean_reversion',
                        'stop_loss_pct': np.random.uniform(0.01, 0.05),
                        'take_profit_pct': np.random.uniform(0.02, 0.10)
                    },
                    outcome={
                        'pnl': np.random.uniform(-500, 1000) if is_profit else np.random.uniform(-1000, 200),
                        'win_rate': win_rate,
                        'sharpe_ratio': np.random.uniform(-1, 2),
                        'profit_factor': np.random.uniform(0.5, 3.0)
                    },
                    tags=['BTCUSDT', f"strategy_{'trend_following' if i % 3 == 0 else 'mean_reversion'}"]
                )

                learning_system.add_experience(experience)

            # 测试学习
            param_result = learning_system.learn(LearningType.PARAMETER_OPTIMIZATION)
            strategy_result = learning_system.learn(LearningType.STRATEGY_SELECTION)
            pattern_result = learning_system.learn(LearningType.PATTERN_RECOGNITION)

            # 测试推荐
            test_context = {
                'market': 'BTCUSDT',
                'timeframe': '1h',
                'trend': 'bullish'
            }
            recommendations = learning_system.get_recommendations(test_context)

            # 学习摘要
            summary = learning_system.get_learning_summary()

            output = {
                "status": "success",
                "test_parameter_optimization": param_result.to_dict(),
                "test_strategy_selection": strategy_result.to_dict(),
                "test_pattern_recognition": pattern_result.to_dict(),
                "test_recommendations": recommendations,
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
