#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("module_health_checker")
except ImportError:
    import logging
    logger = logging.getLogger("module_health_checker")
"""
模块健康检查插件系统
用于检查所有交易系统模块的健康状态
"""

import argparse
import json
import sys
import time
import importlib
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ModuleHealth(Enum):
    """模块健康状态"""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


@dataclass
class ModuleHealthCheck:
    """模块健康检查"""
    module_name: str
    status: ModuleHealth
    message: str
    check_time: float
    response_time: float
    details: Dict[str, Any] = field(default_factory=dict)


class ModuleHealthChecker:
    """模块健康检查器"""

    def __init__(self, system_path: str = "."):
        """
        初始化模块健康检查器

        Args:
            system_path: 系统路径
        """
        self.system_path = Path(system_path)
        self.check_results: Dict[str, ModuleHealthCheck] = {}
        self.check_history: List[ModuleHealthCheck] = []

        # 定义要检查的模块
        self.modules_to_check = [
            "linucb_optimizer",
            "data_quality_validator",
            "database_manager",
            "dynamic_position",
            "signal_scorer",
            "market_regime_optimizer",
            "multi_timeframe",
            "adaptive_stop_loss",
            "directional_balance_filter",
            "seven_layer_system",
            "ring_buffer"
        ]

    def check_module(self, module_name: str) -> ModuleHealthCheck:
        """
        检查单个模块

        Args:
            module_name: 模块名称

        Returns:
            健康检查结果
        """
        start_time = time.time()
        status = ModuleHealth.UNKNOWN
        message = ""
        details = {}

        try:
            # 尝试导入模块
            module = importlib.import_module(module_name)
            import_time = time.time() - start_time

            # 检查模块是否有关键类
            key_classes = {
                "linucb_optimizer": "LinUCB",
                "data_quality_validator": "DataQualityValidator",
                "database_manager": "DatabaseManager",
                "dynamic_position": "DynamicPositionSizer",
                "signal_scorer": "SignalScorer",
                "market_regime_optimizer": "MarketRegimeOptimizer",
                "multi_timeframe": "MultiTimeframeAligner",
                "adaptive_stop_loss": "AdaptiveStopLoss",
                "directional_balance_filter": "DirectionalBalanceFilter",
                "seven_layer_system": "SevenLayerSystem",
                "ring_buffer": "RingBuffer"
            }

            if module_name in key_classes:
                class_name = key_classes[module_name]
                if hasattr(module, class_name):
                    details["has_key_class"] = True
                    details["key_class"] = class_name
                else:
                    status = ModuleHealth.DEGRADED
                    message = f"缺少关键类: {class_name}"

            # 检查模块功能
            if status == ModuleHealth.UNKNOWN:
                self._check_module_functionality(module_name, module, details)

            # 确定最终状态
            if status == ModuleHealth.UNKNOWN:
                status = ModuleHealth.HEALTHY
                message = f"模块正常，导入时间: {import_time*1000:.2f}ms"

            details["import_time"] = import_time

        except ImportError as e:
            status = ModuleHealth.CRITICAL
            message = f"无法导入模块: {str(e)}"
            details["error"] = str(e)
        except Exception as e:
            status = ModuleHealth.UNHEALTHY
            message = f"模块异常: {str(e)}"
            details["error"] = str(e)

        response_time = time.time() - start_time

        check_result = ModuleHealthCheck(
            module_name=module_name,
            status=status,
            message=message,
            check_time=time.time(),
            response_time=response_time,
            details=details
        )

        self.check_results[module_name] = check_result
        self.check_history.append(check_result)

        return check_result

    def _check_module_functionality(self, module_name: str, module: Any, details: Dict[str, Any]):
        """检查模块功能"""
        try:
            # LinUCB功能检查
            if module_name == "linucb_optimizer":
                linucb = module.LinUCB(num_arms=5, alpha=1.0, feature_dim=14)
                context = {str(i): 0 for i in range(14)}
                arm = linucb.select_arm(context)
                linucb.update(arm, 0.01, context)
                details["functionality"] = "LinUCB基本功能正常"

            # DataQualityValidator功能检查
            elif module_name == "data_quality_validator":
                validator = module.DataQualityValidator()
                result = validator.validate_kline_data([])
                details["functionality"] = "DataQualityValidator基本功能正常"

            # DatabaseManager功能检查
            elif module_name == "database_manager":
                db = module.DatabaseManager(":memory:")
                conn = db._get_connection()
                db.close_connection()
                details["functionality"] = "DatabaseManager基本功能正常"

            # DynamicPosition功能检查
            elif module_name == "dynamic_position":
                sizer = module.DynamicPositionSizer()
                result = sizer.calculate_position(
                    volatility=0.02,
                    stop_loss_percent=0.05,
                    method="KELLY_OPTIMIZED"
                )
                details["functionality"] = "DynamicPosition基本功能正常"

            # RingBuffer功能检查
            elif module_name == "ring_buffer":
                buffer = module.RingBuffer(capacity=10)
                for i in range(15):
                    buffer.append(i)
                details["functionality"] = "RingBuffer基本功能正常"

        except Exception as e:
            details["functionality_error"] = str(e)

    def check_all_modules(self) -> Dict[str, ModuleHealthCheck]:
        """
        检查所有模块

        Returns:
            所有模块的健康检查结果
        """
        logger.info(f"[ModuleHealth] 开始检查{len(self.modules_to_check)}个模块")

        results = {}
        for module_name in self.modules_to_check:
            logger.info(f"[ModuleHealth] 检查模块: {module_name}")
            result = self.check_module(module_name)
            results[module_name] = result

            # 打印结果
            status_icon = {
                ModuleHealth.HEALTHY: "✅",
                ModuleHealth.DEGRADED: "⚠️",
                ModuleHealth.UNHEALTHY: "❌",
                ModuleHealth.CRITICAL: "🔴",
                ModuleHealth.UNKNOWN: "❓"
            }.get(result.status, "❓")

            logger.info(f"[ModuleHealth]   {status_icon} {result.status.value}: {result.message}")

        return results

    def get_summary(self) -> Dict[str, Any]:
        """
        获取检查摘要

        Returns:
            检查摘要
        """
        if not self.check_results:
            return {}

        total = len(self.check_results)
        healthy = sum(1 for r in self.check_results.values() if r.status == ModuleHealth.HEALTHY)
        degraded = sum(1 for r in self.check_results.values() if r.status == ModuleHealth.DEGRADED)
        unhealthy = sum(1 for r in self.check_results.values() if r.status == ModuleHealth.UNHEALTHY)
        critical = sum(1 for r in self.check_results.values() if r.status == ModuleHealth.CRITICAL)
        unknown = sum(1 for r in self.check_results.values() if r.status == ModuleHealth.UNKNOWN)

        # 计算平均响应时间
        avg_response_time = sum(r.response_time for r in self.check_results.values()) / total if total > 0 else 0

        return {
            "total_modules": total,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "critical": critical,
            "unknown": unknown,
            "health_percentage": (healthy / total * 100) if total > 0 else 0,
            "avg_response_time": avg_response_time
        }

    def get_unhealthy_modules(self) -> List[str]:
        """
        获取不健康的模块列表

        Returns:
            不健康的模块名称列表
        """
        return [
            module_name
            for module_name, result in self.check_results.items()
            if result.status in [ModuleHealth.UNHEALTHY, ModuleHealth.CRITICAL]
        ]

    def get_degraded_modules(self) -> List[str]:
        """
        获取降级的模块列表

        Returns:
            降级的模块名称列表
        """
        return [
            module_name
            for module_name, result in self.check_results.items()
            if result.status == ModuleHealth.DEGRADED
        ]


