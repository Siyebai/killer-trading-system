#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("profit_loss_ratio_optimizer")
except ImportError:
    import logging
    logger = logging.getLogger("profit_loss_ratio_optimizer")
"""
盈亏比优化模块 - V4.7
基于500笔复盘报告，解决盈亏比0.37的核心问题
核心策略：动态止损调整 + 仓位优化 + 风险管理强化
"""

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np


class RiskLevel(Enum):
    """风险等级"""
    CONSERVATIVE = "CONSERVATIVE"
    MODERATE = "MODERATE"
    AGGRESSIVE = "AGGRESSIVE"


@dataclass
class StopLossConfig:
    """止损配置"""
    atr_multiplier: float
    reason: str


@dataclass
class PositionConfig:
    """仓位配置"""
    base_size: float
    max_size: float
    risk_level: RiskLevel


class ProfitLossRatioOptimizer:
    """盈亏比优化器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化盈亏比优化器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # ATR配置（V4.7优化）
        self.atr_period = self.config.get('atr_period', 20)  # 从14提升至20

        # 止损配置
        self.base_stop_multiplier = self.config.get('atr_multiplier_base', 2.0)  # 从1.5提升至2.0
        self.enable_dynamic_stop = self.config.get('enable_dynamic_adjustment', {}).get('enabled', True)

        # 动态止损规则
        self.dynamic_stop_rules = self.config.get('dynamic_adjustment', {}).get('rules', [
            {'score_min': 0.8, 'atr_multiplier': 1.8},
            {'score_min': 0.7, 'atr_multiplier': 2.0},
            {'score_min': 0.6, 'atr_multiplier': 2.5}
        ])

        # 仓位管理配置
        self.base_position_pct = self.config.get('base_position_percent', 0.08)  # 从12%降至8%
        self.max_position_pct = self.config.get('max_position_percent', 0.25)  # 从35%降至25%
        self.kelly_fraction = self.config.get('kelly_fraction', 0.15)  # 从0.25降至0.15

        # 风险管理配置
        self.max_drawdown = self.config.get('max_drawdown', 0.08)  # 从0.10降至0.08
        self.max_daily_loss = self.config.get('max_daily_loss', 0.02)  # 从0.03降至0.02
        self.consecutive_loss_limit = self.config.get('consecutive_loss_limit', 3)  # 从5降至3

        # 动态仓位缩减
        self.enable_dynamic_reduction = self.config.get('dynamic_position_reduction', {}).get('enabled', True)
        self.drawdown_threshold = self.config.get('dynamic_position_reduction', {}).get('drawdown_threshold', 0.05)
        self.reduction_factor = self.config.get('dynamic_position_reduction', {}).get('reduction_factor', 0.5)

    def calculate_optimal_stop_loss(self, entry_price: float, side: str,
                                     current_atr: float, signal_score: float) -> StopLossConfig:
        """
        计算最优止损

        Args:
            entry_price: 入场价格
            side: 方向
            current_atr: 当前ATR
            signal_score: 信号评分

        Returns:
            止损配置
        """
        # 动态止损距离
        if self.enable_dynamic_stop:
            for rule in self.dynamic_stop_rules:
                if signal_score >= rule['score_min']:
                    atr_multiplier = rule['atr_multiplier']
                    break
            else:
                atr_multiplier = self.base_stop_multiplier
        else:
            atr_multiplier = self.base_stop_multiplier

        # 计算止损价格
        if side == 'long':
            stop_loss = entry_price - atr_multiplier * current_atr
        else:
            stop_loss = entry_price + atr_multiplier * current_atr

        reason = f"信号评分{signal_score:.2f}，止损距离{atr_multiplier}*ATR"

        return StopLossConfig(
            atr_multiplier=atr_multiplier,
            reason=reason
        )

    def calculate_optimal_position_size(self, equity: float, entry_price: float,
                                         stop_loss: float, signal_score: float,
                                         current_drawdown: float = 0) -> PositionConfig:
        """
        计算最优仓位大小

        Args:
            equity: 权益
            entry_price: 入场价格
            stop_loss: 止损价格
            signal_score: 信号评分
            current_drawdown: 当前回撤

        Returns:
            仓位配置
        """
        # 计算基础仓位
        risk_per_trade = equity * self.base_position_pct

        # 计算单笔风险
        if stop_loss > entry_price:
            stop_distance = stop_loss - entry_price
        else:
            stop_distance = entry_price - stop_loss

        stop_distance_pct = stop_distance / entry_price

        # 凯利公式优化版
        if stop_distance_pct > 0:
            position_size = risk_per_trade / (stop_distance_pct * entry_price)
            position_size *= self.kelly_fraction
        else:
            position_size = 0

        # 限制最大仓位
        position_size = min(position_size, self.max_position_pct * equity / entry_price)

        # 动态仓位缩减（回撤超过阈值）
        if self.enable_dynamic_reduction and current_drawdown >= self.drawdown_threshold:
            position_size *= self.reduction_factor

        # 确定风险等级
        if signal_score >= 0.8:
            risk_level = RiskLevel.AGGRESSIVE
        elif signal_score >= 0.7:
            risk_level = RiskLevel.MODERATE
        else:
            risk_level = RiskLevel.CONSERVATIVE

        return PositionConfig(
            base_size=self.base_position_pct,
            max_size=position_size / equity * entry_price,  # 转换为百分比
            risk_level=risk_level
        )

    def check_risk_limits(self, current_drawdown: float, daily_loss_pct: float,
                           consecutive_losses: int) -> Tuple[bool, Optional[str]]:
        """
        检查风险限制

        Args:
            current_drawdown: 当前回撤
            daily_loss_pct: 日亏损百分比
            consecutive_losses: 连续亏损次数

        Returns:
            (是否允许交易, 拒绝原因)
        """
        # 检查最大回撤
        if current_drawdown >= self.max_drawdown:
            return False, f"最大回撤{self.max_drawdown*100:.1f}%已触发（当前{current_drawdown*100:.1f}%）"

        # 检查日亏损
        if daily_loss_pct >= self.max_daily_loss:
            return False, f"日最大亏损{self.max_daily_loss*100:.1f}%已触发（当前{daily_loss_pct*100:.1f}%）"

        # 检查连续亏损
        if consecutive_losses >= self.consecutive_loss_limit:
            return False, f"连续亏损{self.consecutive_loss_limit}次已触发（当前{consecutive_losses}次）"

        return True, None

    def analyze_profit_loss_ratio(self, trades: List[Dict]) -> Dict:
        """
        分析盈亏比

        Args:
            trades: 交易列表

        Returns:
            盈亏比分析结果
        """
        if not trades:
            return {
                "status": "no_data",
                "message": "无交易数据"
            }

        # 统计数据
        winning_trades = [t for t in trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in trades if t.get('pnl', 0) <= 0]

        total_profit = sum(t.get('pnl', 0) for t in winning_trades)
        total_loss = sum(abs(t.get('pnl', 0)) for t in losing_trades)

        avg_profit = total_profit / len(winning_trades) if winning_trades else 0
        avg_loss = total_loss / len(losing_trades) if losing_trades else 0

        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0

        # 目标评估
        target_ratio = 1.2
        target_high = 1.5

        status = "excellent" if profit_loss_ratio >= target_high else \
                 "good" if profit_loss_ratio >= target_ratio else \
                 "needs_improvement"

        return {
            "status": "success",
            "total_trades": len(trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "total_profit": total_profit,
            "total_loss": total_loss,
            "avg_profit": avg_profit,
            "avg_loss": avg_loss,
            "profit_loss_ratio": profit_loss_ratio,
            "status": status,
            "target_ratio": target_ratio,
            "target_high": target_high,
            "recommendations": self._generate_recommendations(profit_loss_ratio)
        }

    def _generate_recommendations(self, profit_loss_ratio: float) -> List[str]:
        """
        生成优化建议

        Args:
            profit_loss_ratio: 盈亏比

        Returns:
            优化建议列表
        """
        recommendations = []

        if profit_loss_ratio < 1.0:
            recommendations.append("❌ 盈亏比过低（<1.0）：需要立即优化")
            recommendations.append("  - 加宽止损距离（1.5 → 2.0*ATR）")
            recommendations.append("  - 放宽止盈目标（2.5 → 3.5*ATR）")
            recommendations.append("  - 优化入场时机，避免震荡市")
        elif profit_loss_ratio < 1.2:
            recommendations.append("⚠️ 盈亏比偏低（1.0-1.2）：需要进一步优化")
            recommendations.append("  - 继续加宽止损和止盈目标")
            recommendations.append("  - 降低仓位，减少单笔风险")
        elif profit_loss_ratio < 1.5:
            recommendations.append("✅ 盈亏比良好（1.2-1.5）：保持当前策略")
        else:
            recommendations.append("🎉 盈亏比优秀（>1.5）：策略表现优异")

        return recommendations

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        return {
            'atr_period': self.atr_period,
            'base_stop_multiplier': self.base_stop_multiplier,
            'enable_dynamic_stop': self.enable_dynamic_stop,
            'base_position_pct': self.base_position_pct,
            'max_position_pct': self.max_position_pct,
            'kelly_fraction': self.kelly_fraction,
            'max_drawdown': self.max_drawdown,
            'max_daily_loss': self.max_daily_loss,
            'consecutive_loss_limit': self.consecutive_loss_limit
        }


def main():
    parser = argparse.ArgumentParser(description="盈亏比优化")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--entry-price", type=float, required=True, help="入场价格")
    parser.add_argument("--side", required=True, choices=['long', 'short'], help="方向")
    parser.add_argument("--atr", type=float, required=True, help="当前ATR值")
    parser.add_argument("--signal-score", type=float, required=True, help="信号评分")
    parser.add_argument("--equity", type=float, default=100000, help="账户权益")
    parser.add_argument("--current-drawdown", type=float, default=0, help="当前回撤")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建盈亏比优化器
        optimizer = ProfitLossRatioOptimizer(config)

        logger.info("=" * 70)
        logger.info("⚖️ 盈亏比优化 - V4.7")
        logger.info("=" * 70)

        stats = optimizer.get_statistics()
        logger.info(f"\n配置:")
        logger.info(f"  ATR周期: {optimizer.atr_period}（V4.7从14提升至20）")
        logger.info(f"  基础止损距离: {optimizer.base_stop_multiplier}*ATR（从1.5提升至2.0）")
        logger.info(f"  动态止损: {'启用' if optimizer.enable_dynamic_stop else '禁用'}")
        logger.info(f"  基础仓位: {optimizer.base_position_pct*100:.1f}%（从12%降至8%）")
        logger.info(f"  最大仓位: {optimizer.max_position_pct*100:.1f}%（从35%降至25%）")
        logger.info(f"  凯利系数: {optimizer.kelly_fraction}（从0.25降至0.15）")

        # 计算止损
        stop_loss_config = optimizer.calculate_optimal_stop_loss(
            args.entry_price, args.side, args.atr, args.signal_score
        )

        logger.info(f"\n{'=' * 70}")
        logger.info("止损优化")
        logger.info(f"{'=' * 70}")
        logger.info(f"\n入场价格: ${args.entry_price:.2f}")
        logger.info(f"方向: {args.side}")
        logger.info(f"当前ATR: ${args.atr:.2f}")
        logger.info(f"信号评分: {args.signal_score:.2f}")

        if args.side == 'long':
            stop_loss = args.entry_price - stop_loss_config.atr_multiplier * args.atr
        else:
            stop_loss = args.entry_price + stop_loss_config.atr_multiplier * args.atr

        logger.info(f"\n止损配置:")
        logger.info(f"  止损价格: ${stop_loss:.2f}")
        logger.info(f"  止损距离: {stop_loss_config.atr_multiplier}*ATR")
        logger.info(f"  原因: {stop_loss_config.reason}")

        # 计算仓位
        position_config = optimizer.calculate_optimal_position_size(
            args.equity, args.entry_price, stop_loss, args.signal_score, args.current_drawdown
        )

        logger.info(f"\n{'=' * 70}")
        logger.info("仓位优化")
        logger.info(f"{'=' * 70}")
        logger.info(f"\n账户权益: ${args.equity:.2f}")
        logger.info(f"当前回撤: {args.current_drawdown*100:.1f}%")
        logger.info(f"\n仓位配置:")
        logger.info(f"  基础仓位: {position_config.base_size*100:.1f}%")
        logger.info(f"  最大仓位: {position_config.max_size*100:.1f}%")
        logger.info(f"  风险等级: {position_config.risk_level.value}")

        if optimizer.enable_dynamic_reduction and args.current_drawdown >= optimizer.drawdown_threshold:
            logger.info(f"  ⚠️ 动态缩减：回撤{args.current_drawdown*100:.1f}%≥{optimizer.drawdown_threshold*100:.1f}%，仓位缩减{optimizer.reduction_factor*100:.0f}%")

        # 检查风险限制
        should_trade, reason = optimizer.check_risk_limits(
            args.current_drawdown, 0, 0
        )

        logger.info(f"\n{'=' * 70}")
        logger.info("风险限制检查")
        logger.info(f"{'=' * 70}")
        logger.info(f"\n最大回撤限制: {optimizer.max_drawdown*100:.1f}%")
        logger.info(f"日最大亏损: {optimizer.max_daily_loss*100:.1f}%")
        logger.info(f"连续亏损限制: {optimizer.consecutive_loss_limit}次")

        if should_trade:
            logger.info(f"\n✅ 允许交易")
        else:
            logger.info(f"\n❌ 禁止交易：{reason}")

        output = {
            "status": "success",
            "stop_loss": {
                "price": stop_loss,
                "atr_multiplier": stop_loss_config.atr_multiplier,
                "reason": stop_loss_config.reason
            },
            "position": {
                "base_size_pct": position_config.base_size,
                "max_size_pct": position_config.max_size,
                "risk_level": position_config.risk_level.value
            },
            "risk_check": {
                "should_trade": should_trade,
                "reason": reason
            }
        }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
