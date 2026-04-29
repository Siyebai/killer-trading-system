#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("linucb_optimizer")
except ImportError:
    import logging
    logger = logging.getLogger("linucb_optimizer")
"""
LinUCB强化学习权重优化模块
基于历史交易表现动态调整策略权重
"""

import argparse
import json
import sys
import numpy as np
from typing import Dict, List


class LinUCB:
    """
    LinUCB (Linear Upper Confidence Bound) 上下文老虎机算法
    用于多策略动态权重优化
    """

    def __init__(self, num_arms: int, alpha: float = 1.0, feature_dim: int = 14):
        """
        初始化LinUCB

        Args:
            num_arms: 策略数量（必须>0）
            alpha: 探索参数，控制探索与利用的平衡
            feature_dim: 特征维度（市场特征，V4.5增强版默认14维）

        Raises:
            ValueError: 如果num_arms <= 0或feature_dim <= 0
        """
        # BUG #6修复：验证参数
        if num_arms <= 0:
            raise ValueError(f"num_arms必须大于0，当前值: {num_arms}")
        if feature_dim <= 0:
            raise ValueError(f"feature_dim必须大于0，当前值: {feature_dim}")

        self.num_arms = num_arms
        self.alpha = alpha
        self.feature_dim = feature_dim

        # 每个策略独立的上下文参数
        self.A = [np.eye(feature_dim) for _ in range(num_arms)]  # 协方差矩阵
        self.b = [np.zeros(feature_dim) for _ in range(num_arms)]  # 奖励向量
        self.counts = np.zeros(num_arms)  # 每个策略的调用次数

    def get_context(self, market_state: Dict) -> np.ndarray:
        """
        从市场状态提取特征向量（V4.5增强版 - 包含微观结构特征）

        Args:
            market_state: 市场状态字典

        Returns:
            特征向量（14维）
        """
        # V4.5增强：扩展特征维度从10到14，加入订单簿和Volume Delta特征
        features = np.zeros(14)  # 明确指定14维

        features[0] = market_state.get("price_change_1m", 0)  # 1分钟价格变化
        features[1] = market_state.get("price_change_5m", 0)  # 5分钟价格变化
        features[2] = market_state.get("volume_change", 0)    # 成交量变化
        features[3] = market_state.get("volatility", 0)       # 波动率
        features[4] = market_state.get("rsi", 50) / 100       # RSI归一化
        features[5] = market_state.get("macd_signal", 0)      # MACD信号
        features[6] = market_state.get("trend_strength", 0)   # 趋势强度
        features[7] = market_state.get("bid_ask_spread", 0)   # 买卖价差
        features[8] = market_state.get("order_flow", 0)       # 订单流
        features[9] = market_state.get("orderbook_slope", 0)  # V4.5新：订单簿斜率
        features[10] = market_state.get("volume_delta", 0)    # V4.5新：Volume Delta
        features[11] = market_state.get("iceberg_detected", 0)  # V4.5新：冰山订单检测
        features[12] = market_state.get("delta_divergence", 0)  # V4.5新：Delta背离
        features[13] = 1.0  # 偏置项

        return features

    def select_arm(self, market_state: Dict) -> int:
        """
        选择最优策略（UCB决策）

        Args:
            market_state: 当前市场状态

        Returns:
            选中的策略索引
        """
        context = self.get_context(market_state)
        ucb_values = []

        for arm in range(self.num_arms):
            # 计算theta
            theta = np.linalg.inv(self.A[arm]).dot(self.b[arm])

            # 计算UCB
            ucb = theta.T.dot(context) + self.alpha * np.sqrt(
                context.T.dot(np.linalg.inv(self.A[arm])).dot(context)
            )
            ucb_values.append(ucb)

        return int(np.argmax(ucb_values))

    def update(self, arm: int, reward: float, market_state: Dict):
        """
        更新模型参数

        Args:
            arm: 选中的策略索引
            reward: 获得的奖励
            market_state: 当时的市场状态
        """
        context = self.get_context(market_state)
        self.A[arm] += np.outer(context, context)
        self.b[arm] += reward * context
        self.counts[arm] += 1

    def get_weights(self) -> List[float]:
        """
        获取当前策略权重（基于调用频率）

        Returns:
            策略权重列表
        """
        total = np.sum(self.counts)
        if total == 0:
            return [1.0 / self.num_arms] * self.num_arms

        return (self.counts / total).tolist()