def main():
    parser = argparse.ArgumentParser(description="模块健康检查插件")
    parser.add_argument("--action", choices=["check", "summary", "unhealthy", "degraded"], default="check", help="操作类型")
    parser.add_argument("--module", help="检查特定模块")

    args = parser.parse_args()

    try:
        checker = ModuleHealthChecker()

        logger.info("=" * 70)
        logger.info("✅ 杀手锏交易系统 - 模块健康检查")
        logger.info("=" * 70)

        if args.action == "check":
            if args.module:
                # 检查单个模块
                result = checker.check_module(args.module)
                logger.info(f"\n模块: {result.module_name}")
                logger.info(f"状态: {result.status.value}")
                logger.info(f"消息: {result.message}")
                logger.info(f"响应时间: {result.response_time*1000:.2f}ms")
                if result.details:
                    logger.info(f"详情: {json.dumps(result.details, ensure_ascii=False, indent=2)}")

                output = {
                    "status": "success",
                    "module_health": {
                        "module_name": result.module_name,
                        "status": result.status.value,
                        "message": result.message,
                        "response_time": result.response_time,
                        "details": result.details
                    }
                }
            else:
                # 检查所有模块
                results = checker.check_all_modules()
                summary = checker.get_summary()

                logger.info(f"\n检查摘要:")
                logger.info(f"  总模块数: {summary['total_modules']}")
                logger.info(f"  健康: {summary['healthy']} ({summary['health_percentage']:.1f}%)")
                logger.info(f"  降级: {summary['degraded']}")
                logger.info(f"  不健康: {summary['unhealthy']}")
                logger.info(f"  严重: {summary['critical']}")
                logger.info(f"  未知: {summary['unknown']}")
                logger.info(f"  平均响应时间: {summary['avg_response_time']*1000:.2f}ms")

                if checker.get_unhealthy_modules():
                    logger.info(f"\n⚠️ 不健康的模块: {', '.join(checker.get_unhealthy_modules())}")

                if checker.get_degraded_modules():
                    logger.info(f"\n⚠️ 降级的模块: {', '.join(checker.get_degraded_modules())}")

                output = {
                    "status": "success",
                    "summary": summary,
                    "unhealthy_modules": checker.get_unhealthy_modules(),
                    "degraded_modules": checker.get_degraded_modules(),
                    "detailed_results": {
                        module_name: {
                            "status": result.status.value,
                            "message": result.message,
                            "response_time": result.response_time,
                            "details": result.details
                        }
                        for module_name, result in results.items()
                    }
                }

        elif args.action == "summary":
            results = checker.check_all_modules()
            summary = checker.get_summary()
            output = {"status": "success", "summary": summary}

        elif args.action == "unhealthy":
            results = checker.check_all_modules()
            unhealthy = checker.get_unhealthy_modules()
            output = {"status": "success", "unhealthy_modules": unhealthy}

        elif args.action == "degraded":
            results = checker.check_all_modules()
            degraded = checker.get_degraded_modules()
            output = {"status": "success", "degraded_modules": degraded}

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
