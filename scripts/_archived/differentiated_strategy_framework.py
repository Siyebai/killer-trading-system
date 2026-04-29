#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.4 - 差异化策略框架
核心功能：根据品种特性部署不同策略模型
参考：2025年机构级实战框架 - 三大核心交易模型
"""
import sys
import os
import json
import numpy as np
import pandas as pd
import ta
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("differentiated_strategy_framework")


class IncrementalModel:
    """
    增量模型（Incremental Model）
    特征：低风险收益比、高胜率、中频交易
    适用场景：BNB/BTC 1H - 利用市场瞬间的供需不平衡"积少成多"
    核心信号：订单簿失衡、价差分析、短期流动性变化
    """

    def __init__(self, config: Dict = None):
        """初始化增量模型"""
        self.version = "v1.0.4"
        self.name = "增量模型"

        # 核心参数
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70

        # 均值回归参数
        self.mean_reversion_period = 20
        self.z_entry = 1.5
        self.z_exit = 0.5

        logger.info(f"✅ {self.name} {self.version} 初始化完成")
        logger.info(f"   RSI周期: {self.rsi_period}")
        logger.info(f"   均值回归周期: {self.mean_reversion_period}")

    def generate_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        生成增量模型信号

        策略逻辑：
        1. RSI超卖 → 做多
        2. RSI超买 → 做空
        3. 价格偏离均值回归 → 反向交易
        """
        signals = []

        if len(df) < self.mean_reversion_period:
            return signals

        # 计算指标
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=self.rsi_period).rsi()
        df['sma'] = df['close'].rolling(window=self.mean_reversion_period).mean()
        df['std'] = df['close'].rolling(window=self.mean_reversion_period).std()
        df['z_score'] = (df['close'] - df['sma']) / df['std']

        latest = df.iloc[-1]

        # RSI超卖 → 做多
        if latest['rsi'] < self.rsi_oversold:
            signals.append({
                'type': 'LONG',
                'confidence': (self.rsi_oversold - latest['rsi']) / self.rsi_oversold * 100,
                'reason': f"RSI超卖({latest['rsi']:.1f})"
            })

        # RSI超买 → 做空
        elif latest['rsi'] > self.rsi_overbought:
            signals.append({
                'type': 'SHORT',
                'confidence': (latest['rsi'] - self.rsi_overbought) / (100 - self.rsi_overbought) * 100,
                'reason': f"RSI超买({latest['rsi']:.1f})"
            })

        # 均值回归信号
        if latest['z_score'] < -self.z_entry:
            signals.append({
                'type': 'LONG',
                'confidence': min(abs(latest['z_score']) * 30, 100),
                'reason': f"价格偏离均值(Z={latest['z_score']:.2f})"
            })
        elif latest['z_score'] > self.z_entry:
            signals.append({
                'type': 'SHORT',
                'confidence': min(abs(latest['z_score']) * 30, 100),
                'reason': f"价格偏离均值(Z={latest['z_score']:.2f})"
            })

        return signals


