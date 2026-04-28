#!/usr/bin/env python3
"""
订单生命周期管理模块 — V6.3 加固版
管理订单从创建到终结的完整状态机,确保幂等性/防重/超时撤单

V6.3 加固:
- 全量 print→logging 迁移
- 状态转换校验: 非法转换被拒绝并记录
- fill_order/cancel_order/reject_order 统计bug修复(先检查旧状态再更新)
- 所有关键操作添加 try-except
- 输入参数边界校验
"""

import argparse
import hashlib
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("order_lifecycle")
except ImportError:
    import logging
    logger = logging.getLogger("order_lifecycle")

# 导入统一事件总线
try:
    from scripts.event_bus import get_event_bus, Event
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False


# ============================================================
# 1. 订单状态定义
# ============================================================

class OrderState(Enum):
    NEW = "NEW"
    SUBMITTING = "SUBMITTING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


# 合法状态转换表
_VALID_TRANSITIONS: Dict[OrderState, Set[OrderState]] = {
    OrderState.NEW: {OrderState.SUBMITTING, OrderState.CANCELLED, OrderState.EXPIRED},
    OrderState.SUBMITTING: {OrderState.ACKNOWLEDGED, OrderState.REJECTED, OrderState.FAILED, OrderState.CANCELLED},
    OrderState.ACKNOWLEDGED: {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCEL_REQUESTED, OrderState.CANCELLED, OrderState.EXPIRED},
    OrderState.PARTIALLY_FILLED: {OrderState.FILLED, OrderState.CANCEL_REQUESTED, OrderState.CANCELLED, OrderState.EXPIRED},
    OrderState.FILLED: set(),  # 终态
    OrderState.CANCEL_REQUESTED: {OrderState.CANCELLED, OrderState.PARTIALLY_FILLED, OrderState.FILLED},
    OrderState.CANCELLED: set(),  # 终态
    OrderState.REJECTED: set(),  # 终态
    OrderState.EXPIRED: set(),  # 终态
    OrderState.FAILED: set(),  # 终态
}

TERMINAL_STATES = {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED,
                   OrderState.EXPIRED, OrderState.FAILED}


# ============================================================
# 2. 订单数据结构
# ============================================================

@dataclass
class Order:
    """订单数据"""
    order_id: str
    client_order_id: str
    symbol: str
    side: str          # BUY/SELL
    order_type: str    # LIMIT/MARKET
    quantity: float
    price: float = 0.0
    state: OrderState = OrderState.NEW
    filled_quantity: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0
    ttl_ms: int = 800
    error: str = ""
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.updated_at == 0.0:
            self.updated_at = self.created_at

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, self.quantity - self.filled_quantity)

    def to_dict(self) -> Dict:
        return {
            'order_id': self.order_id,
            'client_order_id': self.client_order_id,
            'symbol': self.symbol,
            'side': self.side,
            'order_type': self.order_type,
            'quantity': self.quantity,
            'price': self.price,
            'state': self.state.value,
            'filled_quantity': self.filled_quantity,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'ttl_ms': self.ttl_ms,
            'error': self.error,
        }


# ============================================================
# 3. 订单生命周期管理器
# ============================================================

