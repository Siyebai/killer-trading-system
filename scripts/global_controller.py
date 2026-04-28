#!/usr/bin/env python3
"""
杀手锏交易系统 V6.1 - 总控中心（最终整合版）
整合自我检查、自我修复、自我优化体系，实现全局状态管理、健康监控、异常自动修复、多币种任务调度

基于现有V5.6 guardian_daemon.py + self_healing_system.py 整合升级
整合优化建议：状态行为矩阵、内建探针、内建修复策略、在线/离线优化闭环

核心设计：
1. GlobalState - 7种系统状态 + 风控熔断联动 + 状态行为矩阵
2. HealthChecker - asyncio模块级探针 + 内建探针模板
3. RepairEngine - 模块级修复策略 + 内建修复模板 + 自动重试
4. Dispatcher - 多symbol并行调度 + 全局状态控制
5. PerformanceOptimizer - 在线调参 + 离线搜索触发 + 第10层联动
6. GlobalController - 总控入口，统一管理所有子模块

零侵入集成：各模块仅调用 GlobalState().is_xxx_allowed() 一行代码
"""

import argparse
import asyncio
import json
import sys
import time
import gc
import traceback
from typing import Dict, List, Optional, Any, Callable, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import deque, OrderedDict
from datetime import datetime

# 导入统一事件总线
try:
    from scripts.event_bus import get_event_bus, Event
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False

# 导入日志工厂
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("global_controller")
except ImportError:
    import logging
    logger = logging.getLogger("global_controller")


# ============================================================
# 1. 全局状态管理器
# ============================================================

class SystemState(Enum):
    """
    系统状态（7种，含风控熔断联动）
    
    状态行为矩阵：
    | 状态           | 允许扫描 | 允许开仓 | 允许平仓 | 允许新决策 |
    |---------------|---------|---------|---------|-----------|
    | RUNNING       |   Yes   |   Yes   |   Yes   |    Yes    |
    | PAUSED        |   No    |   No    |   Yes   |    No     |
    | DEGRADED      | Yes(评估) |   No    |   Yes   |    No     |
    | SOFT_BREAKER  |   No    |   No    |   Yes   |    No     |
    | HARD_BREAKER  |   No    |   No    | Yes(平仓)|    No     |
    | STOPPED       |   No    |   No    |   No    |    No     |
    """
    INIT = "INIT"                       # 初始化
    RUNNING = "RUNNING"                 # 正常运行
    PAUSED = "PAUSED"                   # 手动暂停
    DEGRADED = "DEGRADED"               # 降级模式（只评估+平仓，不开新仓）
    SOFT_BREAKER = "SOFT_BREAKER"       # 软熔断（暂停开仓，允许平仓）
    HARD_BREAKER = "HARD_BREAKER"       # 硬熔断（平仓所有，断开连接）
    STOPPED = "STOPPED"                 # 完全停止


# 合法状态转换表
_VALID_TRANSITIONS: Dict[SystemState, Set[SystemState]] = {
    SystemState.INIT:          {SystemState.RUNNING, SystemState.STOPPED},
    SystemState.RUNNING:       {SystemState.PAUSED, SystemState.DEGRADED, SystemState.SOFT_BREAKER, SystemState.HARD_BREAKER, SystemState.STOPPED},
    SystemState.PAUSED:        {SystemState.RUNNING, SystemState.STOPPED},
    SystemState.DEGRADED:      {SystemState.RUNNING, SystemState.SOFT_BREAKER, SystemState.HARD_BREAKER, SystemState.STOPPED},
    SystemState.SOFT_BREAKER:  {SystemState.RUNNING, SystemState.HARD_BREAKER, SystemState.STOPPED},
    SystemState.HARD_BREAKER:  {SystemState.STOPPED},
    SystemState.STOPPED:       set(),
}


