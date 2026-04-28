#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("adaptive_regime_switch")
except ImportError:
    import logging
    logger = logging.getLogger("adaptive_regime_switch")
"""
自适应市场切换模块 - v1.0.2
集成regime分类器，趋势市用趋势策略，震荡市自动切换均值回归子策略
核心策略：市场状态识别 + 动态策略切换
"""

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np


class MarketRegime(Enum):
    """市场状态"""
    STRONG_TREND_UP = "STRONG_TREND_UP"      # 强上升趋势
    WEAK_TREND_UP = "WEAK_TREND_UP"          # 弱上升趋势
    RANGE_BOUND = "RANGE_BOUND"              # 震荡市
    WEAK_TREND_DOWN = "WEAK_TREND_DOWN"      # 弱下降趋势
    STRONG_TREND_DOWN = "STRONG_TREND_DOWN"  # 强下降趋势


class StrategyType(Enum):
    """策略类型"""
    TREND_FOLLOWING = "TREND_FOLLOWING"      # 趋势跟随
    MEAN_REVERSION = "MEAN_REVERSION"        # 均值回归
    VOLATILITY_BREAKOUT = "VOLATILITY_BREAKOUT"  # 波动率突破
    NEUTRAL = "NEUTRAL"                      # 中性（不交易）


@dataclass
class RegimeFeatures:
    """市场状态特征"""
    adx: float
    trend_strength: float
    volatility: float
    price_momentum: float
    volume_momentum: float
    rsi: float


@dataclass
class StrategyRecommendation:
    """策略推荐"""
    strategy_type: StrategyType
    confidence: float
    reason: str
    recommended_position_size: float


