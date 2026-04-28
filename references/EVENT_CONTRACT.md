# 事件总线契约规范

**版本**: v1.0.2
**生成时间**: 2025-04-28 05:18:00 UTC
**来源**: `scripts/event_bus.py`

---

## 概述

杀手锏交易系统使用事件驱动架构，通过事件总线实现模块间解耦通信。本文档定义了所有标准事件类型、Payload结构、生产者/消费者关系。

---

## 标准事件类型清单

### 1. 系统状态事件

#### state.changed
- **描述**: 系统状态变更
- **Payload结构**:
  ```json
  {
    "old_state": "string",
    "new_state": "string",
    "timestamp": float,
    "reason": "string"
  }
  ```
- **生产者**: global_controller
- **消费者**: health_check, compliance_audit

#### health.degraded
- **描述**: 系统健康降级
- **Payload结构**:
  ```json
  {
    "score": int,
    "issues": ["string"],
    "timestamp": float
  }
  ```
- **生产者**: health_check
- **消费者**: guardian_daemon, alert_system

#### health.recovered
- **描述**: 系统健康恢复
- **Payload结构**:
  ```json
  {
    "score": int,
    "timestamp": float
  }
  ```
- **生产者**: health_check
- **消费者**: guardian_daemon

---

### 2. 市场数据事件

#### market.scan_completed
- **描述**: 市场扫描完成
- **Payload结构**:
  ```json
  {
    "symbols": ["string"],
    "scan_duration": float,
    "data_points": int
  }
  ```
- **生产者**: market_scanner
- **消费者**: strategy_engine, decision_engine

#### market.data_received
- **描述**: 市场数据接收
- **Payload结构**:
  ```json
  {
    "symbol": "string",
    "price": float,
    "volume": float,
    "timestamp": float
  }
  ```
- **生产者**: orderbook_feeder
- **消费者**: strategy_engine, anomaly_detector

#### market.high_volatility_detected
- **描述**: 高波动市场检测
- **Payload结构**:
  ```json
  {
    "symbol": "string",
    "volatility_index": float,
    "threshold": float
  }
  ```
- **生产者**: anomaly_detector
- **消费者**: risk_engine, decision_engine

---

### 3. 信号事件

#### signal.generated
- **描述**: 信号生成
- **Payload结构**:
  ```json
  {
    "strategy_id": "string",
    "symbol": "string",
    "action": "buy|sell|hold",
    "confidence": float,
    "timestamp": float
  }
  ```
- **生产者**: strategy_lab
- **消费者**: signal_filter, decision_engine

#### signal.filtered
- **描述**: 信号过滤
- **Payload结构**:
  ```json
  {
    "signal": { ... },
    "filter_reason": "string",
    "timestamp": float
  }
  ```
- **生产者**: signal_filter
- **消费者**: decision_engine (日志记录)

#### signal.accepted
- **描述**: 信号接受
- **Payload结构**:
  ```json
  {
    "signal": { ... },
    "timestamp": float
  }
  ```
- **生产者**: signal_filter
- **消费者**: decision_engine

#### signal.rejected
- **描述**: 信号拒绝
- **Payload结构**:
  ```json
  {
    "signal": { ... },
    "rejection_reason": "string",
    "timestamp": float
  }
  ```
- **生产者**: signal_filter
- **消费者**: decision_engine (日志记录)

---

### 4. 决策事件

#### decision.made
- **描述**: 决策制定
- **Payload结构**:
  ```json
  {
    "decision_id": "string",
    "action": "buy|sell|hold|cancel",
    "symbol": "string",
    "quantity": float,
    "price": float,
    "confidence": float,
    "timestamp": float
  }
  ```
- **生产者**: decision_engine
- **消费者**: risk_engine, order_executor

#### decision.cancelled
- **描述**: 决策取消
- **Payload结构**:
  ```json
  {
    "decision_id": "string",
    "cancel_reason": "string",
    "timestamp": float
  }
  ```
- **生产者**: decision_engine
- **消费者**: risk_engine (日志记录)

---

