#!/usr/bin/env python3
"""
订单生命周期管理测试套件 — V6.3
覆盖: 状态机转换/非法转换拒绝/幂等性/超时撤单/错误处理

运行: PYTHONPATH=. python -m pytest tests/test_order_lifecycle.py -v
"""

import pytest
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.order_lifecycle_manager import (
    OrderLifecycleManager, Order, OrderState, _VALID_TRANSITIONS, TERMINAL_STATES
)


class TestOrderCreation:
    def setup_method(self):
        self.mgr = OrderLifecycleManager()

    def test_create_normal_order(self):
        order = self.mgr.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000)
        assert order is not None
        assert order.symbol == "BTCUSDT"
        assert order.state == OrderState.NEW
        assert order.quantity == 0.001

    def test_create_market_order(self):
        order = self.mgr.create_order("BTCUSDT", "SELL", "MARKET", 0.001)
        assert order is not None
        assert order.order_type == "MARKET"

    def test_reject_empty_symbol(self):
        order = self.mgr.create_order("", "BUY", "LIMIT", 0.001, 50000)
        assert order is None

    def test_reject_invalid_side(self):
        order = self.mgr.create_order("BTCUSDT", "HOLD", "LIMIT", 0.001, 50000)
        assert order is None

    def test_reject_zero_quantity(self):
        order = self.mgr.create_order("BTCUSDT", "BUY", "LIMIT", 0, 50000)
        assert order is None

    def test_reject_negative_quantity(self):
        order = self.mgr.create_order("BTCUSDT", "BUY", "LIMIT", -0.001, 50000)
        assert order is None

    def test_reject_limit_without_price(self):
        order = self.mgr.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 0)
        assert order is None


class TestStateMachine:
    def setup_method(self):
        self.mgr = OrderLifecycleManager()
        self.order = self.mgr.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000)
        self.cid = self.order.client_order_id

    def test_normal_lifecycle(self):
        """NEW → SUBMITTING → ACKNOWLEDGED → FILLED"""
        assert self.mgr.submit_order(self.cid, "EX_001") is True
        assert self.order.state == OrderState.SUBMITTING
        assert self.mgr.acknowledge_order(self.cid) is True
        assert self.order.state == OrderState.ACKNOWLEDGED
        assert self.mgr.fill_order(self.cid, 0.001) is True
        assert self.order.state == OrderState.FILLED

    def test_partial_fill_then_full(self):
        """ACKNOWLEDGED → PARTIALLY_FILLED → FILLED"""
        self.mgr.submit_order(self.cid, "EX_001")
        self.mgr.acknowledge_order(self.cid)
        assert self.mgr.fill_order(self.cid, 0.0005, is_partial=True) is True
        assert self.order.state == OrderState.PARTIALLY_FILLED
        assert self.mgr.fill_order(self.cid, 0.0005) is True
        assert self.order.state == OrderState.FILLED

    def test_reject_from_submitting(self):
        """SUBMITTING → REJECTED"""
        self.mgr.submit_order(self.cid, "EX_001")
        assert self.mgr.reject_order(self.cid, "insufficient_margin") is True
        assert self.order.state == OrderState.REJECTED

    def test_cancel_from_acknowledged(self):
        """ACKNOWLEDGED → CANCEL_REQUESTED → CANCELLED"""
        self.mgr.submit_order(self.cid, "EX_001")
        self.mgr.acknowledge_order(self.cid)
        assert self.mgr.cancel_order(self.cid) is True
        assert self.order.state == OrderState.CANCELLED

    def test_invalid_transition_filled_to_cancelled(self):
        """终态FILLED不能转换到CANCELLED"""
        self.mgr.submit_order(self.cid, "EX_001")
        self.mgr.acknowledge_order(self.cid)
        self.mgr.fill_order(self.cid, 0.001)
        assert self.mgr.cancel_order(self.cid) is False
        assert self.order.state == OrderState.FILLED

    def test_invalid_transition_new_to_filled(self):
        """NEW不能直接跳到FILLED"""
        assert self.mgr.fill_order(self.cid, 0.001) is False
        assert self.order.state == OrderState.NEW

    def test_invalid_transition_rejected_to_acknowledged(self):
        """REJECTED终态不能转换"""
        self.mgr.submit_order(self.cid, "EX_001")
        self.mgr.reject_order(self.cid, "test")
        assert self.mgr.acknowledge_order(self.cid) is False
        assert self.order.state == OrderState.REJECTED


