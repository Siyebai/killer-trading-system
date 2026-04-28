#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("directional_balance_filter")
except ImportError:
    import logging
    logger = logging.getLogger("directional_balance_filter")
"""
方向平衡过滤器 - P0优先级优化
解决方向性偏好问题（189多/95空，多头胜率73% vs 空头35.8%）
核心策略：最近N笔交易方向平衡约束，抑制过度偏重某一方向
"""

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import sqlite3
import os
from collections import Counter


class Direction(Enum):
    """交易方向"""
    LONG = "LONG"
    SHORT = "SHORT"


class DirectionalBalanceFilter:
    """方向平衡过滤器"""

    def __init__(
        self,
        config: Optional[Dict] = None
    ):
        """
        初始化方向平衡过滤器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 平衡约束参数
        self.lookback_periods = self.config.get('lookback_periods', 20)  # 回溯20笔交易
        self.max_direction_ratio = self.config.get('max_direction_ratio', 0.7)  # 最大方向比例70%
        self.min_direction_ratio = self.config.get('min_direction_ratio', 0.3)  # 最小方向比例30%
        self.suppression_mode = self.config.get('suppression_mode', 'hard')  # 'hard' or 'soft'

        # 统计信息
        self.long_count = 0
        self.short_count = 0
        self.suppressed_count = 0

    def filter_signal(
        self,
        current_direction: Direction,
        recent_trades: List[Dict],
        current_time: Optional[int] = None
    ) -> Tuple[bool, Direction, Dict]:
        """
        过滤信号

        Args:
            current_direction: 当前信号方向
            recent_trades: 最近N笔交易历史
            current_time: 当前时间戳

        Returns:
            (是否通过, 最终方向, 过滤信息)
        """
        if not recent_trades:
            return True, current_direction, {"reason": "无历史数据", "long_ratio": 0.0}

        # 提取最近N笔交易方向
        recent_directions = []
        for trade in recent_trades[-self.lookback_periods:]:
            direction = trade.get('direction', '').upper()
            if direction in ['LONG', 'SHORT']:
                recent_directions.append(Direction(direction))

        if not recent_directions:
            return True, current_direction, {"reason": "无有效方向数据", "long_ratio": 0.0}

        # 计算方向比例
        direction_counter = Counter(recent_directions)
        total_count = len(recent_directions)

        long_ratio = direction_counter[Direction.LONG] / total_count if total_count > 0 else 0
        short_ratio = direction_counter[Direction.SHORT] / total_count if total_count > 0 else 0

        # 方向平衡约束
        final_direction = current_direction
        should_suppress = False
        reason = ""

        if current_direction == Direction.LONG:
            # 检查是否过度做多
            if long_ratio > self.max_direction_ratio:
                should_suppress = True
                reason = f"过度做多（最近{self.lookback_periods}笔中{int(long_ratio*100)}%为多头）"
                final_direction = None
            elif long_ratio >= 0.6 and self.suppression_mode == 'soft':
                # 软性抑制：降低置信度
                should_suppress = False
                reason = f"做多偏多（{int(long_ratio*100)}%），软性抑制"
                final_direction = current_direction  # 仍然通过，但降低置信度
            else:
                reason = "方向平衡正常"
        elif current_direction == Direction.SHORT:
            # 检查是否过度做空
            if short_ratio > self.max_direction_ratio:
                should_suppress = True
                reason = f"过度做空（最近{self.lookback_periods}笔中{int(short_ratio*100)}%为空头）"
                final_direction = None
            elif short_ratio >= 0.6 and self.suppression_mode == 'soft':
                # 软性抑制：降低置信度
                should_suppress = False
                reason = f"做空偏多（{int(short_ratio*100)}%），软性抑制"
                final_direction = current_direction
            else:
                reason = "方向平衡正常"

        # 更新统计
        if final_direction == Direction.LONG:
            self.long_count += 1
        elif final_direction == Direction.SHORT:
            self.short_count += 1

        if should_suppress:
            self.suppressed_count += 1

        return not should_suppress, final_direction, {
            "reason": reason,
            "long_ratio": long_ratio,
            "short_ratio": short_ratio,
            "suppressed": should_suppress,
            "lookback_periods": self.lookback_periods,
            "max_direction_ratio": self.max_direction_ratio
        }

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        total = self.long_count + self.short_count

        return {
            "total_signals": total,
            "long_signals": self.long_count,
            "short_signals": self.short_count,
            "suppressed_signals": self.suppressed_count,
            "long_ratio": self.long_count / total if total > 0 else 0,
            "short_ratio": self.short_count / total if total > 0 else 0,
            "suppression_ratio": self.suppressed_count / total if total > 0 else 0
        }

    def reset(self):
        """重置统计"""
        self.long_count = 0
        self.short_count = 0
        self.suppressed_count = 0


class DirectionalAnalyzer:
    """方向分析器"""

    @staticmethod
    def analyze_directional_bias(trades: List[Dict]) -> Dict:
        """
        分析方向性偏好

        Args:
            trades: 交易历史

        Returns:
            方向性分析结果
        """
        if not trades:
            return {
                "total_trades": 0,
                "long_trades": 0,
                "short_trades": 0,
                "long_ratio": 0,
                "short_ratio": 0,
                "directional_bias": "NEUTRAL",
                "imbalance_score": 0
            }

        # 统计方向
        long_trades = [t for t in trades if t.get('direction', '').upper() == 'LONG']
        short_trades = [t for t in trades if t.get('direction', '').upper() == 'SHORT']

        total_trades = len(trades)
        long_count = len(long_trades)
        short_count = len(short_trades)

        # 计算比例
        long_ratio = long_count / total_trades if total_trades > 0 else 0
        short_ratio = short_count / total_trades if total_trades > 0 else 0

        # 计算胜率
        long_wins = sum(1 for t in long_trades if t.get('pnl', 0) > 0)
        short_wins = sum(1 for t in short_trades if t.get('pnl', 0) > 0)

        long_win_rate = long_wins / long_count if long_count > 0 else 0
        short_win_rate = short_wins / short_count if short_count > 0 else 0

        # 计算平均盈亏
        long_avg_pnl = sum(t.get('pnl', 0) for t in long_trades) / long_count if long_count > 0 else 0
        short_avg_pnl = sum(t.get('pnl', 0) for t in short_trades) / short_count if short_count > 0 else 0

        # 判断方向性偏好
        imbalance_score = abs(long_ratio - 0.5) * 2  # 0 = 完美平衡, 1 = 完全偏向

        if imbalance_score > 0.3:
            directional_bias = "STRONG_BIAS"
        elif imbalance_score > 0.15:
            directional_bias = "MODERATE_BIAS"
        else:
            directional_bias = "NEUTRAL"

        return {
            "total_trades": total_trades,
            "long_trades": long_count,
            "short_trades": short_count,
            "long_ratio": long_ratio,
            "short_ratio": short_ratio,
            "long_win_rate": long_win_rate,
            "short_win_rate": short_win_rate,
            "long_avg_pnl": long_avg_pnl,
            "short_avg_pnl": short_avg_pnl,
            "directional_bias": directional_bias,
            "imbalance_score": imbalance_score,
            "recommendation": DirectionalAnalyzer._get_recommendation(
                directional_bias, long_ratio, short_ratio, long_win_rate, short_win_rate
            )
        }

    @staticmethod
    def _get_recommendation(
        directional_bias: str,
        long_ratio: float,
        short_ratio: float,
        long_win_rate: float,
        short_win_rate: float
    ) -> str:
        """获取优化建议"""
        if directional_bias == "STRONG_BIAS":
            if long_ratio > 0.7:
                if long_win_rate > 0.6:
                    return "多头偏好强且胜率高，建议保持但启用方向平衡过滤器"
                else:
                    return "多头偏好强但胜率低，建议强制抑制多头信号"
            elif short_ratio > 0.7:
                if short_win_rate > 0.6:
                    return "空头偏好强且胜率高，建议保持但启用方向平衡过滤器"
                else:
                    return "空头偏好强但胜率低，建议强制抑制空头信号"
        elif directional_bias == "MODERATE_BIAS":
            if long_win_rate < short_win_rate:
                return "空头胜率更高，建议适当增加空头权重"
            else:
                return "多头胜率更高，建议适当增加多头权重"
        else:
            return "方向平衡良好，无需优化"

        return "建议启用方向平衡过滤器"


def main():
    parser = argparse.ArgumentParser(description="方向平衡过滤器")
    parser.add_argument("--action", choices=["filter", "analyze", "stats"], required=True, help="操作类型")
    parser.add_argument("--direction", choices=["LONG", "SHORT"], help="当前信号方向")
    parser.add_argument("--trades", help="交易历史JSON文件路径")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建方向平衡过滤器
        filter = DirectionalBalanceFilter(config)

        logger.info("=" * 70)
        logger.info("✅ 方向平衡过滤器 - P0优先级优化")
        logger.info("=" * 70)

        if args.action == "filter":
            if not args.direction or not args.trades:
                logger.info("错误: 请提供 --direction 和 --trades 参数")
                sys.exit(1)

            # 加载交易历史
            with open(args.trades, 'r', encoding='utf-8') as f:
                trades = json.load(f)

            logger.info(f"\n过滤配置:")
            logger.info(f"  回溯周期: {filter.lookback_periods} 笔")
            logger.info(f"  最大方向比例: {filter.max_direction_ratio*100:.0f}%")
            logger.info(f"  最小方向比例: {filter.min_direction_ratio*100:.0f}%")
            logger.info(f"  抑制模式: {filter.suppression_mode}")

            # 过滤信号
            logger.info(f"\n当前信号: {args.direction}")
            logger.info(f"历史交易数: {len(trades)}")

            passed, final_direction, info = filter.filter_signal(
                Direction(args.direction), trades
            )

            logger.info(f"\n过滤结果:")
            logger.info(f"  是否通过: {'✅ 是' if passed else '❌ 否'}")
            logger.info(f"  最终方向: {final_direction.value if final_direction else '无'}")
            logger.info(f"  过滤原因: {info['reason']}")
            logger.info(f"  多头比例: {info['long_ratio']*100:.1f}%")
            logger.info(f"  空头比例: {info['short_ratio']*100:.1f}%")

            output = {
                "status": "success",
                "passed": passed,
                "final_direction": final_direction.value if final_direction else None,
                "filter_info": info
            }

        elif args.action == "analyze":
            if not args.trades:
                logger.info("错误: 请提供 --trades 参数")
                sys.exit(1)

            # 加载交易历史
            with open(args.trades, 'r', encoding='utf-8') as f:
                trades = json.load(f)

            # 分析方向性偏好
            analysis = DirectionalAnalyzer.analyze_directional_bias(trades)

            logger.info(f"\n方向性分析:")
            logger.info(f"  总交易数: {analysis['total_trades']}")
            logger.info(f"  多头交易: {analysis['long_trades']} ({analysis['long_ratio']*100:.1f}%)")
            logger.info(f"  空头交易: {analysis['short_trades']} ({analysis['short_ratio']*100:.1f}%)")
            logger.info(f"  多头胜率: {analysis['long_win_rate']*100:.1f}%")
            logger.info(f"  空头胜率: {analysis['short_win_rate']*100:.1f}%")
            logger.info(f"  多头平均盈亏: ${analysis['long_avg_pnl']:.2f}")
            logger.info(f"  空头平均盈亏: ${analysis['short_avg_pnl']:.2f}")
            logger.info(f"\n方向性偏好: {analysis['directional_bias']}")
            logger.info(f"  不平衡得分: {analysis['imbalance_score']:.2f}")
            logger.info(f"\n优化建议: {analysis['recommendation']}")

            output = {
                "status": "success",
                "analysis": analysis
            }

        elif args.action == "stats":
            # 获取统计信息
            stats = filter.get_statistics()

            logger.info(f"\n过滤器统计:")
            logger.info(f"  总信号数: {stats['total_signals']}")
            logger.info(f"  多头信号: {stats['long_signals']} ({stats['long_ratio']*100:.1f}%)")
            logger.info(f"  空头信号: {stats['short_signals']} ({stats['short_ratio']*100:.1f}%)")
            logger.info(f"  抑制信号: {stats['suppressed_signals']} ({stats['suppression_ratio']*100:.1f}%)")

            output = {
                "status": "success",
                "statistics": stats
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
