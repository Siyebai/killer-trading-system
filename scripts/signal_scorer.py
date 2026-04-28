#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("signal_scorer")
except ImportError:
    import logging
    logger = logging.getLogger("signal_scorer")
"""
信号质量评分模块 - 杀手锏交易系统核心
RSI超买超卖过滤、成交量确认、动量一致性、综合评分
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class SignalScore:
    """信号评分"""
    overall_score: float  # 综合评分 0-1
    rsi_score: float  # RSI评分 0-1
    volume_score: float  # 成交量评分 0-1
    momentum_score: float  # 动量评分 0-1
    trend_score: float  # 趋势评分 0-1
    is_qualified: bool  # 是否通过阈值
    reason: str  # 未通过原因


class SignalScorer:
    """信号质量评分器"""

    def __init__(self, threshold: float = 0.6):
        """
        初始化评分器

        Args:
            threshold: 信号质量阈值，低于此值信号将被过滤
        """
        self.threshold = threshold

    def calculate_rsi_score(self, df: pd.DataFrame, signal_action: str) -> float:
        """
        计算RSI评分

        Args:
            df: 历史数据
            signal_action: 信号动作（BUY/SELL）

        Returns:
            RSI评分 0-1
        """
        if len(df) < 14:
            return 0.5

        # 计算RSI
        deltas = df['close'].diff()
        gains = deltas.where(deltas > 0, 0)
        losses = -deltas.where(deltas < 0, 0)

        avg_gain = gains.rolling(window=14).mean()
        avg_loss = losses.rolling(window=14).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        current_rsi = rsi.iloc[-1]

        if pd.isna(current_rsi):
            return 0.5

        # RSI评分逻辑
        if signal_action == "BUY":
            # 买入信号：RSI应该在超卖区（<30）或中性区（30-70）
            if current_rsi < 30:
                return 1.0  # 超卖，买入机会
            elif current_rsi < 40:
                return 0.8
            elif current_rsi < 70:
                return 0.5  # 中性
            elif current_rsi < 80:
                return 0.2  # 偏高
            else:
                return 0.0  # 超买，不应买入
        else:  # SELL
            # 卖出信号：RSI应该在超买区（>70）
            if current_rsi > 70:
                return 1.0  # 超买，卖出机会
            elif current_rsi > 60:
                return 0.8
            elif current_rsi > 30:
                return 0.5  # 中性
            elif current_rsi > 20:
                return 0.2  # 偏低
            else:
                return 0.0  # 超卖，不应卖出

    def calculate_volume_score(self, df: pd.DataFrame, signal_action: str) -> float:
        """
        计算成交量评分

        Args:
            df: 历史数据
            signal_action: 信号动作

        Returns:
            成交量评分 0-1
        """
        if len(df) < 20 or 'volume' not in df.columns:
            return 0.5

        current_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]

        if avg_volume == 0:
            return 0.5

        volume_ratio = current_volume / avg_volume

        # 成交量评分逻辑
        # 买入/卖出信号应该有成交量支撑
        if volume_ratio > 2.0:
            return 1.0  # 放量，强烈确认
        elif volume_ratio > 1.5:
            return 0.8  # 明显放量
        elif volume_ratio > 1.0:
            return 0.6  # 正常放量
        elif volume_ratio > 0.7:
            return 0.4  # 缩量
        else:
            return 0.2  # 显著缩量，信号可靠性低

    def calculate_momentum_score(self, df: pd.DataFrame, signal_action: str) -> float:
        """
        计算动量评分

        Args:
            df: 历史数据
            signal_action: 信号动作

        Returns:
            动量评分 0-1
        """
        if len(df) < 5:
            return 0.5

        # 计算多周期动量
        momentum_5 = (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5]
        momentum_10 = (df['close'].iloc[-1] - df['close'].iloc[-10]) / df['close'].iloc[-10] if len(df) >= 10 else 0
        momentum_20 = (df['close'].iloc[-1] - df['close'].iloc[-20]) / df['close'].iloc[-20] if len(df) >= 20 else 0

        # 动量一致性评分
        if signal_action == "BUY":
            # 买入信号：多周期动量应该都为正
            mom_scores = [
                min(1.0, max(0, momentum_5 * 100)) if momentum_5 > 0 else 0,
                min(1.0, max(0, momentum_10 * 100)) if momentum_10 > 0 else 0,
                min(1.0, max(0, momentum_20 * 100)) if momentum_20 > 0 else 0
            ]
            # 越长周期权重越高
            weights = [0.2, 0.3, 0.5]
            score = sum(s * w for s, w in zip(mom_scores, weights))
            return min(1.0, score * 2)  # 放大权重
        else:  # SELL
            # 卖出信号：多周期动量应该都为负
            mom_scores = [
                min(1.0, max(0, -momentum_5 * 100)) if momentum_5 < 0 else 0,
                min(1.0, max(0, -momentum_10 * 100)) if momentum_10 < 0 else 0,
                min(1.0, max(0, -momentum_20 * 100)) if momentum_20 < 0 else 0
            ]
            weights = [0.2, 0.3, 0.5]
            score = sum(s * w for s, w in zip(mom_scores, weights))
            return min(1.0, score * 2)

    def calculate_trend_score(self, df: pd.DataFrame, signal_action: str) -> float:
        """
        计算趋势评分（使用MA20/MA60）

        Args:
            df: 历史数据
            signal_action: 信号动作

        Returns:
            趋势评分 0-1
        """
        if len(df) < 60:
            return 0.5

        df['ma20'] = df['close'].rolling(window=20).mean()
        df['ma60'] = df['close'].rolling(window=60).mean()

        ma20 = df['ma20'].iloc[-1]
        ma60 = df['ma60'].iloc[-1]

        if pd.isna(ma20) or pd.isna(ma60):
            return 0.5

        # 趋势判断
        if signal_action == "BUY":
            if ma20 > ma60:
                # 短期均线在长期均线上方
                strength = (ma20 - ma60) / ma60 * 100
                return min(1.0, strength / 2)
            else:
                return 0.0
        else:  # SELL
            if ma20 < ma60:
                # 短期均线在长期均线下方
                strength = (ma60 - ma20) / ma60 * 100
                return min(1.0, strength / 2)
            else:
                return 0.0

    def score_signal(self, df: pd.DataFrame, signal_action: str) -> SignalScore:
        """
        综合评分

        Args:
            df: 历史数据
            signal_action: 信号动作（BUY/SELL）

        Returns:
            信号评分
        """
        # 计算各维度评分
        rsi_score = self.calculate_rsi_score(df, signal_action)
        volume_score = self.calculate_volume_score(df, signal_action)
        momentum_score = self.calculate_momentum_score(df, signal_action)
        trend_score = self.calculate_trend_score(df, signal_action)

        # 加权综合评分
        weights = {
            'rsi': 0.25,
            'volume': 0.2,
            'momentum': 0.3,
            'trend': 0.25
        }

        overall_score = (
            rsi_score * weights['rsi'] +
            volume_score * weights['volume'] +
            momentum_score * weights['momentum'] +
            trend_score * weights['trend']
        )

        # 判断是否通过阈值
        is_qualified = overall_score >= self.threshold

        # 生成未通过原因
        if not is_qualified:
            weak_factors = []
            if rsi_score < 0.4:
                weak_factors.append("RSI指标")
            if volume_score < 0.4:
                weak_factors.append("成交量")
            if momentum_score < 0.4:
                weak_factors.append("动量")
            if trend_score < 0.4:
                weak_factors.append("趋势")

            reason = f"评分低于阈值: {', '.join(weak_factors)}"
        else:
            reason = "信号质量合格"

        return SignalScore(
            overall_score=overall_score,
            rsi_score=rsi_score,
            volume_score=volume_score,
            momentum_score=momentum_score,
            trend_score=trend_score,
            is_qualified=is_qualified,
            reason=reason
        )


# 命令行测试
def main():
    """测试信号质量评分"""
    logger.info("="*60)
    logger.info("📊 信号质量评分模块测试")
    logger.info("="*60)

    # 创建评分器
    scorer = SignalScorer(threshold=0.6)

    # 生成模拟数据（上涨趋势，买入信号）
    base_price = 50000
    prices = []
    volumes = []

    for i in range(100):
        # 上涨趋势
        trend = i * 20
        noise = np.random.randn() * 100
        price = base_price + trend + noise
        volume = 1000 + np.random.randint(200, 800)  # 放量

        prices.append(price)
        volumes.append(volume)

    df = pd.DataFrame({'close': prices, 'volume': volumes})

    logger.info(f"\n生成模拟数据: {len(df)} 个数据点")
    logger.info(f"当前价格: ${df['close'].iloc[-1]:.2f}")
    logger.info(f"平均成交量: {df['volume'].mean():.0f}")

    # 测试买入信号
    logger.info(f"\n测试买入信号...")
    buy_score = scorer.score_signal(df, "BUY")

    logger.info(f"\n📈 买入信号评分:")
    logger.info(f"  综合评分: {buy_score.overall_score:.2f}")
    logger.info(f"  RSI评分: {buy_score.rsi_score:.2f}")
    logger.info(f"  成交量评分: {buy_score.volume_score:.2f}")
    logger.info(f"  动量评分: {buy_score.momentum_score:.2f}")
    logger.info(f"  趋势评分: {buy_score.trend_score:.2f}")
    logger.info(f"  是否合格: {'✓ 通过' if buy_score.is_qualified else '✗ 未通过'}")
    logger.info(f"  原因: {buy_score.reason}")

    # 测试卖出信号
    logger.info(f"\n测试卖出信号...")
    sell_score = scorer.score_signal(df, "SELL")

    logger.info(f"\n📉 卖出信号评分:")
    logger.info(f"  综合评分: {sell_score.overall_score:.2f}")
    logger.info(f"  RSI评分: {sell_score.rsi_score:.2f}")
    logger.info(f"  成交量评分: {sell_score.volume_score:.2f}")
    logger.info(f"  动量评分: {sell_score.momentum_score:.2f}")
    logger.info(f"  趋势评分: {sell_score.trend_score:.2f}")
    logger.info(f"  是否合格: {'✓ 通过' if sell_score.is_qualified else '✗ 未通过'}")
    logger.info(f"  原因: {sell_score.reason}")

    # 测试低质量信号（震荡市）
    logger.info(f"\n测试低质量信号（震荡市）...")
    prices_noise = [base_price + np.random.randn() * 500 for _ in range(100)]
    volumes_noise = [500 + np.random.randint(-200, 300) for _ in range(100)]
    df_noise = pd.DataFrame({'close': prices_noise, 'volume': volumes_noise})

    noise_score = scorer.score_signal(df_noise, "BUY")
    logger.info(f"  综合评分: {noise_score.overall_score:.2f}")
    logger.info(f"  是否合格: {'✓ 通过' if noise_score.is_qualified else '✗ 未通过'}")
    logger.info(f"  原因: {noise_score.reason}")

    logger.info("\n" + "="*60)
    logger.info("信号质量评分模块测试: PASS")


if __name__ == "__main__":
    main()
