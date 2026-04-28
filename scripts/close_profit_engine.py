#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("close_profit_engine")
except ImportError:
    import logging
    logger = logging.getLogger("close_profit_engine")
"""
平仓获利引擎（第6层：平仓获利）
平仓决策引擎 + 获利优化
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import pandas as pd


class CloseReason(Enum):
    """平仓原因"""
    TAKE_PROFIT = "TAKE_PROFIT"  # 止盈
    STOP_LOSS = "STOP_LOSS"  # 止损
    SIGNAL_REVERSAL = "SIGNAL_REVERSAL"  # 信号反转
    TIME_EXIT = "TIME_EXIT"  # 时间退出
    RISK_MANAGEMENT = "RISK_MANAGEMENT"  # 风险管理
    MANUAL = "MANUAL"  # 手动平仓
    OPTIMIZED_EXIT = "OPTIMIZED_EXIT"  # 优化平仓


class ExitType(Enum):
    """退出类型"""
    FULL = "FULL"  # 全部平仓
    PARTIAL = "PARTIAL"  # 部分平仓


@dataclass
class Position:
    """持仓"""
    position_id: str
    symbol: str
    side: str  # LONG/SHORT
    entry_price: float
    current_price: float
    quantity: float
    entry_time: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    holding_time: float = 0.0

    def update(self, current_price: float):
        """更新持仓"""
        self.current_price = current_price
        self.holding_time = time.time() - self.entry_time

        if self.side == 'LONG':
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
            self.unrealized_pnl_pct = (current_price - self.entry_price) / self.entry_price
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity
            self.unrealized_pnl_pct = (self.entry_price - current_price) / self.entry_price

    def to_dict(self) -> Dict:
        return {
            'position_id': self.position_id,
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'current_price': self.current_price,
            'quantity': self.quantity,
            'entry_time': self.entry_time,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'unrealized_pnl': self.unrealized_pnl,
            'unrealized_pnl_pct': self.unrealized_pnl_pct,
            'holding_time': self.holding_time
        }


@dataclass
class CloseDecision:
    """平仓决策"""
    should_close: bool
    close_reason: CloseReason
    exit_type: ExitType
    close_quantity: float  # 部分平仓时的数量
    close_price: Optional[float] = None
    confidence: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'should_close': self.should_close,
            'close_reason': self.close_reason.value,
            'exit_type': self.exit_type.value,
            'close_quantity': self.close_quantity,
            'close_price': self.close_price,
            'confidence': self.confidence,
            'details': self.details
        }


class TakeProfitOptimizer:
    """止盈优化器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.min_profit_pct = self.config.get('min_profit_pct', 0.005)  # 最小止盈 0.5%
        self.max_profit_pct = self.config.get('max_profit_pct', 0.05)  # 最大止盈 5%
        self.partial_profit_levels = self.config.get('partial_profit_levels', [0.01, 0.02, 0.03])  # 分批止盈点位

    def optimize(self, position: Position, market_data: Optional[Dict] = None) -> CloseDecision:
        """优化止盈决策"""
        current_profit_pct = position.unrealized_pnl_pct

        # 检查是否达到最小止盈
        if current_profit_pct < self.min_profit_pct:
            return CloseDecision(
                should_close=False,
                close_reason=CloseReason.TAKE_PROFIT,
                exit_type=ExitType.FULL,
                close_quantity=0.0,
                confidence=0.0,
                details={'current_profit_pct': current_profit_pct, 'min_profit_pct': self.min_profit_pct}
            )

        # 检查是否达到最大止盈
        if current_profit_pct >= self.max_profit_pct:
            # 超过最大止盈，全部平仓
            return CloseDecision(
                should_close=True,
                close_reason=CloseReason.TAKE_PROFIT,
                exit_type=ExitType.FULL,
                close_quantity=position.quantity,
                close_price=position.current_price,
                confidence=0.95,
                details={'current_profit_pct': current_profit_pct, 'max_profit_pct': self.max_profit_pct}
            )

        # 检查分批止盈
        for i, level in enumerate(self.partial_profit_levels):
            if abs(current_profit_pct - level) < 0.002:  # 在止盈点位附近
                # 计算部分平仓数量
                partial_ratio = (i + 1) / len(self.partial_profit_levels)
                close_quantity = position.quantity * partial_ratio

                return CloseDecision(
                    should_close=True,
                    close_reason=CloseReason.OPTIMIZED_EXIT,
                    exit_type=ExitType.PARTIAL,
                    close_quantity=close_quantity,
                    close_price=position.current_price,
                    confidence=0.8,
                    details={'partial_level': level, 'partial_ratio': partial_ratio}
                )

        # 未达到止盈条件
        return CloseDecision(
            should_close=False,
            close_reason=CloseReason.TAKE_PROFIT,
            exit_type=ExitType.FULL,
            close_quantity=0.0,
            confidence=0.0,
            details={'current_profit_pct': current_profit_pct}
        )