def load_history(history_path: str) -> List[Dict]:
    """加载历史交易记录"""
    with open(history_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_rewards(history: List[Dict], strategies: List[str]) -> Dict[str, float]:
    """
    从历史记录提取策略奖励

    Args:
        history: 交易历史
        strategies: 策略列表

    Returns:
        策略平均奖励映射
    """
    strategy_rewards = {s: [] for s in strategies}
    strategy_returns = {s: [] for s in strategies}

    for trade in history:
        strategy = trade.get("strategy")
        if strategy in strategies:
            reward = trade.get("pnl", 0)
            strategy_rewards[strategy].append(reward)

            # 归一化奖励到[0,1]
            normalized = max(0, min(1, reward / 0.01))  # 假设1%为最大奖励
            strategy_returns[strategy].append(normalized)

    # 计算平均奖励
    avg_rewards = {}
    for s in strategies:
        if strategy_returns[s]:
            avg_rewards[s] = np.mean(strategy_returns[s])
        else:
            avg_rewards[s] = 0.5  # 默认中性奖励

    return avg_rewards


def main():
    parser = argparse.ArgumentParser(description="LinUCB权重优化")
    parser.add_argument("--history", required=True, help="历史交易记录JSON文件路径")
    parser.add_argument("--strategies", required=True, help="策略列表(JSON数组)")
    parser.add_argument("--alpha", type=float, default=1.0, help="探索参数")
    parser.add_argument("--iterations", type=int, default=1000, help="优化迭代次数")

    args = parser.parse_args()

    try:
        strategies = json.loads(args.strategies)

        if not isinstance(strategies, list):
            logger.info((json.dumps({)
                "status": "error",
                "message": "strategies必须是列表格式"
            }, ensure_ascii=False))
            sys.exit(1)

        if not strategies:
            logger.info((json.dumps({)
                "status": "error",
                "message": "策略列表不能为空"
            }, ensure_ascii=False))
            sys.exit(1)

        # 加载历史数据
        history = load_history(args.history)

        if len(history) < 10:
            logger.info((json.dumps({)
                "status": "warning",
                "message": f"历史记录不足({len(history)}条)，建议至少100条以获得更好效果",
                "weights": {s: 1.0/len(strategies) for s in strategies}
            }, ensure_ascii=False))
            sys.exit(0)

        # 提取奖励
        strategy_avg_rewards = extract_rewards(history, strategies)

        # 初始化LinUCB（V4.5增强：特征维度14，加入订单簿斜率、Volume Delta等微观结构特征）
        linucb = LinUCB(
            num_arms=len(strategies),
            alpha=args.alpha,
            feature_dim=14  # V4.5：14维特征
        )

        # 模拟训练（使用历史交易）
        for trade in history:
            strategy = trade.get("strategy")
            if strategy not in strategies:
                continue

            arm = strategies.index(strategy)
            market_state = trade.get("market_state", {})
            reward = strategy_avg_rewards[strategy]

            linucb.update(arm, reward, market_state)

        # 获取优化后的权重
        weights = linucb.get_weights()

        output = {
            "status": "success",
            "optimized_weights": {s: w for s, w in zip(strategies, weights)},
            "strategy_performance": strategy_avg_rewards,
            "iterations": len(history),
            "alpha": args.alpha,
            "strategy_counts": linucb.counts.tolist()
        }

        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except FileNotFoundError:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"历史记录文件未找到: {args.history}"
        }, ensure_ascii=False))
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"JSON解析失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"优化失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
