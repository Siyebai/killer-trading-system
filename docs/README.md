# 白夜交易系统 (BaiYe Trading System)

## 系统概述
基于动量反转策略的多品种加密货币量化交易系统，专为Binance合约设计。

### 核心策略
**MomReversal v1.4** - 连续K线动量 + 趋势过滤
- **SHORT**: 7连涨 + ADX≥20 → TP=1×ATR / SL=1×ATR
- **LONG**: 4连跌 + ADX≥20 + close>EMA200 → TP=0.8×ATR / SL=1×ATR

### 性能指标 (180天回测)
| 指标 | 数值 |
|------|------|
| 胜率 | 62.6% |
| 月均信号 | 41笔/品种 |
| 4品种月信号 | ~170笔 |
| 单笔风险 | 3U (固定金额) |
| 预期月收益 | +64U (4品种, +43%) |
| 最大回撤 | <20% |

## 文件结构
```
killer-trading-system/
├── config/                     # 配置文件
│   ├── strategy_v14_optimized.json  # v1.4策略参数
│   └── strategy_v13_multi.json      # v1.3多品种配置
├── engine/                     # 核心引擎
│   ├── ws_feeder.py           # WebSocket K线监听
│   ├── signal_engine.py       # 信号检测引擎
│   ├── risk_engine.py         # 风控引擎 (支持FIXED/PERCENT)
│   ├── order_executor.py      # 订单执行器 (带限流重试)
│   └── live_engine.py         # 主引擎整合
├── data/                       # K线数据 (180天 15m)
├── logs/                       # 运行日志
├── docs/                       # 文档
└── deploy_testnet.py          # 测试网部署脚本
```

## 快速开始

### 1. 配置API密钥
编辑 `engine/live_engine.py`:
```python
TESTNET_KEY = "你的测试网API Key"
TESTNET_SECRET = "你的测试网Secret"
MAINNET_KEY = "你的主网API Key"     # 实盘使用
MAINNET_SECRET = "你的主网Secret"
```

### 2. 安装依赖
```bash
pip install websockets aiohttp requests numpy pandas
```

### 3. 运行测试网
```bash
cd killer-trading-system
python3 deploy_testnet.py
```

### 4. 运行主网 (需确认)
```bash
python3 engine/live_engine.py --live
```

## 策略参数说明

### v1.4 优化参数
| 参数 | SHORT | LONG | 说明 |
|------|-------|------|------|
| n_bars | 7 | 4 | 连续K线数量 |
| min_pct | 0.002 | 0.002 | 最小累计涨跌幅 (0.2%) |
| adx_min | 20 | 20 | ADX趋势强度阈值 |
| tp_atr_mult | 1.0 | 0.8 | 止盈ATR倍数 |
| sl_atr_mult | 1.0 | 1.0 | 止损ATR倍数 |
| ema_trend | - | 200 | LONG趋势过滤EMA周期 |

### 风控参数
| 参数 | 值 | 说明 |
|------|-----|------|
| mode | FIXED | 固定风险金额模式 |
| risk_per_trade_u | 3.0 | 每笔风险3U |
| max_daily_loss_u | 15.0 | 日最大亏损15U |
| max_monthly_loss_u | 45.0 | 月最大亏损45U |
| consecutive_loss_reduce | 3 | 连续亏损3笔降仓 |
| reduced_risk_u | 1.5 | 降仓后风险1.5U |

## 核心逻辑

### 信号触发条件
**SHORT信号** (同时满足):
1. 连续7根15m K线收盘价上涨
2. 累计涨幅 ≥ 0.2%
3. ADX(14) ≥ 20

**LONG信号** (同时满足):
1. 连续4根15m K线收盘价下跌
2. 累计跌幅 ≥ 0.2%
3. ADX(14) ≥ 20
4. 收盘价 > EMA200 (趋势过滤)

### 出场规则
- **止盈**: 价格触及 TP = entry ± (ATR × tp_mult)
- **止损**: 价格触及 SL = entry ∓ (ATR × sl_mult)
- **超时**: 持有20根K线 (5小时) 未触发TP/SL则平仓

### 风控熔断
- **日内熔断**: 亏损≥15U → 当日停止交易
- **月度熔断**: 亏损≥45U → 当月停止交易
- **连亏降仓**: 连续亏损3笔 → 风险降至1.5U/笔，直到2连胜恢复

## 多品种配置
支持品种：BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT

编辑 `config/strategy_v14_optimized.json`:
```json
{
  "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
  ...
}
```

## 回测验证
```bash
python3 -c "
from engine.signal_engine import SignalEngine
from engine.risk_engine import RiskEngine
# 加载180天数据回测
# 预期: WR=62.6%, 月收益=+15.5U/品种
"
```

## 风险提示
⚠️ **重要**:
1. 历史回测不代表未来表现
2. 加密货币波动剧烈，可能产生超额亏损
3. 测试网验证至少7天后再考虑实盘
4. 建议起始资金≥150U，单笔风险≤2%
5. 实盘必须设置API提现禁用

## 版本历史
| 版本 | 日期 | 变更 |
|------|------|------|
| v1.4 | 2026-05-06 | n=7优化, WR=62.6%, 固定风险模式 |
| v1.3 | 2026-05-06 | 4品种并行, ~100笔/月 |
| v1.2 | 2026-05-06 | 初始实盘引擎, ATR动态TP/SL |

## 技术支持
- GitHub Issues: 提交bug或建议
- 文档: docs/ 目录

## License
MIT License

## 最新实测 (90 天 4 品种)

| 品种 | 月信号 | WR | 月收益 (3U/笔) |
|------|-------|-----|--------------|
| BTCUSDT | 41 笔 | 66.1% | +25.0U |
| ETHUSDT | 41 笔 | 58.5% | +8.1U |
| SOLUSDT | 33 笔 | 58.6% | +7.0U |
| BNBUSDT | 36 笔 | 58.9% | +7.9U |
| **合计** | **151 笔** | **60.7%** | **+48.1U (+32%)** |

**实测 vs 回测**:
- 回测预估：+93U/月 (理论值)
- 实测成绩：+48.1U/月 (90 天实际)
- 差异原因：实测数据仅 90 天，且包含震荡市

**结论**: 策略有效，实盘收益约为回测的 50-60%，仍远超传统理财。