class AdaptiveRegimeSwitcher:
    """自适应市场切换器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化自适应市场切换器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 市场状态分类阈值
        self.adx_strong_trend = self.config.get('adx_strong_trend', 30)
        self.adx_weak_trend = self.config.get('adx_weak_trend', 20)
        self.rsi_overbought = self.config.get('rsi_overbought', 70)
        self.rsi_oversold = self.config.get('rsi_oversold', 30)
        self.volatility_high = self.config.get('volatility_high', 0.03)
        self.volatility_low = self.config.get('volatility_low', 0.01)

        # 策略切换配置
        self.min_regime_stability_periods = self.config.get('min_regime_stability_periods', 3)  # 至少3个周期稳定
        self.regime_switch_threshold = self.config.get('regime_switch_threshold', 0.7)  # 置信度>0.7才切换

        # 策略权重配置
        self.trend_strategy_weight = self.config.get('trend_strategy_weight', 0.7)
        self.mean_reversion_weight = self.config.get('mean_reversion_weight', 0.3)

        # 历史状态跟踪
        self.regime_history = []
        self.current_regime = None

    def extract_features(self, price_data: Dict) -> RegimeFeatures:
        """
        提取市场状态特征

        Args:
            price_data: 价格数据字典（包含indicators）

        Returns:
            市场状态特征
        """
        indicators = price_data.get('indicators', {})

        # 提取指标
        adx = indicators.get('adx', 20)
        rsi = indicators.get('rsi', 50)
        trend_strength = indicators.get('trend_strength', 0.5)

        # 计算波动率
        closes = price_data.get('close', [100])
        if len(closes) > 20:
            returns = np.diff(closes[-20:]) / closes[-20:-1]
            volatility = np.std(returns)
        else:
            volatility = 0.02

        # 计算价格动量
        if len(closes) >= 5:
            price_momentum = (closes[-1] - closes[-5]) / closes[-5]
        else:
            price_momentum = 0

        # 计算成交量动量
        volumes = price_data.get('volume', [1000])
        if len(volumes) >= 5:
            volume_momentum = (volumes[-1] - volumes[-5]) / volumes[-5]
        else:
            volume_momentum = 0

        return RegimeFeatures(
            adx=adx,
            trend_strength=trend_strength,
            volatility=volatility,
            price_momentum=price_momentum,
            volume_momentum=volume_momentum,
            rsi=rsi
        )

    def classify_regime(self, features: RegimeFeatures) -> MarketRegime:
        """
        分类市场状态

        Args:
            features: 市场状态特征

        Returns:
            市场状态
        """
        # 强趋势判断（ADX高）
        if features.adx >= self.adx_strong_trend:
            if features.price_momentum > 0.02:
                return MarketRegime.STRONG_TREND_UP
            elif features.price_momentum < -0.02:
                return MarketRegime.STRONG_TREND_DOWN
            elif features.rsi > 60:
                return MarketRegime.WEAK_TREND_UP
            elif features.rsi < 40:
                return MarketRegime.WEAK_TREND_DOWN
            else:
                return MarketRegime.RANGE_BOUND

        # 弱趋势判断（ADX中等）
        elif features.adx >= self.adx_weak_trend:
            if features.trend_strength > 0.6:
                return MarketRegime.WEAK_TREND_UP
            elif features.trend_strength < -0.6:
                return MarketRegime.WEAK_TREND_DOWN
            else:
                return MarketRegime.RANGE_BOUND

        # 震荡市判断（ADX低）
        else:
            # 即使ADX低，也可能有短期趋势
            if abs(features.price_momentum) > 0.03:
                if features.price_momentum > 0:
                    return MarketRegime.WEAK_TREND_UP
                else:
                    return MarketRegime.WEAK_TREND_DOWN
            else:
                return MarketRegime.RANGE_BOUND

    def recommend_strategy(self, regime: MarketRegime, features: RegimeFeatures) -> StrategyRecommendation:
        """
        推荐策略

        Args:
            regime: 市场状态
            features: 市场状态特征

        Returns:
            策略推荐
        """
        # 强上升趋势
        if regime == MarketRegime.STRONG_TREND_UP:
            return StrategyRecommendation(
                strategy_type=StrategyType.TREND_FOLLOWING,
                confidence=0.9,
                reason="强上升趋势，使用趋势跟随策略",
                recommended_position_size=0.25
            )

        # 强下降趋势
        elif regime == MarketRegime.STRONG_TREND_DOWN:
            return StrategyRecommendation(
                strategy_type=StrategyType.TREND_FOLLOWING,
                confidence=0.9,
                reason="强下降趋势，使用趋势跟随策略",
                recommended_position_size=0.20
            )

        # 弱上升趋势
        elif regime == MarketRegime.WEAK_TREND_UP:
            # 检查是否超买
            if features.rsi >= self.rsi_overbought:
                return StrategyRecommendation(
                    strategy_type=StrategyType.MEAN_REVERSION,
                    confidence=0.75,
                    reason="弱上升趋势但RSI超买，使用均值回归策略",
                    recommended_position_size=0.15
                )
            else:
                return StrategyRecommendation(
                    strategy_type=StrategyType.TREND_FOLLOWING,
                    confidence=0.7,
                    reason="弱上升趋势，谨慎使用趋势跟随策略",
                    recommended_position_size=0.15
                )

        # 弱下降趋势
        elif regime == MarketRegime.WEAK_TREND_DOWN:
            # 检查是否超卖
            if features.rsi <= self.rsi_oversold:
                return StrategyRecommendation(
                    strategy_type=StrategyType.MEAN_REVERSION,
                    confidence=0.75,
                    reason="弱下降趋势但RSI超卖，使用均值回归策略",
                    recommended_position_size=0.15
                )
            else:
                return StrategyRecommendation(
                    strategy_type=StrategyType.TREND_FOLLOWING,
                    confidence=0.7,
                    reason="弱下降趋势，谨慎使用趋势跟随策略",
                    recommended_position_size=0.15
                )

        # 震荡市
        elif regime == MarketRegime.RANGE_BOUND:
            # 检查波动率
            if features.volatility >= self.volatility_high:
                return StrategyRecommendation(
                    strategy_type=StrategyType.VOLATILITY_BREAKOUT,
                    confidence=0.65,
                    reason="高波动震荡市，使用波动率突破策略",
                    recommended_position_size=0.10
                )
            elif features.volatility <= self.volatility_low:
                return StrategyRecommendation(
                    strategy_type=StrategyType.NEUTRAL,
                    confidence=0.8,
                    reason="低波动震荡市，不建议交易",
                    recommended_position_size=0.0
                )
            else:
                return StrategyRecommendation(
                    strategy_type=StrategyType.MEAN_REVERSION,
                    confidence=0.7,
                    reason="震荡市，使用均值回归策略",
                    recommended_position_size=0.15
                )

        # 默认：中性
        else:
            return StrategyRecommendation(
                strategy_type=StrategyType.NEUTRAL,
                confidence=0.5,
                reason="市场状态不明，暂停交易",
                recommended_position_size=0.0
            )

    def should_switch_strategy(self, new_regime: MarketRegime, new_strategy: StrategyType) -> Tuple[bool, float]:
        """
        判断是否应该切换策略

        Args:
            new_regime: 新市场状态
            new_strategy: 新策略

        Returns:
            (是否切换, 置信度)
        """
        # 如果是第一次
        if self.current_regime is None:
            self.current_regime = new_regime
            self.regime_history.append(new_regime)
            return True, 1.0

        # 检查状态稳定性
        if len(self.regime_history) < self.min_regime_stability_periods:
            # 状态未稳定，添加历史
            self.regime_history.append(new_regime)
            return False, 0.5

        # 检查状态一致性
        recent_regimes = self.regime_history[-self.min_regime_stability_periods:]
        regime_count = recent_regimes.count(new_regime)

        if regime_count >= self.min_regime_stability_periods:
            # 状态稳定，计算置信度
            confidence = regime_count / self.min_regime_stability_periods

            # 更新当前状态
            self.current_regime = new_regime
            self.regime_history.append(new_regime)

            # 限制历史长度
            if len(self.regime_history) > 20:
                self.regime_history = self.regime_history[-20:]

            return confidence >= self.regime_switch_threshold, confidence
        else:
            # 状态不稳定
            self.regime_history.append(new_regime)
            return False, regime_count / self.min_regime_stability_periods

    def get_strategy_weights(self, regime: MarketRegime) -> Dict[str, float]:
        """
        获取策略权重（用于混合策略框架）

        Args:
            regime: 市场状态

        Returns:
            策略权重字典
        """
        if regime in [MarketRegime.STRONG_TREND_UP, MarketRegime.STRONG_TREND_DOWN]:
            return {
                'ema_trend': 0.4,
                'supertrend': 0.4,
                'rsi_mean_reversion': 0.1,
                'breakout': 0.1
            }
        elif regime in [MarketRegime.WEAK_TREND_UP, MarketRegime.WEAK_TREND_DOWN]:
            return {
                'ema_trend': 0.3,
                'supertrend': 0.3,
                'rsi_mean_reversion': 0.3,
                'breakout': 0.1
            }
        else:  # RANGE_BOUND
            return {
                'ema_trend': 0.15,
                'supertrend': 0.15,
                'rsi_mean_reversion': 0.5,
                'breakout': 0.2
            }


def main():
    parser = argparse.ArgumentParser(description="自适应市场切换")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--adx", type=float, default=25, help="ADX值")
    parser.add_argument("--rsi", type=float, default=50, help="RSI值")
    parser.add_argument("--trend", type=float, default=0.5, help="趋势强度")
    parser.add_argument("--volatility", type=float, default=0.02, help="波动率")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建自适应市场切换器
        switcher = AdaptiveRegimeSwitcher(config)

        logger.info("=" * 70)
        logger.info("🔄 自适应市场切换 - v1.0.2")
        logger.info("=" * 70)

        # 准备特征
        features = RegimeFeatures(
            adx=args.adx,
            trend_strength=args.trend,
            volatility=args.volatility,
            price_momentum=0.01,
            volume_momentum=0.02,
            rsi=args.rsi
        )

        logger.info(f"\n市场特征:")
        logger.info(f"  ADX: {features.adx:.2f}")
        logger.info(f"  RSI: {features.rsi:.2f}")
        logger.info(f"  趋势强度: {features.trend_strength:.2f}")
        logger.info(f"  波动率: {features.volatility:.2%}")

        # 分类市场状态
        regime = switcher.classify_regime(features)

        logger.info(f"\n{'=' * 70}")
        logger.info("市场状态分类")
        logger.info(f"{'=' * 70}")
        logger.info(f"\n当前状态: {regime.value}")

        # 推荐策略
        recommendation = switcher.recommend_strategy(regime, features)

        logger.info(f"\n{'=' * 70}")
        logger.info("策略推荐")
        logger.info(f"{'=' * 70}")
        logger.info(f"\n推荐策略: {recommendation.strategy_type.value}")
        logger.info(f"置信度: {recommendation.confidence:.2f}")
        logger.info(f"原因: {recommendation.reason}")
        logger.info(f"推荐仓位: {recommendation.recommended_position_size*100:.1f}%")

        # 获取策略权重
        weights = switcher.get_strategy_weights(regime)

        logger.info(f"\n{'=' * 70}")
        logger.info("策略权重分配")
        logger.info(f"{'=' * 70}")
        for strategy, weight in weights.items():
            logger.info(f"  {strategy}: {weight*100:.0f}%")

        # 判断是否应该切换
        should_switch, confidence = switcher.should_switch_strategy(regime, recommendation.strategy_type)

        logger.info(f"\n{'=' * 70}")
        logger.info("策略切换判断")
        logger.info(f"{'=' * 70}")
        if should_switch:
            logger.info(f"\n✅ 建议切换至 {recommendation.strategy_type.value}")
            logger.info(f"   置信度: {confidence:.2f}")
        else:
            logger.info(f"\n⚠️ 建议保持当前策略")
            logger.info(f"   置信度: {confidence:.2f}（<0.7阈值）")

        output = {
            "status": "success",
            "regime": regime.value,
            "recommendation": {
                "strategy": recommendation.strategy_type.value,
                "confidence": recommendation.confidence,
                "reason": recommendation.reason,
                "position_size": recommendation.recommended_position_size
            },
            "strategy_weights": weights,
            "should_switch": should_switch,
            "switch_confidence": confidence
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
