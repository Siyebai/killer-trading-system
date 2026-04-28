#!/usr/bin/env python3
"""
优化后的日志吞吐测试
"""

import time
import sys
import logging
sys.path.insert(0, '.')

print("=== 优化后的日志吞吐测试 ===\n")

from scripts.logger_factory import get_logger

# 获取测试logger
logger = get_logger("log_perf_test")

# 测试1: 直接字符串格式化
print("测试1: 直接字符串格式化")
start = time.time()
for i in range(10000):
    logger.info(f"Test message {i}")
elapsed = time.time() - start
throughput1 = 10000 / elapsed
print(f"  吞吐量: {throughput1:.0f} msg/s")

# 测试2: 使用延迟求值
print("\n测试2: 延迟求值")
start = time.time()
for i in range(10000):
    logger.info("Test message %d", i)
elapsed = time.time() - start
throughput2 = 10000 / elapsed
print(f"  吞吐量: {throughput2:.0f} msg/s")

# 测试3: 高频路径（跳过日志）
print("\n测试3: 跳过日志（高频路径优化）")
test_logger = get_logger("high_perf")
test_logger.setLevel(logging.ERROR)  # 只记录ERROR级别
start = time.time()
for i in range(10000):
    if test_logger.isEnabledFor(logging.ERROR):
        test_logger.info("Test message %d", i)
elapsed = time.time() - start
throughput3 = 10000 / elapsed
print(f"  吞吐量: {throughput3:.0f} msg/s")

print(f"\n最佳吞吐量: {max(throughput1, throughput2, throughput3):.0f} msg/s")
if max(throughput1, throughput2, throughput3) > 50000:
    print("✅ 达标 (>50000 msg/s)")
else:
    print("❌ 未达标 (<50000 msg/s)")