class StopLossMonitor:
    """止损监控器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.default_stop_loss_pct = self.config.get('default_stop_loss_pct', 0.02)  # 默认止损 2%
        self.max_loss_pct = self.config.get('max_loss_pct', 0.05)  # 最大止损 5%

    def check_stop_loss(self, position: Position) -> CloseDecision:
        """检查止损"""
        current_loss_pct = -position.unrealized_pnl_pct

        # 检查设定止损
        if position.stop_loss:
            if position.side == 'LONG':
                if position.current_price <= position.stop_loss:
                    return CloseDecision(
                        should_close=True,
                        close_reason=CloseReason.STOP_LOSS,
                        exit_type=ExitType.FULL,
                        close_quantity=position.quantity,
                        close_price=position.stop_loss,
                        confidence=1.0,
                        details={'stop_loss_triggered': True}
                    )
            else:
                if position.current_price >= position.stop_loss:
                    return CloseDecision(
                        should_close=True,
                        close_reason=CloseReason.STOP_LOSS,
                        exit_type=ExitType.FULL,
                        close_quantity=position.quantity,
                        close_price=position.stop_loss,
                        confidence=1.0,
                        details={'stop_loss_triggered': True}
                    )

        # 检查最大止损
        if current_loss_pct >= self.max_loss_pct:
            return CloseDecision(
                should_close=True,
                close_reason=CloseReason.STOP_LOSS,
                exit_type=ExitType.FULL,
                close_quantity=position.quantity,
                close_price=position.current_price,
                confidence=1.0,
                details={'max_loss_triggered': True, 'current_loss_pct': current_loss_pct}
            )

        # 未触发止损
        return CloseDecision(
            should_close=False,
            close_reason=CloseReason.STOP_LOSS,
            exit_type=ExitType.FULL,
            close_quantity=0.0,
            confidence=0.0,
            details={'current_loss_pct': current_loss_pct}
        )


class SignalReversalDetector:
    """信号反转检测器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.reversal_threshold = self.config.get('reversal_threshold', 0.7)  # 反转信号阈值

    def detect_reversal(self, position: Position, market_analysis: Dict) -> CloseDecision:
        """检测信号反转"""
        # 获取市场分析
        direction = market_analysis.get('direction', 'NEUTRAL')
        score = market_analysis.get('score', 0.5)

        # 检查是否反转
        if position.side == 'LONG':
            if direction == 'SHORT' and score >= self.reversal_threshold:
                return CloseDecision(
                    should_close=True,
                    close_reason=CloseReason.SIGNAL_REVERSAL,
                    exit_type=ExitType.FULL,
                    close_quantity=position.quantity,
                    close_price=position.current_price,
                    confidence=score,
                    details={'new_direction': direction, 'score': score}
                )
        else:
            if direction == 'LONG' and score >= self.reversal_threshold:
                return CloseDecision(
                    should_close=True,
                    close_reason=CloseReason.SIGNAL_REVERSAL,
                    exit_type=ExitType.FULL,
                    close_quantity=position.quantity,
                    close_price=position.current_price,
                    confidence=score,
                    details={'new_direction': direction, 'score': score}
                )

        # 未检测到反转
        return CloseDecision(
            should_close=False,
            close_reason=CloseReason.SIGNAL_REVERSAL,
            exit_type=ExitType.FULL,
            close_quantity=0.0,
            confidence=0.0,
            details={'current_direction': direction, 'score': score}
        )


class TimeExitManager:
    """时间退出管理器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.max_holding_time = self.config.get('max_holding_time', 86400)  # 最大持仓时间（秒），默认24小时

    def check_time_exit(self, position: Position) -> CloseDecision:
        """检查时间退出"""
        # 检查是否超过最大持仓时间
        if position.holding_time >= self.max_holding_time:
            return CloseDecision(
                should_close=True,
                close_reason=CloseReason.TIME_EXIT,
                exit_type=ExitType.FULL,
                close_quantity=position.quantity,
                close_price=position.current_price,
                confidence=0.8,
                details={'holding_time': position.holding_time, 'max_holding_time': self.max_holding_time}
            )

        # 未达到时间退出
        return CloseDecision(
            should_close=False,
            close_reason=CloseReason.TIME_EXIT,
            exit_type=ExitType.FULL,
            close_quantity=0.0,
            confidence=0.0,
            details={'holding_time': position.holding_time, 'max_holding_time': self.max_holding_time}
        )


class RiskManagementExit:
    """风险管理退出"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.max_risk_score = self.config.get('max_risk_score', 0.8)  # 最大风险评分

    def check_risk_exit(self, position: Position, risk_analysis: Dict) -> CloseDecision:
        """检查风险管理退出"""
        risk_level = risk_analysis.get('risk_level', 'MEDIUM')
        risk_score = risk_analysis.get('risk_score', 0.5)

        # 检查风险等级
        if risk_level == 'HIGH' or risk_score >= self.max_risk_score:
            return CloseDecision(
                should_close=True,
                close_reason=CloseReason.RISK_MANAGEMENT,
                exit_type=ExitType.FULL,
                close_quantity=position.quantity,
                close_price=position.current_price,
                confidence=risk_score,
                details={'risk_level': risk_level, 'risk_score': risk_score}
            )

        # 未达到风险管理退出
        return CloseDecision(
            should_close=False,
            close_reason=CloseReason.RISK_MANAGEMENT,
            exit_type=ExitType.FULL,
            close_quantity=0.0,
            confidence=0.0,
            details={'risk_level': risk_level, 'risk_score': risk_score}
        )