class TestValidTransitionsTable:
    def test_all_states_in_table(self):
        for state in OrderState:
            assert state in _VALID_TRANSITIONS

    def test_terminal_states_have_no_outgoing(self):
        for state in TERMINAL_STATES:
            assert len(_VALID_TRANSITIONS[state]) == 0


class TestIdempotency:
    def setup_method(self):
        self.mgr = OrderLifecycleManager()

    def test_unique_client_order_ids(self):
        ids = set()
        for _ in range(100):
            cid = self.mgr.generate_client_order_id("BTCUSDT", "BUY")
            ids.add(cid)
        assert len(ids) == 100  # 全部唯一

    def test_dedup_prevents_duplicate(self):
        """去重缓存阻止重复client_order_id"""
        order1 = self.mgr.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000)
        # 手动注入同一client_order_id
        self.mgr._dedup_cache["test_dup"] = time.time()
        # 去重检查
        assert self.mgr._is_duplicate("test_dup") is True


class TestTimeout:
    def setup_method(self):
        self.mgr = OrderLifecycleManager()

    def test_timeout_cancels_old_orders(self):
        order = self.mgr.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000, ttl_ms=1)
        self.mgr.submit_order(order.client_order_id, "EX_001")
        self.mgr.acknowledge_order(order.client_order_id)
        # 等待超过TTL
        time.sleep(0.01)
        timed_out = self.mgr.check_timeout()
        assert len(timed_out) == 1
        assert self.mgr.get_order(order.client_order_id).state == OrderState.CANCELLED


class TestCallbacks:
    def setup_method(self):
        self.mgr = OrderLifecycleManager()
        self.changes = []

        def on_change(order, old, new):
            self.changes.append((old.value, new.value))

        self.mgr.register_callback(on_change)

    def test_callback_fired_on_submit(self):
        order = self.mgr.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000)
        self.mgr.submit_order(order.client_order_id, "EX_001")
        assert ("NEW", "SUBMITTING") in self.changes

    def test_callback_fired_on_fill(self):
        order = self.mgr.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000)
        self.mgr.submit_order(order.client_order_id, "EX_001")
        self.mgr.acknowledge_order(order.client_order_id)
        self.mgr.fill_order(order.client_order_id, 0.001)
        assert ("ACKNOWLEDGED", "FILLED") in self.changes


class TestOrderNotFound:
    def setup_method(self):
        self.mgr = OrderLifecycleManager()

    def test_submit_nonexistent(self):
        assert self.mgr.submit_order("nonexistent", "EX_001") is False

    def test_fill_nonexistent(self):
        assert self.mgr.fill_order("nonexistent", 0.001) is False

    def test_cancel_nonexistent(self):
        assert self.mgr.cancel_order("nonexistent") is False

    def test_reject_nonexistent(self):
        assert self.mgr.reject_order("nonexistent", "test") is False


class TestStats:
    def test_stats_after_lifecycle(self):
        mgr = OrderLifecycleManager()
        order = mgr.create_order("BTCUSDT", "BUY", "LIMIT", 0.001, 50000)
        mgr.submit_order(order.client_order_id, "EX_001")
        mgr.acknowledge_order(order.client_order_id)
        mgr.fill_order(order.client_order_id, 0.001)
        stats = mgr.get_stats()
        assert stats["total_orders"] == 1
        assert stats["active_orders"] == 0
        assert stats["by_state"].get("FILLED", 0) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
