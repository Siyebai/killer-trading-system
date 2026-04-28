# 增量指标计算与高性能优化

## 目录
- [概览](#概览)
- [RingBuffer原理](#ringbuffer原理)
- [增量计算优势](#增量计算优势)
- [指标实现](#指标实现)
- [使用示例](#使用示例)

## 概览

增量指标计算是一种高效的技术指标计算方法，避免每次全量重新计算，显著提升实时交易系统的性能。

## RingBuffer原理

### 什么是环形缓冲区
环形缓冲区（RingBuffer）是一种固定大小的数据结构，使用循环数组实现空间复用。

### 核心特性
- 固定内存分配，避免动态扩容
- O(1)时间复杂度的插入和读取
- 自动覆盖最旧数据，保持窗口大小恒定

### 实现示例
```python
class RingBuffer:
    __slots__ = ('size', 'data', 'index', 'count')
    def __init__(self, size: int):
        self.size = size
        self.data = np.zeros(size, dtype=np.float64)
        self.index = 0
        self.count = 0
    def append(self, value: float):
        self.data[self.index] = value
        self.index = (self.index + 1) % self.size
        self.count = min(self.count + 1, self.size)
    def all(self) -> np.ndarray:
        if self.count < self.size:
            return self.data[:self.count]
        return np.roll(self.data, -self.index)
```

## 增量计算优势

### 性能对比
| 指标 | 全量计算 | 增量计算 | 提升 |
|------|---------|---------|------|
| SMA(200) | O(n) | O(1) | 200x |
| RSI(14) | O(n) | O(1) | 14x |
| ATR(14) | O(n) | O(1) | 14x |

### 内存优势
- 固定内存占用
- 无需维护完整历史数据
- 适合长时间运行

### 实时性优势
- 每次处理仅需O(1)时间
- 低延迟响应市场变化
- 适合高频交易场景

## 指标实现

### 1. 增量SMA（简单移动平均）
```python
class IncrementalSMA:
    def __init__(self, period: int):
        self.buffer = RingBuffer(period)
        self.sum = 0.0

    def update(self, price: float) -> float:
        old_value = self.buffer.data[self.buffer.index] if self.buffer.count == self.buffer.size else 0
        self.sum += price - old_value
        self.buffer.append(price)
        return self.sum / self.buffer.count
```

### 2. 增量RSI（相对强弱指标）
```python
def incremental_rsi(buffer: RingBuffer) -> float:
    n = len(buffer.all())
    if n < 15:
        return 50.0
    prices = buffer.all()
    deltas = np.diff(prices[-15:])
    gains = np.sum(deltas[deltas > 0])
    losses = -np.sum(deltas[deltas < 0])
    avg_gain = gains / 14.0
    avg_loss = losses / 14.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)
```

### 3. 增量ATR（平均真实波幅）
```python
def incremental_atr(high_buffer: RingBuffer, low_buffer: RingBuffer, close_buffer: RingBuffer) -> float:
    h = high_buffer.all()
    l = low_buffer.all()
    c = close_buffer.all()
    n = len(c)
    if n < 15:
        return c[-1] * 0.0005
    tr = np.maximum(h[-14:] - l[-14:], np.abs(h[-14:] - c[-15:-1]))
    tr = np.maximum(tr, np.abs(l[-14:] - c[-15:-1]))
    return np.mean(tr)
```

## 使用示例

### 示例1: 在一体化系统中使用
```python
from scripts.run import IncrementalIndicators

# 初始化指标计算器
indicators = IncrementalIndicators(maxlen=200)

# 更新K线数据
ind = indicators.update_bar(
    open_p=50000,
    high=50100,
    low=49900,
    close=50050,
    volume=1000
)

# 获取指标
print(f"SMA5: {ind['sma5']}")
print(f"SMA20: {ind['sma20']}")
print(f"RSI: {ind['rsi']}")
print(f"ATR: {ind['atr']}")
print(f"波动率: {ind['volatility']}")
```

### 示例2: 自定义增量指标
```python
class CustomIncrementalIndicator:
    def __init__(self, window: int):
        self.buffer = RingBuffer(window)

    def update(self, value: float) -> float:
        self.buffer.append(value)
        data = self.buffer.all()
        # 自定义计算逻辑
        return np.mean(data)

# 使用
indicator = CustomIncrementalIndicator(window=20)
result = indicator.update(50000)
```

### 示例3: 批量处理历史数据
```python
# 初始化
indicators = IncrementalIndicators(maxlen=200)

# 处理历史K线
for bar in historical_data:
    ind = indicators.update_bar(
        bar['open'], bar['high'], bar['low'],
        bar['close'], bar['volume']
    )
    # 存储或使用ind
```

## 性能优化建议

### 1. 使用Numba加速
```python
from numba import jit

@jit(nopython=True)
def fast_rsi(prices: np.ndarray) -> float:
    # JIT加速的RSI计算
    pass
```

### 2. 避免频繁创建对象
- 复用RingBuffer实例
- 避免在循环中创建临时数组
- 使用预分配的缓冲区

### 3. 合理设置缓冲区大小
- SMA/RSI: 14-200
- ATR: 14-50
- 长期趋势: 100-200

## 注意事项
- 缓冲区未满时，指标可能不稳定
- 首次填充需要等待足够的数据量
- 增量计算假设数据连续，跳过数据点会导致偏差
