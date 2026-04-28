#!/usr/bin/env python3
"""
性能监控工具 - v1.0.2 Integrated
统一的性能基准测试和监控
"""

import time
import sys
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("performance_monitor")
except ImportError:
    import logging
    logger = logging.getLogger("performance_monitor")


@dataclass
class PerformanceMetrics:
    """性能指标"""
    startup_time: float = 0.0
    memory_usage_mb: float = 0.0
    event_throughput: float = 0.0
    test_count: int = 0
    test_passed: int = 0
    health_score: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'startup_time': self.startup_time,
            'memory_usage_mb': self.memory_usage_mb,
            'event_throughput': self.event_throughput,
            'test_count': self.test_count,
            'test_passed': self.test_passed,
            'health_score': self.health_score
        }


class PerformanceMonitor:
    """性能监控器"""
    
    # 目标指标
    TARGET_STARTUP_TIME = 1.5  # 秒
    TARGET_MEMORY_USAGE = 80.0  # MB
    TARGET_EVENT_THROUGHPUT = 5000.0  # msg/s
    
    def __init__(self):
        self.baseline: Optional[PerformanceMetrics] = None
        self.current: Optional[PerformanceMetrics] = None
    
    def collect_baseline(self) -> PerformanceMetrics:
        """收集性能基线"""
        metrics = PerformanceMetrics()
        
        # 1. 启动时间
        metrics.startup_time = self._measure_startup_time()
        
        # 2. 内存占用
        metrics.memory_usage_mb = self._measure_memory_usage()
        
        # 3. 事件吞吐
        metrics.event_throughput = self._measure_event_throughput()
        
        # 4. 测试状态
        metrics.test_count, metrics.test_passed = self._measure_test_status()
        
        # 5. 健康得分
        metrics.health_score = self._measure_health_score()
        
        self.baseline = metrics
        logger.info(f"性能基线采集完成: 启动={metrics.startup_time:.3f}s, 内存={metrics.memory_usage_mb:.2f}MB, 吞吐={metrics.event_throughput:.0f}msg/s")
        
        return metrics
    
    def _measure_startup_time(self) -> float:
        """测量启动时间"""
        start = time.time()
        
        modules = [
            'scripts.global_controller',
            'scripts.event_bus',
            'scripts.system_integrator',
            'scripts.shadow_strategy_pool',
            'scripts.strategy_lifecycle_manager',
            'scripts.compliance_audit',
            'scripts.meta_learner_advisor',
            'scripts.risk_engine'
        ]
        
        for module in modules:
            try:
                __import__(module)
            except Exception as e:
                logger.debug(f"模块加载失败: {module}, {e}")
        
        return time.time() - start
    
    def _measure_memory_usage(self) -> float:
        """测量内存占用"""
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0
    
    def _measure_event_throughput(self) -> float:
        """测量事件吞吐"""
        try:
            from scripts.event_bus import get_event_bus
            
            bus = get_event_bus()
            received = [0]
            
            def handler(event):
                received[0] += 1
            
            # 订阅一个标准事件
            bus.subscribe("system.metrics", handler)
            
            # 发送1000条事件
            start = time.time()
            for i in range(1000):
                bus.publish("system.metrics", {"value": i}, "perf_test")
            
            elapsed = time.time() - start
            return 1000 / elapsed if elapsed > 0 else 0.0
            
        except Exception as e:
            logger.warning(f"事件吞吐测量失败: {e}")
            return 0.0
    
    def _measure_test_status(self) -> tuple:
        """测量测试状态"""
        try:
            import subprocess
            result = subprocess.run(
                [sys.executable, '-m', 'pytest', 'tests/', '-q', '--tb=no'],
                capture_output=True,
                text=True,
                cwd='/workspace/projects/trading-simulator',
                timeout=30
            )
            
            # 解析输出
            if result.returncode == 0:
                # 格式: "113 passed in 0.46s"
                parts = result.stdout.strip().split()
                if len(parts) >= 3:
                    return int(parts[0]), int(parts[0])
            
            return 0, 0
        except Exception as e:
            logger.debug(f"Ignored exception in _measure_test_results: {e}")
            return 0, 0
    
    def _measure_health_score(self) -> int:
        """测量健康得分"""
        try:
            import subprocess
            result = subprocess.run(
                [sys.executable, 'scripts/health_check.py'],
                capture_output=True,
                text=True,
                cwd='/workspace/projects/trading-simulator',
                timeout=30
            )
            
            # 解析输出
            for line in result.stdout.split('\n'):
                if '健康得分:' in line:
                    parts = line.split('健康得分:')
                    if len(parts) > 1:
                        score = parts[1].strip().split('/')[0]
                        return int(score)
            
            return 0
        except Exception as e:
            logger.debug(f"Ignored exception in _measure_health_score: {e}")
            return 0
    
    def evaluate(self, metrics: PerformanceMetrics) -> Dict[str, Any]:
        """评估性能指标"""
        result = {
            'startup_time': {
                'value': metrics.startup_time,
                'target': self.TARGET_STARTUP_TIME,
                'status': '✅' if metrics.startup_time <= self.TARGET_STARTUP_TIME else '❌',
                'diff': metrics.startup_time - self.TARGET_STARTUP_TIME
            },
            'memory_usage': {
                'value': metrics.memory_usage_mb,
                'target': self.TARGET_MEMORY_USAGE,
                'status': '✅' if metrics.memory_usage_mb <= self.TARGET_MEMORY_USAGE else '❌',
                'diff': metrics.memory_usage_mb - self.TARGET_MEMORY_USAGE
            },
            'event_throughput': {
                'value': metrics.event_throughput,
                'target': self.TARGET_EVENT_THROUGHPUT,
                'status': '✅' if metrics.event_throughput >= self.TARGET_EVENT_THROUGHPUT else '❌',
                'diff': metrics.event_throughput - self.TARGET_EVENT_THROUGHPUT
            },
            'test_coverage': {
                'value': f"{metrics.test_passed}/{metrics.test_count}",
                'status': '✅' if metrics.test_count > 0 and metrics.test_passed == metrics.test_count else '❌'
            },
            'health_score': {
                'value': f"{metrics.health_score}/100",
                'status': '✅' if metrics.health_score == 100 else '❌'
            }
        }
        
        return result
    
    def print_report(self, metrics: PerformanceMetrics):
        """打印性能报告"""
        evaluation = self.evaluate(metrics)
        
        print("\n" + "="*60)
        print("性能监控报告")
        print("="*60)
        
        print(f"\n📊 核心指标:")
        print(f"  启动时间: {metrics.startup_time:.3f}s (目标: {self.TARGET_STARTUP_TIME}s) {evaluation['startup_time']['status']}")
        print(f"  内存占用: {metrics.memory_usage_mb:.2f}MB (目标: {self.TARGET_MEMORY_USAGE}MB) {evaluation['memory_usage']['status']}")
        print(f"  事件吞吐: {metrics.event_throughput:.0f} msg/s (目标: {self.TARGET_EVENT_THROUGHPUT} msg/s) {evaluation['event_throughput']['status']}")
        print(f"  测试通过: {metrics.test_passed}/{metrics.test_count} {evaluation['test_coverage']['status']}")
        print(f"  健康得分: {metrics.health_score}/100 {evaluation['health_score']['status']}")
        
        # 总体评估
        all_pass = all(e['status'] == '✅' for e in evaluation.values())
        print(f"\n🎯 总体评估: {'✅ 全部达标' if all_pass else '⚠️ 部分未达标'}")
        print("="*60)


if __name__ == "__main__":
    monitor = PerformanceMonitor()
    
    print("性能监控工具 - v1.0.2 Integrated")
    print("正在采集性能基线...")
    
    metrics = monitor.collect_baseline()
    monitor.print_report(metrics)
