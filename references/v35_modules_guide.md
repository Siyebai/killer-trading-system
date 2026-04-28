# V3.5 模块接口文档

## 概览
V3.5版本新增5个高级模块，大幅提升系统的回测能力、订单执行效率、多交易所支持、AI信号优化和实时监控能力。

---

## 1. 回测引擎 (`backtesting_engine.py`)

### 核心功能
- 历史数据加载和处理
- 策略回测执行
- 手续费和滑点模拟
- 回测指标计算（收益率、夏普比率、最大回撤等）
- 权益曲线生成

### 主要接口

#### `BacktestConfig`
```python
@dataclass
class BacktestConfig:
    initial_capital: float = 100000.0      # 初始资金
    commission_rate: float = 0.001          # 手续费率 (0.1%)
    slippage_rate: float = 0.0005           # 滑点率 (0.05%)
    max_position_size: float = 0.5          # 最大持仓比例
    leverage: float = 1.0                   # 杠杆倍数
```

#### `BacktestEngine`
```python
def __init__(config: Optional[BacktestConfig] = None)
```
初始化回测引擎

```python
def load_historical_data(data_source: str) -> pd.DataFrame
```
加载历史数据（支持文件路径或JSON字符串）

```python
def execute_trade(timestamp: float, symbol: str, side: str,
                  price: float, size: float, strategy: str) -> Trade
```
执行交易（包含手续费和滑点）

```python
def close_position(timestamp: float, symbol: str, price: float,
                   reason: str = "manual") -> Optional[Trade]
```
平仓

```python
def run(historical_data: pd.DataFrame,
        strategy_func: Callable) -> BacktestMetrics
```
运行回测

**参数:**
- `historical_data`: 历史数据DataFrame（需包含timestamp, open, high, low, close, volume列）
- `strategy_func`: 策略函数，签名：`def strategy_func(row: pd.Series, positions: Dict, cash: float) -> Dict`

**策略函数返回格式:**
```python
{
    'action': 'BUY' or 'SELL' or 'HOLD',
    'symbol': 'BTCUSDT',
    'size': 0.1,
    'strategy': 'MA_CROSS',
    'reason': '...'
}
```

```python
def get_results() -> Dict[str, Any]
```
获取回测结果（包含指标、权益曲线、交易记录）

#### `BacktestMetrics`
回测指标数据类：
- `total_return`: 总收益率
- `annual_return`: 年化收益率
- `sharpe_ratio`: 夏普比率
- `max_drawdown`: 最大回撤
- `win_rate`: 胜率
- `profit_factor`: 盈亏比
- `total_trades`: 总交易数
- `win_trades`: 盈利交易数
- `avg_trade_pnl`: 平均盈亏

### 使用示例
```python
from scripts.backtesting_engine import BacktestEngine, BacktestConfig

# 创建配置
config = BacktestConfig(
    initial_capital=100000,
    commission_rate=0.001,
    slippage_rate=0.0005
)

# 创建引擎
engine = BacktestEngine(config)

# 加载历史数据
df = engine.load_historical_data('historical_btc.json')

# 运行回测
metrics = engine.run(df, my_strategy_function)

# 获取结果
results = engine.get_results()
print(f"总收益率: {results['metrics']['total_return']*100:.2f}%")
print(f"夏普比率: {results['metrics']['sharpe_ratio']:.2f}")
```

---

## 2. 智能订单路由 (`smart_order_router.py`)

### 核心功能
- 多交易所最优路径选择
- 价格影响计算
- 订单拆分优化
- 流动性分析
- 交易所对比

### 主要接口

#### `Exchange`
```python
@dataclass
class Exchange:
    exchange_id: str
    name: str
    fee_rate: float              # 手续费率
    liquidity_score: float       # 流动性评分 (0-1)
    latency_ms: float            # 延迟（毫秒）
    min_order_size: float        # 最小订单量
    max_order_size: float        # 最大订单量
```

#### `SmartOrderRouter`
```python
def add_exchange(exchange: Exchange)
```
添加交易所

```python
def update_market_depth(depth: MarketDepth)
```
更新市场深度

```python
def route_order(symbol: str, side: str, size: float,
                allow_split: bool = True) -> Dict[str, Any]
```
路由订单

**返回:**
```python
{
    'routing_type': 'SINGLE' or 'SPLIT',
    'optimal_path': {
        'exchanges': ['binance', 'okx'],
        'total_cost_pct': 0.15,
        'expected_slippage_pct': 0.05,
        'execution_time_ms': 80,
        'liquidity_utilization_pct': 25.0
    },
    'suggested_execution': [
        {'exchange': 'binance', 'size': 0.3},
        {'exchange': 'okx', 'size': 0.2}
    ]
}
```

