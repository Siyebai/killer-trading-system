#!/usr/bin/env python3
"""
系统整合器 - v1.0.3 Integrated
整合所有模块为有机整体，实现协同工作
"""

import time
import threading
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import json

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("system_integrator")
except ImportError:
    import logging
    logger = logging.getLogger("system_integrator")

# 导入事件总线
try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False

try:
    from scripts.global_controller import GlobalController, SystemState
    GLOBAL_CONTROLLER_AVAILABLE = True
except ImportError:
    GLOBAL_CONTROLLER_AVAILABLE = False


class IntegrationMode(Enum):
    """整合模式"""
    SANDBOX = "sandbox"  # 沙盒模式
    SHADOW = "shadow"  # 影子模式
    SEMI_AUTO = "semi_auto"  # 半自动模式
    AUTO = "auto"  # 自动模式


@dataclass
class ModuleStatus:
    """模块状态"""
    name: str
    loaded: bool = False
    active: bool = False
    last_heartbeat: float = 0.0
    events_subscribed: List[str] = field(default_factory=list)
    events_published: List[str] = field(default_factory=list)


class SystemIntegrator:
    """系统整合器 - 中枢控制器"""

    def __init__(self, mode: IntegrationMode = IntegrationMode.SHADOW):
        """
        初始化系统整合器

        Args:
            mode: 整合模式
        """
        self.mode = mode
        self.modules: Dict[str, ModuleStatus] = {}
        self.is_running = False
        self.start_time = 0.0

        # 安全边界（硬限制）
        self.safety_limits = {
            'max_position_size': 0.1,  # 最大仓位10%
            'max_drawdown': 0.20,  # 最大回撤20%
            'max_daily_loss': 0.05,  # 日最大亏损5%
            'max_trades_per_hour': 100,  # 每小时最大交易数
        }

        # 实时状态
        self.current_position = 0.0
        self.current_drawdown = 0.0
        self.daily_pnl = 0.0
        self.trade_count_hourly = 0

        # 回调函数
        self.safety_breach_callbacks: List[callable] = []

        # 配置（用于HRP等扩展模块）
        self.config: Dict = {
            'hrp_max_weight_ratio': 2.0,  # HRP权重上限（均分的倍数）
            'hrp_enabled': True,          # 是否启用HRP权重建议
        }

        logger.info(f"系统整合器初始化完成: 模式={mode.value}")

    def register_module(self, name: str, module: object) -> bool:
        """
        注册模块

        Args:
            name: 模块名称
            module: 模块实例

        Returns:
            是否注册成功
        """
        try:
            status = ModuleStatus(name=name, loaded=True)
            self.modules[name] = status

            # 订阅模块事件
            if EVENT_BUS_AVAILABLE and hasattr(module, '_subscribed_events'):
                for event in module._subscribed_events:
                    status.events_subscribed.append(event)

            logger.info(f"模块注册成功: {name}")
            return True

        except Exception as e:
            logger.error(f"模块注册失败: {name}, 错误={e}")
            return False

    def activate_module(self, name: str) -> bool:
        """
        激活模块

        Args:
            name: 模块名称

        Returns:
            是否激活成功
        """
        try:
            if name not in self.modules:
                logger.warning(f"模块未注册: {name}")
                return False

            status = self.modules[name]
            status.active = True
            status.last_heartbeat = time.time()

            logger.info(f"模块激活成功: {name}")
            return True

        except Exception as e:
            logger.error(f"模块激活失败: {name}, 错误={e}")
            return False

    def check_safety_limits(self) -> List[Dict]:
        """
        检查安全边界

        Returns:
            违规列表
        """
        violations = []

        # 第一层防御：仓位检查
        if abs(self.current_position) > self.safety_limits['max_position_size']:
            violations.append({
                'type': 'POSITION_BREACH',
                'current': self.current_position,
                'limit': self.safety_limits['max_position_size'],
                'severity': 'HIGH'
            })

        # 第二层防御：回撤检查
        if self.current_drawdown > self.safety_limits['max_drawdown']:
            violations.append({
                'type': 'DRAWDOWN_BREACH',
                'current': self.current_drawdown,
                'limit': self.safety_limits['max_drawdown'],
                'severity': 'CRITICAL'
            })

        # 第三层防御：日亏损检查
        if abs(self.daily_pnl) > self.safety_limits['max_daily_loss']:
            violations.append({
                'type': 'DAILY_LOSS_BREACH',
                'current': abs(self.daily_pnl),
                'limit': self.safety_limits['max_daily_loss'],
                'severity': 'HIGH'
            })

        # 第四层防御：交易频率检查
        if self.trade_count_hourly > self.safety_limits['max_trades_per_hour']:
            violations.append({
                'type': 'TRADE_FREQUENCY_BREACH',
                'current': self.trade_count_hourly,
                'limit': self.safety_limits['max_trades_per_hour'],
                'severity': 'MEDIUM'
            })

        return violations

    def handle_safety_breach(self, violation: Dict) -> bool:
        """
        处理安全边界违规

        Args:
            violation: 违规信息

        Returns:
            是否处理成功
        """
        try:
            severity = violation['severity']

            # 第一层防御：触发回调
            for callback in self.safety_breach_callbacks:
                try:
                    callback(violation)
                except Exception as e:
                    logger.error(f"安全回调失败: {e}")

            # 第二层防御：根据严重程度采取行动
            if severity == 'CRITICAL':
                # 触发硬熔断
                logger.critical(f"触发硬熔断: {violation['type']}")
                if GLOBAL_CONTROLLER_AVAILABLE:
                    controller = GlobalController()
                    controller.transition_to(SystemState.HARD_BREAKER)
                return False

            elif severity == 'HIGH':
                # 触发软熔断
                logger.error(f"触发软熔断: {violation['type']}")
                if GLOBAL_CONTROLLER_AVAILABLE:
                    controller = GlobalController()
                    controller.transition_to(SystemState.SOFT_BREAKER)
                return False

            elif severity == 'MEDIUM':
                # 仅警告
                logger.warning(f"安全边界警告: {violation['type']}")
                return True

            return True

        except Exception as e:
            logger.error(f"处理安全违规失败: {e}")
            return False

    def update_state(self, position: float, drawdown: float, daily_pnl: float) -> None:
        """
        更新系统状态

        Args:
            position: 当前仓位
            drawdown: 当前回撤
            daily_pnl: 日盈亏
        """
        self.current_position = position
        self.current_drawdown = drawdown
        self.daily_pnl = daily_pnl

        # 检查安全边界
        violations = self.check_safety_limits()
        for violation in violations:
            self.handle_safety_breach(violation)

    def record_trade(self) -> None:
        """记录交易"""
        self.trade_count_hourly += 1

    def reset_hourly_trade_count(self) -> None:
        """重置每小时交易计数"""
        self.trade_count_hourly = 0

    def get_module_health(self) -> Dict[str, Dict]:
        """
        获取模块健康状态

        Returns:
            模块健康状态字典
        """
        health = {}
        for name, status in self.modules.items():
            heartbeat_age = time.time() - status.last_heartbeat if status.last_heartbeat > 0 else float('inf')

            health[name] = {
                'loaded': status.loaded,
                'active': status.active,
                'heartbeat_age': heartbeat_age,
                'events_subscribed': status.events_subscribed,
                'events_published': status.events_published,
                'healthy': heartbeat_age < 60.0  # 60秒内有心跳
            }

        return health

    def start(self) -> bool:
        """
        启动整合器

        Returns:
            是否启动成功
        """
        try:
            if self.is_running:
                logger.warning("整合器已在运行")
                return False

            self.is_running = True
            self.start_time = time.time()

            logger.info("系统整合器启动成功")

            # 广播启动事件
            if EVENT_BUS_AVAILABLE:
                bus = get_event_bus()
                bus.publish(
                    "system.integrator_started",
                    {
                        "mode": self.mode.value,
                        "timestamp": time.time(),
                        "modules_count": len(self.modules)
                    },
                    source="system_integrator"
                )

            return True

        except Exception as e:
            logger.error(f"启动整合器失败: {e}")
            return False

    def stop(self) -> bool:
        """
        停止整合器

        Returns:
            是否停止成功
        """
        try:
            if not self.is_running:
                logger.warning("整合器未运行")
                return False

            self.is_running = False

            logger.info("系统整合器停止成功")

            # 广播停止事件
            if EVENT_BUS_AVAILABLE:
                bus = get_event_bus()
                bus.publish(
                    "system.integrator_stopped",
                    {
                        "mode": self.mode.value,
                        "timestamp": time.time(),
                        "uptime": time.time() - self.start_time
                    },
                    source="system_integrator"
                )

            return True

        except Exception as e:
            logger.error(f"停止整合器失败: {e}")
            return False

    def add_safety_breach_callback(self, callback: callable) -> None:
        """添加安全违规回调"""
        self.safety_breach_callbacks.append(callback)

    # ========== HRP 风险平价整合层 ==========

    def get_hrp_weights(self, symbol_prices: Dict[str, 'pd.Series'],
                        lookback_days: int = 120,
                        risk_free_rate: float = 0.0) -> Dict[str, float]:
        """
        使用分层风险平价(HRP)计算品种目标权重。

        HRP通过层次聚类构建资产树状结构，递归二分分配权重。
        绕过了协方差矩阵求逆的数值不稳定性。

        Args:
            symbol_prices: 品种价格字典 {symbol: pd.Series of prices}
            lookback_days: 回看天数（默认120天）
            risk_free_rate: 无风险利率（年化）

        Returns:
            品种权重字典 {symbol: weight}，权重之和为1.0

        Reference:
            - Lopez de Prado (2016): "Building Diversified Portfolios that Outperform Out-of-Sample"
            - Cycle 1 深度学习: references/deep_learning/risk_parity_family/
        """
        try:
            import pandas as pd
            import numpy as np

            if not symbol_prices:
                logger.warning("HRP: 无品种数据，返回均分权重")
                return {}

            # 对齐价格数据
            symbols = list(symbol_prices.keys())
            price_df = pd.DataFrame(symbol_prices)
            price_df = price_df.dropna()

            if len(price_df) < 30:
                logger.warning(f"HRP: 数据不足({len(price_df)}条)，返回均分权重")
                return {s: 1.0 / len(symbols) for s in symbols}

            # 计算收益率
            returns = price_df.pct_change().dropna()

            if len(returns) < 30:
                logger.warning(f"HRP: 收益率数据不足，返回均分权重")
                return {s: 1.0 / len(symbols) for s in symbols}

            # 调用HRP
            try:
                from scripts.portfolio_hrp import HierarchicalRiskParity
                hrp = HierarchicalRiskParity()
                weights = hrp.allocate(returns)
                weights = {k: float(v) for k, v in weights.items()}
                total = sum(weights.values())
                if total > 0:
                    weights = {k: v / total for k, v in weights.items()}
                logger.info(f"HRP: 计算完成, weights={weights}")
                return weights
            except ImportError:
                logger.warning("HRP模块不可用，返回均分权重")
                return {s: 1.0 / len(symbols) for s in symbols}
            except Exception as e:
                logger.error(f"HRP计算失败: {e}，返回均分权重")
                return {s: 1.0 / len(symbols) for s in symbols}

        except Exception as e:
            logger.error(f"get_hrp_weights异常: {e}")
            return {}

    def get_position_size_with_hrp(self,
                                    symbol: str,
                                    base_size: float,
                                    hrp_weights: Dict[str, float],
                                    equity: float) -> float:
        """
        根据HRP权重调整目标头寸规模。

        在安全边界（hard limit）检查之前，先用HRP权重作为软参考。
        HRP权重仅作为建议，不覆盖风控硬限制。

        Args:
            symbol: 品种名称
            base_size: 基础头寸规模（由策略决定）
            hrp_weights: HRP计算的建议权重
            equity: 当前权益

        Returns:
            调整后的头寸规模

        逻辑:
            adjusted_size = base_size × min(hrp_weight / equal_weight, max_ratio)
            其中 equal_weight = 1 / N, max_ratio = 2.0（防止过度集中）
        """
        try:
            n_symbols = len(hrp_weights)
            if n_symbols == 0 or symbol not in hrp_weights:
                logger.debug(f"HRP: {symbol}无权重数据，使用base_size={base_size}")
                return base_size

            hrp_weight = hrp_weights[symbol]
            equal_weight = 1.0 / n_symbols
            max_ratio = self.config.get('hrp_max_weight_ratio', 2.0)

            # 软调整：限制单品种权重不超过均分的max_ratio倍
            if hrp_weight > equal_weight * max_ratio:
                adjustment = equal_weight * max_ratio / equal_weight
                adjusted_size = base_size * adjustment
                logger.debug(f"HRP: {symbol}权重受限({hrp_weight:.3f}→{equal_weight*max_ratio:.3f})，"
                            f"调整头寸{base_size:.4f}→{adjusted_size:.4f}")
            else:
                adjustment = hrp_weight / equal_weight
                adjusted_size = base_size * adjustment
                logger.debug(f"HRP: {symbol}权重={hrp_weight:.3f}，调整头寸{base_size:.4f}→{adjusted_size:.4f}")

            return adjusted_size

        except Exception as e:
            logger.error(f"get_position_size_with_hrp异常: {e}")
            return base_size

    # ========== HRP 整合层结束 ==========


if __name__ == "__main__":
    # 测试代码
    print("测试系统整合器...")

    integrator = SystemIntegrator(mode=IntegrationMode.SHADOW)

    # 测试安全边界检查
    print("\n测试1: 正常状态")
    integrator.update_state(position=0.05, drawdown=0.10, daily_pnl=0.02)
    violations = integrator.check_safety_limits()
    print(f"违规数: {len(violations)}")

    print("\n测试2: 回撤违规")
    integrator.update_state(position=0.15, drawdown=0.25, daily_pnl=0.03)
    violations = integrator.check_safety_limits()
    print(f"违规数: {len(violations)}")
    for v in violations:
        print(f"  - {v}")

    print("\n测试通过！")
