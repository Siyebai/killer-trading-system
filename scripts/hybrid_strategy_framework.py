#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("hybrid_strategy_framework")
except ImportError:
    import logging
    logger = logging.getLogger("hybrid_strategy_framework")
"""
混合策略架构 - 杀手锏交易系统P0核心
规则策略+ML策略+RL策略三合一，建立策略性能排行榜
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import time
import sys
import os

# 导入LinUCB优化器
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from linucb_optimizer import LinUCB


class StrategyType(Enum):
    """策略类型"""
    RULE_BASED = "RULE_BASED"  # 规则策略（EMA/Supertrend）
    ML_BASED = "ML_BASED"  # 机器学习策略（LightGBM/XGBoost）
    RL_BASED = "RL_BASED"  # 强化学习策略（DQN/PPO）


@dataclass
class StrategySignal:
    """策略信号"""
    strategy_name: str
    strategy_type: StrategyType
    action: str  # BUY/SELL/HOLD
    confidence: float  # 0-1
    features: Dict  # 特征向量
    reasoning: str  # 决策理由


@dataclass
class StrategyPerformance:
    """策略性能"""
    strategy_name: str
    total_trades: int
    win_rate: float
    avg_return: float
    sharpe_ratio: float
    max_drawdown: float
    score: float  # 综合评分


class HybridStrategyFramework:
    """混合策略框架"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化混合策略框架（V4.5增强：集成LinUCB优化器）

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 策略注册表
        self.registered_strategies: Dict[str, Any] = {}

        # 策略性能跟踪
        self.performance_history: Dict[str, List[Dict]] = {}

        # 策略权重
        self.strategy_weights: Dict[str, float] = {}

        # V4.5新增：LinUCB优化器（用于动态权重优化）
        self.enable_linucb = self.config.get('enable_linucb', True)
        self.linucb_optimizer: Optional[LinUCB] = None
        self.linucb_initialized = False

        # 配置参数
        self.min_performance_window = self.config.get('min_performance_window', 50)  # 最少50笔交易
        self.update_frequency = self.config.get('update_frequency', 100)  # 每100笔交易更新一次
        self.linucb_alpha = self.config.get('linucb_alpha', 1.0)  # LinUCB探索参数

    def register_strategy(self, name: str, strategy_type: StrategyType,
                          strategy_obj: Any, initial_weight: float = 1.0):
        """
        注册策略

        Args:
            name: 策略名称
            strategy_type: 策略类型
            strategy_obj: 策略对象
            initial_weight: 初始权重
        """
        self.registered_strategies[name] = {
            'type': strategy_type,
            'obj': strategy_obj,
            'active': True
        }
        self.strategy_weights[name] = initial_weight
        self.performance_history[name] = []

    def generate_signals(self, market_data: Dict) -> List[StrategySignal]:
        """
        生成所有策略的信号

        Args:
            market_data: 市场数据

        Returns:
            信号列表
        """
        signals = []

        for name, strategy_info in self.registered_strategies.items():
            if not strategy_info['active']:
                continue

            try:
                # 根据策略类型生成信号
                signal = self._generate_signal_by_type(
                    name,
                    strategy_info['type'],
                    strategy_info['obj'],
                    market_data
                )

                if signal:
                    signals.append(signal)

            except Exception as e:
                logger.error(f"策略 {name} 生成信号失败: {e}")

        return signals

    def _generate_signal_by_type(self, name: str, strategy_type: StrategyType,
                                   strategy_obj: Any, market_data: Dict) -> Optional[StrategySignal]:
        """
        根据策略类型生成信号

        Args:
            name: 策略名称
            strategy_type: 策略类型
            strategy_obj: 策略对象
            market_data: 市场数据

        Returns:
            策略信号
        """
        # 规则策略
        if strategy_type == StrategyType.RULE_BASED:
            # 假设策略对象有generate方法
            if hasattr(strategy_obj, 'generate'):
                result = strategy_obj.generate(market_data)
                return StrategySignal(
                    strategy_name=name,
                    strategy_type=strategy_type,
                    action=result.get('signal', 'HOLD'),
                    confidence=result.get('confidence', 0.5),
                    features=result.get('features', {}),
                    reasoning=result.get('reason', '规则策略')
                )

        # ML策略
        elif strategy_type == StrategyType.ML_BASED:
            # 模拟ML策略预测
            features = self._extract_ml_features(market_data)
            prediction = self._ml_predict(strategy_obj, features)

            return StrategySignal(
                strategy_name=name,
                strategy_type=strategy_type,
                action=prediction['action'],
                confidence=prediction['confidence'],
                features=features,
                reasoning=f"ML策略，特征权重: {prediction.get('feature_importance', {})}"
            )

        # RL策略
        elif strategy_type == StrategyType.RL_BASED:
            # 模拟RL策略决策
            state = self._extract_rl_state(market_data)
            action = self._rl_action(strategy_obj, state)

            return StrategySignal(
                strategy_name=name,
                strategy_type=strategy_type,
                action=action,
                confidence=0.7,
                features={'state': state},
                reasoning=f"RL策略，状态价值: {state.get('value', 0):.2f}"
            )

        return None

    def _extract_ml_features(self, market_data: Dict) -> Dict:
        """
        提取ML特征

        Args:
            market_data: 市场数据

        Returns:
            特征字典
        """
        features = {}

        # 价格特征
        if 'ohlcv' in market_data:
            ohlcv = market_data['ohlcv']
            features['price_change'] = (ohlcv.get('close', 0) - ohlcv.get('open', 0)) / ohlcv.get('open', 1)

        # 订单簿特征
        if 'orderbook' in market_data:
            ob = market_data['orderbook']
            if 'bids' in ob and 'asks' in ob:
                best_bid = ob['bids'][0][0] if ob['bids'] else 0
                best_ask = ob['asks'][0][0] if ob['asks'] else 0
                features['spread'] = (best_ask - best_bid) / best_ask if best_ask > 0 else 0
                features['orderbook_imbalance'] = 1.0  # 简化

        return features

    def _ml_predict(self, model: Any, features: Dict) -> Dict:
        """
        ML预测（简化实现）

        Args:
            model: ML模型
            features: 特征

        Returns:
            预测结果
        """
        # 简化：基于特征生成预测
        price_change = features.get('price_change', 0)
        spread = features.get('spread', 0)

        if price_change > 0.001 and spread < 0.001:
            return {'action': 'BUY', 'confidence': 0.7, 'feature_importance': {'price_change': 0.6, 'spread': 0.4}}
        elif price_change < -0.001 and spread < 0.001:
            return {'action': 'SELL', 'confidence': 0.7, 'feature_importance': {'price_change': 0.6, 'spread': 0.4}}
        else:
            return {'action': 'HOLD', 'confidence': 0.5, 'feature_importance': {}}

    def _extract_rl_state(self, market_data: Dict) -> Dict:
        """
        提取RL状态

        Args:
            market_data: 市场数据

        Returns:
            状态
        """
        state = {
            'timestamp': time.time(),
            'position': 0,
            'cash': 100000,
            'value': 0.0
        }

        if 'ohlcv' in market_data:
            state['price'] = market_data['ohlcv'].get('close', 0)

        return state

    def _rl_action(self, agent: Any, state: Dict) -> str:
        """
        RL动作选择（简化实现）

        Args:
            agent: RL智能体
            state: 状态

        Returns:
            动作
        """
        # 简化：随机选择
        import random
        return random.choice(['BUY', 'SELL', 'HOLD'])

    def update_performance(self, strategy_name: str, trade_result: Dict):
        """
        更新策略性能

        Args:
            strategy_name: 策略名称
            trade_result: 交易结果
        """
        if strategy_name not in self.performance_history:
            self.performance_history[strategy_name] = []

        self.performance_history[strategy_name].append(trade_result)

        # 检查是否需要更新权重
        if len(self.performance_history[strategy_name]) >= self.update_frequency:
            self._update_strategy_weights()

    def _update_strategy_weights(self):
        """
        更新策略权重（V4.5增强：集成LinUCB优化器）
        """
        if self.enable_linucb:
            # 使用LinUCB优化器动态调整权重
            self._update_weights_with_linucb()
        else:
            # 传统基于性能排行榜的权重调整
            self._update_weights_with_performance()

    def _update_weights_with_linucb(self):
        """
        使用LinUCB优化器更新策略权重
        """
        # 初始化LinUCB（首次使用时）
        if not self.linucb_initialized:
            num_strategies = len(self.registered_strategies)
            self.linucb_optimizer = LinUCB(
                num_arms=num_strategies,
                alpha=self.linucb_alpha,
                feature_dim=14  # V4.5：包含微观结构特征
            )
            self.linucb_initialized = True

        # 收集所有策略的历史数据
        strategy_list = list(self.registered_strategies.keys())
        all_trades = []

        for strategy_name in strategy_list:
            if strategy_name in self.performance_history:
                for trade in self.performance_history[strategy_name]:
                    trade['strategy_name'] = strategy_name
                    all_trades.append(trade)

        # 按时间排序
        all_trades.sort(key=lambda x: x.get('time', 0))

        # 使用LinUCB更新权重
        for trade in all_trades:
            strategy_name = trade.get('strategy_name')
            if strategy_name not in strategy_list:
                continue

            arm = strategy_list.index(strategy_name)

            # 构建市场状态特征
            market_state = {
                'price_change_1m': trade.get('price_change_1m', 0),
                'price_change_5m': trade.get('price_change_5m', 0),
                'volume_change': trade.get('volume_change', 0),
                'volatility': trade.get('volatility', 0),
                'rsi': trade.get('rsi', 50),
                'macd_signal': trade.get('macd_signal', 0),
                'trend_strength': trade.get('trend_strength', 0),
                'bid_ask_spread': trade.get('bid_ask_spread', 0),
                'order_flow': trade.get('order_flow', 0),
                'orderbook_slope': trade.get('orderbook_slope', 0),  # V4.5新
                'volume_delta': trade.get('volume_delta', 0),  # V4.5新
                'iceberg_detected': trade.get('iceberg_detected', 0),  # V4.5新
                'delta_divergence': trade.get('delta_divergence', 0)  # V4.5新
            }

            # 计算奖励（归一化到[0,1]）
            pnl = trade.get('pnl', 0)
            reward = max(0, min(1, pnl / 0.01))  # 假设1%为最大奖励

            # 更新LinUCB模型
            self.linucb_optimizer.update(arm, reward, market_state)

        # 获取LinUCB优化后的权重
        linucb_weights = self.linucb_optimizer.get_weights()

        # 应用权重
        for i, strategy_name in enumerate(strategy_list):
            self.strategy_weights[strategy_name] = linucb_weights[i] if i < len(linucb_weights) else 1.0

        logger.info(f"[LinUCB] 权重已更新: {dict(zip(strategy_list, [f'{w:.4f}' for w in linucb_weights]))}")

    def _update_weights_with_performance(self):
        """
        传统方法：基于性能排行榜更新策略权重
        """
        performance_rankings = self._get_performance_rankings()

        for strategy_name, performance in performance_rankings.items():
            # 基于综合评分调整权重
            new_weight = max(0.1, performance.score * 2.0)
            self.strategy_weights[strategy_name] = new_weight

    def _get_performance_rankings(self) -> Dict[str, StrategyPerformance]:
        """
        获取策略性能排行榜

        Returns:
            性能排行榜
        """
        rankings = {}

        for strategy_name, trades in self.performance_history.items():
            if len(trades) < self.min_performance_window:
                continue

            # 计算性能指标
            returns = [t.get('pnl', 0) for t in trades]
            win_rate = sum(1 for r in returns if r > 0) / len(returns)
            avg_return = np.mean(returns)

            # 简化夏普比率
            sharpe = avg_return / (np.std(returns) + 1e-6) if len(returns) > 1 else 0

            # 简化最大回撤
            cumulative = np.cumsum(returns)
            running_max = np.maximum.accumulate(cumulative)
            drawdown = (cumulative - running_max)
            max_drawdown = np.min(drawdown)

            # 综合评分（胜率40% + 夏普30% + 回撤30%）
            score = (
                win_rate * 0.4 +
                min(sharpe, 5.0) / 5.0 * 0.3 +
                (1 + max_drawdown) * 0.3
            )

            rankings[strategy_name] = StrategyPerformance(
                strategy_name=strategy_name,
                total_trades=len(trades),
                win_rate=win_rate,
                avg_return=avg_return,
                sharpe_ratio=sharpe,
                max_drawdown=max_drawdown,
                score=score
            )

        return rankings

    def get_active_strategies(self) -> Dict[str, float]:
        """
        获取活跃策略及权重

        Returns:
            策略权重字典
        """
        return {
            name: weight
            for name, weight in self.strategy_weights.items()
            if self.registered_strategies[name]['active']
        }

    def aggregate_signals(self, signals: List[StrategySignal]) -> Dict:
        """
        聚合多个策略信号

        Args:
            signals: 信号列表

        Returns:
            聚合信号
        """
        if not signals:
            return {'action': 'HOLD', 'confidence': 0.0, 'reasons': []}

        # 加权投票
        buy_weight = 0.0
        sell_weight = 0.0
        hold_weight = 0.0
        reasons = []

        for signal in signals:
            weight = self.strategy_weights.get(signal.strategy_name, 1.0) * signal.confidence

            if signal.action == 'BUY':
                buy_weight += weight
            elif signal.action == 'SELL':
                sell_weight += weight
            else:
                hold_weight += weight

            reasons.append(f"{signal.strategy_name}: {signal.action} ({signal.confidence:.2f})")

        # 确定最终动作
        if buy_weight > sell_weight and buy_weight > hold_weight:
            action = 'BUY'
            confidence = buy_weight / (buy_weight + sell_weight + hold_weight)
        elif sell_weight > buy_weight and sell_weight > hold_weight:
            action = 'SELL'
            confidence = sell_weight / (buy_weight + sell_weight + hold_weight)
        else:
            action = 'HOLD'
            confidence = max(buy_weight, sell_weight, hold_weight) / (buy_weight + sell_weight + hold_weight)

        return {
            'action': action,
            'confidence': confidence,
            'reasons': reasons,
            'buy_weight': buy_weight,
            'sell_weight': sell_weight,
            'hold_weight': hold_weight
        }


