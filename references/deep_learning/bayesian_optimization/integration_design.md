# Bayesiansk Optimization 整合设计

## 概览

Bayesian Optimization (BO) 用于自动优化策略参数。与现有系统的关系:

```
Cycle 1 (HRP)          Cycle 3 (BO)              Cycle 2 (冲击)
     |                      |                         |
     v                      v                         v
资金分配权重  <---  参数优化引擎  --->  冲击模型参数
                                              (decay_rate, gamma)
```

BO是连接三个深度学习主题的桥梁:
- **上游**: 为HRP优化聚类距离函数参数
- **中游**: 优化信号引擎(RSI周期,ATR乘数等)
- **下游**: 为Hawkes冲击模型优化衰减参数

## 整合架构

### 目标

在 `system_integrator.py` 中新增BO参数优化引擎:
1. 支持多模块参数优化(信号引擎/冲击模型/HRP)
2. 与现有回测框架无缝对接
3. 结果自动写入配置文件
4. 支持样本外验证

### 代码改动

#### 1. 新增模块: `scripts/optimizer_engine.py`

```python
# scripts/optimizer_engine.py
class OptimizerEngine:
    """统一优化引擎 - BO/Random/Grid"""

    def __init__(self, mode='bayesian'):
        self.mode = mode  # 'bayesian' | 'random' | 'grid'

    def optimize(self, module: str, df: pd.DataFrame,
                 objectives: List[str] = ['sharpe']) -> Dict:
        """优化指定模块的参数

        Args:
            module: 模块名 ('signal_engine'|'impact_model'|'hrp')
            df: 历史数据
            objectives: 优化目标
        """
        # 根据module选择参数空间
        param_spaces = {
            'signal_engine': SIGNAL_PARAM_SPACE,
            'impact_model': IMPACT_PARAM_SPACE,
            'hrp': HRP_PARAM_SPACE,
        }
        # 运行优化
        # 返回最优参数 + 验证结果
```

#### 2. 修改 `system_integrator.py`

新增方法:
- `optimize_parameters(module, df)` — 触发BO优化
- `get_optimizer_config()` — 返回当前优化配置

#### 3. 修改 `config.json`

新增配置段:
```json
{
  "optimizer": {
    "default_mode": "bayesian",
    "n_iter": 50,
    "random_state": 42,
    "modules": {
      "signal_engine": {"enabled": true, "n_iter": 50},
      "impact_model": {"enabled": true, "n_iter": 30},
      "hrp": {"enabled": false, "n_iter": 20}
    }
  }
}
```

## 各模块参数空间

### 信号引擎 (signal_engine)
```python
SIGNAL_PARAM_SPACE = {
    'rsi_period': (10, 20),
    'rsi_oversold': (20, 40),
    'rsi_overbought': (60, 80),
    'atr_mult_sl': (1.0, 3.0),
    'atr_mult_tp': (1.5, 4.5),
    'bb_std': (1.5, 3.0),
    'kelly_frac': (0.3, 0.8),
}
```

### 冲击模型 (impact_model)
```python
IMPACT_PARAM_SPACE = {
    'decay_rate': (0.1, 2.0),     # 衰减率
    'base_impact': (0.0001, 0.01), # 基础冲击
    'volatility_scaling': (0.5, 2.0),  # 波动率缩放
    'adv_scaling': (0.01, 0.3),    # ADV缩放
}
```

### HRP聚类 (hrp)
```python
HRP_PARAM_SPACE = {
    'linkage_method': ['ward', 'single', 'complete', 'average'],
    'n_clusters': (2, 5),
}
```

## 与现有系统的集成点

### 1. 回测适配器 (`backtest_adapter.py`)
- 在回测开始前调用 `OptimizerEngine` 检查是否有待优化参数
- 优化后的参数自动注入回测配置

### 2. MLOps闭环 (`closed_loop_engine.py`)
- 每月自动触发BO重新优化
- 优化结果与现有反馈回路集成

### 3. 配置文件管理
- 优化结果写入 `config.json` 而非硬编码
- 支持版本化参数快照

## 参数验证

优化后的参数必须通过:
1. **样本外验证**: 在独立数据段上验证
2. **过拟合检测**: PBO (Probability of Being Better)
3. **参数稳定性**: 多次运行参数差异 < 5%

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 过拟合到历史数据 | 严格的样本外验证,PBO检测 |
| 优化时间过长 | 异步执行 + 进度报告 |
| 目标函数设计不当 | 多目标优化,明确优先级 |
| 参数空间定义过宽 | 从窄空间开始,逐步扩展 |

## 与 Cycle 1/2 的连接

```
Cycle 1 (HRP) + Cycle 2 (冲击模型)
         |                    |
         v                    v
    BO优化聚类参数      BO优化衰减参数
         |                    |
         +--------------------+
                   |
                   v
         共同优化: 信号引擎参数
                   |
                   v
         system_integrator.py
```

## 推荐实施顺序

1. **Phase 1 (立即)**: 集成实验中的 `experiment_bayesian_opt.py` 到正式模块
2. **Phase 2 (1周)**: 在真实历史数据上验证(1000根K线×多品种)
3. **Phase 3 (2周)**: 与 closed_loop_engine 的MLOps闭环集成
4. **Phase 4 (3周)**: 多目标优化(Sharpe + 最大回撤 + 交易频率)

## 需主人确认事项

1. BO优化结果的自动应用策略(完全自动/仅建议/手动确认)
2. 重新优化频率(每月/每周/每次重大行情变化后)
3. 多目标优化中各目标的权重分配
4. 是否需要PBO过拟合检测模块