### 5. 风控事件

#### risk.check_passed
- **描述**: 风控检查通过
- **Payload结构**:
  ```json
  {
    "decision_id": "string",
    "checks": {
      "position_limit": bool,
      "drawdown_limit": bool,
      "risk_ratio": bool
    },
    "timestamp": float
  }
  ```
- **生产者**: risk_engine
- **消费者**: order_executor

#### risk.limit_breached
- **描述**: 风控阈值突破
- **Payload结构**:
  ```json
  {
    "limit_type": "position|drawdown|risk_ratio",
    "current_value": float,
    "threshold": float,
    "action_taken": "string",
    "timestamp": float
  }
  ```
- **生产者**: risk_engine
- **消费者**: global_controller, alert_system

#### risk.block_signal
- **描述**: 风控阻止信号
- **Payload结构**:
  ```json
  {
    "signal": { ... },
    "block_reason": "string",
    "timestamp": float
  }
  ```
- **生产者**: risk_engine
- **消费者**: signal_filter (日志记录)

---

### 6. 订单事件

#### order.created
- **描述**: 订单创建
- **Payload结构**:
  ```json
  {
    "order_id": "string",
    "symbol": "string",
    "side": "buy|sell",
    "order_type": "limit|market",
    "quantity": float,
    "price": float,
    "timestamp": float
  }
  ```
- **生产者**: order_executor
- **消费者**: order_lifecycle_manager, compliance_audit

#### order.acknowledged
- **描述**: 订单确认
- **Payload结构**:
  ```json
  {
    "order_id": "string",
    "exchange_order_id": "string",
    "timestamp": float
  }
  ```
- **生产者**: order_executor
- **消费者**: order_lifecycle_manager

#### order.submitted
- **描述**: 订单提交
- **Payload结构**:
  ```json
  {
    "order_id": "string",
    "timestamp": float
  }
  ```
- **生产者**: order_executor
- **消费者**: order_lifecycle_manager

#### order.filled
- **描述**: 订单成交
- **Payload结构**:
  ```json
  {
    "order_id": "string",
    "symbol": "string",
    "side": "buy|sell",
    "filled_quantity": float,
    "avg_price": float,
    "commission": float,
    "timestamp": float
  }
  ```
- **生产者**: order_executor
- **消费者**: order_lifecycle_manager, portfolio_tracker

#### order.partially_filled
- **描述**: 订单部分成交
- **Payload结构**:
  ```json
  {
    "order_id": "string",
    "filled_quantity": float,
    "remaining_quantity": float,
    "avg_price": float,
    "timestamp": float
  }
  ```
- **生产者**: order_executor
- **消费者**: order_lifecycle_manager

---

## 使用规范

### 1. 发布事件
```python
from scripts.event_bus import EventBus

event_bus = EventBus()
event_bus.publish(
    event_type="signal.generated",
    payload={
        "strategy_id": "sma_crossover",
        "symbol": "BTC/USDT",
        "action": "buy",
        "confidence": 0.85
    },
    source="strategy_lab"
)
```

### 2. 订阅事件
```python
def handle_signal(event):
    print(f"收到信号: {event.payload}")

event_bus.subscribe("signal.generated", handle_signal)
```

### 3. 自定义事件
自定义事件类型应遵循命名规范：`category.action`
- ✅ 推荐: `market.scan_completed`, `risk.limit_breached`
- ❌ 不推荐: `my_event`, `test123`

---

## 性能考虑

- **事件历史缓冲**: 默认保留最近10000条事件
- **订阅者异常隔离**: 单一订阅者失败不影响其他订阅者
- **线程安全**: 使用Lock保证多线程安全
- **性能基准**: 事件吞吐 > 25000 msg/s

---

## 维护说明

添加新事件类型时：
1. 更新本文档
2. 在`event_bus.py`的`STANDARD_EVENT_TYPES`中注册
3. 更新生产者和消费者列表
4. 添加相应的测试用例

---

**文档维护者**: 杀手锏交易系统开发团队
**最后更新**: 2025-04-28
