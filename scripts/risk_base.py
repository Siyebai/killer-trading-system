#!/usr/bin/env python3
"""
风控基类和风险级别定义
提供风控规则的基础框架
"""

from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass


class RiskLevel(Enum):
    """风险级别"""
    INFO = "INFO"           # 信息级
    WARNING = "WARNING"     # 警告级
    HIGH = "HIGH"           # 高风险
    CRITICAL = "CRITICAL"   # 严重风险


@dataclass
class RiskResult:
    """风控检查结果"""
    passed: bool            # 是否通过
    level: RiskLevel        # 风险级别
    message: str            # 检查消息
    details: Dict[str, Any] # 详细信息

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "passed": self.passed,
            "level": self.level.value,
            "message": self.message,
            "details": self.details
        }


class RiskRule:
    """风控规则基类"""

    def __init__(self, name: str, description: str = ""):
        """
        初始化风控规则

        Args:
            name: 规则名称
            description: 规则描述
        """
        self.name = name
        self.description = description

    def check(self, context: Dict[str, Any]) -> RiskResult:
        """
        执行风控检查

        Args:
            context: 检查上下文（包含订单、账户、市场等信息）

        Returns:
            RiskResult: 检查结果
        """
        raise NotImplementedError("子类必须实现check方法")

    def __repr__(self):
        return f"RiskRule(name={self.name})"


class PositionLimitRule(RiskRule):
    """仓位限制规则"""

    def __init__(self, max_position_ratio: float = 0.5):
        """
        初始化仓位限制规则

        Args:
            max_position_ratio: 最大仓位比例（默认50%）
        """
        super().__init__(
            name="position_limit",
            description=f"限制单仓位不超过{max_position_ratio*100}%"
        )
        self.max_position_ratio = max_position_ratio

    def check(self, context: Dict[str, Any]) -> RiskResult:
        """检查仓位限制"""
        # 获取当前仓位和限制
        current_position = context.get("current_position", 0)
        total_capital = context.get("total_capital", 100000)
        max_position = total_capital * self.max_position_ratio

        if current_position <= max_position:
            return RiskResult(
                passed=True,
                level=RiskLevel.INFO,
                message=f"仓位符合限制: {current_position}/{max_position}",
                details={"current": current_position, "max": max_position}
            )
        else:
            return RiskResult(
                passed=False,
                level=RiskLevel.HIGH,
                message=f"仓位超限: {current_position}/{max_position}",
                details={"current": current_position, "max": max_position}
            )


class DrawdownLimitRule(RiskRule):
    """回撤限制规则"""

    def __init__(self, max_drawdown_ratio: float = 0.20):
        """
        初始化回撤限制规则

        Args:
            max_drawdown_ratio: 最大回撤比例（默认20%）
        """
        super().__init__(
            name="drawdown_limit",
            description=f"限制最大回撤不超过{max_drawdown_ratio*100}%"
        )
        self.max_drawdown_ratio = max_drawdown_ratio

    def check(self, context: Dict[str, Any]) -> RiskResult:
        """检查回撤限制"""
        current_drawdown = context.get("current_drawdown", 0)

        if current_drawdown <= self.max_drawdown_ratio:
            return RiskResult(
                passed=True,
                level=RiskLevel.INFO,
                message=f"回撤符合限制: {current_drawdown:.2%}/{self.max_drawdown_ratio:.2%}",
                details={"current": current_drawdown, "max": self.max_drawdown_ratio}
            )
        elif current_drawdown <= self.max_drawdown_ratio * 0.8:
            return RiskResult(
                passed=False,
                level=RiskLevel.HIGH,
                message=f"回撤逼近限制: {current_drawdown:.2%}",
                details={"current": current_drawdown, "max": self.max_drawdown_ratio}
            )
        else:
            return RiskResult(
                passed=False,
                level=RiskLevel.CRITICAL,
                message=f"回撤突破限制: {current_drawdown:.2%}",
                details={"current": current_drawdown, "max": self.max_drawdown_ratio}
            )


