# 杀手锏 v1.2 进度总览
更新时间: 2026-05-06

## 🎯 最终目标
- 胜率 ≥ 58%
- 月盈利 ≥ 50%（150U本金）
- 品种：BTC/ETH/SOL/BNB

## ✅ 已验证策略参数

### SHORT策略 (S4_MomReversal)
- 信号: 连续6根上涨 + 累涨≥0.2% + ADX≥20
- 执行: TP=1ATR / SL=1ATR (1:1)
- 验证: WR=55.8%, EV=0.113, n=113(180d)
- 5折: [55% 55% 64% 55% 59%] min=55% ✅稳健

### LONG策略 (MomReversal LONG)
- 信号: 连续4根下跌 + 累跌≥0.2% + ADX≥20 + close>EMA200
- 执行: TP=0.8ATR / SL=1ATR
- 验证: WR=60.8%, EV=0.13, n=199(180d)
- 牛市环境WR更优

### 组合表现 (150U本金, 180d回测)
- 终值: 265.53U (+77%)
- 月均: 52笔/月
- 总胜率: 59.0%
- 最大回撤: 16.4%
- 盈利因子: 1.24
- 信号冲突率: 0% (天然互斥)

## 🔄 进行中
- [ ] Phase3: 多品种验证 (ETH/SOL/BNB)
- [ ] Phase4: 实盘引擎完善 (live_scanner.py)
- [ ] Phase5: 纸交易运行验证
- [ ] Phase6: 实盘部署

## 📁 关键文件
- scripts/phase1_combine_validate.py  — 冲突检测+组合回测
- scripts/phase3_multi_symbol.py      — 多品种验证
- scripts/live_scanner.py             — 实盘扫描引擎
- scripts/deep_validate_v1.py         — SHORT深度验证
- data/BTCUSDT_15m_180d.json          — 主回测数据

## 🚫 已排除方向
- 1H级别所有技术指标 (WR≈48-50%)
- ATR压缩突破 LONG (WR≈40%)
- EMA金叉大周期 (样本太少)
- RSI超卖 (WR≈50%)
