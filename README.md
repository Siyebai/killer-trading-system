# 白夜系统 (Baiye Trading System)
## 动量反转策略 — 多品种合约自动交易

---

## 📌 系统概述

| 项目 | 内容 |
|------|------|
| 版本 | v2.0.0 |
| 更新日期 | 2026-05-06 |
| 策略类型 | 动量反转（Momentum Reversal） |
| 时间框架 | 15分钟 |
| 合格品种 | 6个（BTC/LINK/POL/ETH/SOL/BNB） |
| 目标 | 月盈利≥50%（150U本金），胜率≥58% |

---

## 🎯 策略逻辑

### SHORT（做空）
```
条件：连涨≥sc根 + 累涨幅≥ccp + ADX≥adx_th
出场：SL = entry + 1×ATR
      TP = entry - tp_s×ATR
```

### LONG（做多）
```
条件：连跌≥lc根 + 累跌幅≥ccp + ADX≥adx_th + close > EMA200
出场：SL = entry - 1×ATR
      TP = entry + tp_l×ATR
```

---

## 📊 回测结果（180天，最优参数）

| 品种 | WR% | 月均% | 回撤% | PF | 优先级 |
|------|-----|-------|-------|-----|--------|
| BTCUSDT  | 60.3 | +23.1 | 19.2 | 1.39 | ⭐⭐⭐ |
| POLUSDT  | 58.6 | +11.6 | 21.4 | 1.22 | ⭐⭐⭐ |
| LINKUSDT | 67.1 | +11.5 | 14.7 | 1.43 | ⭐⭐⭐ |
| ETHUSDT  | 61.4 | +9.4  | 33.3 | 1.21 | ⭐⭐ |
| SOLUSDT  | 60.2 | +9.3  | 18.0 | 1.17 | ⭐⭐ |
| BNBUSDT  | 59.3 | +6.0  | 19.2 | 1.13 | ⭐⭐ |

---

## 🗂️ 目录结构

```
killer-trading-system/
├── engine/
│   ├── backtest_engine_v2.py   # 🔑 核心回测引擎 v2.0（已修复全部Bug）
│   ├── live_engine.py          # 实盘执行引擎
│   ├── signal_engine.py        # 信号生成
│   ├── risk_engine.py          # 风控模块
│   └── order_executor.py       # 下单执行
├── config/
│   ├── optimal_params.yaml     # 🔑 最优参数配置（含注释说明）
│   ├── optimal_params.json     # 🔑 最优参数配置（机器读取）
│   └── system_params.yaml      # 系统基础配置
├── docs/
│   ├── BACKTEST_RESULTS.md     # 🔑 完整回测结果档案
│   └── ENGINE_DOCS.md          # 引擎文档
├── backtest_expand.py          # 扩展品种回测脚本
├── grid_results.json           # 网格搜索原始结果
├── expand_backtest_results.json # 扩展品种测试原始结果
└── VERSION                     # 版本号
```

---

## ⚙️ 快速使用

### 1. 加载最优参数
```python
import json
with open('config/optimal_params.json') as f:
    cfg = json.load(f)

# 获取BTC参数
btc_params = cfg['symbols']['BTCUSDT']
print(btc_params)
# {'sc': 5, 'lc': 5, 'ccp': 0.003, 'adx_th': 20, 'tp_s': 1.0, 'tp_l': 1.0, ...}
```

### 2. 运行回测
```python
from engine.backtest_engine_v2 import compute_indicators, generate_signals, backtest_v2, calc_stats

df = fetch_klines('BTCUSDT', '15m', 180)
df = compute_indicators(df)

params = cfg['symbols']['BTCUSDT']
sigs = generate_signals(df,
    sc=params['sc'], lc=params['lc'],
    ccp=params['ccp'], adx_th=params['adx_th'])

trades = backtest_v2(df, sigs,
    tp_s=params['tp_s'], tp_l=params['tp_l'])

stats = calc_stats(trades)
print(stats)
```

---

## 🔴 风控规则（绝对不可自动修改）

1. **单日亏损≥6%** → 当日停止所有交易
2. **总回撤≥20%** → 系统暂停，等待主人手动确认恢复
3. **ETH仓位×50%**（回撤偏高品种）
4. **最多3个品种**同时持仓
5. **实盘操作必须主人确认**，系统不得自动执行

---

## 📈 已知Bug修复记录（v1→v2）

| 严重度 | Bug | 修复方案 |
|--------|-----|---------|
| 🔴严重 | pandas None→nan bool=True，全量开仓 | 改用np.int8信号数组 |
| 🔴严重 | cum_chg方向未重置 | 切换时从当前值重置 |
| 🟡偏差 | 开仓用信号根close | 改为下根open价 |
| 🟡偏差 | TP/SL同帧乐观偏差0.9% | 用开盘价判断先后 |
| 🟡保护 | ATR/ADX分母=0异常 | 加保护+ffill |
| 🟢优化 | 无cooldown重复开仓 | 加5根冷却期 |

---

## 🚦 开发进度

- ✅ Phase1: 策略研究
- ✅ Phase2: 多品种验证
- ✅ Phase3: 参数网格优化
- ✅ Phase4: 引擎v2.0完善
- ⏳ Phase5: 纸交易验证（≥100笔）
- 🔒 Phase6: 实盘部署（需主人确认）

---

*系统由李白v1.0维护 | 主人：思夜白*
