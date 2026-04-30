# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("ml_signal_enhancer")
except ImportError:
    import logging
    logger = logging.getLogger("ml_signal_enhancer")
"""
机器学习信号增强 - V3.5核心模块
AI信号优化、特征工程、模型预测
"""

import json
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from collections import deque
import time


@dataclass
class Signal:
    """交易信号"""
    timestamp: float
    symbol: str
    action: str  # 'BUY', 'SELL', 'HOLD'
    confidence: float  # 0-1
    strategy: str
    raw_strength: float  # 原始信号强度
    enhanced_strength: float = 0.0  # 增强后信号强度
    features: Dict[str, float] = None  # 特征值

    def __post_init__(self):
        if self.features is None:
            self.features = {}


class FeatureExtractor:
    """特征提取器"""

    def __init__(self, window_size: int = 20):
        """
        初始化特征提取器

        Args:
            window_size: 滑动窗口大小
        """
        self.window_size = window_size
        self.price_history = deque(maxlen=window_size)
        self.volume_history = deque(maxlen=window_size)

    def update(self, price: float, volume: float):
        """更新历史数据"""
        self.price_history.append(price)
        self.volume_history.append(volume)

    def extract_features(self, current_price: float) -> Dict[str, float]:
        """
        提取特征

        Args:
            current_price: 当前价格

        Returns:
            特征字典
        """
        features = {}

        if len(self.price_history) < 3:
            return features

        prices = list(self.price_history)
        volumes = list(self.volume_history)

        # 基础特征
        features['price_return_1'] = (current_price - prices[-1]) / prices[-1] if prices[-1] > 0 else 0
        features['price_return_3'] = (current_price - prices[-3]) / prices[-3] if len(prices) >= 3 and prices[-3] > 0 else 0
        features['price_return_5'] = (current_price - prices[-min(5, len(prices))]) / prices[-min(5, len(prices))] if len(prices) >= 5 and prices[-min(5, len(prices))] > 0 else 0

        # 波动率特征
        returns = np.diff(prices) / np.array(prices[:-1])
        features['volatility_5'] = np.std(returns[-5:]) if len(returns) >= 5 else 0
        features['volatility_10'] = np.std(returns[-10:]) if len(returns) >= 10 else 0

        # 动量特征
        features['momentum_3'] = prices[-1] - prices[-3] if len(prices) >= 3 else 0
        features['momentum_5'] = prices[-1] - prices[-5] if len(prices) >= 5 else 0
        features['momentum_10'] = prices[-1] - prices[-10] if len(prices) >= 10 else 0

        # 趋势特征
        ma5 = np.mean(prices[-5:]) if len(prices) >= 5 else current_price
        ma10 = np.mean(prices[-10:]) if len(prices) >= 10 else current_price
        features['ma_diff_5_10'] = (ma5 - ma10) / ma10 if ma10 > 0 else 0

        # 成交量特征
        features['volume_ratio'] = volumes[-1] / np.mean(volumes[-5:]) if len(volumes) >= 5 else 1.0
        features['volume_trend'] = (volumes[-1] - volumes[-5]) / volumes[-5] if len(volumes) >= 5 and volumes[-5] > 0 else 0

        # RSI特征
        if len(prices) >= 14:
            gains = [max(r, 0) for r in returns]
            losses = [abs(min(r, 0)) for r in returns]
            avg_gain = np.mean(gains[-14:])
            avg_loss = np.mean(losses[-14:])
            rs = avg_gain / avg_loss if avg_loss > 0 else float('inf')
            features['rsi'] = 100 - (100 / (1 + rs))
        else:
            features['rsi'] = 50

        # 布林带位置
        if len(prices) >= 20:
            bb_mid = np.mean(prices[-20:])
            bb_std = np.std(prices[-20:])
            bb_upper = bb_mid + 2 * bb_std
            bb_lower = bb_mid - 2 * bb_std
            features['bb_position'] = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5
        else:
            features['bb_position'] = 0.5

        return features


