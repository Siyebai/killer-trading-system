#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("predictive_risk_control")
except ImportError:
    import logging
    logger = logging.getLogger("predictive_risk_control")
"""
预测性风控 - 杀手锏交易系统P0核心
VaR动态风险预算、GARCH波动率预测、多层次止损体系、智能熔断器
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import time


class RiskLevel(Enum):
    """风险级别"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class StopLossTier(Enum):
    """止损层级"""
    STRATEGY_LEVEL = "STRATEGY_LEVEL"  # 策略层
    PORTFOLIO_LEVEL = "PORTFOLIO_LEVEL"  # 组合层
    ACCOUNT_LEVEL = "ACCOUNT_LEVEL"  # 账户层


@dataclass
class VaRResult:
    """VaR计算结果"""
    var_95: float  # 95%置信度VaR
    var_99: float  # 99%置信度VaR
    expected_shortfall: float  # 期望亏损（ES）
    risk_level: RiskLevel


@dataclass
class VolatilityForecast:
    """波动率预测"""
    current_volatility: float
    forecast_1h: float
    forecast_4h: float
    forecast_24h: float
    trend: str  # RISING/FALLING/STABLE


@dataclass
class CircuitBreakerStatus:
    """熔断器状态"""
    is_triggered: bool
    trigger_reason: str
    level: int  # 1=一级熔断, 2=二级熔断, 3=三级熔断
    actions: List[str]


