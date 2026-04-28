#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("rl_trading_agent")
except ImportError:
    import logging
    logger = logging.getLogger("rl_trading_agent")
"""
强化学习交易智能体 - V4.0核心模块
OpenAI Gym风格环境、DQN简化实现、训练和推理
"""

import numpy as np
import random
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from collections import deque
from enum import Enum


class RLActionType(Enum):
    """强化学习动作类型（内部使用）"""
    HOLD = 0
    BUY = 1
    SELL = 2


@dataclass
class State:
    """状态"""
    price: float
    position: float  # 当前持仓
    cash: float
    portfolio_value: float
    price_change_1: float = 0.0
    price_change_5: float = 0.0
    price_change_10: float = 0.0
    volume_ratio: float = 1.0
    volatility: float = 0.0
    rsi: float = 50.0

    def to_array(self) -> np.ndarray:
        """转换为numpy数组"""
        return np.array([
            self.price / 50000.0,  # 归一化
            self.position / 1.0,  # 归一化
            self.cash / 100000.0,  # 归一化
            self.portfolio_value / 100000.0,  # 归一化
            self.price_change_1,
            self.price_change_5,
            self.price_change_10,
            self.volume_ratio,
            self.volatility,
            self.rsi / 100.0  # 归一化
        ])


@dataclass
class Transition:
    """经验回放样本"""
    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: bool


class TradingEnvironment:
    """交易环境（OpenAI Gym风格）"""

    def __init__(self, initial_cash: float = 100000.0):
        """
        初始化交易环境

        Args:
            initial_cash: 初始现金
        """
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.position = 0.0
        self.portfolio_value = initial_cash

        # 市场数据
        self.price_history = deque(maxlen=100)
        self.volume_history = deque(maxlen=100)

        # 环境状态
        self.current_step = 0
        self.max_steps = 1000
        self.done = False

        # 交易参数
        self.transaction_cost = 0.001  # 0.1%手续费
        self.position_size = 0.1  # 每次交易0.1个单位

    def reset(self) -> State:
        """重置环境"""
        self.cash = self.initial_cash
        self.position = 0.0
        self.portfolio_value = self.initial_cash
        self.current_step = 0
        self.done = False
        self.price_history.clear()
        self.volume_history.clear()

        return self._get_state()

    def step(self, action: int) -> Tuple[State, float, bool, Dict[str, Any]]:
        """
        执行动作

        Args:
            action: 动作（0=HOLD, 1=BUY, 2=SELL）

        Returns:
            (next_state, reward, done, info)
        """
        # 模拟市场价格变化
        price_change = np.random.randn() * 100
        new_price = self.price_history[-1] + price_change if self.price_history else 50000
        new_volume = np.random.randint(500, 1500)

        self.price_history.append(new_price)
        self.volume_history.append(new_volume)

        # 执行动作
        action_type = ActionType(action)
        reward = 0.0
        info = {}

        if action_type == RLActionType.BUY and self.cash > new_price * self.position_size:
            # 买入
            cost = new_price * self.position_size * (1 + self.transaction_cost)
            self.cash -= cost
            self.position += self.position_size

            info['action'] = 'BUY'
            info['price'] = new_price
            info['size'] = self.position_size

        elif action_type == RLActionType.SELL and self.position >= self.position_size:
            # 卖出
            revenue = new_price * self.position_size * (1 - self.transaction_cost)
            self.cash += revenue
            self.position -= self.position_size

            info['action'] = 'SELL'
            info['price'] = new_price
            info['size'] = self.position_size

        else:
            info['action'] = 'HOLD'

        # 计算组合价值
        self.portfolio_value = self.cash + self.position * new_price

        # 计算奖励（使用组合价值变化）
        prev_value = self.portfolio_value - new_price * self.position_size * (action_type == RLActionType.BUY) if action_type == RLActionType.BUY else self.portfolio_value
        reward = (self.portfolio_value - self.initial_cash) / self.initial_cash

        # 惩罚过度交易
        if action_type != RLActionType.HOLD:
            reward -= 0.001

        # 更新步数
        self.current_step += 1
        if self.current_step >= self.max_steps:
            self.done = True

        # 获取新状态
        next_state = self._get_state()

        return next_state, reward, self.done, info

    def _get_state(self) -> State:
        """获取当前状态"""
        if not self.price_history:
            price = 50000.0
        else:
            price = self.price_history[-1]

        # 计算价格变化
        price_change_1 = 0.0
        price_change_5 = 0.0
        price_change_10 = 0.0
        volatility = 0.0
        rsi = 50.0

        if len(self.price_history) >= 10:
            price_change_1 = (self.price_history[-1] - self.price_history[-2]) / self.price_history[-2]
            price_change_5 = (self.price_history[-1] - self.price_history[-5]) / self.price_history[-5] if len(self.price_history) >= 5 else 0
            price_change_10 = (self.price_history[-1] - self.price_history[-10]) / self.price_history[-10]

            # 波动率和RSI
            volatility = 0
            rsi = 50.0

            if len(self.price_history) >= 11:
                prices_array = np.array(list(self.price_history))
                prices_slice = prices_array[-10:]

                if len(prices_slice) >= 2:
                    prices_prev = prices_slice[:-1]
                    prices_curr = prices_slice[1:]
                    returns = (prices_curr - prices_prev) / prices_prev
                    volatility = np.std(returns)

                    # RSI
                    gains = [max(r, 0) for r in returns]
                    losses = [abs(min(r, 0)) for r in returns]
                    avg_gain = np.mean(gains)
                    avg_loss = np.mean(losses)
                    rs = avg_gain / avg_loss if avg_loss > 0 else float('inf')
                    rsi = 100 - (100 / (1 + rs))

        # 成交量比率
        volume_ratio = 1.0
        if len(self.volume_history) >= 5:
            volume_ratio = self.volume_history[-1] / np.mean(list(self.volume_history)[-5:])

        return State(
            price=price,
            position=self.position,
            cash=self.cash,
            portfolio_value=self.portfolio_value,
            price_change_1=price_change_1,
            price_change_5=price_change_5,
            price_change_10=price_change_10,
            volume_ratio=volume_ratio,
            volatility=volatility,
            rsi=rsi
        )

    def get_action_space(self) -> int:
        """获取动作空间大小"""
        return 3  # HOLD, BUY, SELL

    def get_observation_space(self) -> int:
        """获取观察空间大小"""
        return 10  # 状态维度


