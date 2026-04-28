# V4.0 模块接口文档

## 概览
V4.0版本新增4个高级AI/优化模块，大幅提升系统的实时性、预测能力、组合优化和智能决策能力。

---

## 1. 实时风控策略热更新 (`hot_reload_risk.py`)

### 核心功能
- 基于V3事件引擎的配置监听
- JSON/YAML配置文件热加载
- 无需重启即可更新风控参数
- 配置变更回调机制
- 版本管理和校验和验证

### 主要接口

#### `HotReloadRiskManager`
```python
def __init__(config_dir: str = "./config/risk")
```
初始化热更新管理器

```python
def start_watching()
def stop_watching()
```
启动/停止文件监听

```python
def register_policy(policy: RiskPolicy) -> bool
def get_policy(policy_id: str) -> Optional[RiskPolicy]
def remove_policy(policy_id: str) -> bool
```
策略管理

```python
def get_parameter(policy_id: str, param_name: str, default: Any = None) -> Any
def set_parameter(policy_id: str, param_name: str, value: Any) -> bool
```
参数获取和临时修改

```python
def register_callback(callback: Callable[[str, str], None])
```
注册配置变更回调

**回调函数签名**: `callback(policy_id: str, change_type: str)`

```python
def get_change_history(limit: int = 100) -> List[Dict[str, Any]]
def get_status() -> Dict[str, Any]
```
获取变更历史和系统状态

### 使用示例
```python
from scripts.hot_reload_risk import HotReloadRiskManager

# 创建管理器
manager = HotReloadRiskManager("./config/risk")

# 注册回调
def on_change(policy_id, change_type):
    print(f"策略 {policy_id} {change_type}")

manager.register_callback(on_change)

# 启动监听
manager.start_watching()

# 获取参数
max_pos = manager.get_parameter("default_risk", "max_position_size")

# 临时修改
manager.set_parameter("default_risk", "max_position_size", 0.7)
```

---

## 2. 深度学习模型集成 (`deep_learning_predictor.py`)

### 核心功能
- LSTM时序预测模型（简化实现）
- 10个特征自动提取
- 模型训练和推理
- 价格方向预测（UP/DOWN/NEUTRAL）
- 置信度计算

### 主要接口

#### `DeepLearningPredictor`
```python
def __init__(model_type: str = "lstm")
```
初始化预测器

```python
def train(price_history: List[float], volume_history: List[float]) -> bool
```
训练模型

**特征列表**:
- `price_return_1/3/5`: 价格收益率
- `volume_ratio`: 成交量比率
- `volatility_5`: 波动率
- `momentum_3/5`: 动量
- `ma_diff_5_10`: 趋势
- `rsi`: RSI指标
- `bb_position`: 布林带位置

```python
def predict(price_history: List[float],
           volume_history: List[float]) -> Optional[PredictionResult]
```
预测

**返回**: `PredictionResult` 包含:
- `predicted_price`: 预测价格
- `confidence`: 置信度
- `prediction_type`: 预测类型（UP/DOWN/NEUTRAL）
- `features`: 当前特征值

```python
def save_model(filepath: str)
def load_model(filepath: str)
```
模型持久化

```python
def get_model_info() -> Dict[str, Any]
```
获取模型信息

### 使用示例
```python
from scripts.deep_learning_predictor import DeepLearningPredictor

# 创建预测器
predictor = DeepLearningPredictor()

# 训练
price_history = [50000, 50100, 49900, ...]
volume_history = [1000, 1200, 800, ...]
success = predictor.train(price_history, volume_history)

# 预测
result = predictor.predict(price_history, volume_history)
if result:
    print(f"预测: {result.prediction_type}")
    print(f"价格: ${result.predicted_price:.2f}")
    print(f"置信度: {result.confidence:.2f}")

# 保存模型
predictor.save_model("lstm_model.pkl")
```

---

## 3. 多资产组合优化 (`portfolio_optimizer.py`)

### 核心功能
- 马科维茨投资组合理论
- 协方差矩阵计算
- 多种优化策略
- 有效前沿计算
- 组合回测

### 主要接口

#### `PortfolioOptimizer`
```python
def __init__(risk_free_rate: float = 0.02)
```
初始化优化器

```python
def optimize(assets: List[Asset], returns: Dict[str, List[float]],
            strategy: OptimizationStrategy) -> Portfolio
```
优化投资组合

**优化策略**:
- `MEAN_VARIANCE`: 均值-方差优化
- `MINIMUM_VARIANCE`: 最小方差
- `RISK_PARITY`: 风险平价
- `EQUAL_WEIGHT`: 等权重

```python
def calculate_efficient_frontier(assets: List[Asset],
                                returns: Dict[str, List[float]],
                                num_points: int = 20) -> List[Tuple[float, float, Dict]]
```
计算有效前沿

**返回**: `[(return, volatility, weights), ...]`

```python
def backtest_portfolio(portfolio: Portfolio, returns: Dict[str, List[float]],
                      start_idx: int = 0, end_idx: Optional[int] = None) -> Dict[str, float]
```
回测投资组合

**返回**: 包含收益率、波动率、夏普比率、最大回撤等指标

