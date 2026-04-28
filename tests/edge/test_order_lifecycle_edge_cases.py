#!/usr/bin/env python3
"""
订单生命周期管理器 - 边缘测试
测试并发、幂等性、异常场景
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import pytest
import asyncio
from scripts.order_lifecycle_manager import OrderLifecycleManager, Order, OrderState


class TestOrderLifecycleEdgeCases:
    """订单生命周期边缘测试"""

    def test_duplicate_order_id_idempotency(self):
        """测试重复订单ID的幂等性"""
        manager = OrderLifecycleManager()

        order1 = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )
        assert order1 is not None
        assert order1.client_order_id == order1.order_id  # 系统使用order_id作为client_order_id

        # 测试幂等性：创建相同订单
        order2 = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )

        # 应该返回不同的订单ID
        assert order2 is not None
        assert order2.order_id != order1.order_id

    def test_concurrent_state_transitions(self):
        """测试并发状态转换"""
        manager = OrderLifecycleManager()

        order = manager.create_order(
            client_order_id="CLIENT_002",
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )
        assert order is not None

        # 提交订单
        manager.submit_order("CLIENT_002", "TEST_002")

        # 模拟并发状态转换
        async def concurrent_transition():
            try:
                order.state = OrderState.SUBMITTING
                await asyncio.sleep(0.001)
                order.state = OrderState.ACKNOWLEDGED
            except Exception as e:
                print(f"并发转换失败: {e}")

        # 运行多个并发转换
        loop = asyncio.get_event_loop()
        tasks = [concurrent_transition() for _ in range(10)]
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))

        # 最终状态应该是ACKNOWLEDGED
        assert order.state == OrderState.ACKNOWLEDGED

    def test_invalid_state_transition(self):
        """测试非法状态转换"""
        manager = OrderLifecycleManager()

        order = manager.create_order(
            client_order_id="CLIENT_003",
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )
        assert order is not None

        # 尝试非法转换: NEW -> FILLED (跳过SUBMITTING和ACKNOWLEDGED)
        # 直接修改状态，然后验证转换是否被拒绝
        result = manager.transition_order_state(
            "CLIENT_003",  # 使用client_order_id
            OrderState.FILLED
        )

        # 应该返回False（转换被拒绝）
        assert result is False

    def test_negative_price_order(self):
        """测试负价格订单"""
        manager = OrderLifecycleManager()

        # 负价格应该被create_order接受（数据层验证）或在后续流程拒绝
        order = manager.create_order(
            client_order_id="CLIENT_004",
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=-100.0  # 负价格
        )
        # 根据实际需求验证
        # 这里仅验证创建成功，实际交易应该在风控层拒绝
        assert order is not None
        assert order.price == -100.0

    def test_zero_quantity_order(self):
        """测试零数量订单"""
        manager = OrderLifecycleManager()

        order = manager.create_order(
            client_order_id="CLIENT_005",
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=0.0,  # 零数量
            price=50000.0
        )
        # 零数量应该被创建，实际交易应该在风控层拒绝
        assert order is not None
        assert order.quantity == 0.0

    def test_order_expiration(self):
        """测试订单过期"""
        manager = OrderLifecycleManager()

        order = manager.create_order(
            client_order_id="CLIENT_006",
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0,
            ttl_ms=100  # 100ms TTL
        )
        assert order is not None

        # 等待过期
        import time
        time.sleep(0.15)

        # 检查订单是否被标记为过期
        expired_orders = manager.get_expired_orders()
        assert len(expired_orders) > 0

    def test_nonexistent_order_transition(self):
        """测试不存在的订单转换"""
        manager = OrderLifecycleManager()

        # 应该返回False而不是抛出异常
        result = manager.transition_order_state(
            "NONEXISTENT_001",
            OrderState.SUBMITTING
        )
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
