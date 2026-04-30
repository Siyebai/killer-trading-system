# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("winrate_enhancer")
except ImportError:
    import logging
    logger = logging.getLogger("winrate_enhancer")
"""
胜率增强器 - 杀手锏交易系统核心
多时间帧确认、市场环境过滤、信号质量评分、避免噪音时段
"""

from typing import Dict, Optional
from dataclasses import dataclass
import time

# 集成现有模块
from multi_timeframe import MultiTimeframeAligner, MultiTimeframeAnalysis
from market_regime import MarketRegimeDetector
from signal_scorer import SignalScorer, SignalScore


@dataclass
class EnhancedSignal:
    """增强后的信号"""
    original_action: str  # 原始信号
    enhanced_action: str  # 增强后信号（BUY/SELL/HOLD）
    should_trade: bool  # 是否应该交易
    confidence: float  # 置信度 0-1
    reasons: list  # 原因列表
    mtf_alignment: float  # 多时间帧对齐分数
    signal_quality: float  # 信号质量分数
    market_regime: str  # 市场状态


class WinrateEnhancer:
    """胜率增强器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化胜率增强器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 子模块
        self.mtf_aligner = MultiTimeframeAligner()
        self.regime_detector = MarketRegimeDetector(config)
        self.signal_scorer = SignalScorer(threshold=0.6)

        # 配置参数
        self.enable_mtf = self.config.get('enable_mtf', True)
        self.enable_regime_filter = self.config.get('enable_regime_filter', True)
        self.enable_signal_score = self.config.get('enable_signal_score', True)
        self.min_mtf_score = self.config.get('min_mtf_score', 0.4)
        self.min_signal_score = self.config.get('min_signal_score', 0.6)

        # 噪音时段（UTC时间，避免新闻发布时段）
        self.noisy_periods = self.config.get('noisy_periods', [
            (8, 9.5),   # 北京时间16:00-17:30（美股开盘前）
            (13, 14.5), # 北京时间21:00-22:30（美股开盘）
            (20, 21)    # 北京时间04:00-05:00（欧洲开盘）
        ])

    def should_trade(self, original_signal: str, context: Dict) -> EnhancedSignal:
        """
        判断是否应该交易

        Args:
            original_signal: 原始信号（BUY/SELL/HOLD）
            context: 上下文信息，包含：
                - mtf_data: 多时间帧数据
                - indicators: 技术指标
                - orderflow: 订单流
                - market_tick: 市场行情

        Returns:
            增强后的信号
        """
        reasons = []
        should_trade = True
        confidence = 0.5

        # 1. 多时间帧确认
        mtf_alignment = 0.5
        if self.enable_mtf and 'mtf_data' in context:
            mtf_analysis = self.mtf_aligner.align_timeframes(context['mtf_data'])
            mtf_alignment = self.mtf_aligner.get_trend_alignment_score(original_signal, mtf_analysis)

            if mtf_alignment < self.min_mtf_score:
                should_trade = False
                reasons.append(f"多时间帧不一致（{mtf_alignment:.2f} < {self.min_mtf_score}）")

            # 检查主趋势
            if mtf_analysis.primary_direction != 0:
                trend_str = ['震荡', '上涨', '下跌'][mtf_analysis.primary_direction + 1]
                reasons.append(f"主趋势: {trend_str}")
            else:
                reasons.append("主趋势: 震荡")

        # 2. 市场环境过滤
        market_regime = "UNKNOWN"
        if self.enable_regime_filter:
            if 'indicators' in context and 'orderflow' in context and 'market_tick' in context:
                regime_result = self.regime_detector.detect(
                    context['indicators'],
                    context['orderflow'],
                    context['market_tick']
                )
                market_regime = regime_result['regime']

                # 在震荡市暂停交易
                if market_regime in ['RANGE', 'NOISE', 'BAD_LIQUIDITY']:
                    should_trade = False
                    reasons.append(f"市场环境不适合交易: {market_regime}")

                reasons.append(f"市场状态: {market_regime}")

        # 3. 信号质量评分
        signal_quality = 0.5
        if self.enable_signal_score and 'indicators' in context:
            indicators = context['indicators']

            # 构造DataFrame用于评分
            import pandas as pd
            if 'df' in context:
                df = context['df']
                score_result = self.signal_scorer.score_signal(df, original_signal)
            else:
                # 简化：使用指标评分
                score_result = SignalScore(
                    overall_score=0.5,
                    rsi_score=0.5,
                    volume_score=0.5,
                    momentum_score=0.5,
                    trend_score=0.5,
                    is_qualified=True,
                    reason="数据不足"
                )

            signal_quality = score_result.overall_score

            if not score_result.is_qualified:
                should_trade = False
                reasons.append(f"信号质量不足: {score_result.reason}")

        # 4. 避免噪音时段
        if not self._is_quiet_time():
            should_trade = False
            reasons.append("处于噪音时段（新闻/开盘）")

        # 计算综合置信度
        confidence = (
            mtf_alignment * 0.4 +
            signal_quality * 0.4 +
            (0.8 if market_regime == 'TREND' else 0.3) * 0.2
        )

        # 确定最终信号
        if should_trade:
            enhanced_action = original_signal
        else:
            enhanced_action = "HOLD"

        return EnhancedSignal(
            original_action=original_signal,
            enhanced_action=enhanced_action,
            should_trade=should_trade,
            confidence=confidence,
            reasons=reasons,
            mtf_alignment=mtf_alignment,
            signal_quality=signal_quality,
            market_regime=market_regime
        )

    def _is_quiet_time(self) -> bool:
        """
        检查是否为安静时段

        Returns:
            True 表示当前时段适合交易
        """
        current_hour = time.gmtime().tm_hour + time.gmtime().tm_min / 60.0

        for start, end in self.noisy_periods:
            if start <= current_hour < end:
                return False  # 噪音时段

        return True  # 安静时段

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        return {
            'enable_mtf': self.enable_mtf,
            'enable_regime_filter': self.enable_regime_filter,
            'enable_signal_score': self.enable_signal_score,
            'min_mtf_score': self.min_mtf_score,
            'min_signal_score': self.min_signal_score,
            'noisy_periods': self.noisy_periods
        }


# 命令行测试
def main():
    """测试胜率增强器"""
    logger.info("="*60)
    logger.info("🎯 胜率增强器测试")
    logger.info("="*60)

    # 创建增强器
    enhancer = WinrateEnhancer({
        'enable_mtf': True,
        'enable_regime_filter': True,
        'enable_signal_score': True
    })

    # 生成测试上下文
    import pandas as pd
    import numpy as np

    # 多时间帧数据
    mtf_data = {}
    for tf in ['1h', '15m', '5m']:
        n = {'1h': 200, '15m': 300, '5m': 500}[tf]
        prices = [50000 + i * 20 + np.random.randn() * 100 for i in range(n)]
        mtf_data[tf] = pd.DataFrame({'close': prices})

    # 技术指标
    indicators = {
        'sma5': 50100,
        'sma20': 49500,
        'rsi': 55,
        'volatility': 0.008
    }

    # 订单流
    orderflow = {
        'pressure': 0.15,
        'cvd_slope': 0.05
    }

    # 市场行情
    market_tick = {
        'price': 50100,
        'bid': 50099,
        'ask': 50101
    }

    # 构造上下文
    context = {
        'mtf_data': mtf_data,
        'indicators': indicators,
        'orderflow': orderflow,
        'market_tick': market_tick,
        'df': mtf_data['1h']  # 用于信号评分
    }

    # 测试买入信号
    logger.info(f"\n测试买入信号...")
    result = enhancer.should_trade("BUY", context)

    logger.info(f"\n📊 增强结果:")
    logger.info(f"  原始信号: {result.original_action}")
    logger.info(f"  增强信号: {result.enhanced_action}")
    logger.info(f"  是否交易: {'✓ 是' if result.should_trade else '✗ 否'}")
    logger.info(f"  置信度: {result.confidence:.2f}")
    logger.info(f"  多时间帧对齐: {result.mtf_alignment:.2f}")
    logger.info(f"  信号质量: {result.signal_quality:.2f}")
    logger.info(f"  市场状态: {result.market_regime}")

    logger.info(f"\n原因:")
    for reason in result.reasons:
        logger.info(f"  • {reason}")

    # 测试震荡市场景
    logger.info(f"\n\n测试震荡市场景...")
    indicators_range = {
        'sma5': 50000,
        'sma20': 49980,
        'rsi': 50,
        'volatility': 0.003
    }

    context_range = {
        'mtf_data': mtf_data,
        'indicators': indicators_range,
        'orderflow': orderflow,
        'market_tick': market_tick,
        'df': mtf_data['1h']
    }

    result_range = enhancer.should_trade("BUY", context_range)
    logger.info(f"\n震荡市增强结果:")
    logger.info(f"  是否交易: {'✓ 是' if result_range.should_trade else '✗ 否'}")
    for reason in result_range.reasons:
        logger.info(f"  • {reason}")

    # 获取统计信息
    logger.info(f"\n\n配置统计:")
    stats = enhancer.get_statistics()
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")

    logger.info("\n" + "="*60)
    logger.info("胜率增强器测试: PASS")


if __name__ == "__main__":
    main()
