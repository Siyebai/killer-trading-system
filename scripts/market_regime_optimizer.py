#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("market_regime_optimizer")
except ImportError:
    import logging
    logger = logging.getLogger("market_regime_optimizer")
"""
市场状态识别优化模块 - v1.0.3 P1级
解决市场状态识别滞后问题
核心策略：概率性状态预测、置信度动态调整、微观结构指标提前预警
"""

import argparse
import json
import sys
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import sqlite3
import time


class MarketRegime(Enum):
    """市场状态枚举"""
    STRONG_TREND_UP = "STRONG_TREND_UP"
    WEAK_TREND_UP = "WEAK_TREND_UP"
    STRONG_TREND_DOWN = "STRONG_TREND_DOWN"
    WEAK_TREND_DOWN = "WEAK_TREND_DOWN"
    RANGING_HIGH_VOL = "RANGING_HIGH_VOL"
    RANGING_LOW_VOL = "RANGING_LOW_VOL"


@dataclass
class RegimePrediction:
    """市场状态预测"""
    regime: MarketRegime
    confidence: float  # 置信度 [0, 1]
    probability: Dict[MarketRegime, float]  # 各状态概率
    early_warning: bool  # 是否提前预警
    warning_message: str  # 预警信息


class RegimeStateTracker:
    """市场状态跟踪器"""

    def __init__(self, min_stability_periods: int = 1):
        """
        初始化状态跟踪器

        Args:
            min_stability_periods: 最小稳定周期数（v1.0.3优化：从3降至1）
        """
        self.min_stability_periods = min_stability_periods
        self.history = []
        self.current_regime = None
        self.regime_duration = 0


