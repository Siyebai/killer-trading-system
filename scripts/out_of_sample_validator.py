#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.3 - 样本外验证系统
P0修复：防止过拟合，确保策略泛化能力

核心逻辑：
- 历史数据分三段：60%训练 / 20%验证 / 20%最终测试
- 验证集用于调参，测试集只测一次
- 避免在同一段数据上反复优化
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from pathlib import Path
import logging
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fixed_ultimate_strategy import FixedUltimateStrategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("out_of_sample_validation")


class OutOfSampleValidator:
    """
    样本外验证系统
    防止过拟合的核心机制
    """

    def __init__(self, config_path: str = None):
        """初始化验证器"""
        self.project_root = Path("/workspace/projects/trading-simulator")
        self.config_path = config_path or (self.project_root / "config.json")
        self.version = "v1.0.3"

        # 数据分割比例
        self.train_ratio = 0.60
        self.val_ratio = 0.20
        self.test_ratio = 0.20

        logger.info(f"✅ 样本外验证系统 {self.version} 初始化完成")

    def split_data(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        分割数据为三段
        返回：(训练集, 验证集, 测试集)
        """
        total_len = len(df)
        train_end = int(total_len * self.train_ratio)
        val_end = train_end + int(total_len * self.val_ratio)

        train_df = df.iloc[:train_end]
        val_df = df.iloc[train_end:val_end]
        test_df = df.iloc[val_end:]

        logger.info(f"📊 数据分割完成:")
        logger.info(f"  训练集: {len(train_df)} 条 ({self.train_ratio*100:.0f}%)")
        logger.info(f"  验证集: {len(val_df)} 条 ({self.val_ratio*100:.0f}%)")
        logger.info(f"  测试集: {len(test_df)} 条 ({self.test_ratio*100:.0f}%)")

        return train_df, val_df, test_df

    def run_backtest(self, strategy, df: pd.DataFrame, dataset_name: str = "") -> Dict:
        """
        运行回测（带真实滑点）
        """
        capital = 10000
        position = 0
        entry_price = 0
        stop_loss = 0
        take_profit = 0
        signal_direction = 'NEUTRAL'

        trades = []
        consecutive_losses = 0
        max_consecutive_losses = 0

        for i in range(200, len(df)):  # 前200条用于计算指标
            current_df = df.iloc[:i+1]
            signal = strategy.generate_signals(current_df)
            current_price = df['close'].iloc[i]

            # P1修复：真实滑点模拟（基于ATR的动态滑点）
            atr = current_df['atr'].iloc[-1] if 'atr' in current_df.columns else current_price * 0.02
            atr_percent = atr / current_price

            # 滑点 = 0.0005 ~ 0.0015，与波动率正相关
            slippage = 0.0005 + atr_percent * 0.05  # 基础0.05% + ATR相关
            slippage = min(slippage, 0.0015)  # 最大0.15%

            # 入场
            if position == 0 and signal is not None:
                # 应用滑点
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

                # 记录滑点
                slippage_pct = slippage * 100
                if slippage_pct > 0.1:
                    logger.debug(f"⚠️  高滑点警告: {slippage_pct:.3f}%")

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
                    # 出场滑点
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
                        'profit_pct': profit / (position * entry_price) * 100,
                        'slippage': slippage * 100
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

        # 计算盈亏比
        profits = [t['profit_pct'] for t in trades if t['profit'] > 0]
        losses = [t['profit_pct'] for t in trades if t['profit'] < 0]

        avg_profit = np.mean(profits) if profits else 0
        avg_loss = np.mean(losses) if losses else 0
        profit_factor = abs(avg_profit / avg_loss) if avg_loss != 0 else 0

        # 平均滑点
        avg_slippage = np.mean([t['slippage'] for t in trades]) if trades else 0

        result = {
            'dataset': dataset_name,
            'total_trades': total_trades,
            'long_trades': long_trades,
            'short_trades': short_trades,
            'short_pct': short_trades / total_trades * 100 if total_trades > 0 else 0,
            'win_rate': win_rate,
            'total_return': total_return,
            'max_consecutive_losses': max_consecutive_losses,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'avg_slippage': avg_slippage,
            'final_capital': capital
        }

        return result

    def validate(self, df: pd.DataFrame, strategy_class = FixedUltimateStrategy) -> Dict:
        """
        执行完整验证流程
        """
        print("=" * 80)
        print(f"🧪 样本外验证 - {self.version}")
        print("=" * 80)

        # 1. 分割数据
        print("\n📊 步骤1：数据分割")
        print("-" * 80)
        train_df, val_df, test_df = self.split_data(df)

        # 2. 训练阶段
        print("\n📊 步骤2：训练集回测（60%数据）")
        print("-" * 80)
        strategy_train = strategy_class(self.config_path)
        train_result = self.run_backtest(strategy_train, train_df, "训练集")

        print(f"交易数: {train_result['total_trades']}")
        print(f"LONG: {train_result['long_trades']}, SHORT: {train_result['short_trades']} ({train_result['short_pct']:.1f}%)")
        print(f"胜率: {train_result['win_rate']:.2%}")
        print(f"收益: {train_result['total_return']:.2f}%")
        print(f"最大连续亏损: {train_result['max_consecutive_losses']}笔")
        print(f"平均滑点: {train_result['avg_slippage']:.3f}%")

        # 3. 验证阶段
        print("\n📊 步骤3：验证集回测（20%数据）")
        print("-" * 80)
        strategy_val = strategy_class(self.config_path)
        val_result = self.run_backtest(strategy_val, val_df, "验证集")

        print(f"交易数: {val_result['total_trades']}")
        print(f"LONG: {val_result['long_trades']}, SHORT: {val_result['short_trades']} ({val_result['short_pct']:.1f}%)")
        print(f"胜率: {val_result['win_rate']:.2%}")
        print(f"收益: {val_result['total_return']:.2f}%")
        print(f"最大连续亏损: {val_result['max_consecutive_losses']}笔")

        # 4. 最终测试阶段（只能测一次）
        print("\n📊 步骤4：最终测试（20%数据 - 只测一次）")
        print("-" * 80)
        print("⚠️  注意：测试集只能测一次，不能反复优化后再测")

        strategy_test = strategy_class(self.config_path)
        test_result = self.run_backtest(strategy_test, test_df, "测试集")

        print(f"交易数: {test_result['total_trades']}")
        print(f"LONG: {test_result['long_trades']}, SHORT: {test_result['short_trades']} ({test_result['short_pct']:.1f}%)")
        print(f"胜率: {test_result['win_rate']:.2%}")
        print(f"收益: {test_result['total_return']:.2f}%")
        print(f"最大连续亏损: {test_result['max_consecutive_losses']}笔")
        print(f"盈亏比: {test_result['profit_factor']:.2f}")

        # 5. 泛化能力评估
        print("\n" + "=" * 80)
        print("📊 泛化能力评估")
        print("=" * 80)

        # 胜率波动性
        win_rates = [train_result['win_rate'], val_result['win_rate'], test_result['win_rate']]
        win_rate_std = np.std(win_rates)
        avg_win_rate = np.mean(win_rates)

        print(f"\n胜率分析:")
        print(f"  训练集: {train_result['win_rate']:.2%}")
        print(f"  验证集: {val_result['win_rate']:.2%}")
        print(f"  测试集: {test_result['win_rate']:.2%}")
        print(f"  平均胜率: {avg_win_rate:.2%}")
        print(f"  胜率标准差: {win_rate_std:.2%}")

        # SHORT比例检查
        short_pcts = [train_result['short_pct'], val_result['short_pct'], test_result['short_pct']]
        avg_short_pct = np.mean(short_pcts)

        print(f"\nSHORT比例分析:")
        print(f"  训练集: {train_result['short_pct']:.1f}%")
        print(f"  验证集: {val_result['short_pct']:.1f}%")
        print(f"  测试集: {test_result['short_pct']:.1f}%")
        print(f"  平均SHORT比例: {avg_short_pct:.1f}%")

        # 评估结果
        print("\n" + "=" * 80)
        print("✅ 验证结果")
        print("=" * 80)

        # 判断是否过拟合
        overfitting_detected = False
        issues = []

        if win_rate_std > 0.15:  # 胜率波动超过15%
            overfitting_detected = True
            issues.append(f"胜率波动过大({win_rate_std:.2%})，可能过拟合")

        if avg_win_rate > 0.65:  # 平均胜率过高
            overfitting_detected = True
            issues.append(f"平均胜率过高({avg_win_rate:.2%})，可能过拟合")

        if avg_short_pct < 10:  # SHORT比例过低
            issues.append(f"SHORT比例过低({avg_short_pct:.1f}%)，双向策略失效")

        if test_result['max_consecutive_losses'] >= 5:  # 连续亏损过多
            issues.append(f"测试集连续亏损{test_result['max_consecutive_losses']}笔，风控不足")

        if not issues:
            print("\n🎉 通过验证！策略具备良好的泛化能力。")
            print(f"   平均胜率: {avg_win_rate:.2%}（在45-60%为理想）")
            print(f"   测试集胜率: {test_result['win_rate']:.2%}")
        else:
            print("\n⚠️  检测到问题:")
            for issue in issues:
                print(f"   - {issue}")

        # 保存结果
        validation_report = {
            'version': self.version,
            'validation_date': datetime.now().isoformat(),
            'data_split': {
                'train': self.train_ratio,
                'val': self.val_ratio,
                'test': self.test_ratio
            },
            'results': {
                'train': train_result,
                'val': val_result,
                'test': test_result
            },
            'summary': {
                'avg_win_rate': avg_win_rate,
                'win_rate_std': win_rate_std,
                'avg_short_pct': avg_short_pct,
                'overfitting_detected': overfitting_detected,
                'issues': issues
            }
        }

        output_path = self.project_root / "out_of_sample_validation_report.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(validation_report, f, indent=2, ensure_ascii=False)

        print(f"\n📄 验证报告已保存: {output_path}")

        return validation_report


def generate_validation_data():
    """生成用于验证的混合市场数据"""
    np.random.seed(999)

    dates = pd.date_range(start='2024-01-01', periods=1500, freq='h')
    base_price = 50000

    # 阶段1：上涨（30%）
    prices_up = np.linspace(base_price, base_price * 1.3, 450)
    prices_up += np.random.randn(450) * 300

    # 阶段2：下跌（30%）
    prices_down = np.linspace(prices_up[-1], prices_up[-1] * 0.75, 450)
    prices_down += np.random.randn(450) * 300

    # 阶段3：震荡（20%）
    prices_range = prices_down[-1] + np.random.randn(300) * 1500

    # 阶段4：再次上涨（20%）
    prices_up2 = np.linspace(prices_range[-1], prices_range[-1] * 1.2, 300)
    prices_up2 += np.random.randn(300) * 300

    prices = np.concatenate([prices_up, prices_down, prices_range, prices_up2])

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


if __name__ == "__main__":
    # 生成验证数据
    print("📊 生成验证数据...")
    df = generate_validation_data()

    # 执行验证
    validator = OutOfSampleValidator()
    report = validator.validate(df)

    print("\n" + "=" * 80)
    print("✅ 验证完成")
    print("=" * 80)
