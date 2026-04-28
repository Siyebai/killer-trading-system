#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("profit_taking_optimizer")
except ImportError:
    import logging
    logger = logging.getLogger("profit_taking_optimizer")
"""
智能止盈策略优化模块 - V4.6
基于500笔交易数据分析，解决止盈触发率仅1%的问题
核心策略：分批止盈 + 动态追踪 + 多目标退出
"""

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np


class ExitReason(Enum):
    """退出原因"""
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT_PARTIAL = "TAKE_PROFIT_PARTIAL"
    TAKE_PROFIT_FULL = "TAKE_PROFIT_FULL"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_EXIT = "TIME_EXIT"
    SIGNAL_REVERSAL = "SIGNAL_REVERSAL"
    MANUAL = "MANUAL"


@dataclass
class ProfitTarget:
    """止盈目标"""
    level: int  # 止盈级别（1=保守，2=中等，3=激进）
    atr_multiplier: float  # ATR倍数
    exit_percent: float  # 退出比例（0-1）
    reason: str  # 止盈原因


@dataclass
class ExitPlan:
    """退出计划"""
    entry_price: float
    stop_loss: float
    profit_targets: List[ProfitTarget]
    trailing_stop_config: Dict
    max_hold_period: Optional[int]  # 最大持仓周期（K线数）


