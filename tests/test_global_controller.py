#!/usr/bin/env python3
"""
全局状态机测试套件 — 杀手锏交易系统 V6.3
覆盖: 合法转换、非法转换被拒、降级/恢复路径、行为矩阵一致性

运行: PYTHONPATH=. python -m pytest tests/test_global_controller.py -v
"""

import pytest
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.global_controller import (
    SystemState, GlobalState, _VALID_TRANSITIONS,
    ModuleHealth, HealthChecker,
)


class TestGlobalState:
    def setup_method(self):
        GlobalState.reset()

    def test_initial_state_is_init(self):
        gs = GlobalState()
        assert gs.get() == SystemState.INIT

    def test_init_to_running(self):
        gs = GlobalState()
        asyncio.run(gs.set(SystemState.RUNNING, "startup"))
        assert gs.get() == SystemState.RUNNING

    def test_init_to_stopped(self):
        gs = GlobalState()
        asyncio.run(gs.set(SystemState.STOPPED, "shutdown"))
        assert gs.get() == SystemState.STOPPED

    def test_init_to_degraded_rejected(self):
        gs = GlobalState()
        asyncio.run(gs.set(SystemState.DEGRADED, "invalid"))
        assert gs.get() == SystemState.INIT

    def test_running_to_all_valid(self):
        targets = [SystemState.PAUSED, SystemState.DEGRADED,
                   SystemState.SOFT_BREAKER, SystemState.HARD_BREAKER, SystemState.STOPPED]
        for target in targets:
            GlobalState.reset()
            gs = GlobalState()
            asyncio.run(gs.set(SystemState.RUNNING, "startup"))
            asyncio.run(gs.set(target, f"to_{target.value}"))
            assert gs.get() == target

    def test_hard_breaker_only_to_stopped(self):
        for target in [SystemState.RUNNING, SystemState.PAUSED, SystemState.DEGRADED, SystemState.SOFT_BREAKER]:
            GlobalState.reset()
            gs = GlobalState()
            asyncio.run(gs.set(SystemState.RUNNING, "startup"))
            asyncio.run(gs.set(SystemState.HARD_BREAKER, "emergency"))
            asyncio.run(gs.set(target, "should_fail"))
            assert gs.get() == SystemState.HARD_BREAKER

    def test_stopped_no_transitions(self):
        for target in SystemState:
            if target == SystemState.STOPPED:
                continue
            GlobalState.reset()
            gs = GlobalState()
            asyncio.run(gs.set(SystemState.RUNNING, "startup"))
            asyncio.run(gs.set(SystemState.STOPPED, "stop"))
            asyncio.run(gs.set(target, "should_fail"))
            assert gs.get() == SystemState.STOPPED

    def test_self_transition_allowed(self):
        gs = GlobalState()
        asyncio.run(gs.set(SystemState.RUNNING, "startup"))
        asyncio.run(gs.set(SystemState.RUNNING, "refresh"))
        assert gs.get() == SystemState.RUNNING

    def test_history_recorded(self):
        gs = GlobalState()
        asyncio.run(gs.set(SystemState.RUNNING, "startup"))
        asyncio.run(gs.set(SystemState.PAUSED, "pause"))
        history = gs.get_history()
        assert len(history) >= 2
        assert history[-1]["old"] == "RUNNING"
        assert history[-1]["new"] == "PAUSED"

    def test_listener_callback(self):
        callback_data = {}
        def on_change(old, new, reason):
            callback_data["old"] = old.value
            callback_data["new"] = new.value

        gs = GlobalState()
        gs.add_listener(on_change)
        asyncio.run(gs.set(SystemState.RUNNING, "test"))
        assert callback_data["old"] == "INIT"
        assert callback_data["new"] == "RUNNING"


