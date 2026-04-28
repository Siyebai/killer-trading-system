# V3 新模块接口文档

## 概览
V3版本新增8个核心模块，大幅提升系统的异步处理能力、数据持久化、实时监控和回测能力。

---

## 1. 异步事件引擎 (`async_event_engine.py`)

### 核心功能
- 高性能异步事件分发
- 事件订阅/发布机制
- 全局事件监听
- 实时性能统计

### 主要接口

#### `AsyncEventEngine`
```python
async def start() -> None
```
启动事件引擎

```python
async def stop() -> None
```
停止事件引擎

```python
def subscribe(event_type: str, callback: Callable) -> None
```
订阅特定类型事件

**参数:**
- `event_type`: 事件类型（如'market_tick', 'order_update'）
- `callback`: 回调函数（支持同步/异步）

```python
def subscribe_global(callback: Callable) -> None
```
订阅所有事件

```python
async def emit(event_type: str, data: Dict[str, Any]) -> None
```
发布事件

**参数:**
- `event_type`: 事件类型
- `data`: 事件数据字典

```python
def get_stats() -> Dict[str, Any]
```
获取引擎统计

**返回:**
```python
{
    'total_events': int,      # 总事件数
    'processed_events': int,  # 已处理事件数
    'failed_events': int,     # 失败事件数
    'avg_latency_ms': float,  # 平均延迟（毫秒）
    'queue_size': int,        # 队列大小
    'subscriber_types': int,  # 订阅类型数
    'global_subscribers': int # 全局订阅者数
}
```

### 使用示例
```python
import asyncio
from scripts.async_event_engine import AsyncEventEngine

async def main():
    engine = AsyncEventEngine()
    await engine.start()

    # 订阅事件
    def handle_market_tick(event):
        print(f"收到行情: {event.data}")

    engine.subscribe('market_tick', handle_market_tick)

    # 发布事件
    await engine.emit('market_tick', {'price': 50000, 'volume': 100})

    await asyncio.sleep(1)
    await engine.stop()

asyncio.run(main())
```

---

## 2. 数据库持久层 (`database_manager.py`)

### 核心功能
- SQLite数据库管理
- 交易记录存储
- 市场行情存储
- 策略性能追踪
- 高效查询接口

### 主要接口

#### `DatabaseManager`
```python
def __init__(db_path: str = "./data/trading.db")
```
初始化数据库管理器

#### 数据模型

**`TradeRecord`** (交易记录)
```python
@dataclass
class TradeRecord:
    trade_id: str
    symbol: str
    side: str  # 'BUY' or 'SELL'
    price: float
    quantity: float
    timestamp: float
    strategy: str
    pnl: float = 0.0
    commission: float = 0.0
    signal_strength: float = 0.0
```

**`MarketTick`** (市场行情)
```python
@dataclass
class MarketTick:
    timestamp: float
    symbol: str
    bid: float
    ask: float
    mid_price: float
    volume: float
    volatility: float = 0.0
```

#### 主要方法

```python
def save_trade(trade: TradeRecord) -> bool
```
保存交易记录

```python
def save_market_tick(tick: MarketTick) -> bool
```
保存市场行情

```python
def get_recent_trades(symbol: str = None, limit: int = 100) -> List[Dict[str, Any]]
```
获取最近交易记录

**参数:**
- `symbol`: 交易对（可选）
- `limit`: 返回数量限制

```python
def get_market_ticks_range(start_time: float, end_time: float,
                           symbol: str = None) -> List[Dict[str, Any]]
```
获取时间范围内的市场行情

```python
def update_strategy_performance(strategy_id: str, metrics: Dict[str, float]) -> bool
```
更新策略性能指标

**参数:**
- `strategy_id`: 策略ID
- `metrics`:
  ```python
  {
      'total_trades': int,
      'win_trades': int,
      'total_pnl': float,
      'max_drawdown': float,
      'sharpe_ratio': float
  }
  ```

```python
def get_statistics() -> Dict[str, Any]
```
获取数据库统计信息

### 使用示例
```python
from scripts.database_manager import DatabaseManager, TradeRecord, MarketTick
import time

db = DatabaseManager("./data/trading.db")

# 保存交易
trade = TradeRecord(
    trade_id="001",
    symbol="BTCUSDT",
    side="BUY",
    price=50000.0,
    quantity=0.1,
    timestamp=time.time(),
    strategy="MA_CROSS",
    pnl=100.0
)
db.save_trade(trade)

# 查询交易
trades = db.get_recent_trades(symbol="BTCUSDT", limit=10)

# 获取统计
stats = db.get_statistics()
```

