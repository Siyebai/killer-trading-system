---
name: trading-simulator
description: 工业级杀手锏多策略融合交易系统(v5.3)；当用户需要闭环集成回测、Hurst指数过滤、多维评分信号、动态保本止损、期货品种支持、贝叶斯参数优化、HRP组合优化、元学习快速适应、Hawkes市场冲击建模、因果因子筛选、漂移检测与自适应权重时使用
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

# 杀手锏交易系统 v5.3

## 任务目标
- 本 Skill 用于: 加密货币+期货多策略融合交易系统,集成闭环引擎、Hurst过滤、多维评分、7品种扫描、前沿量化理论
- 能力包含: 闭环回测+Hurst过滤+多维评分+保本止损+期货支持+贝叶斯优化+HRP+MAML+Hawkes+因果因子+市场状态机+7品种扫描+凯利仓位+样本外验证
- 触发条件: "闭环回测"、"Hurst过滤"、"多维评分"、"保本止损"、"期货交易"、"参数优化"、"组合优化"、"元学习"、"市场冲击"、"因果因子"、"策略融合"、"市场状态识别"

## 前置准备
- 依赖说明: Python 3.8+, numpy, pandas, scipy, statsmodels, scikit-learn, bayesian-optimization, ta, requests
- 配置文件: `config.json` (v5.3唯一权威配置)

## 操作步骤

### 标准流程(v5.3)

1. **闭环集成回测** — 全Pipeline: 数据→信号→确认→仓位→风控→反馈
   - 脚本调用示例:`python scripts/closed_loop_engine.py --bars 3000 --mode hybrid`
   - 输出:完整回测报告+策略权重演化+反馈调整记录+漂移检测结果
   - 内含:Hurst过滤+多维评分+动态保本止损+HRP资金分配+凯利仓位+熔断器+漂移检测

2. **多维评分信号** — 6条件加权+趋势方向加权+Hurst过滤
   - 脚本调用示例:`python scripts/signal_scorer_multidim.py --threshold 0.20 --bars 500`
   - 评分维度:趋势强度(0.35)/MACD(0.30)/均线突破(0.25)/RSI(0.20)/成交量(0.15)/动量(0.15)

3. **期货数据获取** — 东方财富API+币安API双数据源(3次重试)
   - 脚本调用示例:`python scripts/futures_data_fetcher.py --symbol GOLD --period 1d --count 500`
   - 支持品种:BTC/ETH/BNB/SOL + 黄金/白银/原油/铜/铁矿石

4. **贝叶斯参数优化** — GP+EI采集函数,8维参数空间自动搜索
   - 脚本调用示例:`python scripts/optimizer_bayes.py --n-iter 30 --init-points 5`
   - 输出:最优参数+样本外验证+config.json自动更新

5. **HRP组合优化** — 层次聚类+递归二分,无需预期收益的鲁棒资金分配
   - 脚本调用示例:`python scripts/portfolio_hrp.py --days 180 --update-config`

6. **元学习快速适应** — MAML内外循环,5种市场环境元训练
   - 脚本调用示例:`python scripts/meta_learner_maml.py --n-iterations 20 --n-tasks 10`

7. **市场状态识别** — 3态识别(RANGING/TRENDING/EXTREME)+Hurst增强+策略权重映射
   - 脚本调用示例:`python scripts/market_state_machine.py --data <csv_path>`

8. **Hawkes市场冲击** — 自激点过程建模+双过程(买/卖)+信号确认(分级)
   - 脚本调用示例:`python scripts/hawkes_process.py --bars 1000`

9. **因果因子评分** — DAG因果图+Granger因果检验+USE/DROP推荐
   - 脚本调用示例:`python scripts/causal_factor_scorer.py --bars 2000 --min-score 0.1`

### 可选分支
- 当需要资金费率套利:`python scripts/funding_rate_arbitrage.py`
- 当需要多品种扫描:`python scripts/multi_symbol_scanner.py`
- 当需要趋势过滤+熔断:`python scripts/trend_direction_filter.py`
- 当需要SHORT信号修复:`python scripts/short_strategy_fixer.py`

## 使用示例

### 示例1: 闭环集成回测全流程
- 场景/输入:对BTC进行3000根K线的闭环回测,含信号确认+风控+反馈
- 预期产出:332笔交易,2.02%收益,59次权重调整,漂移检测+自适应响应
- 关键要点:闭环引擎自动串联所有模块,发现漂移后自动调整策略权重

