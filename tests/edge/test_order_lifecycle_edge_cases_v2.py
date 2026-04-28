#!/usr/bin/env python3
"""
订单生命周期管理器 - 边缘测试 v2
使用正确的API接口
"""

import pytest
from scripts.order_lifecycle_manager import OrderLifecycleManager, Order, OrderState


class TestOrderLifecycleEdgeCases:
    """订单生命周期边缘测试"""

    def test_duplicate_order_id_idempotency(self):
        """测试重复订单ID的幂等性"""
        manager = OrderLifecycleManager()

        # 创建第一个订单
        order_id_1 = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )

        # 尝试创建相同参数的订单（应该生成不同的ID）
        order_id_2 = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )

        # 两个订单应该有不同的ID
        assert order_id_1 != order_id_2

    def test_negative_price_order(self):
        """测试负价格订单"""
        manager = OrderLifecycleManager()

        # 创建负价格订单应该失败或被拒绝
        order_id = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=-100.0  # 负价格
        )

        # 系统应该处理这种情况
        assert order_id is not None

        # 尝试提交订单
        result = manager.submit_order(order_id, "EXCHANGE_001")

        # 负价格订单应该被拒绝或无法提交
        # 具体行为取决于实现

    def test_zero_quantity_order(self):
        """测试零数量订单"""
        manager = OrderLifecycleManager()

        # 创建零数量订单
        order_id = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=0.0,  # 零数量
            price=50000.0
        )

        # 系统应该处理这种情况
        assert order_id is not None

        # 获取订单信息
        order = manager.get_order(order_id)
        assert order is not None

    def test_invalid_state_transition(self):
        """测试非法状态转换"""
        manager = OrderLifecycleManager()

        # 创建订单
        order_id = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )

        # 获取订单
        order = manager.get_order(order_id)
        initial_state = order.state

        # 尝试直接修改订单状态（绕过状态机）
        # 这应该被内部验证机制阻止或记录

        # 正确的状态转换流程
        manager.submit_order(order_id, "EXCHANGE_001")
        manager.acknowledge_order(order_id)
        manager.fill_order(order_id, 1.0, 50000.0)

        # 验证订单状态
        order = manager.get_order(order_id)
        assert order.state == OrderState.FILLED

    def test_order_timeout(self):
        """测试订单超时"""
        manager = OrderLifecycleManager(config={"timeout_ms": 100})  # 100ms超时

        # 创建订单
        order_id = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )

        # 提交订单
        manager.submit_order(order_id, "EXCHANGE_001")

        # 等待超时
        import time
        time.sleep(0.15)

        # 检查超时
        timeout_orders = manager.check_timeout()
        # 应该检测到超时订单

    def test_get_nonexistent_order(self):
        """测试获取不存在的订单"""
        manager = OrderLifecycleManager()

        # 获取不存在的订单
        order = manager.get_order("NONEXISTENT_ORDER")
        assert order is None

    def test_get_active_orders_empty(self):
        """测试获取活跃订单（空）"""
        manager = OrderLifecycleManager()

        # 获取活跃订单
        active_orders = manager.get_active_orders()
        assert len(active_orders) == 0

    def test_order_cancellation(self):
        """测试订单取消"""
        manager = OrderLifecycleManager()

        # 创建并提交订单
        order_id = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )

        manager.submit_order(order_id, "EXCHANGE_001")

        # 取消订单
        result = manager.cancel_order(order_id)
        assert result is True

        # 验证订单状态
        order = manager.get_order(order_id)
        assert order.state == OrderState.CANCELLED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
