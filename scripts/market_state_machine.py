#!/usr/bin/env python3
"""
杀手锏交易系统 v5.0 - 市场状态机
核心功能：识别震荡/趋势/极端三种市场状态，动态切换策略

关键发现：均值回归策略在单边下跌中天然劣势，不是参数问题
解决方案：市场状态机动态切换策略，全天候稳定

状态定义：
- RANGING（震荡）：均值回归策略，高胜率低频
- TRENDING（趋势）：趋势跟踪策略，中频中EV
- EXTREME（极端）：危机Alpha策略，超低频高EV
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
from enum import Enum
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("market_state_machine")


class MarketState(Enum):
    """市场状态枚举"""
    RANGING = "RANGING"      # 震荡市 - 均值回归
    TRENDING_UP = "TRENDING_UP"    # 上升趋势 - 趋势跟踪做多
    TRENDING_DOWN = "TRENDING_DOWN"  # 下降趋势 - 趋势跟踪做空
    EXTREME_VOL = "EXTREME_VOL"    # 极端波动 - 危机Alpha


class MarketStateMachine:
    """
    市场状态机 - 核心决策层

    状态转换逻辑：
    RANGING <-> TRENDING_UP <-> EXTREME_VOL
    RANGING <-> TRENDING_DOWN <-> EXTREME_VOL

    识别指标：
    1. ADX(14) - 趋势强度
    2. ATR(14)/Price - 波动率
    3. EMA斜率 - 方向
    4. 价格位置 vs 布林带 - 极端程度
    """

    def __init__(self, config_path: str = None):
        """初始化市场状态机"""
        self.version = "v5.0"
        self.project_root = Path("/workspace/projects/trading-simulator")
        self.config = self._load_config(config_path)

        # 状态阈值
        self.adx_trend_threshold = 25       # ADX > 25 为趋势市
        self.adx_strong_threshold = 40      # ADX > 40 为强趋势
        self.vol_extreme_threshold = 0.05   # ATR/Price > 5% 为极端波动
        self.bb_extreme_threshold = 2.5     # 布林带2.5标准差
        self.ema_slope_threshold = 0.001    # EMA斜率阈值

        # 当前状态
        self.current_state = MarketState.RANGING
        self.state_history = []
        self.state_confidence = 0.0

        # 策略权重映射
        self.strategy_weights = {
            MarketState.RANGING: {
                'mean_reversion': 0.7,
                'trend_following': 0.2,
                'funding_rate_arb': 0.1
            },
            MarketState.TRENDING_UP: {
                'mean_reversion': 0.1,
                'trend_following': 0.8,
                'funding_rate_arb': 0.1
            },
            MarketState.TRENDING_DOWN: {
                'mean_reversion': 0.1,
                'trend_following': 0.8,
                'funding_rate_arb': 0.1
            },
            MarketState.EXTREME_VOL: {
                'mean_reversion': 0.0,
                'trend_following': 0.3,
                'funding_rate_arb': 0.7
            }
        }

        logger.info(f"[OK] 市场状态机 {self.version} 初始化完成")
        logger.info(f"   ADX趋势阈值: {self.adx_trend_threshold}")
        logger.info(f"   波动极端阈值: {self.vol_extreme_threshold}")

    def _load_config(self, config_path: str) -> Dict:
        """加载配置文件"""
        if config_path is None:
            config_path = self.project_root / "config.json"
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def detect_state(self, df: pd.DataFrame) -> Tuple[MarketState, float]:
        """
        检测当前市场状态

        参数：
        - df: OHLCV数据，至少需要50根K线

        返回：
        - (state, confidence): 市场状态和置信度
        """
        if df is None or len(df) < 50:
            return MarketState.RANGING, 0.0

        # 计算识别指标
        indicators = self._calculate_indicators(df)

        # 状态判断逻辑
        adx = indicators['adx']
        vol_ratio = indicators['vol_ratio']
        ema_slope = indicators['ema_slope']
        bb_position = indicators['bb_position']
        plus_di = indicators['plus_di']
        minus_di = indicators['minus_di']

        # 极端波动检测（最高优先级）
        if vol_ratio > self.vol_extreme_threshold:
            state = MarketState.EXTREME_VOL
            confidence = min((vol_ratio / self.vol_extreme_threshold - 1) * 50 + 50, 100)
            self._update_state(state, confidence, indicators)
            return state, confidence

        # 趋势市检测
        if adx > self.adx_trend_threshold:
            if plus_di > minus_di and ema_slope > self.ema_slope_threshold:
                state = MarketState.TRENDING_UP
                confidence = min((adx - self.adx_trend_threshold) * 3, 100)
            elif minus_di > plus_di and ema_slope < -self.ema_slope_threshold:
                state = MarketState.TRENDING_DOWN
                confidence = min((adx - self.adx_trend_threshold) * 3, 100)
            else:
                # ADX高但方向不明确
                state = MarketState.RANGING
                confidence = 30

            self._update_state(state, confidence, indicators)
            return state, confidence

        # 默认震荡市
        state = MarketState.RANGING
        confidence = max(50 - adx, 10)
        self._update_state(state, confidence, indicators)
        return state, confidence

    def _calculate_indicators(self, df: pd.DataFrame) -> Dict:
        """计算市场状态识别指标"""
        try:
            import ta
        except ImportError:
            return self._calc_manual(df)

        try:
            close = df['close']
            high = df['high']
            low = df['low']

            # ADX
            adx_indicator = ta.trend.ADXIndicator(high, low, close, window=14)
            adx = adx_indicator.adx().iloc[-1] if len(adx_indicator.adx()) > 0 else 20
            plus_di = adx_indicator.adx_pos().iloc[-1] if len(adx_indicator.adx_pos()) > 0 else 25
            minus_di = adx_indicator.adx_neg().iloc[-1] if len(adx_indicator.adx_neg()) > 0 else 25

            # ATR/Price 波动率
            atr = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
            atr_val = atr.iloc[-1] if len(atr) > 0 else close.iloc[-1] * 0.02
            vol_ratio = atr_val / close.iloc[-1]

            # EMA斜率
            ema20 = close.ewm(span=20).mean()
            if len(ema20) >= 2:
                ema_slope = (ema20.iloc[-1] - ema20.iloc[-2]) / ema20.iloc[-2]
            else:
                ema_slope = 0

            # 布林带位置
            bb = ta.volatility.BollingerBands(close, window=20, window_dev=2.5)
            bb_upper = bb.bollinger_hband().iloc[-1]
            bb_lower = bb.bollinger_lband().iloc[-1]
            bb_mid = bb.bollinger_mavg().iloc[-1]

            if bb_upper > bb_lower:
                bb_position = (close.iloc[-1] - bb_mid) / (bb_upper - bb_lower) * 2
            else:
                bb_position = 0

            return {
                'adx': float(adx) if not np.isnan(adx) else 20,
                'plus_di': float(plus_di) if not np.isnan(plus_di) else 25,
                'minus_di': float(minus_di) if not np.isnan(minus_di) else 25,
                'vol_ratio': float(vol_ratio),
                'ema_slope': float(ema_slope),
                'bb_position': float(bb_position)
            }
        except Exception as e:
            logger.warning(f"指标计算异常: {e}，使用手动计算")
            return self._calc_manual(df)

    def _calc_manual(self, df: pd.DataFrame) -> Dict:
        """手动计算指标（无ta库时回退）"""
        close = df['close']
        high = df['high']
        low = df['low']

        # 简易ATR
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr_val = tr.rolling(14).mean().iloc[-1]
        vol_ratio = atr_val / close.iloc[-1]

        # 简易EMA斜率
        ema20 = close.ewm(span=20).mean()
        ema_slope = (ema20.iloc[-1] - ema20.iloc[-2]) / ema20.iloc[-2] if len(ema20) >= 2 else 0

        return {
            'adx': 20.0,
            'plus_di': 25.0,
            'minus_di': 25.0,
            'vol_ratio': float(vol_ratio),
            'ema_slope': float(ema_slope),
            'bb_position': 0.0
        }

    def _update_state(self, state: MarketState, confidence: float, indicators: Dict):
        """更新当前状态"""
        old_state = self.current_state
        self.current_state = state
        self.state_confidence = confidence

        self.state_history.append({
            'timestamp': datetime.now().isoformat(),
            'state': state.value,
            'confidence': confidence,
            'indicators': indicators
        })

        # 只保留最近100条记录
        if len(self.state_history) > 100:
            self.state_history = self.state_history[-100:]

        if old_state != state:
            logger.info(f"[STATE] 市场状态切换: {old_state.value} -> {state.value} (置信度{confidence:.1f}%)")

    def get_strategy_weights(self, state: Optional[MarketState] = None) -> Dict:
        """获取当前市场状态下的策略权重"""
        if state is None:
            state = self.current_state
        return self.strategy_weights.get(state, self.strategy_weights[MarketState.RANGING])

    def get_state_summary(self) -> Dict:
        """获取状态摘要"""
        state_counts = {}
        for record in self.state_history:
            s = record['state']
            state_counts[s] = state_counts.get(s, 0) + 1

        return {
            'current_state': self.current_state.value,
            'confidence': self.state_confidence,
            'state_distribution': state_counts,
            'strategy_weights': self.get_strategy_weights()
        }


if __name__ == "__main__":
    print("=" * 80)
    print("Market State Machine v5.0 Test")
    print("=" * 80)

    msm = MarketStateMachine()

    # Generate test data for different market states
    np.random.seed(42)

    # Test 1: Ranging market
    print("\n--- Test 1: Ranging Market ---")
    dates = pd.date_range(start='2024-01-01', periods=200, freq='h')
    ranging_data = pd.DataFrame({
        'open': 100 + np.random.randn(200) * 0.5,
        'high': 100 + np.random.randn(200) * 0.8,
        'low': 100 + np.random.randn(200) * 0.8,
        'close': 100 + np.random.randn(200) * 0.5,
        'volume': np.random.randint(1000, 10000, 200)
    }, index=dates)

    state, conf = msm.detect_state(ranging_data)
    weights = msm.get_strategy_weights(state)
    print(f"  State: {state.value}, Confidence: {conf:.1f}%")
    print(f"  Strategy Weights: {weights}")

    # Test 2: Trending market
    print("\n--- Test 2: Trending Market ---")
    trend_data = pd.DataFrame({
        'open': np.linspace(100, 120, 200) + np.random.randn(200) * 0.3,
        'high': np.linspace(100, 120, 200) + np.random.randn(200) * 0.5,
        'low': np.linspace(100, 120, 200) + np.random.randn(200) * 0.5,
        'close': np.linspace(100, 120, 200) + np.random.randn(200) * 0.3,
        'volume': np.random.randint(1000, 10000, 200)
    }, index=dates)

    state, conf = msm.detect_state(trend_data)
    weights = msm.get_strategy_weights(state)
    print(f"  State: {state.value}, Confidence: {conf:.1f}%")
    print(f"  Strategy Weights: {weights}")

    # Test 3: Extreme volatility
    print("\n--- Test 3: Extreme Volatility ---")
    extreme_data = pd.DataFrame({
        'open': 100 + np.random.randn(200) * 10,
        'high': 100 + np.random.randn(200) * 15,
        'low': 100 + np.random.randn(200) * 15,
        'close': 100 + np.random.randn(200) * 10,
        'volume': np.random.randint(1000, 10000, 200)
    }, index=dates)

    state, conf = msm.detect_state(extreme_data)
    weights = msm.get_strategy_weights(state)
    print(f"  State: {state.value}, Confidence: {conf:.1f}%")
    print(f"  Strategy Weights: {weights}")

    print("\n--- State Summary ---")
    summary = msm.get_state_summary()
    print(f"  Current: {summary['current_state']}")
    print(f"  Distribution: {summary['state_distribution']}")

    print("\n[OK] Market State Machine test complete")