class SmartProfitTaker:
    """智能止盈策略"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化智能止盈策略

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 默认止盈配置（基于500笔交易优化）
        self.atr_period = self.config.get('atr_period', 14)

        # 分批止盈配置
        self.enable_batch_profit = self.config.get('enable_batch_profit', True)
        self.profit_levels = self.config.get('profit_levels', [
            {'atr_multiplier': 1.5, 'exit_percent': 0.3},  # 默认值
            {'atr_multiplier': 2.5, 'exit_percent': 0.4},
            {'atr_multiplier': 4.0, 'exit_percent': 0.3}
        ])

        # 动态追踪配置
        self.enable_trailing_stop = self.config.get('enable_trailing_stop', True)
        self.trailing_activation_atr = self.config.get('trailing_activation_atr', 2.0)  # 盈利>=2*ATR启动追踪
        self.trailing_distance_atr = self.config.get('trailing_distance_atr', 0.8)  # 追踪距离0.8*ATR

        # 时间退出配置
        self.enable_time_exit = self.config.get('enable_time_exit', True)
        self.max_hold_periods = self.config.get('max_hold_periods', 100)  # 最大100个K线

        # 信号反转退出
        self.enable_signal_reversal = self.config.get('enable_signal_reversal', True)

    def calculate_atr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
        """
        计算ATR

        Args:
            high: 最高价数组
            low: 最低价数组
            close: 收盘价数组

        Returns:
            ATR数组
        """
        tr1 = high[1:] - low[1:]
        tr2 = np.abs(high[1:] - close[:-1])
        tr3 = np.abs(low[1:] - close[:-1])

        tr = np.maximum(tr1, np.maximum(tr2, tr3))

        atr = np.zeros_like(close)
        atr[0] = tr[0] if len(tr) > 0 else 0

        for i in range(1, len(atr)):
            atr[i] = (atr[i-1] * (self.atr_period - 1) + tr[i-1]) / self.atr_period

        return atr

    def create_exit_plan(self, entry_price: float, side: str, current_atr: float) -> ExitPlan:
        """
        创建退出计划

        Args:
            entry_price: 入场价格
            side: 方向（long/short）
            current_atr: 当前ATR值

        Returns:
            退出计划
        """
        # 计算止损（1.5*ATR）
        if side == 'long':
            stop_loss = entry_price - 1.5 * current_atr
        else:
            stop_loss = entry_price + 1.5 * current_atr

        # 创建止盈目标
        profit_targets = []
        for i, level_config in enumerate(self.profit_levels, 1):
            atr_mult = level_config['atr_multiplier']
            exit_pct = level_config['exit_percent']

            if side == 'long':
                target_price = entry_price + atr_mult * current_atr
            else:
                target_price = entry_price - atr_mult * current_atr

            profit_targets.append(ProfitTarget(
                level=i,
                atr_multiplier=atr_mult,
                exit_percent=exit_pct,
                reason=f"止盈级别{i}：{atr_mult}*ATR"
            ))

        # 追踪止损配置
        trailing_config = {
            'activation_atr': self.trailing_activation_atr,
            'distance_atr': self.trailing_distance_atr
        }

        return ExitPlan(
            entry_price=entry_price,
            stop_loss=stop_loss,
            profit_targets=profit_targets,
            trailing_stop_config=trailing_config,
            max_hold_period=self.max_hold_periods
        )

    def check_exit_signal(self, current_price: float, exit_plan: ExitPlan,
                          side: str, current_atr: float, hold_period: int,
                          signal_reversal: bool = False) -> Tuple[bool, Optional[ExitReason], Optional[float]]:
        """
        检查退出信号

        Args:
            current_price: 当前价格
            exit_plan: 退出计划
            side: 方向
            current_atr: 当前ATR
            hold_period: 持仓周期
            signal_reversal: 信号反转标志

        Returns:
            (是否退出, 退出原因, 退出数量比例)
        """
        # 1. 止损检查
        if side == 'long':
            if current_price <= exit_plan.stop_loss:
                return True, ExitReason.STOP_LOSS, 1.0
        else:
            if current_price >= exit_plan.stop_loss:
                return True, ExitReason.STOP_LOSS, 1.0

        # 2. 分批止盈检查
        if self.enable_batch_profit:
            for target in exit_plan.profit_targets:
                if side == 'long':
                    target_price = exit_plan.entry_price + target.atr_multiplier * current_atr
                    if current_price >= target_price:
                        return True, ExitReason.TAKE_PROFIT_PARTIAL, target.exit_percent
                else:
                    target_price = exit_plan.entry_price - target.atr_multiplier * current_atr
                    if current_price <= target_price:
                        return True, ExitReason.TAKE_PROFIT_PARTIAL, target.exit_percent

        # 3. 时间退出检查
        if self.enable_time_exit and hold_period >= exit_plan.max_hold_period:
            return True, ExitReason.TIME_EXIT, 1.0

        # 4. 信号反转退出
        if self.enable_signal_reversal and signal_reversal:
            return True, ExitReason.SIGNAL_REVERSAL, 1.0

        # 5. 追踪止损检查
        if self.enable_trailing_stop:
            # 检查是否激活追踪止损
            profit_atr = 0
            if side == 'long':
                profit_atr = (current_price - exit_plan.entry_price) / current_atr
            else:
                profit_atr = (exit_plan.entry_price - current_price) / current_atr

            if profit_atr >= self.trailing_activation_atr:
                # 计算追踪止损价
                if side == 'long':
                    trailing_stop = current_price - self.trailing_distance_atr * current_atr
                    if trailing_stop > exit_plan.stop_loss:
                        exit_plan.stop_loss = trailing_stop  # 更新止损
                else:
                    trailing_stop = current_price + self.trailing_distance_atr * current_atr
                    if trailing_stop < exit_plan.stop_loss:
                        exit_plan.stop_loss = trailing_stop

        return False, None, None

    def get_statistics(self) -> Dict:
        """获取统计信息"""
        return {
            'enable_batch_profit': self.enable_batch_profit,
            'enable_trailing_stop': self.enable_trailing_stop,
            'enable_time_exit': self.enable_time_exit,
            'enable_signal_reversal': self.enable_signal_reversal,
            'profit_levels': self.profit_levels,
            'trailing_activation_atr': self.trailing_activation_atr,
            'trailing_distance_atr': self.trailing_distance_atr,
            'max_hold_periods': self.max_hold_periods
        }


def main():
    parser = argparse.ArgumentParser(description="智能止盈策略优化")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--entry-price", type=float, required=True, help="入场价格")
    parser.add_argument("--side", required=True, choices=['long', 'short'], help="方向")
    parser.add_argument("--atr", type=float, required=True, help="当前ATR值")
    parser.add_argument("--current-price", type=float, help="当前价格（测试退出信号）")
    parser.add_argument("--hold-period", type=int, default=0, help="持仓周期")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建智能止盈策略
        profit_taker = SmartProfitTaker(config)

        logger.info("=" * 70)
        logger.info("🎯 智能止盈策略优化 - V4.6")
        logger.info("=" * 70)

        stats = profit_taker.get_statistics()
        logger.info(f"\n配置:")
        logger.info(f"  分批止盈: {'启用' if stats['enable_batch_profit'] else '禁用'}")
        logger.info(f"  追踪止损: {'启用' if stats['enable_trailing_stop'] else '禁用'}")
        logger.info(f"  时间退出: {'启用' if stats['enable_time_exit'] else '禁用'}")
        logger.info(f"  信号反转: {'启用' if stats['enable_signal_reversal'] else '禁用'}")

        if stats['enable_batch_profit']:
            logger.info(f"\n分批止盈配置:")
            for level in stats['profit_levels']:
                logger.info(f"  级别{level['atr_multiplier']}*ATR: 退出{level['exit_percent']*100}%")

        # 创建退出计划
        exit_plan = profit_taker.create_exit_plan(args.entry_price, args.side, args.atr)

        logger.info(f"\n退出计划:")
        logger.info(f"  入场价格: ${args.entry_price:.2f}")
        logger.info(f"  止损价格: ${exit_plan.stop_loss:.2f}")
        logger.info(f"  最大持仓: {exit_plan.max_hold_period} K线")

        if args.side == 'long':
            logger.info(f"\n止盈目标:")
            for target in exit_plan.profit_targets:
                target_price = args.entry_price + target.atr_multiplier * args.atr
                profit_pct = (target_price - args.entry_price) / args.entry_price * 100
                logger.info(f"  级别{target.level}: ${target_price:.2f} ({profit_pct:+.2f}%) - 退出{target.exit_percent*100}%")
        else:
            logger.info(f"\n止盈目标:")
            for target in exit_plan.profit_targets:
                target_price = args.entry_price - target.atr_multiplier * args.atr
                profit_pct = (target_price - args.entry_price) / args.entry_price * 100
                logger.info(f"  级别{target.level}: ${target_price:.2f} ({profit_pct:+.2f}%) - 退出{target.exit_percent*100}%")

        # 测试退出信号
        if args.current_price:
            logger.info(f"\n{'=' * 70}")
            logger.info("退出信号测试")
            logger.info(f"{'=' * 70}")

            should_exit, reason, exit_ratio = profit_taker.check_exit_signal(
                args.current_price, exit_plan, args.side, args.atr, args.hold_period
            )

            logger.info(f"\n当前价格: ${args.current_price:.2f}")
            logger.info(f"持仓周期: {args.hold_period} K线")
            logger.info(f"\n退出信号: {'✅ 触发' if should_exit else '❌ 未触发'}")

            if should_exit:
                logger.info(f"  退出原因: {reason.value if reason else '未知'}")
                logger.info(f"  退出比例: {exit_ratio*100:.1f}%")

        output = {
            "status": "success",
            "exit_plan": {
                "entry_price": exit_plan.entry_price,
                "stop_loss": exit_plan.stop_loss,
                "profit_targets": [
                    {
                        "level": t.level,
                        "atr_multiplier": t.atr_multiplier,
                        "exit_percent": t.exit_percent,
                        "reason": t.reason
                    }
                    for t in exit_plan.profit_targets
                ],
                "max_hold_period": exit_plan.max_hold_period
            },
            "exit_signal": {
                "should_exit": should_exit if args.current_price else False,
                "reason": reason.value if reason else None,
                "exit_ratio": exit_ratio if args.current_price else None
            } if args.current_price else None
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