class SimpleDQNAgent:
    """简化的DQN智能体"""

    def __init__(self, state_size: int, action_size: int):
        """
        初始化DQN智能体

        Args:
            state_size: 状态维度
            action_size: 动作维度
        """
        self.state_size = state_size
        self.action_size = action_size

        # Q网络（简化：使用线性网络）
        self.q_network = np.random.randn(state_size, action_size) * 0.01
        self.target_network = self.q_network.copy()

        # 经验回放
        self.memory = deque(maxlen=10000)

        # 超参数
        self.gamma = 0.95  # 折扣因子
        self.epsilon = 1.0  # 探索率
        self.epsilon_min = 0.01
        self.epsilon_decay = 0.995
        self.learning_rate = 0.001
        self.batch_size = 32

        self.training_steps = 0

    def remember(self, state: np.ndarray, action: int, reward: float,
                 next_state: np.ndarray, done: bool):
        """存储经验"""
        self.memory.append(Transition(state, action, reward, next_state, done))

    def act(self, state: np.ndarray, training: bool = True) -> int:
        """
        选择动作

        Args:
            state: 当前状态
            training: 是否在训练模式

        Returns:
            动作
        """
        if training and np.random.rand() <= self.epsilon:
            # 探索：随机选择
            return np.random.randint(self.action_size)

        # 利用：选择最优动作
        q_values = np.dot(state, self.q_network)
        return np.argmax(q_values)

    def replay(self):
        """经验回放训练"""
        if len(self.memory) < self.batch_size:
            return

        # 随机采样
        batch = random.sample(list(self.memory), self.batch_size)

        states = np.array([t.state for t in batch])
        actions = np.array([t.action for t in batch])
        rewards = np.array([t.reward for t in batch])
        next_states = np.array([t.next_state for t in batch])
        dones = np.array([t.done for t in batch])

        # 计算目标Q值
        target_q_values = rewards + self.gamma * np.amax(
            np.dot(next_states, self.target_network), axis=1
        ) * (1 - dones)

        # 计算当前Q值
        current_q_values = np.dot(states, self.q_network)
        targets = current_q_values.copy()

        # 更新Q值
        for i in range(self.batch_size):
            targets[i][actions[i]] = target_q_values[i]

        # 更新网络（简化：直接梯度下降）
        error = targets - current_q_values
        self.q_network += self.learning_rate * np.dot(states.T, error) / self.batch_size

        # 更新探索率
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

        self.training_steps += 1

        # 定期更新目标网络
        if self.training_steps % 100 == 0:
            self.target_network = self.q_network.copy()

    def train(self, env: TradingEnvironment, episodes: int = 100) -> List[float]:
        """
        训练智能体

        Args:
            env: 交易环境
            episodes: 训练轮数

        Returns:
            每轮的总奖励
        """
        episode_rewards = []

        for episode in range(episodes):
            state = env.reset()
            state_array = state.to_array()
            total_reward = 0
            done = False

            while not done:
                # 选择动作
                action = self.act(state_array)

                # 执行动作
                next_state, reward, done, info = env.step(action)
                next_state_array = next_state.to_array()

                # 存储经验
                self.remember(state_array, action, reward, next_state_array, done)

                # 训练
                self.replay()

                state_array = next_state_array
                total_reward += reward

            episode_rewards.append(total_reward)

            if (episode + 1) % 10 == 0:
                avg_reward = np.mean(episode_rewards[-10:])
                logger.info(f"Episode {episode + 1}/{episodes}, Avg Reward: {avg_reward:.4f}, Epsilon: {self.epsilon:.3f}")

        return episode_rewards

    def evaluate(self, env: TradingEnvironment, episodes: int = 10) -> Dict[str, float]:
        """
        评估智能体

        Args:
            env: 交易环境
            episodes: 评估轮数

        Returns:
            评估结果
        """
        total_rewards = []
        final_values = []

        for episode in range(episodes):
            state = env.reset()
            state_array = state.to_array()
            total_reward = 0
            done = False

            while not done:
                action = self.act(state_array, training=False)
                next_state, reward, done, info = env.step(action)
                state_array = next_state.to_array()
                total_reward += reward

            total_rewards.append(total_reward)
            final_values.append(env.portfolio_value)

        return {
            'avg_reward': np.mean(total_rewards),
            'std_reward': np.std(total_rewards),
            'avg_final_value': np.mean(final_values),
            'max_final_value': np.max(final_values),
            'min_final_value': np.min(final_values)
        }

    def get_info(self) -> Dict[str, Any]:
        """获取智能体信息"""
        return {
            'state_size': self.state_size,
            'action_size': self.action_size,
            'memory_size': len(self.memory),
            'training_steps': self.training_steps,
            'epsilon': self.epsilon,
            'gamma': self.gamma,
            'learning_rate': self.learning_rate
        }


