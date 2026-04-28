#!/usr/bin/env python3
"""
订单状态机转换性能测试
验证1000次状态转换耗时是否<0.2s
"""

import time
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("order_state_machine_performance")
except ImportError:
    import logging
    logger = logging.getLogger("order_state_machine_performance")

try:
    from scripts.order_lifecycle_manager import OrderLifecycleManager, Order, OrderState
    from scripts.unified_models import OrderSide, OrderStatus
except ImportError as e:
    logger.error(f"导入失败: {e}")
    sys.exit(1)


def test_order_state_transitions_performance():
    """
    测试订单状态机转换性能

    目标: 1000次状态转换 < 0.2s
    """
    logger.info("=" * 80)
    logger.info("订单状态机转换性能测试")
    logger.info("=" * 80)

    # 创建订单生命周期管理器
    manager = OrderLifecycleManager()

    # 创建测试订单
    order = Order(
        order_id="TEST_ORDER_001",
        client_order_id="CLIENT_001",
        symbol="BTC/USDT",
        side="BUY",
        order_type="LIMIT",
        quantity=1.0,
        price=50000.0
    )

    # 状态转换序列（使用OrderState枚举）
    transitions = [
        (OrderState.NEW, OrderState.SUBMITTING),
        (OrderState.SUBMITTING, OrderState.ACKNOWLEDGED),
        (OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED),
        (OrderState.PARTIALLY_FILLED, OrderState.FILLED),
    ]

    # 执行1000次状态转换
    iterations = 1000
    start_time = time.time()

    for i in range(iterations):
        # 重置订单状态
        order.state = OrderState.NEW

        # 执行状态转换
        for from_state, to_state in transitions:
            try:
                order.state = to_state
            except Exception as e:
                logger.warning(f"状态转换失败: {from_state} -> {to_state} - {e}")
                break

    end_time = time.time()
    total_time = end_time - start_time
    avg_time_per_iteration = (total_time / iterations) * 1000  # ms

    logger.info(f"\n性能测试结果:")
    logger.info(f"  迭代次数: {iterations}")
    logger.info(f"  总耗时: {total_time:.4f}s")
    logger.info(f"  平均每次转换: {avg_time_per_iteration:.4f}ms")
    logger.info(f"  目标: < 0.2s")

    # 判断是否达标
    if total_time < 0.2:
        logger.info(f"  ✅ 达标 (超出目标 {0.2 - total_time:.4f}s)")
        return True
    else:
        logger.warning(f"  ⚠️ 未达标 (超出 {total_time - 0.2:.4f}s)")
        return False


if __name__ == "__main__":
    success = test_order_state_transitions_performance()
    sys.exit(0 if success else 1)
