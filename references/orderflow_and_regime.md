# 订单流分析与市场状态识别

## 目录
- [概览](#概览)
- [订单流分析](#订单流分析)
- [市场状态识别](#市场状态识别)
- [集成应用](#集成应用)
- [实战案例](#实战案例)

## 概览

订单流分析和市场状态识别是高频交易的核心能力，帮助理解微观市场结构并做出更优的交易决策。

## 订单流分析

### 核心概念

#### 1. 买卖压力（Imbalance）
衡量主动买入和主动卖出的相对强度。

**计算公式**:
```
imbalance = (主动买入量 - 主动卖出量) / 总成交量
```

**取值范围**: -1 (完全卖方主导) 到 +1 (完全买方主导)

#### 2. CVD（累积成交量差额）
累积的买卖差额，反映资金流向趋势。

**计算公式**:
```
CVD[t] = CVD[t-1] + delta[t]
delta[t] = 主动买入量 - 主动卖出量
```

#### 3. CVD斜率（CVD Slope）
CVD的变化率，反映买卖压力的变化趋势。

**计算方法**: 线性回归斜率

### 脚本使用

```bash
python scripts/order_flow.py \
  --trades ./trades.json \
  --imbalance_threshold 0.3 \
  --cvd_trend_threshold 0.2
```

### 输出示例
```json
{
  "status": "success",
  "features": {
    "imbalance": 0.45,
    "pressure": 0.38,
    "cvd": 1250.5,
    "cvd_slope": 8.3,
    "trade_count": 50
  },
  "signal_analysis": {
    "signal": "buy",
    "strength": 0.9,
    "reason": "买方主导: 不平衡度=0.450, CVD斜率=8.300"
  }
}
```

### 交易信号生成

**买入信号条件**:
- imbalance > 0.3 (买方主导)
- cvd_slope > 0.2 (CVD上升趋势)

**卖出信号条件**:
- imbalance < -0.3 (卖方主导)
- cvd_slope < -0.2 (CVD下降趋势)

## 市场状态识别

### 市场状态分类

| 状态 | 特征 | 适用策略 | 交易建议 |
|------|------|---------|---------|
| TREND | 趋势强度高，订单流一致 | 趋势跟踪 | 顺势交易 |
| RANGE | 趋势强度低，波动率低 | 均值回归 | 高抛低吸 |
| HIGH_VOLATILITY | 波动率过高 | 减仓/观望 | 降低仓位 |
| BAD_LIQUIDITY | 点差过大 | 停止交易 | 等待恢复 |
| NOISE | 无明显特征 | 观望 | 暂不交易 |

### 判断逻辑

#### 1. 流动性检查
```python
spread = (ask - bid) / price
if spread > max_spread_pct:
    return BAD_LIQUIDITY
```

#### 2. 波动率检查
```python
if volatility > volatility_halt_threshold:
    return HIGH_VOLATILITY
```

#### 3. 趋势检查
```python
trend_strength = abs(sma5 - sma20) / price
if trend_strength > trend_threshold and flow_strength > flow_threshold:
    return TREND
```

#### 4. 震荡检查
```python
if trend_strength < range_threshold and volatility < range_volatility:
    return RANGE
```

### 脚本使用

```bash
python scripts/market_regime.py \
  --indicators '{"sma5":50100,"sma20":50000,"volatility":0.008,"rsi":55}' \
  --orderflow '{"pressure":0.15,"imbalance":0.2}' \
  --market_tick '{"price":50050,"bid":50048,"ask":50052}'
```

### 输出示例
```json
{
  "status": "success",
  "regime_detection": {
    "regime": "TREND",
    "reason": "趋势市场: up, 趋势强度=0.20%",
    "confidence": 0.8,
    "details": {
      "trend_strength": 0.002,
      "volatility": 0.008,
      "spread": 0.00008,
      "flow_strength": 0.15
    }
  },
  "trading_advice": {
    "action": "follow_trend",
    "message": "趋势市场，建议使用趋势策略",
    "risk_level": "medium"
  }
}
```

## 集成应用

### 在一体化系统中使用

一体化运行模式 (`scripts/run.py`) 已集成订单流分析和市场状态识别：

```python
# 每个tick都会执行
flow = orderflow[sym].get_features()  # 订单流分析
regime = detect_market_regime(ind, flow, tick, config)  # 市场状态识别

# 只在允许的市场状态交易
if regime in [TREND, RANGE]:
    direction, strength, strategy_id = multi_engine.generate_final_signal(ind, flow)
```

### 自定义集成

```python
from scripts.order_flow import OrderFlowAnalyzer
from scripts.market_regime import MarketRegimeDetector

# 初始化
flow_analyzer = OrderFlowAnalyzer(window_size=50)
regime_detector = MarketRegimeDetector()

# 处理每个tick
def on_tick(tick):
    # 更新订单流
    flow_analyzer.add_trade(tick['price'], tick['volume'], tick['is_buyer_maker'])
    flow_features = flow_analyzer.get_features()

    # 识别市场状态
    indicators = calculate_indicators(tick)
    regime = regime_detector.detect(indicators, flow_features, tick)

    # 根据状态决策
    if regime['regime'] == 'TREND':
        # 使用趋势策略
        pass
    elif regime['regime'] == 'RANGE':
        # 使用均值回归策略
        pass
```

## 实战案例

### 案例1: 趋势突破识别

**场景**: BTC从震荡转为上升趋势

**订单流信号**:
```
imbalance: 0.42
pressure: 0.35
cvd_slope: 12.5
```

**市场状态**: TREND

**交易决策**: 买入，使用趋势策略

### 案例2: 流动性危机预警

**场景**: 市场突然流动性枯竭

**市场状态**:
```
spread: 0.0015 (> max_spread_pct 0.0004)
regime: BAD_LIQUIDITY
```

**交易决策**: 停止开新仓，平掉现有持仓

### 案例3: 高波动过滤

**场景**: 重大新闻导致剧烈波动

**市场状态**:
```
volatility: 0.025 (> volatility_halt_threshold 0.012)
regime: HIGH_VOLATILITY
```

**交易决策**: 降低仓位或暂停交易

## 参数调优建议

### 订单流参数
- `window_size`: 30-100（建议50）
- `cvd_window`: 10-30（建议20）
- `imbalance_threshold`: 0.2-0.4（建议0.3）
- `cvd_trend_threshold`: 0.1-0.3（建议0.2）

### 市场识别参数
- `max_spread_pct`: 0.0002-0.001（根据品种调整）
- `volatility_halt_threshold`: 0.008-0.015
- `trend_strength_threshold`: 0.0005-0.001
- `range_volatility_threshold`: 0.003-0.005

## 注意事项
- 订单流分析需要足够的数据量（建议>30笔）
- 市场状态识别应与技术指标结合使用
- 不同品种需要调整参数（流动性好的品种可以放宽阈值）
- 在重大新闻时段应手动降低交易频率
