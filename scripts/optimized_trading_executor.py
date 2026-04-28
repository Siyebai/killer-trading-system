#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("optimized_trading_executor")
except ImportError:
    import logging
    logger = logging.getLogger("optimized_trading_executor")
"""
优化版交易执行器 - 基于真实交易数据的4点针对性优化
1. 多时间帧强制过滤
2. 信号评分阈值提升 + 市场状态识别
3. Maker限价单 + 动态偏移
4. LinUCB动态权重优化
"""

import json
import sys
import os
import time
import argparse
from typing import Dict, List, Optional

# 导入模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from winrate_enhancer import WinrateEnhancer
from market_regime import MarketRegimeDetector
from high_fidelity_execution import HighFidelityExecution, ExecutionAlgorithm
from hybrid_strategy_framework import HybridStrategyFramework
from linucb_optimizer import LinUCB


class OptimizedTradingEngine:
    """优化版交易引擎"""

    def __init__(self, config_path: str):
        """
        初始化优化交易引擎

        Args:
            config_path: 优化配置文件路径
        """
        # 加载配置
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        logger.info("=" * 70)
        logger.info("🎯 杀手锏交易系统 - 优化版V4.5")
        logger.info("=" * 70)
        logger.info(f"\n配置版本: {self.config['version']}")
        logger.info(f"描述: {self.config['description']}")

        # 显示原始指标
        orig = self.config['optimization_summary']['original_metrics']
        logger.info(f"\n原始指标:")
        logger.info(f"  总交易数: {orig['total_trades']}")
        logger.info(f"  胜率: {orig['win_rate']*100:.2f}%")
        logger.info(f"  盈亏比: {orig['profit_loss_ratio']}")
        logger.info(f"  每笔成本: {orig['cost_per_trade']}")
        logger.info(f"  过滤保留率: {orig['filter_retention_rate']}")

        # 显示预期指标
        exp = self.config['optimization_summary']['expected_metrics']
        logger.info(f"\n预期指标:")
        logger.info(f"  胜率: {exp['win_rate']}")
        logger.info(f"  盈亏比: {exp['profit_loss_ratio']}")
        logger.info(f"  每笔成本: {exp['cost_per_trade']}")
        logger.info(f"  交易数: {exp['total_trades']}")

        # 初始化子模块
        self._init_modules()

    def _init_modules(self):
        """初始化所有子模块"""
        logger.info(f"\n{'=' * 70}")
        logger.info("初始化模块...")
        logger.info(f"{'=' * 70}")

        # 1. 多时间帧过滤
        self.enable_mtf = self.config['multi_timeframe']['enabled']
        if self.enable_mtf:
            logger.info(f"✅ 多时间帧过滤已启用")
            logger.info(f"   时间周期: {self.config['multi_timeframe']['timeframes']}")
            logger.info(f"   一致性阈值: {self.config['multi_timeframe']['consensus_threshold']}")

        # 2. 信号评分 + 市场状态识别
        self.signal_threshold = self.config['signal_scorer']['threshold']
        self.adx_threshold = self.config['market_regime']['adx_threshold']
        logger.info(f"\n✅ 信号评分已优化")
        logger.info(f"   评分阈值: {self.signal_threshold} (从0.5提升)")
        logger.info(f"   ADX最小阈值: {self.adx_threshold} (ADX<{self.adx_threshold}不交易)")

        # 3. Maker限价单
        self.order_type = self.config['execution']['order_type']
        self.limit_offset_bps = self.config['execution']['limit_offset_bps']
        logger.info(f"\n✅ Maker限价单已启用")
        logger.info(f"   订单类型: {self.order_type}")
        logger.info(f"   限价偏移: {self.limit_offset_bps} bps")
        logger.info(f"   预期成本降低: 70% (0.3% → 0.05%-0.1%)")

        # 4. LinUCB动态权重
        self.enable_linucb = self.config['linucb_optimizer']['enabled']
        if self.enable_linucb:
            logger.info(f"\n✅ LinUCB动态权重优化已启用")
            logger.info(f"   探索参数α: {self.config['linucb_optimizer']['alpha']}")
            logger.info(f"   特征维度: {self.config['linucb_optimizer']['feature_dim']}")

        # 初始化胜率增强器
        self.winrate_enhancer = WinrateEnhancer({
            'enable_mtf': self.enable_mtf,
            'enable_regime_filter': True,
            'enable_signal_score': True,
            'min_mtf_score': self.config.get('winrate_enhancer', {}).get('min_mtf_score', 0.4),
            'min_signal_score': self.signal_threshold
        })

        # 初始化市场状态检测器
        self.regime_detector = MarketRegimeDetector(self.config.get('market_regime', {}))

        # 初始化高保真执行引擎
        self.execution_engine = HighFidelityExecution({
            'default_algorithm': 'LIMIT' if self.order_type == 'limit_maker' else 'MARKET',
            'limit_offset_ratio': self.limit_offset_bps / 10000.0
        })

        # 初始化混合策略框架（含LinUCB）
        if self.enable_linucb:
            self.hybrid_framework = HybridStrategyFramework({
                'enable_linucb': True,
                'linucb_alpha': self.config['linucb_optimizer']['alpha'],
                'min_performance_window': 50,
                'update_frequency': 100
            })
        else:
            self.hybrid_framework = None

        logger.info(f"\n{'=' * 70}")
        logger.info("模块初始化完成")
        logger.info(f"{'=' * 70}")

    def analyze_signal(self, original_signal: str, context: Dict) -> Dict:
        """
        分析信号（四层过滤）

        Args:
            original_signal: 原始信号
            context: 上下文信息

        Returns:
            分析结果
        """
        logger.info(f"\n{'=' * 70}")
        logger.info("信号分析")
        logger.info(f"{'=' * 70}")
        logger.info(f"\n原始信号: {original_signal}")

        # 使用胜率增强器进行四层过滤
        enhanced_signal = self.winrate_enhancer.should_trade(original_signal, context)

        logger.info(f"\n增强信号: {enhanced_signal.enhanced_action}")
        logger.info(f"是否交易: {enhanced_signal.should_trade}")
        logger.info(f"置信度: {enhanced_signal.confidence:.2f}")

        if enhanced_signal.reasons:
            logger.info(f"\n过滤原因:")
            for reason in enhanced_signal.reasons:
                logger.info(f"  - {reason}")

        logger.info(f"\n详细评分:")
        logger.info(f"  多时间帧对齐: {enhanced_signal.mtf_alignment:.2f}")
        logger.info(f"  信号质量: {enhanced_signal.signal_quality:.2f}")
        logger.info(f"  市场状态: {enhanced_signal.market_regime}")

        return {
            'original_signal': original_signal,
            'enhanced_signal': enhanced_signal.enhanced_action,
            'should_trade': enhanced_signal.should_trade,
            'confidence': enhanced_signal.confidence,
            'reasons': enhanced_signal.reasons,
            'mtf_alignment': enhanced_signal.mtf_alignment,
            'signal_quality': enhanced_signal.signal_quality,
            'market_regime': enhanced_signal.market_regime
        }

    def execute_order(self, action: str, price: float, size: float) -> Dict:
        """
        执行订单（Maker限价单）

        Args:
            action: 动作（BUY/SELL）
            price: 价格
            size: 数量

        Returns:
            执行结果
        """
        logger.info(f"\n{'=' * 70}")
        logger.info("订单执行")
        logger.info(f"{'=' * 70}")

        if not self.execution_engine:
            return {'status': 'error', 'message': '执行引擎未初始化'}

        # 使用Maker限价单
        if self.order_type == 'limit_maker':
            result = self.execution_engine.place_limit_order(
                symbol='BTCUSDT',
                action=action,
                price=price,
                size=size,
                offset_ratio=self.limit_offset_bps / 10000.0
            )
        else:
            result = self.execution_engine.execute_order(
                symbol='BTCUSDT',
                action=action,
                price=price,
                size=size
            )

        logger.info(f"\n执行结果: {result['status']}")
        logger.info(f"成交价格: {result.get('executed_price', 'N/A')}")
        logger.info(f"成交数量: {result.get('executed_size', 'N/A')}")
        logger.info(f"滑点: {result.get('slippage_bps', 'N/A')} bps")
        logger.info(f"手续费: {result.get('fee', 'N/A')}")

        return result

    def update_linucb_weights(self, trade_result: Dict, market_state: Dict):
        """
        更新LinUCB权重

        Args:
            trade_result: 交易结果
            market_state: 市场状态
        """
        if not self.hybrid_framework or not self.enable_linucb:
            return

        # 更新策略性能
        strategy_name = trade_result.get('strategy', 'unknown')
        self.hybrid_framework.update_performance(strategy_name, trade_result)

        logger.info(f"\n[LinUCB] 策略 {strategy_name} 性能已更新")
        logger.info(f"  盈亏: ${trade_result.get('pnl', 0):.2f}")


