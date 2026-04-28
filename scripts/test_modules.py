#!/usr/bin/env python3
"""
测试核心模块
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

print("测试1: 导入模块...")
try:
    from state_manager import StateManager
    print("  ✓ state_manager")
except Exception as e:
    print(f"  ✗ state_manager: {e}")

try:
    from validator import DataValidator
    print("  ✓ validator")
except Exception as e:
    print(f"  ✗ validator: {e}")

try:
    from strategy_engine import EnhancedStrategyEngine
    print("  ✓ strategy_engine")
except Exception as e:
    print(f"  ✗ strategy_engine: {e}")

try:
    from advanced_risk import AdvancedRiskManager
    print("  ✓ advanced_risk")
except Exception as e:
    print(f"  ✗ advanced_risk: {e}")

try:
    from order_flow import OrderFlowAnalyzer
    print("  ✓ order_flow")
except Exception as e:
    print(f"  ✗ order_flow: {e}")

try:
    from market_regime import MarketRegimeDetector
    print("  ✓ market_regime")
except Exception as e:
    print(f"  ✗ market_regime: {e}")

print("\n测试2: 基本功能...")

# 测试数据验证
try:
    validator = DataValidator()
    tick = {
        'symbol': 'BTCUSDT',
        'price': 50000,
        'timestamp': 1234567890,
        'bid': 49990,
        'ask': 50010,
        'volume': 1.0
    }
    valid, cleaned, error = validator.validate_market_tick(tick)
    print(f"  ✓ 数据验证: {valid}")
except Exception as e:
    print(f"  ✗ 数据验证: {e}")

# 测试订单流
try:
    analyzer = OrderFlowAnalyzer(50, 20)
    analyzer.add_trade(50000, 1.0, False)
    analyzer.add_trade(50001, 1.5, True)
    features = analyzer.get_features()
    print(f"  ✓ 订单流分析: imbalance={features.get('imbalance', 0):.3f}")
except Exception as e:
    print(f"  ✗ 订单流分析: {e}")

# 测试市场识别
try:
    detector = MarketRegimeDetector()
    result = detector.detect(
        {'sma5': 50100, 'sma20': 50000, 'volatility': 0.008, 'rsi': 55},
        {'pressure': 0.15},
        {'price': 50050, 'bid': 50048, 'ask': 50052}
    )
    print(f"  ✓ 市场识别: {result.get('regime', 'unknown')}")
except Exception as e:
    print(f"  ✗ 市场识别: {e}")

# 测试策略引擎
try:
    config = {
        "signal_threshold": 0.6,
        "conflict_threshold": 0.2,
        "ma_trend": {"initial_weight": 0.3},
        "rsi_mean_revert": {"initial_weight": 0.2},
        "orderflow_break": {"initial_weight": 0.3},
        "volatility_break": {"initial_weight": 0.2}
    }
    engine = EnhancedStrategyEngine(config)
    direction, strength, trigger, reason = engine.generate_final_signal(
        {'close': 50000, 'sma5': 50100, 'sma20': 50000, 'volatility': 0.008, 'rsi': 55},
        {'imbalance': 0.3, 'pressure': 0.2}
    )
    print(f"  ✓ 策略引擎: direction={direction}, strength={strength:.3f}")
except Exception as e:
    print(f"  ✗ 策略引擎: {e}")

# 测试风控
try:
    risk_config = {"max_drawdown": 0.08, "max_daily_loss": 0.025, "max_position_pct": 0.10}
    risk = AdvancedRiskManager(risk_config, 100000)
    decision = risk.approve_order({'qty': 0.1}, 50000, 100000)
    print(f"  ✓ 风控系统: approved={decision['approved']}")
except Exception as e:
    print(f"  ✗ 风控系统: {e}")

# 测试状态管理
try:
    state_mgr = StateManager()
    success = state_mgr.save_portfolio({'equity': 100000, 'cash': 100000})
    portfolio = state_mgr.load_portfolio()
    print(f"  ✓ 状态管理: saved={success}, loaded={portfolio is not None}")
except Exception as e:
    print(f"  ✗ 状态管理: {e}")

print("\n所有测试完成！")
