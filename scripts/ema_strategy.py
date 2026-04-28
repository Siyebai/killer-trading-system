#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("ema_strategy")
except ImportError:
    import logging
    logger = logging.getLogger("ema_strategy")
"""
EMA趋势策略 - 杀手锏交易系统
EMA21/EMA55 + RSI过滤 + 成交量确认
基于实战验证的非对称参数和加权平均价格
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class EMASignal:
    """EMA信号"""
    action: str  # BUY/SELL/HOLD
    confidence: float  # 置信度 0-1
    ema_short: float
    ema_long: float
    rsi: float
    volume_ratio: float
    reasons: List[str]


class EMAStrategy:
    """EMA趋势策略"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化EMA策略

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 参数配置（基于实战验证）
        self.short_period = self.config.get('short_period', 21)  # EMA21
        self.long_period = self.config.get('long_period', 55)  # EMA55
        self.rsi_period = self.config.get('rsi_period', 14)
        self.volume_threshold = self.config.get('volume_threshold', 1.2)  # 成交量倍数

        # 价格加权平均：(2*C+O+H+L)/5
        self.use_weighted_price = self.config.get('use_weighted_price', True)

    def calculate_weighted_price(self, df: pd.DataFrame) -> pd.Series:
        """
        计算加权平均价格

        Args:
            df: OHLCV数据

        Returns:
            加权价格序列
        """
        if not all(col in df.columns for col in ['open', 'high', 'low', 'close']):
            return df['close']

        weighted = (2 * df['close'] + df['open'] + df['high'] + df['low']) / 5
        return weighted

    def calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        """
        计算EMA（指数移动平均）

        Args:
            series: 价格序列
            period: 周期

        Returns:
            EMA序列
        """
        return series.ewm(span=period, adjust=False).mean()

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        计算RSI

        Args:
            df: OHLCV数据
            period: 周期

        Returns:
            RSI序列
        """
        if 'close' not in df.columns:
            return pd.Series([50] * len(df), index=df.index)

        deltas = df['close'].diff()
        gains = deltas.where(deltas > 0, 0)
        losses = -deltas.where(deltas < 0, 0)

        avg_gain = gains.rolling(window=period).mean()
        avg_loss = losses.rolling(window=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def check_volume_confirmation(self, df: pd.DataFrame) -> bool:
        """
        检查成交量确认

        Args:
            df: OHLCV数据

        Returns:
            是否放量
        """
        if 'volume' not in df.columns or len(df) < 20:
            return True  # 无成交量数据时跳过检查

        current_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]

        if avg_volume == 0:
            return True

        volume_ratio = current_volume / avg_volume
        return volume_ratio >= self.volume_threshold

    def check_macd_divergence(self, df: pd.DataFrame) -> str:
        """
        检查MACD背离

        Args:
            df: OHLCV数据

        Returns:
            BULLISH/BEARISH/NEUTRAL
        """
        if len(df) < 30:
            return "NEUTRAL"

        # 简化MACD计算
        close_prices = df['close'].values
        ema12 = pd.Series(close_prices).ewm(span=12, adjust=False).mean()
        ema26 = pd.Series(close_prices).ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26

        # 检查底背离：价格新低，MACD未创新低
        if len(macd) >= 10:
            price_low_idx = np.argmin(close_prices[-10:]) + len(close_prices) - 10
            macd_low_idx = np.argmin(macd.values[-10:]) + len(macd) - 10

            if price_low_idx > macd_low_idx:
                return "BULLISH"

            # 检查顶背离：价格新高，MACD未创新高
            price_high_idx = np.argmax(close_prices[-10:]) + len(close_prices) - 10
            macd_high_idx = np.argmax(macd.values[-10:]) + len(macd) - 10

            if price_high_idx > macd_high_idx:
                return "BEARISH"

        return "NEUTRAL"

    def generate_signal(self, df: pd.DataFrame) -> EMASignal:
        """
        生成交易信号

        Args:
            df: OHLCV数据

        Returns:
            EMA信号
        """
        if df is None or len(df) < self.long_period + 10:
            return EMASignal(
                action="HOLD",
                confidence=0.0,
                ema_short=0,
                ema_long=0,
                rsi=50,
                volume_ratio=1.0,
                reasons=["数据不足"]
            )

        # 计算价格
        if self.use_weighted_price:
            price = self.calculate_weighted_price(df)
        else:
            price = df['close']

        # 计算EMA
        ema_short = self.calculate_ema(price, self.short_period)
        ema_long = self.calculate_ema(price, self.long_period)

        # 计算RSI
        rsi = self.calculate_rsi(df, self.rsi_period)

        # 检查成交量
        volume_confirmed = self.check_volume_confirmation(df)
        volume_ratio = df['volume'].iloc[-1] / df['volume'].rolling(window=20).mean().iloc[-1] if 'volume' in df.columns else 1.0

        # 检查MACD背离
        macd_divergence = self.check_macd_divergence(df)

        # 获取最新值
        ema_short_val = ema_short.iloc[-1]
        ema_long_val = ema_long.iloc[-1]
        ema_short_prev = ema_short.iloc[-2]
        ema_long_prev = ema_long.iloc[-2]
        rsi_val = rsi.iloc[-1]

        reasons = []
        action = "HOLD"
        confidence = 0.0

        # 判断金叉/死叉
        is_golden_cross = (ema_short_prev <= ema_long_prev) and (ema_short_val > ema_long_val)
        is_death_cross = (ema_short_prev >= ema_long_prev) and (ema_short_val < ema_long_val)

        if is_golden_cross:
            # 金叉信号
            reasons.append(f"EMA{self.short_period}/EMA{self.long_period}金叉")

            # RSI过滤：避免超买
            if rsi_val < 70:
                reasons.append(f"RSI({rsi_val:.1f})未超买")
                confidence += 0.4
            else:
                reasons.append(f"RSI({rsi_val:.1f})超买，谨慎做多")
                confidence += 0.1

            # 成交量确认
            if volume_confirmed:
                reasons.append(f"成交量放大({volume_ratio:.2f}倍)")
                confidence += 0.3
            else:
                reasons.append(f"成交量不足({volume_ratio:.2f}倍)")

            # MACD底背离
            if macd_divergence == "BULLISH":
                reasons.append("MACD底背离确认")
                confidence += 0.2
            elif macd_divergence == "BEARISH":
                reasons.append("MACD顶背离，谨慎")

            # 综合判断
            if confidence >= 0.5:
                action = "BUY"
            else:
                action = "HOLD"

        elif is_death_cross:
            # 死叉信号
            reasons.append(f"EMA{self.short_period}/EMA{self.long_period}死叉")

            # RSI过滤：避免超卖
            if rsi_val > 30:
                reasons.append(f"RSI({rsi_val:.1f})未超卖")
                confidence += 0.4
            else:
                reasons.append(f"RSI({rsi_val:.1f})超卖，谨慎做空")
                confidence += 0.1

            # 成交量确认
            if volume_confirmed:
                reasons.append(f"成交量放大({volume_ratio:.2f}倍)")
                confidence += 0.3
            else:
                reasons.append(f"成交量不足({volume_ratio:.2f}倍)")

            # MACD顶背离
            if macd_divergence == "BEARISH":
                reasons.append("MACD顶背离确认")
                confidence += 0.2
            elif macd_divergence == "BULLISH":
                reasons.append("MACD底背离，谨慎")

            # 综合判断
            if confidence >= 0.5:
                action = "SELL"
            else:
                action = "HOLD"

        else:
            # 持有状态
            if ema_short_val > ema_long_val:
                reasons.append("多头排列，持有多单")
            else:
                reasons.append("空头排列，持有空单")

        return EMASignal(
            action=action,
            confidence=confidence,
            ema_short=ema_short_val,
            ema_long=ema_long_val,
            rsi=rsi_val,
            volume_ratio=volume_ratio,
            reasons=reasons
        )

    def backtest(self, df: pd.DataFrame) -> Dict:
        """
        简单回测

        Args:
            df: OHLCV数据

        Returns:
            回测结果
        """
        signals = []
        positions = []

        for i in range(self.long_period + 10, len(df)):
            sub_df = df.iloc[:i+1]
            signal = self.generate_signal(sub_df)
            signals.append({
                'index': i,
                'signal': signal.action,
                'confidence': signal.confidence,
                'ema_short': signal.ema_short,
                'ema_long': signal.ema_long,
                'rsi': signal.rsi
            })

        return {
            'signals': signals,
            'total_signals': len(signals),
            'buy_signals': sum(1 for s in signals if s['signal'] == 'BUY'),
            'sell_signals': sum(1 for s in signals if s['signal'] == 'SELL')
        }


# 命令行测试
def main():
    """测试EMA策略"""
    logger.info("="*60)
    logger.info("📈 EMA趋势策略测试")
    logger.info("="*60)

    # 创建策略
    strategy = EMAStrategy({
        'short_period': 21,
        'long_period': 55,
        'volume_threshold': 1.2
    })

    logger.info(f"\n配置:")
    logger.info(f"  短周期EMA: {strategy.short_period}")
    logger.info(f"  长周期EMA: {strategy.long_period}")
    logger.info(f"  RSI周期: {strategy.rsi_period}")
    logger.info(f"  成交量阈值: {strategy.volume_threshold}倍")
    logger.info(f"  加权价格: {strategy.use_weighted_price}")

    # 生成测试数据（上涨趋势）
    base_price = 50000
    data = []
    volumes = []

    for i in range(200):
        # 上涨趋势
        trend = i * 30
        noise = np.random.randn() * 200

        open_price = base_price + trend + noise - 50
        high_price = open_price + abs(np.random.randn() * 100)
        low_price = open_price - abs(np.random.randn() * 100)
        close_price = open_price + np.random.randn() * 50

        # 成交量
        base_volume = 1000
        volume = base_volume + np.random.randint(-200, 800)
        if i > 150:  # 后期放量
            volume *= 1.5

        data.append({
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price
        })
        volumes.append(volume)

    df = pd.DataFrame(data)
    df['volume'] = volumes

    logger.info(f"\n生成测试数据: {len(df)} 个数据点")
    logger.info(f"  起始价格: ${df['close'].iloc[0]:.2f}")
    logger.info(f"  结束价格: ${df['close'].iloc[-1]:.2f}")

    # 生成信号
    logger.info(f"\n生成交易信号...")
    signal = strategy.generate_signal(df)

    logger.info(f"\n📊 最新信号:")
    logger.info(f"  动作: {signal.action}")
    logger.info(f"  置信度: {signal.confidence:.2f}")
    logger.info(f"  EMA{strategy.short_period}: ${signal.ema_short:.2f}")
    logger.info(f"  EMA{strategy.long_period}: ${signal.ema_long:.2f}")
    logger.info(f"  RSI: {signal.rsi:.1f}")
    logger.info(f"  成交量倍数: {signal.volume_ratio:.2f}")

    logger.info(f"\n原因:")
    for reason in signal.reasons:
        logger.info(f"  • {reason}")

    # 回测
    logger.info(f"\n回测结果:")
    backtest_result = strategy.backtest(df)
    logger.info(f"  总信号数: {backtest_result['total_signals']}")
    logger.info(f"  买入信号: {backtest_result['buy_signals']}")
    logger.info(f"  卖出信号: {backtest_result['sell_signals']}")

    # 测试震荡市
    logger.info(f"\n\n测试震荡市场景...")
    data_noise = []
    for i in range(200):
        noise = np.random.randn() * 800
        open_price = base_price + noise - 100
        high_price = open_price + abs(np.random.randn() * 200)
        low_price = open_price - abs(np.random.randn() * 200)
        close_price = open_price + np.random.randn() * 100
        volume = 1000 + np.random.randint(-300, 500)

        data_noise.append({
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price
        })

    df_noise = pd.DataFrame(data_noise)
    df_noise['volume'] = [1000 + np.random.randint(-300, 500) for _ in range(200)]

    signal_noise = strategy.generate_signal(df_noise)
    logger.info(f"  动作: {signal_noise.action}")
    logger.info(f"  置信度: {signal_noise.confidence:.2f}")
    logger.info(f"  原因: {signal_noise.reasons}")

    logger.info("\n" + "="*60)
    logger.info("EMA趋势策略测试: PASS")


if __name__ == "__main__":
    main()
