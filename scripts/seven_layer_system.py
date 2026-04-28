#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("seven_layer_system")
except ImportError:
    import logging
    logger = logging.getLogger("seven_layer_system")
"""
7层闭环系统集成 - 深度优化
整合所有优化模块，实现完整的交易闭环
核心策略：数据聚合→市场识别→策略决策→过滤决策→执行交易→风控管理→优化进化
"""

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import sqlite3
import os
import time


class LayerType(Enum):
    """层级类型"""
    DATA_AGGREGATION = "DATA_AGGREGATION"  # 数据聚合层
    MARKET_RECOGNITION = "MARKET_RECOGNITION"  # 市场识别层
    STRATEGY_DECISION = "STRATEGY_DECISION"  # 策略决策层
    FILTER_DECISION = "FILTER_DECISION"  # 过滤决策层
    EXECUTION_TRADING = "EXECUTION_TRADING"  # 执行交易层
    RISK_MANAGEMENT = "RISK_MANAGEMENT"  # 风控管理层
    OPTIMIZATION_EVOLUTION = "OPTIMIZATION_EVOLUTION"  # 优化进化层


@dataclass
class LayerResult:
    """层级结果"""
    layer: LayerType
    passed: bool
    confidence: float
    data: Dict
    reason: str
    timestamp: int


@dataclass
class SignalChain:
    """信号链"""
    chain_id: str
    layers: List[LayerResult]
    final_signal: str  # 'LONG', 'SHORT', 'HOLD'
    final_confidence: float
    execution_data: Dict


