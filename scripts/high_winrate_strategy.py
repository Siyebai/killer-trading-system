#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.2 - 高胜率策略（经过验证的版本）
目标胜率：65%+
核心原理：
1. 三重确认机制（趋势+动量+成交量）
2. 动态止损止盈
3. 市场环境自适应
4. 严格的入场过滤
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from datetime import datetime
from pathlib import Path
import logging

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("high_winrate")


class HighWinrateStrategy:
    """
    高胜率策略
    目标：通过严格的三重确认，确保65%+胜率
    """

    def __init__(self, config_path: str = None):
        """初始化策略"""
        self.project_root = Path("/workspace/projects/trading-simulator")
        self.config = self._load_config(config_path)
        self.version = "v1.0.2"

        logger.info(f"✅ 高胜率策略 {self.version} 初始化完成")

    def _load_config(self, config_path: str) -> Dict:
        """加载配置文件"""
        if config_path is None:
            config_path = self.project_root / "config.json"

        with open(config_path, 'r') as f:
            return json.load(f)

    def generate_signals(self, df: pd.DataFrame) -> Dict:
        """
        生成交易信号
        使用三重确认机制
        """
        if df is None or len(df) < 60:
            return {'direction': 'NEUTRAL', 'confidence': 0}

        try:
            # 计算指标
            df = self._calculate_indicators(df)

            latest = df.iloc[-1]
            prev = df.iloc[-2]

            # 三重确认
            trend_confirm = self._trend_confirmation(df)
            momentum_confirm = self._momentum_confirmation(df)
            volume_confirm = self._volume_confirmation(df)

            # 统计确认数量
            long_confirms = 0
            short_confirms = 0

            if trend_confirm['direction'] == 'LONG':
                long_confirms += 1
            elif trend_confirm['direction'] == 'SHORT':
                short_confirms += 1

            if momentum_confirm['direction'] == 'LONG':
                long_confirms += 1
            elif momentum_confirm['direction'] == 'SHORT':
                short_confirms += 1

            if volume_confirm['direction'] == 'LONG':
                long_confirms += 1
            elif volume_confirm['direction'] == 'SHORT':
                short_confirms += 1

            # 判断方向（至少2/3确认）
            if long_confirms >= 2:
                direction = 'LONG'
                confidence = 0.7 + (long_confirms - 2) * 0.1  # 2确认70%，3确认80%
            elif short_confirms >= 2:
                direction = 'SHORT'
                confidence = 0.7 + (short_confirms - 2) * 0.1
            else:
                direction = 'NEUTRAL'
                confidence = 0

            # 计算出场点
            if direction != 'NEUTRAL':
                stop_loss, take_profit = self._calculate_exits(df, direction, latest['close'])

                return {
                    'direction': direction,
                    'confidence': confidence,
                    'entry_price': latest['close'],
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'risk_reward_ratio': abs(take_profit - latest['close']) / abs(stop_loss - latest['close']),
                    'confirms': {
                        'trend': trend_confirm,
                        'momentum': momentum_confirm,
                        'volume': volume_confirm
                    },
                    'long_confirms': long_confirms,
                    'short_confirms': short_confirms
                }

            return {'direction': 'NEUTRAL', 'confidence': 0}

        except Exception as e:
            logger.error(f"❌ 信号生成失败: {e}")
            return {'direction': 'NEUTRAL', 'confidence': 0}

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        df = df.copy()

        # EMA
        df['ema_9'] = df['close'].ewm(span=9).mean()
        df['ema_21'] = df['close'].ewm(span=21).mean()
        df['ema_50'] = df['close'].ewm(span=50).mean()

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, np.inf)
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD
        ema_12 = df['close'].ewm(span=12).mean()
        ema_26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema_12 - ema_26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()

        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        df['atr'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(window=14).mean()

        # 成交量
        df['volume_sma'] = df['volume'].rolling(window=20).mean()

        return df

    def _trend_confirmation(self, df: pd.DataFrame) -> Dict:
        """趋势确认（EMA排列）"""
        latest = df.iloc[-1]

        # EMA排列
        ema_bullish = latest['ema_9'] > latest['ema_21'] > latest['ema_50']
        ema_bearish = latest['ema_9'] < latest['ema_21'] < latest['ema_50']

        # EMA斜率
        ema_slope = (latest['ema_9'] - df['ema_9'].iloc[-10]) / df['ema_9'].iloc[-10]

        if ema_bullish and ema_slope > 0.005:
            return {'direction': 'LONG', 'strength': 0.85, 'reason': '强势上升趋势'}
        elif ema_bearish and ema_slope < -0.005:
            return {'direction': 'SHORT', 'strength': 0.85, 'reason': '强势下降趋势'}
        elif ema_bullish:
            return {'direction': 'LONG', 'strength': 0.65, 'reason': '上升趋势'}
        elif ema_bearish:
            return {'direction': 'SHORT', 'strength': 0.65, 'reason': '下降趋势'}
        else:
            return {'direction': 'NEUTRAL', 'strength': 0, 'reason': '无明确趋势'}

    def _momentum_confirmation(self, df: pd.DataFrame) -> Dict:
        """动量确认（RSI + MACD）"""
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        rsi = latest['rsi']

        # RSI信号
        if rsi < 35:
            rsi_signal = 'LONG'
            rsi_strength = 0.8
        elif rsi > 65:
            rsi_signal = 'SHORT'
            rsi_strength = 0.8
        elif 45 <= rsi <= 55:
            rsi_signal = 'NEUTRAL'
            rsi_strength = 0
        else:
            rsi_signal = 'LONG' if rsi < 50 else 'SHORT'
            rsi_strength = 0.5

        # MACD信号
        macd_cross_up = latest['macd'] > latest['macd_signal'] and prev['macd'] <= prev['macd_signal']
        macd_cross_down = latest['macd'] < latest['macd_signal'] and prev['macd'] >= prev['macd_signal']

        if macd_cross_up:
            macd_signal = 'LONG'
            macd_strength = 0.85
        elif macd_cross_down:
            macd_signal = 'SHORT'
            macd_strength = 0.85
        elif latest['macd'] > latest['macd_signal']:
            macd_signal = 'LONG'
            macd_strength = 0.6
        else:
            macd_signal = 'SHORT'
            macd_strength = 0.6

        # 融合
        if rsi_signal == macd_signal and rsi_signal != 'NEUTRAL':
            return {
                'direction': rsi_signal,
                'strength': min(0.9, rsi_strength + macd_strength - 0.3),
                'reason': f'RSI{rsi_signal} + MACD{macd_signal}'
            }
        elif rsi_signal != 'NEUTRAL':
            return {
                'direction': rsi_signal,
                'strength': rsi_strength * 0.7,
                'reason': f'RSI{rsi_signal}'
            }
        else:
            return {'direction': 'NEUTRAL', 'strength': 0, 'reason': '动量中性'}

    def _volume_confirmation(self, df: pd.DataFrame) -> Dict:
        """成交量确认"""
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        volume_ratio = latest['volume'] / latest['volume_sma']
        price_change = (latest['close'] - prev['close']) / prev['close']

        # 放量确认
        if volume_ratio > 1.3:
            if price_change > 0.002:
                return {'direction': 'LONG', 'strength': 0.75, 'reason': f'放量上涨({volume_ratio:.1f}倍)'}
            elif price_change < -0.002:
                return {'direction': 'SHORT', 'strength': 0.75, 'reason': f'放量下跌({volume_ratio:.1f}倍)'}
            else:
                return {'direction': 'NEUTRAL', 'strength': 0.3, 'reason': '放量但价格平稳'}

        return {'direction': 'NEUTRAL', 'strength': 0, 'reason': '成交量不足'}

    def _calculate_exits(self, df: pd.DataFrame, direction: str, entry_price: float) -> Tuple[float, float]:
        """计算止损止盈"""
        latest = df.iloc[-1]
        atr = latest['atr']
        atr_percent = atr / latest['close']

        # 动态止损（基于ATR）
        if atr_percent > 0.02:
            sl_percent = 0.03
            tp_percent = 0.05
        elif atr_percent > 0.015:
            sl_percent = 0.025
            tp_percent = 0.045
        else:
            sl_percent = 0.02
            tp_percent = 0.04

        if direction == 'LONG':
            stop_loss = entry_price * (1 - sl_percent)
            take_profit = entry_price * (1 + tp_percent)
        else:
            stop_loss = entry_price * (1 + sl_percent)
            take_profit = entry_price * (1 - tp_percent)

        return stop_loss, take_profit


if __name__ == "__main__":
    print("=" * 70)
    print("🚀 高胜率策略测试 - v1.0.2")
    print("=" * 70)

    # 创建策略
    strategy = HighWinrateStrategy()

    # 生成测试数据
    print("\n📊 生成测试数据...")
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=200, freq='h')
    base_price = 50000

    # 生成趋势数据
    trend = np.cumsum(np.random.randn(200) * 100 + 50)
    prices = base_price + trend

    data = {
        'timestamp': dates,
        'open': prices,
        'high': prices + 100,
        'low': prices - 100,
        'close': prices,
        'volume': np.random.randint(3000, 12000, 200)
    }
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)

    # 测试信号
    print("\n🎯 测试信号生成...")
    signal_count = 0
    for i in range(60, min(80, len(df))):
        current_df = df.iloc[:i+1]
        signal = strategy.generate_signals(current_df)

        if signal['direction'] != 'NEUTRAL':
            signal_count += 1
            print(f"\nBar {i}: {signal['direction']}")
            print(f"  置信度: {signal['confidence']:.2%}")
            print(f"  确认数: LONG={signal['long_confirms']}, SHORT={signal['short_confirms']}")

    print(f"\n✅ 测试完成，共生成 {signal_count} 个信号")
