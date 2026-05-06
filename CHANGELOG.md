# CHANGELOG.md

## v2.0.0 — 2026-05-06

### 🔴 严重Bug修复
- **[引擎] Bug1修复**：pandas None列表被转为StringArray，nan的bool值为True，导致每根K线都开仓。  
  修复方案：信号改用 `np.int8` 数组（1=LONG, -1=SHORT, 0=无信号）
- **[引擎] Bug2修复**：`cum_chg`（累计涨跌幅）在行情方向切换时未重置，导致跨方向叠加。  
  修复方案：方向切换时 `cc = c`（从当前值重新开始计算）

### 🟡 精度改进
- **开仓时序修正**：开仓价格由信号根 `close` 改为下一根 `open`，更接近实盘时序
- **TP/SL同帧偏差修正**：同一根K线TP和SL都触发时，改用开盘价判断先后顺序，消除约0.9%的乐观偏差
- **ATR安全保护**：ATR=0时改用ffill填充，防止除0异常
- **ADX分母保护**：(pdi+ndi)=0时用 `replace(0, nan)`，防止inf值

### 🟢 功能优化
- **信号冷却期（cooldown=5）**：同向信号5根K线内不重复开仓，防止同一波行情多次触发
- **月均收益计算**：改为按实际数据天数计算，不再固定假设180天

### 📊 参数优化（网格搜索）
- 对6个合格品种（BTC/ETH/SOL/BNB/LINK/POL）完成1728组合×6品种网格搜索
- SHORT连涨阈值（sc）：普遍从6优化至5，信号更灵活
- LONG连跌阈值（lc）：主流最优为4
- 新增 `config/optimal_params.yaml` 和 `config/optimal_params.json` 存储最优参数

### 📁 新增文件
- `engine/backtest_engine_v2.py` — 修复后的核心回测引擎
- `config/optimal_params.yaml` — 带注释的最优参数配置
- `config/optimal_params.json` — 机器可读的最优参数配置
- `docs/BACKTEST_RESULTS.md` — 完整回测结果档案
- `backtest_expand.py` — 扩展品种回测脚本
- `grid_results.json` — 网格搜索原始结果
- `expand_backtest_results.json` — 扩展品种测试原始结果
- `README.md` — 更新为v2.0完整说明

---

## v1.0.6 — 2026-05-01 至 2026-05-05

### 已完成
- 多品种验证：BTC/ETH/SOL/BNB全部通过（WR≥55%）
- SHORT策略（S4_MomReversal）：6连涨+累涨≥0.2%+ADX≥20
- LONG策略（MomReversal）：4连跌+累跌≥0.2%+ADX≥20+close>EMA200
- 扩展测试：新增LINK和POL通过（共6个合格品种）
- 实盘引擎框架搭建（live_engine.py, signal_engine.py等）

---

## v2.1.0 — 2026-05-06

### 新增
- **连续SL冷却机制（Cooldown）**：同品种连续2次止损后冷却16根K线（≈4小时）
  - 解决单边趋势行情中反转信号频繁止损问题（今日BNB/SOL场景）
  - 6品种整体影响：WR +0.2%，月均持平（+0.0%），不损失收益
  - 对LINK特别有效：WR +0.9%，月均 +0.8%
  - 参数：consec_sl_threshold=2，cooldown_bars=16（可配置）

### 测试验证
- 趋势过滤方案1（1H EMA）：月均 -5.0%，信号削减50%，不采用
- 市场状态分类方案2：月均 -2.5%，不采用
- **连续SL冷却方案3：月均 +0.0%，WR +0.2%，采用 ✅**

### 今日行情分析（2026-05-06）
- 市场：BNB+2.73% SOL+2.42% LINK+2.30%（温和上涨）
- 策略今日模拟：-3.38U（-2.25%），主要因BNB 2次SHORT均SL
- 反转策略与单边涨跌负相关，大涨日收益承压属正常