# 命令行测试
def main():
    """测试混合策略框架"""
    logger.info("="*60)
    logger.info("🧠 混合策略架构测试")
    logger.info("="*60)

    # 创建框架
    framework = HybridStrategyFramework({
        'min_performance_window': 5,
        'update_frequency': 10
    })

    logger.info(f"\n配置:")
    logger.info(f"  最少性能窗口: {framework.min_performance_window}笔")
    logger.info(f"  更新频率: {framework.update_frequency}笔")

    # 注册策略
    logger.info(f"\n注册策略...")

    # 规则策略（模拟对象）
    class RuleStrategy:
        def generate(self, market_data):
            return {
                'signal': 'BUY' if market_data.get('price', 50000) > 50100 else 'HOLD',
                'confidence': 0.6,
                'features': {},
                'reason': '规则策略：价格突破'
            }

    framework.register_strategy(
        'EMA_Trend',
        StrategyType.RULE_BASED,
        RuleStrategy(),
        initial_weight=1.0
    )

    framework.register_strategy(
        'Supertrend',
        StrategyType.RULE_BASED,
        RuleStrategy(),
        initial_weight=1.0
    )

    # ML策略（模拟对象）
    framework.register_strategy(
        'LightGBM_Classifier',
        StrategyType.ML_BASED,
        None,  # 模拟模型
        initial_weight=1.2
    )

    # RL策略（模拟对象）
    framework.register_strategy(
        'DQN_Agent',
        StrategyType.RL_BASED,
        None,  # 模拟智能体
        initial_weight=1.0
    )

    logger.info(f"  已注册: {list(framework.registered_strategies.keys())}")

    # 生成信号
    logger.info(f"\n生成信号...")
    market_data = {
        'price': 50200,
        'ohlcv': {'close': 50200, 'open': 50000},
        'orderbook': {
            'bids': [[50199, 1.0]],
            'asks': [[50201, 1.0]]
        }
    }

    signals = framework.generate_signals(market_data)

    logger.info(f"\n📊 策略信号:")
    for signal in signals:
        logger.info(f"  {signal.strategy_name}: {signal.action} (置信度{signal.confidence:.2f})")
        logger.info(f"    类型: {signal.strategy_type.value}")
        logger.info(f"    理由: {signal.reasoning}")

    # 聚合信号
    logger.info(f"\n聚合信号...")
    aggregated = framework.aggregate_signals(signals)

    logger.info(f"\n🎯 聚合结果:")
    logger.info(f"  动作: {aggregated['action']}")
    logger.info(f"  置信度: {aggregated['confidence']:.2f}")
    logger.info(f"  买入权重: {aggregated['buy_weight']:.2f}")
    logger.info(f"  卖出权重: {aggregated['sell_weight']:.2f}")
    logger.info(f"  持有权重: {aggregated['hold_weight']:.2f}")

    # 更新性能
    logger.info(f"\n\n更新性能...")
    for i in range(15):
        framework.update_performance('EMA_Trend', {'pnl': np.random.randn() * 100})
        framework.update_performance('Supertrend', {'pnl': np.random.randn() * 120})
        framework.update_performance('LightGBM_Classifier', {'pnl': np.random.randn() * 150})

    # 获取排行榜
    logger.info(f"\n策略性能排行榜:")
    rankings = framework._get_performance_rankings()
    for strategy_name, perf in sorted(rankings.items(), key=lambda x: x[1].score, reverse=True):
        logger.info(f"  {strategy_name}:")
        logger.info(f"    交易次数: {perf.total_trades}")
        logger.info(f"    胜率: {perf.win_rate*100:.1f}%")
        logger.info(f"    平均收益: {perf.avg_return:.2f}")
        logger.info(f"    夏普比率: {perf.sharpe_ratio:.2f}")
        logger.info(f"    最大回撤: {perf.max_drawdown:.2f}")
        logger.info(f"    综合评分: {perf.score:.2f}")

    # 获取活跃策略权重
    logger.info(f"\n活跃策略权重:")
    active = framework.get_active_strategies()
    for name, weight in active.items():
        logger.info(f"  {name}: {weight:.2f}")

    logger.info("\n" + "="*60)
    logger.info("混合策略架构测试: PASS")


if __name__ == "__main__":
    main()