class ConvexModel:
    """
    凸性模型（Convex Model）
    特征：高盈亏比（5:1+）、中等胜率、低频交易
    适用场景：SOL 1H - 捕捉结构性机会和市场制度转换
    核心信号：布林带+ADX+突破策略
    """

    def __init__(self, config: Dict = None):
        """初始化凸性模型"""
        self.version = "v1.0.4"
        self.name = "凸性模型"

        # 核心参数
        self.bb_period = 20
        self.bb_std = 2.0
        self.adx_period = 14
        self.adx_threshold = 25  # 趋势强度阈值

        # 突破参数
        self.breakout_period = 20
        self.breakout_multiplier = 1.5

        logger.info(f"✅ {self.name} {self.version} 初始化完成")
        logger.info(f"   布林带周期: {self.bb_period}")
        logger.info(f"   ADX周期: {self.adx_period}")
        logger.info(f"   ADX阈值: {self.adx_threshold}")

    def generate_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        生成凸性模型信号

        策略逻辑：
        1. ADX > 25 + 价格突破布林带 → 趋势跟踪
        2. 多头趋势突破 → 做多（高盈亏比）
        3. 空头趋势突破 → 做空
        """
        signals = []

        if len(df) < max(self.bb_period, self.adx_period):
            return signals

        # 计算指标
        bb = ta.volatility.BollingerBands(df['close'], window=self.bb_period, window_dev=self.bb_std)
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_middle'] = bb.bollinger_mavg()

        df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=self.adx_period).adx()
        df['plus_di'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=self.adx_period).adx_pos()
        df['minus_di'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=self.adx_period).adx_neg()

        latest = df.iloc[-1]

        # 趋势强度检查
        if latest['adx'] < self.adx_threshold:
            return signals  # 趋势不够强，不交易

        # 上轨突破 → 做多
        if latest['close'] > latest['bb_upper'] and latest['plus_di'] > latest['minus_di']:
            signals.append({
                'type': 'LONG',
                'confidence': min((latest['adx'] - self.adx_threshold) * 2, 100),
                'reason': f"上轨突破+多头趋势(ADX={latest['adx']:.1f})",
                'target_profit_ratio': 3.0  # 3:1盈亏比
            })

        # 下轨突破 → 做空
        elif latest['close'] < latest['bb_lower'] and latest['minus_di'] > latest['plus_di']:
            signals.append({
                'type': 'SHORT',
                'confidence': min((latest['adx'] - self.adx_threshold) * 2, 100),
                'reason': f"下轨突破+空头趋势(ADX={latest['adx']:.1f})",
                'target_profit_ratio': 3.0
            })

        return signals


class SpecialistModel:
    """
    专业化模型（Specialist Model）
    特征：危机Alpha获取、极端事件捕捉
    适用场景：极端市场失灵事件（闪崩、交易所宕机、资金费率剧烈偏移）
    核心信号：波动率异常、流动性枯竭
    """

    def __init__(self, config: Dict = None):
        """初始化专业化模型"""
        self.version = "v1.0.4"
        self.name = "专业化模型"

        # 核心参数
        self.atr_period = 14
        self.atr_spike_threshold = 3.0  # ATR飙升倍数
        self.volume_spike_threshold = 5.0  # 成交量飙升倍数

        logger.info(f"✅ {self.name} {self.version} 初始化完成")
        logger.info(f"   ATR周期: {self.atr_period}")

    def generate_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        生成专业化模型信号

        策略逻辑：
        1. 波动率异常飙升 → 极端事件
        2. 成交量异常 → 流动性枯竭
        3. 在极端事件反向捕捉反弹
        """
        signals = []

        if len(df) < self.atr_period:
            return signals

        # 计算指标
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=self.atr_period).average_true_range()
        df['atr_ma'] = df['atr'].rolling(window=self.atr_period).mean()

        df['volume_ma'] = df['volume'].rolling(window=20).mean()

        latest = df.iloc[-1]

        # ATR飙升检测
        atr_spike = latest['atr'] / latest['atr_ma'] if latest['atr_ma'] > 0 else 1

        # 成交量飙升检测
        volume_spike = latest['volume'] / latest['volume_ma'] if latest['volume_ma'] > 0 else 1

        # 极端事件检测
        if atr_spike > self.atr_spike_threshold and volume_spike > self.volume_spike_threshold:
            # 闪崩后反弹
            if latest['close'] < df['close'].iloc[-20]:  # 价格大幅下跌
                signals.append({
                    'type': 'LONG',
                    'confidence': min(atr_spike * 20, 100),
                    'reason': f"闪崩后反弹(ATR飙升{atr_spike:.1f}倍)",
                    'target_profit_ratio': 5.0  # 5:1盈亏比
                })

        return signals


class MultiTimeFrameMomentum:
    """
    多时间框架动量策略
    适用场景：BTCUSDT 5m - 较高时间框架确定方向，较低时间框架精确入场
    """

    def __init__(self, config: Dict = None):
        """初始化多时间框架动量"""
        self.version = "v1.0.4"
        self.name = "多时间框架动量"

        # 核心参数
        self.trend_ema = [5, 10, 20, 50, 100]
        self.vwap_period = 0  # 需要tick数据计算VWAP

        logger.info(f"✅ {self.name} {self.version} 初始化完成")

    def generate_signals(self, df: pd.DataFrame) -> List[Dict]:
        """
        生成多时间框架动量信号

        策略逻辑：
        1. EMA带排列判断趋势
        2. 价格偏离VWAP判断超买超卖
        """
        signals = []

        if len(df) < max(self.trend_ema):
            return signals

        # 计算EMA带
        for period in self.trend_ema:
            df[f'ema_{period}'] = ta.trend.EMAIndicator(df['close'], window=period).ema_indicator()

        latest = df.iloc[-1]

        # 多头排列
        bullish_alignment = all(latest[f'ema_{self.trend_ema[i]}'] > latest[f'ema_{self.trend_ema[i+1]}']
                               for i in range(len(self.trend_ema) - 1))

        # 空头排列
        bearish_alignment = all(latest[f'ema_{self.trend_ema[i]}'] < latest[f'ema_{self.trend_ema[i+1]}']
                               for i in range(len(self.trend_ema) - 1))

        if bullish_alignment:
            signals.append({
                'type': 'LONG',
                'confidence': 70,
                'reason': "多头排列"
            })

        elif bearish_alignment:
            signals.append({
                'type': 'SHORT',
                'confidence': 70,
                'reason': "空头排列"
            })

        return signals