class DailyLossLimitRule(RiskRule):
    """日亏损限制规则"""

    def __init__(self, max_daily_loss_ratio: float = 0.05):
        """
        初始化日亏损限制规则

        Args:
            max_daily_loss_ratio: 最大日亏损比例（默认5%）
        """
        super().__init__(
            name="daily_loss_limit",
            description=f"限制日亏损不超过{max_daily_loss_ratio*100}%"
        )
        self.max_daily_loss_ratio = max_daily_loss_ratio

    def check(self, context: Dict[str, Any]) -> RiskResult:
        """检查日亏损限制"""
        daily_pnl = context.get("daily_pnl", 0)
        total_capital = context.get("total_capital", 100000)
        daily_loss_ratio = abs(daily_pnl) / total_capital if daily_pnl < 0 else 0

        if daily_loss_ratio <= self.max_daily_loss_ratio:
            return RiskResult(
                passed=True,
                level=RiskLevel.INFO,
                message=f"日亏损符合限制: {daily_loss_ratio:.2%}",
                details={"daily_pnl": daily_pnl, "max_ratio": self.max_daily_loss_ratio}
            )
        else:
            return RiskResult(
                passed=False,
                level=RiskLevel.CRITICAL,
                message=f"日亏损超限: {daily_loss_ratio:.2%}",
                details={"daily_pnl": daily_pnl, "max_ratio": self.max_daily_loss_ratio}
            )


class RiskRatioRule(RiskRule):
    """风险比率规则"""

    def __init__(self, max_risk_ratio: float = 0.10):
        """
        初始化风险比率规则

        Args:
            max_risk_ratio: 最大风险比率（默认10%）
        """
        super().__init__(
            name="risk_ratio",
            description=f"限制单笔交易风险不超过{max_risk_ratio*100}%"
        )
        self.max_risk_ratio = max_risk_ratio

    def check(self, context: Dict[str, Any]) -> RiskResult:
        """检查风险比率"""
        position_value = context.get("position_value", 0)
        total_capital = context.get("total_capital", 100000)
        risk_ratio = position_value / total_capital

        if risk_ratio <= self.max_risk_ratio:
            return RiskResult(
                passed=True,
                level=RiskLevel.INFO,
                message=f"风险比率符合限制: {risk_ratio:.2%}",
                details={"risk_ratio": risk_ratio, "max": self.max_risk_ratio}
            )
        else:
            return RiskResult(
                passed=False,
                level=RiskLevel.HIGH,
                message=f"风险比率超限: {risk_ratio:.2%}",
                details={"risk_ratio": risk_ratio, "max": self.max_risk_ratio}
            )


# 预定义规则集合
PREDEFINED_RULES = {
    "position_limit": PositionLimitRule,
    "drawdown_limit": DrawdownLimitRule,
    "daily_loss_limit": DailyLossLimitRule,
    "risk_ratio": RiskRatioRule,
}


def create_rule(rule_name: str, **kwargs) -> RiskRule:
    """
    创建风控规则

    Args:
        rule_name: 规则名称
        **kwargs: 规则参数

    Returns:
        RiskRule: 风控规则实例
    """
    if rule_name not in PREDEFINED_RULES:
        raise ValueError(f"未知的规则名称: {rule_name}")

    return PREDEFINED_RULES[rule_name](**kwargs)


if __name__ == "__main__":
    # 测试风控规则
    context = {
        "current_position": 30000,
        "total_capital": 100000,
        "current_drawdown": 0.15,
        "daily_pnl": -3000,
    }

    rule1 = PositionLimitRule(max_position_ratio=0.5)
    result1 = rule1.check(context)
    print(f"仓位限制检查: {result1.to_dict()}")

    rule2 = DrawdownLimitRule(max_drawdown_ratio=0.20)
    result2 = rule2.check(context)
    print(f"回撤限制检查: {result2.to_dict()}")

    rule3 = DailyLossLimitRule(max_daily_loss_ratio=0.05)
    result3 = rule3.check(context)
    print(f"日亏损限制检查: {result3.to_dict()}")
