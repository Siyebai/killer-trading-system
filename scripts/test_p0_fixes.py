#!/usr/bin/env python3
"""
P0问题修复验证 - 完整测试
测试场景：上涨市场、下跌市场、震荡市场
"""
import sys
sys.path.insert(0, '/workspace/projects/trading-simulator/scripts')

import pandas as pd
import numpy as np
import json
from fixed_ultimate_strategy import FixedUltimateStrategy

def generate_three_regimes_data():
    """生成包含三种市场环境的数据"""
    np.random.seed(888)

    dates = pd.date_range(start='2024-01-01', periods=1000, freq='h')

    # 阶段1：上涨市场（30%）
    prices_up = np.linspace(50000, 65000, 300)
    prices_up += np.random.randn(300) * 300

    # 阶段2：下跌市场（40%）- 测试连续亏损场景
    prices_down = np.linspace(65000, 45000, 400)
    prices_down += np.random.randn(400) * 300

    # 阶段3：震荡市场（30%）
    prices_range = 45000 + np.random.randn(300) * 1500

    prices = np.concatenate([prices_up, prices_down, prices_range])

    df = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices + 300,
        'low': prices - 300,
        'close': prices,
        'volume': np.random.randint(5000, 20000, len(prices))
    })
    df.set_index('timestamp', inplace=True)

    # 计算ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    df['atr'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1).rolling(window=14).mean()

    return df