### 使用示例
```python
from scripts.portfolio_optimizer import PortfolioOptimizer, Asset, OptimizationStrategy

# 创建资产
assets = [
    Asset(symbol="BTC", name="Bitcoin", expected_return=0.8, volatility=0.6),
    Asset(symbol="ETH", name="Ethereum", expected_return=0.7, volatility=0.5),
]

# 生成收益率数据
returns = {
    "BTC": [0.01, -0.02, 0.03, ...],
    "ETH": [0.02, -0.01, 0.02, ...]
}

# 优化
optimizer = PortfolioOptimizer()
portfolio = optimizer.optimize(assets, returns, OptimizationStrategy.RISK_PARITY)

print(f"最优权重: {portfolio.assets}")
print(f"预期收益率: {portfolio.expected_return*100:.2f}%")
print(f"夏普比率: {portfolio.sharpe_ratio:.2f}")

# 有效前沿
frontier = optimizer.calculate_efficient_frontier(assets, returns)
for ret, vol, weights in frontier:
    print(f"收益率 {ret*100:.2f}%, 波动率 {vol*100:.2f}%")
```

---

## 4. 强化学习交易智能体 (`rl_trading_agent.py`)

### 核心功能
- OpenAI Gym风格交易环境
- DQN智能体（简化实现）
- 经验回放训练
- 动作空间：HOLD/BUY/SELL
- 状态空间：价格、持仓、现金、技术指标等

### 主要接口

#### `TradingEnvironment`
```python
def __init__(initial_cash: float = 100000.0)
def reset() -> State
def step(action: int) -> Tuple[State, float, bool, Dict]
```
交易环境（Gym风格）

**动作**: 0=HOLD, 1=BUY, 2=SELL

**状态**: 包含价格、持仓、现金、价格变化、波动率、RSI等

#### `SimpleDQNAgent`
```python
def __init__(state_size: int, action_size: int)
def remember(state, action, reward, next_state, done)
def act(state: np.ndarray, training: bool = True) -> int
def replay()
```
DQN智能体

```python
def train(env: TradingEnvironment, episodes: int = 100) -> List[float]
```
训练智能体

**返回**: 每轮的总奖励列表

```python
def evaluate(env: TradingEnvironment, episodes: int = 10) -> Dict[str, float]
```
评估智能体

**返回**: 包含平均奖励、最终权益等指标

### 使用示例
```python
from scripts.rl_trading_agent import TradingEnvironment, SimpleDQNAgent

# 创建环境
env = TradingEnvironment(initial_cash=100000.0)

# 创建智能体
agent = SimpleDQNAgent(
    state_size=env.get_observation_space(),
    action_size=env.get_action_space()
)

# 训练
episode_rewards = agent.train(env, episodes=100)

# 评估
eval_results = agent.evaluate(env, episodes=10)
print(f"平均奖励: {eval_results['avg_reward']:.4f}")
print(f"平均最终权益: ${eval_results['avg_final_value']:.2f}")

# 交易演示
state = env.reset()
for _ in range(20):
    action = agent.act(state, training=False)
    next_state, reward, done, info = env.step(action)
    print(f"动作: {['HOLD','BUY','SELL'][action]}, 价格: ${info.get('price',0):.2f}")
    if done:
        break
```

---

## V4.0 集成指南

### 完整集成示例
```python
from scripts.hot_reload_risk import HotReloadRiskManager
from scripts.deep_learning_predictor import DeepLearningPredictor
from scripts.portfolio_optimizer import PortfolioOptimizer
from scripts.rl_trading_agent import TradingEnvironment, SimpleDQNAgent

class TradingSystemV40:
    def __init__(self):
        # V4.0模块
        self.risk_manager = HotReloadRiskManager()
        self.dl_predictor = DeepLearningPredictor()
        self.portfolio_optimizer = PortfolioOptimizer()
        self.rl_agent = SimpleDQNAgent(10, 3)

        # 启动热更新
        self.risk_manager.start_watching()

    def run(self):
        # 1. 获取实时风控参数
        max_pos = self.risk_manager.get_parameter("default", "max_position_size")

        # 2. 深度学习预测
        dl_result = self.dl_predictor.predict(price_history, volume_history)

        # 3. 组合优化
        portfolio = self.portfolio_optimizer.optimize(assets, returns)

        # 4. RL智能体决策
        env = TradingEnvironment()
        action = self.rl_agent.act(state)

        # 综合决策
        if dl_result and dl_result.prediction_type == 'UP':
            # 使用RL动作
            pass
        else:
            # 保持持有
            pass
```

---

## 性能建议

### 热更新
- 合理设置检查间隔（1-5秒）
- 使用回调机制避免轮询
- 实现配置验证防止错误更新

### 深度学习
- 定期重新训练模型
- 使用滑动窗口保持数据时效性
- 生产环境建议使用PyTorch/TensorFlow

### 组合优化
- 使用协方差矩阵的逆矩阵预计算
- 限制资产数量提高性能
- 定期重新平衡

### 强化学习
- 调整探索率衰减速度
- 增加经验回放容量
- 使用优先经验回放

---

## 扩展方向

### 计划中的V5.0功能
1. Transformer时序模型
2. 多智能体协作
3. 蒙特卡洛模拟
4. 实时风控策略热更新
5. 分布式训练
