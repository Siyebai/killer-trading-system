---
name: trading-simulator
description: 工业级杀手锏多策略融合交易系统(v5.2)；当用户需要Hurst指数过滤、多维评分信号、动态保本止损、期货品种支持、贝叶斯参数优化、HRP组合优化、元学习快速适应、Hawkes市场冲击建模、因果因子筛选、7品种并行扫描、市场状态识别与策略切换时使用
dependency:
  python:
    - numpy==1.24.3
    - pandas==2.0.3
    - scipy>=1.10.0
    - statsmodels>=0.14.0
    - scikit-learn>=1.2.0
    - bayesian-optimization>=1.4.0
    - ta>=0.10.0
    - requests>=2.28.0
  system:
    - python3
---

# 杀手锏交易系统 v5.2

## 任务目标
- 本 Skill 用于: 加密货币+期货多策略融合交易系统,集成Hurst指数过滤、多维评分信号、动态保本止损、7品种扫描、前沿量化理论
- 能力包含: Hurst指数+多维评分+保本止损+期货支持+贝叶斯优化+HRP+MAML+Hawkes+因果因子+市场状态机+7品种扫描+凯利仓位管理+样本外验证
- 触发条件: "Hurst过滤"、"多维评分"、"保本止损"、"期货交易"、"参数优化"、"组合优化"、"元学习"、"市场冲击"、"因果因子"、"策略融合回测"、"市场状态识别"、"资金费率套利"

## 前置准备
- 依赖说明: Python 3.8+, numpy, pandas, scipy, statsmodels, scikit-learn, bayesian-optimization, ta, requests
- 配置文件: `config.json` (v5.2唯一权威配置)

## 操作步骤

### 标准流程(v5.2)

1. **多维评分信号** — 6条件加权+趋势方向加权+Hurst过滤
   - 脚本调用示例:`python scripts/signal_scorer_multidim.py --threshold 0.20 --bars 500`
   - 输出:信号方向+评分详情+Hurst值+保本止损触发统计
   - 评分维度:趋势强度(0.35)/MACD(0.30)/均线突破(0.25)/RSI(0.20)/成交量(0.15)/动量(0.15)
   - Hurst过滤:Hurst<0.5才允许均值回归信号

2. **期货数据获取** — 东方财富API+币安API双数据源
   - 脚本调用示例:`python scripts/futures_data_fetcher.py --symbol GOLD --period 1d --count 500`
   - 支持品种:BTC/ETH/BNB/SOL + 黄金/白银/原油/铜/铁矿石
   - 自动判断品种类型并调用对应API

3. **贝叶斯参数优化** — 自动搜索最优参数组合
   - 脚本调用示例:`python scripts/optimizer_bayes.py --n-iter 30 --init-points 5`
   - 输出:最优参数组合+样本外验证+config.json自动更新
   - 搜索空间:RSI/BB/ATR/ADX共8个维度
   - 方法:高斯过程+Expected Improvement采集函数

2. **HRP组合优化** — 无需预期收益的鲁棒资金分配
   - 脚本调用示例:`python scripts/portfolio_hrp.py --days 180 --update-config`
   - 输出:4品种最优权重+与等权对比+风险平衡改善度
   - 优势:在估计误差大时优于均值-方差优化

3. **元学习快速适应** — 非平稳市场的策略迁移
   - 脚本调用示例:`python scripts/meta_learner_maml.py --n-iterations 20 --n-tasks 10`
   - 输出:元参数(可用于新环境少样本适应)
   - 方法:MAML内外循环,5种市场环境元训练

4. **市场状态识别** — 3态识别+策略权重映射
   - 脚本调用示例:`python scripts/market_state_machine.py --data <csv_path>`
   - 输出:市场状态(RANGING/TRENDING/EXTREME)+策略权重

5. **多策略融合回测** — 根据市场状态动态分配权重
   - 脚本调用示例:`python scripts/multi_strategy_fusion_v5.py --capital 10000 --days 30`

6. **Hawkes市场冲击** — 订单流确认与冲击估计
   - 脚本调用示例:`python scripts/hawkes_process.py --bars 1000`
   - 输出:冲击函数I(V)=sigma*V^gamma+信号确认

7. **因果因子评分** — 筛选真实因果因子,剔除虚假因子
   - 脚本调用示例:`python scripts/causal_factor_scorer.py --bars 2000 --min-score 0.1`
   - 输出:因子排名+Granger因果检验+USE/DROP推荐

### 可选分支
- 当需要资金费率套利:`python scripts/funding_rate_arbitrage.py --data <csv_path>`
- 当需要差异化策略:`python scripts/differentiated_strategy_framework.py`
- 当需要样本外验证:`python scripts/out_of_sample_validator.py`

## 使用示例

