#!/usr/bin/env python3
"""
风控-总控联动桥 — 杀手锏交易系统 v1.0.3
解决风控与总控割裂: VaR/GARCH计算结果仅用于被动止损,不改变系统全局行为

核心设计:
1. RiskSignal — 风控信号分类(VaR超限/波动率飙升/流动性枯竭/资金费率异常)
2. RiskControllerLinkage — 预测→行为映射协议
   - GARCH预测波动率>2σ → 提议DEGRADED
   - VaR预算耗尽>80% → 提议DEGRADED
   - 波动率>3σ+VaR耗尽 → 提议SOFT_BREAKER
3. 风控模块拥有状态变更提议权(非直接执行权),总控中心评估后执行
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("risk_linkage")
except ImportError:
    import logging
    logger = logging.getLogger("risk_linkage")


# ============================================================
# 1. 风控信号定义
# ============================================================

class RiskSignalType(Enum):
    VAR_BREACH = "VAR_BREACH"                   # VaR超限
    VOLATILITY_SPIKE = "VOLATILITY_SPIKE"       # 波动率飙升
    LIQUIDITY_DRY = "LIQUIDITY_DRY"             # 流动性枯竭
    FUNDING_RATE_ANOMALY = "FUNDING_RATE_ANOMALY" # 资金费率异常
    CORRELATION_BREAK = "CORRELATION_BREAK"     # 相关性断裂(对冲失效)
    DRAWDOWN_ACCEL = "DRAWDOWN_ACCEL"           # 回撤加速


class ProposedAction(Enum):
    """提议的系统行为变更"""
    NONE = "NONE"                   # 无需变更
    REDUCE_POSITION = "REDUCE"      # 减仓
    DEGRADED = "DEGRADED"           # 降级(仅评估不开仓)
    SOFT_BREAKER = "SOFT_BREAKER"   # 软熔断
    HARD_BREAKER = "HARD_BREAKER"   # 硬熔断


@dataclass
class RiskSignal:
    """风控信号"""
    signal_type: RiskSignalType
    severity: float          # 0.0-1.0 严重程度
    metric_value: float      # 原始指标值
    threshold: float         # 阈值
    description: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# ============================================================
# 2. 预测→行为映射协议
# ============================================================

# 映射规则: (信号类型, 严重程度范围) → 提议行为
_MAPPING_RULES: List[Tuple[RiskSignalType, float, float, ProposedAction]] = [
    # VaR超限
    (RiskSignalType.VAR_BREACH, 0.0, 0.5, ProposedAction.REDUCE_POSITION),
    (RiskSignalType.VAR_BREACH, 0.5, 0.8, ProposedAction.DEGRADED),
    (RiskSignalType.VAR_BREACH, 0.8, 1.0, ProposedAction.SOFT_BREAKER),
    # 波动率飙升
    (RiskSignalType.VOLATILITY_SPIKE, 0.0, 0.5, ProposedAction.REDUCE_POSITION),
    (RiskSignalType.VOLATILITY_SPIKE, 0.5, 0.8, ProposedAction.DEGRADED),
    (RiskSignalType.VOLATILITY_SPIKE, 0.8, 1.0, ProposedAction.SOFT_BREAKER),
    # 流动性枯竭
    (RiskSignalType.LIQUIDITY_DRY, 0.0, 0.5, ProposedAction.REDUCE_POSITION),
    (RiskSignalType.LIQUIDITY_DRY, 0.5, 1.0, ProposedAction.DEGRADED),
    # 资金费率异常
    (RiskSignalType.FUNDING_RATE_ANOMALY, 0.0, 0.7, ProposedAction.REDUCE_POSITION),
    (RiskSignalType.FUNDING_RATE_ANOMALY, 0.7, 1.0, ProposedAction.DEGRADED),
    # 相关性断裂
    (RiskSignalType.CORRELATION_BREAK, 0.0, 0.5, ProposedAction.REDUCE_POSITION),
    (RiskSignalType.CORRELATION_BREAK, 0.5, 1.0, ProposedAction.DEGRADED),
    # 回撤加速
    (RiskSignalType.DRAWDOWN_ACCEL, 0.0, 0.5, ProposedAction.REDUCE_POSITION),
    (RiskSignalType.DRAWDOWN_ACCEL, 0.5, 0.8, ProposedAction.SOFT_BREAKER),
    (RiskSignalType.DRAWDOWN_ACCEL, 0.8, 1.0, ProposedAction.HARD_BREAKER),
]


# ============================================================
# 3. 风控联动桥
# ============================================================

@dataclass
class LinkageProposal:
    """状态变更提议"""
    proposed_action: ProposedAction
    signals: List[RiskSignal]
    confidence: float         # 提议置信度(多信号一致时更高)
    reason: str
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> Dict:
        return {
            "action": self.proposed_action.value,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "signals": [
                {"type": s.signal_type.value, "severity": round(s.severity, 3),
                 "value": s.metric_value, "threshold": s.threshold}
                for s in self.signals
            ],
            "timestamp": self.timestamp,
        }


class RiskControllerLinkage:
    """
    风控-总控联动桥

    核心原则: 风控模块拥有状态变更提议权,非直接执行权。
    总控中心评估提议后执行,审计日志记录完整决策链。

    工作流程:
    1. 风控模块发出RiskSignal
    2. Linkage评估信号,生成LinkageProposal
    3. Proposal提交给总控中心(通过回调)
    4. 总控中心评估后决定是否执行状态变更
    5. 决策过程写入审计日志

    预测→行为映射示例:
    | GARCH波动率 | VaR预算使用 | 自动命令 |
    |------------|-----------|---------|
    | >2σ        | >80%      | DEGRADED |
    | >3σ        | >100%     | SOFT_BREAKER |
    | 闪崩检测    | 任意       | HARD_BREAKER |
    """

    def __init__(self):
        self._pending_signals: List[RiskSignal] = []
        self._proposal_history: List[LinkageProposal] = []
        self._action_callback: Optional[Callable] = None
        self._suppression_counts: Dict[ProposedAction, int] = {a: 0 for a in ProposedAction}

    def set_action_callback(self, callback: Callable):
        """
        设置状态变更回调(连接GlobalState)。

        Args:
            callback: async callback(action: ProposedAction, reason: str)
        """
        self._action_callback = callback

    def emit_signal(self, signal_type: RiskSignalType,
                    severity: float, metric_value: float,
                    threshold: float, description: str = "") -> None:
        """
        风控模块发出信号。

        Args:
            signal_type: 信号类型
            severity: 严重程度(0.0-1.0)
            metric_value: 原始指标值
            threshold: 阈值
            description: 描述
        """
        signal = RiskSignal(
            signal_type=signal_type, severity=min(max(severity, 0.0), 1.0),
            metric_value=metric_value, threshold=threshold,
            description=description
        )
        self._pending_signals.append(signal)

        logger.info("Risk signal emitted", extra={"extra_data": {
            "type": signal.signal_type.value,
            "severity": round(signal.severity, 3),
            "value": signal.metric_value,
            "threshold": signal.threshold,
        }})

    def evaluate(self) -> Optional[LinkageProposal]:
        """
        评估当前所有待处理信号,生成最高优先级提议。

        Returns:
            LinkageProposal 或 None(无需要变更)
        """
        if not self._pending_signals:
            return None

        # 对每个信号查找匹配的映射规则
        proposals: Dict[ProposedAction, List[RiskSignal]] = {}
        for signal in self._pending_signals:
            for sig_type, sev_low, sev_high, action in _MAPPING_RULES:
                if signal.signal_type == sig_type and sev_low <= signal.severity < sev_high:
                    proposals.setdefault(action, []).append(signal)
                    break

        self._pending_signals.clear()

        if not proposals:
            return None

        # 选择最高优先级的提议
        priority_order = [
            ProposedAction.HARD_BREAKER, ProposedAction.SOFT_BREAKER,
            ProposedAction.DEGRADED, ProposedAction.REDUCE_POSITION,
        ]
        best_action = ProposedAction.NONE
        best_signals = []

        for action in priority_order:
            if action in proposals:
                best_action = action
                best_signals = proposals[action]
                break

        if best_action == ProposedAction.NONE:
            return None

        # 计算提议置信度(多信号一致时更高)
        signal_count = len(best_signals)
        avg_severity = sum(s.severity for s in best_signals) / signal_count
        confidence = min(0.5 + 0.2 * (signal_count - 1) + 0.3 * avg_severity, 1.0)

        reason_parts = [f"{s.signal_type.value}(sev={s.severity:.2f})" for s in best_signals]
        reason = f"Risk linkage: {' + '.join(reason_parts)}"

        proposal = LinkageProposal(
            proposed_action=best_action,
            signals=best_signals,
            confidence=confidence,
            reason=reason,
        )
        self._proposal_history.append(proposal)
        self._suppression_counts[best_action] += 1

        logger.warning("Linkage proposal generated", extra={"extra_data": proposal.to_dict()})

        return proposal

    async def evaluate_and_propose(self) -> Optional[LinkageProposal]:
        """
        评估信号并提交提议(含回调)。

        Returns:
            LinkageProposal
        """
        proposal = self.evaluate()
        if proposal and self._action_callback:
            try:
                await self._action_callback(proposal.proposed_action, proposal.reason)
                logger.info("Proposal submitted to controller", extra={"extra_data": {
                    "action": proposal.proposed_action.value
                }})
            except Exception as e:
                logger.error("Proposal callback failed", extra={"extra_data": {"error": str(e)}})
        return proposal

    # ---------- 便捷方法: 常用风控信号快速发射 ----------

    def check_garch_volatility(self, predicted_vol: float,
                                historical_mean: float,
                                historical_std: float) -> None:
        """
        GARCH波动率预测检查。

        Args:
            predicted_vol: GARCH预测波动率
            historical_mean: 历史均值
            historical_std: 历史标准差
        """
        if historical_std is None or abs(historical_std) < 1e-10:
            return
        sigma = (predicted_vol - historical_mean) / historical_std

        if sigma > 3:
            self.emit_signal(RiskSignalType.VOLATILITY_SPIKE,
                           severity=min(sigma / 5, 1.0),
                           metric_value=predicted_vol,
                           threshold=historical_mean + 3 * historical_std,
                           description=f"GARCH vol {predicted_vol:.6f} > 3σ ({sigma:.1f}σ)")
        elif sigma > 2:
            self.emit_signal(RiskSignalType.VOLATILITY_SPIKE,
                           severity=min(sigma / 5, 1.0),
                           metric_value=predicted_vol,
                           threshold=historical_mean + 2 * historical_std,
                           description=f"GARCH vol {predicted_vol:.6f} > 2σ ({sigma:.1f}σ)")

    def check_var_usage(self, current_var: float, var_budget: float) -> None:
        """
        VaR预算使用率检查。

        Args:
            current_var: 当前VaR
            var_budget: VaR预算
        """
        if var_budget <= 0:
            return
        usage = current_var / var_budget

        if usage > 1.0:
            self.emit_signal(RiskSignalType.VAR_BREACH,
                           severity=min(usage / 1.5, 1.0),
                           metric_value=current_var,
                           threshold=var_budget,
                           description=f"VaR budget exhausted: {usage:.1%}")
        elif usage > 0.8:
            self.emit_signal(RiskSignalType.VAR_BREACH,
                           severity=usage,
                           metric_value=current_var,
                           threshold=var_budget * 0.8,
                           description=f"VaR budget >80%: {usage:.1%}")

    def check_drawdown_acceleration(self, drawdown_pct: float,
                                     drawdown_velocity: float) -> None:
        """
        回撤加速检查。

        Args:
            drawdown_pct: 当前回撤百分比
            drawdown_velocity: 回撤速率(百分比/分钟)
        """
        if drawdown_pct > 0.08:
            severity = min(drawdown_pct / 0.15, 1.0)
            self.emit_signal(RiskSignalType.DRAWDOWN_ACCEL,
                           severity=severity,
                           metric_value=drawdown_pct,
                           threshold=0.08,
                           description=f"Drawdown {drawdown_pct:.2%}, velocity {drawdown_velocity:.4f}/min")

    def get_stats(self) -> Dict:
        """获取联动桥统计"""
        return {
            "pending_signals": len(self._pending_signals),
            "total_proposals": len(self._proposal_history),
            "suppression_counts": {a.value: c for a, c in self._suppression_counts.items()},
            "recent_proposals": [p.to_dict() for p in self._proposal_history[-10:]],
        }


# ============================================================
# 命令行接口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="风控-总控联动桥")
    parser.add_argument("--garch-vol", type=float, default=None, help="GARCH预测波动率")
    parser.add_argument("--hist-mean", type=float, default=0.01, help="历史波动率均值")
    parser.add_argument("--hist-std", type=float, default=0.005, help="历史波动率标准差")
    parser.add_argument("--var-current", type=float, default=None, help="当前VaR")
    parser.add_argument("--var-budget", type=float, default=None, help="VaR预算")
    parser.add_argument("--drawdown", type=float, default=None, help="当前回撤百分比")
    parser.add_argument("--drawdown-vel", type=float, default=0, help="回撤速率")
    parser.add_argument("--stats", action="store_true", help="输出统计")
    args = parser.parse_args()

    linkage = RiskControllerLinkage()

    # 发射信号
    if args.garch_vol is not None:
        linkage.check_garch_volatility(args.garch_vol, args.hist_mean, args.hist_std)

    if args.var_current is not None and args.var_budget is not None:
        linkage.check_var_usage(args.var_current, args.var_budget)

    if args.drawdown is not None:
        linkage.check_drawdown_acceleration(args.drawdown, args.drawdown_vel)

    # 评估
    proposal = linkage.evaluate()

    result = {"signals_emitted": len(linkage._pending_signals) + (1 if proposal else 0)}

    if proposal:
        result["proposal"] = proposal.to_dict()
    else:
        result["proposal"] = None
        result["message"] = "No state change proposed"

    if args.stats:
        result["stats"] = linkage.get_stats()

    logger.info(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
