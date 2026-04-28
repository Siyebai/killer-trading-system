# 13项硬风控规则详解

## 目录
- [概览](#概览)
- [规则列表](#规则列表)
- [配置方法](#配置方法)
- [规则详解](#规则详解)
- [风控最佳实践](#风控最佳实践)

## 概览

本系统实施13项硬风控规则，严格限制交易风险，确保资金安全。所有订单必须通过全部检查才能执行。

## 规则列表

| 序号 | 规则名称 | 类型 | 默认阈值 |
|------|---------|------|---------|
| 1 | 最大持仓比例 | 仓位限制 | 30% |
| 2 | 日亏损限额 | 止损限制 | 5% |
| 3 | 回撤限额 | 回撤控制 | 10% |
| 4 | 订单频率检查 | 交易频率 | 1秒间隔 |
| 5 | 价格偏离度检查 | 价格验证 | 1% |
| 6 | 集中度风险检查 | 分散控制 | 40% |
| 7 | 杠杆限额检查 | 杠杆控制 | 3倍 |
| 8 | 市场波动率检查 | 市场状态 | 5% |
| 9 | 订单规模限制 | 流量控制 | 10% |
| 10 | 相关性风险检查 | 相关性控制 | 30% |
| 11 | 流动性风险检查 | 深度验证 | 0.2%点差 |
| 12 | 系统健康检查 | 系统状态 | 实时 |
| 13 | 时间限制检查 | 时间窗口 | 24/7 |

## 配置方法

### 风控配置文件格式 (risk_config.json)
```json
{
  "max_position_ratio": 0.3,
  "max_daily_loss": 0.05,
  "max_drawdown": 0.10,
  "min_order_interval": 1.0,
  "max_price_deviation": 0.01,
  "max_concentration": 0.4,
  "max_leverage": 3.0,
  "max_volatility": 0.05,
  "max_order_ratio": 0.1,
  "max_correlated_exposure": 0.3,
  "max_spread": 0.002,
  "trading_hours": ["00:00-24:00"]
}
```

### 调用风控检查
```bash
python scripts/risk_control.py \
  --order '{"symbol":"BTCUSDT","side":"buy","size":0.1,"price":50000}' \
  --position position.json \
  --risk_config risk_config.json \
  --market_state '{"mid_price":50000,"volatility":0.02,"spread":0.001}'
```

## 规则详解

### 规则1: 最大持仓比例检查
**目的**: 限制单一品种的持仓规模，防范集中风险

**计算公式**:
```
new_position = |current_position| + |order_size|
max_allowed = account_balance * max_position_ratio / price

触发条件: new_position > max_allowed
```

**参数建议**:
- 保守: 20%
- 标准: 30%
- 激进: 50%

### 规则2: 日亏损限额检查
**目的**: 防止单日过度亏损

**计算公式**:
```
daily_pnl = sum(当日交易盈亏)
loss_ratio = |daily_pnl| / account_balance

触发条件: daily_pnl < 0 AND loss_ratio > max_daily_loss
```

**参数建议**:
- 保守: 3%
- 标准: 5%
- 激进: 8%

### 规则3: 回撤限额检查
**目的**: 控制从历史高点的最大回撤

**计算公式**:
```
drawdown = (peak_equity - current_equity) / peak_equity

触发条件: drawdown > max_drawdown
```

**参数建议**:
- 保守: 5%
- 标准: 10%
- 激进: 15%

### 规则4: 订单频率检查
**目的**: 防止过度交易和刷单

**检查内容**:
- 同一品种最小订单间隔
- 防止短时间内重复下单

**参数建议**:
- 高频策略: 0.1秒
- 中频策略: 1秒
- 低频策略: 5秒

### 规则5: 价格偏离度检查
**目的**: 确保订单价格接近市场价

**计算公式**:
```
deviation = |order_price - market_price| / market_price

触发条件: deviation > max_price_deviation
```

**参数建议**:
- 市价单: 0.5%
- 限价单: 1%
- 大单: 0.2%

### 规则6: 集中度风险检查
**目的**: 控制单一品种占总资金的比例

**计算公式**:
```
symbol_exposure = |symbol_position| + |order_size|
total_exposure = sum(|all_positions|)
concentration = symbol_exposure / total_exposure

触发条件: concentration > max_concentration
```

**参数建议**:
- 分散策略: 30%
- 集中策略: 50%
- 单一策略: 80%

### 规则7: 杠杆限额检查
**目的**: 限制杠杆倍数，控制风险敞口

**计算公式**:
```
notional_value = |order_size| * order_price
leverage = notional_value / available_balance

触发条件: leverage > max_leverage
```

**参数建议**:
- 保守: 2倍
- 标准: 3倍
- 激进: 5倍

### 规则8: 市场波动率检查
**目的**: 在高波动环境下暂停交易

**计算方法**:
```
volatility = 标准差 / 均价 (最近N根K线)

触发条件: volatility > max_volatility
```

**参数建议**:
- 正常市场: 3%
- 高波市场: 5%
- 极端市场: 10%

### 规则9: 订单规模限制
**目的**: 避免大单对市场造成冲击

**计算公式**:
```
order_value = |order_size| * order_price
ratio = order_value / orderbook_value

触发条件: ratio > max_order_ratio
```

**参数建议**:
- 流动性好的品种: 20%
- 流动性差的品种: 5%

### 规则10: 相关性风险检查
**目的**: 限制高相关性品种的总持仓

**相关品种对**:
- BTC/ETH: 高相关
- 各主流币对: 中相关
- 独立品种: 低相关

**参数建议**:
- 保守: 20%
- 标准: 30%
- 激进: 50%

### 规则11: 流动性风险检查
**目的**: 确保有足够流动性执行订单

**检查内容**:
- 买卖价差
- 订单簿深度
- 成交量

**参数建议**:
- 主流币: 0.1%
- 次主流: 0.3%
- 小市值: 1%

### 规则12: 系统健康检查
**目的**: 确保系统运行正常

**检查内容**:
- API连接状态
- 数据延迟
- 内存占用
- CPU使用率

### 规则13: 时间限制检查
**目的**: 限制交易时间窗口

**使用场景**:
- 避开重大新闻时段
- 限制交易时段
- 维护时间窗口

**配置示例**:
```json
{
  "trading_hours": ["09:00-17:00"],
  "exclude_events": ["FOMC", "CPI", "NFP"]
}
```

## 风控最佳实践

### 1. 参数配置原则
- 初始使用保守参数
- 根据回测结果调整
- 实盘时进一步收紧
- 定期复盘优化

### 2. 风控层次
```
第一层: 策略级风控
  - 止损止盈
  - 仓位管理

第二层: 组合级风控
  - 品种分散
  - 相关性控制

第三层: 账户级风控
  - 总仓位限制
  - 回撤控制
```

### 3. 紧急处理
- 触发止损: 立即平仓
- 超出限额: 暂停开仓
- 系统异常: 停止所有交易
- 极端行情: 启动熔断

### 4. 监控指标
- 实时盈亏
- 持仓分布
- 风险敞口
- 触发规则统计

### 注意事项
- 风控规则不可绕过
- 参数调整需谨慎测试
- 定期检查规则有效性
- 记录所有风控触发日志
