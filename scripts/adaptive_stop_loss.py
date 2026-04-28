#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("adaptive_stop_loss")
except ImportError:
    import logging
    logger = logging.getLogger("adaptive_stop_loss")
"""
自适应止损优化模块 - P1优先级优化
解决止损触发率46.5%问题，从"被动挨打"到"主动防守"
核心策略：持仓时间动态调整 + 波动率自适应止损
"""

import argparse
import json
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np


class Direction(Enum):
    """交易方向"""
    LONG = "LONG"
    SHORT = "SHORT"


class Phase(Enum):
    """持仓阶段"""
    INITIAL = "INITIAL"  # 初始阶段（<5根K线）
    HOLDING = "HOLDING"  # 持仓阶段（5-15根K线）
    PROFIT_PROTECTION = "PROFIT_PROTECTION"  # 利润保护阶段（>15根K线）


@dataclass
class StopLossResult:
    """止损结果"""
    stop_loss_price: float
    stop_loss_distance: float  # 距离入场价的比例
    atr_multiplier: float
    phase: Phase
    volatility_adjustment: float
    reason: str


class AdaptiveStopLoss:
    """自适应止损管理器"""

    def __init__(
        self,
        config: Optional[Dict] = None
    ):
        """
        初始化自适应止损管理器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 持仓阶段参数
        self.initial_phase_bars = self.config.get('initial_phase_bars', 5)  # 初始阶段5根K线
        self.holding_phase_bars = self.config.get('holding_phase_bars', 15)  # 持仓阶段15根K线

        # ATR倍数参数
        self.initial_atr_multiplier = self.config.get('initial_atr_multiplier', 2.5)  # 初始2.5倍ATR
        self.holding_atr_multiplier = self.config.get('holding_atr_multiplier', 2.0)  # 持仓2.0倍ATR
        self.protection_atr_multiplier = self.config.get('protection_atr_multiplier', 1.5)  # 利润保护1.5倍ATR

        # 波动率调整参数
        self.volatility_threshold_high = self.config.get('volatility_threshold_high', 0.03)  # 高波动阈值3%
        self.volatility_threshold_low = self.config.get('volatility_threshold_low', 0.01)  # 低波动阈值1%
        self.volatility_adjustment_high = self.config.get('volatility_adjustment_high', 0.5)  # 高波动+0.5倍ATR
        self.volatility_adjustment_low = self.config.get('volatility_adjustment_low', -0.5)  # 低波动-0.5倍ATR

        # 最小/最大止损距离
        self.min_stop_distance = self.config.get('min_stop_distance', 0.5)  # 最小0.5倍ATR
        self.max_stop_distance = self.config.get('max_stop_distance', 4.0)  # 最大4.0倍ATR

    def calculate_stop_loss(
        self,
        entry_price: float,
        atr: float,
        direction: Direction,
        holding_bars: int,
        current_price: float,
        volatility: Optional[float] = None,
        is_profitable: bool = False
    ) -> StopLossResult:
        """
        计算自适应止损

        Args:
            entry_price: 入场价格
            atr: 当前ATR值
            direction: 交易方向
            holding_bars: 持仓时间（K线数）
            current_price: 当前价格
            volatility: 当前波动率（可选）
            is_profitable: 是否盈利（可选）

        Returns:
            止损结果
        """
        # 确定持仓阶段
        phase = self._determine_phase(holding_bars)

        # 根据阶段选择基础ATR倍数
        if phase == Phase.INITIAL:
            base_multiplier = self.initial_atr_multiplier
            phase_reason = "初始阶段，放宽止损避免过早被震荡触发"
        elif phase == Phase.HOLDING:
            base_multiplier = self.holding_atr_multiplier
            phase_reason = "持仓阶段，标准止损"
        else:  # Phase.PROFIT_PROTECTION
            if is_profitable:
                base_multiplier = self.protection_atr_multiplier
                phase_reason = "利润保护阶段，收紧止损保护利润"
            else:
                base_multiplier = self.holding_atr_multiplier
                phase_reason = "利润保护阶段但未盈利，保持标准止损"

        # 波动率调整
        volatility_adjustment = self._calculate_volatility_adjustment(volatility)

        # 计算最终ATR倍数
        final_multiplier = base_multiplier + volatility_adjustment

        # 限制在最小/最大范围内
        final_multiplier = max(self.min_stop_distance, min(self.max_stop_distance, final_multiplier))

        # 计算止损价格
        if direction == Direction.LONG:
            stop_loss_distance = final_multiplier * atr
            stop_loss_price = entry_price - stop_loss_distance
        else:  # SHORT
            stop_loss_distance = final_multiplier * atr
            stop_loss_price = entry_price + stop_loss_distance

        # 计算止损距离比例
        stop_loss_distance_ratio = stop_loss_distance / entry_price

        # 构建原因说明
        reason_parts = [
            phase_reason,
            f"ATR倍数: {final_multiplier:.2f}x"
        ]

        if volatility_adjustment != 0:
            volatility_status = "高波动" if volatility_adjustment > 0 else "低波动"
            reason_parts.append(f"{volatility_status}调整: {volatility_adjustment:+.1f}x")

        reason = " | ".join(reason_parts)

        return StopLossResult(
            stop_loss_price=stop_loss_price,
            stop_loss_distance=stop_loss_distance_ratio,
            atr_multiplier=final_multiplier,
            phase=phase,
            volatility_adjustment=volatility_adjustment,
            reason=reason
        )

    def _determine_phase(self, holding_bars: int) -> Phase:
        """
        确定持仓阶段

        Args:
            holding_bars: 持仓时间（K线数）

        Returns:
            持仓阶段
        """
        if holding_bars < self.initial_phase_bars:
            return Phase.INITIAL
        elif holding_bars < self.holding_phase_bars:
            return Phase.HOLDING
        else:
            return Phase.PROFIT_PROTECTION

    def _calculate_volatility_adjustment(self, volatility: Optional[float]) -> float:
        """
        计算波动率调整

        Args:
            volatility: 当前波动率

        Returns:
            波动率调整值（ATR倍数）
        """
        if volatility is None:
            return 0.0

        if volatility >= self.volatility_threshold_high:
            # 高波动：放宽止损
            return self.volatility_adjustment_high
        elif volatility <= self.volatility_threshold_low:
            # 低波动：收紧止损
            return self.volatility_adjustment_low
        else:
            # 中等波动：不调整
            return 0.0

    def check_stop_loss_trigger(
        self,
        current_price: float,
        stop_loss_price: float,
        direction: Direction
    ) -> bool:
        """
        检查是否触发止损

        Args:
            current_price: 当前价格
            stop_loss_price: 止损价格
            direction: 交易方向

        Returns:
            是否触发止损
        """
        if direction == Direction.LONG:
            return current_price <= stop_loss_price
        else:  # SHORT
            return current_price >= stop_loss_price

    def update_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        atr: float,
        direction: Direction,
        current_stop_loss: float,
        holding_bars: int,
        is_profitable: bool = False
    ) -> Optional[float]:
        """
        更新跟踪止损

        Args:
            entry_price: 入场价格
            current_price: 当前价格
            atr: 当前ATR值
            direction: 交易方向
            current_stop_loss: 当前止损价格
            holding_bars: 持仓时间
            is_profitable: 是否盈利

        Returns:
            新的止损价格（如果需要更新）
        """
        # 只在盈利时才启动跟踪止损
        if not is_profitable:
            return None

        # 计算利润比例
        if direction == Direction.LONG:
            profit_ratio = (current_price - entry_price) / entry_price
        else:
            profit_ratio = (entry_price - current_price) / entry_price

        # 只有利润超过1倍ATR时才启动跟踪止损
        atr_ratio = atr / entry_price
        if profit_ratio < atr_ratio:
            return None

        # 计算新的止损价格（使用利润保护阶段的ATR倍数）
        new_stop_distance = self.protection_atr_multiplier * atr

        if direction == Direction.LONG:
            new_stop_loss = current_price - new_stop_distance
            # 只有新止损比当前止损更优时才更新
            if new_stop_loss > current_stop_loss:
                return new_stop_loss
        else:  # SHORT
            new_stop_loss = current_price + new_stop_distance
            # 只有新止损比当前止损更优时才更新
            if new_stop_loss < current_stop_loss:
                return new_stop_loss

        return None


class StopLossAnalyzer:
    """止损分析器"""

    @staticmethod
    def analyze_stop_loss_performance(trades: List[Dict]) -> Dict:
        """
        分析止损表现

        Args:
            trades: 交易历史

        Returns:
            止损表现分析
        """
        if not trades:
            return {
                "total_trades": 0,
                "stop_loss_trades": 0,
                "stop_loss_rate": 0.0,
                "avg_stop_loss_pnl": 0.0,
                "avg_take_profit_pnl": 0.0
            }

        # 分类交易
        stop_loss_trades = [t for t in trades if t.get('exit_reason') == 'STOP_LOSS']
        take_profit_trades = [t for t in trades if t.get('exit_reason') in ['TAKE_PROFIT', 'TRAILING_STOP', 'SIGNAL_REVERSE']]

        total_trades = len(trades)
        stop_loss_count = len(stop_loss_trades)
        take_profit_count = len(take_profit_trades)

        # 计算平均盈亏
        avg_stop_loss_pnl = np.mean([t.get('pnl', 0) for t in stop_loss_trades]) if stop_loss_trades else 0
        avg_take_profit_pnl = np.mean([t.get('pnl', 0) for t in take_profit_trades]) if take_profit_trades else 0

        # 计算止损触发率
        stop_loss_rate = stop_loss_count / total_trades if total_trades > 0 else 0

        # 分析问题
        issues = []

        if stop_loss_rate > 0.45:
            issues.append("止损触发率过高（>45%），说明入场信号过于激进或止损设置过紧")

        if avg_stop_loss_pnl < -50 and avg_take_profit_pnl > 100:
            issues.append("止损亏损过大 vs 止盈盈利，需要优化盈亏比")

        stop_loss_to_take_profit_ratio = stop_loss_count / take_profit_count if take_profit_count > 0 else 0
        if stop_loss_to_take_profit_ratio > 1.0:
            issues.append(f"止损/止盈比例失衡（{stop_loss_to_take_profit_ratio:.2f}），需要优化止损策略")

        return {
            "total_trades": total_trades,
            "stop_loss_trades": stop_loss_count,
            "take_profit_trades": take_profit_count,
            "stop_loss_rate": stop_loss_rate,
            "avg_stop_loss_pnl": avg_stop_loss_pnl,
            "avg_take_profit_pnl": avg_take_profit_pnl,
            "stop_loss_to_take_profit_ratio": stop_loss_to_take_profit_ratio,
            "issues": issues,
            "recommendations": StopLossAnalyzer._generate_recommendations(
                stop_loss_rate, avg_stop_loss_pnl, avg_take_profit_pnl
            )
        }

    @staticmethod
    def _generate_recommendations(
        stop_loss_rate: float,
        avg_stop_loss_pnl: float,
        avg_take_profit_pnl: float
    ) -> List[str]:
        """生成优化建议"""
        recommendations = []

        if stop_loss_rate > 0.45:
            recommendations.append("启用自适应止损，根据持仓时间动态调整止损距离")
            recommendations.append("提升信号质量阈值，减少低质量开仓")

        if avg_stop_loss_pnl < -50:
            recommendations.append("降低最大仓位，控制单笔最大亏损")
            recommendations.append("优化入场时机，避免在震荡市开仓")

        if avg_take_profit_pnl > 0 and avg_stop_loss_pnl < 0:
            reward_risk_ratio = abs(avg_take_profit_pnl / avg_stop_loss_pnl) if avg_stop_loss_pnl != 0 else 0
            if reward_risk_ratio > 3:
                recommendations.append("盈亏比良好，保持当前止盈策略")
            elif reward_risk_ratio < 2:
                recommendations.append("盈亏比过低，需要优化止盈策略或收紧止损")

        return recommendations


def main():
    parser = argparse.ArgumentParser(description="自适应止损优化")
    parser.add_argument("--action", choices=["calculate", "check", "analyze"], required=True, help="操作类型")
    parser.add_argument("--entry-price", type=float, help="入场价格")
    parser.add_argument("--atr", type=float, help="ATR值")
    parser.add_argument("--direction", choices=["LONG", "SHORT"], help="交易方向")
    parser.add_argument("--holding-bars", type=int, help="持仓时间（K线数）")
    parser.add_argument("--current-price", type=float, help="当前价格")
    parser.add_argument("--volatility", type=float, help="当前波动率")
    parser.add_argument("--stop-loss-price", type=float, help="止损价格")
    parser.add_argument("--is-profitable", action="store_true", help="是否盈利")
    parser.add_argument("--trades", help="交易历史JSON文件路径")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建自适应止损管理器
        stop_loss_manager = AdaptiveStopLoss(config)

        logger.info("=" * 70)
        logger.info("✅ 自适应止损优化 - P1优先级优化")
        logger.info("=" * 70)

        if args.action == "calculate":
            if not args.entry_price or not args.atr or not args.direction or not args.holding_bars or not args.current_price:
                logger.info("错误: 请提供完整参数")
                sys.exit(1)

            # 计算止损
            result = stop_loss_manager.calculate_stop_loss(
                entry_price=args.entry_price,
                atr=args.atr,
                direction=Direction(args.direction),
                holding_bars=args.holding_bars,
                current_price=args.current_price,
                volatility=args.volatility,
                is_profitable=args.is_profitable
            )

            logger.info(f"\n自适应止损计算:")
            logger.info(f"  入场价格: ${args.entry_price:.2f}")
            logger.info(f"  ATR值: ${args.atr:.2f}")
            logger.info(f"  交易方向: {args.direction}")
            logger.info(f"  持仓时间: {args.holding_bars} 根K线")
            logger.info(f"  当前价格: ${args.current_price:.2f}")
            if args.volatility:
                logger.info(f"  当前波动率: {args.volatility*100:.2f}%")
            logger.info(f"  是否盈利: {'是' if args.is_profitable else '否'}")
            logger.info(f"\n止损结果:")
            logger.info(f"  止损价格: ${result.stop_loss_price:.2f}")
            logger.info(f"  止损距离: {result.stop_loss_distance*100:.2f}%")
            logger.info(f"  ATR倍数: {result.atr_multiplier:.2f}x")
            logger.info(f"  持仓阶段: {result.phase.value}")
            logger.info(f"  波动率调整: {result.volatility_adjustment:+.1f}x")
            logger.info(f"  调整原因: {result.reason}")

            output = {
                "status": "success",
                "result": {
                    "stop_loss_price": result.stop_loss_price,
                    "stop_loss_distance": result.stop_loss_distance,
                    "atr_multiplier": result.atr_multiplier,
                    "phase": result.phase.value,
                    "volatility_adjustment": result.volatility_adjustment,
                    "reason": result.reason
                }
            }

        elif args.action == "check":
            if not args.current_price or not args.stop_loss_price or not args.direction:
                logger.info("错误: 请提供 --current-price, --stop-loss-price, --direction 参数")
                sys.exit(1)

            # 检查止损触发
            triggered = stop_loss_manager.check_stop_loss_trigger(
                current_price=args.current_price,
                stop_loss_price=args.stop_loss_price,
                direction=Direction(args.direction)
            )

            logger.info(f"\n止损检查:")
            logger.info(f"  当前价格: ${args.current_price:.2f}")
            logger.info(f"  止损价格: ${args.stop_loss_price:.2f}")
            logger.info(f"  交易方向: {args.direction}")
            logger.info(f"\n是否触发止损: {'✅ 是' if triggered else '❌ 否'}")

            output = {
                "status": "success",
                "triggered": triggered
            }

        elif args.action == "analyze":
            if not args.trades:
                logger.info("错误: 请提供 --trades 参数")
                sys.exit(1)

            # 加载交易历史
            with open(args.trades, 'r', encoding='utf-8') as f:
                trades = json.load(f)

            # 分析止损表现
            analysis = StopLossAnalyzer.analyze_stop_loss_performance(trades)

            logger.info(f"\n止损表现分析:")
            logger.info(f"  总交易数: {analysis['total_trades']}")
            logger.info(f"  止损退出: {analysis['stop_loss_trades']} ({analysis['stop_loss_rate']*100:.1f}%)")
            logger.info(f"  止盈退出: {analysis['take_profit_trades']}")
            logger.info(f"  止损/止盈比例: {analysis['stop_loss_to_take_profit_ratio']:.2f}")
            logger.info(f"  平均止损盈亏: ${analysis['avg_stop_loss_pnl']:.2f}")
            logger.info(f"  平均止盈盈亏: ${analysis['avg_take_profit_pnl']:.2f}")

            if analysis['issues']:
                logger.info(f"\n存在问题:")
                for issue in analysis['issues']:
                    logger.info(f"  ⚠️ {issue}")

            if analysis['recommendations']:
                logger.info(f"\n优化建议:")
                for rec in analysis['recommendations']:
                    logger.info(f"  💡 {rec}")

            output = {
                "status": "success",
                "analysis": analysis
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
