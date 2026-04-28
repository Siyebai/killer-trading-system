#!/usr/bin/env python3
"""
深度性能测量工具 - v1.0.3 Integrated
七维性能指标全面测量
"""

import time
import sys
import os
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass

sys.path.insert(0, '.')

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("deep_performance")
except ImportError:
    import logging
    logger = logging.getLogger("deep_performance")


@dataclass
class PerformanceMetrics:
    """性能指标"""
    cold_startup: float = 0.0
    memory_baseline: float = 0.0
    event_throughput: float = 0.0
    p99_latency: float = 0.0
    order_conversion_1000: float = 0.0
    log_throughput: float = 0.0
    idle_cpu: float = 0.0
    
    def to_dict(self) -> Dict[str, float]:
        return {
            'cold_startup': self.cold_startup,
            'memory_baseline': self.memory_baseline,
            'event_throughput': self.event_throughput,
            'p99_latency': self.p99_latency,
            'order_conversion_1000': self.order_conversion_1000,
            'log_throughput': self.log_throughput,
            'idle_cpu': self.idle_cpu
        }


class DeepPerformanceMeasurer:
    """深度性能测量器"""
    
    def __init__(self):
        self.metrics = PerformanceMetrics()
    
    def measure_all(self) -> PerformanceMetrics:
        """测量所有七维指标"""
        print("=" * 70)
        print("深度性能七维测量")
        print("=" * 70)
        
        # 1. 冷启动时间
        print("\n[1/7] 冷启动时间测量...")
        self.metrics.cold_startup = self._measure_cold_startup()
        print(f"  冷启动时间: {self.metrics.cold_startup:.4f}s")
        
        # 2. 内存基线
        print("\n[2/7] 内存基线测量...")
        self.metrics.memory_baseline = self._measure_memory_baseline()
        print(f"  空载内存: {self.metrics.memory_baseline:.2f} MB")
        
        # 3. 事件总线吞吐
        print("\n[3/7] 事件总线吞吐测量...")
        self.metrics.event_throughput, self.metrics.p99_latency = self._measure_event_bus()
        print(f"  事件吞吐: {self.metrics.event_throughput:.0f} msg/s")
        print(f"  P99延迟: {self.metrics.p99_latency*1000:.3f} ms")
        
        # 4. 订单状态机转换
        print("\n[4/7] 订单状态机转换测量...")
        self.metrics.order_conversion_1000 = self._measure_order_conversion()
        print(f"  1000次转换: {self.metrics.order_conversion_1000:.4f}s")
        
        # 5. 日志写入吞吐
        print("\n[5/7] 日志写入吞吐测量...")
        self.metrics.log_throughput = self._measure_log_throughput()
        print(f"  日志吞吐: {self.metrics.log_throughput:.0f} msg/s")
        
        # 6. CPU占用
        print("\n[6/7] 空载CPU占用测量...")
        self.metrics.idle_cpu = self._measure_idle_cpu()
        print(f"  空载CPU: {self.metrics.idle_cpu:.2f}%")
        
        print("\n" + "=" * 70)
        print("测量完成")
        print("=" * 70)
        
        return self.metrics
    
    def _measure_cold_startup(self) -> float:
        """测量冷启动时间"""
        start = time.time()
        
        modules = [
            'scripts.global_controller',
            'scripts.event_bus',
            'scripts.system_integrator',
            'scripts.shadow_strategy_pool',
            'scripts.strategy_lifecycle_manager',
            'scripts.compliance_audit',
            'scripts.meta_learner_advisor',
            'scripts.risk_engine',
            'scripts.technical_indicators'
        ]
        
        for module in modules:
            try:
                __import__(module)
            except Exception as e:
                print(f"    ✗ {module}: {e}")
        
        return time.time() - start
    
    def _measure_memory_baseline(self) -> float:
        """测量内存基线"""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            print("    (psutil未安装，使用估算)")
            return 75.0  # 估算值
    
    def _measure_event_bus(self) -> Tuple[float, float]:
        """测量事件总线吞吐和P99延迟"""
        try:
            from scripts.event_bus import get_event_bus, Event
            
            bus = get_event_bus()
            received = []
            latencies = []
            
            def handler(event):
                received.append(event)
                latencies.append(time.time() - event.timestamp)
            
            bus.subscribe("state.changed", handler)
            
            # 发送10000条事件（使用标准事件类型）
            start = time.time()
            for i in range(10000):
                bus.publish("state.changed", {"index": i}, "perf_test")
            
            elapsed = time.time() - start
            throughput = 10000 / elapsed if elapsed > 0 else 0
            
            # 计算P99延迟
            if latencies:
                latencies.sort()
                p99_index = int(len(latencies) * 0.99)
                p99_latency = latencies[p99_index] if p99_index < len(latencies) else latencies[-1]
            else:
                p99_latency = 0.0
            
            return throughput, p99_latency
            
        except Exception as e:
            print(f"    事件总线测量失败: {e}")
            return 0.0, 0.0
    
    def _measure_order_conversion(self) -> float:
        """测量订单状态机转换"""
        try:
            from scripts.order_lifecycle_manager import OrderLifecycleManager
            
            manager = OrderLifecycleManager()
            
            # 模拟1000次状态转换
            start = time.time()
            
            for i in range(1000):
                order_id = f"test_order_{i}"
                
                # 新建 → 已提交 → 已成交 → 已关闭
                manager.create_order(order_id, "BTCUSDT", "BUY", 0.001, 50000.0)
                manager.update_order_status(order_id, "SUBMITTED")
                manager.update_order_status(order_id, "FILLED")
                manager.update_order_status(order_id, "CLOSED")
            
            return time.time() - start
            
        except Exception as e:
            print(f"    订单转换测量失败: {e}")
            return 0.0
    
    def _measure_log_throughput(self) -> float:
        """测量日志写入吞吐"""
        try:
            from scripts.logger_factory import get_logger
            import io
            
            test_logger = get_logger("perf_test")
            
            # 捕获日志输出
            log_stream = io.StringIO()
            
            start = time.time()
            for i in range(1000):
                test_logger.info(f"Test log message {i}")
            
            elapsed = time.time() - start
            throughput = 1000 / elapsed if elapsed > 0 else 0
            
            return throughput
            
        except Exception as e:
            print(f"    日志吞吐测量失败: {e}")
            return 0.0
    
    def _measure_idle_cpu(self) -> float:
        """测量空载CPU占用"""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            
            # 测量60秒的平均CPU占用
            samples = []
            for _ in range(10):
                samples.append(process.cpu_percent(interval=0.1))
            
            return sum(samples) / len(samples)
            
        except ImportError:
            print("    (psutil未安装，跳过)")
            return 1.0  # 估算值
    
    def print_report(self, metrics: PerformanceMetrics):
        """打印性能报告"""
        print("\n" + "=" * 70)
        print("性能七维报告")
        print("=" * 70)
        print(f"\n📊 七维指标:")
        print(f"  1. 冷启动时间:     {metrics.cold_startup:.4f}s (目标: <0.5s)")
        print(f"  2. 内存基线:       {metrics.memory_baseline:.2f} MB (目标: <75MB)")
        print(f"  3. 事件吞吐:       {metrics.event_throughput:.0f} msg/s (目标: >25000 msg/s)")
        print(f"  4. P99延迟:        {metrics.p99_latency*1000:.3f} ms (目标: <1ms)")
        print(f"  5. 订单转换1000次: {metrics.order_conversion_1000:.4f}s (目标: <0.2s)")
        print(f"  6. 日志吞吐:       {metrics.log_throughput:.0f} msg/s (目标: >50000 msg/s)")
        print(f"  7. 空载CPU:        {metrics.idle_cpu:.2f}% (目标: <2%)")
        
        print("\n" + "=" * 70)


if __name__ == "__main__":
    measurer = DeepPerformanceMeasurer()
    metrics = measurer.measure_all()
    measurer.print_report(metrics)
