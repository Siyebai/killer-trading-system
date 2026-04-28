#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("linucb_cold_start")
except ImportError:
    import logging
    logger = logging.getLogger("linucb_cold_start")
"""
LinUCB冷启动优化模块 - V5.0 P1级
解决LinUCB优化器冷启动问题
核心策略：历史回测数据预训练、小样本学习模式、多臂老虎机探索-利用平衡
"""

import argparse
import json
import sys
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
import pickle
import os


@dataclass
class BacktestResult:
    """回测结果"""
    strategy: str
    returns: List[float]
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int


class LinUCBColdStart:
    """LinUCB冷启动优化器"""

    def __init__(
        self,
        strategies: List[str],
        feature_dim: int = 14,
        alpha: float = 1.0,
        epsilon: float = 0.1,
        use_bayesian_prior: bool = True,
        config: Optional[Dict] = None
    ):
        """
        初始化LinUCB冷启动优化器

        Args:
            strategies: 策略列表
            feature_dim: 特征维度
            alpha: 探索参数
            epsilon: epsilon-greedy探索率
            use_bayesian_prior: 是否使用贝叶斯先验
            config: 配置字典
        """
        self.strategies = strategies
        self.num_arms = len(strategies)
        self.feature_dim = feature_dim
        self.alpha = alpha
        self.epsilon = epsilon
        self.use_bayesian_prior = use_bayesian_prior
        self.config = config or {}

        # 初始化LinUCB参数
        self.A = [np.eye(feature_dim) for _ in range(self.num_arms)]
        self.b = [np.zeros(feature_dim) for _ in range(self.num_arms)]
        self.counts = np.zeros(self.num_arms)

        # 贝叶斯先验（如果启用）
        if self.use_bayesian_prior:
            self._initialize_bayesian_prior()

        # 预训练状态
        self.is_pretrained = False

    def _initialize_bayesian_prior(self):
        """初始化贝叶斯先验"""
        # 使用弱信息先验
        prior_mean = 0.5  # 中性期望
        prior_std = 0.3   # 适度不确定性

        # 用先验信息初始化b向量
        for arm in range(self.num_arms):
            self.b[arm] += prior_mean * prior_std * np.ones(self.feature_dim)

            # 用先验信息初始化A矩阵（增加初始置信度）
            self.A[arm] += np.eye(self.feature_dim) * 1.0

        # 设置初始虚拟计数
        self.counts = np.ones(self.num_arms) * 10  # 每个策略10次虚拟样本

    def pretrain_from_backtest(
        self,
        backtest_results: List[BacktestResult],
        market_states: List[Dict]
    ) -> Dict:
        """
        从回测结果预训练LinUCB

        Args:
            backtest_results: 回测结果列表
            market_states: 市场状态列表（与回测结果一一对应）

        Returns:
            预训练统计信息
        """
        logger.info(f"开始LinUCB冷启动预训练...")
        logger.info(f"策略数量: {self.num_arms}")
        logger.info(f"回测记录数: {len(backtest_results)}")

        # 策略索引映射
        strategy_to_idx = {s: i for i, s in enumerate(self.strategies)}

        # 预训练统计
        training_stats = defaultdict(int)
        strategy_rewards = defaultdict(list)

        for i, (result, state) in enumerate(zip(backtest_results, market_states)):
            strategy = result.strategy
            if strategy not in strategy_to_idx:
                continue

            arm = strategy_to_idx[strategy]

            # 计算奖励（基于多个指标）
            reward = self._calculate_backtest_reward(result)
            strategy_rewards[strategy].append(reward)

            # 提取特征
            context = self._extract_context(state)

            # 更新LinUCB参数
            self.A[arm] += np.outer(context, context)
            self.b[arm] += reward * context
            self.counts[arm] += 1

            training_stats["total_updates"] += 1
            training_stats[f"updates_{strategy}"] += 1

        # 计算策略平均奖励
        avg_rewards = {}
        for strategy, rewards in strategy_rewards.items():
            if rewards:
                avg_rewards[strategy] = np.mean(rewards)
            else:
                avg_rewards[strategy] = 0.5

        self.is_pretrained = True

        logger.info(f"\n预训练完成:")
        logger.info(f"  总更新次数: {training_stats['total_updates']}")
        for strategy in self.strategies:
            logger.info(f"  {strategy}: {training_stats.get(f'updates_{strategy}', 0)} 次更新")

        return {
            "status": "success",
            "pretrained": True,
            "total_updates": training_stats["total_updates"],
            "strategy_updates": {s: training_stats.get(f"updates_{s}", 0) for s in self.strategies},
            "avg_rewards": avg_rewards,
            "initial_weights": self.get_weights()
        }

    def _calculate_backtest_reward(self, result: BacktestResult) -> float:
        """
        基于回测结果计算奖励

        Args:
            result: 回测结果

        Returns:
            归一化奖励 [0, 1]
        """
        # 综合多个指标计算奖励
        reward = 0.0

        # 胜率权重 40%
        reward += result.win_rate * 0.4

        # 夏普比率权重 30%（归一化到[0,1]）
        sharpe_normalized = min(1.0, max(0.0, (result.sharpe_ratio + 1) / 4))
        reward += sharpe_normalized * 0.3

        # 最大回撤权重 20%（回撤越小奖励越高）
        drawdown_penalty = min(1.0, result.max_drawdown / 0.5)  # 50%回撤为最差
        reward += (1.0 - drawdown_penalty) * 0.2

        # 交易数量权重 10%（鼓励充分测试）
        trade_bonus = min(1.0, result.total_trades / 100)
        reward += trade_bonus * 0.1

        return max(0.0, min(1.0, reward))

    def _extract_context(self, market_state: Dict) -> np.ndarray:
        """
        从市场状态提取特征向量

        Args:
            market_state: 市场状态字典

        Returns:
            特征向量
        """
        features = np.zeros(self.feature_dim)

        # 基础特征
        features[0] = market_state.get("price_change_1m", 0)
        features[1] = market_state.get("price_change_5m", 0)
        features[2] = market_state.get("volume_change", 0)
        features[3] = market_state.get("volatility", 0)
        features[4] = market_state.get("rsi", 50) / 100
        features[5] = market_state.get("macd_signal", 0)
        features[6] = market_state.get("trend_strength", 0)

        # 微观结构特征
        features[7] = market_state.get("bid_ask_spread", 0)
        features[8] = market_state.get("order_flow", 0)
        features[9] = market_state.get("orderbook_slope", 0)
        features[10] = market_state.get("volume_delta", 0)
        features[11] = market_state.get("iceberg_detected", 0)
        features[12] = market_state.get("delta_divergence", 0)

        # 偏置项
        features[13] = 1.0

        return features

    def select_arm_epsilon_greedy(self, market_state: Dict) -> Tuple[int, str]:
        """
        使用epsilon-greedy策略选择策略（冷启动期推荐）

        Args:
            market_state: 市场状态

        Returns:
            (策略索引, 策略名称)
        """
        context = self._extract_context(market_state)

        # epsilon概率随机探索
        if np.random.random() < self.epsilon:
            arm = np.random.randint(self.num_arms)
            return arm, self.strategies[arm]

        # 1-epsilon概率选择最优
        ucb_values = []
        for arm in range(self.num_arms):
            try:
                theta = np.linalg.inv(self.A[arm]).dot(self.b[arm])
                ucb = theta.T.dot(context) + self.alpha * np.sqrt(
                    context.T.dot(np.linalg.inv(self.A[arm])).dot(context)
                )
                ucb_values.append(ucb)
            except np.linalg.LinAlgError:
                ucb_values.append(0.0)

        arm = int(np.argmax(ucb_values))
        return arm, self.strategies[arm]

    def select_arm_ucb(self, market_state: Dict) -> Tuple[int, str]:
        """
        使用UCB策略选择策略（正常期推荐）

        Args:
            market_state: 市场状态

        Returns:
            (策略索引, 策略名称)
        """
        context = self._extract_context(market_state)
        ucb_values = []

        for arm in range(self.num_arms):
            try:
                theta = np.linalg.inv(self.A[arm]).dot(self.b[arm])
                ucb = theta.T.dot(context) + self.alpha * np.sqrt(
                    context.T.dot(np.linalg.inv(self.A[arm])).dot(context)
                )
                ucb_values.append(ucb)
            except np.linalg.LinAlgError:
                ucb_values.append(0.0)

        arm = int(np.argmax(ucb_values))
        return arm, self.strategies[arm]

    def update(self, arm: int, reward: float, market_state: Dict):
        """
        更新模型参数

        Args:
            arm: 选中的策略索引
            reward: 获得的奖励 [0, 1]
            market_state: 当时的市场状态
        """
        context = self._extract_context(market_state)
        self.A[arm] += np.outer(context, context)
        self.b[arm] += reward * context
        self.counts[arm] += 1

    def get_weights(self) -> Dict[str, float]:
        """
        获取当前策略权重

        Returns:
            策略权重字典
        """
        total = np.sum(self.counts)
        if total == 0:
            return {s: 1.0 / self.num_arms for s in self.strategies}

        normalized_counts = self.counts / total
        return {s: float(normalized_counts[i]) for i, s in enumerate(self.strategies)}

    def save(self, filepath: str):
        """保存模型到文件"""
        model_data = {
            "strategies": self.strategies,
            "A": self.A,
            "b": self.b,
            "counts": self.counts,
            "alpha": self.alpha,
            "epsilon": self.epsilon,
            "is_pretrained": self.is_pretrained
        }

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)

    @classmethod
    def load(cls, filepath: str) -> 'LinUCBColdStart':
        """从文件加载模型"""
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        instance = cls(
            strategies=model_data["strategies"],
            alpha=model_data["alpha"],
            epsilon=model_data["epsilon"]
        )

        instance.A = model_data["A"]
        instance.b = model_data["b"]
        instance.counts = model_data["counts"]
        instance.is_pretrained = model_data["is_pretrained"]

        return instance


