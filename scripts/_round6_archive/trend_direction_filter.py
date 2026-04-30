# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.3 - 趋势方向过滤器
P0修复：解决连续32笔亏损和单边做多问题
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional
from datetime import datetime
from pathlib import Path
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trend_filter")


class TrendDirectionFilter:
    """
    趋势方向过滤器
    核心功能：
    1. 基于EMA200判断市场趋势
    2. 空头市场禁止做多
    3. 多头市场禁止做空
    4. 防止单边交易导致的连续亏损
    """

    def __init__(self, ema_period: int = 200):
        """初始化过滤器"""
        self.ema_period = ema_period or 200
        self.trend_threshold_long = 1.005   # 价格在EMA200上方0.5%为多头
        self.trend_threshold_short = 0.995  # 价格在EMA200下方0.5%为空头

        # 统计信息
        self.long_market_count = 0
        self.short_market_count = 0
        self.neutral_market_count = 0
        self.blocked_long_signals = 0
        self.blocked_short_signals = 0

        logger.info(f"✅ 趋势方向过滤器初始化完成 (EMA{self.ema_period})")

    def detect_market_regime(self, df: pd.DataFrame) -> str:
        """
        检测市场环境
        返回: 'LONG' (多头) / 'SHORT' (空头) / 'NEUTRAL' (中性)
        """
        if df is None or len(df) < self.ema_period:
            return 'NEUTRAL'

        # 计算EMA200
        ema = df['close'].ewm(span=self.ema_period).mean()
        current_price = df['close'].iloc[-1]
        current_ema = ema.iloc[-1]

        # 判断市场环境
        price_to_ema = current_price / current_ema

        if price_to_ema >= self.trend_threshold_long:
            regime = 'LONG'
            self.long_market_count += 1
        elif price_to_ema <= self.trend_threshold_short:
            regime = 'SHORT'
            self.short_market_count += 1
        else:
            regime = 'NEUTRAL'
            self.neutral_market_count += 1

        return regime

    def filter_signal(self, signal: Dict, df: pd.DataFrame) -> Optional[Dict]:
        """
        过滤交易信号
        根据市场环境过滤不符合趋势方向的信号

        返回：
        - 信号有效：返回原信号（添加market_regime字段）
        - 信号被过滤：返回None
        """
        # 检测市场环境
        market_regime = self.detect_market_regime(df)

        # 获取信号方向
        signal_direction = signal.get('direction', 'NEUTRAL')

        # 过滤逻辑
        if market_regime == 'SHORT':
            # 空头市场：禁止做多
            if signal_direction == 'LONG':
                self.blocked_long_signals += 1
                logger.warning(f"🚫 阻止做多信号 - 空头市场 (价格/EMA200: {df['close'].iloc[-1]/df['close'].ewm(span=self.ema_period).mean().iloc[-1]:.3f})")
                return None

        elif market_regime == 'LONG':
            # 多头市场：禁止做空
            if signal_direction == 'SHORT':
                self.blocked_short_signals += 1
                logger.warning(f"🚫 阻止做空信号 - 多头市场 (价格/EMA200: {df['close'].iloc[-1]/df['close'].ewm(span=self.ema_period).mean().iloc[-1]:.3f})")
                return None

        # 信号有效，添加市场环境信息
        signal['market_regime'] = market_regime
        signal['trend_filter_enabled'] = True

        logger.debug(f"✅ 信号通过 - 方向: {signal_direction}, 市场: {market_regime}")

        return signal

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        total = self.long_market_count + self.short_market_count + self.neutral_market_count

        stats = {
            'long_market_pct': self.long_market_count / total * 100 if total > 0 else 0,
            'short_market_pct': self.short_market_count / total * 100 if total > 0 else 0,
            'neutral_market_pct': self.neutral_market_count / total * 100 if total > 0 else 0,
            'blocked_long_signals': self.blocked_long_signals,
            'blocked_short_signals': self.blocked_short_signals
        }

        return stats

    def reset_statistics(self):
        """重置统计信息"""
        self.long_market_count = 0
        self.short_market_count = 0
        self.neutral_market_count = 0
        self.blocked_long_signals = 0
        self.blocked_short_signals = 0