class GlobalState:
    """
    全局状态管理器（单例模式）
    
    零侵入集成：各模块仅调用以下方法：
    - is_trading_allowed()  → 是否允许开新仓
    - is_close_allowed()    → 是否允许平仓
    - is_scan_allowed()     → 是否允许扫描
    - is_decision_allowed() → 是否允许执行新决策
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._state = SystemState.INIT
            cls._instance._listeners = []
            cls._instance._state_history = deque(maxlen=200)
            cls._instance._reason = ""
        return cls._instance
    
    @classmethod
    def reset(cls):
        """重置单例（仅用于测试）"""
        cls._instance = None
    
    async def set(self, new_state: SystemState, reason: str = ""):
        """
        设置系统状态（带合法性校验 + 事件广播）

        Args:
            new_state: 目标状态
            reason: 变更原因
        """
        old = self._state

        # 第一层防御：状态转换合法性校验
        if new_state not in _VALID_TRANSITIONS.get(old, set()):
            if old != new_state:  # 允许原地设置
                logger.warning(f"[GlobalState] 非法状态转换: {old.value} -> {new_state.value}，忽略")
                return

        # 第二层防御：状态变更记录
        self._state = new_state
        self._reason = reason
        self._state_history.append({
            'old': old.value,
            'new': new_state.value,
            'reason': reason,
            'timestamp': time.time()
        })
        logger.info(f"[GlobalState] {old.value} -> {new_state.value} | {reason}")

        # 第三层防御：事件总线广播（集成点）
        if EVENT_BUS_AVAILABLE:
            try:
                event_bus = get_event_bus()
                event_bus.publish(
                    "state.changed",
                    {
                        "from": old.value,
                        "to": new_state.value,
                        "reason": reason,
                        "state_matrix": self.get_state_matrix()
                    },
                    source="global_controller"
                )
                logger.debug(f"[GlobalState] 状态变更事件已广播: {old.value} -> {new_state.value}")
            except Exception as e:
                logger.error(f"[GlobalState] 事件广播失败: {e}")

        # 触发传统监听器（保持向后兼容）
        for listener in self._listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(old, new_state, reason)
                else:
                    listener(old, new_state, reason)
            except Exception as e:
                logger.error(f"[GlobalState] 监听器异常: {e}")
    
    def get(self) -> SystemState:
        return self._state
    
    def get_reason(self) -> str:
        return self._reason
    
    # ---------- 状态行为矩阵（核心查询接口） ----------
    
    def is_trading_allowed(self) -> bool:
        """是否允许开新仓（仅RUNNING）"""
        return self._state == SystemState.RUNNING
    
    def is_close_allowed(self) -> bool:
        """是否允许平仓（RUNNING/DEGRADED/SOFT_BREAKER/HARD_BREAKER）"""
        return self._state in (
            SystemState.RUNNING,
            SystemState.DEGRADED,
            SystemState.SOFT_BREAKER,
            SystemState.HARD_BREAKER
        )
    
    def is_scan_allowed(self) -> bool:
        """是否允许扫描（RUNNING/DEGRADED-仅评估）"""
        return self._state in (SystemState.RUNNING, SystemState.DEGRADED)
    
    def is_decision_allowed(self) -> bool:
        """是否允许执行新决策（仅RUNNING）"""
        return self._state == SystemState.RUNNING
    
    # ---------- 辅助方法 ----------
    
    def add_listener(self, listener: Callable):
        self._listeners.append(listener)
    
    def get_history(self) -> List[Dict]:
        return list(self._state_history)
    
    def get_state_matrix(self) -> Dict:
        """获取当前状态的完整行为矩阵"""
        return {
            'state': self._state.value,
            'allow_scan': self.is_scan_allowed(),
            'allow_trade': self.is_trading_allowed(),
            'allow_close': self.is_close_allowed(),
            'allow_decision': self.is_decision_allowed()
        }


# ============================================================
# 2. 健康检查器
# ============================================================

@dataclass
class ModuleHealth:
    """模块健康状态"""
    name: str
    healthy: bool = True
    latency: float = 0.0
    last_check: float = 0.0
    error_count: int = 0
    last_error: str = ""
    consecutive_failures: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'healthy': self.healthy,
            'latency': round(self.latency, 4),
            'last_check': self.last_check,
            'error_count': self.error_count,
            'last_error': self.last_error,
            'consecutive_failures': self.consecutive_failures
        }


class HealthChecker:
    """
    健康检查器（基于asyncio模块级探针）
    
    每个核心模块注册一个健康检查函数，定期调用并记录结果。
    连续失败超过阈值时标记为不健康。
    """
    
    def __init__(self, check_interval: int = 30, max_consecutive_failures: int = 3):
        self.check_interval = check_interval
        self.max_consecutive_failures = max_consecutive_failures
        self.health_status: Dict[str, ModuleHealth] = {}
        self.check_funcs: Dict[str, Callable] = {}
        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}
    
    def register_module(self, name: str, check_func: Callable):
        """注册模块健康检查"""
        self.health_status[name] = ModuleHealth(name=name)
        self.check_funcs[name] = check_func
    
    async def start(self):
        """启动健康检查"""
        self._running = True
        for name, func in self.check_funcs.items():
            task = asyncio.create_task(self._check_loop(name, func))
            self._tasks[name] = task
        logger.debug(f"[HealthChecker] 启动，{len(self.check_funcs)} 个模块，间隔 {self.check_interval}s")
    
    async def stop(self):
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
    
    async def _check_loop(self, name: str, func: Callable):
        while self._running:
            try:
                start = time.time()
                ok = await func() if asyncio.iscoroutinefunction(func) else func()
                latency = time.time() - start
                
                health = self.health_status[name]
                health.latency = latency
                health.last_check = time.time()
                
                if ok:
                    health.healthy = True
                    health.consecutive_failures = 0
                else:
                    health.consecutive_failures += 1
                    health.error_count += 1
                    health.last_error = f"连续失败 {health.consecutive_failures} 次"
                    if health.consecutive_failures >= self.max_consecutive_failures:
                        health.healthy = False
            except Exception as e:
                health = self.health_status[name]
                health.healthy = False
                health.error_count += 1
                health.last_error = str(e)
                health.consecutive_failures += 1
            
            await asyncio.sleep(self.check_interval)
    
    def is_healthy(self, name: str) -> bool:
        return self.health_status.get(name, ModuleHealth(name="unknown")).healthy
    
    def get_unhealthy_modules(self) -> List[str]:
        return [n for n, h in self.health_status.items() if not h.healthy]
    
    def get_all_status(self) -> Dict[str, Dict]:
        return {n: h.to_dict() for n, h in self.health_status.items()}
    
    def get_health_score(self) -> float:
        if not self.health_status:
            return 100.0
        return sum(1 for h in self.health_status.values() if h.healthy) / len(self.health_status) * 100.0


# ============================================================
# 3. 内建探针模板
# ============================================================

class BuiltinProbes:
    """
    内建健康检查探针模板
    
    提供常用的健康检查函数，可直接注册到HealthChecker。
    """
    
    @staticmethod
    def websocket_probe(ws_client) -> Callable:
        """
        WebSocket健康检查探针
        
        检查：
        1. 连接是否活跃
        2. 最后一条消息时间 < 3秒
        """
        def check() -> bool:
            if not hasattr(ws_client, 'is_connected'):
                return False
            if not ws_client.is_connected:
                return False
            if hasattr(ws_client, 'last_message_time'):
                return (time.time() - ws_client.last_message_time) < 3.0
            return True
        return check
    
    @staticmethod
    def execution_probe(exec_engine, max_pending: int = 50) -> Callable:
        """
        执行引擎健康检查探针
        
        检查：
        1. 挂起订单数 < max_pending
        2. 最近无致命错误
        """
        def check() -> bool:
            pending = 0
            if hasattr(exec_engine, 'orders'):
                pending = sum(1 for o in exec_engine.orders.values()
                              if o.status.value in ('NEW', 'SUBMITTING', 'ACKNOWLEDGED'))
            if pending >= max_pending:
                return False
            if hasattr(exec_engine, 'last_fatal_error_time'):
                return (time.time() - exec_engine.last_fatal_error_time) > 60
            return True
        return check
    
    @staticmethod
    def risk_engine_probe(risk_engine) -> Callable:
        """
        风控引擎健康检查探针
        
        检查：
        1. 熔断器正常响应
        2. 无死锁标志
        """
        def check() -> bool:
            if hasattr(risk_engine, 'circuit_breaker'):
                cb = risk_engine.circuit_breaker
                if hasattr(cb, 'is_deadlocked') and cb.is_deadlocked:
                    return False
            return True
        return check
    
    @staticmethod
    def database_probe(db_manager) -> Callable:
        """
        数据库健康检查探针
        
        检查：
        1. 连接是否正常
        2. 最近查询是否成功
        """
        def check() -> bool:
            if hasattr(db_manager, 'is_connected'):
                return db_manager.is_connected
            return True
        return check


# ============================================================
# 4. 修复引擎
# ============================================================

class RepairEngine:
    """
    修复引擎
    
    自动检测不健康模块并尝试修复。
    每个模块可注册修复策略，修复失败时升级告警。
    支持5分钟内最多重试3次（可配置）。
    """
    
    def __init__(self, health_checker: HealthChecker, global_state: GlobalState,
                 repair_interval: int = 60, max_retries: int = 3):
        self.health_checker = health_checker
        self.global_state = global_state
        self.repair_interval = repair_interval
        self.max_retries = max_retries
        self.repair_strategies: Dict[str, Callable] = {}
        self.repair_history: List[Dict] = []
        self._running = False
        self._task = None
    
    def register_repair(self, name: str, repair_func: Callable):
        """注册修复策略"""
        self.repair_strategies[name] = repair_func
    
    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._repair_loop())
        logger.debug(f"[RepairEngine] 启动，间隔 {self.repair_interval}s")
    
    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
    
    async def _repair_loop(self):
        while self._running:
            try:
                unhealthy = self.health_checker.get_unhealthy_modules()
                for name in unhealthy:
                    if name in self.repair_strategies:
                        await self._try_repair(name)
                    else:
                        logger.debug(f"[RepairEngine] {name} 不健康但无修复策略")
                
                # 如果所有模块都不健康，触发全局降级
                if len(unhealthy) == len(self.health_checker.health_status) and len(unhealthy) > 0:
                    await self.global_state.set(SystemState.DEGRADED, "所有模块不健康，自动降级")
                
            except Exception as e:
                logger.debug(f"[RepairEngine] 修复循环异常: {e}")
            await asyncio.sleep(self.repair_interval)
    
    async def _try_repair(self, name: str) -> bool:
        """尝试修复模块"""
        # 5分钟内最多重试max_retries次
        recent = [r for r in self.repair_history
                  if r['name'] == name and time.time() - r['timestamp'] < 300]
        if len(recent) >= self.max_retries:
            return False
        
        logger.debug(f"[RepairEngine] 修复模块: {name}")
        try:
            func = self.repair_strategies[name]
            success = await func() if asyncio.iscoroutinefunction(func) else func()
            self.repair_history.append({'name': name, 'success': success, 'timestamp': time.time()})
            
            if success and name in self.health_checker.health_status:
                h = self.health_checker.health_status[name]
                h.consecutive_failures = 0
                h.healthy = True
                h.last_error = ""
            return success
        except Exception as e:
            self.repair_history.append({'name': name, 'success': False, 'error': str(e), 'timestamp': time.time()})
            return False
    
    async def force_repair(self, name: str) -> bool:
        if name not in self.repair_strategies:
            return False
        return await self._try_repair(name)
    
    def get_stats(self) -> Dict:
        total = len(self.repair_history)
        success = sum(1 for r in self.repair_history if r['success'])
        return {'total_repairs': total, 'successful': success, 'failed': total - success,
                'success_rate': success / total if total > 0 else 0}


# ============================================================
# 5. 内建修复策略模板
# ============================================================

class BuiltinRepairStrategies:
    """
    内建修复策略模板
    
    提供常用的修复函数，可直接注册到RepairEngine。
    """
    
    @staticmethod
    def websocket_reconnect(ws_client) -> Callable:
        """WebSocket重连修复策略"""
        async def repair() -> bool:
            try:
                if hasattr(ws_client, 'reconnect'):
                    await ws_client.reconnect()
                    return True
                elif hasattr(ws_client, 'connect'):
                    await ws_client.connect()
                    return True
            except Exception:
                return False
            return False
        return repair
    
    @staticmethod
    def execution_reset(exec_engine) -> Callable:
        """执行引擎重置修复策略"""
        async def repair() -> bool:
            try:
                if hasattr(exec_engine, 'cleanup'):
                    await exec_engine.cleanup()
                if hasattr(exec_engine, 'cancel_all_pending'):
                    await exec_engine.cancel_all_pending()
                return True
            except Exception:
                return False
        return repair
    
    @staticmethod
    def listenkey_renew(ws_client) -> Callable:
        """listenKey续期修复策略"""
        async def repair() -> bool:
            try:
                if hasattr(ws_client, 'renew_listen_key'):
                    await ws_client.renew_listen_key()
                    return True
            except Exception:
                return False
            return False
        return repair
    
    @staticmethod
    def database_reconnect(db_manager) -> Callable:
        """数据库重连修复策略"""
        async def repair() -> bool:
            try:
                if hasattr(db_manager, 'reconnect'):
                    db_manager.reconnect()
                    return True
            except Exception:
                return False
            return False
        return repair


# ============================================================
# 6. 任务调度器
# ============================================================

class Dispatcher:
    """
    任务调度器
    
    管理多symbol的并行交易闭环，根据全局状态控制任务执行。
    """
    
    def __init__(self, symbols: List[str], scan_interval: int = 60):
        self.symbols = symbols
        self.scan_interval = scan_interval
        self.tasks: Dict[str, asyncio.Task] = {}
        self.task_errors: Dict[str, int] = {}
        self._running = False
        self._global_state = GlobalState()
    
    async def start(self, loop_func: Callable):
        self._running = True
        self.loop_func = loop_func
        for symbol in self.symbols:
            task = asyncio.create_task(self._run_symbol(symbol))
            self.tasks[symbol] = task
        logger.debug(f"[Dispatcher] 启动，{len(self.symbols)} 个品种: {self.symbols}")
        try:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        except asyncio.CancelledError:
            pass
    
    async def _run_symbol(self, symbol: str):
        while self._running:
            state = self._global_state.get()
            
            if state in (SystemState.HARD_BREAKER, SystemState.STOPPED):
                break
            if state in (SystemState.PAUSED, SystemState.SOFT_BREAKER):
                await asyncio.sleep(1)
                continue
            
            try:
                await self.loop_func(symbol)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.task_errors[symbol] = self.task_errors.get(symbol, 0) + 1
                logger.debug(f"[Dispatcher] {symbol} 闭环错误: {e}")
                if self.task_errors[symbol] >= 10:
                    logger.debug(f"[Dispatcher] {symbol} 错误过多，暂停")
                    break
            
            await asyncio.sleep(self.scan_interval)
    
    async def stop(self):
        self._running = False
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()
    
    def get_status(self) -> Dict:
        return {
            'running': self._running,
            'symbols': self.symbols,
            'active_tasks': len([t for t in self.tasks.values() if not t.done()]),
            'error_counts': dict(self.task_errors)
        }


# ============================================================
# 7. 性能优化器（在线调参 + 离线搜索触发）
# ============================================================

class PerformanceOptimizer:
    """
    性能优化器
    
    在线调参：每20笔交易微调信号阈值和策略权重
    离线搜索：每周触发Optuna搜索（调用第10层self_optimization_system.py）
    性能监控：闭环耗时超200ms自动降频
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.metrics: deque = deque(maxlen=1000)
        self.trade_results: deque = deque(maxlen=100)
        self.optimization_history: List[Dict] = []
        
        # 在线调参参数
        self.signal_threshold = self.config.get('signal_threshold', 0.6)
        self.scan_interval = self.config.get('scan_interval', 60)
        self.max_concurrent_symbols = self.config.get('max_concurrent_symbols', 4)
        
        self._running = False
        self._task = None
    
    def record_metric(self, metric: Dict):
        """记录性能指标"""
        metric['timestamp'] = time.time()
        self.metrics.append(metric)
    
    def record_trade(self, trade: Dict):
        """记录交易结果（用于在线调参）"""
        trade['timestamp'] = time.time()
        self.trade_results.append(trade)
        
        # 每完成20笔交易触发在线微调
        if len(self.trade_results) % 20 == 0:
            self._online_tune()
    
    async def start(self, tune_interval: int = 300):
        self._running = True
        self._tune_interval = tune_interval
        self._task = asyncio.create_task(self._tune_loop())
        logger.debug(f"[PerformanceOptimizer] 启动，调参间隔 {tune_interval}s")
    
    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
    
    async def _tune_loop(self):
        """定期性能分析和参数调整"""
        while self._running:
            try:
                self._performance_tune()
            except Exception as e:
                logger.debug(f"[PerformanceOptimizer] 调参异常: {e}")
            await asyncio.sleep(self._tune_interval)
    
    def _online_tune(self):
        """在线微调（每20笔交易触发一次）"""
        if len(self.trade_results) < 20:
            return
        
        recent = list(self.trade_results)[-20:]
        wins = sum(1 for t in recent if t.get('pnl', 0) > 0)
        win_rate = wins / len(recent)
        avg_pnl = sum(t.get('pnl', 0) for t in recent) / len(recent)
        
        adjustments = []
        
        # 胜率低于55%时提高信号阈值
        if win_rate < 0.55:
            old_threshold = self.signal_threshold
            self.signal_threshold = min(0.8, self.signal_threshold + 0.02)
            adjustments.append(f"信号阈值 {old_threshold:.2f} -> {self.signal_threshold:.2f}")
        
        # 胜率高于70%时降低信号阈值（增加交易机会）
        elif win_rate > 0.70:
            old_threshold = self.signal_threshold
            self.signal_threshold = max(0.5, self.signal_threshold - 0.02)
            adjustments.append(f"信号阈值 {old_threshold:.2f} -> {self.signal_threshold:.2f}")
        
        if adjustments:
            self.optimization_history.append({
                'type': 'online',
                'win_rate': win_rate,
                'adjustments': adjustments,
                'timestamp': time.time()
            })
            logger.debug(f"[PerformanceOptimizer] 在线微调: 胜率={win_rate:.1%}, {', '.join(adjustments)}")
    
    def _performance_tune(self):
        """定期性能分析"""
        if len(self.metrics) < 10:
            return
        
        recent = list(self.metrics)[-100:]
        recommendations = []
        
        # 闭环耗时分析
        loop_times = [m.get('loop_time_ms', 0) for m in recent if 'loop_time_ms' in m]
        if loop_times:
            avg_loop_time = sum(loop_times) / len(loop_times)
            if avg_loop_time > 200:
                old_interval = self.scan_interval
                self.scan_interval = min(120, self.scan_interval + 10)
                recommendations.append(f"扫描间隔 {old_interval}s -> {self.scan_interval}s (闭环耗时{avg_loop_time:.0f}ms)")
        
        # 错误率分析
        errors = [m.get('error', False) for m in recent]
        if errors:
            error_rate = sum(1 for e in errors if e) / len(errors)
            if error_rate > 0.1:
                old_max = self.max_concurrent_symbols
                self.max_concurrent_symbols = max(1, self.max_concurrent_symbols - 1)
                recommendations.append(f"并行品种 {old_max} -> {self.max_concurrent_symbols} (错误率{error_rate:.1%})")
        
        if recommendations:
            self.optimization_history.append({
                'type': 'performance',
                'recommendations': recommendations,
                'timestamp': time.time()
            })
            logger.debug(f"[PerformanceOptimizer] 性能调参: {', '.join(recommendations)}")
    
    def get_current_params(self) -> Dict:
        """获取当前优化后的参数"""
        return {
            'signal_threshold': self.signal_threshold,
            'scan_interval': self.scan_interval,
            'max_concurrent_symbols': self.max_concurrent_symbols
        }
    
    def get_stats(self) -> Dict:
        return {
            'total_optimizations': len(self.optimization_history),
            'metrics_count': len(self.metrics),
            'trades_count': len(self.trade_results),
            'current_params': self.get_current_params(),
            'recent_optimizations': self.optimization_history[-5:] if self.optimization_history else []
        }


