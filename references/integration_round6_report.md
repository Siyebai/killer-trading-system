# Round 6 整合报告：职责边界整合

## 基线状态

| 指标 | 清理前 | 清理后 | 变化 |
|------|--------|--------|------|
| 模块总数 | 115 | 75 | -40 (-35%) |
| 代码总行数 | ~74,541 | ~51,000 | ~-23,500 |
| 归档文件 | 0 | 40 | +40 |
| 健康得分 | 100/100 | 100/100 | 不变 |
| 核心测试 | 187/187 | 187/187 | 不变 |

## 一、归档的死文件清单

归档目录：`_round6_archive/`（40个文件全部带 `[ARCHIVED by Round 6]` 标记头）

### 迁移工具类（2个）
| 文件 | 归档原因 |
|------|----------|
| `safe_migrate_prints.py` | 迁移工具，无活跃调用者 |
| `migrate_prints_core.py` | 迁移工具，无活跃调用者 |

### 实验文件（3个）— 被生产模块替代
| 文件 | 替代生产模块 |
|------|-------------|
| `experiment_bayesian_opt.py` | `optimizer_bayes.py` |
| `experiment_market_impact.py` | `impact_model.py` |
| `experiment_risk_parity.py` | `portfolio_hrp.py` + `risk_parity_allocator.py` |

### 旧版本回测引擎（3个）
`backtest_v2.py`, `backtest_v8.py`, `backtest_v11.py` — 均无活跃调用者

### 旧版本信号引擎（5个）
`signal_engine_v2.py`, `signal_engine_v5.py`, `signal_engine_v8.py`, `signal_engine_advanced.py`, `signal_engine_advanced_v3.py` — 均无活跃调用者

### 孤立业务脚本（27个）
`short_strategy_fixer.py`, `winrate_enhancer.py`, `rl_trading_agent.py`, `ema_strategy.py`, `supertrend_indicator.py`, `causal_factor_scorer.py`, `web_dashboard.py`, `close_profit_engine.py`, `dynamic_position.py`, `async_event_engine.py`, `trend_direction_filter.py`, `binance_testnet_client.py`, `monitoring_dashboard.py`, `database_manager.py`, `fetch_real_data.py`, `fetch_alpha_data.py`, `predictive_risk_control.py`, `dependency_analyzer.py`, `perfect_industrial_round3.py`, `state_manager.py`, `data_aggregation_engine.py`, `ml_signal_enhancer.py`, `portfolio_optimizer.py`, `validator.py`, `quick_backtest.py`, `orderbook_analyzer.py`, `ring_buffer.py`

## 二、权威源判定表

### 2.1 风控家族（Authority Source）

| 数据/行为 | 权威源 | 消费者 |
|-----------|--------|--------|
| 交易前风控检查（仓位/亏损/频率） | `risk_engine.check_pre_trade()` | `global_controller`, `closed_loop_engine` |
| 交易中风控（止损/保本/熔断） | `risk_engine.check_in_trade()` | `closed_loop_engine` |
| 熔断器状态 | `risk_engine.circuit_breaker` | `global_controller`（health probe） |
| 风控规则基类与枚举 | `risk_base.py` | 仅被 `risk_engine.py` 导入 |
| 预交易规则 | `risk_pre_trade.py` | 仅被 `risk_engine.py` 导入 |
| 交易中止损规则 | `risk_in_trade.py` | 仅被 `risk_engine.py` 导入 |
| 熔断器实现 | `risk_circuit_breaker.py` | 仅被 `risk_engine.py` 导入 |
| 风险平价权重（ERC/HERC/IVP） | `risk_parity_allocator.py` | `system_integrator.py`（建议权重） |

**判定**：`risk_engine.py` 是风控的单一权威入口，子模块为内部实现细节，不应被外部直接调用。

### 2.2 策略家族

| 数据/行为 | 权威源 | 消费者 |
|-----------|--------|--------|
| 策略信号生成 | `strategy_engine.py`（`EnhancedStrategyEngine`） | `multi_strategy_fusion_v5.py` |
| 策略回测/实验室 | `strategy_lab.py`（`StrategyLab`） | `backtest_adapter.py` |
| 影子策略池 | `shadow_strategy_pool.py` | `strategy_lifecycle_manager` |
| 策略生命周期 | `strategy_lifecycle_manager.py` | `global_controller` |

**判定**：`strategy_engine.py` 是策略信号的权威源，`strategy_lab.py` 是回测权威。职责不重叠。

### 2.3 过滤家族

| 数据/行为 | 权威源 | 消费者 |
|-----------|--------|--------|
| EV信号过滤 | `ev_filter.py`（`EVFilter`） | `closed_loop_engine` |
| 自适应阈值/市场状态分类 | `adaptive_threshold_matrix.py`（`AdaptiveThresholdMatrix`） | 独立工具模块 |
| Hurst指数过滤 | `hurst_filter.py` | `closed_loop_engine` |

**判定**：`ev_filter.py` 和 `adaptive_threshold_matrix.py` 职责不同，前者过滤交易信号，后者动态调整阈值。不重叠。

### 2.4 监控家族

| 数据/行为 | 权威源 | 消费者 |
|-----------|--------|--------|
| 系统健康检查 | `health_check.py` | `global_controller` |
| 异常检测 | `anomaly_detector.py` | 事件总线订阅者 |
| 系统稳定性监控 | `stability_monitor.py` | 独立工具 |

**判定**：三个模块职责分明，无重叠。

### 2.5 执行家族

| 数据/行为 | 权威源 | 消费者 |
|-----------|--------|--------|
| 订单状态机 | `order_lifecycle_manager.py` | `deep_performance.py` |
| 订单执行模拟 | `order_executor.py` | `compliance_audit.py` |

**判定**：`order_lifecycle_manager.py` 管理状态，`order_executor.py` 处理实际撮合。职责互补。

## 三、跨模块职责重叠分析

### 重叠1：止损逻辑（`risk_in_trade.py` vs `adaptive_stop_loss.py`）
- `adaptive_stop_loss.py` **已被归档**（不在活跃模块中）
- 止损权威：`risk_in_trade.py`（`TrailingStopRule`, `VolatilityBreakerRule`）

### 重叠2：风险控制（`risk_controller_linkage.py` vs `risk_engine.py`）
- `risk_controller_linkage.py` 提供风控建议提案（`RiskSignal` + `LinkageProposal`）
- `risk_engine.py` 是执行权威，两者互补而非重叠
- **无需修改**

## 四、验证结果

| 验证项 | 结果 |
|--------|------|
| 归档后核心测试 | 187/187 ✅ |
| 健康检查 | 100/100 ✅ |
| 模块可加载性 | 14/14 ✅ |
| 事件总线 | 32种事件 ✅ |
