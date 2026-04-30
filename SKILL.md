---
name: trading-simulator
description: 工业级杀手锏多策略融合交易系统(v1.0.5)；当用户需要闭环集成回测、风险平价资金分配(ERC/HERC/IVP)、Hurst指数过滤、多维评分信号、动态保本止损、期货品种支持、贝叶斯参数优化、HRP组合优化、元学习快速适应、Hawkes市场冲击建模、因果因子筛选、市场冲击模型统一接口、过拟合检测(CSCV/PBO/DSR)、DAG流水线并行编排时使用
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

# 杀手锏交易系统 v1.0.5-P1

## 任务目标
- 本 Skill 用于: 加密货币+期货多策略融合交易系统,集成闭环引擎、Hurst过滤、多维评分、7品种扫描、DAG流水线并行编排、前沿量化理论
- 能力包含: 闭环回测+Hurst过滤+多维评分+保本止损+期货支持+贝叶斯优化+HRP+MAML+Hawkes+因果因子+市场状态机+7品种扫描+凯利仓位+样本外验证+DAG编排引擎+过拟合检测+48类型事件总线
- 触发条件: "闭环回测"、"Hurst过滤"、"多维评分"、"保本止损"、"期货交易"、"参数优化"、"组合优化"、"元学习"、"市场冲击"、"因果因子"、"策略融合"、"市场状态识别"、"DAG并行"、"流水线编排"

## 前置准备
- 依赖说明: Python 3.8+, numpy, pandas, scipy, statsmodels, scikit-learn, bayesian-optimization, ta, requests
- 配置文件: `config.json` (v1.0.5唯一权威配置)

## 操作步骤

### 标准流程(v1.0.4)

1. **闭环集成回测** — 全Pipeline: 数据→信号→确认→仓位→风控→反馈
   - 脚本调用示例:`python scripts/closed_loop_engine.py --bars 3000 --mode hybrid`
   - 输出:完整回测报告+策略权重演化+反馈调整记录+漂移检测结果
   - 内含:Hurst过滤+多维评分+动态保本止损+HRP资金分配+凯利仓位+熔断器+漂移检测

2. **多维评分信号** — 6条件加权+趋势方向加权+Hurst过滤(v1.0.5 P0修复)
   - 脚本调用示例:`python scripts/signal_scorer_multidim.py --threshold 0.55 --bars 500`
   - 评分维度:趋势强度(0.35)/MACD(0.30)/均线突破(0.25)/RSI(0.20)/成交量(0.15)/动量(0.15)

3. **期货数据获取** — 东方财富API+币安API双数据源(3次重试)
   - 脚本调用示例:`python scripts/futures_data_fetcher.py --symbol GOLD --period 1d --count 500`
   - 支持品种:BTC/ETH/BNB/SOL + 黄金/白银/原油/铜/铁矿石

4. **贝叶斯参数优化** — GP+EI采集函数,8维参数空间自动搜索
   - 脚本调用示例:`python scripts/optimizer_bayes.py --n-iter 30 --init-points 5`
   - 输出:最优参数+样本外验证+config.json自动更新

5. **HRP组合优化** — 层次聚类+递归二分,无需预期收益的鲁棒资金分配
   - 脚本调用示例:`python scripts/portfolio_hrp.py --days 180 --update-config`

6. **风险平价资金分配** — ERC(等风险贡献)/约束HERC(层次等风险)/IVP(反波动率)三方法+自动regime切换
   - 脚本调用示例:`python scripts/risk_parity_allocator.py --method auto --lookback 60`
   - 策略级:ERC分配MR/TF/FR权重; 资产级:约束HERC分配7品种权重; 极端行情:IVP兜底

7. **元学习快速适应** — MAML内外循环,5种市场环境元训练
   - 脚本调用示例:`python scripts/meta_learner_maml.py --n-iterations 20 --n-tasks 10`

8. **市场状态识别** — 3态识别(RANGING/TRENDING/EXTREME)+Hurst增强+策略权重映射
   - 脚本调用示例:`python scripts/market_state_machine.py --data <csv_path>`

9. **Hawkes市场冲击** — 自激点过程建模+双过程(买/卖)+信号确认(分级)
   - 脚本调用示例:`python scripts/hawkes_process.py --bars 1000`

10. **因果因子评分** — DAG因果图+Granger因果检验+USE/DROP推荐
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

### 示例3: 风险平价资金分配
- 场景/输入:7品种(BTC/ETH/SOL/BNB/GOLD/SILVER/CRUDE)动态资金分配
- 预期产出:ERC模式下各资产风险贡献均等(各14.3%); 约束HERC模式下crypto占50%+,commodity占50%-
- 关键要点:ERC适合策略级权重分配; 约束HERC适合资产级分配(需设crypto/commodity边界); 极端行情自动切IVP

### 示例4: HRP组合优化
- 场景/输入:4品种(BTC/ETH/SOL/BNB)资金分配
- 预期产出:BTC 29%/BNB 31%/ETH 23.4%/SOL 16.6%,风险平衡改善90.86%
- 关键要点:HRP无需预期收益,在估计误差大时优于MVO(注意:无约束HRP会过度分配低波动资产,建议用约束HERC替代)

## 资源索引

### v5.3核心引擎
- [scripts/closed_loop_engine.py](scripts/closed_loop_engine.py) — 闭环集成引擎:DataPipeline+SignalPipeline+StrategyOrchestrator+PortfolioAllocator+RiskManager+FeedbackLoop

### v5.2信号+数据
- [scripts/signal_scorer_multidim.py](scripts/signal_scorer_multidim.py) — 多维评分信号:6条件加权+趋势方向加权+Hurst过滤+动态保本止损
- [scripts/futures_data_fetcher.py](scripts/futures_data_fetcher.py) — 期货数据获取:东方财富API+币安API双数据源,7品种,3次重试