# ============================================================
# 8. 总控中心
# ============================================================

class GlobalController:
    """
    总控中心
    
    整合全局状态管理、健康检查、修复引擎、任务调度、性能优化。
    提供统一的启动/停止/状态查询接口。
    """
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        
        # 核心组件
        self.global_state = GlobalState()
        self.health_checker = HealthChecker(
            check_interval=self.config.get('health_check_interval', 30),
            max_consecutive_failures=self.config.get('max_consecutive_failures', 3)
        )
        self.repair_engine = RepairEngine(
            health_checker=self.health_checker,
            global_state=self.global_state,
            repair_interval=self.config.get('repair_interval', 60),
            max_retries=self.config.get('max_repair_retries', 3)
        )
        self.performance_optimizer = PerformanceOptimizer(
            config=self.config.get('optimizer', {})
        )
        self.dispatcher: Optional[Dispatcher] = None
        
        self._running = False
        self._start_time = 0
        
        # 告警系统
        self.active_alerts: List[Dict] = []
        self.alert_history: deque = deque(maxlen=1000)
        
        # 注册全局状态监听器
        self.global_state.add_listener(self._on_state_change)
    
    async def _on_state_change(self, old_state: SystemState, new_state: SystemState, reason: str):
        """全局状态变更回调"""
        if new_state == SystemState.SOFT_BREAKER:
            self._create_alert('WARNING', f"软熔断: {reason}", 'GlobalState')
        elif new_state == SystemState.HARD_BREAKER:
            self._create_alert('CRITICAL', f"硬熔断: {reason}", 'GlobalState')
            if self.dispatcher:
                await self.dispatcher.stop()
        elif new_state == SystemState.DEGRADED:
            self._create_alert('WARNING', f"系统降级: {reason}", 'GlobalState')
        elif new_state == SystemState.RUNNING and old_state in (
            SystemState.SOFT_BREAKER, SystemState.DEGRADED, SystemState.PAUSED
        ):
            self._create_alert('INFO', "系统恢复运行", 'GlobalState')
    
    def register_module_health(self, name: str, check_func: Callable, repair_func: Optional[Callable] = None):
        """注册模块健康检查和修复策略"""
        self.health_checker.register_module(name, check_func)
        if repair_func:
            self.repair_engine.register_repair(name, repair_func)
    
    async def start(self):
        """启动总控中心"""
        self._running = True
        self._start_time = time.time()
        
        await self.global_state.set(SystemState.RUNNING, "总控中心启动")
        await self.health_checker.start()
        await self.repair_engine.start()
        await self.performance_optimizer.start(
            tune_interval=self.config.get('tune_interval', 300)
        )
        
        logger.debug(f"\n{'='*60}")
        logger.debug(f"  杀手锏交易系统 V6.1 - 总控中心已启动")
        logger.debug(f"{'='*60}")
        logger.debug(f"  系统状态: {self.global_state.get().value}")
        logger.debug(f"  健康检查: {self.config.get('health_check_interval', 30)}s")
        logger.debug(f"  修复引擎: {self.config.get('repair_interval', 60)}s")
        logger.debug(f"  注册模块: {len(self.health_checker.check_funcs)}")
        logger.debug(f"  修复策略: {len(self.repair_engine.repair_strategies)}")
        logger.debug(f"{'='*60}\n")
    
    async def stop(self):
        """停止总控中心"""
        self._running = False
        await self.global_state.set(SystemState.STOPPED, "总控中心停止")
        await self.health_checker.stop()
        await self.repair_engine.stop()
        await self.performance_optimizer.stop()
        if self.dispatcher:
            await self.dispatcher.stop()
        logger.debug("[GlobalController] 总控中心已停止")
    
    async def pause(self):
        """手动暂停"""
        await self.global_state.set(SystemState.PAUSED, "手动暂停")
    
    async def resume(self):
        """手动恢复"""
        await self.global_state.set(SystemState.RUNNING, "手动恢复")
    
    async def trigger_soft_breaker(self, reason: str = "外部触发"):
        await self.global_state.set(SystemState.SOFT_BREAKER, reason)
    
    async def trigger_hard_breaker(self, reason: str = "外部触发"):
        await self.global_state.set(SystemState.HARD_BREAKER, reason)
    
    def _create_alert(self, severity: str, message: str, component: str):
        alert = {'severity': severity, 'message': message, 'component': component, 'timestamp': time.time()}
        self.active_alerts.append(alert)
        self.alert_history.append(alert)
        logger.debug(f"[Alert][{severity}] {component}: {message}")
    
    def get_status(self) -> Dict:
        """获取系统完整状态"""
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            'system_state': self.global_state.get().value,
            'state_reason': self.global_state.get_reason(),
            'state_matrix': self.global_state.get_state_matrix(),
            'uptime_seconds': round(uptime, 1),
            'health_score': self.health_checker.get_health_score(),
            'modules': self.health_checker.get_all_status(),
            'unhealthy_modules': self.health_checker.get_unhealthy_modules(),
            'repair_stats': self.repair_engine.get_stats(),
            'optimizer_stats': self.performance_optimizer.get_stats(),
            'optimizer_params': self.performance_optimizer.get_current_params(),
            'active_alerts': len(self.active_alerts),
            'alert_history_count': len(self.alert_history),
            'dispatcher_status': self.dispatcher.get_status() if self.dispatcher else None
        }
    
    def print_status(self):
        """打印系统状态"""
        status = self.get_status()
        sm = status['state_matrix']
        logger.info(f"\n{'='*60}")
        logger.info(f"  杀手锏交易系统 V6.1 - 系统状态")
        logger.info(f"{'='*60}")
        logger.info(f"  状态: {status['system_state']} ({status['state_reason']})")
        logger.info(f"  运行: {status['uptime_seconds']}s | 健康: {status['health_score']:.0f}%")
        scan_text = 'Yes' if sm['allow_scan'] else 'No '
        trade_text = 'Yes' if sm['allow_trade'] else 'No '
        close_text = 'Yes' if sm['allow_close'] else 'No '
        decision_text = 'Yes' if sm['allow_decision'] else 'No '
        logger.info(f"  扫描:{scan_text} 开仓:{trade_text} 平仓:{close_text} 决策:{decision_text}")
        threshold_text = f"{status['optimizer_params']['signal_threshold']:.2f}"
        interval_text = f"{status['optimizer_params']['scan_interval']}s"
        logger.info(f"  优化参数: 信号阈值={threshold_text}, 扫描间隔={interval_text}")
        
        modules = status['modules']
        if modules:
            logger.info(f"  模块健康:")
            for name, h in modules.items():
                icon = "OK" if h['healthy'] else "NG"
                logger.info(f"    [{icon}] {name}: {h['latency']}ms, err={h['error_count']}")

        if status['unhealthy_modules']:
            logger.info(f"  不健康: {status['unhealthy_modules']}")
        logger.info(f"{'='*60}\n")