```python
def get_exchange_comparison(symbol: str, side: str,
                            size: float) -> List[Dict[str, Any]]
```
获取交易所对比

### 使用示例
```python
from scripts.smart_order_router import SmartOrderRouter, Exchange

# 创建路由器
router = SmartOrderRouter()

# 添加交易所
router.add_exchange(Exchange(
    exchange_id='binance',
    name='Binance',
    fee_rate=0.001,
    liquidity_score=0.95,
    latency_ms=50,
    min_order_size=0.001,
    max_order_size=10.0
))

# 路由订单
result = router.route_order('BTCUSDT', 'BUY', 0.5, allow_split=True)
print(f"最优交易所: {result['optimal_path']['exchanges']}")
print(f"总成本: {result['optimal_path']['total_cost_pct']:.3f}%")
```

---

## 3. 多交易所适配器 (`multi_exchange_adapter.py`)

### 核心功能
- 统一交易所接口
- 多交易所管理
- 套利机会发现
- 行情对比

### 主要接口

#### `ExchangeAdapter`（抽象基类）
```python
def connect() -> bool
def disconnect()
def get_balance() -> List[Balance]
def get_ticker(symbol: str) -> Optional[Ticker]
def place_order(order: Order) -> Optional[Order]
def cancel_order(order_id: str) -> bool
def get_order(order_id: str) -> Optional[Order]
def get_order_book(symbol: str, limit: int = 20) -> Dict[str, List]
```

#### `ExchangeManager`
```python
def register_adapter(exchange_type: str, exchange_id: str,
                    api_key: str = "", api_secret: str = "") -> bool
```
注册交易所适配器

**支持的交易所类型:** `binance`, `okx`, `bybit`

```python
def connect_all() -> bool
def disconnect_all()
def get_adapter(exchange_id: str) -> Optional[ExchangeAdapter]
def get_all_balances() -> Dict[str, List[Balance]]
def compare_tickers(symbol: str) -> Dict[str, Ticker]
def find_arbitrage_opportunities(symbol: str,
                                min_spread_pct: float = 0.1) -> List[Dict]
```
寻找套利机会

### 使用示例
```python
from scripts.multi_exchange_adapter import ExchangeManager, Order, OrderSide, OrderType

# 创建管理器
manager = ExchangeManager()

# 注册交易所
manager.register_adapter('binance', 'binance_1', 'api_key', 'api_secret')
manager.register_adapter('okx', 'okx_1', 'api_key', 'api_secret')

# 连接
manager.connect_all()

# 获取余额
balances = manager.get_all_balances()

# 对比行情
tickers = manager.compare_tickers('BTCUSDT')

# 寻找套利机会
opportunities = manager.find_arbitrage_opportunities('BTCUSDT', min_spread_pct=0.1)

# 下单
adapter = manager.get_adapter('binance_1')
order = Order(
    order_id='test_001',
    symbol='BTCUSDT',
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    quantity=0.1,
    price=50000.0
)
result = adapter.place_order(order)
```

---

## 4. 机器学习信号增强 (`ml_signal_enhancer.py`)

### 核心功能
- 特征提取（价格、波动率、动量、趋势、成交量）
- 信号增强和置信度调整
- 直接信号预测
- 模型权重管理

### 主要接口

#### `FeatureExtractor`
```python
def __init__(window_size: int = 20)
def update(price: float, volume: float)
def extract_features(current_price: float) -> Dict[str, float]
```
提取特征（15个特征：价格收益率、波动率、动量、趋势、RSI、布林带位置等）

#### `MLSignalEnhancer`
```python
def __init__(model_type: str = "simple_ensemble")
def update_market_data(price: float, volume: float)
def enhance_signal(signal: Signal) -> Signal
```
增强信号

```python
def predict_signal(features: Dict[str, float]) -> Tuple[str, float]
```
直接预测信号
**返回:** (action, confidence)

```python
def get_feature_importance() -> Dict[str, float]
def get_model_summary() -> Dict[str, Any]
```

### 使用示例
```python
from scripts.ml_signal_enhancer import MLSignalEnhancer, Signal

# 创建增强器
enhancer = MLSignalEnhancer(model_type="simple_ensemble")

# 更新市场数据
enhancer.update_market_data(50000.0, 1000)

# 增强信号
signal = Signal(
    timestamp=time.time(),
    symbol='BTCUSDT',
    action='BUY',
    confidence=0.7,
    strategy='MA_CROSS',
    raw_strength=0.8
)
enhanced = enhancer.enhance_signal(signal)
print(f"增强后置信度: {enhanced.confidence:.3f}")

# 直接预测
features = {
    'price_return_1': 0.002,
    'momentum_3': 100,
    'rsi': 65
}
action, confidence = enhancer.predict_signal(features)
```

