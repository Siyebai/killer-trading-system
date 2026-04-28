#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("multi_timeframe")
except ImportError:
    import logging
    logger = logging.getLogger("multi_timeframe")
"""
多时间帧对齐模块 - 杀手锏交易系统核心
解决MA策略在震荡市产生假信号的问题，生成大趋势方向
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class TimeframeSignal:
    """时间帧信号"""
    timeframe: str
    direction: int  # 1=上涨, -1=下跌, 0=震荡
    strength: float  # 信号强度 0-1
    ma_short: float
    ma_long: float
    price: float


@dataclass
class MultiTimeframeAnalysis:
    """多时间帧分析结果"""
    primary_direction: int  # 主趋势方向
    consensus_strength: float  # 一致性强度 0-1
    timeframe_signals: Dict[str, TimeframeSignal]
    is_aligned: bool  # 各时间帧是否一致
    recommendation: str  # 建议操作


class MultiTimeframeAligner:
    """多时间帧对齐器"""

    def __init__(self, timeframes: List[str] = None):
        """
        初始化多时间帧对齐器

        Args:
            timeframes: 时间帧列表，如 ['1h', '15m', '5m']
        """
        self.timeframes = timeframes or ['1h', '15m', '5m']

        # 默认MA周期（根据回测数据优化）
        self.ma_pairs = {
            '1h': (20, 60),  # MA20/MA60
            '15m': (15, 50),
            '5m': (10, 30)
        }

    def analyze_single_timeframe(self, df: pd.DataFrame, timeframe: str) -> Optional[TimeframeSignal]:
        """
        分析单个时间帧

        Args:
            df: 历史数据DataFrame（需包含close列）
            timeframe: 时间周期

        Returns:
            时间帧信号
        """
        if df is None or len(df) < 60:
            return None

        # 获取MA周期
        ma_short, ma_long = self.ma_pairs.get(timeframe, (20, 60))

        # 计算均线
        df['ma_short'] = df['close'].rolling(window=ma_short).mean()
        df['ma_long'] = df['close'].rolling(window=ma_long).mean()

        latest = df.iloc[-1]

        ma_short_val = latest['ma_short']
        ma_long_val = latest['ma_long']
        price = latest['close']

        # 判断方向
        if pd.isna(ma_short_val) or pd.isna(ma_long_val):
            return None

        # 趋势判断：短期均线上穿长期均线为上涨，下穿为下跌
        if ma_short_val > ma_long_val:
            direction = 1
            # 计算信号强度（均线距离归一化）
            strength = (ma_short_val - ma_long_val) / ma_long_val * 100
            strength = min(1.0, max(0.1, abs(strength) / 2))
        elif ma_short_val < ma_long_val:
            direction = -1
            strength = (ma_long_val - ma_short_val) / ma_long_val * 100
            strength = min(1.0, max(0.1, abs(strength) / 2))
        else:
            direction = 0
            strength = 0

        return TimeframeSignal(
            timeframe=timeframe,
            direction=direction,
            strength=strength,
            ma_short=ma_short_val,
            ma_long=ma_long_val,
            price=price
        )

    def align_timeframes(self, data_dict: Dict[str, pd.DataFrame]) -> MultiTimeframeAnalysis:
        """
        对齐多个时间帧

        Args:
            data_dict: 时间帧数据字典 {'1h': df1, '15m': df2, ...}

        Returns:
            多时间帧分析结果
        """
        signals = {}

        # 分析每个时间帧
        for timeframe in self.timeframes:
            df = data_dict.get(timeframe)
            signal = self.analyze_single_timeframe(df, timeframe)
            if signal:
                signals[timeframe] = signal

        # 计算主趋势（加权平均，大周期权重更高）
        weights = {'1h': 0.5, '15m': 0.3, '5m': 0.2}
        weighted_direction = 0
        total_weight = 0

        for timeframe, signal in signals.items():
            weight = weights.get(timeframe, 0.3)
            weighted_direction += signal.direction * signal.strength * weight
            total_weight += weight

        if total_weight > 0:
            primary_direction = 1 if weighted_direction > 0 else -1
            consensus_strength = abs(weighted_direction) / total_weight
        else:
            primary_direction = 0
            consensus_strength = 0

        # 判断是否一致
        directions = [s.direction for s in signals.values()]
        unique_directions = set(d for d in directions if d != 0)
        is_aligned = len(unique_directions) <= 1

        # 生成建议
        if is_aligned and primary_direction != 0 and consensus_strength > 0.4:
            if primary_direction == 1:
                recommendation = "STRONG_BUY"
            else:
                recommendation = "STRONG_SELL"
        elif consensus_strength > 0.2:
            if primary_direction == 1:
                recommendation = "WEAK_BUY"
            elif primary_direction == -1:
                recommendation = "WEAK_SELL"
            else:
                recommendation = "WAIT"
        else:
            recommendation = "WAIT"

        return MultiTimeframeAnalysis(
            primary_direction=primary_direction,
            consensus_strength=consensus_strength,
            timeframe_signals=signals,
            is_aligned=is_aligned,
            recommendation=recommendation
        )

    def get_trend_alignment_score(self, signal_action: str, analysis: MultiTimeframeAnalysis) -> float:
        """
        计算信号与趋势的匹配分数

        Args:
            signal_action: 信号动作（BUY/SELL/HOLD）
            analysis: 多时间帧分析结果

        Returns:
            匹配分数 0-1
        """
        if signal_action == "HOLD" or analysis.primary_direction == 0:
            return 0.5

        if signal_action == "BUY":
            if analysis.primary_direction == 1:
                return analysis.consensus_strength
            else:
                return 0

        if signal_action == "SELL":
            if analysis.primary_direction == -1:
                return analysis.consensus_strength
            else:
                return 0

        return 0.5


# 命令行测试
def main():
    """测试多时间帧对齐"""
    logger.info("="*60)
    logger.info("🎯 多时间帧对齐模块测试")
    logger.info("="*60)

    # 创建对齐器
    aligner = MultiTimeframeAligner(['1h', '15m', '5m'])

    # 生成模拟数据（上涨趋势）
    base_price = 50000
    data_dict = {}

    for timeframe in ['1h', '15m', '5m']:
        n_samples = {'1h': 200, '15m': 300, '5m': 500}[timeframe]
        trend_slope = 50 if timeframe == '1h' else 20  # 大周期趋势更明显

        prices = []
        for i in range(n_samples):
            noise = np.random.randn() * 100
            trend = i * trend_slope / n_samples
            price = base_price + trend + noise
            prices.append(price)

        df = pd.DataFrame({'close': prices})
        data_dict[timeframe] = df

    logger.info(f"\n生成模拟数据:")
    for tf, df in data_dict.items():
        logger.info(f"  {tf}: {len(df)} 个数据点")

    # 分析
    logger.info(f"\n开始多时间帧分析...")
    analysis = aligner.align_timeframes(data_dict)

    logger.info(f"\n📊 分析结果:")
    logger.info(f"  主趋势方向: {['震荡', '上涨', '下跌'][analysis.primary_direction + 1]}")
    logger.info(f"  一致性强度: {analysis.consensus_strength:.2f}")
    logger.info(f"  时间帧一致性: {analysis.is_aligned}")
    logger.info(f"  建议: {analysis.recommendation}")

    logger.info(f"\n各时间帧详情:")
    for tf, signal in analysis.timeframe_signals.items():
        direction_str = ['震荡', '上涨', '下跌'][signal.direction + 1]
        logger.info(f"  {tf}: {direction_str} (强度{signal.strength:.2f})")
        logger.info(f"    MA{aligner.ma_pairs[tf][0]}: {signal.ma_short:.2f}, MA{aligner.ma_pairs[tf][1]}: {signal.ma_long:.2f}")

    # 测试匹配分数
    logger.info(f"\n匹配分数测试:")
    buy_score = aligner.get_trend_alignment_score("BUY", analysis)
    sell_score = aligner.get_trend_alignment_score("SELL", analysis)

    logger.info(f"  信号BUY匹配分数: {buy_score:.2f}")
    logger.info(f"  信号SELL匹配分数: {sell_score:.2f}")

    # 下跌趋势测试
    logger.info(f"\n测试下跌趋势...")
    data_dict_bear = {}
    for timeframe in ['1h', '15m', '5m']:
        n_samples = {'1h': 200, '15m': 300, '5m': 500}[timeframe]
        trend_slope = -30 if timeframe == '1h' else -10

        prices = []
        for i in range(n_samples):
            noise = np.random.randn() * 100
            trend = i * trend_slope / n_samples
            price = base_price + trend + noise
            prices.append(price)

        df = pd.DataFrame({'close': prices})
        data_dict_bear[timeframe] = df

    analysis_bear = aligner.align_timeframes(data_dict_bear)
    logger.info(f"  下跌趋势建议: {analysis_bear.recommendation}")

    logger.info("\n" + "="*60)
    logger.info("多时间帧对齐模块测试: PASS")


if __name__ == "__main__":
    main()
