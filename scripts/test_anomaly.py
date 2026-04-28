#!/usr/bin/env python3
"""
异常检测测试 - v1.0.3 Stable
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import numpy as np

print("=" * 60)
print("异常检测测试 - v1.0.3 Stable")
print("=" * 60)

from scripts.anomaly_detector import AnomalyDetector, AnomalyType, Severity

# 创建检测器
detector = AnomalyDetector()
print("✓ 异常检测器创建成功")

# 生成训练数据
print("\n生成训练数据...")
normal_data = np.random.randn(100, 5)
print(f"✓ 训练数据: {normal_data.shape}")

# 训练（阈值检测模式，跳过Isolation Forest）
print("\n训练检测器（阈值模式）...")
# v1.0.3 Stable: 阈值检测无需训练
print("✓ 检测器就绪")

# 测试1: 正常数据
print("\n[测试1] 正常数据检测...")
normal_point = np.array([0, 0, 0, 0, 0.01])
result1 = detector.detect(normal_point, 'volatility')
if result1 is None:
    print("✓ 正常数据：未检测到异常")
else:
    print(f"✗ 正常数据：误报异常 - {result1.anomaly_type.value}")
    sys.exit(1)

# 测试2: 高波动率异常
print("\n[测试2] 高波动率异常...")
high_vol_point = np.array([0, 0, 0, 0, 0.1])  # 10%波动率
result2 = detector.detect(high_vol_point, 'volatility')
if result2 is not None:
    print(f"✓ 检测到异常: {result2.anomaly_type.value} ({result2.severity.value})")
    print(f"  指标值: {result2.metric_value:.4f}")
    print(f"  阈值: {result2.threshold:.4f}")
else:
    print("✗ 未检测到预期异常")
    sys.exit(1)

# 测试3: 高回撤异常
print("\n[测试3] 高回撤异常...")
high_dd_point = np.array([0, 0, 0, 0, 0.25])  # 25%回撤
result3 = detector.detect(high_dd_point, 'drawdown')
if result3 is not None:
    print(f"✓ 检测到异常: {result3.anomaly_type.value} ({result3.severity.value})")
    print(f"  指标值: {result3.metric_value:.4f}")
    print(f"  阈值: {result3.threshold:.4f}")
else:
    print("✗ 未检测到预期异常")
    sys.exit(1)

# 测试4: 高延迟异常
print("\n[测试4] 高延迟异常...")
high_latency_point = np.array([0, 0, 0, 0, 1500.0])  # 1500ms延迟
result4 = detector.detect(high_latency_point, 'latency')
if result4 is not None:
    print(f"✓ 检测到异常: {result4.anomaly_type.value} ({result4.severity.value})")
    print(f"  指标值: {result4.metric_value:.4f}")
    print(f"  阈值: {result4.threshold:.4f}")
else:
    print("✗ 未检测到预期异常")
    sys.exit(1)

# 统计
stats = detector.get_anomaly_statistics()
print(f"\n异常统计: {stats}")

# 评估
print("\n" + "=" * 60)
print("✓ 异常检测测试通过！")
print("=" * 60)
sys.exit(0)
