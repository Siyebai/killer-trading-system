#!/usr/bin/env python3
"""
动态滑点模型对比测试 - Phase 4 P0.2
对比固定滑点 vs sqrt动态滑点在趋势市/震荡市的盈亏差异
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import numpy as np
from datetime import datetime

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("slippage_test")
except ImportError:
    import logging
    logger = logging.getLogger("slippage_test")

try:
    from scripts.backtesting_engine import BacktestEngine, BacktestConfig
except ImportError as e:
    logger.error(f"核心模块导入失败: {e}")
    sys.exit(1)


def generate_market_data(market_type='trend', days=10):
    """生成模拟市场数据"""
    np.random.seed(42)

    if market_type == 'trend':
        # 趋势市：缓慢上涨
        base = 50000
        trend = 100  # 每天1%趋势
        noise = 500  # 日内波动
    else:
        # 震荡市：横盘
        base = 50000
        trend = 0
        noise = 800

    data = []
    price = base
    for day in range(days):
        for hour in range(24):
            # 小时K线
            change = trend / 24 + np.random.normal(0, noise / 24)
            price = max(price + change, 1000)

            high = price * (1 + np.random.uniform(0, 0.005))
            low = price * (1 - np.random.uniform(0, 0.005))

            data.append({
                'timestamp': 1777200000000 + day * 86400000 + hour * 3600000,
                'open': price,
                'high': high,
                'low': low,
                'close': price,
                'volume': 1000 + np.random.randint(0, 500)
            })

    return data


def run_test(market_type, use_dynamic_slippage):
    """执行测试"""
    # 配置
    if use_dynamic_slippage:
        config = BacktestConfig(
            initial_capital=100000.0,
            commission_rate=0.001,
            dynamic_slippage_base=0.0001,
            avg_daily_volume=1000000.0,
            max_position_size=0.5,
            leverage=1.0
        )
        slippage_mode = "Dynamic (sqrt)"
    else:
        config = BacktestConfig(
            initial_capital=100000.0,
            commission_rate=0.001,
            slippage_rate=0.0005,  # 固定0.05%
            max_position_size=0.5,
            leverage=1.0
        )
        slippage_mode = "Fixed (0.05%)"

    engine = BacktestEngine(config)
    data = generate_market_data(market_type)

    # 简化交易逻辑
    trades = []
    for i in range(10, len(data) - 10):
        if i % 6 == 0:  # 每6小时交易一次
            price = data[i]['close']
            try:
                # 开仓
                trade = engine.open_position(data[i]['timestamp'], 'BTC', price, 0.01)
                if trade:
                    # 6小时后平仓
                    exit_price = data[i+6]['close']
                    engine.close_position(data[i+6]['timestamp'], 'BTC', exit_price, 'TIME_STOP')
                    trades.append({
                        'entry': price,
                        'exit': exit_price,
                        'pnl_pct': (exit_price - price) / price
                    })
            except:
                pass

    final_equity = engine.equity
    total_pnl = final_equity - config.initial_capital
    win_rate = sum(1 for t in trades if t['pnl_pct'] > 0) / len(trades) if trades else 0

    return {
        'market_type': market_type,
        'slippage_mode': slippage_mode,
        'trades_count': len(trades),
        'final_equity': final_equity,
        'total_pnl': total_pnl,
        'pnl_pct': total_pnl / config.initial_capital,
        'win_rate': win_rate
    }


def main():
    """主函数"""
    logger.info("="*60)
    logger.info("动态滑点模型对比测试 - Phase 4 P0.2")
    logger.info("="*60)

    results = []

    # 测试1: 趋势市固定滑点
    results.append(run_test('trend', False))

    # 测试2: 趋势市动态滑点
    results.append(run_test('trend', True))

    # 测试3: 震荡市固定滑点
    results.append(run_test('ranging', False))

    # 测试4: 震荡市动态滑点
    results.append(run_test('ranging', True))

    # 生成报告
    report = {
        'test_name': 'Dynamic Slippage Model Comparison',
        'timestamp': datetime.now().isoformat(),
        'version': 'v1.0.2',
        'results': results,
        'analysis': {}
    }

    # 分析盈亏差异
    for market_type in ['trend', 'ranging']:
        market_results = [r for r in results if r['market_type'] == market_type]
        fixed = next(r for r in market_results if 'Fixed' in r['slippage_mode'])
        dynamic = next(r for r in market_results if 'Dynamic' in r['slippage_mode'])

        pnl_diff = dynamic['total_pnl'] - fixed['total_pnl']
        pnl_diff_pct = (dynamic['pnl_pct'] - fixed['pnl_pct']) * 100

        report['analysis'][market_type] = {
            'fixed_pnl': fixed['total_pnl'],
            'dynamic_pnl': dynamic['total_pnl'],
            'pnl_diff': pnl_diff,
            'pnl_diff_pct': pnl_diff_pct,
            'better_mode': 'Dynamic' if pnl_diff > 0 else 'Fixed'
        }

    # 保存报告
    with open('test_results_slippage_comparison.json', 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # 打印结果
    logger.info("\n测试结果:")
    for r in results:
        logger.info(f"  {r['market_type']:8s} {r['slippage_mode']:20s}: PnL {r['total_pnl']:8.2f} ({r['pnl_pct']*100:6.2f}%)")

    logger.info("\n分析:")
    for mt, analysis in report['analysis'].items():
        logger.info(f"  {mt:8s}: 动态滑点 vs 固定滑点 = {analysis['pnl_diff_pct']:+6.2f}%")

    logger.info("="*60)

    return report


if __name__ == "__main__":
    report = main()
    print(f"\n报告已保存: test_results_slippage_comparison.json")
    print(f"\n结论:")
    for mt, analysis in report['analysis'].items():
        print(f"  {mt.upper()}: {'动态滑点' if analysis['better_mode'] == 'Dynamic' else '固定滑点'} 更优 ({analysis['pnl_diff_pct']:+.2f}%)")
