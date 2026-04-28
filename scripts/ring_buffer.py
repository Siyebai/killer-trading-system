#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("ring_buffer")
except ImportError:
    import logging
    logger = logging.getLogger("ring_buffer")
"""
RingBuffer - 固定大小环形缓冲区
用于增量指标计算，避免全量重算
"""

from typing import List, Any, Optional
import numpy as np


class RingBuffer:
    """固定大小环形缓冲区"""

    def __init__(self, capacity: int):
        """
        初始化环形缓冲区

        Args:
            capacity: 缓冲区容量
        """
        if capacity <= 0:
            raise ValueError(f"capacity必须大于0，当前值: {capacity}")

        self.capacity = capacity
        self._buffer: List[Any] = [None] * capacity
        self._index = 0
        self._size = 0
        self._full = False

    def append(self, value: Any) -> None:
        """
        添加元素到缓冲区

        Args:
            value: 要添加的值
        """
        self._buffer[self._index] = value
        self._index = (self._index + 1) % self.capacity

        if self._index == 0:
            self._full = True
        elif not self._full:
            self._size += 1

    def __getitem__(self, index: int) -> Any:
        """
        获取指定索引的元素

        Args:
            index: 索引（从0开始）

        Returns:
            元素值
        """
        if self._full:
            # 缓冲区已满，从当前位置开始
            actual_index = (self._index + index) % self.capacity
        else:
            # 缓冲区未满，直接使用索引
            actual_index = index

        if actual_index >= self._size:
            raise IndexError(f"索引{index}超出范围，当前大小: {self._size}")

        return self._buffer[actual_index]

    def __len__(self) -> int:
        """获取当前大小"""
        return self.capacity if self._full else self._size

    def is_full(self) -> bool:
        """检查缓冲区是否已满"""
        return self._full

    def to_list(self) -> List[Any]:
        """转换为列表"""
        if not self._full:
            return self._buffer[:self._size]

        # 缓冲区已满，按正确顺序返回
        result = self._buffer[self._index:] + self._buffer[:self._index]
        return [x for x in result if x is not None]

    def clear(self) -> None:
        """清空缓冲区"""
        self._buffer = [None] * self.capacity
        self._index = 0
        self._size = 0
        self._full = False

    def mean(self) -> float:
        """计算平均值（仅支持数值类型）"""
        data = self.to_list()
        if not data:
            return 0.0
        return float(np.mean(data))

    def std(self) -> float:
        """计算标准差（仅支持数值类型）"""
        data = self.to_list()
        if len(data) < 2:
            return 0.0
        return float(np.std(data))

    def max(self) -> Any:
        """获取最大值"""
        data = self.to_list()
        if not data:
            raise ValueError("缓冲区为空")
        return max(data)

    def min(self) -> Any:
        """获取最小值"""
        data = self.to_list()
        if not data:
            raise ValueError("缓冲区为空")
        return min(data)

    def sum(self) -> float:
        """计算总和（仅支持数值类型）"""
        data = self.to_list()
        return sum(float(x) for x in data if x is not None)

    def __repr__(self) -> str:
        return f"RingBuffer(capacity={self.capacity}, size={len(self)}, full={self._full})"


class IncrementalIndicator:
    """增量指标计算器"""

    def __init__(self, window_size: int):
        """
        初始化增量指标计算器

        Args:
            window_size: 窗口大小
        """
        self.buffer = RingBuffer(window_size)
        self._sum = 0.0
        self._mean = 0.0

    def update(self, value: float) -> dict:
        """
        更新指标

        Args:
            value: 新值

        Returns:
            指标字典
        """
        old_value = None

        if self.buffer.is_full():
            # 缓冲区已满，将被覆盖的值
            old_value = self.buffer.to_list()[0]

        # 更新缓冲区
        self.buffer.append(value)

        # 增量计算
        if old_value is not None:
            self._sum = self._sum - old_value + value
        else:
            self._sum = self._sum + value

        self._mean = self._sum / len(self.buffer)

        return {
            'value': value,
            'mean': self._mean,
            'sum': self._sum,
            'size': len(self.buffer)
        }


if __name__ == "__main__":
    # 测试RingBuffer
    logger.info("RingBuffer测试")
    buffer = RingBuffer(capacity=5)

    # 填充15个元素
    for i in range(15):
        buffer.append(i)

    logger.info(f"缓冲区内容: {buffer.to_list()}")
    logger.info(f"期望内容: [10, 11, 12, 13, 14]")
    logger.info(f"一致性: {buffer.to_list() == [10, 11, 12, 13, 14]}")

    # 测试增量指标
    logger.info("\n增量指标计算器测试")
    indicator = IncrementalIndicator(window_size=10)

    for i in range(20):
        result = indicator.update(i)
        if i >= 9:
            logger.info(f"步骤{i}: mean={result['mean']:.2f}, sum={result['sum']:.2f}")