---

## 5. 性能告警系统 (`performance_alerts.py`)

### 核心功能
- 实时性能监控
- 多级别告警（INFO/WARNING/ERROR/CRITICAL）
- 自动阈值检测
- 告警处理器注册
- 系统健康评分

### 主要接口

#### `AlertThreshold`
```python
def get_threshold(metric_name: str) -> Dict[str, float]
```
获取指标阈值配置

**监控指标:**
- `latency_ms`: 延迟（毫秒）
- `error_rate_pct`: 错误率（百分比）
- `win_rate_pct`: 胜率（百分比）
- `drawdown_pct`: 回撤（百分比）
- `cpu_usage_pct`: CPU使用率（百分比）
- `memory_usage_pct`: 内存使用率（百分比）

#### `PerformanceMonitor`
```python
def __init__(window_size: int = 100)
def update_metric(metric_name: str, value: float)
def get_metric_avg(metric_name: str, window: int = 10) -> float
def get_current_metrics() -> Dict[str, float]
```

#### `AlertSystem`
```python
def register_handler(level: AlertLevel, handler: Callable)
```
注册告警处理器

```python
def check_metrics() -> List[Alert]
def update_metrics(metrics: Dict[str, float]) -> List[Alert]
```
批量更新指标并检查告警

```python
def get_active_alerts() -> List[Alert]
def get_alert_history(limit: int = 100) -> List[Alert]
def resolve_alert(alert_id: str)
def get_system_status() -> Dict[str, Any]
```
获取系统状态（包含健康分数）

### 使用示例
```python
from scripts.performance_alerts import AlertSystem, AlertLevel, default_alert_handler

# 创建系统
system = AlertSystem()

# 注册处理器
system.register_handler(AlertLevel.WARNING, default_alert_handler)
system.register_handler(AlertLevel.ERROR, default_alert_handler)

# 更新指标
metrics = {
    'latency_ms': 800,
    'error_rate_pct': 0.1,
    'win_rate_pct': 60,
    'drawdown_pct': 2,
    'cpu_usage_pct': 40,
    'memory_usage_pct': 50
}
alerts = system.update_metrics(metrics)

# 获取系统状态
status = system.get_system_status()
print(f"健康分数: {status['health_score']}/100")
print(f"状态: {status['status']}")
```

---

## V3.5 模块集成指南

### 集成到主程序
```python
from scripts.backtesting_engine import BacktestEngine
from scripts.smart_order_router import SmartOrderRouter
from scripts.multi_exchange_adapter import ExchangeManager
from scripts.ml_signal_enhancer import MLSignalEnhancer
from scripts.performance_alerts import AlertSystem

class TradingSystemV35:
    def __init__(self):
        # 初始化所有V3.5模块
        self.backtest_engine = BacktestEngine()
        self.order_router = SmartOrderRouter()
        self.exchange_manager = ExchangeManager()
        self.signal_enhancer = MLSignalEnhancer()
        self.alert_system = AlertSystem()

    async def run(self):
        # 1. 多交易所连接
        self.exchange_manager.connect_all()

        # 2. 增强信号
        enhanced_signal = self.signal_enhancer.enhance_signal(original_signal)

        # 3. 智能路由
        routing_result = self.order_router.route_order(
            symbol='BTCUSDT',
            side='BUY',
            size=0.5,
            allow_split=True
        )

        # 4. 执行订单
        for exec_plan in routing_result['suggested_execution']:
            adapter = self.exchange_manager.get_adapter(exec_plan['exchange'])
            adapter.place_order(order)

        # 5. 监控告警
        self.alert_system.update_metrics(performance_metrics)
```

---

## 性能建议

### 回测引擎
- 使用批量数据处理提高性能
- 定期清理历史交易记录（>1000条）
- 合理设置滑动窗口大小

### 智能订单路由
- 缓存市场深度数据，减少API调用
- 拆单时考虑交易所最小订单量限制
- 定期更新交易所流动性评分

### 多交易所适配器
- 使用连接池管理多个交易所连接
- 实现断线重连机制
- 限制并发请求数量避免API限流

### 机器学习信号增强
- 定期重新训练模型权重
- 监控特征重要性变化
- 使用滚动窗口保持特征时效性

### 性能告警系统
- 合理设置告警冷却时间（避免告警风暴）
- 实现告警聚合和去重
- 支持告警升级机制

---

## 扩展方向

### 计划中的V4.0功能
1. 深度学习模型集成（LSTM、Transformer）
2. 强化学习交易智能体
3. 分布式回测引擎
4. 实时风控策略热更新
5. 多资产组合优化