### v5.1前沿理论
- [scripts/optimizer_bayes.py](scripts/optimizer_bayes.py) — 贝叶斯优化:GP+EI,8维参数空间,样本外验证集成
- [scripts/portfolio_hrp.py](scripts/portfolio_hrp.py) — HRP分层风险平价:层次聚类+递归二分,7品种分配
- [scripts/risk_parity_allocator.py](scripts/risk_parity_allocator.py) — 风险平价资金分配:ERC/约束HERC/IVP三方法+自动regime切换+约束边界
- [scripts/experiment_risk_parity.py](scripts/experiment_risk_parity.py) — 风险平价对比实验:1/N/IVP/ERC/HRP/HERC五方法三场景系统化比较
- [scripts/meta_learner_maml.py](scripts/meta_learner_maml.py) — MAML元学习:内外循环,5种市场环境,少样本快速适应
- [scripts/hawkes_process.py](scripts/hawkes_process.py) — Hawkes过程:自激点过程建模,分级信号确认(1.1x/1.5x)
- [scripts/causal_factor_scorer.py](scripts/causal_factor_scorer.py) — 因果因子评分:DAG+Granger+合成控制,USE/DROP推荐

### v5.4工程闭环模块(Stage 1-5交付)
- [scripts/impact_model.py](scripts/impact_model.py) — 市场冲击模型统一接口:AlmgrenChriss/Obizhaeva/SquareRoot/Hawkes四种模型,用于回测滑点估算和执行成本预测
- [scripts/overfitting_detector.py](scripts/overfitting_detector.py) — 过拟合检测:CSCV组合对称交叉验证/PBO概率回测过拟合/DeflatedSharpeRatio多重测试校正,集成到策略评估和BO目标函数
- [scripts/dag_engine.py](scripts/dag_engine.py) — DAG执行引擎:支持交易流水线节点并行执行与条件守卫,状态守卫(RUNNING/DEGRADED/CIRCUIT_BROKEN),拓扑排序自动解析,critical熔断机制,create_trading_dag工厂函数
- [config/search_space.yaml](config/search_space.yaml) — BO参数搜索空间配置:25个可优化参数,4个预设场景(aggressive/balanced/conservative/high_frequency),硬/软约束定义
- [tests/test_portfolio_hrp.py](tests/test_portfolio_hrp.py) — HRP单元测试:正常输入/边界/异常/权重归一化/单品种场景,14用例
- [tests/test_impact_model.py](tests/test_impact_model.py) — 冲击模型单元测试:4种模型/滑点计算/边界/异常,16用例
- [tests/test_optimizer_bayes.py](tests/test_optimizer_bayes.py) — BO单元测试:优化流程/GridSearch回退/边界/参数验证,11用例
- [tests/test_overfitting_detector.py](tests/test_overfitting_detector.py) — 过拟合检测单元测试:CSCV/PBO/DSR三种方法/边界/集成,29用例
- [tests/test_meta_learner_maml.py](tests/test_meta_learner_maml.py) — MAML元学习单元测试:内外循环/收敛/持久化,16用例

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
- [references/ultimate_round_7_report.md](references/ultimate_round_7_report.md) — 终极整合Round 7报告(事件Payload标准化)
- [references/FINAL_OPTIMIZATION_AND_INTEGRATION_REPORT.md](references/FINAL_OPTIMIZATION_AND_INTEGRATION_REPORT.md) — 综合优化整合最终报告
- [references/COLLABORATION_FINAL_REPORT.md](references/COLLABORATION_FINAL_REPORT.md) — 深度协调整合最终报告(8轮完成)
- [references/authority_map.md](references/authority_map.md) — 系统权威源映射表(15个能力域唯一权威模块)

### 深度学习笔记
- [references/deep_learning/progress.md](references/deep_learning/progress.md) — 深度学习进度追踪(已完成主题+下一步计划)
- [references/deep_learning/risk_parity_family/notes.md](references/deep_learning/risk_parity_family/notes.md) — 风险平价家族完整理论笔记(1/N→IVP→ERC→HRP→HERC)
- [references/deep_learning/risk_parity_family/experiment_results.md](references/deep_learning/risk_parity_family/experiment_results.md) — 风险平价对比实验结果(5方法×3场景)
- [references/deep_learning/risk_parity_family/integration_design.md](references/deep_learning/risk_parity_family/integration_design.md) — 风险平价系统整合设计(ERC策略级+HERC资产级+IVP兜底)
- [references/deep_learning/risk_parity_family/reflection.md](references/deep_learning/risk_parity_family/reflection.md) — 风险平价学习反思(核心洞见+脆弱性+下一步)

### 配置
- [config.json](config.json) — v1.0.4唯一权威配置(含闭环引擎/Hurst/多维评分/期货/BO/HRP/MAML/Hawkes/Causal参数)

## 注意事项
- 闭环引擎是v1.0.4的核心,串联所有模块形成Pipeline,建议优先使用
- Hurst指数是市场状态识别的关键:Hurst<0.5=均值回归市场,Hurst>0.5=趋势市场
- 多维评分信号的趋势方向加权:顺势x1.5,逆势x0.3
- 动态保本止损:价格到达BB均线时移止损到成本
- Hawkes信号确认采用分级:1.1x(弱确认,confidence<0.5)/1.5x(强确认,confidence>0.5)
- 期货数据获取支持3次重试+指数退避,东方财富API可能受网络限制
- 贝叶斯优化需严格样本外验证(60/20/20),避免过拟合
- 废弃1分钟周期策略(胜率17-39%全面失效)
- 月收益预期:保守3-8%,激进10-20%
- 本系统默认为纯模拟模式,不连接真实交易所,无资金风险