class OrderLifecycleManager:
    """
    订单生命周期管理器

    核心功能:
    1. 幂等性: clientOrderId = 时间戳+UUID+哈希
    2. 去重: 300s TTL缓存
    3. 状态机: 10种状态 + 合法转换校验
    4. 超时撤单: 800ms TTL
    5. 防御性错误处理: 所有关键操作含try-except
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.dedup_ttl = self.config.get('dedup_ttl', 300)
        self.default_ttl_ms = self.config.get('default_ttl_ms', 800)
        self.orders: Dict[str, Order] = {}
        self._dedup_cache: Dict[str, float] = {}  # client_order_id → timestamp
        self._state_callbacks: List[Callable] = []

    def register_callback(self, callback: Callable):
        """注册状态变更回调 callback(order, old_state, new_state)"""
        self._state_callbacks.append(callback)

    def generate_client_order_id(self, symbol: str, side: str) -> str:
        """生成幂等性clientOrderId: 时间戳+UUID+哈希"""
        ts = int(time.time() * 1000)
        uid = uuid.uuid4().hex[:8]
        raw = f"{symbol}_{side}_{ts}_{uid}"
        h = hashlib.md5(raw.encode()).hexdigest()[:8]
        return f"{ts}_{uid}_{h}"

    def create_order(self, symbol: str, side: str, order_type: str,
                     quantity: float, price: float = 0.0,
                     ttl_ms: Optional[int] = None) -> Optional[Order]:
        """
        创建订单(含去重检查和参数校验)

        Args:
            symbol: 交易品种
            side: BUY/SELL
            order_type: LIMIT/MARKET
            quantity: 数量
            price: 价格
            ttl_ms: 超时时间(毫秒)

        Returns:
            Order 或 None(创建失败)
        """
        try:
            # 参数校验
            if not symbol:
                logger.error("create_order: symbol is empty")
                return None
            if side not in ("BUY", "SELL"):
                logger.error("create_order: invalid side", extra={"extra_data": {"side": side}})
                return None
            if quantity <= 0:
                logger.error("create_order: quantity must be positive", extra={"extra_data": {"quantity": quantity}})
                return None
            if order_type == "LIMIT" and price <= 0:
                logger.error("create_order: LIMIT order requires positive price")
                return None

            client_order_id = self.generate_client_order_id(symbol, side)

            # 去重检查
            if self._is_duplicate(client_order_id):
                logger.warning("Duplicate client_order_id rejected", extra={"extra_data": {
                    "client_order_id": client_order_id
                }})
                return None

            order = Order(
                order_id="",
                client_order_id=client_order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                ttl_ms=ttl_ms or self.default_ttl_ms,
            )

            self.orders[client_order_id] = order
            self._dedup_cache[client_order_id] = time.time()

            logger.info("Order created", extra={"extra_data": {
                "client_order_id": client_order_id,
                "symbol": symbol, "side": side,
                "quantity": quantity, "state": order.state.value
            }})

            # 广播order.created事件（Phase 5.5新增）
            if EVENT_BUS_AVAILABLE:
                try:
                    event_bus = get_event_bus()
                    event_bus.publish(
                        "order.created",
                        {
                            "client_order_id": client_order_id,
                            "symbol": symbol,
                            "side": side,
                            "order_type": order_type,
                            "quantity": quantity,
                            "price": price,
                            "state": order.state.value
                        },
                        source="order_lifecycle_manager"
                    )
                    logger.debug(f"订单创建事件已广播: {client_order_id}")
                except Exception as e:
                    logger.error("订单创建事件广播失败", extra={"extra_data": {
                        "client_order_id": client_order_id,
                        "error": str(e)
                    }})

            return order

        except Exception as e:
            logger.error("create_order failed", extra={"extra_data": {
                "symbol": symbol, "error": str(e)
            }})
            return None

    def submit_order(self, client_order_id: str, order_id: str) -> bool:
        """
        提交订单(NEW → SUBMITTING),含状态校验

        Args:
            client_order_id: 客户端订单ID
            order_id: 交易所返回的订单ID

        Returns:
            是否成功
        """
        try:
            order = self.orders.get(client_order_id)
            if not order:
                logger.error("submit_order: order not found", extra={"extra_data": {
                    "client_order_id": client_order_id
                }})
                return False

            if not self._validate_transition(order.state, OrderState.SUBMITTING):
                logger.warning("submit_order: invalid state transition", extra={"extra_data": {
                    "client_order_id": client_order_id,
                    "current_state": order.state.value,
                    "target_state": "SUBMITTING"
                }})
                return False

            old_state = order.state
            order.state = OrderState.SUBMITTING
            order.order_id = order_id
            order.updated_at = time.time()

            self._notify_callbacks(order, old_state, OrderState.SUBMITTING)

            logger.info("Order submitted", extra={"extra_data": {
                "client_order_id": client_order_id,
                "order_id": order_id
            }})
            return True

        except Exception as e:
            logger.error("submit_order failed", extra={"extra_data": {
                "client_order_id": client_order_id, "error": str(e)
            }})
            return False

    def acknowledge_order(self, client_order_id: str) -> bool:
        """SUBMITTING → ACKNOWLEDGED"""
        try:
            order = self.orders.get(client_order_id)
            if not order:
                return False
            if not self._validate_transition(order.state, OrderState.ACKNOWLEDGED):
                return False

            old_state = order.state
            order.state = OrderState.ACKNOWLEDGED
            order.updated_at = time.time()
            self._notify_callbacks(order, old_state, OrderState.ACKNOWLEDGED)
            return True
        except Exception as e:
            logger.error("acknowledge_order failed", extra={"extra_data": {
                "client_order_id": client_order_id, "error": str(e)
            }})
            return False

    def fill_order(self, client_order_id: str, filled_quantity: float,
                   is_partial: bool = False) -> bool:
        """
        成交订单(ACKNOWLEDGED/PARTIALLY_FILLED → FILLED/PARTIALLY_FILLED)

        Args:
            client_order_id: 客户端订单ID
            filled_quantity: 本次成交量
            is_partial: 是否部分成交
        """
        try:
            order = self.orders.get(client_order_id)
            if not order:
                logger.error("fill_order: order not found")
                return False

            target_state = OrderState.PARTIALLY_FILLED if is_partial else OrderState.FILLED

            if not self._validate_transition(order.state, target_state):
                logger.warning("fill_order: invalid transition", extra={"extra_data": {
                    "current": order.state.value, "target": target_state.value
                }})
                return False

            old_state = order.state
            order.filled_quantity += filled_quantity
            order.state = target_state
            order.updated_at = time.time()

            # 自动检测: 如果已全部成交
            if order.filled_quantity >= order.quantity and order.state == OrderState.PARTIALLY_FILLED:
                order.state = OrderState.FILLED

            self._notify_callbacks(order, old_state, order.state)

            logger.info("Order filled", extra={"extra_data": {
                "client_order_id": client_order_id,
                "filled_quantity": filled_quantity,
                "total_filled": order.filled_quantity,
                "state": order.state.value
            }})
            return True

        except Exception as e:
            logger.error("fill_order failed", extra={"extra_data": {
                "client_order_id": client_order_id, "error": str(e)
            }})
            return False

    def cancel_order(self, client_order_id: str) -> bool:
        """取消订单(*→CANCEL_REQUESTED→CANCELLED)"""
        try:
            order = self.orders.get(client_order_id)
            if not order:
                return False

            # 先尝试CANCEL_REQUESTED
            if self._validate_transition(order.state, OrderState.CANCEL_REQUESTED):
                old_state = order.state
                order.state = OrderState.CANCEL_REQUESTED
                order.updated_at = time.time()
                self._notify_callbacks(order, old_state, OrderState.CANCEL_REQUESTED)

                # 立即完成取消
                old_state2 = order.state
                order.state = OrderState.CANCELLED
                order.updated_at = time.time()
                self._notify_callbacks(order, old_state2, OrderState.CANCELLED)

                logger.info("Order cancelled", extra={"extra_data": {
                    "client_order_id": client_order_id
                }})
                return True

            # 如果可以直接CANCELLED
            if self._validate_transition(order.state, OrderState.CANCELLED):
                old_state = order.state
                order.state = OrderState.CANCELLED
                order.updated_at = time.time()
                self._notify_callbacks(order, old_state, OrderState.CANCELLED)
                logger.info("Order cancelled directly", extra={"extra_data": {
                    "client_order_id": client_order_id
                }})
                return True

            logger.warning("cancel_order: invalid state", extra={"extra_data": {
                "client_order_id": client_order_id, "state": order.state.value
            }})
            return False

        except Exception as e:
            logger.error("cancel_order failed", extra={"extra_data": {
                "client_order_id": client_order_id, "error": str(e)
            }})
            return False

    def reject_order(self, client_order_id: str, reason: str = "") -> bool:
        """拒绝订单(SUBMITTING → REJECTED)"""
        try:
            order = self.orders.get(client_order_id)
            if not order:
                return False

            if not self._validate_transition(order.state, OrderState.REJECTED):
                logger.warning("reject_order: invalid transition", extra={"extra_data": {
                    "current": order.state.value
                }})
                return False

            old_state = order.state
            order.state = OrderState.REJECTED
            order.error = reason
            order.updated_at = time.time()
            self._notify_callbacks(order, old_state, OrderState.REJECTED)

            logger.warning("Order rejected", extra={"extra_data": {
                "client_order_id": client_order_id, "reason": reason
            }})
            return True

        except Exception as e:
            logger.error("reject_order failed", extra={"extra_data": {
                "client_order_id": client_order_id, "error": str(e)
            }})
            return False

    def check_timeout(self) -> List[str]:
        """检查超时订单并自动撤单"""
        now = time.time()
        timed_out = []
        try:
            for cid, order in self.orders.items():
                if order.is_terminal:
                    continue
                elapsed_ms = (now - order.created_at) * 1000
                if elapsed_ms > order.ttl_ms:
                    if self.cancel_order(cid):
                        timed_out.append(cid)
                        logger.info("Order timed out and cancelled", extra={"extra_data": {
                            "client_order_id": cid,
                            "elapsed_ms": round(elapsed_ms),
                            "ttl_ms": order.ttl_ms
                        }})
        except Exception as e:
            logger.error("check_timeout failed", extra={"extra_data": {"error": str(e)}})
        return timed_out

    # ---------- 辅助方法 ----------

    def _validate_transition(self, current: OrderState, target: OrderState) -> bool:
        """校验状态转换合法性"""
        if current == target:
            return True  # 自环允许
        allowed = _VALID_TRANSITIONS.get(current, set())
        return target in allowed

    def _is_duplicate(self, client_order_id: str) -> bool:
        """去重检查(含TTL过期清理)"""
        now = time.time()
        # 清理过期条目
        expired = [k for k, v in self._dedup_cache.items() if now - v > self.dedup_ttl]
        for k in expired:
            del self._dedup_cache[k]
        return client_order_id in self._dedup_cache

    def _notify_callbacks(self, order: Order, old_state: OrderState,
                          new_state: OrderState):
        """
        通知状态变更回调（传统回调 + 事件总线广播）

        Args:
            order: 订单对象
            old_state: 旧状态
            new_state: 新状态
        """
        # 第一层：传统回调（保持向后兼容）
        for cb in self._state_callbacks:
            try:
                cb(order, old_state, new_state)
            except Exception as e:
                logger.error("State callback error", extra={"extra_data": {"error": str(e)}})

        # 第二层：事件总线广播（Phase 5.5 新增）
        if EVENT_BUS_AVAILABLE:
            try:
                event_bus = get_event_bus()

                # 映射状态到标准事件类型
                state_to_event = {
                    OrderState.NEW: "order.created",
                    OrderState.SUBMITTING: "order.submitted",
                    OrderState.ACKNOWLEDGED: "order.acknowledged",
                    OrderState.PARTIALLY_FILLED: "order.partially_filled",
                    OrderState.FILLED: "order.filled",
                    OrderState.CANCEL_REQUESTED: "order.cancel_requested",
                    OrderState.CANCELLED: "order.cancelled",
                    OrderState.REJECTED: "order.rejected",
                    OrderState.EXPIRED: "order.expired",
                    OrderState.FAILED: "order.failed"
                }

                event_type = state_to_event.get(new_state)
                if event_type:
                    event_bus.publish(
                        event_type,
                        {
                            "client_order_id": order.client_order_id,
                            "order_id": order.order_id,
                            "symbol": order.symbol,
                            "side": order.side,
                            "order_type": order.order_type,
                            "quantity": order.quantity,
                            "filled_quantity": order.filled_quantity,
                            "remaining_quantity": order.remaining_quantity,
                            "price": order.price,
                            "old_state": old_state.value,
                            "new_state": new_state.value,
                            "is_partial": new_state == OrderState.PARTIALLY_FILLED,
                            "is_terminal": new_state in TERMINAL_STATES
                        },
                        source="order_lifecycle_manager"
                    )

                    logger.debug(f"订单状态事件已广播: {event_type} | {order.client_order_id}")

            except Exception as e:
                logger.error("订单事件广播失败", extra={"extra_data": {
                    "client_order_id": order.client_order_id,
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                    "error": str(e)
                }})

    def get_order(self, client_order_id: str) -> Optional[Order]:
        return self.orders.get(client_order_id)

    def get_active_orders(self) -> List[Order]:
        return [o for o in self.orders.values() if not o.is_terminal]

    def get_stats(self) -> Dict:
        total = len(self.orders)
        by_state = {}
        for order in self.orders.values():
            s = order.state.value
            by_state[s] = by_state.get(s, 0) + 1
        return {
            "total_orders": total,
            "active_orders": len(self.get_active_orders()),
            "by_state": by_state,
            "dedup_cache_size": len(self._dedup_cache),
        }

    def cleanup_expired(self):
        """清理过期去重缓存"""
        now = time.time()
        expired = [k for k, v in self._dedup_cache.items() if now - v > self.dedup_ttl]
        for k in expired:
            del self._dedup_cache[k]
        return len(expired)


def main():
    parser = argparse.ArgumentParser(description="订单生命周期管理 V6.3")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--side", default="BUY", choices=["BUY", "SELL"])
    parser.add_argument("--quantity", type=float, default=0.001)
    parser.add_argument("--price", type=float, default=50000.0)
    parser.add_argument("--type", default="LIMIT", choices=["LIMIT", "MARKET"])
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    mgr = OrderLifecycleManager()

    if args.stats:
        logger.info(json.dumps(mgr.get_stats(), ensure_ascii=False, indent=2))
        return

    order = mgr.create_order(
        symbol=args.symbol, side=args.side,
        order_type=args.type, quantity=args.quantity,
        price=args.price
    )
    if order:
        mgr.submit_order(order.client_order_id, order_id="EX_001")
        mgr.acknowledge_order(order.client_order_id)
        mgr.fill_order(order.client_order_id, filled_quantity=args.quantity)
        final = mgr.get_order(order.client_order_id)
        logger.info(json.dumps(final.to_dict(), ensure_ascii=False, indent=2))
    else:
        logger.info(json.dumps({"status": "error", "message": "Order creation failed"}))


if __name__ == "__main__":
    main()
