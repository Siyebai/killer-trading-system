# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.3 - 修复版SHORT策略
P1修复：解决SHORT信号生成不足问题
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from typing import Dict
import logging

logger = logging.getLogger("short_strategy_fixer")


class ShortSignalGenerator:
    """
    SHORT信号生成器（修复版）
    目标：确保SHORT信号数量达到交易的30-40%
    """

    def __init__(self):
        """初始化"""
        self.version = "v1.0.3"
        logger.info(f"✅ SHORT信号生成器 {self.version} 初始化完成")

    def generate_short_signals(self, df: pd.DataFrame) -> Dict:
        """
        生成SHORT信号
        确保SHORT信号条件与做多对称
        """
        if df is None or len(df) < 60:
            return {'direction': 'NEUTRAL', 'confidence': 0}

        try:
            latest = df.iloc[-1]
            prev = df.iloc[-2]

            # 计算指标
            ema_9 = df['close'].ewm(span=9).mean().iloc[-1]
            ema_21 = df['close'].ewm(span=21).mean().iloc[-1]
            ema_50 = df['close'].ewm(span=50).mean().iloc[-1]

            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss.replace(0, np.inf)
            rsi = 100 - (100 / (1 + rs)).iloc[-1]

            # MACD
            ema_12 = df['close'].ewm(span=12).mean().iloc[-1]
            ema_26 = df['close'].ewm(span=26).mean().iloc[-1]
            macd = ema_12 - ema_26
            macd_signal = macd.ewm(span=9).mean().iloc[-1]
            macd_prev = df['close'].ewm(span=12).mean().iloc[-2] - df['close'].ewm(span=26).mean().iloc[-2]
            macd_signal_prev = macd.ewm(span=9).mean().iloc[-2]

            # 布林带
            bb_middle = df['close'].rolling(window=20).mean().iloc[-1]
            bb_std = df['close'].rolling(window=20).std().iloc[-1]
            bb_upper = bb_middle + 2 * bb_std
            bb_lower = bb_middle - 2 * bb_std

            # ATR
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            atr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(window=14).mean().iloc[-1]

            # 成交量
            volume_sma = df['volume'].rolling(window=20).mean().iloc[-1]
            volume_ratio = df['volume'].iloc[-1] / volume_sma

            # SHORT信号评分
            short_score = 0
            reasons = []

            # 1. EMA空头排列（3分）
            if latest['close'] < ema_9 < ema_21 < ema_50:
                short_score += 3
                reasons.append("EMA空头排列")
            elif latest['close'] < ema_9 < ema_21:
                short_score += 2
                reasons.append("EMA部分空头")

            # 2. RSI超买（2分）
            if rsi > 70:
                short_score += 2
                reasons.append(f"RSI超买({rsi:.1f})")
            elif rsi > 65:
                short_score += 1
                reasons.append(f"RSI偏高({rsi:.1f})")

            # 3. MACD死叉（2分）
            if macd < macd_signal and macd_prev >= macd_signal_prev:
                short_score += 2
                reasons.append("MACD死叉")
            elif macd < macd_signal:
                short_score += 1
                reasons.append("MACD负值")

            # 4. 布林带上轨突破（2分）
            bb_position = (latest['close'] - bb_lower) / (bb_upper - bb_lower)
            if bb_position > 0.9:
                short_score += 2
                reasons.append("触及布林上轨")
            elif bb_position > 0.8:
                short_score += 1
                reasons.append("接近布林上轨")

            # 5. 放量下跌（1分）
            price_change = (latest['close'] - prev['close']) / prev['close']
            if price_change < -0.005 and volume_ratio > 1.3:
                short_score += 1
                reasons.append("放量下跌")

            # 6. 动量转弱（1分）
            momentum_10 = df['close'].iloc[-1] / df['close'].iloc[-10] - 1
            if momentum_10 < -0.01:
                short_score += 1
                reasons.append("10日动量转弱")

            # 评估
            max_score = 11  # 3+2+2+2+1+1
            confidence = short_score / max_score

            # 至少4分才生成信号
            if short_score >= 4:
                return {
                    'direction': 'SHORT',
                    'confidence': min(0.85, confidence + 0.2),
                    'score': short_score,
                    'max_score': max_score,
                    'reasons': reasons
                }
            else:
                return {'direction': 'NEUTRAL', 'confidence': 0}

        except Exception as e:
            logger.error(f"❌ SHORT信号生成失败: {e}")
            return {'direction': 'NEUTRAL', 'confidence': 0}


