#!/usr/bin/env python3
"""
风控引擎 - 边缘测试
测试亏损逼近熔断线、负价格输入等异常场景
"""

import pytest
from scripts.risk_engine import RiskEngine
from scripts.risk_base import RiskLevel

# ===== 测试类使用 fixture =====
class TestRiskEngineEdgeCases:
    """风控引擎边缘测试"""

    def test_negative_price_input(self):
        """测试负价格输入"""
        risk_engine = RiskEngine({})

        order_info = {
            "symbol": "BTC/USDT",
            "price": -100.0,  # 负价格
            "quantity": 1.0,
            "side": "BUY"
        }

        result = risk_engine.check_order(order_info)

        # 应该拒绝订单
        assert result["allowed"] == False
        assert "价格" in result["reason"]

    def test_extreme_volatility(self):
        """测试极端波动"""
        risk_engine = RiskEngine({})

        market_info = {
            "symbol": "BTC/USDT",
            "price": 50000.0,
            "volatility": 5.0,  # 500%波动率（极端）
            "avg_volatility": 0.05
        }

        result = risk_engine.check_market_condition(market_info)

        # 应该阻止交易
        assert result["allowed"] == False
        assert "波动率" in result["reason"]

    def test_insufficient_capital(self):
        """测试资金不足"""
        risk_engine = RiskEngine({})

        order_info = {
            "symbol": "BTC/USDT",
            "price": 50000.0,
            "quantity": 1.0,
            "side": "BUY",
            "available_capital": 1000.0  # 资金不足
        }

        result = risk_engine.check_capital(order_info)

        # 应该拒绝订单
        assert result["allowed"] == False
        assert "资金" in result["reason"]

    def test_position_limit_exceeded(self):
        """测试仓位超限"""
        risk_engine = RiskEngine({})

        position_info = {
            "symbol": "BTC/USDT",
            "current_position": 15.0,  # 当前仓位
            "limit": 10.0,  # 仓位上限
            "side": "BUY"
        }

        result = risk_engine.check_position_limit(position_info)

        # 应该拒绝订单
        assert result["allowed"] == False
        assert "超限" in result["reason"]

    def test_rate_limit_exceeded(self):
        """测试速率限制"""
        risk_engine = RiskEngine({})

        # 模拟超过速率限制的订单流
        orders = [{"symbol": "BTC/USDT"}] * 60

        result = risk_engine.check_rate_limit(orders)

        # 应该拒绝
        assert result["allowed"] == False
        assert "速率" in result["reason"]

    def test_risk_rule_overload(self):
        """测试风险规则超载"""
        risk_engine = RiskEngine({})

        # 多重违规：无效价格
        order = {"symbol": "BTC/USDT", "price": -100.0, "quantity": 1.0, "side": "BUY"}
        result = risk_engine.check_order(order)
        assert result["allowed"] == False

    def test_duplicate_order_id_idempotency(self):
        """测试重复订单ID的幂等性"""
        from scripts.order_lifecycle_manager import OrderLifecycleManager

        manager = OrderLifecycleManager({})

        order1 = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )
        assert order1 is not None
        assert order1.client_order_id is not None

        # 创建相同参数订单
        order2 = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0
        )

        # 应该返回不同的订单ID
        assert order2 is not None
        assert order2.client_order_id != order1.client_order_id

    def test_invalid_state_transition(self):
        """测试非法状态转换"""
        from scripts.order_lifecycle_manager import OrderLifecycleManager, OrderState

        manager = OrderLifecycleManager({})

        # NEW -> FILLED 跳过中间状态，应被拒绝
        valid = manager._validate_transition(OrderState.NEW, OrderState.FILLED)
        assert valid == False

        # NEW -> SUBMITTING 是合法转换
        valid_legal = manager._validate_transition(OrderState.NEW, OrderState.SUBMITTING)
        assert valid_legal == True

    def test_negative_price_order(self):
        """测试负价格订单"""
        from scripts.order_lifecycle_manager import OrderLifecycleManager

        manager = OrderLifecycleManager({})

        order = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=-100.0  # 负价格
        )
        # 订单层已验证，直接返回None
        assert order is None

    def test_zero_quantity_order(self):
        """测试零数量订单"""
        from scripts.order_lifecycle_manager import OrderLifecycleManager

        manager = OrderLifecycleManager({})

        order = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=0.0,  # 零数量
            price=50000.0
        )
        # 订单层已验证零数量，直接返回None
        assert order is None

    def test_order_expiration(self):
        """测试订单超时检查"""
        from scripts.order_lifecycle_manager import OrderLifecycleManager

        manager = OrderLifecycleManager({})

        order = manager.create_order(
            symbol="BTC/USDT",
            side="BUY",
            order_type="LIMIT",
            quantity=1.0,
            price=50000.0,
            ttl_ms=50  # 50ms TTL
        )
        assert order is not None

        # 等待过期
        import time
        time.sleep(0.06)

        # 检查超时订单
        timed_out = manager.check_timeout()
        assert len(timed_out) > 0

    def test_nonexistent_order_transition(self):
        """测试不存在的订单"""
        from scripts.order_lifecycle_manager import OrderLifecycleManager

        manager = OrderLifecycleManager({})

        # 不存在的订单 -> 返回None
        order = manager.get_order("NONEXISTENT_001")
        assert order is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
