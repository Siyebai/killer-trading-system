#!/usr/bin/env python3
"""
测试高胜率策略的胜率
"""
import sys
sys.path.insert(0, '/workspace/projects/trading-simulator/scripts')

import pandas as pd
import numpy as np
import json
from high_winrate_strategy import HighWinrateStrategy

def generate_realistic_data(days=60):
    """生成更真实的测试数据"""
    np.random.seed(123)

    total_periods = days * 24
    dates = pd.date_range(start='2024-01-01', periods=total_periods, freq='h')
    base_price = 50000

    # 模拟真实市场的数据生成
    price_path = [base_price]

    for i in range(1, total_periods):
        # 不同阶段的市场特征
        if i < total_periods * 0.3:
            # 趋势上涨
            change = np.random.randn() * 150 + 80
        elif i < total_periods * 0.5:
            # 震荡
            change = np.random.randn() * 80
        elif i < total_periods * 0.7:
            # 趋势下跌
            change = np.random.randn() * 150 - 80
        else:
            # 突破上涨
            change = np.random.randn() * 200 + 100

        new_price = price_path[-1] + change
        price_path.append(new_price)

    prices = np.array(price_path)

    data = {
        'timestamp': dates,
        'open': prices,
        'high': prices + np.random.rand(total_periods) * 200,
        'low': prices - np.random.rand(total_periods) * 200,
        'close': prices,
        'volume': np.random.randint(2000, 10000, total_periods)
    }
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)

    # 确保high >= open/close >= low
    df['high'] = df[['open', 'close', 'high']].max(axis=1)
    df['low'] = df[['open', 'close', 'low']].min(axis=1)

    return df

def run_backtest(strategy, df, min_confidence=0.7):
    """运行回测"""
    capital = 10000
    position = 0
    entry_price = 0
    stop_loss = 0
    take_profit = 0

    trades = []
    total_trades = 0
    winning_trades = 0

    for i in range(60, len(df)):
        current_df = df.iloc[:i+1]
        signal = strategy.generate_signals(current_df)
        current_price = df['close'].iloc[i]

        # 入场
        if position == 0 and signal['direction'] != 'NEUTRAL':
            if signal['confidence'] >= min_confidence:
                position_size = capital * 0.02
                position = position_size / current_price
                entry_price = current_price
                stop_loss = signal['stop_loss']
                take_profit = signal['take_profit']

        # 出场
        elif position != 0:
            exit_triggered = False
            exit_reason = ''

            if signal['direction'] == 'LONG':
                if current_price <= stop_loss:
                    exit_triggered = True
                    exit_reason = 'stop_loss'
                elif current_price >= take_profit:
                    exit_triggered = True
                    exit_reason = 'take_profit'
            else:
                if current_price >= stop_loss:
                    exit_triggered = True
                    exit_reason = 'stop_loss'
                elif current_price <= take_profit:
                    exit_triggered = True
                    exit_reason = 'take_profit'

            if exit_triggered:
                if signal['direction'] == 'LONG':
                    profit = position * (current_price - entry_price)
                else:
                    profit = position * (entry_price - current_price)

                capital += profit

                trades.append({
                    'type': signal['direction'],
                    'entry': entry_price,
                    'exit': current_price,
                    'profit': profit,
                    'exit_reason': exit_reason
                })

                total_trades += 1
                if profit > 0:
                    winning_trades += 1

                position = 0
                entry_price = 0

    # 计算结果
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    total_return = (capital - 10000) / 10000

    return {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'win_rate': win_rate,
        'total_return': total_return,
        'final_capital': capital,
        'trades': trades
    }

def main():
    print("=" * 70)
    print("🚀 高胜率策略回测 - v1.0.3")
    print("=" * 70)

    # 创建策略
    strategy = HighWinrateStrategy()

    # 生成测试数据
    print("\n📊 生成测试数据...")
    df = generate_realistic_data(days=60)

    # 测试不同置信度阈值
    thresholds = [0.65, 0.70, 0.75, 0.80]

    print("\n🎯 测试不同置信度阈值:")
    print("-" * 70)

    best_result = None

    for threshold in thresholds:
        result = run_backtest(strategy, df, min_confidence=threshold)

        print(f"\n置信度阈值: {threshold:.2%}")
        print(f"  总交易: {result['total_trades']}")
        print(f"  盈利交易: {result['winning_trades']}")
        print(f"  胜率: {result['win_rate']:.2%}")
        print(f"  总收益: {result['total_return']:.2%}")

        if result['total_trades'] >= 10:
            if best_result is None or result['win_rate'] > best_result['win_rate']:
                best_result = result
                best_result['threshold'] = threshold

    print("\n" + "=" * 70)
    print("📊 最佳结果:")
    print("=" * 70)

    if best_result:
        print(f"置信度阈值: {best_result['threshold']:.2%}")
        print(f"胜率: {best_result['win_rate']:.2%}")
        print(f"总收益: {best_result['total_return']:.2%}")
        print(f"总交易: {best_result['total_trades']}")

        if best_result['win_rate'] >= 0.65:
            print(f"\n🎉 成功！胜率达到目标 65%+")
        else:
            gap = 0.65 - best_result['win_rate']
            print(f"\n⚠️  胜率未达标，差距: {gap:.2%}")

        # 保存结果
        output_path = "/workspace/projects/trading-simulator/high_winrate_test_results.json"
        with open(output_path, 'w') as f:
            json.dump(best_result, f, indent=2)
        print(f"\n📄 结果已保存: {output_path}")

if __name__ == "__main__":
    main()
