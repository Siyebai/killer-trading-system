# 模块职责边界与权威源映射

**文档版本**: V1.0
**编制日期**: 2026-04-28
**目的**: 明确各模块的唯一职责，消除职责重叠，建立权威源原则

---

## 一、权威源原则

### 1.1 原则定义

**权威源 (Authoritative Source)**: 某类数据或行为的唯一真实来源。

- **读取规则**: 其他模块需要此类数据时，必须从权威源读取，不得自行计算或缓存。
- **修改规则**: 修改此类数据必须通过权威源的公开API，不得直接修改其内部状态。
- **异常规则**: 权威源不可用时，系统应降级或拒绝操作，而非从其他地方获取可能不一致的数据。

### 1.2 权威源映射表

| 数据/行为 | 权威源模块 | 公开接口 | 修改限制 |
|-----------|-----------|---------|---------|
| **系统状态** | `global_controller.py` | `GlobalState.get()`, `GlobalState.set()` | 仅通过 `GlobalState.set()` 修改，需校验转换合法性 |
| **订单状态** | `order_lifecycle_manager.py` | `get_order_state()`, `transition_order_state()` | 仅通过状态转换方法修改，校验 `_VALID_TRANSITIONS` |
| **信号质量评分** | `ev_filter.py` | `calculate_ev()`, `filter_signals()` | 只读，策略模块不得修改EV值 |
| **市场状态判定** | `adaptive_threshold_matrix.py` | `get_market_state()`, `get_ev_threshold()` | 只读，状态由内部算法判定 |
| **止损参数** | `adaptive_stop_loss.py` | `calculate_stop_loss()`, `update_atr()` | 通过ATR更新方法修改，禁止直接覆盖 |
| **风控规则** | `risk_engine.py` | `check_risk()`, `get_risk_limits()` | 通过配置更新，禁止运行时修改阈值 |
| **持仓信息** | `position_tracker.py` | `get_position()`, `update_position()` | 仅通过订单成交事件更新 |
| **配置值** | `config_manager.py` | `get_config()`, `reload_config()` | 只读，配置变更需重启或调用 `reload_config()` |
| **K线数据** | `market_scanner.py` | `get_kline_data()`, `scan_market()` | 从交易所或缓存读取，禁止修改历史数据 |
| **策略权重** | `linucb_cold_start.py` | `get_weights()`, `update_weights()` | 通过反馈机制更新，禁止手动调整 |

---

## 二、模块职责分类

### 2.1 决策层 (Decision Layer)

负责消费市场数据事件，产出交易决策。

| 模块 | 职责 | 输入 | 输出 | 依赖 |
|------|------|------|------|------|
| `strategy_engine.py` | 策略调度与信号分发 | 市场扫描事件 | 信号集合 | 市场状态、策略权重 |
| `ma_trend.py` | 均线趋势策略 | K线数据 | 趋势信号 | 均线周期配置 |
| `orderflow_break.py` | 订单流突破策略 | K线数据 | 突破信号 | 订单流阈值 |
| `volatility_break.py` | 波动率突破策略 | K线数据、GARCH预测 | 波动信号 | GARCH模型 |
| `rsi_mean_revert.py` | RSI均值回归策略 | K线数据、RSI指标 | 回归信号 | RSI周期配置 |
| `ev_filter.py` | 期望值过滤 | 原始信号 | 过滤后信号 | EV阈值、市场状态 |
| `adaptive_threshold_matrix.py` | 自适应阈值管理 | 市场状态、GARCH预测 | EV阈值调整 | 市场状态历史 |
| `decision_engine.py` | 决策融合与优先级排序 | 过滤后信号 | 最终决策 | 风控限制、仓位管理 |
| `linucb_cold_start.py` | 策略权重分配 | 策略历史收益 | 权重分布 | 探索- exploitation 参数 |

**边界原则**:
- 决策层不直接访问订单执行接口
- 决策层不修改系统状态（通过事件请求）
- 决策层输出决策事件，由控制层处理

---

### 2.2 控制层 (Control Layer)

负责管理系统状态、风控规则、修复协议。

