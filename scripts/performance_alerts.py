#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("performance_alerts")
except ImportError:
    import logging
    logger = logging.getLogger("performance_alerts")
"""
性能告警系统 - V3.5核心模块
实时异常检测和告警
"""

import json
import time
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import deque


class AlertLevel(Enum):
    """告警级别"""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertType(Enum):
    """告警类型"""
    HIGH_LATENCY = "HIGH_LATENCY"
    HIGH_ERROR_RATE = "HIGH_ERROR_RATE"
    LOW_WIN_RATE = "LOW_WIN_RATE"
    HIGH_DRAWDOWN = "HIGH_DRAWDOWN"
    ANOMALOUS_SIGNAL = "ANOMALOUS_SIGNAL"
    SYSTEM_OVERLOAD = "SYSTEM_OVERLOAD"
    DATA_QUALITY = "DATA_QUALITY"
    RISK_LIMIT = "RISK_LIMIT"


@dataclass
class Alert:
    """告警"""
    alert_id: str
    alert_type: AlertType
    level: AlertLevel
    message: str
    timestamp: float
    metrics: Dict[str, float] = field(default_factory=dict)
    threshold: float = 0.0
    current_value: float = 0.0
    is_resolved: bool = False
    resolve_time: Optional[float] = None


class AlertThreshold:
    """告警阈值配置"""

    def __init__(self):
        self.thresholds = {
            # 延迟阈值（毫秒）
            'latency_ms': {
                'warning': 100,
                'error': 500,
                'critical': 1000
            },
            # 错误率（百分比）
            'error_rate_pct': {
                'warning': 1.0,
                'error': 5.0,
                'critical': 10.0
            },
            # 胜率（百分比）
            'win_rate_pct': {
                'warning': 30.0,
                'error': 20.0,
                'critical': 10.0
            },
            # 回撤（百分比）
            'drawdown_pct': {
                'warning': 5.0,
                'error': 10.0,
                'critical': 15.0
            },
            # CPU使用率（百分比）
            'cpu_usage_pct': {
                'warning': 70.0,
                'error': 85.0,
                'critical': 95.0
            },
            # 内存使用率（百分比）
            'memory_usage_pct': {
                'warning': 75.0,
                'error': 90.0,
                'critical': 98.0
            }
        }

    def get_threshold(self, metric_name: str) -> Dict[str, float]:
        """获取指定指标的阈值"""
        return self.thresholds.get(metric_name, {})


class PerformanceMonitor:
    """性能监控器"""

    def __init__(self, window_size: int = 100):
        """
        初始化监控器

        Args:
            window_size: 滑动窗口大小
        """
        self.window_size = window_size
        self.metrics_history = {
            'latency_ms': deque(maxlen=window_size),
            'error_rate': deque(maxlen=window_size),
            'win_rate': deque(maxlen=window_size),
            'drawdown': deque(maxlen=window_size),
            'cpu_usage': deque(maxlen=window_size),
            'memory_usage': deque(maxlen=window_size)
        }

        self.current_metrics = {
            'latency_ms': 0.0,
            'error_rate_pct': 0.0,
            'win_rate_pct': 0.0,
            'drawdown_pct': 0.0,
            'cpu_usage_pct': 0.0,
            'memory_usage_pct': 0.0
        }

    def update_metric(self, metric_name: str, value: float):
        """
        更新指标

        Args:
            metric_name: 指标名称
            value: 指标值
        """
        if metric_name in self.metrics_history:
            self.metrics_history[metric_name].append(value)
            self.current_metrics[metric_name] = value

    def get_metric_avg(self, metric_name: str, window: int = 10) -> float:
        """
        获取指标平均值

        Args:
            metric_name: 指标名称
            window: 窗口大小

        Returns:
            平均值
        """
        history = self.metrics_history.get(metric_name, deque())
        if len(history) == 0:
            return 0.0

        values = list(history)[-window:]
        return sum(values) / len(values)

    def get_current_metrics(self) -> Dict[str, float]:
        """获取当前指标"""
        return self.current_metrics.copy()