### 示例1: 贝叶斯参数优化全流程
- 场景/输入:对信号引擎参数进行自动调优(8维搜索空间)
- 预期产出:最优RSI_OS=27/RSI_OB=60/BB_STD=1.6/SL=2.5ATR/TP=5.0ATR,OOS胜率64.29%
- 关键要点:BO自动平衡探索与利用,30次迭代即可收敛,含样本外验证防过拟合

### 示例2: HRP组合优化
- 场景/输入:4品种(BTC/ETH/SOL/BNB)资金分配
- 预期产出:BTC 29%/BNB 31%/ETH 23.4%/SOL 16.6%,风险平衡改善90.86%
- 关键要点:HRP无需预期收益,在估计误差大时优于MVO

### 示例3: 因果因子筛选
- 场景/输入:8个候选因子(技术/量/情绪/微观结构)
- 预期产出:5个推荐因子(ema_cross/bb_signal/rsi_signal/adx_trend/volume_surge),3个剔除
- 关键要点:Granger因果检验+DAG因果图双重验证,避免因子幻觉

## 资源索引

### v5.2核心新增(整合自strategy_v5_ultimate + crude_oil_optimization)
- [scripts/signal_scorer_multidim.py](scripts/signal_scorer_multidim.py) — 多维评分信号:6条件加权+趋势方向加权+Hurst过滤+动态保本止损
- [scripts/futures_data_fetcher.py](scripts/futures_data_fetcher.py) — 期货数据获取:东方财富API+币安API双数据源,7品种支持

### v5.1模块
- [scripts/optimizer_bayes.py](scripts/optimizer_bayes.py) — 贝叶斯优化:GP+EI采集函数,8维参数空间,样本外验证集成
- [scripts/portfolio_hrp.py](scripts/portfolio_hrp.py) — HRP分层风险平价:层次聚类+递归二分,无需预期收益,7品种分配
- [scripts/meta_learner_maml.py](scripts/meta_learner_maml.py) — MAML元学习:内外循环,5种市场环境,少样本快速适应
- [scripts/hawkes_process.py](scripts/hawkes_process.py) — Hawkes过程:自激点过程建模,双过程(买/卖),冲击函数I(V)=sigma*V^gamma
- [scripts/causal_factor_scorer.py](scripts/causal_factor_scorer.py) — 因果因子评分:DAG因果图+Granger因果检验+合成控制,USE/DROP推荐

### v5.0模块
- [scripts/market_state_machine.py](scripts/market_state_machine.py) — 市场状态机:3态识别+策略权重映射+Hurst增强(v5.2)
- [scripts/multi_strategy_fusion_v5.py](scripts/multi_strategy_fusion_v5.py) — 多策略融合引擎v5.2:7品种x3策略=21条信号流
- [scripts/funding_rate_arbitrage.py](scripts/funding_rate_arbitrage.py) — 资金费率套利
- [scripts/multi_symbol_scanner.py](scripts/multi_symbol_scanner.py) — 多品种扫描器

### v1.0.4模块
- [scripts/kelly_position_manager.py](scripts/kelly_position_manager.py) — 凯利仓位管理
- [scripts/differentiated_strategy_framework.py](scripts/differentiated_strategy_framework.py) — 差异化策略框架

### v1.0.3模块
- [scripts/out_of_sample_validator.py](scripts/out_of_sample_validator.py) — 样本外验证
- [scripts/trend_direction_filter.py](scripts/trend_direction_filter.py) — 趋势方向过滤器+熔断器

### 参考文档
- [references/quantitative_trading_learning_report.md](references/quantitative_trading_learning_report.md) — 量化交易学习优化报告(理论+方法+实施路径)

### 配置
- [config.json](config.json) — v5.2唯一权威配置(含Hurst/多维评分/期货/BO/HRP/MAML/Hawkes/Causal参数)

## 注意事项
- Hurst指数是市场状态识别的关键指标:Hurst<0.5=均值回归市场,Hurst>0.5=趋势市场
- 多维评分信号的趋势方向加权:顺势×1.5,逆势×0.3,显著改善信号质量
- 动态保本止损:价格到达BB均线时移止损到成本,有效保护浮盈
- 量比过滤:vol_ratio>1.5时不做均值回归(高量=趋势市)
- 贝叶斯优化需严格样本外验证(60/20/20),避免过拟合;建议增加"滚动窗口验证"
- HRP在协方差矩阵估计不稳定时表现最好;数据量越大效果越好
- MAML元训练成本较高(10+分钟),建议离线训练后保存元参数
- Hawkes过程拟合需足够事件(>100),数据不足时参数不稳定
- 因果因子评分依赖统计检验,样本量<200时结论需谨慎
- 废弃1分钟周期策略(胜率17-39%全面失效)
- 月收益预期:保守3-8%,激进10-20%
- 本系统默认为纯模拟模式,不连接真实交易所,无资金风险