class MLSignalEnhancer:
    """机器学习信号增强器"""

    def __init__(self, model_type: str = "simple_ensemble"):
        """
        初始化信号增强器

        Args:
            model_type: 模型类型
        """
        self.model_type = model_type
        self.feature_extractor = FeatureExtractor(window_size=20)
        self.signal_history = deque(maxlen=100)  # 信号历史

        # 简化模型权重（实际中应使用训练好的模型）
        self.model_weights = {
            'price_return_1': 2.0,
            'price_return_3': 1.5,
            'volatility_5': -1.0,
            'momentum_3': 1.8,
            'ma_diff_5_10': 2.5,
            'rsi': 1.2,
            'bb_position': 1.5,
            'volume_ratio': 0.8
        }

    def update_market_data(self, price: float, volume: float):
        """更新市场数据"""
        self.feature_extractor.update(price, volume)

    def enhance_signal(self, signal: Signal) -> Signal:
        """
        增强信号

        Args:
            signal: 原始信号

        Returns:
            增强后的信号
        """
        # 提取特征
        features = self.feature_extractor.extract_features(signal.raw_strength or 0)

        # 计算增强分数
        enhanced_score = self._calculate_enhanced_score(features, signal.action)

        # 调整置信度
        adjusted_confidence = self._adjust_confidence(signal.confidence, enhanced_score)

        # 更新信号
        signal.features = features
        signal.enhanced_strength = enhanced_score
        signal.confidence = max(0, min(1, adjusted_confidence))

        # 记录历史
        self.signal_history.append(signal)

        return signal

    def _calculate_enhanced_score(self, features: Dict[str, float], action: str) -> float:
        """
        计算增强分数

        Args:
            features: 特征字典
            action: 信号动作

        Returns:
            增强分数
        """
        score = 0.0

        for feature_name, weight in self.model_weights.items():
            feature_value = features.get(feature_name, 0)

            # 根据动作调整权重方向
            if action == 'BUY':
                # 买入：正特征加分，负特征减分
                score += feature_value * weight
            elif action == 'SELL':
                # 卖出：正特征减分，负特征加分
                score -= feature_value * weight

        # 归一化到 -1 到 1
        score = max(-1, min(1, score / 10))

        return score

    def _adjust_confidence(self, original_confidence: float,
                          enhanced_score: float) -> float:
        """
        调整置信度

        Args:
            original_confidence: 原始置信度
            enhanced_score: 增强分数

        Returns:
            调整后的置信度
        """
        # 增强分数绝对值越大，置信度越高
        score_abs = abs(enhanced_score)

        # 基础置信度
        adjusted = original_confidence * 0.6 + score_abs * 0.4

        return adjusted

    def get_feature_importance(self) -> Dict[str, float]:
        """
        获取特征重要性

        Returns:
            特征重要性字典
        """
        return self.model_weights.copy()

    def predict_signal(self, features: Dict[str, float]) -> Tuple[str, float]:
        """
        直接预测信号

        Args:
            features: 特征字典

        Returns:
            (动作, 置信度)
        """
        # 计算买入和卖出分数
        buy_score = self._calculate_enhanced_score(features, 'BUY')
        sell_score = self._calculate_enhanced_score(features, 'SELL')

        if abs(buy_score) > abs(sell_score) and buy_score > 0:
            confidence = min(1, abs(buy_score))
            return 'BUY', confidence
        elif abs(sell_score) > abs(buy_score) and sell_score > 0:
            confidence = min(1, abs(sell_score))
            return 'SELL', confidence
        else:
            return 'HOLD', 0.5

    def get_model_summary(self) -> Dict[str, Any]:
        """获取模型摘要"""
        return {
            'model_type': self.model_type,
            'feature_count': len(self.model_weights),
            'signal_history_size': len(self.signal_history),
            'feature_weights': self.model_weights
        }


# 命令行测试
def main():
    """测试机器学习信号增强"""
    logger.info("="*60)
    logger.info("🤖 机器学习信号增强测试")
    logger.info("="*60)

    # 创建增强器
    enhancer = MLSignalEnhancer(model_type="simple_ensemble")

    # 更新一些市场数据
    base_price = 50000
    for i in range(20):
        price = base_price + np.random.randn() * 50
        volume = np.random.uniform(100, 500)
        enhancer.update_market_data(price, volume)

    # 测试信号增强
    logger.info("\n测试信号增强:")

    test_signals = [
        Signal(timestamp=time.time(), symbol="BTCUSDT",
               action="BUY", confidence=0.7, strategy="MA_CROSS",
               raw_strength=0.8),
        Signal(timestamp=time.time(), symbol="BTCUSDT",
               action="SELL", confidence=0.6, strategy="RSI",
               raw_strength=-0.6),
        Signal(timestamp=time.time(), symbol="BTCUSDT",
               action="BUY", confidence=0.5, strategy="VOLATILITY",
               raw_strength=0.3),
    ]

    for signal in test_signals:
        enhanced = enhancer.enhance_signal(signal)

        logger.info(f"\n原始信号:")
        logger.info(f"  动作: {signal.action}")
        logger.info(f"  置信度: {signal.confidence:.3f}")
        logger.info(f"  原始强度: {signal.raw_strength:.3f}")

        logger.info(f"\n增强后信号:")
        logger.info(f"  动作: {enhanced.action}")
        logger.info(f"  置信度: {enhanced.confidence:.3f}")
        logger.info(f"  增强强度: {enhanced.enhanced_strength:.3f}")

        logger.info(f"\n特征值:")
        for feat_name, feat_val in list(enhanced.features.items())[:5]:
            logger.info(f"  {feat_name}: {feat_val:.4f}")

    # 测试直接预测
    logger.info("\n\n直接预测:")
    features = {
        'price_return_1': 0.002,
        'price_return_3': 0.005,
        'volatility_5': 0.01,
        'momentum_3': 100,
        'ma_diff_5_10': 0.008,
        'rsi': 65,
        'bb_position': 0.7,
        'volume_ratio': 1.2
    }

    action, confidence = enhancer.predict_signal(features)
    logger.info(f"  预测动作: {action}")
    logger.info(f"  预测置信度: {confidence:.3f}")

    # 模型摘要
    logger.info("\n\n模型摘要:")
    summary = enhancer.get_model_summary()
    logger.info(f"  模型类型: {summary['model_type']}")
    logger.info(f"  特征数量: {summary['feature_count']}")
    logger.info(f"  历史信号数: {summary['signal_history_size']}")

    logger.info("\n特征权重:")
    for feat, weight in summary['feature_weights'].items():
        logger.info(f"  {feat}: {weight:.2f}")

    logger.info("\n" + "="*60)
    logger.info("机器学习信号增强测试: PASS")


if __name__ == "__main__":
    main()