---

## 3. 实时监控仪表板 (`monitoring_dashboard.py`)

### 核心功能
- Web UI实时监控
- 投资组合可视化
- 策略性能展示
- 风控指标显示
- 自动刷新机制

### 主要接口

#### `MonitoringDashboard`
```python
def __init__(output_dir: str = "./dashboard")
```
初始化监控仪表板

#### 主要方法

```python
def update_portfolio(balance: float, equity: float, positions: Dict[str, float]) -> None
```
更新投资组合数据

```python
def add_trade(trade: Dict[str, Any]) -> None
```
添加交易记录

```python
def update_strategy_stats(strategy_id: str, stats: Dict[str, Any]) -> None
```
更新策略统计

```python
def update_risk_metrics(risk_data: Dict[str, Any]) -> None
```
更新风控指标

```python
def update_system_stats(system_data: Dict[str, Any]) -> None
```
更新系统统计

```python
def generate_dashboard() -> str
```
生成HTML仪表板

**返回:** 仪表板文件路径

```python
def print_summary() -> None
```
打印监控摘要（控制台）

### 使用示例
```python
from scripts.monitoring_dashboard import MonitoringDashboard

dashboard = MonitoringDashboard("./dashboard")

# 更新数据
dashboard.update_portfolio(100000, 101500, {'BTCUSDT': 0.5})
dashboard.update_risk_metrics({
    'current_drawdown': 0.015,
    'max_drawdown': 0.025,
    'sharpe_ratio': 2.5
})

# 生成仪表板
dashboard_file = dashboard.generate_dashboard()
print(f"仪表板已生成: {dashboard_file}")

# 打印摘要
dashboard.print_summary()
```

### 仪表板访问
生成仪表板后，用浏览器打开 `dashboard/dashboard.html` 即可查看实时监控页面。

---

## V3 模块集成指南

### 集成到主程序 (run.py)

```python
from scripts.async_event_engine import AsyncEventEngine
from scripts.database_manager import DatabaseManager
from scripts.monitoring_dashboard import MonitoringDashboard

class TradingAgentV3:
    def __init__(self, config: Dict):
        # 初始化V3模块
        self.event_engine = AsyncEventEngine()
        self.db = DatabaseManager("./data/trading.db")
        self.dashboard = MonitoringDashboard("./dashboard")

        # 订阅事件
        self.event_engine.subscribe('trade_executed', self._on_trade)
        self.event_engine.subscribe('market_tick', self._on_tick)

    async def _on_trade(self, event):
        """交易回调"""
        trade_data = event.data
        self.db.save_trade(trade_data)
        self.dashboard.add_trade(trade_data)

    async def _on_tick(self, event):
        """行情回调"""
        tick_data = event.data
        self.db.save_market_tick(tick_data)

    async def start(self):
        """启动系统"""
        await self.event_engine.start()
        # ... 其他初始化

        # 定期更新仪表板
        while True:
            self.dashboard.update_portfolio(...)
            self.dashboard.update_system_stats(...)
            self.dashboard.generate_dashboard()
            await asyncio.sleep(5)
```

---

## 性能建议

### 事件引擎
- 事件处理函数尽量快速（<100ms）
- 避免在事件处理中进行阻塞操作
- 使用异步处理I/O密集型任务

### 数据库
- 批量插入使用事务
- 定期清理历史数据（>30天）
- 索引查询字段（timestamp, symbol）

### 监控仪表板
- 限制历史交易记录数量（100条）
- 避免频繁生成仪表板（每5秒一次）
- 使用CDN加速静态资源加载

---

## 兼容性说明

### V3模块与V2兼容性
- V3模块为可选增强，不影响V2功能
- 可渐进式集成（先集成事件引擎，再集成数据库）
- V2的JSON状态持久化可继续使用

### 系统要求
- Python 3.7+
- SQLite 3（内置）
- 现代浏览器（Chrome/Firefox/Edge）

---

## 扩展方向

### 计划中的V3.5功能
1. 回测引擎 (`backtesting_engine.py`)
2. 智能订单路由 (`smart_order_router.py`)
3. 多交易所适配器 (`exchange_adapters/`)
4. 机器学习信号增强 (`ml_signal_enhancer.py`)
5. 性能告警系统 (`performance_alerts.py`)
