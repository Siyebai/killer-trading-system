# [ARCHIVED by Round 9 Integration - 2025-04-30]
# Reason: No active callers

#!/usr/bin/env python3
"""
长时间稳定性监控 - Phase 5 P1
监控内存泄漏、连接池耗尽、日志文件膨胀
"""

import os
import psutil
import time
import json
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("stability_monitor")
except ImportError:
    import logging
    logger = logging.getLogger("stability_monitor")


class StabilityMonitor:
    """稳定性监控器"""

    def __init__(self, check_interval: int = 60, alert_threshold_mb: int = 100):
        """
        初始化监控器

        Args:
            check_interval: 检查间隔（秒）
            alert_threshold_mb: 内存告警阈值（MB）
        """
        self.check_interval = check_interval
        self.alert_threshold_mb = alert_threshold_mb
        self.process = psutil.Process(os.getpid())
        self.start_time = time.time()

        # 历史数据
        self.memory_history: deque = deque(maxlen=1440)  # 保留24小时（每分钟一次）
        self.alert_history: List[Dict] = []

        # 告警条件
        self.consecutive_failures = 0
        self.max_consecutive_failures = 3
        self.memory_growth_threshold = 0.2  # 每小时增长20%

    def get_memory_info(self) -> Dict:
        """
        获取内存信息

        Returns:
            内存信息字典
        """
        try:
            # 第一层防御：进程获取异常处理
            if not self.process:
                logger.warning("进程对象不可用")
                return {}

            memory_info = self.process.memory_info()

            # 第二层防御：数值计算保护
            rss_mb = memory_info.rss / 1024 / 1024  # RSS（常驻内存集）

            return {
                'timestamp': time.time(),
                'rss_mb': rss_mb,
                'vms_mb': memory_info.vms / 1024 / 1024,
                'percent': self.process.memory_percent(),
                'available_mb': psutil.virtual_memory().available / 1024 / 1024
            }

        except psutil.NoSuchProcess as e:
            logger.error(f"进程不存在: {e}")
            return {}
        except Exception as e:
            logger.error(f"获取内存信息异常: {e}")
            return {}

    def check_memory_growth(self) -> bool:
        """
        检查内存增长是否异常

        Returns:
            是否异常（True表示超过阈值）
        """
        try:
            if len(self.memory_history) < 60:  # 至少需要1小时数据
                return False

            # 计算过去1小时的内存增长率
            now = time.time()
            one_hour_ago = now - 3600

            # 获取1小时前的内存数据
            old_memory = None
            for record in self.memory_history:
                if record['timestamp'] >= one_hour_ago and record['timestamp'] <= one_hour_ago + 60:
                    old_memory = record['rss_mb']
                    break

            if old_memory is None:
                return False

            # 获取当前内存
            current_memory = self.memory_history[-1]['rss_mb']

            # 计算增长率
            if old_memory > 0:
                growth_rate = (current_memory - old_memory) / old_memory

                # 第三层防御：异常兜底
                if growth_rate < 0 or growth_rate > 1.0:  # 异常增长率
                    logger.warning(f"内存增长率异常: {growth_rate:.2%}")
                    return False

                if growth_rate > self.memory_growth_threshold:
                    logger.error(f"内存增长异常: {growth_rate:.2%} "
                               f"(过去1小时: {old_memory:.1f}MB → {current_memory:.1f}MB)")
                    return True

            return False

        except ZeroDivisionError as e:
            logger.error(f"计算内存增长率时除零错误: {e}")
            return False
        except Exception as e:
            logger.error(f"检查内存增长异常: {e}")
            return False

    def check_system_resources(self) -> Dict:
        """
        检查系统资源状态

        Returns:
            资源状态字典
        """
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            return {
                'timestamp': time.time(),
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_available_mb': memory.available / 1024 / 1024,
                'disk_percent': disk.percent,
                'disk_free_mb': disk.free / 1024 / 1024
            }

        except Exception as e:
            logger.error(f"检查系统资源异常: {e}")
            return {}

    def log_checkpoint(self, status: str = "OK"):
        """
        记录检查点

        Args:
            status: 状态（OK/WARNING/ERROR）
        """
        try:
            memory_info = self.get_memory_info()
            system_info = self.check_system_resources()

            checkpoint = {
                'timestamp': datetime.now().isoformat(),
                'status': status,
                'runtime_hours': (time.time() - self.start_time) / 3600,
                'memory_mb': memory_info.get('rss_mb', 0),
                'cpu_percent': system_info.get('cpu_percent', 0),
                'memory_system_percent': system_info.get('memory_percent', 0)
            }

            self.memory_history.append({
                'timestamp': time.time(),
                'rss_mb': memory_info.get('rss_mb', 0)
            })

            # 记录到日志
            logger.info(f"稳定性检查点: 运行{checkpoint['runtime_hours']:.1f}h | "
                       f"内存{checkpoint['memory_mb']:.1f}MB | "
                       f"CPU{checkpoint['cpu_percent']:.1f}% | "
                       f"系统内存{checkpoint['memory_system_percent']:.1f}%")

            return checkpoint

        except Exception as e:
            logger.error(f"记录检查点异常: {e}")
            return {}

    def trigger_alert(self, alert_type: str, message: str, severity: str = "WARNING"):
        """
        触发告警

        Args:
            alert_type: 告警类型
            message: 告警消息
            severity: 严重程度（INFO/WARNING/ERROR/CRITICAL）
        """
        try:
            alert = {
                'timestamp': datetime.now().isoformat(),
                'type': alert_type,
                'severity': severity,
                'message': message,
                'runtime_hours': (time.time() - self.start_time) / 3600
            }

            self.alert_history.append(alert)

            # 记录日志
            if severity == "CRITICAL":
                logger.critical(f"告警: {message}")
            elif severity == "ERROR":
                logger.error(f"告警: {message}")
            elif severity == "WARNING":
                logger.warning(f"告警: {message}")
            else:
                logger.info(f"告警: {message}")

            # 保存到文件
            alert_log_path = "references/stability_alerts.json"
            with open(alert_log_path, 'w') as f:
                json.dump(list(self.alert_history), f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"触发告警异常: {e}")

    def run_single_check(self) -> bool:
        """
        执行单次检查

        Returns:
            检查是否通过（True表示通过，False表示发现问题）
        """
        try:
            # 记录检查点
            checkpoint = self.log_checkpoint()

            # 检查内存增长
            if self.check_memory_growth():
                self.trigger_alert("MEMORY_GROWTH", "内存增长异常，可能存在内存泄漏", "WARNING")
                self.consecutive_failures += 1
                return False

            # 检查内存阈值
            memory_mb = checkpoint.get('memory_mb', 0)
            if memory_mb > self.alert_threshold_mb:
                self.trigger_alert("MEMORY_THRESHOLD", f"内存超过阈值: {memory_mb:.1f}MB", "WARNING")
                self.consecutive_failures += 1
                return False

            # 检查系统资源
            system_info = self.check_system_resources()
            if system_info.get('memory_percent', 0) > 90:
                self.trigger_alert("SYSTEM_MEMORY", f"系统内存不足: {system_info['memory_percent']:.1f}%", "ERROR")
                self.consecutive_failures += 1
                return False

            # 检查通过
            self.consecutive_failures = 0
            return True

        except Exception as e:
            logger.error(f"执行检查异常: {e}")
            self.consecutive_failures += 1
            return False

    def run_continuous_monitor(self, duration_hours: float = 1.0):
        """
        连续监控

        Args:
            duration_hours: 监控时长（小时）
        """
        logger.info(f"启动连续稳定性监控，预计运行 {duration_hours:.1f} 小时")

        start_time = time.time()
        check_count = 0

        try:
            while True:
                # 检查是否达到运行时长
                elapsed_hours = (time.time() - start_time) / 3600
                if elapsed_hours >= duration_hours:
                    logger.info(f"监控时长达到 {duration_hours:.1f} 小时，停止监控")
                    break

                # 执行检查
                passed = self.run_single_check()
                check_count += 1

                # 检查是否连续失败
                if self.consecutive_failures >= self.max_consecutive_failures:
                    self.trigger_alert("CONSECUTIVE_FAILURES",
                                     f"连续{self.max_consecutive_failures}次检查失败",
                                     "CRITICAL")
                    logger.error("连续检查失败超过阈值，停止监控")
                    break

                # 等待下一次检查
                time.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("收到中断信号，停止监控")

        # 生成报告
        self.generate_report(check_count, elapsed_hours)

    def generate_report(self, check_count: int, runtime_hours: float):
        """
        生成监控报告

        Args:
            check_count: 检查次数
            runtime_hours: 运行时长
        """
        try:
            report = {
                'monitoring_period': {
                    'start_time': datetime.fromtimestamp(self.start_time).isoformat(),
                    'end_time': datetime.now().isoformat(),
                    'duration_hours': runtime_hours,
                    'total_checks': check_count,
                    'checks_per_hour': check_count / max(runtime_hours, 0.01)
                },
                'memory_summary': {
                    'current_mb': self.memory_history[-1]['rss_mb'] if self.memory_history else 0,
                    'peak_mb': max(r['rss_mb'] for r in self.memory_history) if self.memory_history else 0,
                    'average_mb': sum(r['rss_mb'] for r in self.memory_history) / len(self.memory_history) if self.memory_history else 0
                },
                'alerts': {
                    'total': len(self.alert_history),
                    'by_severity': {}
                }
            }

            # 统计告警
            for alert in self.alert_history:
                severity = alert['severity']
                report['alerts']['by_severity'][severity] = report['alerts']['by_severity'].get(severity, 0) + 1

            # 保存报告
            report_path = f"references/stability_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(report_path, 'w') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            logger.info(f"稳定性监控报告已生成: {report_path}")

        except Exception as e:
            logger.error(f"生成监控报告异常: {e}")


if __name__ == "__main__":
    # 运行 10 分钟监控测试
    monitor = StabilityMonitor(check_interval=60, alert_threshold_mb=500)
    monitor.run_continuous_monitor(duration_hours=10/60)
