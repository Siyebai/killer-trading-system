---
name: trading-simulator
description: 工业级杀手锏多策略融合交易系统(v5.0)；当用户需要多策略融合回测、市场状态识别与策略切换、4品种并行扫描、资金费率套利、凯利仓位管理、样本外验证、趋势过滤与熔断机制时使用
dependency:
  python:
    - numpy==1.24.3
    - pandas==2.0.3
    - scipy>=1.10.0
    - statsmodels>=0.14.0
    - scikit-optimize>=0.9.0
    - ta>=0.10.0
  system:
    - python3
---

# 杀手锏交易系统 v5.0

## 任务目标
- 本 Skill 用于: 加密货币多策略融合交易系统,根据市场状态动态切换策略,4品种并行扫描,资金费率套利,凯利仓位管理
- 能力包含: 市场状态机(3态识别)+多策略融合(均值回归/趋势跟踪/资金费率套利)+4品种扫描(BTC/ETH/SOL/BNB)+凯利仓位管理+样本外验证+趋势过滤+熔断机制+ATR动态止损止盈+真实滑点模拟
- 触发条件: "多策略回测"、"市场状态识别"、"资金费率套利"、"品种扫描"、"仓位管理"、"样本外验证"、"趋势过滤"

## 前置准备
- 依赖说明: Python 3.8+, numpy, pandas, scipy, statsmodels, scikit-optimize, ta
- 配置文件: `config.json` (v5.0唯一权威配置)

## 操作步骤

### 标准流程(v5.0)

1. **市场状态识别** — 市场状态机自动识别当前行情类型
   - 脚本调用示例:`python scripts/market_state_machine.py --data <csv_path>`
   - 输出:市场状态(RANGING/TRENDING/EXTREME)+策略权重建议

2. **多品种扫描** — 4品种并行扫描信号
   - 脚本调用示例:`python scripts/multi_symbol_scanner.py --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT --timeframe 1H`
   - 输出:每个品种的信号列表+聚合信号

3. **多策略融合决策** — 根据市场状态动态分配策略权重
   - 脚本调用示例:`python scripts/multi_strategy_fusion_v5.py --capital 10000 --days 30`
   - 震荡市:均值回归60%+趋势跟踪20%+资金费率20%
   - 趋势市:趋势跟踪60%+均值回归20%+资金费率20%
   - 极端市:资金费率40%+趋势跟踪35%+均值回归25%

4. **资金费率套利** — 检测极端费率并反向操作
   - 脚本调用示例:`python scripts/funding_rate_arbitrage.py --data <csv_path>`
   - 触发条件:费率>0.1%做空/费率<-0.05%做多
   - 预期胜率:70%+

5. **凯利仓位管理** — 基于胜率和盈亏比计算最优仓位
   - 1/2凯利保守策略,单笔最大亏损2.5%,日亏5%停机
   - 动态仓位:ATR高时减仓,ATR低时加仓

6. **风控检查** — 趋势过滤+熔断机制+盈亏比保护
   - 趋势过滤:EMA200方向过滤,空头市禁止做多
   - 熔断:连续5笔亏损或日亏5%停仓24小时
   - 盈亏比:强制>=2:1

### 可选分支
- 当需要样本外验证:`python scripts/out_of_sample_validator.py`
- 当需要差异化策略:`python scripts/differentiated_strategy_framework.py`
- 当需要回测验证:`python scripts/backtesting_engine.py`

## 使用示例

### 示例1: v5.0完整多策略融合回测
- 场景/输入:30天4品种回测,初始资金10000 USDT
- 预期产出:回测胜率69.82%,收益12.85%,日均10-30笔交易
- 关键要点:系统自动识别市场状态并切换策略权重

### 示例2: 资金费率套利信号检测
- 场景/输入:检测到BTC资金费率0.15%(极端高)
- 鵆期产出:生成做空信号,仓位1/2凯利=7.4%,预期胜率70%+
- 关键要点:费率极端时信号置信度最高

### 示例3: 市场状态切换
- 场景/输入:市场从震荡转为趋势(ADX从18升至35)
- 预期产出:策略权重从均值回归60%切换为趋势跟踪60%
- 关键要点:状态机滞后确认(5根K线)避免频繁切换

## 资源索引

### 核心脚本(v5.0新增)
- [scripts/market_state_machine.py](scripts/market_state_machine.py) — 市场状态机:3态识别(RANGING/TRENDING/EXTREME)+策略权重映射+滞后确认
- [scripts/multi_strategy_fusion_v5.py](scripts/multi_strategy_fusion_v5.py) — 多策略融合引擎v5.0:均值回归+趋势跟踪+资金费率套利+4品种扫描+凯利仓位
- [scripts/funding_rate_arbitrage.py](scripts/funding_rate_arbitrage.py) — 资金费率套利:极端费率检测+反向操作+历史统计验证
- [scripts/multi_symbol_scanner.py](scripts/multi_symbol_scanner.py) — 4品种扫描器:BTC/ETH/SOL/BNB并行+跨品种相关性+信号聚合

### v1.0.4模块
- [scripts/kelly_position_manager.py](scripts/kelly_position_manager.py) — 凯利仓位管理+动态网格+统计套利
- [scripts/differentiated_strategy_framework.py](scripts/differentiated_strategy_framework.py) — 差异化策略框架:增量/凸性/专业化三大模型

### v1.0.3模块
- [scripts/out_of_sample_validator.py](scripts/out_of_sample_validator.py) — 样本外验证:60/20/20分割+真实滑点
- [scripts/short_strategy_fixer.py](scripts/short_strategy_fixer.py) — SHORT信号生成器:6项评分系统
- [scripts/trend_direction_filter.py](scripts/trend_direction_filter.py) — 趋势方向过滤器:EMA200+熔断器

### 配置
- [config.json](config.json) — v5.0唯一权威配置(含市场状态机/资金费率/跨品种参数)

## 注意事项
- v5.0废弃1分钟周期策略(胜率17-39%全面失效,噪音信号比过高)
- 均值回归策略在单边下跌中天然劣势,需通过市场状态机动态切换
- 单一策略难以突破60%胜率,必须多策略融合
- 资金费率套利是高胜率策略(70%+),但需要实时API数据
- 4品种并行扫描可将日均笔数从0.5-1.3提升至10-30笔
- 凯利仓位管理使用1/2保守策略,全凯利在加密市场风险过高
- 月收益预期调整:保守3-8%,激进10-20%(原50-60%不现实)
- 本系统默认为纯模拟模式,不连接真实交易所,无资金风险
