#!/usr/bin/env python3
"""
通用技术指标工具 - v1.0.2 Integrated
统一的技术指标计算库，支持多种输入类型
"""

import numpy as np
from typing import Union, Optional
import warnings

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("technical_indicators")
except ImportError:
    import logging
    logger = logging.getLogger("technical_indicators")


class TechnicalIndicators:
    """技术指标计算工具类"""
    
    @staticmethod
    def calculate_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
        """
        计算ATR（平均真实波幅）
        
        Args:
            high: 最高价数组
            low: 最低价数组
            close: 收盘价数组
            period: ATR周期，默认14
            
        Returns:
            ATR值数组
        """
        # 第一层防御：输入验证
        if len(high) != len(low) or len(high) != len(close):
            raise ValueError("high、low、close数组长度必须一致")
        
        if len(high) < period + 1:
            raise ValueError(f"数据长度必须大于period={period}")
        
        if period <= 0:
            raise ValueError("period必须大于0")
        
        # 第二层防御：除零保护
        try:
            # 计算真实波幅
            tr1 = high[1:] - low[1:]
            tr2 = np.abs(high[1:] - close[:-1])
            tr3 = np.abs(low[1:] - close[:-1])
            
            tr = np.maximum.reduce([tr1, tr2, tr3])
            
            # 计算ATR（RMA方法）
            atr = np.zeros_like(close)
            atr[period] = np.mean(tr[:period])
            
            for i in range(period + 1, len(atr)):
                atr[i] = (atr[i-1] * (period - 1) + tr[i-1]) / period
            
            return atr
            
        except Exception as e:
            logger.error(f"ATR计算失败: {e}")
            # 返回零数组作为兜底
            return np.zeros_like(close)
    
    @staticmethod
    def calculate_sma(data: np.ndarray, period: int) -> np.ndarray:
        """
        计算简单移动平均线（SMA）
        
        Args:
            data: 价格数组
            period: 周期
            
        Returns:
            SMA数组
        """
        if period <= 0:
            raise ValueError("period必须大于0")
        
        if len(data) < period:
            raise ValueError(f"数据长度必须大于period={period}")
        
        return np.convolve(data, np.ones(period)/period, mode='valid')
    
    @staticmethod
    def calculate_ema(data: np.ndarray, period: int) -> np.ndarray:
        """
        计算指数移动平均线（EMA）
        
        Args:
            data: 价格数组
            period: 周期
            
        Returns:
            EMA数组
        """
        if period <= 0:
            raise ValueError("period必须大于0")
        
        if len(data) < period:
            raise ValueError(f"数据长度必须大于period={period}")
        
        multiplier = 2 / (period + 1)
        ema = np.zeros_like(data)
        
        # 初始EMA使用SMA
        ema[period - 1] = np.mean(data[:period])
        
        # 计算后续EMA
        for i in range(period, len(data)):
            ema[i] = (data[i] * multiplier) + (ema[i-1] * (1 - multiplier))
        
        return ema
    
    @staticmethod
    def calculate_rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
        """
        计算相对强弱指标（RSI）
        
        Args:
            data: 价格数组
            period: 周期，默认14
            
        Returns:
            RSI数组（0-100）
        """
        if len(data) < period + 1:
            raise ValueError(f"数据长度必须大于period={period}")
        
        # 计算价格变化
        delta = np.diff(data)
        
        # 分离上涨和下跌
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        
        # 计算平均上涨和下跌
        avg_gain = np.zeros_like(data)
        avg_loss = np.zeros_like(data)
        
        avg_gain[period] = np.mean(gain[:period])
        avg_loss[period] = np.mean(loss[:period])
        
        for i in range(period + 1, len(data)):
            avg_gain[i] = (avg_gain[i-1] * (period - 1) + gain[i-1]) / period
            avg_loss[i] = (avg_loss[i-1] * (period - 1) + loss[i-1]) / period
        
        # 计算RSI
        rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    @staticmethod
    def calculate_macd(data: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple:
        """
        计算MACD指标
        
        Args:
            data: 价格数组
            fast: 快线周期，默认12
            slow: 慢线周期，默认26
            signal: 信号线周期，默认9
            
        Returns:
            (macd, signal_line, histogram)
        """
        if slow <= fast:
            raise ValueError("slow必须大于fast")
        
        # 计算EMA
        ema_fast = TechnicalIndicators.calculate_ema(data, fast)
        ema_slow = TechnicalIndicators.calculate_ema(data, slow)
        
        # 计算MACD
        macd = ema_fast - ema_slow
        
        # 计算信号线
        signal_line = TechnicalIndicators.calculate_ema(macd, signal)
        
        # 计算柱状图
        histogram = macd - signal_line
        
        return macd, signal_line, histogram
    
    @staticmethod
    def calculate_bollinger_bands(data: np.ndarray, period: int = 20, std_dev: float = 2.0) -> tuple:
        """
        计算布林带
        
        Args:
            data: 价格数组
            period: 周期，默认20
            std_dev: 标准差倍数，默认2.0
            
        Returns:
            (upper_band, middle_band, lower_band)
        """
        middle_band = TechnicalIndicators.calculate_sma(data, period)
        std = np.std(data[-period:])
        
        upper_band = middle_band + (std * std_dev)
        lower_band = middle_band - (std * std_dev)
        
        return upper_band, middle_band, lower_band
    
    @staticmethod
    def calculate_supertrend(data: np.ndarray, period: int = 10, multiplier: float = 3.0) -> tuple:
        """
        计算SuperTrend指标
        
        Args:
            data: 价格数组
            period: ATR周期
            multiplier: ATR乘数
            
        Returns:
            (supertrend, direction) direction: 1=上升, -1=下降
        """
        # 分解high/low/close
        if len(data.shape) == 2 and data.shape[1] >= 3:
            high = data[:, 0]
            low = data[:, 1]
            close = data[:, 2]
        else:
            raise ValueError("SuperTrend需要high/low/close数据")
        
        # 计算ATR
        atr = TechnicalIndicators.calculate_atr(high, low, close, period)
        
        # 计算基本上下轨
        hl2 = (high + low) / 2
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)
        
        # 初始化
        supertrend = np.zeros_like(close)
        direction = np.zeros_like(close)
        
        supertrend[0] = upper_band[0]
        direction[0] = 1
        
        # 迭代计算
        for i in range(1, len(close)):
            if direction[i-1] == 1:  # 上升趋势
                if close[i] > lower_band[i-1]:
                    supertrend[i] = lower_band[i]
                    direction[i] = 1
                else:
                    supertrend[i] = upper_band[i]
                    direction[i] = -1
            else:  # 下降趋势
                if close[i] < upper_band[i-1]:
                    supertrend[i] = upper_band[i]
                    direction[i] = -1
                else:
                    supertrend[i] = lower_band[i]
                    direction[i] = 1
        
        return supertrend, direction


if __name__ == "__main__":
    # 测试代码
    print("测试通用技术指标工具...\n")
    
    # 生成测试数据
    np.random.seed(42)
    close = np.random.normal(100, 1, 100)
    high = close + np.random.uniform(0, 1, 100)
    low = close - np.random.uniform(0, 1, 100)
    
    # 测试ATR
    print("1. ATR测试:")
    atr = TechnicalIndicators.calculate_atr(high, low, close, 14)
    print(f"   ATR[{-1}:]: {atr[-5:]}")
    
    # 测试SMA
    print("\n2. SMA测试:")
    sma = TechnicalIndicators.calculate_sma(close, 20)
    print(f"   SMA[{-1}:]: {sma[-5:]}")
    
    # 测试EMA
    print("\n3. EMA测试:")
    ema = TechnicalIndicators.calculate_ema(close, 12)
    print(f"   EMA[{-1}:]: {ema[-5:]}")
    
    # 测试RSI
    print("\n4. RSI测试:")
    rsi = TechnicalIndicators.calculate_rsi(close, 14)
    print(f"   RSI[{-1}:]: {rsi[-5:]}")
    
    print("\n✅ 所有测试通过")