class AlertSystem:
    """告警系统"""

    def __init__(self):
        """初始化告警系统"""
        self.thresholds = AlertThreshold()
        self.monitor = PerformanceMonitor()
        self.alerts: List[Alert] = []
        self.alert_handlers: Dict[AlertLevel, List[Callable]] = {
            AlertLevel.INFO: [],
            AlertLevel.WARNING: [],
            AlertLevel.ERROR: [],
            AlertLevel.CRITICAL: []
        }
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_cooldown = 60  # 告警冷却时间（秒）
        self.last_alert_time: Dict[str, float] = {}

    def register_handler(self, level: AlertLevel, handler: Callable):
        """
        注册告警处理器

        Args:
            level: 告警级别
            handler: 处理函数
        """
        self.alert_handlers[level].append(handler)

    def check_metrics(self) -> List[Alert]:
        """
        检查指标是否触发告警

        Returns:
            新触发的告警列表
        """
        new_alerts = []
        current_metrics = self.monitor.get_current_metrics()

        # 检查延迟
        latency_alert = self._check_threshold(
            'latency_ms',
            current_metrics['latency_ms'],
            AlertType.HIGH_LATENCY,
            "事件处理延迟过高"
        )
        if latency_alert:
            new_alerts.append(latency_alert)

        # 检查错误率
        error_alert = self._check_threshold(
            'error_rate_pct',
            current_metrics['error_rate_pct'],
            AlertType.HIGH_ERROR_RATE,
            "错误率过高"
        )
        if error_alert:
            new_alerts.append(error_alert)

        # 检查胜率
        winrate_alert = self._check_threshold(
            'win_rate_pct',
            current_metrics['win_rate_pct'],
            AlertType.LOW_WIN_RATE,
            "胜率过低"
        )
        if winrate_alert:
            new_alerts.append(winrate_alert)

        # 检查回撤
        drawdown_alert = self._check_threshold(
            'drawdown_pct',
            current_metrics['drawdown_pct'],
            AlertType.HIGH_DRAWDOWN,
            "回撤过大"
        )
        if drawdown_alert:
            new_alerts.append(drawdown_alert)

        # 检查CPU
        cpu_alert = self._check_threshold(
            'cpu_usage_pct',
            current_metrics['cpu_usage_pct'],
            AlertType.SYSTEM_OVERLOAD,
            "CPU使用率过高"
        )
        if cpu_alert:
            new_alerts.append(cpu_alert)

        # 检查内存
        memory_alert = self._check_threshold(
            'memory_usage_pct',
            current_metrics['memory_usage_pct'],
            AlertType.SYSTEM_OVERLOAD,
            "内存使用率过高"
        )
        if memory_alert:
            new_alerts.append(memory_alert)

        return new_alerts

    def _check_threshold(self, metric_name: str, value: float,
                        alert_type: AlertType, message: str) -> Optional[Alert]:
        """
        检查阈值

        Args:
            metric_name: 指标名称
            value: 当前值
            alert_type: 告警类型
            message: 告警消息

        Returns:
            告警对象（如果触发）
        """
        threshold_config = self.thresholds.get_threshold(metric_name)

        if not threshold_config:
            return None

        level = None
        threshold = 0.0

        # 判断告警级别
        if value >= threshold_config.get('critical', float('inf')):
            level = AlertLevel.CRITICAL
            threshold = threshold_config['critical']
        elif value >= threshold_config.get('error', float('inf')):
            level = AlertLevel.ERROR
            threshold = threshold_config['error']
        elif value >= threshold_config.get('warning', float('inf')):
            level = AlertLevel.WARNING
            threshold = threshold_config['warning']

        if not level:
            return None

        # 检查冷却时间
        alert_key = f"{alert_type.value}_{metric_name}"
        now = time.time()
        last_time = self.last_alert_time.get(alert_key, 0)

        if now - last_time < self.alert_cooldown:
            # 已有活跃告警，检查是否需要更新
            if alert_key in self.active_alerts:
                self.active_alerts[alert_key].current_value = value
            return None

        # 创建告警
        alert = Alert(
            alert_id=f"{alert_key}_{int(now)}",
            alert_type=alert_type,
            level=level,
            message=message,
            timestamp=now,
            metrics={metric_name: value},
            threshold=threshold,
            current_value=value
        )

        # 记录告警
        self.alerts.append(alert)
        self.active_alerts[alert_key] = alert
        self.last_alert_time[alert_key] = now

        # 触发处理器
        self._trigger_handlers(alert)

        return alert

    def _trigger_handlers(self, alert: Alert):
        """触发告警处理器"""
        handlers = self.alert_handlers.get(alert.level, [])
        for handler in handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"告警处理器执行失败: {e}")

    def resolve_alert(self, alert_id: str):
        """
        解决告警

        Args:
            alert_id: 告警ID
        """
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.is_resolved = True
                alert.resolve_time = time.time()
                break

        # 移除活跃告警
        keys_to_remove = [k for k, v in self.active_alerts.items()
                         if v.alert_id == alert_id]
        for key in keys_to_remove:
            del self.active_alerts[key]

    def update_metrics(self, metrics: Dict[str, float]):
        """
        批量更新指标

        Args:
            metrics: 指标字典
        """
        for metric_name, value in metrics.items():
            self.monitor.update_metric(metric_name, value)

        # 自动检查告警
        new_alerts = self.check_metrics()
        return new_alerts

    def get_active_alerts(self) -> List[Alert]:
        """获取活跃告警"""
        return list(self.active_alerts.values())

    def get_alert_history(self, limit: int = 100) -> List[Alert]:
        """获取告警历史"""
        return self.alerts[-limit:]

    def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        current_metrics = self.monitor.get_current_metrics()
        active_alerts = self.get_active_alerts()

        # 计算健康分数
        health_score = 100
        for alert in active_alerts:
            if alert.level == AlertLevel.CRITICAL:
                health_score -= 20
            elif alert.level == AlertLevel.ERROR:
                health_score -= 10
            elif alert.level == AlertLevel.WARNING:
                health_score -= 5

        health_score = max(0, health_score)

        return {
            'health_score': health_score,
            'status': 'CRITICAL' if health_score < 50 else 'WARNING' if health_score < 80 else 'OK',
            'metrics': current_metrics,
            'active_alerts_count': len(active_alerts),
            'active_alerts': [
                {
                    'type': a.alert_type.value,
                    'level': a.level.value,
                    'message': a.message,
                    'current_value': a.current_value,
                    'threshold': a.threshold
                } for a in active_alerts
            ]
        }