def main():
    parser = argparse.ArgumentParser(description="优化版交易执行器")
    parser.add_argument("--config", required=True, help="优化配置文件路径")
    parser.add_argument("--signal", help="测试信号（BUY/SELL/HOLD）")
    parser.add_argument("--price", type=float, help="测试价格")
    parser.add_argument("--size", type=float, help="测试数量")

    args = parser.parse_args()

    try:
        # 初始化引擎
        engine = OptimizedTradingEngine(args.config)

        # 测试模式
        if args.signal:
            context = {
                'df': {},  # 简化
                'indicators': {'adx': 30, 'rsi': 55},  # 模拟指标
                'orderflow': {},
                'market_tick': {}
            }

            # 分析信号
            analysis = engine.analyze_signal(args.signal, context)

            # 如果需要交易，执行订单
            if analysis['should_trade'] and args.price and args.size:
                result = engine.execute_order(analysis['enhanced_signal'], args.price, args.size)

        # 交互模式
        else:
            logger.info(f"\n{'=' * 70}")
            logger.info("交互模式")
            logger.info(f"{'=' * 70}")
            logger.info("\n可用命令:")
            logger.info("  analyze <BUY|SELL|HOLD> - 分析信号")
            logger.info("  execute <BUY|SELL> <price> <size> - 执行订单")
            logger.info("  exit - 退出")

            while True:
                try:
                    cmd = input("\n> ").strip()
                    if not cmd:
                        continue

                    if cmd == 'exit':
                        break

                    parts = cmd.split()
                    if parts[0] == 'analyze' and len(parts) == 2:
                        context = {
                            'df': {},
                            'indicators': {'adx': 30, 'rsi': 55},
                            'orderflow': {},
                            'market_tick': {}
                        }
                        analysis = engine.analyze_signal(parts[1], context)

                    elif parts[0] == 'execute' and len(parts) == 4:
                        result = engine.execute_order(parts[1], float(parts[2]), float(parts[3]))

                    else:
                        logger.info("无效命令")

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    logger.error(f"错误: {e}")

        logger.info(f"\n{'=' * 70}")
        logger.info("优化版交易引擎运行完成")
        logger.info(f"{'=' * 70}")

    except Exception as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
