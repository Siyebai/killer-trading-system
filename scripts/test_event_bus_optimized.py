#!/usr/bin/env python3
"""
优化后的事件总线性能测试
"""

import time
import sys
sys.path.insert(0, '.')

print("=== 优化后的事件总线性能测试 ===\n")

from scripts.event_bus import get_event_bus, Event

bus = get_event_bus()
received = []
latencies = []

def handler(event):
    received.append(event)
    latencies.append(time.time() - event.timestamp)

# 使用标准事件类型
bus.subscribe("state.changed", handler)

print("发送10000条标准事件...")
start = time.time()
for i in range(10000):
    bus.publish("state.changed", {"index": i}, "perf_test")

elapsed = time.time() - start
throughput = 10000 / elapsed

# 计算P99延迟
if latencies:
    latencies.sort()
    p99_index = int(len(latencies) * 0.99)
    p99_latency = latencies[p99_index] if p99_index < len(latencies) else latencies[-1]
else:
    p99_latency = 0.0

print(f"\n结果:")
print(f"  吞吐量: {throughput:.0f} msg/s")
print(f"  P99延迟: {p99_latency*1000:.3f} ms")
print(f"  接收数: {len(received)}")

if throughput > 25000:
    print(f"\n✅ 吞吐量达标 ({throughput:.0f} > 25000)")
else:
    print(f"\n❌ 吞吐量未达标 ({throughput:.0f} < 25000)")