def main():
    parser = argparse.ArgumentParser(description="LinUCB冷启动优化")
    parser.add_argument("--action", choices=["pretrain", "select", "update", "save", "load"], default="pretrain", help="操作类型")
    parser.add_argument("--backtest", help="回测结果JSON文件路径")
    parser.add_argument("--states", help="市场状态JSON文件路径")
    parser.add_argument("--strategies", required=True, help="策略列表(JSON数组)")
    parser.add_argument("--market-state", help="当前市场状态JSON字符串")
    parser.add_argument("--arm", type=int, help="策略索引")
    parser.add_argument("--reward", type=float, help="奖励值")
    parser.add_argument("--model", help="模型文件路径")
    parser.add_argument("--mode", choices=["epsilon", "ucb"], default="epsilon", help="选择模式")

    args = parser.parse_args()

    try:
        strategies = json.loads(args.strategies)

        if not isinstance(strategies, list):
            logger.info((json.dumps({)
                "status": "error",
                "message": "strategies必须是列表格式"
            }, ensure_ascii=False))
            sys.exit(1)

        # 创建冷启动优化器
        optimizer = LinUCBColdStart(strategies)

        logger.info("=" * 70)
        logger.info("✅ LinUCB冷启动优化 - V5.0 P1级")
        logger.info("=" * 70)

        if args.action == "pretrain":
            if not args.backtest or not args.states:
                logger.info("错误: 请提供 --backtest 和 --states 参数")
                sys.exit(1)

            # 加载回测结果
            with open(args.backtest, 'r', encoding='utf-8') as f:
                backtest_data = json.load(f)

            # 加载市场状态
            with open(args.states, 'r', encoding='utf-8') as f:
                market_states = json.load(f)

            # 转换为BacktestResult对象
            backtest_results = []
            for item in backtest_data:
                result = BacktestResult(
                    strategy=item["strategy"],
                    returns=item.get("returns", []),
                    win_rate=item.get("win_rate", 0.5),
                    sharpe_ratio=item.get("sharpe_ratio", 0),
                    max_drawdown=item.get("max_drawdown", 0.5),
                    total_trades=item.get("total_trades", 0)
                )
                backtest_results.append(result)

            # 预训练
            result = optimizer.pretrain_from_backtest(backtest_results, market_states)

            logger.info(f"\n预训练结果:")
            logger.info(json.dumps(result, ensure_ascii=False, indent=2))

            output = result

        elif args.action == "select":
            if not args.market_state:
                logger.info("错误: 请提供 --market-state 参数")
                sys.exit(1)

            market_state = json.loads(args.market_state)

            if args.mode == "epsilon":
                arm, strategy = optimizer.select_arm_epsilon_greedy(market_state)
            else:
                arm, strategy = optimizer.select_arm_ucb(market_state)

            logger.info(f"\n选择结果:")
            logger.info(f"  策略索引: {arm}")
            logger.info(f"  策略名称: {strategy}")

            output = {
                "status": "success",
                "arm_index": arm,
                "strategy_name": strategy,
                "mode": args.mode
            }

        elif args.action == "update":
            if args.arm is None or args.reward is None or not args.market_state:
                logger.info("错误: 请提供 --arm, --reward 和 --market-state 参数")
                sys.exit(1)

            market_state = json.loads(args.market_state)

            optimizer.update(args.arm, args.reward, market_state)

            weights = optimizer.get_weights()

            logger.info(f"\n更新完成:")
            logger.info(f"  策略索引: {args.arm}")
            logger.info(f"  奖励: {args.reward}")
            logger.info(f"  当前权重: {weights}")

            output = {
                "status": "success",
                "arm_index": args.arm,
                "reward": args.reward,
                "current_weights": weights
            }

        elif args.action == "save":
            if not args.model:
                logger.info("错误: 请提供 --model 参数")
                sys.exit(1)

            optimizer.save(args.model)

            logger.info(f"\n模型已保存到: {args.model}")

            output = {
                "status": "success",
                "model_path": args.model
            }

        elif args.action == "load":
            if not args.model:
                logger.info("错误: 请提供 --model 参数")
                sys.exit(1)

            optimizer = LinUCBColdStart.load(args.model)

            weights = optimizer.get_weights()

            logger.info(f"\n模型已加载:")
            logger.info(f"  模型路径: {args.model}")
            logger.info(f"  策略数量: {len(optimizer.strategies)}")
            logger.info(f"  是否预训练: {optimizer.is_pretrained}")
            logger.info(f"  当前权重: {weights}")

            output = {
                "status": "success",
                "model_path": args.model,
                "strategies": optimizer.strategies,
                "is_pretrained": optimizer.is_pretrained,
                "current_weights": weights
            }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
