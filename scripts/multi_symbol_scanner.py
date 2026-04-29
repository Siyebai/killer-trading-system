#!/usr/bin/env python3
"""
杀手锏交易系统 v5.0 - 多品种扫描器
核心功能：4品种(BTC+ETH+SOL+BNB)并行扫描，3策略融合

架构：
4品种 x 3策略 = 12条信号流
预期日均：10-30笔

策略配置：
- BTCUSDT: 均值回归(1H) + 趋势跟踪(15m) + 资金费率
- ETHUSDT: 跨品种跟随(1H) + 趋势跟踪(15m) + 资金费率
- SOLUSDT: 趋势突破(1H) + 动量策略(15m) + 资金费率
- BNBUSDT: 均值回归(1H) + 动量策略(15m) + 资金费率

最优参数（来自回测）：
- OB70/OS30 + 2.5sigma BB + SL1.5 + TP3.0
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("multi_symbol_scanner")


# 品种配置
SYMBOL_CONFIG = {
    'BTCUSDT': {
        'base_price': 100000,
        'volatility': 0.03,       # 3% 日波动
        'strategies': ['mean_reversion', 'trend_following', 'funding_rate'],
        'timeframes': ['1H', '15m'],
        'weight': 0.4,            # 资金权重
        'max_position_pct': 3.0,  # 最大仓位%
        'is_leader': True         # 领先品种
    },
    'ETHUSDT': {
        'base_price': 3500,
        'volatility': 0.04,       # 4% 日波动
        'strategies': ['cross_symbol', 'trend_following', 'funding_rate'],
        'timeframes': ['1H', '15m'],
        'weight': 0.25,
        'max_position_pct': 2.5,
        'is_leader': False
    },
    'SOLUSDT': {
        'base_price': 240,
        'volatility': 0.05,       # 5% 日波动
        'strategies': ['breakout', 'momentum', 'funding_rate'],
        'timeframes': ['1H', '15m'],
        'weight': 0.2,
        'max_position_pct': 2.0,
        'is_leader': False
    },
    'BNBUSDT': {
        'base_price': 680,
        'volatility': 0.035,      # 3.5% 日波动
        'strategies': ['mean_reversion', 'momentum', 'funding_rate'],
        'timeframes': ['1H', '15m'],
        'weight': 0.15,
        'max_position_pct': 2.0,
        'is_leader': False
    }
}

# v5.0 最优参数
OPTIMAL_PARAMS = {
    'mean_reversion': {
        'rsi_oversold': 30,       # OS30 (v4用25)
        'rsi_overbought': 70,     # OB70 (v4用75)
        'bb_std': 2.5,            # 2.5sigma (v4用2.0)
        'bb_period': 20,
        'sl_atr_multiplier': 1.5,
        'tp_atr_multiplier': 3.0,
        'z_entry': 1.5,
        'z_exit': 0.5
    },
    'trend_following': {
        'ema_fast': 9,
        'ema_medium': 21,
        'ema_slow': 55,
        'adx_threshold': 25,
        'atr_sl_multiplier': 2.0,
        'atr_tp_multiplier': 4.0
    },
    'breakout': {
        'bb_std': 2.5,
        'bb_period': 20,
        'volume_spike': 2.0,
        'adx_threshold': 25,
        'sl_atr_multiplier': 1.5,
        'tp_atr_multiplier': 3.0
    },
    'momentum': {
        'rsi_period': 14,
        'macd_fast': 12,
        'macd_slow': 26,
        'macd_signal': 9,
        'sl_atr_multiplier': 1.5,
        'tp_atr_multiplier': 3.0
    }
}


class MultiSymbolScanner:
    """
    多品种扫描器
    4品种 x 3策略 = 12条信号流
    """

    def __init__(self, config_path: str = None):
        """初始化多品种扫描器"""
        self.version = "v5.0"
        self.project_root = Path("/workspace/projects/trading-simulator")
        self.config = self._load_config(config_path)

        # 品种配置
        self.symbols = SYMBOL_CONFIG
        self.params = OPTIMAL_PARAMS

        # 扫描结果
        self.scan_results = {}
        self.signal_queue = []

        # 统计
        self.total_scans = 0
        self.total_signals = 0

        logger.info(f"[OK] 多品种扫描器 {self.version} 初始化完成")
        logger.info(f"   品种: {list(self.symbols.keys())}")
        logger.info(f"   信号流: {sum(len(s['strategies']) for s in self.symbols.values())} 条")

    def _load_config(self, config_path: str) -> Dict:
        """加载配置"""
        if config_path is None:
            config_path = self.project_root / "config.json"
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def scan_symbol(self, symbol: str, df: pd.DataFrame, market_state: str = "RANGING") -> List[Dict]:
        """
        扫描单个品种

        参数：
        - symbol: 品种名称
        - df: OHLCV数据
        - market_state: 当前市场状态

        返回：
        - signals: 信号列表
        """
        if symbol not in self.symbols:
            logger.warning(f"未知品种: {symbol}")
            return []

        config = self.symbols[symbol]
        signals = []

        # 根据市场状态筛选策略
        active_strategies = self._get_active_strategies(config['strategies'], market_state)

        for strategy_name in active_strategies:
            strategy_signals = self._run_strategy(symbol, strategy_name, df, config)
            signals.extend(strategy_signals)

        self.scan_results[symbol] = {
            'timestamp': datetime.now().isoformat(),
            'signal_count': len(signals),
            'signals': signals,
            'market_state': market_state
        }

        self.total_scans += 1
        self.total_signals += len(signals)

        if signals:
            logger.info(f"[SCAN] {symbol}: {len(signals)} signals ({market_state})")
            for s in signals:
                logger.info(f"  - {s['type']} ({s['confidence']:.0f}%) [{s['strategy']}]")

        return signals

    def scan_all(self, data_dict: Dict[str, pd.DataFrame], market_state: str = "RANGING") -> List[Dict]:
        """
        扫描所有品种

        参数：
        - data_dict: {symbol: DataFrame}
        - market_state: 市场状态

        返回：
        - all_signals: 所有信号
        """
        all_signals = []

        for symbol, df in data_dict.items():
            signals = self.scan_symbol(symbol, df, market_state)
            all_signals.extend(signals)

        # 信号聚合和排序
        all_signals = self._aggregate_signals(all_signals)

        return all_signals

    def _get_active_strategies(self, available_strategies: List[str], market_state: str) -> List[str]:
        """根据市场状态筛选活跃策略"""
        if market_state == "RANGING":
            preferred = ['mean_reversion', 'momentum']
        elif market_state in ["TRENDING_UP", "TRENDING_DOWN"]:
            preferred = ['trend_following', 'breakout', 'cross_symbol']
        elif market_state == "EXTREME_VOL":
            preferred = ['funding_rate']
        else:
            preferred = available_strategies

        # 取交集
        active = [s for s in available_strategies if s in preferred]
        if not active:
            active = available_strategies[:1]  # 至少一个策略

        return active

    def _run_strategy(self, symbol: str, strategy_name: str, df: pd.DataFrame, config: Dict) -> List[Dict]:
        """运行单个策略"""
        params = self.params.get(strategy_name, {})
        signals = []

        if len(df) < 50:
            return signals

        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']

        if strategy_name == 'mean_reversion':
            signals = self._mean_reversion_signals(symbol, close, high, low, volume, params)

        elif strategy_name == 'trend_following':
            signals = self._trend_following_signals(symbol, close, high, low, volume, params)

        elif strategy_name == 'breakout':
            signals = self._breakout_signals(symbol, close, high, low, volume, params)

        elif strategy_name == 'momentum':
            signals = self._momentum_signals(symbol, close, high, low, volume, params)

        elif strategy_name == 'funding_rate':
            # 资金费率需要外部数据，此处模拟
            pass

        elif strategy_name == 'cross_symbol':
            # 跨品种跟随需要外部信号，此处模拟
            pass

        return signals

    def _mean_reversion_signals(self, symbol: str, close: pd.Series, high: pd.Series, low: pd.Series,
                                volume: pd.Series, params: Dict) -> List[Dict]:
        """均值回归信号 - OB70/OS30 + 2.5sigma BB"""
        signals = []

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        # 布林带 2.5sigma
        bb_mid = close.rolling(params.get('bb_period', 20)).mean()
        bb_std = close.rolling(params.get('bb_period', 20)).std()
        bb_upper = bb_mid + bb_std * params.get('bb_std', 2.5)
        bb_lower = bb_mid - bb_std * params.get('bb_std', 2.5)

        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        latest_rsi = rsi.iloc[-1]
        latest_close = close.iloc[-1]
        latest_atr = atr.iloc[-1]

        # RSI超卖 + 布林下轨
        if latest_rsi < params.get('rsi_oversold', 30) and latest_close < bb_lower.iloc[-1]:
            sl = latest_close - latest_atr * params.get('sl_atr_multiplier', 1.5)
            tp = latest_close + latest_atr * params.get('tp_atr_multiplier', 3.0)
            signals.append({
                'type': 'LONG',
                'confidence': 70,
                'strategy': 'mean_reversion',
                'symbol': symbol,
                'reason': f"RSI超卖({latest_rsi:.1f})+BB下轨",
                'stop_loss': sl,
                'take_profit': tp
            })

        # RSI超买 + 布林上轨
        elif latest_rsi > params.get('rsi_overbought', 70) and latest_close > bb_upper.iloc[-1]:
            sl = latest_close + latest_atr * params.get('sl_atr_multiplier', 1.5)
            tp = latest_close - latest_atr * params.get('tp_atr_multiplier', 3.0)
            signals.append({
                'type': 'SHORT',
                'confidence': 70,
                'strategy': 'mean_reversion',
                'symbol': symbol,
                'reason': f"RSI超买({latest_rsi:.1f})+BB上轨",
                'stop_loss': sl,
                'take_profit': tp
            })

        return signals

    def _trend_following_signals(self, symbol: str, close: pd.Series, high: pd.Series, low: pd.Series,
                                 volume: pd.Series, params: Dict) -> List[Dict]:
        """趋势跟踪信号 - EMA三线"""
        signals = []

        ema_fast = close.ewm(span=params.get('ema_fast', 9)).mean()
        ema_medium = close.ewm(span=params.get('ema_medium', 21)).mean()
        ema_slow = close.ewm(span=params.get('ema_slow', 55)).mean()

        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        latest_atr = atr.iloc[-1]
        latest_close = close.iloc[-1]

        # 多头排列
        if ema_fast.iloc[-1] > ema_medium.iloc[-1] > ema_slow.iloc[-1]:
            # 金叉确认
            if ema_fast.iloc[-2] <= ema_medium.iloc[-2]:
                sl = latest_close - latest_atr * params.get('atr_sl_multiplier', 2.0)
                tp = latest_close + latest_atr * params.get('atr_tp_multiplier', 4.0)
                signals.append({
                    'type': 'LONG',
                    'confidence': 75,
                    'strategy': 'trend_following',
                    'symbol': symbol,
                    'reason': "EMA多头排列+金叉",
                    'stop_loss': sl,
                    'take_profit': tp
                })

        # 空头排列
        elif ema_fast.iloc[-1] < ema_medium.iloc[-1] < ema_slow.iloc[-1]:
            if ema_fast.iloc[-2] >= ema_medium.iloc[-2]:
                sl = latest_close + latest_atr * params.get('atr_sl_multiplier', 2.0)
                tp = latest_close - latest_atr * params.get('atr_tp_multiplier', 4.0)
                signals.append({
                    'type': 'SHORT',
                    'confidence': 75,
                    'strategy': 'trend_following',
                    'symbol': symbol,
                    'reason': "EMA空头排列+死叉",
                    'stop_loss': sl,
                    'take_profit': tp
                })

        return signals

    def _breakout_signals(self, symbol: str, close: pd.Series, high: pd.Series, low: pd.Series,
                          volume: pd.Series, params: Dict) -> List[Dict]:
        """突破信号 - 布林带突破+放量"""
        signals = []

        # 布林带
        bb_mid = close.rolling(params.get('bb_period', 20)).mean()
        bb_std = close.rolling(params.get('bb_period', 20)).std()
        bb_upper = bb_mid + bb_std * params.get('bb_std', 2.5)
        bb_lower = bb_mid - bb_std * params.get('bb_std', 2.5)

        # 成交量
        vol_ma = volume.rolling(20).mean()

        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        latest_close = close.iloc[-1]
        latest_vol = volume.iloc[-1]
        latest_atr = atr.iloc[-1]

        # 上轨突破+放量
        if latest_close > bb_upper.iloc[-1] and latest_vol > vol_ma.iloc[-1] * params.get('volume_spike', 2.0):
            sl = latest_close - latest_atr * params.get('sl_atr_multiplier', 1.5)
            tp = latest_close + latest_atr * params.get('tp_atr_multiplier', 3.0)
            signals.append({
                'type': 'LONG',
                'confidence': 65,
                'strategy': 'breakout',
                'symbol': symbol,
                'reason': f"BB上轨突破+放量({latest_vol/vol_ma.iloc[-1]:.1f}x)",
                'stop_loss': sl,
                'take_profit': tp
            })

        # 下轨突破+放量
        elif latest_close < bb_lower.iloc[-1] and latest_vol > vol_ma.iloc[-1] * params.get('volume_spike', 2.0):
            sl = latest_close + latest_atr * params.get('sl_atr_multiplier', 1.5)
            tp = latest_close - latest_atr * params.get('tp_atr_multiplier', 3.0)
            signals.append({
                'type': 'SHORT',
                'confidence': 65,
                'strategy': 'breakout',
                'symbol': symbol,
                'reason': f"BB下轨突破+放量({latest_vol/vol_ma.iloc[-1]:.1f}x)",
                'stop_loss': sl,
                'take_profit': tp
            })

        return signals

    def _momentum_signals(self, symbol: str, close: pd.Series, high: pd.Series, low: pd.Series,
                          volume: pd.Series, params: Dict) -> List[Dict]:
        """动量信号 - RSI+MACD"""
        signals = []

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        # MACD
        ema_fast = close.ewm(span=params.get('macd_fast', 12)).mean()
        ema_slow = close.ewm(span=params.get('macd_slow', 26)).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=params.get('macd_signal', 9)).mean()
        macd_hist = macd_line - signal_line

        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        latest_rsi = rsi.iloc[-1]
        latest_macd = macd_hist.iloc[-1]
        latest_close = close.iloc[-1]
        latest_atr = atr.iloc[-1]

        # RSI从超卖回升 + MACD金叉
        if latest_rsi > 30 and rsi.iloc[-2] <= 30 and latest_macd > 0 and macd_hist.iloc[-2] <= 0:
            sl = latest_close - latest_atr * params.get('sl_atr_multiplier', 1.5)
            tp = latest_close + latest_atr * params.get('tp_atr_multiplier', 3.0)
            signals.append({
                'type': 'LONG',
                'confidence': 65,
                'strategy': 'momentum',
                'symbol': symbol,
                'reason': "RSI回升+MACD金叉",
                'stop_loss': sl,
                'take_profit': tp
            })

        # RSI从超买回落 + MACD死叉
        elif latest_rsi < 70 and rsi.iloc[-2] >= 70 and latest_macd < 0 and macd_hist.iloc[-2] >= 0:
            sl = latest_close + latest_atr * params.get('sl_atr_multiplier', 1.5)
            tp = latest_close - latest_atr * params.get('tp_atr_multiplier', 3.0)
            signals.append({
                'type': 'SHORT',
                'confidence': 65,
                'strategy': 'momentum',
                'symbol': symbol,
                'reason': "RSI回落+MACD死叉",
                'stop_loss': sl,
                'take_profit': tp
            })

        return signals

    def _aggregate_signals(self, signals: List[Dict]) -> List[Dict]:
        """聚合和排序信号"""
        if not signals:
            return []

        # 按置信度排序
        signals.sort(key=lambda x: x.get('confidence', 0), reverse=True)

        # 去重（同品种同方向取最高置信度）
        seen = {}
        for s in signals:
            key = f"{s['symbol']}_{s['type']}"
            if key not in seen or s.get('confidence', 0) > seen[key].get('confidence', 0):
                seen[key] = s

        return list(seen.values())

    def get_scan_summary(self) -> Dict:
        """获取扫描摘要"""
        return {
            'total_scans': self.total_scans,
            'total_signals': self.total_signals,
            'symbols': list(self.symbols.keys()),
            'signal_flows': sum(len(s['strategies']) for s in self.symbols.values()),
            'results': {k: {'signal_count': v['signal_count'], 'state': v['market_state']}
                       for k, v in self.scan_results.items()}
        }


if __name__ == "__main__":
    print("=" * 80)
    print("Multi-Symbol Scanner v5.0 Test")
    print("=" * 80)

    scanner = MultiSymbolScanner()

    # Generate test data
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=200, freq='h')

    # Create test data for each symbol
    data_dict = {}
    for symbol, config in SYMBOL_CONFIG.items():
        base = config['base_price']
        vol = config['volatility']
        trend = np.linspace(0, base * 0.1, 200)
        noise = np.random.randn(200) * base * vol * 0.1
        close = base + trend + noise

        data_dict[symbol] = pd.DataFrame({
            'open': close + np.random.randn(200) * base * 0.005,
            'high': close + np.abs(np.random.randn(200)) * base * 0.01,
            'low': close - np.abs(np.random.randn(200)) * base * 0.01,
            'close': close,
            'volume': np.random.randint(1000, 10000, 200)
        }, index=dates)

    # Test 1: Single symbol scan
    print("\n--- Test 1: Single Symbol Scan (BTCUSDT) ---")
    signals = scanner.scan_symbol('BTCUSDT', data_dict['BTCUSDT'], 'RANGING')
    print(f"  Signals: {len(signals)}")
    for s in signals:
        print(f"  - {s['type']} ({s['confidence']}%) [{s['strategy']}] {s['reason']}")

    # Test 2: Full scan
    print("\n--- Test 2: Full Scan (4 Symbols) ---")
    all_signals = scanner.scan_all(data_dict, 'RANGING')
    print(f"  Total signals: {len(all_signals)}")
    for s in all_signals:
        print(f"  - {s['symbol']} {s['type']} ({s['confidence']}%) [{s['strategy']}]")

    # Test 3: Different market states
    print("\n--- Test 3: Market State Comparison ---")
    for state in ['RANGING', 'TRENDING_UP', 'TRENDING_DOWN', 'EXTREME_VOL']:
        signals = scanner.scan_all(data_dict, state)
        print(f"  {state}: {len(signals)} signals")

    # Summary
    print("\n--- Scan Summary ---")
    summary = scanner.get_scan_summary()
    print(f"  Total scans: {summary['total_scans']}")
    print(f"  Total signals: {summary['total_signals']}")
    print(f"  Signal flows: {summary['signal_flows']}")

    print("\n[OK] Multi-Symbol Scanner test complete")
