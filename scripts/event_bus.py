#!/usr/bin/env python3
"""
统一事件总线 - Phase 5.5 P0
解耦模块间通信，支持发布/订阅模式
"""

import json
import time
from typing import Callable, Dict, List, Optional, Any
from collections import defaultdict
from threading import Lock
from dataclasses import dataclass, asdict
from datetime import datetime

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("event_bus")
except ImportError:
    import logging
    logger = logging.getLogger("event_bus")


@dataclass
class Event:
    """事件数据结构"""
    event_type: str
    payload: Dict[str, Any]
    timestamp: float
    source: Optional[str] = None
    event_id: Optional[str] = None

    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)


class EventBus:
    """
    统一事件总线

    特性：
    - 线程安全的发布/订阅机制
    - 异步事件传播（避免阻塞）
    - 事件历史记录（用于调试和审计）
    - 订阅者异常隔离（单一订阅者失败不影响其他订阅者）
    """

    # 标准化事件类型
    STANDARD_EVENT_TYPES = {
        # 系统状态事件
        "state.changed": "系统状态变更",
        "state.recovery_started": "系统恢复开始",
        "state.recovery_completed": "系统恢复完成",
        "health.degraded": "系统健康降级",
        "health.recovered": "系统健康恢复",

        # 系统故障事件
        "system.component_failure": "组件故障检测",
        "system.latency_high": "组件延迟过高",
        "system.resource_critical": "系统资源告急",

        # 市场数据事件
        "market.scan_completed": "市场扫描完成",
        "market.data_received": "市场数据接收",
        "market.high_volatility_detected": "高波动市场检测",

        # 信号事件
        "signal.generated": "信号生成",
        "signal.filtered": "信号过滤",
        "signal.accepted": "信号接受",
        "signal.rejected": "信号拒绝",

        # 决策事件
        "decision.made": "决策制定",
        "decision.cancelled": "决策取消",

        # 风控事件
        "risk.check_passed": "风控检查通过",
        "risk.limit_breached": "风控阈值突破",
        "risk.block_signal": "风控阻止信号",

        # 订单事件
        "order.created": "订单创建",
        "order.acknowledged": "订单确认",
        "order.submitted": "订单提交",
        "order.filled": "订单成交",
        "order.partially_filled": "订单部分成交",
        "order.cancelled": "订单取消",
        "order.rejected": "订单拒绝",
        "order.failed": "订单失败",

        # 持仓事件
        "position.opened": "持仓开立",
        "position.closed": "持仓关闭",
        "position.modified": "持仓修改",

        # 修复事件
        "repair.attempted": "修复尝试",
        "repair.succeeded": "修复成功",
        "repair.failed": "修复失败",
        "repair.escalated": "修复升级",

        # 配置事件
        "config.reloaded": "配置重新加载",
        "config.changed": "配置变更",

        # 优化事件
        "optimization.started": "参数优化开始",
        "optimization.completed": "参数优化完成",
        "optimization.failed": "参数优化失败",

        # 组合优化事件
        "hrp.weights_computed": "HRP权重计算完成",
        "erc.weights_computed": "ERC权重计算完成",
        "backtest.started": "回测开始",
        "backtest.completed": "回测完成",

        # 元学习事件
        "meta.update_completed": "元学习参数更新完成",
        "meta.adaptation_completed": "策略快速适应完成",

        # 过拟合检测事件
        "overfitting.detected": "过拟合检测完成",
        "overfitting.safe": "过拟合检测通过"
    }

    def __init__(self, enable_history: bool = True, max_history: int = 1000):
        """
        初始化事件总线

        Args:
            enable_history: 是否启用事件历史记录
            max_history: 最大历史记录数量
        """
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = Lock()
        self._event_history: List[Event] = []
        self._enable_history = enable_history
        self._max_history = max_history
        self._event_counter = 0
        self._stats = {
            "total_published": 0,
            "total_subscribers": 0,
            "failed_deliveries": 0,
            "event_type_counts": defaultdict(int)
        }

        logger.info("事件总线初始化完成，支持事件类型: %d", len(self.STANDARD_EVENT_TYPES))

    def subscribe(self, event_type: str, callback: Callable[[Event], None]) -> str:
        """
        订阅事件

        Args:
            event_type: 事件类型
            callback: 回调函数，接收Event对象

        Returns:
            订阅ID
        """
        try:
            # 第一层防御：参数校验
            if not callable(callback):
                logger.error("订阅失败: 回调函数不可调用 (event_type=%s)", event_type)
                return ""

            if not event_type:
                logger.error("订阅失败: 事件类型为空")
                return ""

            with self._lock:
                self._subscribers[event_type].append(callback)
                self._stats["total_subscribers"] += 1

                logger.debug("订阅成功: event_type=%s, 总订阅者=%d",
                           event_type, len(self._subscribers[event_type]))

                return f"{event_type}_{len(self._subscribers[event_type])}"

        except Exception as e:
            logger.error(f"订阅异常: {e}")
            return ""

    def unsubscribe(self, event_type: str, callback: Callable) -> bool:
        """
        取消订阅

        Args:
            event_type: 事件类型
            callback: 回调函数

        Returns:
            是否成功
        """
        try:
            with self._lock:
                if callback in self._subscribers[event_type]:
                    self._subscribers[event_type].remove(callback)
                    self._stats["total_subscribers"] -= 1
                    logger.debug("取消订阅成功: event_type=%s", event_type)
                    return True
                return False

        except Exception as e:
            logger.error(f"取消订阅异常: {e}")
            return False

    def publish(self, event_type: str, payload: Dict[str, Any], source: Optional[str] = None) -> Event:
        """
        发布事件

        Args:
            event_type: 事件类型
            payload: 事件数据
            source: 事件来源（模块名）

        Returns:
            创建的Event对象
        """
        try:
            # 第一层防御：参数校验
            if not event_type:
                logger.error("发布失败: 事件类型为空")
                return None

            # 允许None payload通过，其他类型必须为dict
            if payload is not None and not isinstance(payload, dict):
                logger.error("发布失败: payload必须是字典类型或None")
                return None

            # 验证事件类型是否标准（仅警告）
            if event_type not in self.STANDARD_EVENT_TYPES:
                logger.warning("非标准事件类型: %s (标准类型数: %d)",
                            event_type, len(self.STANDARD_EVENT_TYPES))

            # 创建事件对象
            self._event_counter += 1
            event = Event(
                event_type=event_type,
                payload=payload,
                timestamp=time.time(),
                source=source,
                event_id=f"evt_{int(time.time())}_{self._event_counter}"
            )

            # 记录历史
            if self._enable_history:
                self._add_to_history(event)

            # 更新统计
            self._stats["total_published"] += 1
            self._stats["event_type_counts"][event_type] += 1

            # 获取订阅者
            with self._lock:
                subscribers = self._subscribers[event_type].copy()

            # 第二层防御：通知订阅者（异常隔离）
            delivered_count = 0
            for callback in subscribers:
                try:
                    callback(event)
                    delivered_count += 1
                except Exception as e:
                    logger.error(f"事件投递失败: event_type={event_type}, subscriber={callback.__name__}, error={e}")
                    self._stats["failed_deliveries"] += 1

            logger.debug("事件发布: type=%s, subscribers=%d, delivered=%d, source=%s",
                       event_type, len(subscribers), delivered_count, source)

            return event

        except Exception as e:
            logger.error(f"发布事件异常: {e}")
            return None

    def _add_to_history(self, event: Event):
        """
        添加事件到历史记录

        Args:
            event: 事件对象
        """
        try:
            self._event_history.append(event)

            # 第三层防御：限制历史记录大小
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)

        except Exception as e:
            logger.error(f"添加历史记录异常: {e}")

    def get_history(self, event_type: Optional[str] = None, limit: int = 100) -> List[Event]:
        """
        获取事件历史

        Args:
            event_type: 过滤事件类型（None表示全部）
            limit: 返回数量限制

        Returns:
            事件列表
        """
        try:
            with self._lock:
                if event_type:
                    filtered = [e for e in self._event_history if e.event_type == event_type]
                    return filtered[-limit:] if filtered else []
                else:
                    return self._event_history[-limit:] if self._event_history else []

        except Exception as e:
            logger.error(f"获取历史记录异常: {e}")
            return []

    def get_stats(self) -> Dict:
        """
        获取统计信息

        Returns:
            统计字典
        """
        try:
            with self._lock:
                return {
                    **self._stats,
                    "event_type_counts": dict(self._stats["event_type_counts"]),
                    "active_subscriptions": {
                        event_type: len(subs)
                        for event_type, subs in self._subscribers.items()
                        if subs
                    },
                    "history_size": len(self._event_history)
                }

        except Exception as e:
            logger.error(f"获取统计信息异常: {e}")
            return {}

    def clear_history(self) -> None:
        """清空历史记录"""
        try:
            with self._lock:
                self._event_history.clear()
                logger.info("事件历史已清空")

        except Exception as e:
            logger.error(f"清空历史记录异常: {e}")

    def get_subscribers_count(self, event_type: Optional[str] = None) -> int:
        """
        获取订阅者数量

        Args:
            event_type: 事件类型（None表示全部）

        Returns:
            订阅者数量
        """
        try:
            with self._lock:
                if event_type:
                    return len(self._subscribers.get(event_type, []))
                else:
                    return sum(len(subs) for subs in self._subscribers.values())

        except Exception as e:
            logger.error(f"获取订阅者数量异常: {e}")
            return 0

    def close(self) -> None:
        """关闭事件总线，清理所有订阅和历史记录"""
        try:
            with self._lock:
                self._subscribers.clear()
                self._event_history.clear()
            logger.info("[事件总线] 已关闭")
        except Exception as e:
            logger.error(f"关闭事件总线异常: {e}")


