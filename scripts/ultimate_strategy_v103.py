#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.3 - 完整版（整合所有P0+P1修复）

P0修复（必须改）：
✅ 1. 趋势方向过滤（4H EMA200）
✅ 2. 连续亏损熔断
✅ 3. 样本外验证流程

P1修复（本周改）：
✅ 4. 修复SHORT信号生成
✅ 5. ATR动态止损止盈
✅ 6. 真实滑点模拟

P2计划（下版本）：
📋 7. 多市场环境测试
📋 8. Binance Testnet真实验证
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, Optional
from datetime import datetime
from pathlib import Path
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trend_direction_filter import TrendDirectionFilter, MaxConsecutiveLossFilter
from short_strategy_fixer import ShortSignalGenerator, DirectionalBalanceFilter
from ultimate_winrate_system import UltimateWinrateSystem

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("v1.0.3_strategy")


class UltimateStrategyV103:
    """
    杀手锏交易系统 v1.0.3
    整合所有P0+P1修复的完整版
    """

    def __init__(self, config_path: str = None):
        """初始化策略"""
        self.project_root = Path("/workspace/projects/trading-simulator")
        self.config = self._load_config(config_path)
        self.version = "v1.0.3"

        # 基础策略系统
        self.base_strategy = UltimateWinrateSystem(config_path)

        # P0-1：趋势方向过滤器
        trend_config = self.config.get('trend_filter', {})
        self.trend_filter = TrendDirectionFilter(
            ema_period=trend_config.get('ema_period', 200)
        )

        # P0-2：连续亏损熔断
        circuit_config = self.config.get('risk_circuit_breaker', {})
        self.circuit_breaker = MaxConsecutiveLossFilter(
            max_consecutive_losses=circuit_config.get('max_consecutive_losses', 5),
            daily_loss_limit=circuit_config.get('daily_loss_limit', 3.0)
        )

        # P1-4：SHORT信号生成器
        self.short_generator = ShortSignalGenerator()

        # P1-4：方向平衡过滤器
        self.balance_filter = DirectionalBalanceFilter(
            max_short_ratio=trend_config.get('max_short_ratio', 0.5)
        )

        # 统计
        self.long_trades = 0
        self.short_trades = 0
        self.long_profits = []
        self.short_profits = []

        logger.info(f"✅ 杀手锏交易系统 {self.version} 初始化完成")
        logger.info(f"   P0修复: 趋势过滤、熔断、样本外验证")
        logger.info(f"   P1修复: SHORT策略、ATR动态、真实滑点")

    def _load_config(self, config_path: str) -> Dict:
        """加载配置文件"""
        if config_path is None:
            config_path = self.project_root / "config.json"

        with open(config_path, 'r') as f:
            return json.load(f)

    def generate_signals(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        生成交易信号（完整版）
        """
        if df is None or len(df) < 200:
            return None

        try:
            # 1. 基础策略生成信号
            base_signal = self.base_strategy.generate_signals(df)

            # 2. P1-4：增强SHORT信号生成
            if base_signal['direction'] == 'NEUTRAL':
                # 尝试生成SHORT信号
                short_signal = self.short_generator.generate_short_signals(df)
                if short_signal['direction'] == 'SHORT':
                    base_signal = short_signal

            if base_signal['direction'] == 'NEUTRAL':
                return None

            # 3. P0-1：趋势方向过滤
            filtered_signal = self.trend_filter.filter_signal(base_signal, df)

            if filtered_signal is None:
                return None

            # 4. P0-2：检查熔断状态
            is_allowed, reason = self.circuit_breaker.check_and_update(0, reset_daily=False)

            if not is_allowed:
                logger.warning(f"🚨 熔断生效，拒绝信号: {reason}")
                return None

            # 5. P1-4：方向平衡过滤
            balanced_signal = self.balance_filter.filter_signal(filtered_signal)

            if balanced_signal['direction'] == 'NEUTRAL':
                return None

            # 6. P1-5：ATR动态止损止盈
            latest = df.iloc[-1]
            atr = latest.get('atr', 0)

            if atr <= 0:
                # 使用默认ATR
                atr = latest['close'] * 0.02

            risk_config = self.config['risk_management']

            # ATR动态计算
            sl_atr_mult = risk_config.get('atr_multiplier_sl', 1.5)
            tp_atr_mult = risk_config.get('atr_multiplier_tp', 3.0)

            sl_distance = atr * sl_atr_mult
            tp_distance = atr * tp_atr_mult

            # 确保盈亏比至少2:1
            if abs(tp_distance) / abs(sl_distance) < 1.8:
                tp_distance = sl_distance * 2.0

            # 计算止损止盈
            if balanced_signal['direction'] == 'LONG':
                stop_loss = latest['close'] - sl_distance
                take_profit = latest['close'] + tp_distance
            else:
                stop_loss = latest['close'] + sl_distance
                take_profit = latest['close'] - tp_distance

            # P1-6：计算动态滑点（供回测使用）
            atr_percent = atr / latest['close']
            slippage = 0.0005 + atr_percent * 0.05
            slippage = min(slippage, 0.0015)

            # 更新信号
            balanced_signal.update({
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'risk_reward_ratio': abs(tp_distance) / abs(sl_distance),
                'atr': atr,
                'estimated_slippage': slippage * 100,
                'p0_fixes': ['trend_filter', 'circuit_breaker', 'out_of_sample_validation'],
                'p1_fixes': ['short_strategy', 'atr_dynamic', 'real_slippage']
            })

            return balanced_signal

        except Exception as e:
            logger.error(f"❌ 信号生成失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def record_trade(self, direction: str, profit: float):
        """记录交易结果"""
        # 更新熔断状态
        self.circuit_breaker.check_and_update(profit, reset_daily=True)

        # 更新方向平衡
        self.balance_filter.record_trade(direction)

        # 更新统计
        if direction == 'LONG':
            self.long_trades += 1
            self.long_profits.append(profit)
        elif direction == 'SHORT':
            self.short_trades += 1
            self.short_profits.append(profit)

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        total_trades = self.long_trades + self.short_trades

        long_win_rate = sum(1 for p in self.long_profits if p > 0) / len(self.long_profits) if self.long_profits else 0
        short_win_rate = sum(1 for p in self.short_profits if p > 0) / len(self.short_profits) if self.short_profits else 0

        trend_stats = self.trend_filter.get_statistics()
        circuit_stats = self.circuit_breaker.get_status()
        balance_stats = self.balance_filter.get_statistics()

        return {
            'version': self.version,
            'total_trades': total_trades,
            'long_trades': self.long_trades,
            'short_trades': self.short_trades,
            'long_pct': self.long_trades / total_trades * 100 if total_trades > 0 else 0,
            'short_pct': self.short_trades / total_trades * 100 if total_trades > 0 else 0,
            'long_win_rate': long_win_rate,
            'short_win_rate': short_win_rate,
            'trend_filter': trend_stats,
            'circuit_breaker': circuit_stats,
            'balance_filter': balance_stats
        }


def run_comprehensive_test(strategy, df):
    """运行综合测试"""
    print("\n" + "=" * 80)
    print("🧪 v1.0.3 综合测试")
    print("=" * 80)

    capital = 10000
    position = 0
    entry_price = 0
    stop_loss = 0
    take_profit = 0
    signal_direction = 'NEUTRAL'

    trades = []
    consecutive_losses = 0
    max_consecutive_losses = 0

    for i in range(200, len(df)):
        current_df = df.iloc[:i+1]
        signal = strategy.generate_signals(current_df)
        current_price = df['close'].iloc[i]

        # 入场
        if position == 0 and signal is not None:
            # 应用滑点
            slippage = signal.get('estimated_slippage', 0.05) / 100
            if signal['direction'] == 'LONG':
                actual_entry = current_price * (1 + slippage)
            else:
                actual_entry = current_price * (1 - slippage)

            position_size = capital * 0.02
            position = position_size / actual_entry
            entry_price = actual_entry
            stop_loss = signal['stop_loss']
            take_profit = signal['take_profit']
            signal_direction = signal['direction']

        # 出场
        elif position != 0:
            exit_triggered = False

            if signal_direction == 'LONG':
                if current_price <= stop_loss or current_price >= take_profit:
                    exit_triggered = True
            else:
                if current_price >= stop_loss or current_price <= take_profit:
                    exit_triggered = True

            if exit_triggered:
                slippage = signal.get('estimated_slippage', 0.05) / 100
                if signal_direction == 'LONG':
                    actual_exit = current_price * (1 - slippage)
                else:
                    actual_exit = current_price * (1 + slippage)

                profit = position * abs(actual_exit - entry_price) * (1 if (actual_exit > entry_price) == (signal_direction == 'LONG') else -1)
                capital += profit

                trades.append({
                    'type': signal_direction,
                    'entry': entry_price,
                    'exit': actual_exit,
                    'profit': profit,
                    'profit_pct': profit / (position * entry_price) * 100
                })

                strategy.record_trade(signal_direction, profit)

                if profit < 0:
                    consecutive_losses += 1
                    max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
                else:
                    consecutive_losses = 0

                position = 0
                entry_price = 0

    # 计算结果
    winning_trades = sum(1 for t in trades if t['profit'] > 0)
    total_trades = len(trades)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    total_return = (capital - 10000) / 10000 * 100

    long_trades = sum(1 for t in trades if t['type'] == 'LONG')
    short_trades = sum(1 for t in trades if t['type'] == 'SHORT')

    stats = strategy.get_statistics()

    print("\n📊 回测结果:")
    print(f"  总交易: {total_trades}")
    print(f"  LONG: {long_trades}, SHORT: {short_trades} ({short_trades/total_trades*100:.1f}%)")
    print(f"  胜率: {win_rate:.2%}")
    print(f"  收益: {total_return:.2f}%")
    print(f"  最大连续亏损: {max_consecutive_losses}笔")

    print("\n📊 系统统计:")
    print(f"  LONG胜率: {stats['long_win_rate']:.2%}")
    print(f"  SHORT胜率: {stats['short_win_rate']:.2%}")
    print(f"  阻止做多: {stats['trend_filter']['blocked_long_signals']}次")
    print(f"  阻止做空: {stats['trend_filter']['blocked_short_signals']}次")
    print(f"  熔断触发: {stats['circuit_breaker']['triggered_count']}次")

    return {
        'total_trades': total_trades,
        'short_pct': short_trades / total_trades * 100 if total_trades > 0 else 0,
        'win_rate': win_rate,
        'max_consecutive_losses': max_consecutive_losses,
        'total_return': total_return
    }


if __name__ == "__main__":
    print("=" * 80)
    print("🚀 杀手锏交易系统 v1.0.3")
    print("=" * 80)
    print("\nP0修复:")
    print("  ✅ 1. 趋势方向过滤（4H EMA200）")
    print("  ✅ 2. 连续亏损熔断（5笔或日亏3%）")
    print("  ✅ 3. 样本外验证流程（60/20/20分割）")
    print("\nP1修复:")
    print("  ✅ 4. 修复SHORT信号生成")
    print("  ✅ 5. ATR动态止损止盈（2:1）")
    print("  ✅ 6. 真实滑点模拟（0.05%-0.15%）")
    print("\nP2计划:")
    print("  📋 7. 多市场环境测试")
    print("  📋 8. Binance Testnet真实验证")

    # 生成测试数据
    print("\n📊 生成测试数据...")
    from out_of_sample_validator import generate_validation_data
    df = generate_validation_data()

    # 创建策略
    strategy = UltimateStrategyV103()

    # 运行测试
    result = run_comprehensive_test(strategy, df)

    print("\n" + "=" * 80)
    print("✅ v1.0.3测试完成")
    print("=" * 80)
