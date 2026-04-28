#!/usr/bin/env python3
"""
风控引擎 - 边缘测试
测试亏损逼近熔断线、负价格输入等异常场景
"""

import pytest
from scripts.risk_engine import RiskEngine
from scripts.risk_base import RiskLevel


class TestRiskEngineEdgeCases:
    """风控引擎边缘测试"""

    def test_drawdown_approaching_meltdown(self):
        """测试亏损逼近熔断线"""
        risk_engine = RiskEngine()

        # 模拟亏损逼近熔断线（熔断线为20%）
        portfolio_info = {
            "total_capital": 100000.0,
            "current_drawdown": 0.18,  # 18%，接近20%熔断线
            "daily_pnl": -18000.0,
            "max_drawdown_limit": 0.20
        }

        result = risk_engine.check_drawdown(portfolio_info)

        # 应该发出高优先级警告
        assert result["level"] == RiskLevel.HIGH
        assert "逼近熔断线" in result["message"]

    def test_negative_price_input(self):
        """测试负价格输入"""
        risk_engine = RiskEngine()

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
        risk_engine = RiskEngine()

        market_info = {
            "symbol": "BTC/USDT",
            "price": 50000.0,
            "volatility": 5.0,  # 500%波动率（极端）
            "avg_volatility": 0.05
        }

        result = risk_engine.check_market_condition(market_info)

        # 应该阻止交易
        assert result["allowed"] == False
        assert "波动" in result["reason"]

    def test_position_limit_breach(self):
        """测试仓位限制突破"""
        risk_engine = RiskEngine()

        position_info = {
            "symbol": "BTC/USDT",
            "current_position": 100.0,
            "limit": 10.0  # 限制10个，当前100个
        }

        result = risk_engine.check_position_limit(position_info)

        # 应该阻止新开仓
        assert result["allowed"] == False
        assert "仓位" in result["reason"]

    def test_insufficient_capital(self):
        """测试资金不足"""
        risk_engine = RiskEngine()

        order_info = {
            "symbol": "BTC/USDT",
            "price": 50000.0,
            "quantity": 10.0,
            "side": "BUY",
            "available_capital": 1000.0  # 需要500000，只有1000
        }

        result = risk_engine.check_capital(order_info)

        # 应该拒绝订单
        assert result["allowed"] == False
        assert "资金" in result["reason"]

    def test_rapid_fire_orders(self):
        """测试快速连续下单（防刷单）"""
        risk_engine = RiskEngine()

        # 模拟快速连续下单
        orders = []
        for i in range(100):
            order_info = {
                "symbol": "BTC/USDT",
                "price": 50000.0,
                "quantity": 1.0,
                "side": "BUY",
                "timestamp": 0.001 * i  # 1ms间隔
            }
            orders.append(order_info)

        result = risk_engine.check_rate_limit(orders)

        # 应该触发速率限制
        assert result["allowed"] == False
        assert "速率" in result["reason"]

    def test_risk_rule_overload(self):
        """测试风控规则过载"""
        risk_engine = RiskEngine()

        # 模拟同时触发多条风控规则
        order_info = {
            "symbol": "BTC/USDT",
            "price": -100.0,  # 负价格
            "quantity": 1000.0,  # 超限
            "side": "BUY",
            "available_capital": 100.0  # 资金不足
        }

        result = risk_engine.check_order(order_info)

        # 应该被拒绝，且包含所有违规原因
        assert result["allowed"] == False
        # 应该有多条拒绝原因
        assert len(result["violations"]) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
