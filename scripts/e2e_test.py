#!/usr/bin/env python3
"""
端到端测试 - v1.0.3 Stable
测试完整流程：数据加载→策略进化→回测
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

print("=" * 60)
print("端到端测试 - v1.0.3 Stable")
print("=" * 60)

# 步骤1: 数据加载
print("\n[1/3] 数据加载测试...")
try:
    from scripts.historical_data_loader import HistoricalDataLoader
except ImportError:
    try:
        from historical_data_loader import HistoricalDataLoader
    except ImportError:
        print("❌ 无法导入HistoricalDataLoader")
        sys.exit(1)

loader = HistoricalDataLoader()
market_data = loader.generate_mock_data("BTCUSDT", n_samples=2000)
print(f"✓ 数据生成成功: {market_data.shape}")

# 步骤2: 策略进化
print("\n[2/3] 策略进化测试...")
try:
    from scripts.strategy_lab import StrategyLab
except ImportError:
    try:
        from strategy_lab import StrategyLab
    except ImportError:
        print("❌ 无法导入StrategyLab")
        sys.exit(1)

lab = StrategyLab(
    population_size=20,
    generations=5,
    use_backtest_adapter=True
)

best_strategy = lab.run(market_data)
print(f"✓ 进化完成")
print(f"  最佳适应度: {best_strategy.fitness:.4f}")
print(f"  Sharpe比率: {best_strategy.sharpe_ratio:.4f}")
print(f"  胜率: {best_strategy.win_rate:.4f}")
print(f"  交易次数: {best_strategy.fitness * 100:.0f}")  # 估算

# 步骤3: 回测验证
print("\n[3/3] 回测验证测试...")
try:
    from scripts.backtest_adapter import BacktestAdapter
except ImportError:
    try:
        from backtest_adapter import BacktestAdapter
    except ImportError:
        print("❌ 无法导入BacktestAdapter")
        sys.exit(1)

adapter = BacktestAdapter()
result = adapter.run_backtest(best_strategy, market_data)
print(f"✓ 回测完成")
print(f"  Sharpe比率: {result.sharpe_ratio:.4f}")
print(f"  胜率: {result.win_rate:.4f}")
print(f"  最大回撤: {result.max_drawdown:.4f}")
print(f"  总收益: {result.total_return:.4f}")
print(f"  交易次数: {result.total_trades}")

# 评估结果
print("\n" + "=" * 60)
if result.total_trades > 0 and result.sharpe_ratio > 0:
    print("✓ 端到端测试通过！")
    print("=" * 60)
    sys.exit(0)
else:
    print("✗ 端到端测试失败：无有效交易")
    print("=" * 60)
    sys.exit(1)
