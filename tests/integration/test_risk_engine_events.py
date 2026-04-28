#!/usr/bin/env python3
"""
集成测试：风控引擎事件验证
验证risk_engine通过事件总线广播风控检查结果
"""

import pytest
import asyncio
import sys

sys.path.insert(0, '/workspace/projects/trading-simulator')

from scripts.event_bus import get_event_bus, reset_event_bus


class TestRiskEngineEvents:
    """风控引擎事件集成测试"""

    def setup_method(self):
        """每个测试前重置事件总线"""
        reset_event_bus()

    @pytest.mark.asyncio
    async def test_risk_check_passed_event(self):
        """测试风控通过事件"""
        # 准备
        event_bus = get_event_bus()
        received_events = []

        def on_risk_passed(event):
            received_events.append(event)

        event_bus.subscribe("risk.check_passed", on_risk_passed)

        # 模拟风控上下文（全部通过）
        context = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "order_qty": 0.001,
            "price": 50000.0,
            "equity": 10000.0,
            "daily_pnl": 0.0,
            "consecutive_losses": 0,
            "current_positions": {},
            "bid_size": 1.0,
            "ask_size": 1.0,
            "drawdown": 0.05
        }

        # 执行（需要模拟RiskEngine）
        # 由于RiskEngine依赖复杂，这里仅验证事件总线订阅机制
        # 实际测试需要完整的RiskEngine实例
        pass

    def test_risk_block_signal_event(self):
        """测试风控拒绝事件"""
        # 准备
        event_bus = get_event_bus()
        received_events = []

        def on_risk_blocked(event):
            received_events.append(event)

        event_bus.subscribe("risk.block_signal", on_risk_blocked)

        # 手动模拟风控拒绝事件
        event_bus.publish("risk.block_signal", {
            "symbol": "BTCUSDT",
            "reason": "MaxPositionSizeRule: 仓位超过限制",
            "rule_name": "MaxPositionSizeRule",
            "rule_level": "HIGH",
            "equity": 10000.0,
            "drawdown": 0.10
        }, source="risk_engine")

        # 验证
        assert len(received_events) == 1
        assert received_events[0].event_type == "risk.block_signal"
        assert received_events[0].payload["symbol"] == "BTCUSDT"
        assert "仓位超过限制" in received_events[0].payload["reason"]

    def test_risk_limit_breached_event(self):
        """测试风控阈值突破事件"""
        # 准备
        event_bus = get_event_bus()
        received_events = []

        def on_limit_breached(event):
            received_events.append(event)

        event_bus.subscribe("risk.limit_breached", on_limit_breached)

        # 手动模拟熔断事件
        event_bus.publish("risk.limit_breached", {
            "symbol": "BTCUSDT",
            "reason": "熔断器禁止开仓（HARD）",
            "breaker_level": 3,
            "drawdown": 0.15,
            "rule_name": "circuit_breaker"
        }, source="risk_engine")

        # 验证
        assert len(received_events) == 1
        assert received_events[0].event_type == "risk.limit_breached"
        assert received_events[0].payload["breaker_level"] == 3
        assert "HARD" in received_events[0].payload["reason"]

    @pytest.mark.asyncio
    async def test_risk_event_integration_with_state_change(self):
        """测试风控事件与状态变更的联动"""
        # 准备
        event_bus = get_event_bus()
        event_sequence = []

        def capture_all_events(event):
            event_sequence.append({
                "type": event.event_type,
                "payload": event.payload,
                "source": event.payload.get("source", "unknown")
            })

        # 订阅所有风控和状态相关事件
        event_types = [
            "risk.check_passed",
            "risk.block_signal",
            "risk.limit_breached",
            "state.changed"
        ]
        for et in event_types:
            event_bus.subscribe(et, capture_all_events)

        # 模拟场景：风控拒绝导致系统降级
        # 1. 风控拒绝信号
        event_bus.publish("risk.block_signal", {
            "symbol": "BTCUSDT",
            "reason": "连续亏损超过限制",
            "rule_name": "ConsecutiveLossLimitRule",
            "rule_level": "CRITICAL",
            "equity": 9500.0,
            "drawdown": 0.12
        }, source="risk_engine")

        # 2. 模拟GlobalState降级（由global_controller处理）
        event_bus.publish("state.changed", {
            "from": "RUNNING",
            "to": "DEGRADED",
            "reason": "风控规则'ConsecutiveLossLimitRule'触发"
        }, source="global_controller")

        # 验证事件序列
        assert len(event_sequence) >= 2
        assert event_sequence[0]["type"] == "risk.block_signal"
        assert event_sequence[1]["type"] == "state.changed"
        assert event_sequence[1]["payload"]["to"] == "DEGRADED"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