class MaxConsecutiveLossFilter:
    """
    最大连续亏损过滤器
    P0修复：防止连续亏损导致爆仓
    """

    def __init__(self, max_consecutive_losses: int = 5, daily_loss_limit: float = 3.0):
        """
        初始化

        参数：
        - max_consecutive_losses: 最大连续亏损笔数（默认5笔）
        - daily_loss_limit: 单日最大亏损百分比（默认3%）
        """
        self.max_consecutive_losses = max_consecutive_losses or 5
        self.daily_loss_limit = daily_loss_limit or 3.0

        # 状态追踪
        self.consecutive_losses = 0
        self.daily_loss = 0.0
        self.last_reset_date = datetime.now().date()
        self.is_blocked = False
        self.block_until = None

        # 统计
        self.triggered_count = 0  # 熔断触发次数

        logger.info(f"✅ 最大连续亏损过滤器初始化完成 (最大{self.max_consecutive_losses}笔, 日限{self.daily_loss_limit}%)")

    def check_and_update(self, profit: float, reset_daily: bool = True) -> Tuple[bool, str]:
        """
        检查并更新状态

        参数：
        - profit: 当前交易盈亏（正数盈利，负数亏损）
        - reset_daily: 是否检查日重置

        返回：
        - (is_allowed, reason): 是否允许交易，原因说明
        """
        current_date = datetime.now().date()

        # 检查日重置
        if reset_daily and current_date != self.last_reset_date:
            self.consecutive_losses = 0
            self.daily_loss = 0.0
            self.last_reset_date = current_date
            self.is_blocked = False
            self.block_until = None
            logger.info("📅 新的一天，重置连续亏损计数")

        # 检查是否在熔断期
        if self.is_blocked and self.block_until and datetime.now() < self.block_until:
            remaining = (self.block_until - datetime.now()).total_seconds() / 3600
            return False, f"熔断中，还需等待{remaining:.1f}小时"

        # 检查连续亏损
        if profit < 0:
            self.consecutive_losses += 1
            self.daily_loss += abs(profit)

            # 触发熔断
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.triggered_count += 1
                self.is_blocked = True
                self.block_until = datetime.now() + pd.Timedelta(hours=24)

                logger.error(f"🚨 熔断触发！连续{self.consecutive_losses}笔亏损，停仓24小时")
                return False, f"熔断触发：连续{self.consecutive_losses}笔亏损，停仓24小时"

            # 检查日亏损限制
            if abs(self.daily_loss) >= self.daily_loss_limit:
                self.triggered_count += 1
                self.is_blocked = True
                self.block_until = datetime.now() + pd.Timedelta(hours=24)

                logger.error(f"🚨 熔断触发！日亏损{self.daily_loss:.2f}%，停仓24小时")
                return False, f"熔断触发：日亏损{self.daily_loss:.2f}%，停仓24小时"
        else:
            # 盈利，重置连续亏损
            self.consecutive_losses = 0

        return True, "正常"

    def get_status(self) -> Dict:
        """获取当前状态"""
        return {
            'consecutive_losses': self.consecutive_losses,
            'daily_loss': self.daily_loss,
            'is_blocked': self.is_blocked,
            'block_until': self.block_until.isoformat() if self.block_until else None,
            'triggered_count': self.triggered_count
        }

    def reset(self):
        """手动重置（仅用于测试）"""
        self.consecutive_losses = 0
        self.daily_loss = 0.0
        self.is_blocked = False
        self.block_until = None


if __name__ == "__main__":
    print("=" * 70)
    print("🧪 趋势过滤器测试")
    print("=" * 70)

    # 创建过滤器
    trend_filter = TrendDirectionFilter()

    # 测试数据
    np.random.seed(999)
    dates = pd.date_range(start='2024-01-01', periods=300, freq='h')
    prices = 50000 + np.cumsum(np.random.randn(300) * 100)

    # 模拟下跌趋势
    prices[100:] = prices[100] - np.arange(200) * 50  # 强烈下跌

    df = pd.DataFrame({
        'timestamp': dates,
        'close': prices
    })
    df.set_index('timestamp', inplace=True)

    # 测试过滤
    print("\n📊 测试趋势过滤:")
    print("-" * 70)

    test_signals = [
        {'direction': 'LONG', 'confidence': 0.7},
        {'direction': 'SHORT', 'confidence': 0.7},
        {'direction': 'LONG', 'confidence': 0.8},
    ]

    for i in range(100, min(150, len(df))):
        current_df = df.iloc[:i+1]

        for signal in test_signals:
            filtered = trend_filter.filter_signal(signal.copy(), current_df)
            status = "✅ 通过" if filtered else "🚫 阻止"
            print(f"Bar {i}: {signal['direction']} - {status}")

        if i == 110:
            print("...\n（仅显示部分）")
            break

    # 显示统计
    print("\n📊 过滤器统计:")
    stats = trend_filter.get_statistics()
    print(f"  多头市场: {stats['long_market_pct']:.1f}%")
    print(f"  空头市场: {stats['short_market_pct']:.1f}%")
    print(f"  阻止做多: {stats['blocked_long_signals']}次")
    print(f"  阻止做空: {stats['blocked_short_signals']}次")

    # 测试连续亏损熔断
    print("\n" + "=" * 70)
    print("🧪 连续亏损熔断测试")
    print("=" * 70)

    loss_filter = MaxConsecutiveLossFilter(max_consecutive_losses=3, daily_loss_limit=2.0)

    test_profits = [-1.5, -2.0, -1.8, -2.2, 3.0, -1.0, -1.5]  # 模拟连续亏损

    print("\n📊 模拟交易序列:")
    for i, profit in enumerate(test_profits, 1):
        allowed, reason = loss_filter.check_and_update(profit)
        status = "✅ 允许" if allowed else "🚫 拒绝"
        print(f"交易{i}: {profit:+.2f}% - {status} ({reason})")

        status = loss_filter.get_status()
        print(f"  连续亏损: {status['consecutive_losses']}笔")

    print("\n✅ 测试完成")
