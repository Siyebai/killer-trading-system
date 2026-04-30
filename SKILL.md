---
name: trading-simulator
description: 杀手锏多策略交易系统v1.6(P5优化)；当用户需要300笔真实闭环回测、ADX+Hurst双维度过滤、做多方向优化、ETH均值回归、参数热力图分析、ATR动态止损优化时使用
dependency:
  python:
    - numpy>=1.24.0
    - pandas>=2.0.0
    - scipy>=1.10.0
    - statsmodels>=0.14.0
    - scikit-learn>=1.2.0
    - bayesian-optimization>=1.4.0
    - ta>=0.10.0
    - requests>=2.28.0
  system:
    - python3
---

# 杀手锏交易系统 v1.6 (P5优化版)

## 任务目标
- 本 Skill 用于: 加密货币均值回归策略闭环回测,基于ADX+Hurst双维度市场过滤器优化做多方向
- 能力包含: 300笔真实闭环回测 | ADX+Hurst动态阈值 | ETH专项优化 | ATR动态止损 | 短周期验证(1m/3m/5m不适用) | Gap胜率分析
- 触发条件: "闭环回测"、"P5优化"、"ADX过滤"、"Hurst过滤"、"300笔测试"、"均值回归"、"做多优化"

## 前置准备
- 依赖说明: Python 3.8+, numpy, pandas, scipy, statsmodels, scikit-learn, bayesian-optimization, ta, requests
- 数据文件: `data/BTCUSDT_1h_with_flow.json` (8760根1H K线), `data/ETHUSDT_1h.json` (8760根1H K线)
- P5测试脚本: `scripts/p5_closed_loop_test.py`
- P5配置文件: `config/v16_p5_optimal.yaml`

## 操作步骤

### P5核心流程

1. **数据分析与市场状态诊断**
   - 运行P5分析脚本:`python scripts/p5_closed_loop_test.py`
   - 分析ADX/Hurst分布,确认均值回归市场占比
   - BTC: Hurst<0.42仅占11.5%, ADX<20仅占12.7%,均值回归机会稀缺
   - ETH: Hurst<0.42占15.3%, ADX<20占14.1%,略优于BTC

2. **300笔真实闭环回测**
   - 加载BTC+ETH各8760根1H数据
   - 对齐时间范围后执行闭环交易模拟
   - 核心指标:Gap胜率 = WR - 盈亏平衡胜率(>0为正期望)

3. **参数优化(基于验证结论)**
   - 关键发现:ETH做多方向是唯一正期望策略,BTC做空全面亏损
   - 最优配置:atr_sl=2.0, atr_tp=2.0, max_hold=20, vol_filter=0.25, adx_max=80, thresh_base=0.52
   - 动态阈值:ADX>25时+0.03; Hurst>0.55时+0.02

4. **结果验证与记录**
   - 对比P4(v15)和P5(v16)配置差异
   - 确认ETH做多方向为最优策略分支
   - 更新`config/v16_p5_optimal.yaml`

### 标准流程(v1.0.4)

1. **闭环集成回测** — 全Pipeline: 数据→信号→确认→仓位→风控→反馈
   - 脚本调用示例:`python scripts/closed_loop_engine.py --bars 3000 --mode hybrid`

2. **贝叶斯参数优化** — GP+EI采集函数,8维参数空间自动搜索
   - 脚本调用示例:`python scripts/optimizer_bayes.py --n-iter 30 --init-points 5`

3. **HRP组合优化** — 层次聚类+递归二分,无需预期收益的鲁棒资金分配
   - 脚本调用示例:`python scripts/portfolio_hrp.py --days 180 --update-config`

4. **风险平价资金分配** — ERC/约束HERC/IVP三方法+自动regime切换
   - 脚本调用示例:`python scripts/risk_parity_allocator.py --method auto --lookback 60`

## 使用示例

### 示例1: P5 300笔真实闭环测试
- 场景/输入:BTC+ETH各8760根1H K线,ETH做多方向
- 预期产出:ETH Gap=+2.19%(正期望), BTC Gap=-3.5%(负期望)
- 关键要点:ADX>80时禁止开仓; Hurst>0.42时阈值提升; 宽止损(ATR 2.0倍)匹配均值回归特性

### 示例2: 市场状态诊断
- 场景/输入:分析Hurst<0.42和ADX<20的交集比例
- 预期产出:BTC 5.6%时间处于"双低"状态; ETH 6.8%
- 关键要点:均值回归机会稀缺,需宽止损+低频交易

### 示例3: P4 vs P5参数对比
- 场景/输入:P4配置atr_sl=1.3 vs P5配置atr_sl=2.0
- 预期产出:P4 Gap=-2.5%; P5 Gap=+2.19%(ETH做多)
- 关键要点:宽止损显著降低止损频率,提高TP/SL比

## 资源索引

### P5核心文件
- [scripts/p5_closed_loop_test.py](scripts/p5_closed_loop_test.py) — P5闭环测试框架:compute_indicators(含ADX/Hurst计算)+P5Strategy+300笔回测引擎
- [config/v16_p5_optimal.yaml](config/v16_p5_optimal.yaml) — P5最优配置:atr_sl=2.0,atr_tp=2.0,max_hold=20,vol_filter=0.25,adx_max=80,LONG_ONLY
- [references/P5_OPTIMIZATION_REPORT.md](references/P5_OPTIMIZATION_REPORT.md) — P5优化完整报告:市场诊断→参数搜索→分组分析→策略对比→结论

### v1.0.4核心引擎
- [scripts/closed_loop_engine.py](scripts/closed_loop_engine.py) — 闭环集成引擎:DataPipeline+SignalPipeline+StrategyOrchestrator+PortfolioAllocator+RiskManager+FeedbackLoop
- [scripts/signal_scorer_multidim.py](scripts/signal_scorer_multidim.py) — 多维评分信号
- [scripts/optimizer_bayes.py](scripts/optimizer_bayes.py) — 贝叶斯优化

### 参考文档
- [references/P4_OPTIMIZATION_REPORT.md](references/P4_OPTIMIZATION_REPORT.md) — P4优化报告
- [references/FINAL_OPTIMIZATION_AND_INTEGRATION_REPORT.md](references/FINAL_OPTIMIZATION_AND_INTEGRATION_REPORT.md) — 综合优化整合最终报告

## 注意事项
- 1m/3m/5m短周期策略全面失效:噪音过大,Gap<-30%
- 4H数据可改善Hurst<0.42比例至27.6%,但信号频率降低
- BTC做空策略在2025-2026市场严重亏损,已禁用
- SOL/BNB结构性亏损(gap=-12%),已排除出核心策略
- 建议仅使用ETH做多方向,参数:atr_sl=2.0,atr_tp=2.0,adx_max=80,thresh_base=0.52
- 本系统默认为纯模拟模式,不连接真实交易所
