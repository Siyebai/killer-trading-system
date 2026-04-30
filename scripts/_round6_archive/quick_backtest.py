# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
快速回测测试 - v1.0.3 Stable
使用预定义规则进行回测
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import numpy as np

print("=" * 60)
print("快速回测测试 - v1.0.3 Stable")
print("=" * 60)

# 生成测试数据
try:
    from scripts.historical_data_loader import HistoricalDataLoader
    loader = HistoricalDataLoader()
except ImportError:
    try:
        from historical_data_loader import HistoricalDataLoader
        loader = HistoricalDataLoader()
    except ImportError:
        print("❌ 无法导入HistoricalDataLoader")
        sys.exit(1)
market_data = loader.generate_mock_data("BTCUSDT", n_samples=2000)
print(f"✓ 数据生成成功: {market_data.shape}")

# 简化回测（预定义规则）
capital = 100000.0
position = 0.0
cash = capital
trade_count = 0
win_count = 0

# 计算技术指标
close_prices = market_data[:, 3]

# EMA计算
def ema(prices, period):
    multiplier = 2.0 / (period + 1.0)
    ema_values = []
    ema_val = prices[0]
    for price in prices:
        ema_val = (price * multiplier) + (ema_val * (1 - multiplier))
        ema_values.append(ema_val)
    return np.array(ema_values)

ema_12 = ema(close_prices, 12)
ema_26 = ema(close_prices, 26)

# 简单回测
entry_price = 0.0
for i in range(50, len(market_data)):
    close = close_prices[i]

    # 预定义规则1: EMA交叉
    if i > 50:
        if ema_12[i] > ema_26[i] and ema_12[i-1] <= ema_26[i-1]:
            # 金叉买入
            if position <= 0:
                if position < 0:  # 平空
                    pnl = (entry_price - close) * abs(position)
                    cash += pnl
                    if pnl > 0:
                        win_count += 1
                    trade_count += 1
                # 开多
                trade_value = cash * 0.1
                position = trade_value / close
                cash -= trade_value

        elif ema_12[i] < ema_26[i] and ema_12[i-1] >= ema_26[i-1]:
            # 死叉卖出
            if position >= 0:
                if position > 0:  # 平多
                    pnl = (close - entry_price) * position
                    cash += pnl
                    if pnl > 0:
                        win_count += 1
                    trade_count += 1
                # 开空
                trade_value = cash * 0.1
                position = -trade_value / close
                cash -= trade_value

# 平仓
if position > 0:
    pnl = (close_prices[-1] - entry_price) * position
    cash += pnl
    if pnl > 0:
        win_count += 1
    trade_count += 1
elif position < 0:
    pnl = (entry_price - close_prices[-1]) * abs(position)
    cash += pnl
    if pnl > 0:
        win_count += 1
    trade_count += 1

# 计算结果
total_return = (cash - capital) / capital
win_rate = win_count / max(1, trade_count)

print(f"\n✓ 回测完成")
print(f"  交易次数: {trade_count}")
print(f"  胜率: {win_rate:.4f}")
print(f"  总收益: {total_return:.4f}")

# 评估
print("\n" + "=" * 60)
if trade_count > 10:  # 只要有足够多的交易就算通过
    print("✓ 快速回测测试通过！")
    print("=" * 60)
    sys.exit(0)
else:
    print("✗ 快速回测测试失败：交易次数不足")
    print("=" * 60)
    sys.exit(1)
