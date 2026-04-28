#!/usr/bin/env python3
"""
预期价值(Expected Value, EV)过滤模块 — V6.3 加固版
基于数学期望过滤低质量交易,显著提升胜率和夏普比率

核心公式:
EV = confidence * tp_pct - (1 - confidence) * sl_pct - (taker_fee + slippage + spread/2)
仅当 EV > min_ev 时才执行交易

V6.3 加固:
- 全量 print→logging 迁移
- calculate_ev 添加防御性错误处理(除零/无效输入)
- batch_filter 单条异常不影响批量处理
- 输入参数边界校验
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("ev_filter")
except ImportError:
    import logging
    logger = logging.getLogger("ev_filter")

# 导入事件总线（Phase 5.6新增）
try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False


class TradeDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class EVFilterInput:
    """EV过滤输入"""
    symbol: str
    direction: TradeDirection
    confidence: float
    entry_price: float
    tp_price: float
    sl_price: float
    taker_fee: float = 0.0004
    slippage: float = 0.0005
    spread: float = 0.0002

    def validate(self) -> List[str]:
        """输入参数校验,返回错误列表"""
        errors = []
        if not self.symbol:
            errors.append("symbol is empty")
        if self.entry_price <= 0:
            errors.append(f"entry_price must be positive, got {self.entry_price}")
        if self.tp_price <= 0:
            errors.append(f"tp_price must be positive, got {self.tp_price}")
        if self.sl_price <= 0:
            errors.append(f"sl_price must be positive, got {self.sl_price}")
        if not (0 <= self.confidence <= 1):
            errors.append(f"confidence must be 0-1, got {self.confidence}")
        if self.taker_fee < 0:
            errors.append(f"taker_fee must be non-negative, got {self.taker_fee}")
        return errors

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'direction': self.direction.value,
            'confidence': self.confidence,
            'entry_price': self.entry_price,
            'tp_price': self.tp_price,
            'sl_price': self.sl_price,
            'taker_fee': self.taker_fee,
            'slippage': self.slippage,
            'spread': self.spread
        }


@dataclass
class EVFilterResult:
    """EV过滤结果"""
    passed: bool
    ev: float
    expected_profit: float
    expected_loss: float
    transaction_cost: float
    reason: str
    recommendation: str
    confidence_adjusted: float
    symbol: str = ""
    error: str = ""

    def to_dict(self) -> Dict:
        d = {
            'passed': self.passed,
            'ev': self.ev,
            'expected_profit': self.expected_profit,
            'expected_loss': self.expected_loss,
            'transaction_cost': self.transaction_cost,
            'reason': self.reason,
            'recommendation': self.recommendation,
            'confidence_adjusted': self.confidence_adjusted,
        }
        if self.symbol:
            d['symbol'] = self.symbol
        if self.error:
            d['error'] = self.error
        return d


class EVFilter:
    """
    预期价值过滤器

    核心功能:
    1. 计算交易期望值
    2. 过滤负期望交易
    3. 评估交易质量等级
    4. 调整信号置信度
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.min_ev = self.config.get('min_ev', 0.00035)
        self.confidence_threshold = self.config.get('confidence_threshold', 0.6)
        self.risk_reward_ratio = self.config.get('risk_reward_ratio', 2.0)
        self.stats = {
            'total_checks': 0,
            'total_passed': 0,
            'total_rejected': 0,
            'total_errors': 0,
            'avg_ev': 0.0,
            'high_quality_trades': 0
        }

    def calculate_ev(self, input_data: EVFilterInput) -> EVFilterResult:
        """
        计算预期价值(含防御性错误处理)

        Args:
            input_data: EV过滤输入数据

        Returns:
            EVFilterResult: 过滤结果(异常时返回安全默认值)
        """
        self.stats['total_checks'] += 1

        try:
            # 输入校验
            validation_errors = input_data.validate()
            if validation_errors:
                self.stats['total_errors'] += 1
                self.stats['total_rejected'] += 1
                msg = f"Invalid input: {'; '.join(validation_errors)}"
                logger.error("EV filter input validation failed", extra={"extra_data": {
                    "symbol": input_data.symbol, "errors": validation_errors
                }})
                return EVFilterResult(
                    passed=False, ev=0.0, expected_profit=0.0,
                    expected_loss=0.0, transaction_cost=0.0,
                    reason=msg, recommendation="SKIP",
                    confidence_adjusted=0.0,
                    symbol=input_data.symbol, error=msg
                )

            # 计算止盈止损百分比(防御除零)
            if input_data.entry_price == 0:
                raise ZeroDivisionError("entry_price is zero")

            if input_data.direction == TradeDirection.LONG:
                tp_pct = (input_data.tp_price - input_data.entry_price) / input_data.entry_price
                sl_pct = (input_data.entry_price - input_data.sl_price) / input_data.entry_price
            else:
                tp_pct = (input_data.entry_price - input_data.tp_price) / input_data.entry_price
                sl_pct = (input_data.sl_price - input_data.entry_price) / input_data.entry_price

            # 防御: 止损方向错误(如LONG但sl_price>entry_price)
            if tp_pct < 0 or sl_pct < 0:
                self.stats['total_errors'] += 1
                self.stats['total_rejected'] += 1
                msg = f"Invalid tp/sl direction: tp_pct={tp_pct:.4f}, sl_pct={sl_pct:.4f}"
                logger.warning("EV filter: invalid tp/sl direction", extra={"extra_data": {
                    "symbol": input_data.symbol, "direction": input_data.direction.value,
                    "tp_pct": tp_pct, "sl_pct": sl_pct,
                    "entry": input_data.entry_price, "tp": input_data.tp_price,
                    "sl": input_data.sl_price
                }})
                return EVFilterResult(
                    passed=False, ev=0.0, expected_profit=0.0,
                    expected_loss=0.0, transaction_cost=0.0,
                    reason=msg, recommendation="SKIP",
                    confidence_adjusted=0.0,
                    symbol=input_data.symbol, error=msg
                )

            # 计算期望盈利和期望亏损
            expected_profit = input_data.confidence * tp_pct
            expected_loss = (1 - input_data.confidence) * sl_pct

            # 计算交易成本
            transaction_cost = input_data.taker_fee + input_data.slippage + input_data.spread / 2

            # 计算期望值
            ev = expected_profit - expected_loss - transaction_cost

            # 判断是否通过
            passed = ev > self.min_ev

            # 盈亏比(防御除零)
            risk_reward = tp_pct / sl_pct if sl_pct > 0 else 0.0

            # 生成建议
            recommendation, reason = self._generate_recommendation(
                ev, passed, risk_reward, input_data.confidence
            )

            # 调整置信度
            confidence_adjusted = self._adjust_confidence(
                input_data.confidence, ev, passed
            )

            # 更新统计
            self.stats['avg_ev'] = (
                (self.stats['avg_ev'] * (self.stats['total_checks'] - 1) + ev)
                / self.stats['total_checks']
            )
            if passed:
                self.stats['total_passed'] += 1
                if ev > 0.001:
                    self.stats['high_quality_trades'] += 1
            else:
                self.stats['total_rejected'] += 1

            logger.info("EV calculated", extra={"extra_data": {
                "symbol": input_data.symbol, "ev": round(ev, 6),
                "passed": passed, "recommendation": recommendation
            }})

            return EVFilterResult(
                passed=passed, ev=ev,
                expected_profit=expected_profit,
                expected_loss=expected_loss,
                transaction_cost=transaction_cost,
                reason=reason, recommendation=recommendation,
                confidence_adjusted=confidence_adjusted,
                symbol=input_data.symbol
            )

        except ZeroDivisionError as e:
            self.stats['total_errors'] += 1
            self.stats['total_rejected'] += 1
            msg = f"Division by zero in EV calculation: {e}"
            logger.error("EV calculation zero division", extra={"extra_data": {
                "symbol": input_data.symbol, "error": str(e)
            }})
            return EVFilterResult(
                passed=False, ev=0.0, expected_profit=0.0,
                expected_loss=0.0, transaction_cost=0.0,
                reason=msg, recommendation="SKIP",
                confidence_adjusted=0.0,
                symbol=input_data.symbol, error=msg
            )

        except Exception as e:
            self.stats['total_errors'] += 1
            self.stats['total_rejected'] += 1
            msg = f"EV calculation error: {e}"
            logger.error("EV calculation unexpected error", extra={"extra_data": {
                "symbol": input_data.symbol, "error": str(e)
            }})
            return EVFilterResult(
                passed=False, ev=0.0, expected_profit=0.0,
                expected_loss=0.0, transaction_cost=0.0,
                reason=msg, recommendation="SKIP",
                confidence_adjusted=0.0,
                symbol=input_data.symbol, error=msg
            )

    def _generate_recommendation(self, ev: float, passed: bool,
                                  risk_reward: float, confidence: float) -> Tuple[str, str]:
        if not passed:
            if ev < 0:
                return "SKIP", f"Negative EV ({ev:.4f}), trade rejected"
            else:
                return "SKIP", f"Insufficient EV ({ev:.4f} < min_ev={self.min_ev}), trade rejected"

        if ev > 0.001 and risk_reward > 3.0 and confidence > 0.75:
            return "STRONG_BUY", f"High quality (EV={ev:.4f}, R:R={risk_reward:.2f}, conf={confidence:.2f})"
        elif ev > 0.0007 and risk_reward > 2.0 and confidence > 0.65:
            return "BUY", f"Good trade (EV={ev:.4f}, R:R={risk_reward:.2f}, conf={confidence:.2f})"
        else:
            return "HOLD", f"Marginal pass (EV={ev:.4f}), consider waiting"

    def _adjust_confidence(self, original_confidence: float,
                           ev: float, passed: bool) -> float:
        if not passed:
            return 0.0
        if ev > 0.001:
            return min(0.95, original_confidence * 1.1)
        elif ev > 0.0007:
            return min(0.85, original_confidence * 1.05)
        else:
            return max(0.5, original_confidence * 0.95)

    def batch_filter(self, inputs: List[EVFilterInput]) -> List[EVFilterResult]:
        """
        批量过滤(单条异常不影响其他)

        Args:
            inputs: 输入列表

        Returns:
            结果列表(与输入一一对应)
        """
        results = []
        passed_count = 0
        rejected_count = 0

        for input_data in inputs:
            try:
                result = self.calculate_ev(input_data)
                results.append(result)
                if result.passed:
                    passed_count += 1
                else:
                    rejected_count += 1
            except Exception as e:
                # calculate_ev内部已有try-except,此处为最终兜底
                logger.error("batch_filter unexpected error", extra={"extra_data": {
                    "symbol": input_data.symbol, "error": str(e)
                }})
                results.append(EVFilterResult(
                    passed=False, ev=0.0, expected_profit=0.0,
                    expected_loss=0.0, transaction_cost=0.0,
                    reason=f"batch_filter error: {e}", recommendation="SKIP",
                    confidence_adjusted=0.0,
                    symbol=input_data.symbol, error=str(e)
                ))
                rejected_count += 1

        # 广播signal.filtered事件（Phase 5.6新增）
        if EVENT_BUS_AVAILABLE:
            self._publish_signal_filtered_event(results, passed_count, rejected_count)

        return results

    def _publish_signal_filtered_event(self, results: List[EVFilterResult], passed_count: int, rejected_count: int):
        """
        广播信号过滤事件（Phase 5.6新增）

        Args:
            results: 过滤结果列表
            passed_count: 通过数量
            rejected_count: 拒绝数量
        """
        try:
            event_bus = get_event_bus()

            # 统计通过和拒绝的信号
            passed_signals = [r for r in results if r.passed]
            rejected_signals = [r for r in results if not r.passed]

            event_bus.publish(
                "signal.filtered",
                {
                    "total_signals": len(results),
                    "passed_count": passed_count,
                    "rejected_count": rejected_count,
                    "pass_rate": f"{passed_count/len(results)*100:.1f}%" if results else "0%",
                    "min_ev_threshold": self.min_ev,
                    "passed_signals": [
                        {"symbol": r.symbol, "ev": r.ev, "expected_profit": r.expected_profit}
                        for r in passed_signals[:10]  # 最多显示10个
                    ],
                    "rejected_signals": [
                        {"symbol": r.symbol, "ev": r.ev, "reason": r.reason}
                        for r in rejected_signals[:10]  # 最多显示10个
                    ]
                },
                source="ev_filter"
            )
            logger.debug(f"信号过滤事件已广播: {passed_count}/{len(results)}通过")
        except Exception as e:
            logger.error(f"信号过滤事件广播失败: {e}")

    def get_stats(self) -> Dict:
        if self.stats['total_checks'] == 0:
            return self.stats
        return {
            **self.stats,
            'pass_rate': self.stats['total_passed'] / self.stats['total_checks'],
            'error_rate': self.stats['total_errors'] / self.stats['total_checks'],
            'high_quality_rate': (
                self.stats['high_quality_trades'] / self.stats['total_passed']
                if self.stats['total_passed'] > 0 else 0
            )
        }

    def reset_stats(self):
        self.stats = {
            'total_checks': 0, 'total_passed': 0,
            'total_rejected': 0, 'total_errors': 0,
            'avg_ev': 0.0, 'high_quality_trades': 0
        }


def main():
    parser = argparse.ArgumentParser(description="EV过滤模块 V6.3")
    parser.add_argument('--symbol', type=str, default='BTCUSDT')
    parser.add_argument('--direction', type=str, default='LONG', choices=['LONG', 'SHORT'])
    parser.add_argument('--confidence', type=float, required=True)
    parser.add_argument('--entry_price', type=float, required=True)
    parser.add_argument('--tp_price', type=float, required=True)
    parser.add_argument('--sl_price', type=float, required=True)
    parser.add_argument('--min_ev', type=float, default=0.00035)
    args = parser.parse_args()

    config = {'min_ev': args.min_ev}
    ev_filter = EVFilter(config)

    input_data = EVFilterInput(
        symbol=args.symbol,
        direction=TradeDirection(args.direction),
        confidence=args.confidence,
        entry_price=args.entry_price,
        tp_price=args.tp_price,
        sl_price=args.sl_price
    )

    result = ev_filter.calculate_ev(input_data)

    output = {
        'input': input_data.to_dict(),
        'result': result.to_dict(),
        'stats': ev_filter.get_stats()
    }
    logger.info(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
