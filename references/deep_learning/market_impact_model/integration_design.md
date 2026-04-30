# 市场冲击模型整合设计

## 一、整合目标

在交易系统的信号过滤层（`ev_filter.py`）和订单执行层（`order_lifecycle_manager.py`）中，集成基于SquareRoot模型的市场冲击估算，实现以下目标：

1. **EV修正**：在信号筛选时，将冲击成本从预期收益中扣除，得到真实的净EV
2. **动态阈值**：根据市场波动率和流动性状态，自动调整EV阈值
3. **分批执行建议**：对大单订单提供分批执行计划，替代一次性全量下单
4. **TCA日志**：记录每笔订单的预测冲击与实际冲击偏差，建立反馈机制

---

## 二、需要修改的模块

### 2.1 新增：`scripts/market_impact_estimator.py`

**职责**：提供标准化的市场冲击估算接口

**核心功能**：
- `estimate_impact(order, market_state)`：返回冲击成本估算
- `calculate_participation_rate(order)`：计算参与率
- `get_adaptive_threshold(market_state)`：根据市场状态返回动态阈值

**模型选择**：以SquareRoot为主（实证支持），AC为辅（框架完整性）

```python
class MarketImpactEstimator:
    """
    冲击估算器 - SquareRoot主导 + AC备选
    """
    def __init__(self, config=None):
        self.config = config or {
            # SquareRoot参数 (待从真实数据校准)
            'sigma_multiplier': 1.0,  # 波动率放大系数
            'adv_window': 20,  # ADV滚动窗口
            'decay_factor': 0.7,  # 做空方向系数
            # 场景阈值 (基于实验结果设定)
            'thresholds': {
                'normal': 0.005,
                'high_vol': 0.015,
                'low_liquidity': 0.010,
                'combined': 0.020
            }
        }

    def estimate(self, order, market_data):
        """
        估算订单的冲击成本和净EV
        """
        sigma = market_data['volatility']
        adv = self._calculate_adv(market_data)
        participation = abs(order.quantity) / adv

        # SquareRoot冲击: σ × √(Q/ADV)
        impact_pct = sigma * np.sqrt(max(participation, 1e-10))

        # 方向修正
        if order.direction == 'SHORT':
            impact_pct *= self.config['decay_factor']

        return {
            'impact_pct': impact_pct,
            'impact_usd': impact_pct * order.price * order.quantity,
            'participation_rate': participation,
            'gross_ev': order.expected_value,
            'net_ev': order.expected_value - impact_pct
        }

    def get_threshold(self, market_state):
        """根据市场状态返回EV阈值"""
        thresholds = self.config['thresholds']
        if market_state == 'EXTREME_VOL':
            return thresholds['combined']
        elif market_state == 'HIGH_VOL':
            return thresholds['high_vol']
        elif market_state == 'LOW_LIQUIDITY':
            return thresholds['low_liquidity']
        else:
            return thresholds['normal']
```

---

### 2.2 修改：`scripts/ev_filter.py`

**修改位置**：`_calculate_ev` 方法

**修改内容**：
1. 注入市场数据参数
2. 在计算EV时减去冲击成本
3. 对低净EV订单增加拒绝日志

```python
# 在 EVFilterInput 中新增字段
class EVFilterInput:
    quantity: float = 0.0  # 订单数量（用于冲击估算）

# 修改 _calculate_ev 方法签名
def _calculate_ev(self, signal, market_data=None):
    # ... 原有逻辑 ...

    # 新增：冲击成本估算
    if market_data and signal.quantity > 0:
        impact = self.impact_estimator.estimate(signal, market_data)
        # 修正净EV
        gross_ev = ev
        net_ev = gross_ev - impact['impact_pct']

        if net_ev < 0:
            return EVResult(
                passed=False,
                ev=ev,
                net_ev=net_ev,
                error=f"EV={net_ev:.4f} < 0 after impact cost ({impact['impact_pct']:.4f}), REJECTED"
            )

    return EVResult(passed=ev >= min_ev, ev=ev, net_ev=ev)
```

**需要注意**：冲击估算依赖ADV数据，需要`market_state_machine.py`先提供市场状态和ADV估计。

---

### 2.3 修改：`scripts/market_state_machine.py`

**修改位置**：市场状态检测结果

**修改内容**：在状态检测时，增加ADV估算字段

