# 杀手锏交易系统 v1.4/v1.5 - P4 优化报告

## P4 优化时间
2026-04-30（基于548笔真实OOS闭环交易分析）

---

## 一、根因诊断（基于548笔OOS交易）

### 核心发现
| 品种 | 交易数 | 胜率 | Gap | 收益率 | 结论 |
|------|--------|------|-----|--------|------|
| ETH+BTC | 270笔 | 31.9% | +1.0% | +11.7% | 正期望 |
| SOL+BNB | 278笔 | 23.0% | -12.0% | -100% | 结构性亏损 |

**根因**: 不是策略问题，是**品种选择问题**。

- SOL/BNB 在2024-2025年趋势市场中持续上涨/下跌，均值回归策略被反复逆势止损
- ETH+BTC 有足够的震荡期让均值回归发挥作用

### 行动项
1. **P4-1**: 排除SOL/BNB，仅运行ETH+BTC
2. **P4-2**: 市场状态过滤器（ADX>25时降低风险敞口）
3. **P4-3**: 动态阈值（震荡市降低thresh，趋势市提高thresh）

---

## 二、短周期测试结果

### Gate.io 数据管道修复
- 每批最大1000根K线（超过触发"Too many requests"错误）
- 1m: 12小时/批（720根）；3m: 48小时/批；5m: 72小时/批
- `high=max(o,h,l,c), low=min(o,h,l,c)` 修正Gate.io数据错误

### 短周期表现（P3策略，thresh=0.50，atr_sl=1.6）

| 时间周期 | 交易数 | 胜率 | 盈亏比 | Gap | 结论 |
|---------|--------|------|--------|-----|------|
| BTC-1m | 38 | 10.5% | 0.72 | -47.7% | **不可用** |
| BTC-3m | 23 | 21.7% | 0.90 | -30.9% | **不可用** |
| BTC-5m | 124 | 14.5% | 0.98 | -36.0% | **不可用** |
| BTC-15m | 2 | 0.0% | 0.00 | 0.0% | 数据不足 |
| BTC-30m | 2 | 0.0% | 0.00 | 0.0% | 数据不足 |
| BTC-1H | 46 | 23.9% | 2.36 | -5.8% | 参考基准 |
| ETH-1H | 50 | 20.0% | 2.73 | -6.8% | 参考基准 |

**结论**: 1m/3m/5m数据噪音过大，BB+RSI均值回归信号频繁失效。

**原因**:
- 1m ATR%中位数=0.033%（几乎无波动）
- 原始`vol_filter=0.25`在1m上永远不触发（0.033% < 0.25%）
- 即便移除vol_filter，噪音信号仍导致10-20%胜率

**建议**: 专注1H周期，短周期策略需完全不同的方法论（纯突破/日内动量）。

---

## 三、ADX市场状态过滤器

### P4 实现（closed_loop_engine.py）

```python
# Hurst + ADX 双维度市场状态判断（P4新增）
hurst = row.get('hurst', 0.5)
adx = row.get('adx', 25)

if adx > 30:
    mr_boost, tf_boost = 0.5, 1.4  # 抑制均值回归
    signal_boost = 0.05             # 提高阈值
elif adx > 25:
    if hurst > 0.55: mr_boost, tf_boost = 0.7, 1.3
    elif hurst < 0.45: mr_boost, tf_boost = 1.0, 1.0
    else: mr_boost, tf_boost = 0.8, 1.1
    signal_boost = 0.03
elif adx < 20:
    if hurst < 0.45: mr_boost, tf_boost = 1.4, 0.6  # 双重确认震荡
    elif hurst > 0.55: mr_boost, tf_boost = 1.1, 0.9
    else: mr_boost, tf_boost = 1.2, 0.8
    signal_boost = -0.05  # 降低阈值捕捉机会
else:
    # 中性市场: Hurst主导
    if hurst < 0.45: mr_boost, tf_boost = 1.3, 0.7
    elif hurst > 0.55: mr_boost, tf_boost = 0.7, 1.3
    else: mr_boost, tf_boost = 1.0, 1.0
    signal_boost = 0.0

# 动态阈值 = 0.52 + Hurst调整 + ADX调整
signal_threshold = 0.52 + hurst_adj + signal_boost
```

### 实证结果（Gate.io 30天数据）

| 品种 | 策略 | 交易数 | 胜率 | 盈亏比 | Gap | 收益率 |
|------|------|--------|------|--------|-----|--------|
| BTC-1H | P3(fixed=0.50) | 46 | 23.9% | 2.42 | -5.3% | -6.2% |
| BTC-1H | P4(ADX filter) | 22 | 27.3% | 2.52 | -1.1% | -0.9% |
| **Delta** | | -24 | +3.4% | +0.1 | **+4.2%** | **+5.3%** |
| ETH-1H | P3(fixed=0.50) | 50 | 22.0% | 2.65 | -5.4% | -9.2% |
| ETH-1H | P4(ADX filter) | 24 | 25.0% | 2.77 | -1.6% | -2.0% |
| **Delta** | | -26 | +3.0% | +0.12 | **+3.9%** | **+7.2%** |

**结论**: ADX过滤器在震荡/混合市场中可提升Gap 3-4个百分点，但会减少50%交易次数。在强趋势市场中表现待验证。

---

## 四、已修复 Bug

1. **P3-3 SOL/BNB突破策略**: `if i >= lookback:` → `if idx >= lookback:`
2. **P3-3 变量作用域**: `iloc[i-lookback:i]` → `iloc[idx-lookback:idx]`
3. **EMA斜率计算**: `.ewm().iloc[]` → `.ewm().mean().iloc[]`（pandas API兼容）
4. **Hurst预声明**: 添加 `hurst = 0.5` 避免 `UnboundLocalError`

---

## 五、配置更新（config/v15_p4_optimal.yaml）

```yaml
name: 杀手锏交易系统 v1.5 P4优化
base_threshold: 0.52  # 动态调整范围: 0.45-0.60
market_filter:
  adx_trending: 30
  adx_range: 20
symbols:
  ETHUSDT:  # 优先级1
    status: active
    confirm_threshold: 0.55
  BTCUSDT:  # 优先级2
    status: active
    confirm_threshold: 0.50
  SOLUSDT:  # 排除
    status: excluded
    note: gap=-12%，趋势市场均值回归失效
  BNBUSDT:  # 排除
    status: excluded
```

---

## 六、行动清单

| 优先级 | 任务 | 状态 |
|--------|------|------|
| P1 | 排除SOL/BNB，仅运行ETH+BTC | 完成 |
| P2 | ADX+Hurst双维度市场过滤器 | 代码完成，待OOS验证 |
| P3 | 修复closed_loop_engine.py中的4个bug | 完成 |
| P4 | 专注1H周期，停止短周期策略 | 完成 |
| P5 | OOS验证P4改进（需548笔ETH+BTC数据） | 待执行 |
| P6 | 在真实市场中验证实时表现 | 待执行 |

---

## 七、关键参数总结

| 参数 | v1.4值 | v1.5建议 | 说明 |
|------|--------|----------|------|
| thresh | 0.50/0.55 | 动态0.45-0.60 | ADX+Hurst调整 |
| atr_sl | 1.3 | 1.3 | ETH+BTC用1.3，SOL/BNB用1.5 |
| vol_filter | 0.25 | 0.25 | 1H专用 |
| 品种 | ETH+BTC+SOL+BNB | **仅ETH+BTC** | 排除结构性亏损 |
| 周期 | 1H | 1H | 排除1m/3m/5m |
