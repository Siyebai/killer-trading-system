#!/usr/bin/env python3
"""
杀手锏交易系统 - 核心模块包初始化
提供统一的核心类导出，支持健康检查和模块加载
"""

__version__ = "1.0.2"
__author__ = "Killer Trading System Team"

# 核心事件相关
from scripts.event_bus import EventBus, Event

# 核心管理器
from scripts.global_controller import GlobalController
from scripts.system_integrator import SystemIntegrator
from scripts.shadow_strategy_pool import ShadowStrategyPool
from scripts.strategy_lifecycle_manager import StrategyLifecycleManager
# from scripts.compliance_audit import ComplianceAudit  # 实际类名是ComplianceAuditSystem
from scripts.meta_learner_advisor import MetaLearnerAdvisor

# 策略相关
from scripts.strategy_lab import StrategyLab

# 风控相关
from scripts.risk_engine import RiskEngine

# 回测相关
from scripts.backtest_adapter import BacktestAdapter
from scripts.historical_data_loader import HistoricalDataLoader

# 订单管理
from scripts.order_lifecycle_manager import OrderLifecycleManager, Order

# 数据加载
from scripts.orderbook_feeder import OrderBookFeeder

# 异常检测
from scripts.anomaly_detector import AnomalyDetector

# 健康检查
from scripts.health_check import HealthChecker

# 性能监控
from scripts.performance_monitor import PerformanceMonitor
# from scripts.final_performance_check import FinalPerformanceChecker  # 脚本，非模块

__all__ = [
    # 版本信息
    "__version__",
    "__author__",

    # 核心事件
    "EventBus",
    "Event",

    # 核心管理器
    "GlobalController",
    "SystemIntegrator",
    "ShadowStrategyPool",
    "StrategyLifecycleManager",
    # "ComplianceAudit",  # 实际类名是ComplianceAuditSystem
    "MetaLearnerAdvisor",

    # 策略相关
    "StrategyLab",

    # 风控相关
    "RiskEngine",

    # 回测相关
    "BacktestAdapter",
    "HistoricalDataLoader",

    # 订单管理
    "OrderLifecycleManager",
    "Order",

    # 数据加载
    "OrderBookFeeder",

    # 异常检测
    "AnomalyDetector",

    # 健康检查
    "HealthChecker",

    # 性能监控
    "PerformanceMonitor",
    # "FinalPerformanceChecker",  # 脚本，非模块
]


def get_package_version():
    """获取包版本"""
    return __version__


def get_module_info():
    """获取模块信息"""
    import sys
    import importlib

    modules = {}

    for module_name in __all__:
        if module_name in ["__version__", "__author__"]:
            continue

        try:
            # 尝试导入模块
            full_name = f"scripts.{module_name.lower()}"
            if module_name in ["EventBus", "Event"]:
                full_name = "scripts.event_bus"
            elif module_name == "HealthChecker":
                full_name = "scripts.health_check"
            elif module_name == "FinalPerformanceChecker":
                full_name = "scripts.final_performance_check"

            module = importlib.import_module(full_name)
            modules[module_name] = {
                "loaded": True,
                "version": getattr(module, "__version__", "unknown")
            }
        except Exception as e:
            modules[module_name] = {
                "loaded": False,
                "error": str(e)
            }

    return modules


def check_package_health():
    """检查包健康状态"""
    modules = get_module_info()

    loaded_count = sum(1 for m in modules.values() if m["loaded"])
    total_count = len(modules)

    health_score = int((loaded_count / total_count) * 100) if total_count > 0 else 0

    return {
        "health_score": health_score,
        "loaded_modules": loaded_count,
        "total_modules": total_count,
        "modules": modules
    }


if __name__ == "__main__":
    # 运行健康检查
    health = check_package_health()
    print(f"包健康得分: {health['health_score']}/100")
    print(f"已加载模块: {health['loaded_modules']}/{health['total_modules']}")