```python
def detect_state(self, df, volume_column='volume'):
    """
    检测市场状态
    返回: (MarketState, adx, {'volatility': σ, 'adv': ADV, 'liquidity': 'normal'|'low'|'high'})
    """
    # ... 现有逻辑 ...

    # 新增：ADV估算（20日滚动均值）
    adv = df[volume_column].rolling(20).mean().iloc[-1]

    # 新增：流动性状态判断
    adv_ma = df[volume_column].rolling(60).mean().iloc[-1]
    if adv < adv_ma * 0.5:
        liquidity = 'low'
    elif adv > adv_ma * 1.5:
        liquidity = 'high'
    else:
        liquidity = 'normal'

    return (
        state,
        adx,
        {
            'volatility': volatility,
            'adv': adv,
            'liquidity': liquidity
        }
    )
```

---

### 2.4 修改：`scripts/order_lifecycle_manager.py`

**修改位置**：订单执行阶段

**修改内容**：对大单（参与率 > 1%）建议分批执行

```python
def check_impact_advisory(self, order, market_data):
    """
    检查是否需要分批执行
    返回: (needs_slicing: bool, slices: int, slice_size: float)
    """
    participation = abs(order.quantity) / market_data.get('adv', 1000)

    if participation > 0.01:  # 参与率 > 1% 建议分批
        # 目标：每批参与率 ≤ 0.5%
        target = 0.005
        slices = max(2, int(np.ceil(participation / target)))
        slice_size = order.quantity / slices

        return True, slices, slice_size

    return False, 1, order.quantity
```

---

## 三、数据流变化

```
原始数据流:
  K线数据 → 市场状态机 → 策略信号 → EV过滤器 → 订单 → 执行 → 记录

新增后数据流:
  K线数据 → 市场状态机 → (新增ADV/波动率) → 策略信号
                                              ↓
                                    EV过滤器(+冲击估算)
                                              ↓
                                    订单(含参与率/冲击建议)
                                              ↓
                               订单生命周期管理(+分批建议)
                                              ↓
                                    分批执行计划
                                              ↓
                                    实际执行 → TCA日志
                                              ↓
                                    反馈 → ADV校准
```

---

## 四、TCA日志设计（新增）

```python
# scripts/tca_logger.py
class TCALogger:
    """
    Transaction Cost Analysis日志
    记录每笔订单的预测vs实际冲击
    """
    def log_trade(self, order, execution, prediction):
        actual_slippage = (execution.avg_price - order.price) / order.price
        predicted_impact = prediction['impact_pct']

        return {
            'order_id': order.id,
            'symbol': order.symbol,
            'quantity': order.quantity,
            'predicted_impact': predicted_impact,
            'actual_slippage': actual_slippage,
            'deviation': actual_slippage - predicted_impact,
            'participation_rate': prediction['participation_rate'],
            'market_state': prediction['market_state'],
            'timestamp': execution.time
        }

    def recalibrate(self, lookback_days=30):
        """
        用过去N天的TCA数据重新校准模型参数
        """
        # 计算预测偏差的均值和标准差
        # 如果偏差系统性偏离0，调整sigma_multiplier
```

---

## 五、预期收益与风险

### 预期收益

| 改进项 | 预期效果 | 验证方式 |
|--------|----------|----------|
| EV修正后过滤 | 减少约10-15%的低质量订单 | 对比过滤前后的胜率 |
| 动态阈值 | 高波动期减少50%大单亏损 | 分场景统计 |
| 分批执行 | 大单冲击降低30-50% | TCA日志对比 |
| TCA反馈 | 6周后参数误差<5% | 校准日志 |

### 潜在风险

| 风险 | 缓解措施 |
|------|----------|
| ADV估计不准确 | 使用较长窗口（20-60日），异常值平滑 |
| 冲击模型系统性偏差 | TCA日志定期校准，每季度重新拟合 |
| 过拟合到历史数据 | 留出30%数据进行样本外验证 |
| 计算延迟影响执行 | 冲击估算异步执行，不阻塞订单生成 |

---

## 六、需主人确认事项

1. **冲击估算是否完全自动**：还是仅作为建议供人工确认后生效？
2. **ADV数据来源**：使用成交量（volume）还是Quote资产（USDT）计量？
3. **分批执行策略**：是系统自动拆分还是仅输出建议？
4. **TCA校准频率**：每月/每季度/手动触发？
5. **SquareRoot vs AC权重**：混合模型中两者的比例如何设定？
