# 系统权威源映射表 (Authority Map)
版本: v1.0.3-synergy | 覆盖: 59个活跃模块

## 核心原则
- 每个业务能力有且只有**一个权威模块**
- 非权威模块通过**事件订阅**或**接口调用**获取能力，不得自行复制逻辑
- 权威模块对性能、正确性负全部责任

---

## 一、交易流水线权威

| 能力领域 | 权威模块 | 辅助/消费者 |
|---------|---------|-----------|
| **行情获取** | `futures_data_fetcher.py` (期货) / `binance_data_fetcher.py` (现货) | closed_loop_engine, paper_engine |
| **市场扫描** | `market_scanner.py` | closed_loop_engine |
| **技术指标** | `technical_indicators.py` | 全系统通用 |
| **信号生成** | `signal_engine_v4.py` (原始信号) / `signal_scorer_multidim.py` (多维评分) | multi_strategy_fusion_v5 |
| **信号融合** | `multi_strategy_fusion_v5.py` | closed_loop_engine |
| **市场状态识别** | `market_regime.py` (主) / `adaptive_threshold_matrix.py` (辅助阈值) | signal_engine_v4 |
| **信号过滤** | `ev_filter.py` | multi_strategy_fusion_v5 |
| **策略执行** | `strategy_engine.py` (MA趋势等) | strategy_lifecycle_manager |
| **策略生命周期** | `strategy_lifecycle_manager.py` | shadow_strategy_pool |
| **影子策略池** | `shadow_strategy_pool.py` | strategy_lifecycle_manager |
| **策略实验室** | `strategy_lab.py` | backtest_adapter, shadow_strategy_pool |

---

## 二、风控权威

| 能力领域 | 权威模块 | 辅助/消费者 |
|---------|---------|-----------|
| **风控门面(唯一权威)** | `risk_engine.py` | health_check, closed_loop_engine |
| **风控规则基类** | `risk_base.py` | risk_engine, risk_pre_trade, risk_in_trade |
| **交易前风控规则** | `risk_pre_trade.py` | risk_engine |
| **交易中风控规则** | `risk_in_trade.py` | risk_engine |
| **熔断器** | `risk_circuit_breaker.py` | risk_engine |
| **仓位风控** | `position_risk.py` | order_lifecycle_manager |
| **ATR追踪止损** | `atr_trailing_stop.py` | order_lifecycle_manager |

---

## 三、订单与持仓权威

| 能力领域 | 权威模块 | 辅助/消费者 |
|---------|---------|-----------|
| **订单状态机** | `order_lifecycle_manager.py` | (唯一权威，OrderState在此定义) |
| **订单执行** | `order_executor.py` | order_lifecycle_manager |
| **持仓管理** | `position_manager.py` | order_lifecycle_manager |
| **资产组合HRP** | `portfolio_hrp.py` | system_integrator, closed_loop_engine |
| **Bayesian优化** | `optimizer_bayes.py` | closed_loop_engine |
| **风险平价分配** | `risk_parity_allocator.py` | closed_loop_engine |

---

## 四、监控与反馈权威

| 能力领域 | 权威模块 | 辅助/消费者 |
|---------|---------|-----------|
| **健康检查** | `health_check.py` | daemon |
| **异常检测** | `anomaly_detector.py` | (发布anomaly.*事件) |
| **稳定性监控** | `stability_monitor.py` | daemon |
| **性能监控** | `performance_monitor.py` | closed_loop_engine |
| **元学习** | `meta_learner_maml.py` | closed_loop_engine |
| **过拟合检测** | `overfitting_detector.py` | closed_loop_engine |
| **影响模型** | `impact_model.py` | closed_loop_engine |
| **闭环引擎** | `closed_loop_engine.py` | paper_engine, backtest_adapter |
| **回测适配器** | `backtest_adapter.py` | strategy_lab |
| **纸张交易引擎** | `paper_engine_v106.py` | daemon |

---

## 五、基础设施权威

| 能力领域 | 权威模块 | 辅助/消费者 |
|---------|---------|-----------|
| **事件总线** | `event_bus.py` | 全系统唯一通信中枢 |
| **配置管理** | `config_manager.py` | 全系统唯一配置入口 |
| **统一工具库** | `unified_utils.py` | 全系统唯一工具函数源 |
| **统一数据模型** | `unified_models.py` | 全系统唯一数据模型源 |
| **日志工厂** | `logger_factory.py` | 全系统 |
| **守护进程** | `daemon.py` | 系统级 |

---

## 六、职责重叠说明

### 重叠1: 信号生成 (已明确分工)
- `signal_engine_v4.py`: 生成原始技术面信号（EMA/RSI/BB等）
- `signal_scorer_multidim.py`: 多维评分（趋势/Hurst/量价综合）
- `multi_strategy_fusion_v5.py`: 多策略融合（权威组合器）
- **结论**: 三者分工明确，无重叠移除需求

### 重叠2: 市场状态识别 (已明确分工)
- `market_regime.py`: 基于ADX、波动率的完整市场状态检测
- `adaptive_threshold_matrix.py`: 基于ADX+实现波动率的分类器
- **结论**: market_regime.py为主，adaptive_threshold_matrix.py为辅助阈值计算

### 重叠3: 组合优化 (已明确分工)
- `portfolio_hrp.py`: HRP层次风险平价（主要组合方法）
- `optimizer_bayes.py`: Bayesian超参优化
- `risk_parity_allocator.py`: 风险平价组合
- **结论**: 三者针对不同优化目标，无冲突

### 重叠4: 风控家族 (门面模式)
- `risk_engine.py`: 统一门面，初始化并协调所有风控子模块
- `risk_base.py`: 基类
- `risk_pre_trade.py`: 交易前规则实现
- `risk_in_trade.py`: 交易中规则实现
- `risk_circuit_breaker.py`: 熔断器
- **结论**: 门面+子模块模式，架构合理，无需合并

---

## 七、事件权威 (发布者)

| 事件类型前缀 | 权威发布者 |
|------------|-----------|
| `signal.*` | signal_engine_v4, signal_scorer_multidim, multi_strategy_fusion_v5 |
| `risk.*` | risk_engine |
| `order.*` | order_lifecycle_manager |
| `market.*` | market_scanner, futures_data_fetcher |
| `strategy.*` | strategy_engine, strategy_lifecycle_manager |
| `portfolio.*` | portfolio_hrp, optimizer_bayes |
| `system.*` | health_check, anomaly_detector, stability_monitor |
| `state.*` | event_bus (自动), daemon |
| `optimization.*` | optimizer_bayes |
| `hrp.*` | portfolio_hrp |
| `overfitting.*` | overfitting_detector |
| `anomaly.*` | anomaly_detector |
| `config.*` | config_manager |

---

## 八、跨版本遗留标记

| 文件 | 状态 | 原因 |
|-----|------|------|
| `order_execution_engine_v60.py` | **已废弃** | 功能被 `order_lifecycle_manager.py` 完全覆盖 |
| `complete_loop_v61.py` | **归档候选** | 功能被 `closed_loop_engine.py` 覆盖 |
| `exchange_adapter.py` | **归档候选** | 功能被 `binance_data_fetcher.py` + `order_executor.py` 覆盖 |

---

*本表为系统职责边界的唯一权威文档。任何新增能力必须先确认不属于现有权威模块，方可独立成模块。*