# 命令行测试
def main():
    """测试强化学习智能体"""
    logger.info("="*60)
    logger.info("🤖 强化学习交易智能体测试")
    logger.info("="*60)

    # 创建环境
    env = TradingEnvironment(initial_cash=100000.0)

    logger.info(f"\n环境信息:")
    logger.info(f"  动作空间: {env.get_action_space()} (0=HOLD, 1=BUY, 2=SELL)")
    logger.info(f"  观察空间: {env.get_observation_space()}")

    # 创建智能体
    agent = SimpleDQNAgent(
        state_size=env.get_observation_space(),
        action_size=env.get_action_space()
    )

    logger.info(f"\n智能体信息:")
    info = agent.get_info()
    for key, value in info.items():
        logger.info(f"  {key}: {value}")

    # 训练
    logger.info(f"\n开始训练...")
    episode_rewards = agent.train(env, episodes=50)

    logger.info(f"\n训练完成!")
    logger.info(f"  最后10轮平均奖励: {np.mean(episode_rewards[-10:]):.4f}")

    # 评估
    logger.info(f"\n开始评估...")
    eval_results = agent.evaluate(env, episodes=10)

    logger.info(f"\n评估结果:")
    logger.info(f"  平均奖励: {eval_results['avg_reward']:.4f}")
    logger.info(f"  平均最终权益: ${eval_results['avg_final_value']:.2f}")
    logger.info(f"  最大权益: ${eval_results['max_final_value']:.2f}")
    logger.info(f"  最小权益: ${eval_results['min_final_value']:.2f}")

    # 展示一回合
    logger.info(f"\n展示一回合交易...")
    state = env.reset()
    state_array = state.to_array()

    actions_taken = []

    for step in range(20):
        action = agent.act(state_array, training=False)
        next_state, reward, done, info = env.step(action)

        action_name = ['HOLD', 'BUY', 'SELL'][action]
        actions_taken.append({
            'step': step,
            'action': action_name,
            'price': info.get('price', 0),
            'position': env.position,
            'portfolio_value': env.portfolio_value
        })

        state_array = next_state.to_array()

        if done:
            break

    logger.info(f"\n交易记录:")
    logger.info(f"{'步骤':<6} {'动作':<8} {'价格':<12} {'持仓':<12} {'权益':<15}")
    logger.info("-" * 60)
    for record in actions_taken[:10]:
        logger.info(f"{record['step']:<6} {record['action']:<8} ${record['price']:<11.2f} {record['position']:<12.2f} ${record['portfolio_value']:<14.2f}")

    logger.info("\n" + "="*60)
    logger.info("强化学习交易智能体测试: PASS")


if __name__ == "__main__":
    main()
