#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DAG执行引擎 - Phase DAG v1.0
支持交易流水线节点并行执行与条件守卫
"""

from typing import Dict, List, Any, Callable, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import time
from concurrent.futures import ThreadPoolExecutor, Future, wait

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("dag_engine")
except ImportError:
    import logging
    logger = logging.getLogger("dag_engine")


class NodeState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class DAGNode:
    name: str
    fn: Callable
    dependencies: Set[str] = field(default_factory=set)
    guards: List[str] = field(default_factory=list)
    timeout: float = 5.0
    critical: bool = False
    state: NodeState = NodeState.PENDING
    result: Any = None
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    def duration_ms(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


class DAGExecutionEngine:
    """
    DAG执行引擎

    支持:
    - 拓扑排序自动解析依赖
    - 无依赖节点并行执行(线程池)
    - 状态守卫(自动跳过不满足条件的节点)
    - 超时控制
    - 熔断机制(任一critical节点失败则终止DAG)
    """

    def __init__(self, max_workers: int = 4,
                 global_state_getter: Optional[Callable] = None):
        self.nodes: Dict[str, DAGNode] = {}
        self.max_workers = max_workers
        self.global_state_getter = global_state_getter or (lambda: "RUNNING")
        self._log: List[Dict] = []

    def add_node(self, name: str, fn: Callable,
                 dependencies: List[str] = None,
                 guards: List[str] = None,
                 timeout: float = 5.0,
                 critical: bool = False) -> 'DAGExecutionEngine':
        self.nodes[name] = DAGNode(
            name=name, fn=fn,
            dependencies=set(dependencies or []),
            guards=guards or ["RUNNING", "DEGRADED", "CIRCUIT_BROKEN"],
            timeout=timeout, critical=critical
        )
        return self

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """执行DAG,返回{node_name: result}"""
        self._log = []
        for node in self.nodes.values():
            node.state = NodeState.PENDING
            node.result = None
            node.error = None

        results: Dict[str, Any] = {}
        completed: Set[str] = set()
        circuit_broken = False

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            pending_futures: Dict[str, Future] = {}

            while len(completed) < len(self.nodes) and not circuit_broken:
                state = self.global_state_getter()
                if state == "CIRCUIT_BROKEN":
                    break

                # 提交当前可执行的所有节点
                for node_name, node in self.nodes.items():
                    if node_name in completed or node_name in pending_futures:
                        continue
                    deps_met = all(d in completed for d in node.dependencies)
                    if not deps_met:
                        continue
                    if state not in node.guards:
                        node.state = NodeState.SKIPPED
                        completed.add(node_name)
                        continue

                    node.state = NodeState.RUNNING
                    node.start_time = time.time()
                    pending_futures[node_name] = pool.submit(
                        self._run_node, node, context, results
                    )

                # 等待任意一个节点完成
                if not pending_futures:
                    break

                # 使用wait直到至少一个完成
                done_futs, _ = wait(list(pending_futures.values()), timeout=0.05, return_when='FIRST_COMPLETED')
                if not done_futs:
                    continue

                done_names = {n for n, f in pending_futures.items() if f in done_futs}
                for name in done_names:
                    fut = pending_futures.pop(name)
                    node = self.nodes[name]
                    try:
                        results[name] = fut.result(timeout=node.timeout)
                        node.state = NodeState.COMPLETED
                        completed.add(name)
                    except Exception as e:
                        node.state = NodeState.FAILED
                        node.error = str(e)
                        logger.error(f"[DAG] Node '{name}' failed: {e}")
                        if node.critical:
                            circuit_broken = True
                    finally:
                        node.end_time = time.time()
                        self._log.append({
                            'node': node.name, 'state': node.state.value,
                            'duration_ms': node.duration_ms(), 'error': node.error
                        })

            # 取消未完成的非critical节点
            for name, fut in pending_futures.items():
                node = self.nodes[name]
                if not node.critical:
                    fut.cancel()
                    node.state = NodeState.SKIPPED
                    completed.add(name)
                else:
                    try:
                        results[name] = fut.result(timeout=1.0)
                        node.state = NodeState.COMPLETED
                    except Exception as e:
                        node.state = NodeState.FAILED
                        node.error = str(e)
                    node.end_time = time.time()

        return results

    def _run_node(self, node: DAGNode,
                  context: Dict, results: Dict) -> Any:
        """执行单个节点"""
        try:
            result = node.fn(context, results)
            return result
        except Exception as e:
            raise RuntimeError(f"{e}") from e

    def _topological_sort(self) -> List[List[str]]:
        """Kahn算法,返回按层级分组的节点名列表"""
        in_degree = {name: len(n.dependencies) for name, n in self.nodes.items()}
        levels: List[List[str]] = []
        remaining = set(self.nodes.keys())

        while remaining:
            current = sorted([n for n in remaining if in_degree[n] == 0])
            if not current:
                break
            levels.append(current)
            remaining -= set(current)
            for node_name in current:
                for other_name, other_node in self.nodes.items():
                    if node_name in other_node.dependencies:
                        in_degree[other_name] -= 1

        return levels

    def get_stats(self) -> Dict[str, Any]:
        total = len(self.nodes)
        completed = sum(1 for n in self.nodes.values() if n.state == NodeState.COMPLETED)
        failed = sum(1 for n in self.nodes.values() if n.state == NodeState.FAILED)
        skipped = sum(1 for n in self.nodes.values() if n.state == NodeState.SKIPPED)
        total_ms = sum(n.duration_ms() for n in self.nodes.values() if n.end_time)
        return {
            'total_nodes': total,
            'completed': completed,
            'failed': failed,
            'skipped': skipped,
            'total_duration_ms': total_ms,
            'avg_node_ms': total_ms / max(completed, 1)
        }

    def get_execution_log(self) -> List[Dict]:
        return self._log


# ============================================================
# 标准交易流水线DAG工厂
# ============================================================

def create_trading_dag(
    calculate_indicators_fn: Callable = None,
    generate_signal_fn: Callable = None,
    risk_check_fn: Callable = None,
    market_scan_fn: Callable = None,
    monitor_positions_fn: Callable = None,
    state_getter: Callable = None,
) -> DAGExecutionEngine:
    """创建标准交易流水线DAG"""
    dag = DAGExecutionEngine(
        max_workers=4,
        global_state_getter=state_getter or (lambda: "RUNNING")
    )

    if calculate_indicators_fn:
        dag.add_node("calculate_indicators", calculate_indicators_fn,
                     guards=["RUNNING", "DEGRADED"], critical=True)

    if generate_signal_fn:
        dag.add_node("generate_signal", generate_signal_fn,
                     dependencies=["calculate_indicators"],
                     guards=["RUNNING"], critical=True)

    if risk_check_fn:
        dag.add_node("risk_check", risk_check_fn,
                     dependencies=["generate_signal"],
                     guards=["RUNNING", "DEGRADED"], critical=True)

    if market_scan_fn:
        dag.add_node("market_scan", market_scan_fn,
                     guards=["RUNNING", "DEGRADED"], timeout=3.0)

    if monitor_positions_fn:
        dag.add_node("monitor_positions", monitor_positions_fn,
                     dependencies=[],
                     guards=["RUNNING", "DEGRADED", "CIRCUIT_BROKEN"],
                     timeout=2.0)

    return dag


if __name__ == "__main__":
    import time as t

    def stage_a(_ctx, _results):
        t.sleep(0.05)
        return 1  # 简单值,非dict

    def stage_b(_ctx, results):
        assert "a" in results
        t.sleep(0.05)
        return results["a"] + 1

    def stage_c(_ctx, results):
        assert "a" in results
        t.sleep(0.05)
        return results["a"] + 2

    def stage_d(_ctx, results):
        assert "b" in results and "c" in results
        return results["b"] + results["c"]

    dag = DAGExecutionEngine()
    dag.add_node("a", stage_a, guards=["RUNNING"])
    dag.add_node("b", stage_b, dependencies=["a"], guards=["RUNNING"])
    dag.add_node("c", stage_c, dependencies=["a"], guards=["RUNNING"])
    dag.add_node("d", stage_d, dependencies=["b", "c"], guards=["RUNNING"])

    results = dag.execute({})
    stats = dag.get_stats()

    print(f"DAG Stats: {stats}")
    print(f"Results: b={results.get('b')}, c={results.get('c')}, d={results.get('d')}")
    assert stats['completed'] == 4, f"Expected 4, got {stats['completed']}"
    assert results['d'] == 5, f"Expected 5, got {results['d']}"
    print("[PASS] DAG Execution Engine test")
