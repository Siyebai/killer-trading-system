#!/usr/bin/env python3
"""
事件总线 - 边缘测试
测试订阅者异常隔离、事件历史缓冲区满等场景
"""

import pytest
from scripts.event_bus import EventBus


class TestEventBusEdgeCases:
    """事件总线边缘测试"""

    def test_subscriber_exception_isolation(self):
        """测试订阅者异常隔离"""
        bus = EventBus()

        # 注册一个会抛出异常的订阅者
        def failing_subscriber(event):
            raise Exception("订阅者异常")

        # 注册一个正常订阅者
        results = []
        def normal_subscriber(event):
            results.append(event.event_type)

        # 订阅
        bus.subscribe("test.event", failing_subscriber)
        bus.subscribe("test.event", normal_subscriber)

        # 发布事件
        bus.publish("test.event", {"data": "test"})

        # 正常订阅者应该收到事件，尽管失败订阅者抛出异常
        assert len(results) == 1
        assert results[0] == "test.event"

    def test_event_history_buffer_full(self):
        """测试事件历史缓冲区满"""
        bus = EventBus(max_history=10)  # 限制为10条

        # 发布超过限制的事件
        for i in range(20):
            bus.publish("test.event", {"id": i})

        # 历史记录应该只保留最近10条
        history = bus.get_history()
        assert len(history) == 10
        # 应该是最后10条
        assert history[0].payload["id"] == 10
        assert history[-1].payload["id"] == 19

    def test_nonexistent_event_type(self):
        """测试不存在的事件类型"""
        bus = EventBus()

        # 订阅不存在的类型
        results = []
        bus.subscribe("nonexistent.event", lambda e: results.append(e))

        # 发布不存在的事件
        bus.publish("nonexistent.event", {"data": "test"})

        # 订阅者应该收到事件（事件总线不限制事件类型）
        assert len(results) == 1

    def test_duplicate_subscription(self):
        """测试重复订阅"""
        bus = EventBus()

        results = []
        def subscriber(event):
            results.append(event.event_type)

        # 重复订阅同一个事件
        bus.subscribe("test.event", subscriber)
        bus.subscribe("test.event", subscriber)

        # 发布事件
        bus.publish("test.event", {"data": "test"})

        # 订阅者应该被调用两次
        assert len(results) == 2

    def test_unsubscribe_nonexistent_subscriber(self):
        """测试取消不存在的订阅"""
        bus = EventBus()

        def subscriber(event):
            pass

        # 取消从未订阅的订阅者
        bus.unsubscribe("test.event", subscriber)

        # 不应该抛出异常
        assert True

    def test_empty_event_type(self):
        """测试空事件类型"""
        bus = EventBus()

        # 发布空事件类型
        bus.publish("", {"data": "test"})

        # 不应该抛出异常，但可能被记录
        assert True

    def test_none_payload(self):
        """测试None载荷"""
        bus = EventBus()

        results = []
        bus.subscribe("test.event", lambda e: results.append(e.payload))

        # 发布None载荷
        bus.publish("test.event", None)

        # 订阅者应该收到None
        assert results[0] is None

    def test_cyclic_event_publishing(self):
        """测试循环事件发布（订阅者在回调中发布新事件）"""
        bus = EventBus()

        results = []

        def subscriber(event):
            results.append(event.event_type)
            # 在回调中发布新事件
            if event.event_type == "event.a":
                bus.publish("event.b", {"data": "from_a"})

        bus.subscribe("event.a", subscriber)
        bus.subscribe("event.b", subscriber)

        # 发布初始事件
        bus.publish("event.a", {"data": "init"})

        # 应该触发event.a和event.b
        assert "event.a" in results
        assert "event.b" in results

    def test_large_payload(self):
        """测试大载荷"""
        bus = EventBus()

        # 创建大载荷（1MB）
        large_payload = {"data": "x" * 1024 * 1024}

        # 发布大载荷
        bus.publish("test.event", large_payload)

        # 不应该抛出异常
        assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
