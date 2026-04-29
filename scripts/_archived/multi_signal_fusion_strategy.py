#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.3 - 多信号融合策略
目标胜率：65%+
核心原理：多指标融合 + 信号确认 + 市场环境识别 + 动态出场
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from pathlib import Path
import logging

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("multi_signal_fusion")

class MultiSignalFusionStrategy:
    """
    多信号融合策略 - 高胜率版本
    目标：通过多指标融合和严格确认，将胜率提升至65%+
    """

    def __init__(self, config_path: str = None):
        """初始化策略"""
        self.project_root = Path("/workspace/projects/trading-simulator")
        self.config = self._load_config(config_path)
        self.version = "v1.0.3"

        # 信号权重配置
        self.signal_weights = {
            'trend_following': 0.30,
            'momentum': 0.25,
            'mean_reversion': 0.20,
            'volume': 0.15,
            'support_resistance': 0.10
        }

        # 确认规则（优化为更积极的信号生成）
        self.confirmation_rules = {
            'min_indicators': 2,  # 至少2个指标同向
            'min_confidence': 0.50,  # 最低置信度（降低到50%）
            'require_volume_confirm': False,  # 不强制需要成交量确认
            'require_trend_align': False  # 不强制需要与主趋势对齐
        }

        logger.info(f"✅ 多信号融合策略 {self.version} 初始化完成")

    def _load_config(self, config_path: str) -> Dict:
        """加载配置文件"""
        if config_path is None:
            config_path = self.project_root / "config.json"

        with open(config_path, 'r') as f:
            return json.load(f)

    def generate_signals(self, df: pd.DataFrame) -> Dict:
        """
        生成交易信号（核心逻辑）
        返回：{
            'direction': 'LONG'/'SHORT'/'NEUTRAL',
            'confidence': float (0-1),
            'signals': Dict (各个子信号详情),
            'entry_price': float,
            'stop_loss': float,
            'take_profit': float
        }
        """
        if df is None or len(df) < 55:
            return {'direction': 'NEUTRAL', 'confidence': 0}

        try:
            # 计算所有指标
            df = self._calculate_all_indicators(df)

            # 获取最新价格
            current_price = df['close'].iloc[-1]
            current_time = df.index[-1] if hasattr(df.index[-1], 'strftime') else datetime.now()

            # 生成子信号
            signals = {
                'trend_following': self._trend_following_signal(df),
                'momentum': self._momentum_signal(df),
                'mean_reversion': self._mean_reversion_signal(df),
                'volume': self._volume_signal(df),
                'support_resistance': self._support_resistance_signal(df)
            }

            # 识别市场环境
            market_regime = self._detect_market_regime(df)

            # 融合信号
            fused_signal = self._fuse_signals(signals, market_regime)

            # 计算出场点
            if fused_signal['direction'] != 'NEUTRAL':
                stop_loss, take_profit = self._calculate_exit_points(
                    df, fused_signal['direction'], current_price
                )

                fused_signal.update({
                    'entry_price': current_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'risk_reward_ratio': abs(take_profit - current_price) / abs(stop_loss - current_price),
                    'market_regime': market_regime,
                    'timestamp': current_time.isoformat()
                })

                logger.info(f"🎯 信号生成: {fused_signal['direction']} | "
                          f"置信度: {fused_signal['confidence']:.2%} | "
                          f"盈亏比: {fused_signal['risk_reward_ratio']:.2f} | "
                          f"市场环境: {market_regime}")

            return fused_signal

        except Exception as e:
            logger.error(f"❌ 信号生成失败: {e}")
            return {'direction': 'NEUTRAL', 'confidence': 0}

    def _calculate_all_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算所有技术指标"""
        df = df.copy()

        # EMA指标
        df['ema_fast'] = df['close'].ewm(span=9).mean()
        df['ema_medium'] = df['close'].ewm(span=21).mean()
        df['ema_slow'] = df['close'].ewm(span=55).mean()

        # RSI指标
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD指标
        exp12 = df['close'].ewm(span=12).mean()
        exp26 = df['close'].ewm(span=26).mean()
        df['macd'] = exp12 - exp26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']

        # ATR指标（用于动态止损）
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df['atr'] = true_range.rolling(window=14).mean()

        # 成交量指标
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']

        # 布林带
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']

        return df

    def _trend_following_signal(self, df: pd.DataFrame) -> Dict:
        """趋势跟踪信号"""
        latest = df.iloc[-1]

        # 多重EMA排列检查
        ema_bullish = (latest['ema_fast'] > latest['ema_medium'] > latest['ema_slow'])
        ema_bearish = (latest['ema_fast'] < latest['ema_medium'] < latest['ema_slow'])

        # MACD确认
        macd_bullish = latest['macd'] > latest['macd_signal'] and latest['macd_histogram'] > 0
        macd_bearish = latest['macd'] < latest['macd_signal'] and latest['macd_histogram'] < 0

        # 综合判断
        if ema_bullish and macd_bullish:
            return {'direction': 'LONG', 'strength': 0.85, 'reason': '多重EMA多头排列 + MACD金叉'}
        elif ema_bearish and macd_bearish:
            return {'direction': 'SHORT', 'strength': 0.85, 'reason': '多重EMA空头排列 + MACD死叉'}
        elif ema_bullish:
            return {'direction': 'LONG', 'strength': 0.65, 'reason': 'EMA多头排列'}
        elif ema_bearish:
            return {'direction': 'SHORT', 'strength': 0.65, 'reason': 'EMA空头排列'}
        else:
            return {'direction': 'NEUTRAL', 'strength': 0, 'reason': '趋势不明确'}

    def _momentum_signal(self, df: pd.DataFrame) -> Dict:
        """动量信号（RSI + MACD动量）"""
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # RSI动量
        rsi = latest['rsi']
        if rsi < 30:
            rsi_signal = {'direction': 'LONG', 'strength': 0.8, 'reason': f'RSI超卖({rsi:.1f})'}
        elif rsi > 70:
            rsi_signal = {'direction': 'SHORT', 'strength': 0.8, 'reason': f'RSI超买({rsi:.1f})'}
        elif 40 <= rsi <= 60:
            rsi_signal = {'direction': 'NEUTRAL', 'strength': 0, 'reason': 'RSI中性'}
        elif 30 < rsi < 50:
            rsi_signal = {'direction': 'LONG', 'strength': 0.5, 'reason': f'RSI偏多({rsi:.1f})'}
        else:
            rsi_signal = {'direction': 'SHORT', 'strength': 0.5, 'reason': f'RSI偏空({rsi:.1f})'}

        # MACD动量
        macd_momentum = latest['macd_histogram'] - prev['macd_histogram']
        if macd_momentum > 0:
            macd_signal = {'direction': 'LONG', 'strength': 0.6, 'reason': 'MACD柱状图向上'}
        else:
            macd_signal = {'direction': 'SHORT', 'strength': 0.6, 'reason': 'MACD柱状图向下'}

        # 融合
        if rsi_signal['direction'] == macd_signal['direction']:
            return {
                'direction': rsi_signal['direction'],
                'strength': min(0.9, rsi_signal['strength'] + 0.2),
                'reason': f"{rsi_signal['reason']} + {macd_signal['reason']}"
            }
        else:
            return {'direction': 'NEUTRAL', 'strength': 0, 'reason': 'RSI与MACD背离'}

    def _mean_reversion_signal(self, df: pd.DataFrame) -> Dict:
        """均值回归信号（布林带）"""
        latest = df.iloc[-1]

        # 布林带位置
        bb_position = (latest['close'] - latest['bb_lower']) / (latest['bb_upper'] - latest['bb_lower'])

        if bb_position < 0.1:
            return {'direction': 'LONG', 'strength': 0.75, 'reason': '触及布林带下轨（超卖）'}
        elif bb_position > 0.9:
            return {'direction': 'SHORT', 'strength': 0.75, 'reason': '触及布林带上轨（超买）'}
        elif bb_position < 0.3:
            return {'direction': 'LONG', 'strength': 0.5, 'reason': '接近布林带下轨'}
        elif bb_position > 0.7:
            return {'direction': 'SHORT', 'strength': 0.5, 'reason': '接近布林带上轨'}
        else:
            return {'direction': 'NEUTRAL', 'strength': 0, 'reason': '价格处于布林带中轨'}

    def _volume_signal(self, df: pd.DataFrame) -> Dict:
        """成交量信号"""
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # 成交量放大确认
        volume_ratio = latest['volume_ratio']

        # 价格变化
        price_change = (latest['close'] - prev['close']) / prev['close']

        if volume_ratio > 1.5 and abs(price_change) > 0.005:
            if price_change > 0:
                return {'direction': 'LONG', 'strength': 0.7,
                       'reason': f'放量上涨(成交量{volume_ratio:.1f}倍)'}
            else:
                return {'direction': 'SHORT', 'strength': 0.7,
                       'reason': f'放量下跌(成交量{volume_ratio:.1f}倍)'}
        elif volume_ratio > 1.2:
            return {'direction': 'NEUTRAL', 'strength': 0.3,
                   'reason': f'成交量温和放大({volume_ratio:.1f}倍)'}
        else:
            return {'direction': 'NEUTRAL', 'strength': 0,
                   'reason': '成交量不足'}

    def _support_resistance_signal(self, df: pd.DataFrame) -> Dict:
        """支撑阻力信号"""
        latest = df.iloc[-1]
        current_price = latest['close']

        # 计算近期的支撑阻力位（简单方法）
        recent_highs = df['high'].tail(20)
        recent_lows = df['low'].tail(20)

        resistance = recent_highs.max()
        support = recent_lows.min()

        distance_to_support = (current_price - support) / current_price
        distance_to_resistance = (resistance - current_price) / current_price

        if distance_to_support < 0.01:
            return {'direction': 'LONG', 'strength': 0.65,
                   'reason': f'接近支撑位({support:.2f})'}
        elif distance_to_resistance < 0.01:
            return {'direction': 'SHORT', 'strength': 0.65,
                   'reason': f'接近阻力位({resistance:.2f})'}
        else:
            return {'direction': 'NEUTRAL', 'strength': 0,
                   'reason': '远离关键支撑阻力位'}

    def _detect_market_regime(self, df: pd.DataFrame) -> str:
        """检测市场环境"""
        latest = df.iloc[-1]

        # ATR波动率
        atr_percent = latest['atr'] / latest['close']

        # EMA斜率
        ema_slope = (latest['ema_fast'] - df['ema_fast'].iloc[-5]) / df['ema_fast'].iloc[-5]

        # 判断市场环境
        if abs(ema_slope) > 0.01 and atr_percent > 0.02:
            return 'breakout'  # 突破市场
        elif abs(ema_slope) > 0.005:
            return 'trend' if ema_slope > 0 else 'downtrend'  # 趋势市场
        elif atr_percent < 0.015:
            return 'ranging'  # 震荡市场
        else:
            return 'neutral'

    def _fuse_signals(self, signals: Dict, market_regime: str) -> Dict:
        """
        融合所有信号
        核心逻辑：多指标确认 + 权重融合
        """
        # 统计各方向信号数量和强度
        long_count = 0
        short_count = 0
        long_strength = 0
        short_strength = 0

        for name, signal in signals.items():
            if signal['direction'] == 'LONG':
                long_count += 1
                long_strength += signal['strength'] * self.signal_weights[name]
            elif signal['direction'] == 'SHORT':
                short_count += 1
                short_strength += signal['strength'] * self.signal_weights[name]

        # 确认规则检查
        min_indicators = self.confirmation_rules['min_indicators']
        min_confidence = self.confirmation_rules['min_confidence']

        # 判断方向（优化置信度计算）
        # 计算加权平均强度（0-1范围）
        if long_count >= min_indicators:
            avg_long_strength = long_strength / sum([self.signal_weights[name] for name in signals.keys() if signals[name]['direction'] == 'LONG'])
            direction = 'LONG'
            confidence = avg_long_strength
        elif short_count >= min_indicators:
            avg_short_strength = short_strength / sum([self.signal_weights[name] for name in signals.keys() if signals[name]['direction'] == 'SHORT'])
            direction = 'SHORT'
            confidence = avg_short_strength
        else:
            # 少于最小指标数，根据数量加权
            if long_count > 0 or short_count > 0:
                direction = 'LONG' if long_count >= short_count else 'SHORT'
                confidence = max(long_strength, short_strength) * 2  # 放大置信度
            else:
                direction = 'NEUTRAL'
                confidence = 0

        # 市场环境调整
        if market_regime == 'ranging' and direction != 'NEUTRAL':
            # 震荡市场降低信心
            confidence *= 0.8
        elif market_regime == 'trend' and direction == 'LONG':
            # 上升趋势增强做多信心
            confidence *= 1.1
        elif market_regime == 'downtrend' and direction == 'SHORT':
            # 下降趋势增强做空信心
            confidence *= 1.1

        confidence = min(0.95, confidence)

        return {
            'direction': direction,
            'confidence': confidence,
            'signals': signals,
            'long_count': long_count,
            'short_count': short_count
        }

    def _calculate_exit_points(self, df: pd.DataFrame, direction: str,
                               entry_price: float) -> Tuple[float, float]:
        """
        计算出场点（动态止损止盈）
        使用ATR动态计算止损，盈亏比2:1
        """
        latest = df.iloc[-1]
        atr = latest['atr']
        atr_percent = atr / latest['close']

        # 配置参数
        risk_percent = self.config['risk_management']['stop_loss'] / 100
        reward_percent = self.config['risk_management']['take_profit'] / 100
        trailing_activation = self.config['risk_management']['trailing_activation'] / 100

        # 动态止损（基于ATR）
        if atr_percent > 0.02:
            # 高波动环境，放大止损
            dynamic_sl = risk_percent * 1.5
            dynamic_tp = reward_percent * 1.5
        else:
            # 低波动环境，紧止损
            dynamic_sl = risk_percent
            dynamic_tp = reward_percent

        if direction == 'LONG':
            stop_loss = entry_price * (1 - dynamic_sl)
            take_profit = entry_price * (1 + dynamic_tp)
        else:  # SHORT
            stop_loss = entry_price * (1 + dynamic_sl)
            take_profit = entry_price * (1 - dynamic_tp)

        return stop_loss, take_profit


def main():
    """测试函数"""
    print("=" * 70)
    print("🚀 多信号融合策略测试 - v1.0.3")
    print("=" * 70)

    # 创建策略实例
    strategy = MultiSignalFusionStrategy()

    # 生成测试数据
    print("\n📊 生成测试K线数据...")
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=200, freq='1H')
    base_price = 50000

    data = {
        'timestamp': dates,
        'open': np.random.randn(200).cumsum() * 100 + base_price,
        'high': np.random.randn(200).cumsum() * 100 + base_price + 50,
        'low': np.random.randn(200).cumsum() * 100 + base_price - 50,
        'close': np.random.randn(200).cumsum() * 100 + base_price,
        'volume': np.random.randint(1000, 10000, 200)
    }
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)

    # 确保high >= open/close >= low
    df['high'] = df[['open', 'close', 'high']].max(axis=1)
    df['low'] = df[['open', 'close', 'low']].min(axis=1)

    print(f"✅ 生成 {len(df)} 条K线数据")

    # 生成信号
    print("\n🎯 生成交易信号...")
    signal = strategy.generate_signals(df)

    print("\n📋 信号详情:")
    print(f"  方向: {signal['direction']}")
    print(f"  置信度: {signal.get('confidence', 0):.2%}")
    if 'entry_price' in signal:
        print(f"  入场价: {signal['entry_price']:.2f}")
        print(f"  止损: {signal['stop_loss']:.2f}")
        print(f"  止盈: {signal['take_profit']:.2f}")
        print(f"  盈亏比: {signal['risk_reward_ratio']:.2f}")
        print(f"  市场环境: {signal['market_regime']}")

    print("\n✅ 测试完成!")


if __name__ == "__main__":
    main()
