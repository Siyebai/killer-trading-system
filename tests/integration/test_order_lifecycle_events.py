#!/usr/bin/env python3
"""
集成测试：订单生命周期事件验证
验证order_lifecycle_manager通过事件总线广播订单状态变更
"""

import pytest
import time
import asyncio

# 导入待测试模块
import sys
sys.path.insert(0, '/workspace/projects/trading-simulator')

from scripts.order_lifecycle_manager import OrderLifecycleManager, OrderState
from scripts.event_bus import get_event_bus, reset_event_bus


class TestOrderLifecycleEvents:
    """订单生命周期事件集成测试"""

    def setup_method(self):
        """每个测试前重置事件总线"""
        reset_event_bus()

    def test_order_created_event(self):
        """测试订单创建事件"""
        # 准备
        event_bus = get_event_bus()
        received_events = []

        def on_order_created(event):
            received_events.append(event)

        event_bus.subscribe("order.created", on_order_created)

        # 执行
        manager = OrderLifecycleManager()
        order = manager.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000.0)

        # 验证
        assert order is not None
        assert len(received_events) == 1
        assert received_events[0].event_type == "order.created"
        assert received_events[0].payload["symbol"] == "BTCUSDT"
        assert received_events[0].payload["side"] == "BUY"
        assert received_events[0].payload["state"] == "NEW"  # order.created使用state而非new_state

    def test_order_submitted_event(self):
        """测试订单提交事件"""
        # 准备
        event_bus = get_event_bus()
        received_events = []

        def on_order_submitted(event):
            received_events.append(event)

        event_bus.subscribe("order.submitted", on_order_submitted)

        # 执行
        manager = OrderLifecycleManager()
        order = manager.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000.0)
        success = manager.submit_order(order.client_order_id, "12345")

        # 验证
        assert success is True
        assert len(received_events) == 1
        assert received_events[0].event_type == "order.submitted"
        assert received_events[0].payload["order_id"] == "12345"
        assert received_events[0].payload["old_state"] == "NEW"
        assert received_events[0].payload["new_state"] == "SUBMITTING"

    def test_order_filled_event(self):
        """测试订单成交事件"""
        # 准备
        event_bus = get_event_bus()
        received_events = []

        def on_order_filled(event):
            received_events.append(event)

        event_bus.subscribe("order.filled", on_order_filled)

        # 执行
        manager = OrderLifecycleManager()
        order = manager.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000.0)
        manager.submit_order(order.client_order_id, "12345")
        manager.acknowledge_order(order.client_order_id)
        success = manager.fill_order(order.client_order_id, 0.001)

        # 验证
        assert success is True
        assert len(received_events) == 1
        assert received_events[0].event_type == "order.filled"
        assert received_events[0].payload["filled_quantity"] == 0.001
        assert received_events[0].payload["remaining_quantity"] == 0.0
        assert received_events[0].payload["is_terminal"] is True

    def test_order_partially_filled_event(self):
        """测试订单部分成交事件"""
        # 准备
        event_bus = get_event_bus()
        received_events = []

        def on_order_partial(event):
            received_events.append(event)

        event_bus.subscribe("order.partially_filled", on_order_partial)

        # 执行
        manager = OrderLifecycleManager()
        order = manager.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000.0)
        manager.submit_order(order.client_order_id, "12345")
        manager.acknowledge_order(order.client_order_id)
        success = manager.fill_order(order.client_order_id, 0.0005, is_partial=True)

        # 验证
        assert success is True
        assert len(received_events) == 1
        assert received_events[0].event_type == "order.partially_filled"
        assert received_events[0].payload["filled_quantity"] == 0.0005
        assert received_events[0].payload["remaining_quantity"] == 0.0005
        assert received_events[0].payload["is_partial"] is True
        assert received_events[0].payload["is_terminal"] is False

    def test_order_cancelled_event(self):
        """测试订单取消事件"""
        # 准备
        event_bus = get_event_bus()
        received_events = []

        def on_order_cancelled(event):
            received_events.append(event)

        event_bus.subscribe("order.cancelled", on_order_cancelled)

        # 执行
        manager = OrderLifecycleManager()
        order = manager.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000.0)
        manager.submit_order(order.client_order_id, "12345")
        success = manager.cancel_order(order.client_order_id)

        # 验证
        assert success is True
        assert len(received_events) == 1
        assert received_events[0].event_type == "order.cancelled"
        assert received_events[0].payload["new_state"] == "CANCELLED"
        assert received_events[0].payload["is_terminal"] is True

    def test_order_rejected_event(self):
        """测试订单拒绝事件"""
        # 准备
        event_bus = get_event_bus()
        received_events = []

        def on_order_rejected(event):
            received_events.append(event)

        event_bus.subscribe("order.rejected", on_order_rejected)

        # 执行
        manager = OrderLifecycleManager()
        order = manager.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000.0)
        manager.submit_order(order.client_order_id, "12345")
        success = manager.reject_order(order.client_order_id, "Insufficient funds")

        # 验证
        assert success is True
        assert len(received_events) == 1
        assert received_events[0].event_type == "order.rejected"
        assert received_events[0].payload["new_state"] == "REJECTED"
        assert "reason" not in received_events[0].payload  # 原因在error字段

    def test_complete_lifecycle_event_sequence(self):
        """测试完整生命周期事件序列"""
        # 准备
        event_bus = get_event_bus()
        event_sequence = []

        def capture_event(event):
            event_sequence.append({
                "type": event.event_type,
                "state": event.payload.get("new_state") or event.payload.get("state"),
                "timestamp": time.time()
            })

        # 订阅所有订单相关事件
        event_types = [
            "order.created", "order.submitted", "order.acknowledged",
            "order.partially_filled", "order.filled", "order.cancelled",
            "order.rejected", "order.failed"
        ]
        for et in event_types:
            event_bus.subscribe(et, capture_event)

        # 执行完整流程
        manager = OrderLifecycleManager()
        order = manager.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000.0)
        manager.submit_order(order.client_order_id, "12345")
        manager.acknowledge_order(order.client_order_id)
        manager.fill_order(order.client_order_id, 0.001)

        # 验证事件序列
        assert len(event_sequence) >= 3
        assert event_sequence[0]["type"] == "order.created"
        assert event_sequence[0]["state"] == "NEW"
        assert event_sequence[1]["type"] == "order.submitted"
        assert event_sequence[1]["state"] == "SUBMITTING"
        assert event_sequence[2]["type"] == "order.acknowledged"
        assert event_sequence[2]["state"] == "ACKNOWLEDGED"

    def test_backward_compatibility_with_callbacks(self):
        """测试向后兼容性：传统回调仍可工作"""
        # 准备
        callback_calls = []

        def traditional_callback(order, old_state, new_state):
            callback_calls.append({
                "client_order_id": order.client_order_id,
                "old": old_state.value if old_state else "UNKNOWN",
                "new": new_state.value if new_state else "UNKNOWN"
            })

        # 执行
        manager = OrderLifecycleManager()
        manager.register_callback(traditional_callback)

        order = manager.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000.0)
        manager.submit_order(order.client_order_id, "12345")

        # 验证：只有状态转换时才会触发回调（submit_order会触发）
        # create_order不会触发回调，因为没有状态转换
        assert len(callback_calls) >= 1  # submitted
        assert callback_calls[0]["old"] == "NEW"
        assert callback_calls[0]["new"] == "SUBMITTING"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