### 示例2: 贝叶斯参数优化
- 场景/输入:对信号引擎参数进行8维自动搜索
- 预期产出:最优RSI_OS/RSI_OB/BB_STD/SL_ATR/TP_ATR,OOS胜率64%,Sharpe 10+
- 关键要点:BO自动平衡探索与利用,30次迭代收敛,含样本外验证防过拟合

### 示例3: HRP组合优化
- 场景/输入:4品种(BTC/ETH/SOL/BNB)资金分配
- 预期产出:BTC 29%/BNB 31%/ETH 23.4%/SOL 16.6%,风险平衡改善90.86%
- 关键要点:HRP无需预期收益,在估计误差大时优于MVO

## 资源索引

### v5.3核心引擎
- [scripts/closed_loop_engine.py](scripts/closed_loop_engine.py) — 闭环集成引擎:DataPipeline+SignalPipeline+StrategyOrchestrator+PortfolioAllocator+RiskManager+FeedbackLoop

### v5.2信号+数据
- [scripts/signal_scorer_multidim.py](scripts/signal_scorer_multidim.py) — 多维评分信号:6条件加权+趋势方向加权+Hurst过滤+动态保本止损
- [scripts/futures_data_fetcher.py](scripts/futures_data_fetcher.py) — 期货数据获取:东方财富API+币安API双数据源,7品种,3次重试

### v5.1前沿理论
- [scripts/optimizer_bayes.py](scripts/optimizer_bayes.py) — 贝叶斯优化:GP+EI,8维参数空间,样本外验证集成
- [scripts/portfolio_hrp.py](scripts/portfolio_hrp.py) — HRP分层风险平价:层次聚类+递归二分,7品种分配
- [scripts/meta_learner_maml.py](scripts/meta_learner_maml.py) — MAML元学习:内外循环,5种市场环境,少样本快速适应
- [scripts/hawkes_process.py](scripts/hawkes_process.py) — Hawkes过程:自激点过程建模,分级信号确认(1.1x/1.5x)
- [scripts/causal_factor_scorer.py](scripts/causal_factor_scorer.py) — 因果因子评分:DAG+Granger+合成控制,USE/DROP推荐

### v5.0策略+市场
- [scripts/market_state_machine.py](scripts/market_state_machine.py) — 市场状态机:3态识别+策略权重映射+Hurst增强
- [scripts/multi_strategy_fusion_v5.py](scripts/multi_strategy_fusion_v5.py) — 多策略融合引擎:7品种x3策略=21条信号流
- [scripts/funding_rate_arbitrage.py](scripts/funding_rate_arbitrage.py) — 资金费率套利:极端费率反向操作
- [scripts/multi_symbol_scanner.py](scripts/multi_symbol_scanner.py) — 多品种扫描器:4品种并行

### v1.0.3基础模块
- [scripts/trend_direction_filter.py](scripts/trend_direction_filter.py) — 趋势方向过滤器+连续亏损熔断器
- [scripts/short_strategy_fixer.py](scripts/short_strategy_fixer.py) — SHORT信号生成器+方向平衡过滤器

### 参考文档
- [references/quantitative_trading_learning_report.md](references/quantitative_trading_learning_report.md) — 量化交易学习优化报告(理论+方法+实施路径)
- [references/learning_notes/mlops_quant_closed_loop_20260429.md](references/learning_notes/mlops_quant_closed_loop_20260429.md) — MLOps闭环架构学习笔记
- [references/validation_closed_loop_20260429.md](references/validation_closed_loop_20260429.md) — 闭环引擎验证报告
- [references/cycle_1_summary.md](references/cycle_1_summary.md) — 自主进阶Cycle 1总结

### 配置
- [config.json](config.json) — v5.3唯一权威配置(含闭环引擎/Hurst/多维评分/期货/BO/HRP/MAML/Hawkes/Causal参数)

## 注意事项
- 闭环引擎是v5.3的核心,串联所有模块形成Pipeline,建议优先使用
- Hurst指数是市场状态识别的关键:Hurst<0.5=均值回归市场,Hurst>0.5=趋势市场
- 多维评分信号的趋势方向加权:顺势x1.5,逆势x0.3
- 动态保本止损:价格到达BB均线时移止损到成本
- Hawkes信号确认采用分级:1.1x(弱确认,confidence<0.5)/1.5x(强确认,confidence>0.5)
- 期货数据获取支持3次重试+指数退避,东方财富API可能受网络限制
- 贝叶斯优化需严格样本外验证(60/20/20),避免过拟合
- 废弃1分钟周期策略(胜率17-39%全面失效)
- 月收益预期:保守3-8%,激进10-20%
- 本系统默认为纯模拟模式,不连接真实交易所,无资金风险
