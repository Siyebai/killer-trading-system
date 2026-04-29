#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("guardian_daemon")
except ImportError:
    import logging
    logger = logging.getLogger("guardian_daemon")
"""
集成守护进程 - 中央控制系统
整合自我检查、自我修复、自我优化系统
"""

import argparse
import json
import sys
import time
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import traceback

from self_healing_system import SelfHealingSystem, HealthStatus, SeverityLevel
from module_health_checker import ModuleHealthChecker, ModuleHealth


class SystemState(Enum):
    """系统状态"""
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    CRITICAL = "CRITICAL"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    STOPPED = "STOPPED"


@dataclass
class SystemAlert:
    """系统告警"""
    alert_id: str
    severity: SeverityLevel
    message: str
    component: str
    timestamp: float
    acknowledged: bool = False
    resolved: bool = False


class GuardianDaemon:
    """集成守护进程 - 中央控制系统"""

    def __init__(
        self,
        health_check_interval: int = 30,
        module_check_interval: int = 300,
        auto_recovery: bool = True,
        auto_optimization: bool = True
    ):
        """
        初始化守护进程

        Args:
            health_check_interval: 健康检查间隔（秒）
            module_check_interval: 模块检查间隔（秒）
            auto_recovery: 是否自动修复
            auto_optimization: 是否自动优化
        """
        self.health_check_interval = health_check_interval
        self.module_check_interval = module_check_interval
        self.auto_recovery = auto_recovery
        self.auto_optimization = auto_optimization

        # 子系统
        self.healing_system = SelfHealingSystem(
            check_interval=health_check_interval,
            memory_threshold=80.0,
            cpu_threshold=80.0
        )
        self.module_checker = ModuleHealthChecker()

        # 系统状态
        self.system_state = SystemState.STARTING
        self.running = False
        self.start_time = time.time()

        # 告警系统
        self.alerts: List[SystemAlert] = []
        self.alert_history: List[SystemAlert] = []

        # 统计
        self.total_uptime = 0.0
        self.recovery_count = 0
        self.optimization_count = 0
        self.alert_count = 0

    def start(self):
        """启动守护进程"""
        self.running = True
        self.system_state = SystemState.RUNNING
        self.start_time = time.time()

        logger.info("=" * 70)
        logger.info("✅ 杀手锏交易系统 - 集成守护进程")
        logger.info("=" * 70)
        logger.info(f"[Guardian] 启动时间: {datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"[Guardian] 健康检查间隔: {self.health_check_interval}秒")
        logger.info(f"[Guardian] 模块检查间隔: {self.module_check_interval}秒")
        logger.info(f"[Guardian] 自动修复: {self.auto_recovery}")
        logger.info(f"[Guardian] 自动优化: {self.auto_optimization}")
        logger.info(f"[Guardian] 系统状态: {self.system_state.value}")

        # 启动健康检查线程
        health_thread = threading.Thread(target=self._health_monitor_loop, daemon=True)
        health_thread.start()

        # 启动模块检查线程
        module_thread = threading.Thread(target=self._module_monitor_loop, daemon=True)
        module_thread.start()

        # 主循环
        try:
            while self.running:
                self._maintain_system()
                time.sleep(10)

        except KeyboardInterrupt:
            logger.error(f"\n[Guardian] 收到中断信号，正在关闭...")
            self.stop()
        except Exception as e:
            logger.error(f"[Guardian] 主循环异常: {str(e)}")
            traceback.print_exc()
            self.system_state = SystemState.CRITICAL
            self.create_alert(
                severity=SeverityLevel.CRITICAL,
                message=f"主循环异常: {str(e)}",
                component="GuardianDaemon"
            )

    def stop(self):
        """停止守护进程"""
        logger.info(f"[Guardian] 停止守护进程...")
        self.running = False
        self.system_state = SystemState.SHUTTING_DOWN
        self.healing_system.stop()

        time.sleep(1)  # 等待线程结束

        self.system_state = SystemState.STOPPED
        logger.info(f"[Guardian] 已停止")

    def _health_monitor_loop(self):
        """健康监控循环"""
        logger.info(f"[Guardian] 启动健康监控线程")
        last_check = 0

        while self.running:
            try:
                current_time = time.time()
                if current_time - last_check >= self.health_check_interval:
                    self._perform_health_check()
                    last_check = current_time

                time.sleep(1)

            except Exception as e:
                logger.error(f"[Guardian] 健康监控异常: {str(e)}")
                traceback.print_exc()

    def _module_monitor_loop(self):
        """模块监控循环"""
        logger.info(f"[Guardian] 启动模块监控线程")
        last_check = 0

        while self.running:
            try:
                current_time = time.time()
                if current_time - last_check >= self.module_check_interval:
                    self._perform_module_check()
                    last_check = current_time

                time.sleep(1)

            except Exception as e:
                logger.error(f"[Guardian] 模块监控异常: {str(e)}")
                traceback.print_exc()

    def _perform_health_check(self):
        """执行健康检查"""
        logger.info(f"\n[Guardian] === 执行健康检查 ===")

        # 获取健康状态
        status = self.healing_system.get_status()

        # 评估系统状态
        health_score = status['health_score']
        if health_score >= 80:
            new_state = SystemState.RUNNING
        elif health_score >= 50:
            new_state = SystemState.DEGRADED
        else:
            new_state = SystemState.CRITICAL

        if new_state != self.system_state and new_state in [SystemState.DEGRADED, SystemState.CRITICAL]:
            self.system_state = new_state
            severity = SeverityLevel.WARNING if new_state == SystemState.DEGRADED else SeverityLevel.CRITICAL
            self.create_alert(
                severity=severity,
                message=f"系统状态变更: {new_state.value} (健康评分: {health_score:.1f})",
                component="SystemState"
            )

        # 检查是否需要自动修复
        if self.auto_recovery and status['issues_found'] > status['issues_resolved']:
            logger.info(f"[Guardian] 执行自动修复...")
            self._perform_auto_recovery(status)

        # 检查是否需要自动优化
        if self.auto_optimization:
            self._perform_auto_optimization(status)

        # 更新统计
        self.total_uptime = time.time() - self.start_time

    def _perform_module_check(self):
        """执行模块检查"""
        logger.info(f"\n[Guardian] === 执行模块检查 ===")

        # 检查所有模块
        results = self.module_checker.check_all_modules()
        summary = self.module_checker.get_summary()

        # 检查是否有不健康或降级的模块
        unhealthy_modules = self.module_checker.get_unhealthy_modules()
        degraded_modules = self.module_checker.get_degraded_modules()

        if unhealthy_modules:
            severity = SeverityLevel.CRITICAL
            message = f"发现{len(unhealthy_modules)}个不健康模块: {', '.join(unhealthy_modules)}"
            self.create_alert(
                severity=severity,
                message=message,
                component="ModuleHealth"
            )

            # 尝试重启不健康的模块
            if self.auto_recovery:
                self._restart_modules(unhealthy_modules)

        if degraded_modules:
            severity = SeverityLevel.WARNING
            message = f"发现{len(degraded_modules)}个降级模块: {', '.join(degraded_modules)}"
            self.create_alert(
                severity=severity,
                message=message,
                component="ModuleHealth"
            )

        # 打印摘要
        logger.info(f"[Guardian] 模块健康度: {summary['health_percentage']:.1f}%")
        logger.info(f"[Guardian] 健康: {summary['healthy']}, 降级: {summary['degraded']}, 不健康: {summary['unhealthy']}, 严重: {summary['critical']}")

    def _perform_auto_recovery(self, status: Dict[str, Any]):
        """执行自动修复"""
        logger.info(f"[Guardian] 执行自动修复...")

        # 执行自我修复系统的检查和修复
        self.healing_system.check_and_heal()

        self.recovery_count += 1
        logger.info(f"[Guardian] 修复完成，总计: {self.recovery_count}次")

    def _perform_auto_optimization(self, status: Dict[str, Any]):
        """执行自动优化"""
        logger.info(f"[Guardian] 执行自动优化...")

        # 获取健康指标
        metrics = {
            "memory": type('obj', (object,), {
                'value': status['metrics']['memory']['value'],
                'status': HealthStatus(status['metrics']['memory']['status'])
            })(),
            "cpu": type('obj', (object,), {
                'value': status['metrics']['cpu']['value'],
                'status': HealthStatus(status['metrics']['cpu']['status'])
            })()
        }

        # 执行优化
        optimizations = self.healing_system.self_optimizer.optimize_parameters(metrics)

        if optimizations:
            logger.info(f"[Guardian] 建议优化:")
            for opt in optimizations:
                logger.info(f"[Guardian]   - {opt.description}")

            self.optimization_count += len(optimizations)

    def _restart_modules(self, module_names: List[str]):
        """重启模块"""
        logger.info(f"[Guardian] 尝试重启模块: {', '.join(module_names)}")

        # 这里可以实现模块重启逻辑
        # 简化版本：只记录告警

    def _maintain_system(self):
        """维护系统"""
        # 定期清理告警历史
        if len(self.alert_history) > 1000:
            self.alert_history = self.alert_history[-500:]

        # 定期检查系统健康度
        status = self.healing_system.get_status()
        if status['health_score'] < 50:
            self.system_state = SystemState.DEGRADED
        elif status['health_score'] < 30:
            self.system_state = SystemState.CRITICAL

    def create_alert(
        self,
        severity: SeverityLevel,
        message: str,
        component: str
    ):
        """创建告警"""
        alert = SystemAlert(
            alert_id=f"ALT_{int(time.time())}_{len(self.alerts)}",
            severity=severity,
            message=message,
            component=component,
            timestamp=time.time()
        )

        self.alerts.append(alert)
        self.alert_history.append(alert)
        self.alert_count += 1

        # 打印告警
        severity_icon = {
            SeverityLevel.INFO: "ℹ️",
            SeverityLevel.WARNING: "⚠️",
            SeverityLevel.ERROR: "❌",
            SeverityLevel.CRITICAL: "🔴",
            SeverityLevel.FATAL: "💀"
        }.get(severity, "❓")

        logger.info(f"[Guardian] {severity_icon} [{severity.value}] {component}: {message}")

    def acknowledge_alert(self, alert_id: str):
        """确认告警"""
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                break

    def resolve_alert(self, alert_id: str):
        """解决告警"""
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.resolved = True
                break

    def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        healing_status = self.healing_system.get_status()
        module_summary = self.module_checker.get_summary()

        return {
            "system_state": self.system_state.value,
            "uptime": self.total_uptime,
            "running": self.running,
            "start_time": self.start_time,
            "health_check_interval": self.health_check_interval,
            "module_check_interval": self.module_check_interval,
            "auto_recovery": self.auto_recovery,
            "auto_optimization": self.auto_optimization,
            "statistics": {
                "total_uptime": self.total_uptime,
                "recovery_count": self.recovery_count,
                "optimization_count": self.optimization_count,
                "alert_count": self.alert_count,
                "active_alerts": len([a for a in self.alerts if not a.resolved])
            },
            "health_status": healing_status,
            "module_health": module_summary,
            "recent_alerts": [
                {
                    "alert_id": a.alert_id,
                    "severity": a.severity.value,
                    "message": a.message,
                    "component": a.component,
                    "timestamp": a.timestamp,
                    "acknowledged": a.acknowledged,
                    "resolved": a.resolved
                }
                for a in self.alerts[-10:]
            ]
        }


def main():
    parser = argparse.ArgumentParser(description="集成守护进程")
    parser.add_argument("--action", choices=["start", "status", "check"], default="status", help="操作类型")
    parser.add_argument("--health-check-interval", type=int, default=30, help="健康检查间隔（秒）")
    parser.add_argument("--module-check-interval", type=int, default=300, help="模块检查间隔（秒）")
    parser.add_argument("--no-auto-recovery", action="store_true", help="禁用自动修复")
    parser.add_argument("--no-auto-optimization", action="store_true", help="禁用自动优化")

    args = parser.parse_args()

    try:
        guardian = GuardianDaemon(
            health_check_interval=args.health_check_interval,
            module_check_interval=args.module_check_interval,
            auto_recovery=not args.no_auto_recovery,
            auto_optimization=not args.no_auto_optimization
        )

        if args.action == "start":
            guardian.start()

        elif args.action == "status":
            # 执行单次检查
            guardian._perform_health_check()
            guardian._perform_module_check()

            status = guardian.get_system_status()

            logger.info(f"\n系统状态:")
            logger.info(f"  状态: {status['system_state']}")
            logger.info(f"  运行时间: {status['uptime']:.0f}秒")
            logger.info(f"  运行中: {status['running']}")
            logger.info(f"\n统计:")
            logger.info(f"  运行时间: {status['statistics']['total_uptime']:.0f}秒")
            logger.info(f"  修复次数: {status['statistics']['recovery_count']}")
            logger.info(f"  优化次数: {status['statistics']['optimization_count']}")
            logger.info(f"  告警次数: {status['statistics']['alert_count']}")
            logger.info(f"  活跃告警: {status['statistics']['active_alerts']}")
            logger.info(f"\n健康评分: {status['health_status']['health_score']:.1f}/100")
            logger.info(f"模块健康度: {status['module_health']['health_percentage']:.1f}%")

            if status['recent_alerts']:
                logger.info(f"\n最近告警:")
                for alert in status['recent_alerts']:
                    logger.info(f"  [{alert['severity']}] {alert['message']}")

        elif args.action == "check":
            # 执行单次检查
            guardian._perform_health_check()
            guardian._perform_module_check()

        output = {
            "status": "success",
            "system_status": guardian.get_system_status() if args.action != "start" else None
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