class TestStateBehaviorMatrix:
    def setup_method(self):
        GlobalState.reset()

    def _set_state(self, state):
        gs = GlobalState()
        asyncio.run(gs.set(SystemState.RUNNING, "setup"))
        asyncio.run(gs.set(state, "test"))

    def test_running_allows_all(self):
        self._set_state(SystemState.RUNNING)
        gs = GlobalState()
        assert gs.is_trading_allowed() is True
        assert gs.is_close_allowed() is True
        assert gs.is_scan_allowed() is True
        assert gs.is_decision_allowed() is True

    def test_paused_no_trading(self):
        """PAUSED 不允许任何交易操作(手动暂停=完全冻结)"""
        self._set_state(SystemState.PAUSED)
        gs = GlobalState()
        assert gs.is_trading_allowed() is False
        assert gs.is_close_allowed() is False
        assert gs.is_scan_allowed() is False
        assert gs.is_decision_allowed() is False

    def test_degraded_scan_and_close(self):
        self._set_state(SystemState.DEGRADED)
        gs = GlobalState()
        assert gs.is_trading_allowed() is False
        assert gs.is_close_allowed() is True
        assert gs.is_scan_allowed() is True
        assert gs.is_decision_allowed() is False

    def test_soft_breaker_only_close(self):
        self._set_state(SystemState.SOFT_BREAKER)
        gs = GlobalState()
        assert gs.is_trading_allowed() is False
        assert gs.is_close_allowed() is True
        assert gs.is_scan_allowed() is False
        assert gs.is_decision_allowed() is False

    def test_hard_breaker_only_close(self):
        self._set_state(SystemState.HARD_BREAKER)
        gs = GlobalState()
        assert gs.is_trading_allowed() is False
        assert gs.is_close_allowed() is True
        assert gs.is_scan_allowed() is False
        assert gs.is_decision_allowed() is False

    def test_stopped_nothing_allowed(self):
        self._set_state(SystemState.STOPPED)
        gs = GlobalState()
        assert gs.is_trading_allowed() is False
        assert gs.is_close_allowed() is False
        assert gs.is_scan_allowed() is False
        assert gs.is_decision_allowed() is False


class TestValidTransitions:
    def test_all_states_in_table(self):
        for state in SystemState:
            assert state in _VALID_TRANSITIONS

    def test_no_self_loops(self):
        for state, targets in _VALID_TRANSITIONS.items():
            assert state not in targets

    def test_init_can_reach_running(self):
        assert SystemState.RUNNING in _VALID_TRANSITIONS[SystemState.INIT]

    def test_running_can_reach_breakers(self):
        required = {SystemState.SOFT_BREAKER, SystemState.HARD_BREAKER, SystemState.DEGRADED}
        assert required.issubset(_VALID_TRANSITIONS[SystemState.RUNNING])


class TestRecoveryPaths:
    def setup_method(self):
        GlobalState.reset()

    def test_degraded_recovery(self):
        gs = GlobalState()
        asyncio.run(gs.set(SystemState.RUNNING, "startup"))
        asyncio.run(gs.set(SystemState.DEGRADED, "risk"))
        asyncio.run(gs.set(SystemState.RUNNING, "cleared"))
        assert gs.get() == SystemState.RUNNING

    def test_soft_breaker_recovery(self):
        gs = GlobalState()
        asyncio.run(gs.set(SystemState.RUNNING, "startup"))
        asyncio.run(gs.set(SystemState.SOFT_BREAKER, "loss"))
        asyncio.run(gs.set(SystemState.RUNNING, "cooldown"))
        assert gs.get() == SystemState.RUNNING

    def test_cascading_failure(self):
        gs = GlobalState()
        path = [
            (SystemState.RUNNING, "startup"),
            (SystemState.DEGRADED, "risk"),
            (SystemState.SOFT_BREAKER, "loss_5pct"),
            (SystemState.HARD_BREAKER, "loss_10pct"),
            (SystemState.STOPPED, "emergency"),
        ]
        for state, reason in path:
            asyncio.run(gs.set(state, reason))
            assert gs.get() == state


class TestModuleHealth:
    def test_default_healthy(self):
        h = ModuleHealth(name="test")
        assert h.healthy is True
        assert h.consecutive_failures == 0

    def test_to_dict(self):
        h = ModuleHealth(name="ws", healthy=False, consecutive_failures=3)
        d = h.to_dict()
        assert d["name"] == "ws"
        assert d["healthy"] is False
        assert d["consecutive_failures"] == 3


class TestHealthChecker:
    def test_register_module(self):
        hc = HealthChecker()
        hc.register_module("ws", lambda: True)
        assert "ws" in hc.health_status

    def test_health_score(self):
        hc = HealthChecker()
        hc.register_module("ws", lambda: True)
        hc.register_module("db", lambda: True)
        assert hc.get_health_score() == 100.0
        hc.health_status["db"].healthy = False
        assert hc.get_health_score() == 50.0

    def test_unhealthy_modules(self):
        hc = HealthChecker()
        hc.register_module("ws", lambda: True)
        hc.register_module("db", lambda: True)
        hc.health_status["db"].healthy = False
        assert hc.get_unhealthy_modules() == ["db"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