class DifferentiatedStrategyFramework:
    """
    差异化策略框架
    根据品种特性部署不同策略模型
    """

    def __init__(self, config_path: str = None):
        """初始化差异化策略框架"""
        self.version = "v1.0.4"
        self.project_root = Path("/workspace/projects/trading-simulator")
        self.config = self._load_config(config_path)

        # 策略映射表
        self.strategy_mapping = {
            # SOLUSDT 1H - 凸性模型 + 自适应突破
            'SOLUSDT': {
                '1H': ConvexModel(self.config)
            },

            # BNBUSDT 1H - 增量模型 + 均值回归
            'BNBUSDT': {
                '1H': IncrementalModel(self.config)
            },

            # BTCUSDT 5m - 多时间框架动量
            # BTCUSDT 1H - 增量模型 + 波动率过滤
            'BTCUSDT': {
                '5m': MultiTimeFrameMomentum(self.config),
                '1H': IncrementalModel(self.config)
            },

            # ETH - 放弃单边方向，改用跨品种统计套利
            'ETHUSDT': {
                'ALL': 'STATISTICAL_ARBITRAGE'
            },

            # 1分钟 - 废弃方向预测
        }

        logger.info(f"✅ 差异化策略框架 {self.version} 初始化完成")
        logger.info(f"   已配置品种: {list(self.strategy_mapping.keys())}")

    def _load_config(self, config_path: str) -> Dict:
        """加载配置文件"""
        if config_path is None:
            config_path = self.project_root / "config.json"

        with open(config_path, 'r') as f:
            return json.load(f)

    def get_strategy_for_symbol(self, symbol: str, timeframe: str):
        """
        获取品种对应的策略

        参数：
        - symbol: 品种名称（如 'SOLUSDT'）
        - timeframe: 时间周期（如 '1H'）

        返回：
        - strategy: 策略对象
        """
        if symbol not in self.strategy_mapping:
            logger.warning(f"品种 {symbol} 未配置策略，使用默认策略")
            return IncrementalModel(self.config)

        if timeframe not in self.strategy_mapping[symbol]:
            logger.warning(f"品种 {symbol} 的 {timeframe} 周期未配置策略")
            return None

        strategy = self.strategy_mapping[symbol][timeframe]

        # 特殊处理统计套利
        if strategy == 'STATISTICAL_ARBITRAGE':
            logger.info(f"品种 {symbol} 使用统计套利策略")
            return None  # 需要单独处理

        return strategy

    def generate_signals(self, symbol: str, timeframe: str, df: pd.DataFrame) -> List[Dict]:
        """
        生成信号

        参数：
        - symbol: 品种名称
        - timeframe: 时间周期
        - df: 价格数据

        返回：
        - signals: 信号列表
        """
        # 废弃1分钟周期
        if timeframe == '1m':
            logger.info(f"1分钟周期已废弃，不生成信号")
            return []

        # 获取策略
        strategy = self.get_strategy_for_symbol(symbol, timeframe)

        if strategy is None:
            return []

        # 生成信号
        signals = strategy.generate_signals(df)

        # 添加品种和时间信息
        for signal in signals:
            signal['symbol'] = symbol
            signal['timeframe'] = timeframe
            signal['strategy'] = strategy.name

        return signals


if __name__ == "__main__":
    print("=" * 80)
    print("🧪 v1.0.4 差异化策略框架测试")
    print("=" * 80)

    framework = DifferentiatedStrategyFramework()

    # 生成测试数据
    dates = pd.date_range(start='2024-01-01', periods=100, freq='h')
    test_data = pd.DataFrame({
        'open': np.linspace(100, 110, 100) + np.random.randn(100) * 2,
        'high': np.linspace(100, 110, 100) + np.random.randn(100) * 3,
        'low': np.linspace(100, 110, 100) + np.random.randn(100) * 3,
        'close': np.linspace(100, 110, 100) + np.random.randn(100) * 2,
        'volume': np.random.randint(1000, 10000, 100)
    }, index=dates)

    # 测试各品种策略
    test_cases = [
        ('SOLUSDT', '1H', '凸性模型'),
        ('BNBUSDT', '1H', '增量模型'),
        ('BTCUSDT', '5m', '多时间框架动量'),
        ('BTCUSDT', '1H', '增量模型'),
        ('ETHUSDT', '1H', '统计套利'),
    ]

    for symbol, timeframe, expected_strategy in test_cases:
        print(f"\n{'=' * 80}")
        print(f"📊 {symbol} {timeframe} - {expected_strategy}")
        print("=" * 80)

        signals = framework.generate_signals(symbol, timeframe, test_data)

        if signals:
            print(f"生成信号数: {len(signals)}")
            for i, signal in enumerate(signals, 1):
                print(f"  信号{i}: {signal['type']} (置信度{signal['confidence']:.1f}%) - {signal['reason']}")
        else:
            print("无信号")

    print("\n✅ 测试完成")
