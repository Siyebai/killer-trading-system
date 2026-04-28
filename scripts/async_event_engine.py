#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("async_event_engine")
except ImportError:
    import logging
    logger = logging.getLogger("async_event_engine")
"""
异步事件引擎 - V3核心模块
实现高性能异步事件分发和处理
"""

import asyncio
import time
from typing import Dict, Callable, Any, Optional, List
from collections import defaultdict
from dataclasses import dataclass
import uuid

# 导入统一的Event模型
from scripts.unified_models import Event as UnifiedEvent


class AsyncEventEngine:
    """异步事件引擎"""

    def __init__(self):
        self.event_queue = asyncio.Queue()
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self.global_subscribers: List[Callable] = []
        self.running = False
        self.processor_task = None
        self.stats = {
            'total_events': 0,
            'processed_events': 0,
            'failed_events': 0,
            'avg_latency_ms': 0.0
        }

    async def start(self):
        """启动事件引擎"""
        if self.running:
            return

        self.running = True
        self.processor_task = asyncio.create_task(self._process_events())
        logger.info("[AsyncEventEngine] 事件引擎已启动")

    async def stop(self):
        """停止事件引擎"""
        if not self.running:
            return

        self.running = False
        if self.processor_task:
            self.processor_task.cancel()
            try:
                await self.processor_task
            except asyncio.CancelledError:
                pass
        logger.info("[AsyncEventEngine] 事件引擎已停止")

    def subscribe(self, event_type: str, callback: Callable):
        """订阅特定类型事件"""
        self.subscribers[event_type].append(callback)
        logger.info(f"[AsyncEventEngine] 已订阅事件: {event_type}, 订阅者数: {len(self.subscribers[event_type])}")

    def subscribe_global(self, callback: Callable):
        """订阅所有事件"""
        self.global_subscribers.append(callback)
        logger.info(f"[AsyncEventEngine] 已订阅全局事件, 订阅者数: {len(self.global_subscribers)}")

    async def emit(self, event_type: str, data: Dict[str, Any]):
        """发布事件"""
        event = Event(
            event_type=event_type,
            data=data,
            timestamp=time.time()
        )
        await self.event_queue.put(event)
        self.stats['total_events'] += 1

    async def _process_events(self):
        """事件处理循环"""
        while self.running:
            try:
                # 获取事件（带超时避免阻塞）
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)

                start_time = time.time()

                # 分发给全局订阅者
                for callback in self.global_subscribers:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(event)
                        else:
                            callback(event)
                    except Exception as e:
                        logger.error(f"[AsyncEventEngine] 全局订阅者处理失败: {e}")

                # 分发给类型订阅者
                subscribers = self.subscribers.get(event.event_type, [])
                for callback in subscribers:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(event)
                        else:
                            callback(event)
                    except Exception as e:
                        logger.error(f"[AsyncEventEngine] 订阅者处理失败: {e}")

                # 更新统计
                self.stats['processed_events'] += 1
                latency_ms = (time.time() - start_time) * 1000
                self.stats['avg_latency_ms'] = (
                    self.stats['avg_latency_ms'] * 0.9 + latency_ms * 0.1
                )

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[AsyncEventEngine] 事件处理异常: {e}")
                self.stats['failed_events'] += 1

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计"""
        return {
            **self.stats,
            'queue_size': self.event_queue.qsize(),
            'subscriber_types': len(self.subscribers),
            'global_subscribers': len(self.global_subscribers)
        }


# 命令行测试
async def test_handler(event: Event):
    """测试处理器"""
    logger.info(f"收到事件: {event.event_type}, 数据: {event.data}")
    await asyncio.sleep(0.1)  # 模拟处理耗时


async def main():
    """测试主函数"""
    engine = AsyncEventEngine()

    # 订阅事件
    engine.subscribe('market_tick', test_handler)
    engine.subscribe('order_update', test_handler)
    engine.subscribe_global(lambda e: logger.debug(f"全局处理: {e.event_type}"))

    # 启动引擎
    await engine.start()

    # 发布测试事件
    for i in range(5):
        await engine.emit('market_tick', {'price': 50000 + i * 100, 'volume': i * 10})
        await asyncio.sleep(0.05)

    await engine.emit('order_update', {'order_id': '123', 'status': 'filled'})

    # 等待处理完成
    await asyncio.sleep(1)

    # 输出统计
    logger.info("\n引擎统计:")
    logger.info(engine.get_stats())

    # 停止引擎
    await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