class CloseProfitEngine:
    """平仓获利引擎"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化平仓获利引擎

        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.enable_take_profit = self.config.get('enable_take_profit', True)
        self.enable_stop_loss = self.config.get('enable_stop_loss', True)
        self.enable_signal_reversal = self.config.get('enable_signal_reversal', True)
        self.enable_time_exit = self.config.get('enable_time_exit', True)
        self.enable_risk_management = self.config.get('enable_risk_management', True)

        self.take_profit_optimizer = TakeProfitOptimizer(self.config.get('take_profit_config', {}))
        self.stop_loss_monitor = StopLossMonitor(self.config.get('stop_loss_config', {}))
        self.signal_reversal_detector = SignalReversalDetector(self.config.get('signal_reversal_config', {}))
        self.time_exit_manager = TimeExitManager(self.config.get('time_exit_config', {}))
        self.risk_management_exit = RiskManagementExit(self.config.get('risk_management_config', {}))

    def evaluate_close_decision(self, position: Position, market_analysis: Optional[Dict] = None, risk_analysis: Optional[Dict] = None) -> CloseDecision:
        """评估平仓决策"""
        # 更新持仓
        position.update(position.current_price)

        # 优先级：止损 > 信号反转 > 风险管理 > 止盈 > 时间退出

        decisions = []

        # 1. 止损检查（最高优先级）
        if self.enable_stop_loss:
            stop_loss_decision = self.stop_loss_monitor.check_stop_loss(position)
            if stop_loss_decision.should_close:
                return stop_loss_decision
            decisions.append(('STOP_LOSS', stop_loss_decision))

        # 2. 信号反转检查
        if self.enable_signal_reversal and market_analysis:
            reversal_decision = self.signal_reversal_detector.detect_reversal(position, market_analysis)
            if reversal_decision.should_close:
                return reversal_decision
            decisions.append(('SIGNAL_REVERSAL', reversal_decision))

        # 3. 风险管理检查
        if self.enable_risk_management and risk_analysis:
            risk_decision = self.risk_management_exit.check_risk_exit(position, risk_analysis)
            if risk_decision.should_close:
                return risk_decision
            decisions.append(('RISK_MANAGEMENT', risk_decision))

        # 4. 止盈优化
        if self.enable_take_profit:
            take_profit_decision = self.take_profit_optimizer.optimize(position)
            if take_profit_decision.should_close:
                return take_profit_decision
            decisions.append(('TAKE_PROFIT', take_profit_decision))

        # 5. 时间退出检查
        if self.enable_time_exit:
            time_exit_decision = self.time_exit_manager.check_time_exit(position)
            if time_exit_decision.should_close:
                return time_exit_decision
            decisions.append(('TIME_EXIT', time_exit_decision))

        # 不平仓
        return CloseDecision(
            should_close=False,
            close_reason=CloseReason.MANUAL,
            exit_type=ExitType.FULL,
            close_quantity=0.0,
            confidence=0.0,
            details={'evaluated_decisions': [name for name, _ in decisions]}
        )

    def get_close_summary(self, position: Position) -> Dict[str, Any]:
        """获取平仓摘要"""
        return {
            'position_id': position.position_id,
            'symbol': position.symbol,
            'side': position.side,
            'entry_price': position.entry_price,
            'current_price': position.current_price,
            'quantity': position.quantity,
            'unrealized_pnl': position.unrealized_pnl,
            'unrealized_pnl_pct': position.unrealized_pnl_pct,
            'holding_time': position.holding_time,
            'holding_time_str': f"{position.holding_time / 3600:.1f}小时",
            'stop_loss': position.stop_loss,
            'take_profit': position.take_profit
        }


def main():
    parser = argparse.ArgumentParser(description="平仓获利引擎（第6层：平仓获利）")
    parser.add_argument("--action", choices=["evaluate", "test"], default="test", help="操作类型")
    parser.add_argument("--position", help="持仓JSON")
    parser.add_argument("--market_analysis", help="市场分析JSON")
    parser.add_argument("--risk_analysis", help="风险分析JSON")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r') as f:
                config = json.load(config)

        # 创建平仓获利引擎
        engine = CloseProfitEngine(config)

        logger.info("=" * 70)
        logger.info("✅ 杀手锏交易系统 - 平仓获利引擎（第6层：平仓获利）")
        logger.info("=" * 70)

        if args.action == "evaluate":
            # 评估平仓决策
            if not args.position:
                logger.info("错误: 请提供持仓数据")
                sys.exit(1)

            position_data = json.loads(args.position)
            position = Position(**position_data)

            # 加载分析数据
            market_analysis = json.loads(args.market_analysis) if args.market_analysis else None
            risk_analysis = json.loads(args.risk_analysis) if args.risk_analysis else None

            # 更新持仓
            position.update(position.current_price)

            logger.info(f"\n[持仓信息]")
            summary = engine.get_close_summary(position)
            logger.info(f"  持仓ID: {summary['position_id']}")
            logger.info(f"  品种: {summary['symbol']}")
            logger.info(f"  方向: {summary['side']}")
            logger.info(f"  入场价: {summary['entry_price']}")
            logger.info(f"  当前价: {summary['current_price']}")
            logger.info(f"  数量: {summary['quantity']}")
            logger.info(f"  未实现盈亏: {summary['unrealized_pnl']:.2f}")
            logger.info(f"  未实现盈亏%: {summary['unrealized_pnl_pct']:.2%}")
            logger.info(f"  持仓时间: {summary['holding_time_str']}")

            # 评估平仓决策
            logger.info(f"\n[平仓评估]")
            decision = engine.evaluate_close_decision(position, market_analysis, risk_analysis)

            logger.info(f"  是否平仓: {decision.should_close}")
            logger.info(f"  平仓原因: {decision.close_reason.value}")
            logger.info(f"  退出类型: {decision.exit_type.value}")
            logger.info(f"  平仓数量: {decision.close_quantity}")
            logger.info(f"  置信度: {decision.confidence:.2%}")

            output = {
                "status": "success",
                "position_summary": summary,
                "close_decision": decision.to_dict()
            }

        elif args.action == "test":
            # 测试模式
            # 测试1: 止盈场景
            position_profit = Position(
                position_id='pos_profit',
                symbol='BTCUSDT',
                side='LONG',
                entry_price=50000.0,
                current_price=52500.0,  # 盈利5%
                quantity=0.1,
                entry_time=time.time() - 3600  # 1小时前
            )

            decision_profit = engine.evaluate_close_decision(position_profit)

            # 测试2: 止损场景
            position_loss = Position(
                position_id='pos_loss',
                symbol='BTCUSDT',
                side='LONG',
                entry_price=50000.0,
                current_price=47500.0,  # 亏损5%
                quantity=0.1,
                entry_time=time.time() - 1800,  # 30分钟前
                stop_loss=48000.0
            )

            decision_loss = engine.evaluate_close_decision(position_loss)

            # 测试3: 信号反转场景
            position_reversal = Position(
                position_id='pos_reversal',
                symbol='BTCUSDT',
                side='LONG',
                entry_price=50000.0,
                current_price=50200.0,  # 小幅盈利
                quantity=0.1,
                entry_time=time.time() - 7200  # 2小时前
            )

            market_analysis = {
                'direction': 'SHORT',
                'score': 0.8
            }

            decision_reversal = engine.evaluate_close_decision(position_reversal, market_analysis)

            # 测试4: 时间退出场景
            position_time = Position(
                position_id='pos_time',
                symbol='BTCUSDT',
                side='LONG',
                entry_price=50000.0,
                current_price=50100.0,  # 小幅盈利
                quantity=0.1,
                entry_time=time.time() - 86400  # 24小时前
            )

            decision_time = engine.evaluate_close_decision(position_time)

            output = {
                "status": "success",
                "test_take_profit": {
                    "position": engine.get_close_summary(position_profit),
                    "decision": decision_profit.to_dict()
                },
                "test_stop_loss": {
                    "position": engine.get_close_summary(position_loss),
                    "decision": decision_loss.to_dict()
                },
                "test_signal_reversal": {
                    "position": engine.get_close_summary(position_reversal),
                    "decision": decision_reversal.to_dict()
                },
                "test_time_exit": {
                    "position": engine.get_close_summary(position_time),
                    "decision": decision_time.to_dict()
                }
            }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        import traceback
        logger.error(json.dumps({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