| 模块 | 职责 | 输入 | 输出 | 依赖 |
|------|------|------|------|------|
| `global_controller.py` | 全局状态管理、总控调度 | 健康检查事件、决策事件 | 状态变更事件、执行指令 | 健康检查器、修复引擎 |
| `risk_engine.py` | 风控规则检查 | 决策事件、持仓信息 | 风控通过/拒绝事件 | 风控配置、持仓数据 |
| `predictive_risk_control.py` | 预测性风控（GARCH/VaR） | 市场波动数据 | 风险预警事件 | GARCH模型、历史数据 |
| `repair_upgrade_protocol.py` | 修复升级协议 | 健康降级事件 | 修复动作事件 | 修复策略库 |
| `self_healing_loop.py` | 自愈闭环控制器 | 修复失败事件 | 修复重试事件 | 修复协议、状态机 |
| `circuit_breaker.py` | 熔断器 | 连续失败计数 | 熔断/解熔断事件 | 失败阈值配置 |

**边界原则**:
- 控制层不直接执行交易
- 控制层通过事件广播状态变更
- 控制层管理系统的全局行为矩阵

---

### 2.3 执行层 (Execution Layer)

负责执行交易指令、上报执行结果。

| 模块 | 职责 | 输入 | 输出 | 依赖 |
|------|------|------|------|------|
| `market_scanner.py` | 市场扫描与数据获取 | 扫描指令 | 市场数据事件 | 交易所API/数据源 |
| `order_lifecycle_manager.py` | 订单生命周期管理 | 订单提交/成交事件 | 订单状态变更事件 | 状态机规则 |
| `order_executor.py` | 订单执行与路由 | 执行指令 | 订单提交事件 | 交易所连接池 |
| `order_execution_engine_v60.py` | 订单执行引擎（V6.0） | 决策事件 | 订单执行结果 | 动态滑点模型 |
| `position_tracker.py` | 持仓跟踪与管理 | 成交事件 | 持仓信息 | 持仓数据库 |
| `backtesting_engine.py` | 回测引擎（模拟执行） | 决策事件 | 回测结果 | 历史K线、滑点模型 |

**边界原则**:
- 执行层不参与决策逻辑
- 执行层通过事件上报执行结果
- 执行层实现物理隔离（模拟盘/实盘）

---

## 三、事件流规范

### 3.1 标准事件类型

| 事件类型 | 发布者 | 订阅者 | 说明 |
|----------|--------|--------|------|
| `state.changed` | global_controller | 所有模块 | 系统状态变更 |
| `market.scan_completed` | market_scanner | composite_analysis, 策略 | 市场扫描完成 |
| `signal.generated` | 策略模块 | ev_filter, decision_engine | 信号生成 |
| `signal.filtered` | ev_filter | decision_engine | 信号过滤结果 |
| `decision.made` | decision_engine | risk_engine, order_executor | 决策制定 |
| `risk.check_passed` | risk_engine | order_executor | 风控通过 |
| `risk.limit_breached` | risk_engine | global_controller | 风控阈值突破 |
| `order.submitted` | order_lifecycle_manager | position_tracker, 日志系统 | 订单提交 |
| `order.filled` | order_lifecycle_manager | position_tracker, risk_engine | 订单成交 |
| `order.cancelled` | order_lifecycle_manager | position_tracker, 日志系统 | 订单取消 |
| `health.degraded` | health_checker | global_controller, repair_protocol | 健康降级 |
| `repair.attempted` | repair_protocol | 日志系统 | 修复尝试 |
| `repair.succeeded` | repair_protocol | global_controller | 修复成功 |
| `repair.failed` | repair_protocol | self_healing_loop | 修复失败 |

### 3.2 事件传递原则

1. **单向传播**: 事件只能从低层向高层传播（执行层→控制层→决策层）或同级广播
2. **异步处理**: 所有事件处理函数必须是非阻塞的
3. **异常隔离**: 订阅者异常不应影响其他订阅者或事件总线
4. **历史审计**: 所有事件默认记录历史（可选关闭）

---

## 四、职责重叠清理方案

### 4.1 信号过滤重叠

**现状**: `ev_filter` + `adaptive_threshold_matrix` + 各策略自身过滤

**解决方案**:
1. 各策略仅输出原始信号（标记为"未过滤"）
2. `adaptive_threshold_matrix` 提供EV阈值建议（不修改信号）
3. `ev_filter` 作为唯一过滤入口，基于EV阈值执行过滤
4. 过滤后的信号通过 `signal.filtered` 事件广播

### 4.2 止损管理重叠

**现状**: `adaptive_stop_loss` + `position_risk` + `risk_engine` 都在管理止损