class DirectionalBalanceFilter:
    """
    方向平衡过滤器
    确保做多和做空的比例合理
    """

    def __init__(self, max_short_ratio: float = 0.5):
        """
        初始化

        参数：
        - max_short_ratio: 做空仓位最大为做多的50%
        """
        self.max_short_ratio = max_short_ratio
        self.long_trades = 0
        self.short_trades = 0

        logger.info(f"✅ 方向平衡过滤器初始化完成 (SHORT上限: {max_short_ratio*100}%)")

    def filter_signal(self, signal: Dict) -> Dict:
        """
        过滤信号，保持方向平衡
        """
        if signal['direction'] == 'NEUTRAL':
            return signal

        # 计算当前比例
        total_trades = self.long_trades + self.short_trades
        if total_trades == 0:
            # 初始阶段，允许两种信号
            pass
        else:
            short_ratio = self.short_trades / total_trades

            # 如果SHORT比例过低，优先SHORT
            if short_ratio < 0.3:
                if signal['direction'] == 'SHORT':
                    # 提升SHORT信号置信度
                    signal['confidence'] = min(0.9, signal['confidence'] + 0.1)
                    signal['balance_boosted'] = True

            # 如果SHORT比例过高，限制SHORT
            if short_ratio > 0.4:
                if signal['direction'] == 'SHORT':
                    # 降低SHORT信号置信度
                    signal['confidence'] *= 0.8
                    signal['balance_reduced'] = True

                    if signal['confidence'] < 0.5:
                        return {'direction': 'NEUTRAL', 'confidence': 0, 'reason': 'SHORT比例过高'}

        # 检查仓位限制
        if signal['direction'] == 'SHORT':
            # 做空仓位不超过做多的50%
            max_short_allowed = self.long_trades * self.max_short_ratio
            if self.short_trades >= max_short_allowed and self.long_trades > 0:
                return {
                    'direction': 'NEUTRAL',
                    'confidence': 0,
                    'reason': 'SHORT仓位已达上限'
                }

        return signal

    def record_trade(self, direction: str):
        """记录交易"""
        if direction == 'LONG':
            self.long_trades += 1
        elif direction == 'SHORT':
            self.short_trades += 1

    def get_statistics(self) -> Dict:
        """获取统计"""
        total = self.long_trades + self.short_trades

        return {
            'long_trades': self.long_trades,
            'short_trades': self.short_trades,
            'short_pct': self.short_trades / total * 100 if total > 0 else 0,
            'long_pct': self.long_trades / total * 100 if total > 0 else 0
        }


if __name__ == "__main__":
    print("=" * 70)
    print("🧪 SHORT信号生成器测试")
    print("=" * 70)

    # 生成测试数据（下跌趋势）
    np.random.seed(777)
    dates = pd.date_range(start='2024-01-01', periods=200, freq='h')
    prices = 50000 - np.cumsum(np.random.randn(200) * 100 + 50)  # 下跌趋势

    df = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices + 100,
        'low': prices - 100,
        'close': prices,
        'volume': np.random.randint(5000, 15000, 200)
    })
    df.set_index('timestamp', inplace=True)

    # 测试SHORT信号生成
    print("\n📊 测试SHORT信号生成:")
    print("-" * 70)

    short_gen = ShortSignalGenerator()
    short_count = 0

    for i in range(60, min(100, len(df))):
        current_df = df.iloc[:i+1]
        signal = short_gen.generate_short_signals(current_df)

        if signal['direction'] == 'SHORT':
            short_count += 1
            print(f"Bar {i}: SHORT信号 (置信度: {signal['confidence']:.2%}, 得分: {signal['score']}/{signal['max_score']})")
            print(f"  原因: {', '.join(signal['reasons'])}")

    print(f"\n✅ 共生成 {short_count} 个SHORT信号")

    # 测试方向平衡过滤器
    print("\n" + "=" * 70)
    print("🧪 方向平衡过滤器测试")
    print("=" * 70)

    balance_filter = DirectionalBalanceFilter(max_short_ratio=0.5)

    # 模拟一系列信号
    test_signals = [
        {'direction': 'LONG', 'confidence': 0.7},
        {'direction': 'LONG', 'confidence': 0.75},
        {'direction': 'SHORT', 'confidence': 0.7},
        {'direction': 'SHORT', 'confidence': 0.72},
        {'direction': 'LONG', 'confidence': 0.68},
        {'direction': 'SHORT', 'confidence': 0.7},
    ]

    print("\n📊 信号过滤序列:")
    for i, signal in enumerate(test_signals, 1):
        filtered = balance_filter.filter_signal(signal.copy())

        status = "✅ 通过" if filtered['direction'] != 'NEUTRAL' else "🚫 阻止"
        print(f"信号{i}: {signal['direction']} ({signal['confidence']:.2%}) → {filtered['direction']} ({filtered.get('confidence', 0):.2%}) - {status}")

        if filtered['direction'] != 'NEUTRAL':
            balance_filter.record_trade(filtered['direction'])

    stats = balance_filter.get_statistics()
    print(f"\n📊 最终统计:")
    print(f"  LONG: {stats['long_trades']} ({stats['long_pct']:.1f}%)")
    print(f"  SHORT: {stats['short_trades']} ({stats['short_pct']:.1f}%)")

    print("\n✅ 测试完成")
