#!/usr/bin/env python3
"""
元学习控制器 - Phase 6 核心组件
使用PPO强化学习实现策略参数的在线自适应调整
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import time
import json

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("meta_controller")
except ImportError:
    import logging
    logger = logging.getLogger("meta_controller")

# 导入事件总线
try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False


class MarketState(Enum):
    """市场状态"""
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    LOW_LIQUIDITY = "low_liquidity"


@dataclass
class StateVector:
    """状态向量（元学习输入）"""
    # 市场特征
    market_state: MarketState
    volatility: float = 0.0
    liquidity_ratio: float = 0.0
    trend_strength: float = 0.0

    # 系统状态
    total_pnl: float = 0.0
    drawdown: float = 0.0
    position_risk: float = 0.0

    # 策略表现
    strategy_sharpe: float = 0.0
    strategy_win_rate: float = 0.0

    def to_numpy(self) -> np.ndarray:
        """转换为numpy数组"""
        return np.array([
            # 市场特征 (one-hot encoding)
            1.0 if self.market_state == MarketState.TRENDING else 0.0,
            1.0 if self.market_state == MarketState.RANGING else 0.0,
            1.0 if self.market_state == MarketState.VOLATILE else 0.0,
            1.0 if self.market_state == MarketState.LOW_LIQUIDITY else 0.0,
            self.volatility,
            self.liquidity_ratio,
            self.trend_strength,
            # 系统状态
            self.total_pnl / 10000.0,  # 归一化
            self.drawdown,
            self.position_risk,
            # 策略表现
            self.strategy_sharpe,
            self.strategy_win_rate
        ], dtype=np.float32)


@dataclass
class ActionVector:
    """动作向量（元学习输出）"""
    # 策略权重调整
    ma_trend_weight_delta: float = 0.0
    orderflow_weight_delta: float = 0.0
    volatility_weight_delta: float = 0.0
    rsi_weight_delta: float = 0.0

    # 风控参数调整
    stop_loss_multiplier_delta: float = 0.0
    position_size_multiplier_delta: float = 0.0

    # 交易频率调整
    scan_interval_delta: float = 0.0

    def clamp(self, limits: Dict[str, Tuple[float, float]]) -> None:
        """
        限制动作范围（安全走廊）

        Args:
            limits: 各参数的限制范围
        """
        # 第一层防御：参数校验
        self.ma_trend_weight_delta = np.clip(
            self.ma_trend_weight_delta, limits['ma_trend'][0], limits['ma_trend'][1]
        )
        self.orderflow_weight_delta = np.clip(
            self.orderflow_weight_delta, limits['orderflow'][0], limits['orderflow'][1]
        )
        self.volatility_weight_delta = np.clip(
            self.volatility_weight_delta, limits['volatility'][0], limits['volatility'][1]
        )
        self.rsi_weight_delta = np.clip(
            self.rsi_weight_delta, limits['rsi'][0], limits['rsi'][1]
        )
        self.stop_loss_multiplier_delta = np.clip(
            self.stop_loss_multiplier_delta, limits['stop_loss'][0], limits['stop_loss'][1]
        )
        self.position_size_multiplier_delta = np.clip(
            self.position_size_multiplier_delta, limits['position_size'][0], limits['position_size'][1]
        )
        self.scan_interval_delta = np.clip(
            self.scan_interval_delta, limits['scan_interval'][0], limits['scan_interval'][1]
        )

    def to_numpy(self) -> np.ndarray:
        """转换为numpy数组"""
        return np.array([
            self.ma_trend_weight_delta,
            self.orderflow_weight_delta,
            self.volatility_weight_delta,
            self.rsi_weight_delta,
            self.stop_loss_multiplier_delta,
            self.position_size_multiplier_delta,
            self.scan_interval_delta
        ], dtype=np.float32)


@dataclass
class Reward:
    """奖励信号"""
    sharpe_component: float = 0.0
    drawdown_penalty: float = 0.0
    win_rate_reward: float = 0.0
    total: float = 0.0

    def calculate(self, metrics: Dict) -> None:
        """
        计算奖励

        Args:
            metrics: 性能指标字典
        """
        try:
            # 第一层防御：参数校验
            sharpe = metrics.get('sharpe_ratio', 0.0)
            drawdown = metrics.get('drawdown', 0.0)
            win_rate = metrics.get('win_rate', 0.0)

            # 第二层防御：除零保护
            drawdown = max(0.01, drawdown)

            # Sharpe比率奖励
            self.sharpe_component = sharpe * 0.5

            # 最大回撤惩罚
            self.drawdown_penalty = -drawdown * 2.0

            # 胜率奖励
            self.win_rate_reward = (win_rate - 0.5) * 0.3

            # 总奖励
            self.total = self.sharpe_component + self.drawdown_penalty + self.win_rate_reward

        except Exception as e:
            logger.error(f"计算奖励异常: {e}")
            self.total = 0.0


class MetaController:
    """元学习控制器（基于PPO框架）"""

    def __init__(self,
                 state_dim: int = 12,
                 action_dim: int = 7,
                 learning_rate: float = 3e-4,
                 gamma: float = 0.99,
                 gae_lambda: float = 0.95,
                 clip_epsilon: float = 0.2):
        """
        初始化元学习控制器

        Args:
            state_dim: 状态向量维度
            action_dim: 动作向量维度
            learning_rate: 学习率
            gamma: 折扣因子
            gae_lambda: GAE参数
            clip_epsilon: PPO裁剪参数
        """
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.learning_rate = learning_rate
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_epsilon = clip_epsilon

        # 策略网络和价值网络（简化实现）
        self.policy_weights = np.random.randn(state_dim, action_dim) * 0.01
        self.value_weights = np.random.randn(state_dim, 1) * 0.01

        # 经验回放池
        self.states: List[np.ndarray] = []
        self.actions: List[np.ndarray] = []
        self.rewards: List[float] = []
        self.values: List[float] = []
        self.log_probs: List[float] = []
        self.dones: List[bool] = []

        # 训练统计
        self.update_count = 0
        self.episode_rewards: List[float] = []

        # 动作限制（安全走廊）
        self.action_limits = {
            'ma_trend': (-0.1, 0.1),
            'orderflow': (-0.1, 0.1),
            'volatility': (-0.1, 0.1),
            'rsi': (-0.1, 0.1),
            'stop_loss': (-0.2, 0.2),
            'position_size': (-0.2, 0.2),
            'scan_interval': (-5.0, 5.0)
        }

        logger.info("元学习控制器初始化完成")

    def select_action(self, state: StateVector) -> Tuple[ActionVector, float]:
        """
        选择动作（基于当前策略）

        Args:
            state: 状态向量

        Returns:
            (动作, 对数概率)
        """
        try:
            # 第一层防御：状态向量化
            state_array = state.to_numpy()
            state_array = state_array.reshape(1, -1)

            # 前向传播（简化）
            logits = np.dot(state_array, self.policy_weights).flatten()
            logits = np.clip(logits, -10, 10)  # 防止数值溢出

            # 添加高斯噪声（探索）
            logits += np.random.randn(self.action_dim) * 0.1

            # 计算动作（sigmoid激活，映射到[-1, 1]）
            action_values = np.tanh(logits)

            # 构建动作向量
            action = ActionVector(
                ma_trend_weight_delta=action_values[0],
                orderflow_weight_delta=action_values[1],
                volatility_weight_delta=action_values[2],
                rsi_weight_delta=action_values[3],
                stop_loss_multiplier_delta=action_values[4],
                position_size_multiplier_delta=action_values[5],
                scan_interval_delta=action_values[6]
            )

            # 应用安全走廊限制
            action.clamp(self.action_limits)

            # 计算对数概率（高斯分布）
            log_prob = -0.5 * np.sum(action_values ** 2)  # 简化

            # 估算价值
            value = np.dot(state_array, self.value_weights).flatten()[0]

            return action, log_prob, value

        except Exception as e:
            logger.error(f"选择动作异常: {e}")
            # 返回安全默认动作
            return ActionVector(), 0.0, 0.0

    def store_transition(self,
                        state: StateVector,
                        action: ActionVector,
                        reward: float,
                        value: float,
                        done: bool) -> None:
        """
        存储转换

        Args:
            state: 状态
            action: 动作
            reward: 奖励
            value: 价值估计
            done: 是否结束
        """
        try:
            self.states.append(state.to_numpy())
            self.actions.append(action.to_numpy())
            self.rewards.append(reward)
            self.values.append(value)
            self.dones.append(done)

        except Exception as e:
            logger.error(f"存储转换异常: {e}")

    def compute_gae(self) -> List[float]:
        """
        计算广义优势估计（GAE）

        Returns:
            优势列表
        """
        try:
            advantages = []
            gae = 0.0

            # 从后往前计算
            for t in reversed(range(len(self.rewards))):
                if t == len(self.rewards) - 1:
                    next_value = 0.0
                else:
                    next_value = self.values[t + 1]

                delta = self.rewards[t] + self.gamma * next_value - self.values[t]
                gae = delta + self.gamma * self.gae_lambda * (1.0 - float(self.dones[t])) * gae
                advantages.insert(0, gae)

            # 归一化
            advantages = np.array(advantages)
            advantages = (advantages - np.mean(advantages)) / (np.std(advantages) + 1e-8)

            return advantages.tolist()

        except Exception as e:
            logger.error(f"计算GAE异常: {e}")
            return [0.0] * len(self.rewards)

    def update(self) -> Dict:
        """
        更新策略网络

        Returns:
            训练统计信息
        """
        try:
            if len(self.states) < 32:  # 最小批次大小
                return {'update_count': 0, 'policy_loss': 0.0, 'value_loss': 0.0}

            # 第一层防御：数据准备
            states = np.array(self.states)
            actions = np.array(self.actions)
            values = np.array(self.values)
            advantages = self.compute_gae()
            returns = np.array(advantages) + np.array(values)

            # PPO更新（简化实现）
            # 实际实现需要使用PyTorch/TensorFlow

            # 计算策略梯度（简化）
            policy_loss = -np.mean(advantages)  # 极度简化

            # 计算价值损失（MSE）
            value_predictions = np.dot(states, self.value_weights).flatten()
            value_loss = np.mean((value_predictions - returns) ** 2)

            # 梯度更新（简化）
            lr = self.learning_rate
            self.policy_weights += lr * np.dot(states.T, advantages.reshape(-1, 1)) * 0.01
            self.value_weights += lr * np.dot(states.T, (returns - value_predictions).reshape(-1, 1)) * 0.01

            # 清空缓存
            self.clear_buffer()

            self.update_count += 1

            stats = {
                'update_count': self.update_count,
                'policy_loss': float(policy_loss),
                'value_loss': float(value_loss),
                'batch_size': len(self.states)
            }

            logger.debug(f"元控制器更新: {stats}")
            return stats

        except Exception as e:
            logger.error(f"更新策略异常: {e}")
            self.clear_buffer()
            return {'update_count': 0, 'policy_loss': 0.0, 'value_loss': 0.0}

    def clear_buffer(self) -> None:
        """清空经验缓冲区"""
        self.states.clear()
        self.actions.clear()
        self.rewards.clear()
        self.values.clear()
        self.dones.clear()

    def get_weights(self) -> Dict:
        """获取当前权重"""
        return {
            'policy_weights': self.policy_weights.tolist(),
            'value_weights': self.value_weights.tolist(),
            'update_count': self.update_count
        }

    def save(self, path: str) -> None:
        """保存模型"""
        try:
            data = self.get_weights()
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"元控制器模型已保存: {path}")
        except Exception as e:
            logger.error(f"保存模型异常: {e}")

    def load(self, path: str) -> None:
        """加载模型"""
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            self.policy_weights = np.array(data['policy_weights'])
            self.value_weights = np.array(data['value_weights'])
            self.update_count = data.get('update_count', 0)
            logger.info(f"元控制器模型已加载: {path}")
        except Exception as e:
            logger.error(f"加载模型异常: {e}")


if __name__ == "__main__":
    # 测试代码
    controller = MetaController()

    # 模拟训练
    for episode in range(10):
        state = StateVector(
            market_state=MarketState.TRENDING,
            volatility=0.02,
            liquidity_ratio=1.0,
            trend_strength=0.5,
            total_pnl=100.0,
            drawdown=0.05,
            position_risk=0.1,
            strategy_sharpe=1.5,
            strategy_win_rate=0.6
        )

        action, log_prob, value = controller.select_action(state)
        reward = Reward()
        reward.calculate({'sharpe_ratio': 1.5, 'drawdown': 0.05, 'win_rate': 0.6})

        controller.store_transition(state, action, reward.total, value, done=False)

        stats = controller.update()
        print(f"Episode {episode}: {stats}")

    # 保存模型
    controller.save("meta_controller_weights.json")
    print("\n模型已保存")