# ============================================================
# 命令行接口
# ============================================================

async def demo():
    """演示总控中心"""
    config = {
        'health_check_interval': 10,
        'repair_interval': 30,
        'max_consecutive_failures': 3,
        'max_repair_retries': 3,
        'tune_interval': 60,
        'optimizer': {'signal_threshold': 0.6, 'scan_interval': 60, 'max_concurrent_symbols': 4}
    }
    
    controller = GlobalController(config)
    
    # 注册模块健康检查
    controller.register_module_health("market_scanner", lambda: True, lambda: True)
    controller.register_module_health("execution_engine", lambda: True, lambda: True)
    controller.register_module_health("risk_engine", lambda: True)
    controller.register_module_health("ev_filter", lambda: True)
    controller.register_module_health("order_lifecycle", lambda: True)
    
    await controller.start()
    
    for i in range(3):
        await asyncio.sleep(10)
        controller.print_status()
    
    await controller.stop()


def main():
    parser = argparse.ArgumentParser(description="杀手锏交易系统 V6.1 - 总控中心")
    parser.add_argument('--action', choices=['start', 'status', 'demo'], default='demo')
    parser.add_argument('--config', type=str, default='assets/configs/killer_config_v60.json')
    args = parser.parse_args()
    
    if args.action == 'demo':
        asyncio.run(demo())
    elif args.action == 'status':
        GlobalController().print_status()
    else:
        logger.debug("请使用 main_v61.py --mode v61 启动完整系统")


if __name__ == "__main__":
    main()