class MarketRegimeOptimizer:
    """市场状态识别优化器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化市场状态识别优化器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 配置参数
        self.adx_threshold_strong = self.config.get('adx_threshold_strong', 30)
        self.adx_threshold_weak = self.config.get('adx_threshold_weak', 20)
        self.rsi_overbought = self.config.get('rsi_overbought', 70)
        self.rsi_oversold = self.config.get('rsi_oversold', 30)
        self.volatility_threshold = self.config.get('volatility_threshold', 0.02)

        # 置信度阈值（动态调整）
        self.confidence_threshold = self.config.get('confidence_threshold', 0.6)
        self.confidence_adaptive = self.config.get('confidence_adaptive', True)

        # 提前预警阈值
        self.early_warning_threshold = self.config.get('early_warning_threshold', 0.75)

        # 微观结构权重（v1.0.3新增）
        self.orderbook_slope_weight = self.config.get('orderbook_slope_weight', 0.3)
        self.volume_delta_weight = self.config.get('volume_delta_weight', 0.2)

        # 状态跟踪器
        self.state_tracker = RegimeStateTracker(
            min_stability_periods=self.config.get('min_stability_periods', 1)  # v1.0.3优化：从3降至1
        )

    def predict_regime(
        self,
        market_state: Dict,
        historical_context: Optional[List[Dict]] = None
    ) -> RegimePrediction:
        """
        概率性预测市场状态（v1.0.3核心优化）

        Args:
            market_state: 当前市场状态
            historical_context: 历史市场状态（可选）

        Returns:
            市场状态预测
        """
        # 提取特征
        adx = market_state.get('adx', 0)
        rsi = market_state.get('rsi', 50)
        trend_strength = market_state.get('trend_strength', 0)
        volatility = market_state.get('volatility', 0)
        price_change = market_state.get('price_change', 0)

        # 微观结构特征（v1.0.3新增）
        orderbook_slope = market_state.get('orderbook_slope', 0)
        volume_delta = market_state.get('volume_delta', 0)

        # 计算各状态概率
        probabilities = {
            MarketRegime.STRONG_TREND_UP: self._calc_strong_trend_up_prob(
                adx, rsi, trend_strength, price_change, orderbook_slope, volume_delta
            ),
            MarketRegime.WEAK_TREND_UP: self._calc_weak_trend_up_prob(
                adx, rsi, trend_strength, price_change, orderbook_slope, volume_delta
            ),
            MarketRegime.STRONG_TREND_DOWN: self._calc_strong_trend_down_prob(
                adx, rsi, trend_strength, price_change, orderbook_slope, volume_delta
            ),
            MarketRegime.WEAK_TREND_DOWN: self._calc_weak_trend_down_prob(
                adx, rsi, trend_strength, price_change, orderbook_slope, volume_delta
            ),
            MarketRegime.RANGING_HIGH_VOL: self._calc_ranging_high_vol_prob(
                adx, volatility, rsi, orderbook_slope, volume_delta
            ),
            MarketRegime.RANGING_LOW_VOL: self._calc_ranging_low_vol_prob(
                adx, volatility, rsi, orderbook_slope, volume_delta
            )
        }

        # 归一化概率
        total_prob = sum(probabilities.values())
        if total_prob > 0:
            probabilities = {k: v / total_prob for k, v in probabilities.items()}

        # 选择最高概率状态
        predicted_regime = max(probabilities, key=probabilities.get)
        confidence = probabilities[predicted_regime]

        # 动态调整置信度阈值
        effective_threshold = self._get_adaptive_threshold(historical_context)

        # 提前预警检测
        early_warning = False
        warning_message = ""

        if confidence >= self.early_warning_threshold:
            early_warning = True
            warning_message = f"高置信度市场状态转换预警: {predicted_regime.value} (置信度: {confidence:.2f})"

        # 检测状态转换
        if self.state_tracker.current_regime and \
           self.state_tracker.current_regime != predicted_regime:
            if confidence >= effective_threshold:
                # 状态转换确认
                self.state_tracker.current_regime = predicted_regime
                self.state_tracker.regime_duration = 0
                self.state_tracker.history.append(predicted_regime)
            else:
                # 置信度不足，保持当前状态
                predicted_regime = self.state_tracker.current_regime
                confidence = probabilities[predicted_regime]
        else:
            if not self.state_tracker.current_regime:
                # 初始状态
                if confidence >= effective_threshold:
                    self.state_tracker.current_regime = predicted_regime
                    self.state_tracker.history.append(predicted_regime)
            else:
                # 保持当前状态
                self.state_tracker.regime_duration += 1

        return RegimePrediction(
            regime=predicted_regime,
            confidence=confidence,
            probability=probabilities,
            early_warning=early_warning,
            warning_message=warning_message
        )

    def _calc_strong_trend_up_prob(
        self,
        adx: float,
        rsi: float,
        trend_strength: float,
        price_change: float,
        orderbook_slope: float,
        volume_delta: float
    ) -> float:
        """计算强上升趋势概率"""
        prob = 0.0

        # ADX强度（强趋势）
        if adx >= self.adx_threshold_strong:
            prob += 0.3
        elif adx >= self.adx_threshold_weak:
            prob += 0.15

        # RSI适中（未超买）
        if 40 <= rsi <= 70:
            prob += 0.2
        elif rsi < 40:
            prob += 0.1

        # 趋势强度
        prob += trend_strength * 0.2

        # 价格变化
        if price_change > 0:
            prob += min(0.1, price_change / 0.05)

        # 微观结构指标（v1.0.3新增）
        if orderbook_slope > 0:  # 买盘强
            prob += 0.05 * self.orderbook_slope_weight
        if volume_delta > 0:  # 主动买盘
            prob += 0.05 * self.volume_delta_weight

        return prob

    def _calc_weak_trend_up_prob(
        self,
        adx: float,
        rsi: float,
        trend_strength: float,
        price_change: float,
        orderbook_slope: float,
        volume_delta: float
    ) -> float:
        """计算弱上升趋势概率"""
        prob = 0.0

        # ADX强度（弱趋势）
        if self.adx_threshold_weak <= adx < self.adx_threshold_strong:
            prob += 0.3
        elif adx < self.adx_threshold_weak:
            prob += 0.1

        # RSI适中
        if 30 <= rsi <= 60:
            prob += 0.2
        elif rsi > 60:
            prob += 0.1

        # 趋势强度适中
        prob += trend_strength * 0.15

        # 价格变化
        if 0 < price_change < 0.02:
            prob += min(0.15, price_change / 0.02)

        # 微观结构指标
        if orderbook_slope > 0:
            prob += 0.03 * self.orderbook_slope_weight
        if volume_delta > 0:
            prob += 0.03 * self.volume_delta_weight

        return prob

    def _calc_strong_trend_down_prob(
        self,
        adx: float,
        rsi: float,
        trend_strength: float,
        price_change: float,
        orderbook_slope: float,
        volume_delta: float
    ) -> float:
        """计算强下降趋势概率"""
        prob = 0.0

        # ADX强度
        if adx >= self.adx_threshold_strong:
            prob += 0.3
        elif adx >= self.adx_threshold_weak:
            prob += 0.15

        # RSI适中（未超卖）
        if 30 <= rsi <= 60:
            prob += 0.2
        elif rsi > 60:
            prob += 0.1

        # 趋势强度
        prob += trend_strength * 0.2

        # 价格变化
        if price_change < 0:
            prob += min(0.1, abs(price_change) / 0.05)

        # 微观结构指标
        if orderbook_slope < 0:  # 卖盘强
            prob += 0.05 * self.orderbook_slope_weight
        if volume_delta < 0:  # 主动卖盘
            prob += 0.05 * self.volume_delta_weight

        return prob

    def _calc_weak_trend_down_prob(
        self,
        adx: float,
        rsi: float,
        trend_strength: float,
        price_change: float,
        orderbook_slope: float,
        volume_delta: float
    ) -> float:
        """计算弱下降趋势概率"""
        prob = 0.0

        # ADX强度（弱趋势）
        if self.adx_threshold_weak <= adx < self.adx_threshold_strong:
            prob += 0.3
        elif adx < self.adx_threshold_weak:
            prob += 0.1

        # RSI适中
        if 40 <= rsi <= 70:
            prob += 0.2
        elif rsi < 40:
            prob += 0.1

        # 趋势强度适中
        prob += trend_strength * 0.15

        # 价格变化
        if -0.02 < price_change < 0:
            prob += min(0.15, abs(price_change) / 0.02)

        # 微观结构指标
        if orderbook_slope < 0:
            prob += 0.03 * self.orderbook_slope_weight
        if volume_delta < 0:
            prob += 0.03 * self.volume_delta_weight

        return prob

    def _calc_ranging_high_vol_prob(
        self,
        adx: float,
        volatility: float,
        rsi: float,
        orderbook_slope: float,
        volume_delta: float
    ) -> float:
        """计算高波动震荡市概率"""
        prob = 0.0

        # ADX低（无明确趋势）
        if adx < self.adx_threshold_weak:
            prob += 0.3

        # 高波动
        if volatility >= self.volatility_threshold:
            prob += 0.3

        # RSI中性
        if 40 <= rsi <= 60:
            prob += 0.15

        # 微观结构指标（订单流不稳定）
        if abs(orderbook_slope) < 0.1:
            prob += 0.05 * self.orderbook_slope_weight
        if abs(volume_delta) < 0.1:
            prob += 0.05 * self.volume_delta_weight

        return prob

    def _calc_ranging_low_vol_prob(
        self,
        adx: float,
        volatility: float,
        rsi: float,
        orderbook_slope: float,
        volume_delta: float
    ) -> float:
        """计算低波动震荡市概率"""
        prob = 0.0

        # ADX低
        if adx < self.adx_threshold_weak:
            prob += 0.3

        # 低波动
        if volatility < self.volatility_threshold:
            prob += 0.3

        # RSI中性
        if 45 <= rsi <= 55:
            prob += 0.2

        # 微观结构指标（订单流稳定）
        if abs(orderbook_slope) < 0.05:
            prob += 0.05 * self.orderbook_slope_weight
        if abs(volume_delta) < 0.05:
            prob += 0.05 * self.volume_delta_weight

        return prob

    def _get_adaptive_threshold(self, historical_context: Optional[List[Dict]]) -> float:
        """
        动态调整置信度阈值

        Args:
            historical_context: 历史市场状态

        Returns:
            调整后的置信度阈值
        """
        if not self.confidence_adaptive or not historical_context:
            return self.confidence_threshold

        # 基于历史波动率调整阈值
        recent_volatility = np.std([
            s.get('volatility', 0) for s in historical_context[-10:]
        ]) if len(historical_context) >= 10 else 0

        # 波动率高时降低阈值（更快响应）
        if recent_volatility > self.volatility_threshold * 1.5:
            return self.confidence_threshold * 0.8
        # 波动率低时提高阈值（更稳定）
        elif recent_volatility < self.volatility_threshold * 0.5:
            return self.confidence_threshold * 1.2

        return self.confidence_threshold

    def get_regime_recommendation(
        self,
        prediction: RegimePrediction
    ) -> Dict:
        """
        基于市场状态预测提供策略推荐

        Args:
            prediction: 市场状态预测

        Returns:
            策略推荐
        """
        regime = prediction.regime
        confidence = prediction.confidence

        recommendations = {
            MarketRegime.STRONG_TREND_UP: {
                "strategy": "TREND_FOLLOWING",
                "position_size": "LARGE (25%)",
                "stop_loss": "TIGHT (1.5x ATR)",
                "take_profit": "TRAILING (3.0x ATR)",
                "reason": "强上升趋势，激进跟随"
            },
            MarketRegime.WEAK_TREND_UP: {
                "strategy": "TREND_FOLLOWING",
                "position_size": "MEDIUM (15%)",
                "stop_loss": "NORMAL (2.0x ATR)",
                "take_profit": "FIXED (2.5x ATR)",
                "reason": "弱上升趋势，适度跟随"
            },
            MarketRegime.STRONG_TREND_DOWN: {
                "strategy": "TREND_FOLLOWING",
                "position_size": "LARGE (25%)",
                "stop_loss": "TIGHT (1.5x ATR)",
                "take_profit": "TRAILING (3.0x ATR)",
                "reason": "强下降趋势，激进跟随"
            },
            MarketRegime.WEAK_TREND_DOWN: {
                "strategy": "TREND_FOLLOWING",
                "position_size": "MEDIUM (15%)",
                "stop_loss": "NORMAL (2.0x ATR)",
                "take_profit": "FIXED (2.5x ATR)",
                "reason": "弱下降趋势，适度跟随"
            },
            MarketRegime.RANGING_HIGH_VOL: {
                "strategy": "MEAN_REVERSION",
                "position_size": "SMALL (10%)",
                "stop_loss": "WIDE (2.5x ATR)",
                "take_profit": "FIXED (1.5x ATR)",
                "reason": "高波动震荡，均值回归"
            },
            MarketRegime.RANGING_LOW_VOL: {
                "strategy": "NO_TRADE",
                "position_size": "ZERO (0%)",
                "stop_loss": "N/A",
                "take_profit": "N/A",
                "reason": "低波动震荡，暂停交易"
            }
        }

        rec = recommendations.get(regime, recommendations[MarketRegime.RANGING_LOW_VOL])

        # 根据置信度调整推荐
        if confidence < 0.5:
            rec["position_size"] = f"REDUCED (50% of {rec['position_size']})"
            rec["reason"] += f" (置信度低: {confidence:.2f})"

        return rec


def main():
    parser = argparse.ArgumentParser(description="市场状态识别优化")
    parser.add_argument("--market-state", required=True, help="市场状态JSON字符串")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建市场状态识别优化器
        optimizer = MarketRegimeOptimizer(config)

        logger.info("=" * 70)
        logger.info("✅ 市场状态识别优化 - v1.0.3 P1级")
        logger.info("=" * 70)

        # 解析市场状态
        market_state = json.loads(args.market_state)

        logger.info(f"\n市场特征:")
        logger.info(f"  ADX: {market_state.get('adx', 0):.2f}")
        logger.info(f"  RSI: {market_state.get('rsi', 0):.2f}")
        logger.info(f"  趋势强度: {market_state.get('trend_strength', 0):.2f}")
        logger.info(f"  波动率: {market_state.get('volatility', 0):.4f}")
        logger.info(f"  价格变化: {market_state.get('price_change', 0):.4f}")
        logger.info(f"  订单簿斜率: {market_state.get('orderbook_slope', 0):.4f}")
        logger.info(f"  Volume Delta: {market_state.get('volume_delta', 0):.4f}")

        # 预测市场状态
        logger.info(f"\n{'=' * 70}")
        logger.info("开始预测...")
        logger.info(f"{'=' * 70}")

        prediction = optimizer.predict_regime(market_state)

        logger.info(f"\n预测结果:")
        logger.info(f"  市场状态: {prediction.regime.value}")
        logger.info(f"  置信度: {prediction.confidence:.2%}")
        logger.info(f"  提前预警: {'✅ 是' if prediction.early_warning else '❌ 否'}")

        if prediction.early_warning:
            logger.info(f"  预警信息: {prediction.warning_message}")

        logger.info(f"\n各状态概率:")
        for regime, prob in prediction.probability.items():
            if prob > 0.05:
                logger.info(f"  {regime.value}: {prob:.2%}")

        # 获取策略推荐
        logger.info(f"\n{'=' * 70}")
        logger.info("策略推荐")
        logger.info(f"{'=' * 70}")

        recommendation = optimizer.get_regime_recommendation(prediction)

        logger.info(f"\n推荐策略: {recommendation['strategy']}")
        logger.info(f"  仓位大小: {recommendation['position_size']}")
        logger.info(f"  止损设置: {recommendation['stop_loss']}")
        logger.info(f"  止盈设置: {recommendation['take_profit']}")
        logger.info(f"  推荐理由: {recommendation['reason']}")

        output = {
            "status": "success",
            "prediction": {
                "regime": prediction.regime.value,
                "confidence": prediction.confidence,
                "early_warning": prediction.early_warning,
                "warning_message": prediction.warning_message,
                "probabilities": {k.value: v for k, v in prediction.probability.items()}
            },
            "recommendation": recommendation,
            "state_tracker": {
                "current_regime": optimizer.state_tracker.current_regime.value if optimizer.state_tracker.current_regime else None,
                "regime_duration": optimizer.state_tracker.regime_duration
            }
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