class SevenLayerSystem:
    """7层闭环系统"""

    def __init__(
        self,
        config: Optional[Dict] = None
    ):
        """
        初始化7层闭环系统

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 层级配置
        self.layer_configs = {
            LayerType.DATA_AGGREGATION: {
                "enabled": True,
                "data_sources": ["klines", "orderbook", "funding_rate"],
                "quality_threshold": 0.9
            },
            LayerType.MARKET_RECOGNITION: {
                "enabled": True,
                "regime_prediction": True,
                "confidence_threshold": 0.6
            },
            LayerType.STRATEGY_DECISION: {
                "enabled": True,
                "strategies": ["ma_trend", "rsi_mean_revert", "orderflow_break", "pairs_trading"],
                "linucb_optimization": True
            },
            LayerType.FILTER_DECISION: {
                "enabled": True,
                "signal_quality_threshold": 0.65,  # P0优化：从50提升至65
                "directional_balance_filter": True,
                "market_state_filter": True
            },
            LayerType.EXECUTION_TRADING: {
                "enabled": True,
                "order_type": "limit_maker",
                "slipage_model": True,
                "dynamic_offset": True
            },
            LayerType.RISK_MANAGEMENT: {
                "enabled": True,
                "adaptive_stop_loss": True,
                "trailing_stop": True,
                "position_sizing": "kelly"
            },
            LayerType.OPTIMIZATION_EVOLUTION: {
                "enabled": True,
                "linucb_cold_start": True,
                "lstm_data_collection": True,
                "bayesian_optimization": True
            }
        }

        # 统计信息
        self.layer_pass_counts = {layer: 0 for layer in LayerType}
        self.layer_fail_counts = {layer: 0 for layer in LayerType}

    def process_signal(
        self,
        market_data: Dict,
        historical_trades: List[Dict]
    ) -> SignalChain:
        """
        处理信号（完整7层流程）

        Args:
            market_data: 市场数据
            historical_trades: 历史交易

        Returns:
            信号链
        """
        chain_id = f"chain_{int(time.time() * 1000)}"
        layers = []

        # 第1层：数据聚合层
        layer1_result = self._layer_data_aggregation(market_data)
        layers.append(layer1_result)

        if not layer1_result.passed:
            return self._create_signal_chain(chain_id, layers, "HOLD", 0.0, {"reason": "数据质量不合格"})

        # 第2层：市场识别层
        layer2_result = self._layer_market_recognition(market_data)
        layers.append(layer2_result)

        if not layer2_result.passed:
            return self._create_signal_chain(chain_id, layers, "HOLD", 0.0, {"reason": "市场状态不适合交易"})

        # 第3层：策略决策层
        layer3_result = self._layer_strategy_decision(market_data, historical_trades)
        layers.append(layer3_result)

        if not layer3_result.passed:
            return self._create_signal_chain(chain_id, layers, "HOLD", 0.0, {"reason": "策略决策无信号"})

        # 第4层：过滤决策层
        layer4_result = self._layer_filter_decision(market_data, historical_trades, layer3_result.data)
        layers.append(layer4_result)

        if not layer4_result.passed:
            return self._create_signal_chain(chain_id, layers, "HOLD", 0.0, {"reason": "信号被过滤"})

        # 第5层：执行交易层
        layer5_result = self._layer_execution_trading(market_data, layer4_result.data)
        layers.append(layer5_result)

        if not layer5_result.passed:
            return self._create_signal_chain(chain_id, layers, "HOLD", 0.0, {"reason": "执行失败"})

        # 第6层：风控管理层
        layer6_result = self._layer_risk_management(market_data, layer5_result.data, historical_trades)
        layers.append(layer6_result)

        if not layer6_result.passed:
            return self._create_signal_chain(chain_id, layers, "HOLD", 0.0, {"reason": "风控拒绝"})

        # 第7层：优化进化层
        layer7_result = self._layer_optimization_evolution(market_data, historical_trades, layer6_result.data)
        layers.append(layer7_result)

        # 生成最终信号
        final_signal = layer6_result.data.get('direction', 'HOLD')
        final_confidence = min(
            layer3_result.confidence,
            layer4_result.confidence,
            layer5_result.confidence,
            layer6_result.confidence
        )

        return self._create_signal_chain(chain_id, layers, final_signal, final_confidence, layer6_result.data)

    def _layer_data_aggregation(self, market_data: Dict) -> LayerResult:
        """第1层：数据聚合层"""
        config = self.layer_configs[LayerType.DATA_AGGREGATION]

        # 数据质量检查
        quality_score = market_data.get('quality_score', 0.0)

        if quality_score < config['quality_threshold']:
            self.layer_fail_counts[LayerType.DATA_AGGREGATION] += 1
            return LayerResult(
                layer=LayerType.DATA_AGGREGATION,
                passed=False,
                confidence=quality_score,
                data={},
                reason=f"数据质量{quality_score:.2f}低于阈值{config['quality_threshold']}",
                timestamp=int(time.time() * 1000)
            )

        self.layer_pass_counts[LayerType.DATA_AGGREGATION] += 1
        return LayerResult(
            layer=LayerType.DATA_AGGREGATION,
            passed=True,
            confidence=quality_score,
            data=market_data,
            reason=f"数据质量合格 ({quality_score:.2f})",
            timestamp=int(time.time() * 1000)
        )

    def _layer_market_recognition(self, market_data: Dict) -> LayerResult:
        """第2层：市场识别层"""
        config = self.layer_configs[LayerType.MARKET_RECOGNITION]

        # 市场状态识别（复用market_regime_optimizer）
        regime = market_data.get('regime', 'RANGING')
        regime_confidence = market_data.get('regime_confidence', 0.0)

        # 只在趋势市允许交易
        if regime not in ['STRONG_TREND_UP', 'STRONG_TREND_DOWN', 'WEAK_TREND_UP', 'WEAK_TREND_DOWN']:
            self.layer_fail_counts[LayerType.MARKET_RECOGNITION] += 1
            return LayerResult(
                layer=LayerType.MARKET_RECOGNITION,
                passed=False,
                confidence=regime_confidence,
                data={'regime': regime},
                reason=f"市场状态为{regime}，不适合交易",
                timestamp=int(time.time() * 1000)
            )

        if regime_confidence < config['confidence_threshold']:
            self.layer_fail_counts[LayerType.MARKET_RECOGNITION] += 1
            return LayerResult(
                layer=LayerType.MARKET_RECOGNITION,
                passed=False,
                confidence=regime_confidence,
                data={'regime': regime},
                reason=f"市场状态置信度{regime_confidence:.2f}低于阈值{config['confidence_threshold']}",
                timestamp=int(time.time() * 1000)
            )

        self.layer_pass_counts[LayerType.MARKET_RECOGNITION] += 1
        return LayerResult(
            layer=LayerType.MARKET_RECOGNITION,
            passed=True,
            confidence=regime_confidence,
            data={'regime': regime, 'direction': 'LONG' if 'UP' in regime else 'SHORT'},
            reason=f"市场状态{regime}适合交易",
            timestamp=int(time.time() * 1000)
        )

    def _layer_strategy_decision(self, market_data: Dict, historical_trades: List[Dict]) -> LayerResult:
        """第3层：策略决策层"""
        config = self.layer_configs[LayerType.STRATEGY_DECISION]

        # 多策略投票（复用hybrid_strategy_framework）
        strategies = config['strategies']
        strategy_votes = {}

        for strategy in strategies:
            # 模拟策略信号（实际应该调用对应策略模块）
            if strategy == 'ma_trend':
                signal = 'LONG' if market_data.get('ma_signal', 0) > 0 else 'SHORT'
                confidence = abs(market_data.get('ma_signal', 0))
            elif strategy == 'rsi_mean_revert':
                signal = 'SHORT' if market_data.get('rsi', 50) > 70 else 'LONG'
                confidence = abs(market_data.get('rsi', 50) - 50) / 50
            else:
                signal = 'HOLD'
                confidence = 0.5

            strategy_votes[strategy] = {'signal': signal, 'confidence': confidence}

        # 投票聚合
        long_votes = sum(1 for v in strategy_votes.values() if v['signal'] == 'LONG')
        short_votes = sum(1 for v in strategy_votes.values() if v['signal'] == 'SHORT')

        if long_votes > short_votes:
            final_signal = 'LONG'
            avg_confidence = np.mean([v['confidence'] for v in strategy_votes.values() if v['signal'] == 'LONG'])
        elif short_votes > long_votes:
            final_signal = 'SHORT'
            avg_confidence = np.mean([v['confidence'] for v in strategy_votes.values() if v['signal'] == 'SHORT'])
        else:
            final_signal = 'HOLD'
            avg_confidence = 0.5

        if final_signal == 'HOLD':
            self.layer_fail_counts[LayerType.STRATEGY_DECISION] += 1
            return LayerResult(
                layer=LayerType.STRATEGY_DECISION,
                passed=False,
                confidence=avg_confidence,
                data={'strategy_votes': strategy_votes},
                reason="策略投票无明确方向",
                timestamp=int(time.time() * 1000)
            )

        self.layer_pass_counts[LayerType.STRATEGY_DECISION] += 1
        return LayerResult(
            layer=LayerType.STRATEGY_DECISION,
            passed=True,
            confidence=avg_confidence,
            data={'direction': final_signal, 'strategy_votes': strategy_votes},
            reason=f"策略决策：{final_signal}",
            timestamp=int(time.time() * 1000)
        )

    def _layer_filter_decision(self, market_data: Dict, historical_trades: List[Dict], strategy_result: Dict) -> LayerResult:
        """第4层：过滤决策层"""
        config = self.layer_configs[LayerType.FILTER_DECISION]

        direction = strategy_result.get('direction', 'HOLD')

        # 信号质量过滤（P0优化：阈值从50提升至65）
        signal_quality = market_data.get('signal_quality', 0.0)

        if signal_quality < config['signal_quality_threshold']:
            self.layer_fail_counts[LayerType.FILTER_DECISION] += 1
            return LayerResult(
                layer=LayerType.FILTER_DECISION,
                passed=False,
                confidence=signal_quality,
                data={},
                reason=f"信号质量{signal_quality:.2f}低于阈值{config['signal_quality_threshold']}",
                timestamp=int(time.time() * 1000)
            )

        # 方向平衡过滤（P0优化）
        if config['directional_balance_filter']:
            # 检查最近20笔交易方向
            recent_directions = [t.get('direction', '') for t in historical_trades[-20:]]
            long_ratio = recent_directions.count('LONG') / len(recent_directions) if recent_directions else 0.5

            if direction == 'LONG' and long_ratio > 0.7:
                self.layer_fail_counts[LayerType.FILTER_DECISION] += 1
                return LayerResult(
                    layer=LayerType.FILTER_DECISION,
                    passed=False,
                    confidence=signal_quality,
                    data={},
                    reason=f"方向平衡过滤：最近20笔中{int(long_ratio*100)}%为多头，抑制做多",
                    timestamp=int(time.time() * 1000)
                )
            elif direction == 'SHORT' and long_ratio < 0.3:
                self.layer_fail_counts[LayerType.FILTER_DECISION] += 1
                return LayerResult(
                    layer=LayerType.FILTER_DECISION,
                    passed=False,
                    confidence=signal_quality,
                    data={},
                    reason=f"方向平衡过滤：最近20笔中{int((1-long_ratio)*100)}%为空头，抑制做空",
                    timestamp=int(time.time() * 1000)
                )

        self.layer_pass_counts[LayerType.FILTER_DECISION] += 1
        return LayerResult(
            layer=LayerType.FILTER_DECISION,
            passed=True,
            confidence=signal_quality,
            data={'direction': direction},
            reason="信号通过所有过滤",
            timestamp=int(time.time() * 1000)
        )

    def _layer_execution_trading(self, market_data: Dict, filter_result: Dict) -> LayerResult:
        """第5层：执行交易层"""
        config = self.layer_configs[LayerType.EXECUTION_TRADING]

        direction = filter_result.get('direction', 'HOLD')
        price = market_data.get('close', 0)

        # 模拟执行
        execution_data = {
            'direction': direction,
            'price': price,
            'order_type': config['order_type'],
            'size': 0.1,  # 简化
            'slipage': price * 0.0005  # 0.05%滑点
        }

        self.layer_pass_counts[LayerType.EXECUTION_TRADING] += 1
        return LayerResult(
            layer=LayerType.EXECUTION_TRADING,
            passed=True,
            confidence=0.9,
            data=execution_data,
            reason="执行成功",
            timestamp=int(time.time() * 1000)
        )

    def _layer_risk_management(self, market_data: Dict, execution_result: Dict, historical_trades: List[Dict]) -> LayerResult:
        """第6层：风控管理层"""
        config = self.layer_configs[LayerType.RISK_MANAGEMENT]

        # 自适应止损（P1优化）
        atr = market_data.get('atr', 100)
        entry_price = execution_result['price']
        direction = execution_result['direction']

        # 计算止损
        if direction == 'LONG':
            stop_loss = entry_price - 2.0 * atr
        else:
            stop_loss = entry_price + 2.0 * atr

        risk_data = {
            'direction': direction,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'position_size': 0.25,  # 25%仓位
            'risk_amount': abs(entry_price - stop_loss) * 0.25
        }

        # 检查风险限额
        daily_loss_limit = market_data.get('daily_loss_limit', 0.03)  # 3%
        daily_pnl = market_data.get('daily_pnl', 0)

        if daily_pnl < -daily_loss_limit:
            self.layer_fail_counts[LayerType.RISK_MANAGEMENT] += 1
            return LayerResult(
                layer=LayerType.RISK_MANAGEMENT,
                passed=False,
                confidence=0.0,
                data={},
                reason=f"日亏损{daily_pnl:.2f}超过限额{daily_loss_limit*100:.0f}%",
                timestamp=int(time.time() * 1000)
            )

        self.layer_pass_counts[LayerType.RISK_MANAGEMENT] += 1
        return LayerResult(
            layer=LayerType.RISK_MANAGEMENT,
            passed=True,
            confidence=0.9,
            data=risk_data,
            reason="风控通过",
            timestamp=int(time.time() * 1000)
        )

    def _layer_optimization_evolution(self, market_data: Dict, historical_trades: List[Dict], risk_result: Dict) -> LayerResult:
        """第7层：优化进化层"""
        config = self.layer_configs[LayerType.OPTIMIZATION_EVOLUTION]

        # LinUCB冷启动
        # LSTM数据收集
        # 贝叶斯优化

        optimization_data = {
            'linucb_enabled': config['linucb_cold_start'],
            'lstm_collection_enabled': config['lstm_data_collection'],
            'bayesian_optimization_enabled': config['bayesian_optimization']
        }

        self.layer_pass_counts[LayerType.OPTIMIZATION_EVOLUTION] += 1
        return LayerResult(
            layer=LayerType.OPTIMIZATION_EVOLUTION,
            passed=True,
            confidence=1.0,
            data=optimization_data,
            reason="优化层正常",
            timestamp=int(time.time() * 1000)
        )

    def _create_signal_chain(self, chain_id: str, layers: List[LayerResult], final_signal: str, final_confidence: float, execution_data: Dict) -> SignalChain:
        """创建信号链"""
        return SignalChain(
            chain_id=chain_id,
            layers=layers,
            final_signal=final_signal,
            final_confidence=final_confidence,
            execution_data=execution_data
        )

    def get_system_statistics(self) -> Dict:
        """获取系统统计"""
        total_pass = sum(self.layer_pass_counts.values())
        total_fail = sum(self.layer_fail_counts.values())

        return {
            "total_processed": total_pass + total_fail,
            "layer_pass_counts": {layer.value: count for layer, count in self.layer_pass_counts.items()},
            "layer_fail_counts": {layer.value: count for layer, count in self.layer_fail_counts.items()},
            "layer_pass_rates": {
                layer.value: (count / (count + self.layer_fail_counts[layer]) * 100 if count + self.layer_fail_counts[layer] > 0 else 0)
                for layer, count in self.layer_pass_counts.items()
            }
        }


def main():
    parser = argparse.ArgumentParser(description="7层闭环系统集成")
    parser.add_argument("--action", choices=["process", "stats"], required=True, help="操作类型")
    parser.add_argument("--market-data", help="市场数据JSON字符串")
    parser.add_argument("--trades", help="交易历史JSON文件路径")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        import numpy as np

        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建7层系统
        system = SevenLayerSystem(config)

        logger.info("=" * 70)
        logger.info("✅ 7层闭环系统集成 - 深度优化")
        logger.info("=" * 70)

        if args.action == "process":
            if not args.market_data or not args.trades:
                logger.info("错误: 请提供 --market-data 和 --trades 参数")
                sys.exit(1)

            # 解析市场数据
            market_data = json.loads(args.market_data)

            # 加载交易历史
            with open(args.trades, 'r', encoding='utf-8') as f:
                historical_trades = json.load(f)

            # 处理信号
            signal_chain = system.process_signal(market_data, historical_trades)

            logger.info(f"\n信号链ID: {signal_chain.chain_id}")
            logger.info(f"\n层级处理结果:")

            for i, layer in enumerate(signal_chain.layers, 1):
                logger.info(f"\n  第{i}层: {layer.layer.value}")
                logger.info(f"    通过: {'✅ 是' if layer.passed else '❌ 否'}")
                logger.info(f"    置信度: {layer.confidence:.2%}")
                logger.info(f"    原因: {layer.reason}")

            logger.info(f"\n最终信号: {signal_chain.final_signal}")
            logger.info(f"最终置信度: {signal_chain.final_confidence:.2%}")

            if signal_chain.execution_data:
                logger.info(f"\n执行数据:")
                logger.info(f"  方向: {signal_chain.execution_data.get('direction', 'N/A')}")
                logger.info(f"  价格: ${signal_chain.execution_data.get('price', 0):.2f}")

            output = {
                "status": "success",
                "signal_chain": {
                    "chain_id": signal_chain.chain_id,
                    "final_signal": signal_chain.final_signal,
                    "final_confidence": signal_chain.final_confidence,
                    "execution_data": signal_chain.execution_data,
                    "layers": [
                        {
                            "layer": layer.layer.value,
                            "passed": layer.passed,
                            "confidence": layer.confidence,
                            "reason": layer.reason
                        }
                        for layer in signal_chain.layers
                    ]
                }
            }

        elif args.action == "stats":
            # 获取系统统计
            stats = system.get_system_statistics()

            logger.info(f"\n系统统计:")
            logger.info(f"  总处理数: {stats['total_processed']}")
            logger.info(f"\n层级通过率:")

            for layer, rate in stats['layer_pass_rates'].items():
                logger.info(f"  {layer}: {rate:.1f}%")

            output = {
                "status": "success",
                "statistics": stats
            }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error(json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
