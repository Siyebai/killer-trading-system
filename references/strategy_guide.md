# 交易策略开发指南

## 目录
- [概览](#概览)
- [策略接口规范](#策略接口规范)
- [信号格式](#信号格式)
- [内置策略示例](#内置策略示例)
- [自定义策略开发](#自定义策略开发)
- [策略测试方法](#策略测试方法)

## 概览

本指南说明如何开发符合系统要求的交易策略。所有策略通过标准接口输出信号，由 `strategy_voting.py` 进行聚合。

## 策略接口规范

### 输入要求
- 市场数据：OHLCV格式（开高低收成交量）
- 时间周期：支持 1m, 5m, 15m, 1h, 4h, 1d
- 必需字段：open, high, low, close, volume, timestamp

### 输出格式
每个策略必须输出符合以下格式的信号：

```json
{
  "name": "策略名称",
  "signal": "buy|sell|hold",
  "confidence": 0.0-1.0,
  "price": 当前价格,
  "size": 建议仓位大小,
  "stop_loss": 止损价格,
  "take_profit": 止盈价格,
  "reason": "触发原因",
  "timestamp": "时间戳"
}
```

## 信号格式

### signal 字段
- `buy`: 做多信号
- `sell`: 做空信号
- `hold`: 持有/观望

### confidence 字段
- 范围：0.0 到 1.0
- 0.0-0.3: 弱信号
- 0.3-0.6: 中等信号
- 0.6-1.0: 强信号

## 内置策略示例

### 1. 移动平均线交叉策略 (MA_Cross)
```python
def ma_cross_strategy(prices: list, short_period: int = 10, long_period: int = 30):
    """MA交叉策略"""
    if len(prices) < long_period:
        return {"signal": "hold", "confidence": 0.0}

    short_ma = sum(prices[-short_period:]) / short_period
    long_ma = sum(prices[-long_period:]) / long_period

    if short_ma > long_ma:
        return {
            "name": "ma_cross",
            "signal": "buy",
            "confidence": 0.7,
            "reason": f"短期MA({short_ma:.2f}) > 长期MA({long_ma:.2f})"
        }
    elif short_ma < long_ma:
        return {
            "name": "ma_cross",
            "signal": "sell",
            "confidence": 0.7,
            "reason": f"短期MA({short_ma:.2f}) < 长期MA({long_ma:.2f})"
        }
    else:
        return {"name": "ma_cross", "signal": "hold", "confidence": 0.0}
```

### 2. RSI 超买超卖策略
```python
def rsi_strategy(prices: list, period: int = 14):
    """RSI策略"""
    if len(prices) < period + 1:
        return {"signal": "hold", "confidence": 0.0}

    # 计算RSI（简化版）
    gains = []
    losses = []

    for i in range(len(prices) - period, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return {"signal": "hold", "confidence": 0.0}

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    if rsi < 30:
        return {
            "name": "rsi",
            "signal": "buy",
            "confidence": (30 - rsi) / 30,
            "reason": f"RSI超买: {rsi:.2f}"
        }
    elif rsi > 70:
        return {
            "name": "rsi",
            "signal": "sell",
            "confidence": (rsi - 70) / 30,
            "reason": f"RSI超卖: {rsi:.2f}"
        }
    else:
        return {"name": "rsi", "signal": "hold", "confidence": 0.0}
```

### 3. MACD 策略
```python
def macd_strategy(prices: list, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD策略"""
    if len(prices) < slow + signal:
        return {"signal": "hold", "confidence": 0.0}

    # 计算EMA（简化版）
    def ema(data, period):
        multiplier = 2 / (period + 1)
        ema_list = [sum(data[:period]) / period]
        for price in data[period:]:
            ema_list.append((price - ema_list[-1]) * multiplier + ema_list[-1])
        return ema_list

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)

    macd_line = [f - s for f, s in zip(ema_fast[-slow:], ema_slow[-slow:])]
    signal_line = ema(macd_line, signal)

    if macd_line[-1] > signal_line[-1] and macd_line[-2] <= signal_line[-2]:
        return {
            "name": "macd",
            "signal": "buy",
            "confidence": 0.6,
            "reason": "MACD金叉"
        }
    elif macd_line[-1] < signal_line[-1] and macd_line[-2] >= signal_line[-2]:
        return {
            "name": "macd",
            "signal": "sell",
            "confidence": 0.6,
            "reason": "MACD死叉"
        }
    else:
        return {"name": "macd", "signal": "hold", "confidence": 0.0}
```

## 自定义策略开发

### 开发步骤
1. 定义策略逻辑
2. 实现信号计算函数
3. 输出标准格式信号
4. 集成到策略投票系统

### 代码模板
```python
def custom_strategy(market_data: dict):
    """
    自定义策略模板

    Args:
        market_data: 市场数据字典
            - prices: 价格列表
            - volumes: 成交量列表
            - timestamps: 时间戳列表

    Returns:
        信号字典
    """
    prices = market_data.get("prices", [])

    # 1. 实现策略逻辑
    # ...你的策略代码...

    # 2. 生成信号
    signal = "buy|sell|hold"
    confidence = 0.5

    # 3. 返回标准格式
    return {
        "name": "custom_strategy",
        "signal": signal,
        "confidence": confidence,
        "price": prices[-1] if prices else 0,
        "size": 0.1,  # 建议仓位
        "reason": "触发原因描述",
        "timestamp": market_data.get("timestamps", [""])[-1]
    }
```

## 策略测试方法

### 1. 单策略测试
```bash
# 生成策略信号
python -c "
import json
from your_strategy import custom_strategy

market_data = json.load(open('market_data.json'))
signal = custom_strategy(market_data)
print(json.dumps(signal))
"
```

### 2. 多策略聚合测试
```bash
# 测试投票聚合
python scripts/strategy_voting.py \
  --signals '[{"name":"ma_cross","signal":"buy","confidence":0.8},{"name":"rsi","signal":"hold","confidence":0.3}]' \
  --method weighted
```

### 3. 回测验证
- 使用历史数据运行策略
- 记录每笔交易
- 计算盈亏、胜率、夏普比率
- 分析策略稳定性

### 注意事项
- 确保信号格式符合规范
- confidence 值反映信号强度
- 提供清晰的 reason 说明
- 处理边界情况（数据不足等）