# 全局事件总线实例
_global_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """
    获取全局事件总线实例（单例模式）

    Returns:
        EventBus实例
    """
    global _global_event_bus

    try:
        if _global_event_bus is None:
            _global_event_bus = EventBus()
        return _global_event_bus

    except Exception as e:
        logger.error(f"获取全局事件总线异常: {e}")
        raise


def reset_event_bus() -> None:
    """重置全局事件总线（主要用于测试）"""
    global _global_event_bus
    _global_event_bus = None


if __name__ == "__main__":
    # 测试代码
    def on_state_changed(event):
        print(f"[订阅者1] 状态变更: {event.payload}")

    def on_state_changed_2(event):
        print(f"[订阅者2] 状态变更: {event.payload}")

    # 获取事件总线
    bus = get_event_bus()

    # 订阅事件
    bus.subscribe("state.changed", on_state_changed)
    bus.subscribe("state.changed", on_state_changed_2)

    # 发布事件
    bus.publish("state.changed", {"from": "RUNNING", "to": "DEGRADED", "reason": "test"})

    # 获取历史
    history = bus.get_history("state.changed")
    print(f"\n历史记录数: {len(history)}")

    # 获取统计
    stats = bus.get_stats()
    print(f"统计信息: {json.dumps(stats, indent=2, ensure_ascii=False)}")