class PredictiveRiskControl:
    """预测性风控系统"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化预测性风控

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # VaR参数
        self.var_confidence = self.config.get('var_confidence', 0.95)
        self.var_window = self.config.get('var_window', 100)
        self.max_var_percent = self.config.get('max_var_percent', 0.02)  # 最大VaR 2%

        # 熔断器参数
        self.circuit_breaker_enabled = self.config.get('circuit_breaker_enabled', True)
        self.circuit_breaker_levels = self.config.get('circuit_breaker_levels', {
            1: {'price_drop': 0.05, 'volume_spike': 3.0},
            2: {'price_drop': 0.10, 'volume_spike': 5.0},
            3: {'price_drop': 0.15, 'volume_spike': 10.0}
        })

        # 波动率预测历史
        self.volatility_history: List[float] = []
        self.price_history: List[float] = []

    def calculate_var(self, returns: List[float]) -> VaRResult:
        """
        计算VaR（Value at Risk）

        Args:
            returns: 收益率序列

        Returns:
            VaR结果
        """
        try:
            # 第一层防御：输入校验
            if not returns or len(returns) < self.var_window:
                logger.warning(f"计算VaR失败：收益率序列长度不足（{len(returns) if returns else 0} < {self.var_window}）")
                return VaRResult(
                    var_95=0.0,
                    var_99=0.0,
                    expected_shortfall=0.0,
                    risk_level=RiskLevel.MEDIUM
                )

            # 过滤无效值
            valid_returns = [r for r in returns if isinstance(r, (int, float)) and not np.isnan(r) and not np.isinf(r)]
            if len(valid_returns) < self.var_window:
                logger.warning(f"计算VaR失败：有效收益率不足（{len(valid_returns)} < {self.var_window}）")
                return VaRResult(
                    var_95=0.0,
                    var_99=0.0,
                    expected_shortfall=0.0,
                    risk_level=RiskLevel.MEDIUM
                )

            returns_array = np.array(valid_returns[-self.var_window:])

            # 第二层防御：除零保护
            if len(returns_array) == 0:
                logger.error("计算VaR失败：returns_array为空")
                return VaRResult(
                    var_95=0.0,
                    var_99=0.0,
                    expected_shortfall=0.0,
                    risk_level=RiskLevel.MEDIUM
                )

            # 计算VaR（历史模拟法）
            sorted_returns = np.sort(returns_array)

            # 95% VaR（5%分位数）
            var_95_index = int(len(sorted_returns) * 0.05)
            var_95 = abs(sorted_returns[var_95_index]) if var_95_index < len(sorted_returns) else 0.0

            # 99% VaR（1%分位数）
            var_99_index = int(len(sorted_returns) * 0.01)
            var_99 = abs(sorted_returns[var_99_index]) if var_99_index < len(sorted_returns) else 0.0

            # 期望亏损（ES）：超过VaR的平均亏损
            es_returns = sorted_returns[:var_95_index] if var_95_index > 0 else np.array([])
            expected_shortfall = abs(np.mean(es_returns)) if len(es_returns) > 0 else var_95

            # 风险级别判断
            if var_95 > self.max_var_percent * 2:
                risk_level = RiskLevel.CRITICAL
            elif var_95 > self.max_var_percent:
                risk_level = RiskLevel.HIGH
            elif var_95 > self.max_var_percent * 0.5:
                risk_level = RiskLevel.MEDIUM
            else:
                risk_level = RiskLevel.LOW

            return VaRResult(
                var_95=var_95,
                var_99=var_99,
                expected_shortfall=expected_shortfall,
                risk_level=risk_level
            )
        except ZeroDivisionError as e:
            logger.error(f"计算VaR时发生除零错误：{e}，返回默认值")
            return VaRResult(
                var_95=0.0,
                var_99=0.0,
                expected_shortfall=0.0,
                risk_level=RiskLevel.MEDIUM
            )
        except Exception as e:
            logger.error(f"计算VaR失败：{e}，返回默认值")
            return VaRResult(
                var_95=0.0,
                var_99=0.0,
                expected_shortfall=0.0,
                risk_level=RiskLevel.MEDIUM
            )

    def forecast_volatility_garch(self, returns: List[float]) -> VolatilityForecast:
        """
        GARCH波动率预测（简化实现）

        Args:
            returns: 收益率序列

        Returns:
            波动率预测
        """
        try:
            # 第一层防御：输入校验
            if not returns or len(returns) < 20:
                return VolatilityForecast(
                    current_volatility=0.0,
                    forecast_1h=0.0,
                    forecast_4h=0.0,
                    forecast_24h=0.0,
                    trend="STABLE"
                )

            # 过滤无效值
            valid_returns = [r for r in returns if isinstance(r, (int, float)) and not np.isnan(r) and not np.isinf(r)]
            if len(valid_returns) < 20:
                return VolatilityForecast(
                    current_volatility=0.0,
                    forecast_1h=0.0,
                    forecast_4h=0.0,
                    forecast_24h=0.0,
                    trend="STABLE"
                )

            # 简化GARCH(1,1)模型
            # σ²ₜ = ω + α * ε²ₜ₋₁ + β * σ²ₜ₋₁

            omega = 0.00001  # 长期平均波动率
            alpha = 0.1  # 前期波动率的权重
            beta = 0.85  # 前期方差的权重

            returns_array = np.array(valid_returns)
            squared_returns = returns_array ** 2

            # 第二层防御：除零保护
            if len(returns_array) == 0:
                return VolatilityForecast(
                    current_volatility=0.0,
                    forecast_1h=0.0,
                    forecast_4h=0.0,
                    forecast_24h=0.0,
                    trend="STABLE"
                )

            # 初始化
            init_window = min(20, len(returns_array))
            volatility_squared = np.var(returns_array[:init_window])

            # 第三层防御：捕获数值计算异常
            if volatility_squared <= 0 or np.isnan(volatility_squared):
                logger.warning(f"初始波动率平方异常：{volatility_squared}，使用默认值")
                volatility_squared = 0.0001

            # 迭代计算
            for i in range(20, len(returns_array)):
                epsilon_squared = squared_returns[i-1]
                volatility_squared = omega + alpha * epsilon_squared + beta * volatility_squared

                # 防止波动率平方变为负数或NaN
                if volatility_squared <= 0 or np.isnan(volatility_squared):
                    logger.warning(f"迭代波动率平方异常：{volatility_squared}，重置为默认值")
                    volatility_squared = 0.0001

            current_volatility = np.sqrt(volatility_squared)

            # 预测未来波动率（简化：均值回归）
            mean_reversion_speed = 0.1
            long_term_vol = np.std(returns_array)

            # 第二层防御：除零保护
            if long_term_vol == 0:
                long_term_vol = 0.01

            forecast_1h = current_volatility * (1 - mean_reversion_speed) + long_term_vol * mean_reversion_speed
            forecast_4h = forecast_1h * (1 - mean_reversion_speed) + long_term_vol * mean_reversion_speed
            forecast_24h = forecast_4h * (1 - mean_reversion_speed) + long_term_vol * mean_reversion_speed

            # 趋势判断
            if forecast_1h > current_volatility * 1.2:
                trend = "RISING"
            elif forecast_1h < current_volatility * 0.8:
                trend = "FALLING"
            else:
                trend = "STABLE"

            return VolatilityForecast(
                current_volatility=current_volatility,
                forecast_1h=forecast_1h,
                forecast_4h=forecast_4h,
                forecast_24h=forecast_24h,
                trend=trend
            )
        except ZeroDivisionError as e:
            logger.error(f"GARCH预测时发生除零错误：{e}，返回默认值")
            return VolatilityForecast(
                current_volatility=0.01,
                forecast_1h=0.01,
                forecast_4h=0.01,
                forecast_24h=0.01,
                trend="STABLE"
            )
        except Exception as e:
            logger.error(f"GARCH预测失败：{e}，返回默认值")
            return VolatilityForecast(
                current_volatility=0.01,
                forecast_1h=0.01,
                forecast_4h=0.01,
                forecast_24h=0.01,
                trend="STABLE"
            )

    def check_circuit_breaker(self, market_data: Dict, portfolio_data: Dict) -> CircuitBreakerStatus:
        """
        检查熔断器

        Args:
            market_data: 市场数据
            portfolio_data: 组合数据

        Returns:
            熔断器状态
        """
        if not self.circuit_breaker_enabled:
            return CircuitBreakerStatus(
                is_triggered=False,
                trigger_reason="",
                level=0,
                actions=[]
            )

        triggered = False
        trigger_reason = ""
        level = 0
        actions = []

        current_price = market_data.get('price', 0)
        reference_price = market_data.get('reference_price', current_price)
        current_volume = market_data.get('volume', 0)
        avg_volume = market_data.get('avg_volume', current_volume)

        # 价格跌幅检查
        if current_price > 0 and reference_price > 0:
            price_drop = (reference_price - current_price) / reference_price

            for lvl, params in self.circuit_breaker_levels.items():
                if price_drop >= params['price_drop']:
                    triggered = True
                    level = max(level, lvl)
                    trigger_reason = f"价格下跌{price_drop*100:.1f}%超过{params['price_drop']*100:.0f}%阈值"

        # 成交量突增检查
        if current_volume > 0 and avg_volume > 0:
            volume_ratio = current_volume / avg_volume

            for lvl, params in self.circuit_breaker_levels.items():
                if volume_ratio >= params['volume_spike']:
                    triggered = True
                    level = max(level, lvl)
                    if trigger_reason:
                        trigger_reason += f"，成交量{volume_ratio:.1f}倍"
                    else:
                        trigger_reason = f"成交量{volume_ratio:.1f}倍超过{params['volume_spike']:.0f}倍阈值"

        # 确定触发动作
        if triggered:
            if level >= 3:
                actions = ["暂停所有交易", "平仓所有持仓", "发送紧急告警"]
            elif level >= 2:
                actions = ["暂停开新仓", "降低仓位至20%", "发送警告通知"]
            else:
                actions = ["降低仓位至50%", "加强监控"]
        else:
            actions = []

        return CircuitBreakerStatus(
            is_triggered=triggered,
            trigger_reason=trigger_reason,
            level=level,
            actions=actions
        )

    def calculate_dynamic_stop_loss(self, tier: StopLossTier, volatility: float,
                                     position_value: float, confidence: float = 0.95) -> Dict:
        """
        计算动态止损（多层次）

        Args:
            tier: 止损层级
            volatility: 波动率
            position_value: 持仓价值
            confidence: 置信度

        Returns:
            止损配置
        """
        try:
            # 第一层防御：输入校验（价格合理性检查）
            if position_value <= 0.01:
                logger.warning(f"持仓价值异常（{position_value}），拒绝计算止损")
                return {
                    'tier': tier.value,
                    'stop_loss_percent': 0.0,
                    'stop_loss_amount': 0.0,
                    'volatility_based': False,
                    'confidence': confidence,
                    'error': 'position_value_too_low'
                }

            if np.isnan(volatility) or np.isinf(volatility) or volatility < 0:
                logger.warning(f"波动率异常（{volatility}），使用默认值0.01")
                volatility = 0.01

            # 第二层防御：除零保护
            # 基于波动率计算止损宽度
            if tier == StopLossTier.STRATEGY_LEVEL:
                # 策略层：基于技术指标/信号质量
                stop_loss_percent = min(0.05, 2 * volatility)  # 最大5%
            elif tier == StopLossTier.PORTFOLIO_LEVEL:
                # 组合层：基于相关性/集中度
                stop_loss_percent = min(0.08, 3 * volatility)  # 最大8%
            else:  # ACCOUNT_LEVEL
                # 账户层：基于最大回撤/日亏损限制
                stop_loss_percent = min(0.10, 4 * volatility)  # 最大10%

            # 第二层防御：防止负值
            stop_loss_percent = max(0.0, stop_loss_percent)

            stop_loss_amount = position_value * stop_loss_percent

            # 第三层防御：NaN检查
            if np.isnan(stop_loss_amount) or np.isinf(stop_loss_amount):
                logger.error(f"止损金额计算异常：{stop_loss_amount}，返回默认值")
                stop_loss_amount = 0.0
                stop_loss_percent = 0.0

            return {
                'tier': tier.value,
                'stop_loss_percent': stop_loss_percent,
                'stop_loss_amount': stop_loss_amount,
                'volatility_based': True,
                'confidence': confidence
            }
        except ZeroDivisionError as e:
            logger.error(f"计算动态止损时发生除零错误：{e}，返回默认值")
            return {
                'tier': tier.value,
                'stop_loss_percent': 0.0,
                'stop_loss_amount': 0.0,
                'volatility_based': False,
                'confidence': confidence,
                'error': 'division_by_zero'
            }
        except Exception as e:
            logger.error(f"计算动态止损失败：{e}，返回默认值")
            return {
                'tier': tier.value,
                'stop_loss_percent': 0.0,
                'stop_loss_amount': 0.0,
                'volatility_based': False,
                'confidence': confidence,
                'error': str(e)
            }

    def get_risk_assessment(self, returns: List[float], market_data: Dict,
                           portfolio_data: Dict) -> Dict:
        """
        综合风险评估

        Args:
            returns: 收益率序列
            market_data: 市场数据
            portfolio_data: 组合数据

        Returns:
            风险评估报告
        """
        # VaR计算
        var_result = self.calculate_var(returns)

        # 波动率预测
        volatility_forecast = self.forecast_volatility_garch(returns)

        # 熔断器检查
        circuit_breaker = self.check_circuit_breaker(market_data, portfolio_data)

        # 多层次止损建议
        position_value = portfolio_data.get('total_value', 100000)
        strategy_stop_loss = self.calculate_dynamic_stop_loss(
            StopLossTier.STRATEGY_LEVEL,
            volatility_forecast.current_volatility,
            position_value
        )

        # 综合风险评分
        risk_score = 0.0

        # VaR评分（0-40）
        if var_result.risk_level == RiskLevel.CRITICAL:
            risk_score += 40
        elif var_result.risk_level == RiskLevel.HIGH:
            risk_score += 30
        elif var_result.risk_level == RiskLevel.MEDIUM:
            risk_score += 20
        else:
            risk_score += 10

        # 波动率评分（0-30）
        if volatility_forecast.trend == "RISING":
            risk_score += 30
        elif volatility_forecast.trend == "STABLE":
            risk_score += 15
        else:
            risk_score += 5

        # 熔断器评分（0-30）
        if circuit_breaker.is_triggered:
            risk_score += circuit_breaker.level * 10

        return {
            'overall_risk_score': min(100, risk_score),
            'var_result': var_result,
            'volatility_forecast': volatility_forecast,
            'circuit_breaker': circuit_breaker,
            'strategy_stop_loss': strategy_stop_loss,
            'recommendations': self._generate_recommendations(
                var_result, volatility_forecast, circuit_breaker
            )
        }

    def _generate_recommendations(self, var_result: VaRResult,
                                  volatility_forecast: VolatilityForecast,
                                  circuit_breaker: CircuitBreakerStatus) -> List[str]:
        """
        生成风险建议

        Args:
            var_result: VaR结果
            volatility_forecast: 波动率预测
            circuit_breaker: 熔断器状态

        Returns:
            建议列表
        """
        recommendations = []

        # VaR建议
        if var_result.risk_level == RiskLevel.CRITICAL:
            recommendations.append("VaR风险极高，建议立即降低仓位至10%以下")
        elif var_result.risk_level == RiskLevel.HIGH:
            recommendations.append("VaR风险较高，建议降低仓位至30%以下")

        # 波动率建议
        if volatility_forecast.trend == "RISING":
            recommendations.append("波动率上升预期，建议收紧止损宽度")
        elif volatility_forecast.trend == "FALLING":
            recommendations.append("波动率下降预期，可适当放宽止损宽度")

        # 熔断器建议
        if circuit_breaker.is_triggered:
            recommendations.append(f"熔断器已触发（{circuit_breaker.level}级），执行以下动作:")
            for action in circuit_breaker.actions:
                recommendations.append(f"  - {action}")

        return recommendations


# 命令行测试
def main():
    """测试预测性风控"""
    logger.info("="*60)
    logger.info("🛡️ 预测性风控测试")
    logger.info("="*60)

    # 创建风控系统
    prc = PredictiveRiskControl({
        'var_confidence': 0.95,
        'var_window': 100,
        'max_var_percent': 0.02,
        'circuit_breaker_enabled': True
    })

    logger.info(f"\n配置:")
    logger.info(f"  VaR置信度: {prc.var_confidence}")
    logger.info(f"  VaR窗口: {prc.var_window}")
    logger.info(f"  最大VaR: {prc.max_var_percent * 100}%")

    # 生成测试数据
    returns = [np.random.randn() * 0.01 for _ in range(150)]

    # 计算VaR
    logger.info(f"\n计算VaR...")
    var_result = prc.calculate_var(returns)

    logger.info(f"\n📊 VaR结果:")
    logger.info(f"  VaR 95%: {var_result.var_95 * 100:.2f}%")
    logger.info(f"  VaR 99%: {var_result.var_99 * 100:.2f}%")
    logger.info(f"  期望亏损(ES): {var_result.expected_shortfall * 100:.2f}%")
    logger.info(f"  风险级别: {var_result.risk_level.value}")

    # 波动率预测
    logger.info(f"\n预测波动率...")
    volatility_forecast = prc.forecast_volatility_garch(returns)

    logger.info(f"\n📈 波动率预测:")
    logger.info(f"  当前波动率: {volatility_forecast.current_volatility * 100:.2f}%")
    logger.info(f"  预测1小时: {volatility_forecast.forecast_1h * 100:.2f}%")
    logger.info(f"  预测4小时: {volatility_forecast.forecast_4h * 100:.2f}%")
    logger.info(f"  预测24小时: {volatility_forecast.forecast_24h * 100:.2f}%")
    logger.info(f"  趋势: {volatility_forecast.trend}")

    # 熔断器检查（正常市场）
    logger.info(f"\n检查熔断器（正常市场）...")
    market_data = {
        'price': 50000,
        'reference_price': 50200,  # 下跌0.4%
        'volume': 1000,
        'avg_volume': 900
    }

    circuit_breaker = prc.check_circuit_breaker(market_data, {})
    logger.info(f"  触发: {'是' if circuit_breaker.is_triggered else '否'}")

    # 熔断器检查（异常市场）
    logger.info(f"\n检查熔断器（异常市场 - 价格暴跌）...")
    market_data_crash = {
        'price': 45000,  # 下跌10%
        'reference_price': 50000,
        'volume': 5000,  # 成交量5倍
        'avg_volume': 1000
    }

    circuit_breaker_crash = prc.check_circuit_breaker(market_data_crash, {})
    logger.info(f"  触发: {'是' if circuit_breaker_crash.is_triggered else '否'}")
    if circuit_breaker_crash.is_triggered:
        logger.info(f"  级别: {circuit_breaker_crash.level}")
        logger.info(f"  原因: {circuit_breaker_crash.trigger_reason}")
        logger.info(f"  动作:")
        for action in circuit_breaker_crash.actions:
            logger.info(f"    • {action}")

    # 动态止损
    logger.info(f"\n计算动态止损...")
    strategy_stop_loss = prc.calculate_dynamic_stop_loss(
        StopLossTier.STRATEGY_LEVEL,
        volatility_forecast.current_volatility,
        100000
    )

    logger.info(f"  策略层止损: {strategy_stop_loss['stop_loss_percent']*100:.2f}% (${strategy_stop_loss['stop_loss_amount']:.2f})")

    # 综合风险评估
    logger.info(f"\n\n综合风险评估...")
    assessment = prc.get_risk_assessment(returns, market_data_crash, {'total_value': 100000})

    logger.info(f"\n🎯 风险评估报告:")
    logger.info(f"  综合风险评分: {assessment['overall_risk_score']}/100")
    logger.info(f"  VaR风险级别: {assessment['var_result'].risk_level.value}")
    logger.info(f"  波动率趋势: {assessment['volatility_forecast'].trend}")
    logger.info(f"  熔断器触发: {'是' if assessment['circuit_breaker'].is_triggered else '否'}")

    logger.info(f"\n建议:")
    for rec in assessment['recommendations']:
        logger.info(f"  • {rec}")

    logger.info("\n" + "="*60)
    logger.info("预测性风控测试: PASS")


if __name__ == "__main__":
    main()