**解决方案**:
1. **权威源**: `adaptive_stop_loss.py` 负责计算止损价位
2. **校验者**: `risk_engine.py` 负责校验止损是否违反风控限制
3. **执行者**: `position_tracker.py` 监控价格，触发止损订单
4. **数据流**: `adaptive_stop_loss` → `risk_engine.check_risk()` → `position_tracker.update_stop_loss()`

### 4.3 订单状态重叠

**现状**: `order_lifecycle_manager` + `order_executor` + `order_execution_engine_v60`

**解决方案**:
1. **权威源**: `order_lifecycle_manager.py` 作为订单状态唯一来源
2. **执行者**: `order_executor` 和 `order_execution_engine_v60` 仅负责物理下单
3. **状态更新**: 执行结果通过事件上报，由 `order_lifecycle_manager` 更新状态
4. **查询接口**: 所有模块通过 `order_lifecycle_manager.get_order_state()` 查询订单状态

---

## 五、配置访问规范

### 5.1 合法配置访问

```python
# ✅ 正确：通过 config_manager
from scripts.config_manager import get_config

stop_loss_threshold = get_config('stop_loss.threshold', default=0.02)
ev_threshold_trending = get_config('thresholds.ev_trending', default=0.00050)
```

### 5.2 非法配置访问

```python
# ❌ 错误：直接读取配置文件
import json

with open('assets/configs/killer_config_v60.json') as f:
    config = json.load(f)
    stop_loss_threshold = config['stop_loss']['threshold']
```

### 5.3 数据文件访问（合法）

```python
# ✅ 正确：读取数据文件（非配置）
with open('assets/data/historical_klines.json') as f:
    kline_data = json.load(f)  # 这是数据，不是配置
```

### 5.4 测试结果输出（合法）

```python
# ✅ 正确：写入测试结果
with open('references/test_results.json', 'w') as f:
    json.dump(results, f)  # 这是输出，不是配置读取
```

---

## 六、检查清单

### 6.1 模块集成检查

- [ ] 模块是否订阅了必要的事件？
- [ ] 模块是否发布了正确的事件？
- [ ] 模块是否越权修改了权威源数据？
- [ ] 模块是否通过公开接口访问权威源？
- [ ] 模块是否处理了事件订阅异常？

### 6.2 配置访问检查

- [ ] 是否通过 `config_manager.get()` 读取配置？
- [ ] 是否避免直接使用 `json.load()` 读取配置文件？
- [ ] 配置键名是否遵循 `section.key` 格式？
- [ ] 是否为必填配置项设置了默认值？

### 6.3 事件发布检查

- [ ] 事件类型是否在标准类型列表中？
- [ ] 事件payload是否包含必要字段？
- [ ] 是否在事件发布后记录了日志？
- [ ] 是否处理了事件发布失败的异常？

---

## 七、演进路线

### Phase 5.5 P1 (当前)
- [x] 创建事件总线 `event_bus.py`
- [x] 集成 `global_controller.py`
- [x] 创建配置访问检查脚本
- [x] 编写模块职责边界文档

### Phase 5.5 P2 (后续)
- [ ] 将主要模块迁移到事件驱动模式
- [ ] 修复核心配置访问违规（10-20个高频模块）
- [ ] 补充集成测试用例

### Phase 6 (长期)
- [ ] 完成所有模块的事件驱动改造
- [ ] 修复全部配置访问违规
- [ ] 建立配置访问CI门禁
- [ ] 实现闭环流程DAG化

---

## 八、附录

### 8.1 事件总线API

```python
from scripts.event_bus import get_event_bus

# 获取全局实例
event_bus = get_event_bus()

# 发布事件
event_bus.publish(
    "state.changed",
    {"from": "RUNNING", "to": "DEGRADED", "reason": "GARCH预警"},
    source="global_controller"
)

# 订阅事件
def on_state_changed(event):
    print(f"状态变更为: {event.payload['to']}")

event_bus.subscribe("state.changed", on_state_changed)

# 获取事件历史
history = event_bus.get_history("state.changed", limit=100)

# 获取统计信息
stats = event_bus.get_stats()
```

### 8.2 参考文档

- `scripts/event_bus.py` - 事件总线实现
- `scripts/global_controller.py` - 总控中心
- `scripts/config_manager.py` - 配置管理器
- `references/config_access_check_report.json` - 配置访问检查报告

---

**文档维护**: 本文档随架构演进动态更新，重大变更需记录版本历史。
