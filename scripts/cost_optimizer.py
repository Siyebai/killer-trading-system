#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("cost_optimizer")
except ImportError:
    import logging
    logger = logging.getLogger("cost_optimizer")
"""
交易成本优化模块 - V4.6
基于500笔交易数据分析，解决手续费占盈利83%的问题
核心策略：减少无效交易 + 优化仓位管理 + 提高信号质量
"""

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np


class TradeQuality(Enum):
    """交易质量"""
    EXCELLENT = "EXCELLENT"  # 优质交易
    GOOD = "GOOD"  # 良好交易
    ACCEPTABLE = "ACCEPTABLE"  # 可接受交易
    POOR = "POOR"  # 低质量交易
    REJECT = "REJECT"  # 拒绝交易


@dataclass
class CostMetrics:
    """成本指标"""
    total_trades: int
    filtered_trades: int
    execution_cost: float  # 执行成本（滑点+手续费）
    opportunity_cost: float  # 机会成本
    cost_per_trade: float
    cost_to_profit_ratio: float  # 成本/盈利比


class CostOptimizer:
    """交易成本优化器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化成本优化器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 成本配置
        self.maker_fee = self.config.get('maker_fee', -0.0002)  # Maker费率（负数表示返佣）
        self.taker_fee = self.config.get('taker_fee', 0.0005)   # Taker费率
        self.avg_slippage_bps = self.config.get('avg_slippage_bps', 2)  # 平均滑点2bps

        # 过滤配置（基于500笔交易优化）
        self.min_signal_score = self.config.get('min_signal_score', 0.65)  # 从0.6提升至0.65
        self.min_win_score = self.config.get('min_win_score', 0.6)
        self.min_confidence = self.config.get('min_confidence', 0.7)

        # 市场状态过滤
        self.avoid_range_market = self.config.get('avoid_range_market', True)
        self.adx_min_threshold = self.config.get('adx_min_threshold', 25)

        # 仓位优化
        self.enable_dynamic_sizing = self.config.get('enable_dynamic_sizing', True)
        self.min_position_size = self.config.get('min_position_size', 0.001)

    def calculate_trade_cost(self, entry_price: float, exit_price: float,
                             size: float, is_maker: bool = False) -> CostMetrics:
        """
        计算交易成本

        Args:
            entry_price: 入场价格
            exit_price: 退出价格
            size: 数量
            is_maker: 是否Maker订单

        Returns:
            成本指标
        """
        # 计算手续费
        fee_rate = self.maker_fee if is_maker else self.taker_fee
        entry_fee = entry_price * size * abs(fee_rate)
        exit_fee = exit_price * size * abs(fee_rate)

        # 计算滑点
        slippage_cost = (entry_price + exit_price) * size * self.avg_slippage_bps / 10000

        # 总成本
        total_cost = entry_fee + exit_fee + slippage_cost

        return CostMetrics(
            total_trades=1,
            filtered_trades=0,
            execution_cost=total_cost,
            opportunity_cost=0,
            cost_per_trade=total_cost,
            cost_to_profit_ratio=0
        )

    def evaluate_trade_quality(self, signal_score: float, win_score: float,
                               confidence: float, market_state: str,
                               adx: float, trend_strength: float) -> TradeQuality:
        """
        评估交易质量

        Args:
            signal_score: 信号评分
            win_score: 胜率评分
            confidence: 置信度
            market_state: 市场状态
            adx: ADX值
            trend_strength: 趋势强度

        Returns:
            交易质量
        """
        reasons = []

        # 1. 信号质量检查
        if signal_score < self.min_signal_score:
            return TradeQuality.REJECT

        # 2. 胜率评分检查
        if win_score < self.min_win_score:
            return TradeQuality.REJECT

        # 3. 置信度检查
        if confidence < self.min_confidence:
            return TradeQuality.REJECT

        # 4. 市场状态检查
        if self.avoid_range_market and market_state == 'RANGE':
            return TradeQuality.REJECT

        # 5. ADX检查
        if adx < self.adx_min_threshold:
            return TradeQuality.REJECT

        # 6. 综合评分
        composite_score = (
            signal_score * 0.4 +
            win_score * 0.3 +
            confidence * 0.2 +
            (trend_strength if trend_strength > 0.6 else 0) * 0.1
        )

        if composite_score >= 0.8:
            return TradeQuality.EXCELLENT
        elif composite_score >= 0.7:
            return TradeQuality.GOOD
        elif composite_score >= 0.65:
            return TradeQuality.ACCEPTABLE
        else:
            return TradeQuality.POOR

    def optimize_position_size(self, confidence: float, volatility: float,
                               max_risk_per_trade: float = 0.01) -> float:
        """
        优化仓位大小

        Args:
            confidence: 置信度
            volatility: 波动率
            max_risk_per_trade: 单笔最大风险

        Returns:
            仓位大小（比例）
        """
        if not self.enable_dynamic_sizing:
            return 1.0

        # 基于置信度调整仓位
        base_size = confidence * max_risk_per_trade * 2

        # 基于波动率调整（高波动降低仓位）
        volatility_factor = 1.0 / (1.0 + volatility * 10)

        optimal_size = base_size * volatility_factor

        # 限制最小/最大仓位
        optimal_size = max(self.min_position_size, min(0.3, optimal_size))

        return optimal_size

    def analyze_cost_efficiency(self, trades: List[Dict]) -> Dict:
        """
        分析成本效率

        Args:
            trades: 交易列表

        Returns:
            成本效率分析结果
        """
        if not trades:
            return {
                "status": "no_data",
                "message": "无交易数据"
            }

        # 统计数据
        total_cost = 0
        total_profit = 0
        cost_by_quality = {
            "EXCELLENT": 0,
            "GOOD": 0,
            "ACCEPTABLE": 0,
            "POOR": 0,
            "REJECT": 0
        }

        for trade in trades:
            # 计算成本
            entry_price = trade.get('entry_price', 0)
            exit_price = trade.get('exit_price', 0)
            size = trade.get('size', 0)
            pnl = trade.get('pnl', 0)

            cost_metrics = self.calculate_trade_cost(entry_price, exit_price, size)
            total_cost += cost_metrics.execution_cost

            if pnl > 0:
                total_profit += pnl

            # 按质量分类
            quality = trade.get('quality', 'ACCEPTABLE')
            if quality in cost_by_quality:
                cost_by_quality[quality] += cost_metrics.execution_cost

        # 计算效率指标
        cost_to_profit_ratio = total_cost / total_profit if total_profit > 0 else float('inf')

        return {
            "status": "success",
            "total_trades": len(trades),
            "total_cost": total_cost,
            "total_profit": total_profit,
            "cost_to_profit_ratio": cost_to_profit_ratio,
            "cost_breakdown_by_quality": cost_by_quality,
            "recommendations": self._generate_recommendations(cost_to_profit_ratio, cost_by_quality)
        }

    def _generate_recommendations(self, cost_ratio: float,
                                   cost_by_quality: Dict) -> List[str]:
        """
        生成优化建议

        Args:
            cost_ratio: 成本/盈利比
            cost_by_quality: 按质量分类的成本

        Returns:
            优化建议列表
        """
        recommendations = []

        if cost_ratio > 0.5:
            recommendations.append("❌ 成本过高：建议提高信号质量阈值，减少低质量交易")

        if cost_by_quality.get('POOR', 0) > cost_by_quality.get('EXCELLENT', 0):
            recommendations.append("⚠️ 低质量交易过多：建议强化过滤条件，只接受GOOD级别以上交易")

        if cost_by_quality.get('REJECT', 0) > 0:
            recommendations.append("✅ 过滤生效：成功拒绝" + str(cost_by_quality.get('REJECT', 0)) + "笔低质量交易")

        if len(recommendations) == 0:
            recommendations.append("✅ 成本控制良好：继续当前策略")

        return recommendations

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        return {
            'maker_fee': self.maker_fee,
            'taker_fee': self.taker_fee,
            'avg_slippage_bps': self.avg_slippage_bps,
            'min_signal_score': self.min_signal_score,
            'min_win_score': self.min_win_score,
            'min_confidence': self.min_confidence,
            'adx_min_threshold': self.adx_min_threshold
        }


def main():
    parser = argparse.ArgumentParser(description="交易成本优化")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--evaluate", help="评估交易质量（JSON格式）")
    parser.add_argument("--entry-price", type=float, help="入场价格")
    parser.add_argument("--exit-price", type=float, help="退出价格")
    parser.add_argument("--size", type=float, help="数量")
    parser.add_argument("--maker", action="store_true", help="Maker订单")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建成本优化器
        optimizer = CostOptimizer(config)

        logger.info("=" * 70)
        logger.info("💰 交易成本优化 - V4.6")
        logger.info("=" * 70)

        stats = optimizer.get_statistics()
        logger.info(f"\n配置:")
        logger.info(f"  Maker费率: {optimizer.maker_fee*100:.3f}%")
        logger.info(f"  Taker费率: {optimizer.taker_fee*100:.3f}%")
        logger.info(f"  平均滑点: {optimizer.avg_slippage_bps} bps")
        logger.info(f"  信号评分阈值: {optimizer.min_signal_score}")
        logger.info(f"  胜率评分阈值: {optimizer.min_win_score}")
        logger.info(f"  置信度阈值: {optimizer.min_confidence}")
        logger.info(f"  ADX最小阈值: {optimizer.adx_min_threshold}")

        # 评估交易质量
        if args.evaluate:
            eval_data = json.loads(args.evaluate)
            quality = optimizer.evaluate_trade_quality(
                signal_score=eval_data.get('signal_score', 0),
                win_score=eval_data.get('win_score', 0),
                confidence=eval_data.get('confidence', 0),
                market_state=eval_data.get('market_state', 'UNKNOWN'),
                adx=eval_data.get('adx', 0),
                trend_strength=eval_data.get('trend_strength', 0)
            )

            logger.info(f"\n{'=' * 70}")
            logger.info("交易质量评估")
            logger.info(f"{'=' * 70}")
            logger.info(f"\n信号评分: {eval_data.get('signal_score', 0):.2f}")
            logger.info(f"胜率评分: {eval_data.get('win_score', 0):.2f}")
            logger.info(f"置信度: {eval_data.get('confidence', 0):.2f}")
            logger.info(f"市场状态: {eval_data.get('market_state', 'UNKNOWN')}")
            logger.info(f"ADX: {eval_data.get('adx', 0):.2f}")
            logger.info(f"\n交易质量: {quality.value}")

            if quality == TradeQuality.REJECT:
                logger.info(f"  ⚠️ 建议：拒绝此交易")
            elif quality in [TradeQuality.EXCELLENT, TradeQuality.GOOD]:
                logger.info(f"  ✅ 建议：执行此交易")
            else:
                logger.info(f"  ⚠️ 建议：谨慎执行")

        # 计算交易成本
        if args.entry_price and args.exit_price and args.size:
            logger.info(f"\n{'=' * 70}")
            logger.info("交易成本计算")
            logger.info(f"{'=' * 70}")

            cost_metrics = optimizer.calculate_trade_cost(
                args.entry_price, args.exit_price, args.size, args.maker
            )

            logger.info(f"\n入场价格: ${args.entry_price:.2f}")
            logger.info(f"退出价格: ${args.exit_price:.2f}")
            logger.info(f"数量: {args.size}")
            logger.info(f"订单类型: {'Maker' if args.maker else 'Taker'}")
            logger.info(f"\n执行成本: ${cost_metrics.execution_cost:.2f}")
            logger.info((f"  入场手续费: ${cost_metrics.execution_cost * 0.45:.2f}")  # 估算)
            logger.info((f"  退出手续费: ${cost_metrics.execution_cost * 0.45:.2f}")  # 估算)
            logger.info((f"  滑点成本: ${cost_metrics.execution_cost * 0.10:.2f}")  # 估算)

        logger.info(f"\n{'=' * 70}")
        logger.info("优化建议")
        logger.info(f"{'=' * 70}")
        logger.info(f"\n1. 提高信号质量阈值至 {optimizer.min_signal_score}")
        logger.info(f"2. 只接受 ADX>{optimizer.adx_min_threshold} 的趋势市场")
        logger.info(f"3. 避免震荡市交易")
        logger.info(f"4. 优先使用 Maker 限价单降低手续费")
        logger.info(f"5. 基于置信度动态调整仓位大小")

    except Exception as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