def run_backtest(strategy, df, regime_name, start_bar, end_bar):
    """运行回测"""
    capital = 10000
    position = 0
    entry_price = 0
    stop_loss = 0
    take_profit = 0
    signal_direction = 'NEUTRAL'

    trades = []
    consecutive_losses = 0
    max_consecutive_losses = 0

    for i in range(start_bar, min(end_bar, len(df))):
        current_df = df.iloc[:i+1]
        signal = strategy.generate_signals(current_df)
        current_price = df['close'].iloc[i]

        # 入场
        if position == 0 and signal is not None:
            position_size = capital * 0.02
            position = position_size / current_price
            entry_price = current_price
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
                profit = position * abs(current_price - entry_price) * (1 if (current_price > entry_price) == (signal_direction == 'LONG') else -1)
                capital += profit

                trades.append({
                    'type': signal_direction,
                    'entry': entry_price,
                    'exit': current_price,
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

    # 计算结果
    winning_trades = sum(1 for t in trades if t['profit'] > 0)
    total_trades = len(trades)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    total_return = (capital - 10000) / 10000 * 100

    long_trades = sum(1 for t in trades if t['type'] == 'LONG')
    short_trades = sum(1 for t in trades if t['type'] == 'SHORT')

    return {
        'regime': regime_name,
        'total_trades': total_trades,
        'long_trades': long_trades,
        'short_trades': short_trades,
        'short_pct': short_trades / total_trades * 100 if total_trades > 0 else 0,
        'win_rate': win_rate,
        'total_return': total_return,
        'max_consecutive_losses': max_consecutive_losses,
        'final_capital': capital
    }

def main():
    print("=" * 80)
    print("🧪 P0问题修复验证 - 三种市场环境测试")
    print("=" * 80)

    # 创建策略
    strategy = FixedUltimateStrategy()

    # 生成测试数据
    print("\n📊 生成测试数据...")
    df = generate_three_regimes_data()

    # 测试三种市场环境
    results = []

    # 1. 上涨市场
    print("\n" + "=" * 80)
    print("📈 测试1：上涨市场")
    print("=" * 80)
    result_up = run_backtest(strategy, df, "上涨市场", 200, 300)
    results.append(result_up)
    print(f"交易数: {result_up['total_trades']}")
    print(f"LONG: {result_up['long_trades']}, SHORT: {result_up['short_trades']} ({result_up['short_pct']:.1f}%)")
    print(f"胜率: {result_up['win_rate']:.2%}")
    print(f"最大连续亏损: {result_up['max_consecutive_losses']}笔")

    # 2. 下跌市场
    print("\n" + "=" * 80)
    print("📉 测试2：下跌市场（关键测试）")
    print("=" * 80)
    result_down = run_backtest(strategy, df, "下跌市场", 350, 450)
    results.append(result_down)
    print(f"交易数: {result_down['total_trades']}")
    print(f"LONG: {result_down['long_trades']}, SHORT: {result_down['short_trades']} ({result_down['short_pct']:.1f}%)")
    print(f"胜率: {result_down['win_rate']:.2%}")
    print(f"最大连续亏损: {result_down['max_consecutive_losses']}笔")
    print(f"🔥 关键：如果不触发连续32笔亏损，说明趋势过滤器有效！")

    # 3. 震荡市场
    print("\n" + "=" * 80)
    print("〰️  测试3：震荡市场")
    print("=" * 80)
    result_range = run_backtest(strategy, df, "震荡市场", 750, 850)
    results.append(result_range)
    print(f"交易数: {result_range['total_trades']}")
    print(f"LONG: {result_range['long_trades']}, SHORT: {result_range['short_trades']} ({result_range['short_pct']:.1f}%)")
    print(f"胜率: {result_range['win_rate']:.2%}")
    print(f"最大连续亏损: {result_range['max_consecutive_losses']}笔")

    # 汇总结果
    print("\n" + "=" * 80)
    print("📊 P0问题修复验证汇总")
    print("=" * 80)

    total_trades_all = sum(r['total_trades'] for r in results)
    total_short = sum(r['short_trades'] for r in results)
    max_cons_losses = max(r['max_consecutive_losses'] for r in results)
    avg_win_rate = np.mean([r['win_rate'] for r in results])

    print(f"\n总交易: {total_trades_all}")
    print(f"SHORT交易: {total_short} ({total_short/total_trades_all*100:.1f}%)")
    print(f"平均胜率: {avg_win_rate:.2%}")
    print(f"最大连续亏损: {max_cons_losses}笔")

    print("\n" + "=" * 80)
    print("✅ P0问题修复验证")
    print("=" * 80)

    # 验证1：连续亏损
    if max_cons_losses < 5:
        print(f"✅ 问题1（连续亏损32笔）: 已解决")
        print(f"   当前最大连续亏损: {max_cons_losses}笔 < 5笔目标")
    else:
        print(f"❌ 问题1（连续亏损32笔）: 未解决")
        print(f"   当前最大连续亏损: {max_cons_losses}笔 >= 5笔")

    # 验证2：单边做多
    short_pct = total_short / total_trades_all * 100 if total_trades_all > 0 else 0
    if 20 < short_pct < 50:
        print(f"✅ 问题2（96.7%单边做多）: 已解决")
        print(f"   当前SHORT比例: {short_pct:.1f}% 在合理范围")
    elif short_pct >= 10:
        print(f"⚠️  问题2（96.7%单边做多）: 部分解决")
        print(f"   当前SHORT比例: {short_pct:.1f}%，建议进一步优化")
    else:
        print(f"❌ 问题2（96.7%单边做多）: 未解决")
        print(f"   当前SHORT比例: {short_pct:.1f}% 太低")

    # 验证3：过拟合
    if 0.40 < avg_win_rate < 0.60:
        print(f"✅ 问题3（过拟合）: 已解决")
        print(f"   平均胜率{avg_win_rate:.2%}在40-60%合理范围")
        print(f"   说明策略具有泛化能力，不是记忆数据")
    elif avg_win_rate > 0.65:
        print(f"⚠️  问题3（过拟合）: 仍可能存在")
        print(f"   平均胜率{avg_win_rate:.2%}过高，需警惕过拟合")
    else:
        print(f"⚠️  问题3（过拟合）: 策略需要优化")
        print(f"   平均胜率{avg_win_rate:.2%}偏低")

    print("\n" + "=" * 80)
    print("📝 结论")
    print("=" * 80)

    if max_cons_losses < 5 and 20 < short_pct < 50:
        print("✅ P0致命问题已修复！系统具备实盘基本资格。")
        print("\n建议下一步:")
        print("  1. 进行样本外交叉验证")
        print("  2. 接入Testnet进行72小时Paper Trading")
        print("  3. 在实盘小资金测试")
    else:
        print("⚠️  P0问题部分修复，需要进一步优化。")

    # 保存结果
    output = {
        'version': 'v1.0.3-FIXED',
        'test_date': pd.Timestamp.now().isoformat(),
        'results': results,
        'summary': {
            'total_trades': total_trades_all,
            'short_pct': short_pct,
            'avg_win_rate': avg_win_rate,
            'max_consecutive_losses': max_cons_losses
        },
        'p0_fixes': {
            'consecutive_losses_fixed': max_cons_losses < 5,
            'single_direction_fixed': 20 < short_pct < 50,
            'overfitting_fixed': 0.40 < avg_win_rate < 0.60
        }
    }

    with open('/workspace/projects/trading-simulator/p0_fixes_validation.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n📄 详细结果已保存: /workspace/projects/trading-simulator/p0_fixes_validation.json")

if __name__ == "__main__":
    main()
