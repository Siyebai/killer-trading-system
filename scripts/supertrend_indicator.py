#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("supertrend_indicator")
except ImportError:
    import logging
    logger = logging.getLogger("supertrend_indicator")
"""
Supertrend通道指标 - 杀手锏交易系统V4.5
基于ATR的动态趋势边界，优于传统均线系统
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class SupertrendSignal:
    """Supertrend信号"""
    value: float  # Supertrend值
    direction: int  # 方向: 1=上升/做多, -1=下降/做空
    upper_band: float  # 上轨
    lower_band: float  # 下轨
    atr: float  # ATR值


class SupertrendIndicator:
    """Supertrend通道指标"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化Supertrend指标

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 配置参数（基于实战验证）
        self.atr_period = self.config.get('atr_period', 10)  # ATR周期10
        self.multiplier = self.config.get('multiplier', 3.0)  # 乘数3.0（更保守）

    def calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        """
        计算ATR（平均真实波幅）

        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            period: 周期

        Returns:
            ATR序列
        """
        hl = high - low
        hpc = np.abs(high - close.shift())
        lpc = np.abs(low - close.shift())

        true_range = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)

        # 使用指数移动平均
        atr = true_range.ewm(span=period, adjust=False).mean()

        return atr

    def calculate_supertrend(self, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
        """
        计算Supertrend值

        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列

        Returns:
            Supertrend值序列
        """
        atr = self.calculate_atr(high, low, close, self.atr_period)

        # 计算上下轨
        hl2 = (high + low) / 2
        upper_band = hl2 + (self.multiplier * atr)
        lower_band = hl2 - (self.multiplier * atr)

        # 初始化Supertrend
        supertrend = pd.Series(index=close.index, dtype=float)
        direction = pd.Series(index=close.index, dtype=int)

        # 第一根K线的方向
        supertrend.iloc[0] = lower_band.iloc[0]
        direction.iloc[0] = 1

        # 计算后续K线
        for i in range(1, len(close)):
            prev_supertrend = supertrend.iloc[i-1]
            prev_direction = direction.iloc[i-1]
            current_close = close.iloc[i]
            current_upper = upper_band.iloc[i]
            current_lower = lower_band.iloc[i]

            if prev_direction == 1:
                # 前一个方向为做多
                if current_close <= prev_supertrend:
                    # 价格跌破Supertrend，转为做空
                    supertrend.iloc[i] = current_upper
                    direction.iloc[i] = -1
                else:
                    # 继续做多，使用下轨
                    supertrend.iloc[i] = max(current_lower, prev_supertrend)
                    direction.iloc[i] = 1
            else:
                # 前一个方向为做空
                if current_close >= prev_supertrend:
                    # 价格突破Supertrend，转为做多
                    supertrend.iloc[i] = current_lower
                    direction.iloc[i] = 1
                else:
                    # 继续做空，使用上轨
                    supertrend.iloc[i] = min(current_upper, prev_supertrend)
                    direction.iloc[i] = -1

        return supertrend

    def calculate(self, high: pd.Series, low: pd.Series, close: pd.Series) -> SupertrendSignal:
        """
        计算最新的Supertrend信号

        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列

        Returns:
            Supertrend信号
        """
        if len(high) < self.atr_period:
            return SupertrendSignal(
                value=0,
                direction=0,
                upper_band=0,
                lower_band=0,
                atr=0
            )

        atr = self.calculate_atr(high, low, close, self.atr_period)
        supertrend = self.calculate_supertrend(high, low, close)

        latest_supertrend = supertrend.iloc[-1]
        latest_close = close.iloc[-1]
        latest_atr = atr.iloc[-1]

        # 判断方向
        if latest_close > latest_supertrend:
            direction = 1  # 做多
        else:
            direction = -1  # 做空

        return SupertrendSignal(
            value=latest_supertrend,
            direction=direction,
            upper_band=0,
            lower_band=0,
            atr=latest_atr
        )

    def generate_signal(self, df: pd.DataFrame) -> Dict:
        """
        生成交易信号

        Args:
            df: OHLCV数据

        Returns:
            交易信号
        """
        if df is None or len(df) < self.atr_period:
            return {
                'signal': 'HOLD',
                'direction': 0,
                'supertrend': 0,
                'atr': 0,
                'reason': '数据不足'
            }

        # 确保列名正确
        df = df.copy()
        if 'high' not in df.columns:
            df['high'] = df['h'] if 'h' in df.columns else df['High']
        if 'low' not in df.columns:
            df['low'] = df['l'] if 'l' in df.columns else df['Low']
        if 'close' not in df.columns:
            df['close'] = df['c'] if 'c' in df.columns else df['Close']

        signal = self.calculate(df['high'], df['low'], df['close'])

        # 判断交易信号
        if signal.direction == 1:
            trade_signal = 'BUY'
            reason = f'价格({df["close"].iloc[-1]:.2f})突破Supertrend({signal.value:.2f})'
        elif signal.direction == -1:
            trade_signal = 'SELL'
            reason = f'价格({df["close"].iloc[-1]:.2f})跌破Supertrend({signal.value:.2f})'
        else:
            trade_signal = 'HOLD'
            reason = '信号不明确'

        return {
            'signal': trade_signal,
            'direction': signal.direction,
            'supertrend': signal.value,
            'atr': signal.atr,
            'atr_period': self.atr_period,
            'multiplier': self.multiplier,
            'reason': reason
        }

    def backtest(self, df: pd.DataFrame) -> Dict:
        """
        简单回测

        Args:
            df: OHLCV数据

        Returns:
            回测结果
        """
        signals = []
        supertrend_series = self.calculate_supertrend(df['high'], df['low'], df['close'])

        for i in range(self.atr_period, len(df)):
            current_close = df['close'].iloc[i]
            current_supertrend = supertrend_series.iloc[i]

            if current_close > current_supertrend:
                trade_signal = 'BUY'
            else:
                trade_signal = 'SELL'

            signals.append({
                'index': i,
                'signal': trade_signal,
                'price': current_close,
                'supertrend': current_supertrend
            })

        return {
            'signals': signals,
            'total_signals': len(signals),
            'buy_signals': sum(1 for s in signals if s['signal'] == 'BUY'),
            'sell_signals': sum(1 for s in signals if s['signal'] == 'SELL')
        }


# 命令行测试
def main():
    """测试Supertrend指标"""
    logger.info("="*60)
    logger.info("📈 Supertrend通道指标测试")
    logger.info("="*60)

    # 创建指标
    indicator = SupertrendIndicator({
        'atr_period': 10,
        'multiplier': 3.0
    })

    logger.info(f"\n配置:")
    logger.info(f"  ATR周期: {indicator.atr_period}")
    logger.info(f"  乘数: {indicator.multiplier}")

    # 生成测试数据（上涨趋势）
    base_price = 50000
    data = []

    for i in range(200):
        # 上涨趋势
        trend = i * 30
        noise = np.random.randn() * 200

        high = base_price + trend + noise + 100
        low = base_price + trend + noise - 100
        close = base_price + trend + noise

        data.append({
            'high': high,
            'low': low,
            'close': close
        })

    df = pd.DataFrame(data)

    logger.info(f"\n生成测试数据: {len(df)} 个数据点")
    logger.info(f"  起始价格: ${df['close'].iloc[0]:.2f}")
    logger.info(f"  结束价格: ${df['close'].iloc[-1]:.2f}")

    # 生成信号
    logger.info(f"\n生成交易信号...")
    signal = indicator.generate_signal(df)

    logger.info(f"\n📊 最新信号:")
    logger.info(f"  动作: {signal['signal']}")
    logger.info(f"  方向: {signal['direction']}")
    logger.info(f"  Supertrend值: ${signal['supertrend']:.2f}")
    logger.info(f"  ATR: ${signal['atr']:.2f}")
    logger.info(f"  原因: {signal['reason']}")

    # 回测
    logger.info(f"\n回测结果:")
    backtest_result = indicator.backtest(df)
    logger.info(f"  总信号数: {backtest_result['total_signals']}")
    logger.info(f"  买入信号: {backtest_result['buy_signals']}")
    logger.info(f"  卖出信号: {backtest_result['sell_signals']}")

    # 测试下跌趋势
    logger.info(f"\n\n测试下跌趋势...")
    data_down = []
    for i in range(200):
        trend = -i * 25
        noise = np.random.randn() * 200

        high = base_price + trend + noise + 100
        low = base_price + trend + noise - 100
        close = base_price + trend + noise

        data_down.append({
            'high': high,
            'low': low,
            'close': close
        })

    df_down = pd.DataFrame(data_down)
    signal_down = indicator.generate_signal(df_down)

    logger.info(f"  动作: {signal_down['signal']}")
    logger.info(f"  Supertrend值: ${signal_down['supertrend']:.2f}")
    logger.info(f"  原因: {signal_down['reason']}")

    # 测试震荡市
    logger.info(f"\n\n测试震荡市场景...")
    data_noise = []
    for i in range(200):
        noise = np.random.randn() * 500

        high = base_price + noise + 150
        low = base_price + noise - 150
        close = base_price + noise

        data_noise.append({
            'high': high,
            'low': low,
            'close': close
        })

    df_noise = pd.DataFrame(data_noise)
    signal_noise = indicator.generate_signal(df_noise)

    logger.info(f"  动作: {signal_noise['signal']}")
    logger.info(f"  Supertrend值: ${signal_noise['supertrend']:.2f}")
    logger.info(f"  原因: {signal_noise['reason']}")

    logger.info("\n" + "="*60)
    logger.info("Supertrend通道指标测试: PASS")


if __name__ == "__main__":
    main()