# 默认告警处理器
def default_alert_handler(alert: Alert):
    """默认告警处理器"""
    level_emoji = {
        AlertLevel.INFO: "ℹ️",
        AlertLevel.WARNING: "⚠️",
        AlertLevel.ERROR: "❌",
        AlertLevel.CRITICAL: "🚨"
    }

    emoji = level_emoji.get(alert.level, "")
    timestamp_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(alert.timestamp))

    logger.info(f"{emoji} [{alert.level.value}] {alert.message}")
    logger.info(f"   时间: {timestamp_str}")
    logger.info(f"   当前值: {alert.current_value:.2f} | 阈值: {alert.threshold:.2f}")


# 命令行测试
def main():
    """测试性能告警系统"""
    system = AlertSystem()

    # 注册默认处理器
    system.register_handler(AlertLevel.WARNING, default_alert_handler)
    system.register_handler(AlertLevel.ERROR, default_alert_handler)
    system.register_handler(AlertLevel.CRITICAL, default_alert_handler)

    logger.info("="*60)
    logger.info("🚨 性能告警系统测试")
    logger.info("="*60)

    # 测试场景1: 正常状态
    logger.info("\n场景1: 正常状态")
    metrics = {
        'latency_ms': 50,
        'error_rate_pct': 0.1,
        'win_rate_pct': 60,
        'drawdown_pct': 2,
        'cpu_usage_pct': 40,
        'memory_usage_pct': 50
    }
    new_alerts = system.update_metrics(metrics)
    logger.info(f"触发告警: {len(new_alerts)} 个")

    # 测试场景2: 延迟过高
    logger.info("\n场景2: 延迟过高")
    metrics = {
        'latency_ms': 800,
        'error_rate_pct': 0.1,
        'win_rate_pct': 60,
        'drawdown_pct': 2,
        'cpu_usage_pct': 40,
        'memory_usage_pct': 50
    }
    new_alerts = system.update_metrics(metrics)
    logger.info(f"触发告警: {len(new_alerts)} 个")

    # 测试场景3: 胜率过低
    logger.info("\n场景3: 胜率过低")
    metrics = {
        'latency_ms': 50,
        'error_rate_pct': 0.1,
        'win_rate_pct': 15,
        'drawdown_pct': 2,
        'cpu_usage_pct': 40,
        'memory_usage_pct': 50
    }
    new_alerts = system.update_metrics(metrics)
    logger.info(f"触发告警: {len(new_alerts)} 个")

    # 测试场景4: 系统过载
    logger.info("\n场景4: 系统过载")
    metrics = {
        'latency_ms': 50,
        'error_rate_pct': 0.1,
        'win_rate_pct': 60,
        'drawdown_pct': 2,
        'cpu_usage_pct': 90,
        'memory_usage_pct': 95
    }
    new_alerts = system.update_metrics(metrics)
    logger.info(f"触发告警: {len(new_alerts)} 个")

    # 查看系统状态
    logger.info("\n" + "="*60)
    logger.info("系统状态")
    logger.info("="*60)

    status = system.get_system_status()
    logger.info(f"\n健康分数: {status['health_score']}/100")
    logger.info(f"状态: {status['status']}")
    logger.info(f"活跃告警数: {status['active_alerts_count']}")

    logger.info("\n当前指标:")
    for metric_name, value in status['metrics'].items():
        logger.info(f"  {metric_name}: {value:.2f}")

    if status['active_alerts']:
        logger.info("\n活跃告警:")
        for alert in status['active_alerts']:
            logger.info(f"  [{alert['level']}] {alert['message']}")
            logger.info(f"    当前值: {alert['current_value']:.2f} | 阈值: {alert['threshold']:.2f}")

    logger.info("\n" + "="*60)
    logger.info("性能告警系统测试: PASS")


if __name__ == "__main__":
    main()
