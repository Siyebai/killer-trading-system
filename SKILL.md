---
name: trading-simulator
description: 工业级杀手锏交易系统(v1.0.2)；当用户需要策略回测、风险模型验证、多策略组合优化、高频交易模拟、交易复盘分析、系统健康评估、自适应阈值优化、风控联动、智能调度时使用
dependency:
  python:
    - numpy==1.24.3
    - pandas==2.0.3
    - scipy>=1.10.0
    - statsmodels>=0.14.0
    - scikit-optimize>=0.9.0
    - fastapi>=0.100.0
    - uvicorn>=0.23.0
    - pytest>=7.0.0
  system:
    - python3
---

# 杀手锏交易系统 v1.0.2

## 任务目标
- 本 Skill 用于: 模拟加密货币高频交易全流程,验证策略逻辑、测试风控模型、优化多策略组合权重、执行交易回测与复盘分析、系统工程加固
- 能力包含: 11层完整闭环 + 总控中心(7状态管理/健康检查/修复引擎/性能优化) + LinUCB强化学习 + EV过滤(含防御性错误处理) + 订单生命周期管理(含状态机校验) + 13项风控规则 + 多策略融合 + 统一日志工厂 + 配置管理器 + 自适应阈值矩阵 + 修复升级协议 + 风控联动桥 + 策略级熔断器 + EDF调度器
- 触发条件: "交易策略回测"、"风险模型测试"、"多策略优化"、"高频交易模拟"、"交易复盘"、"系统评估"、"工程优化"、"自适应阈值"、"风控联动"、"智能调度"

## 前置准备
- 依赖说明: Python 3.8+, numpy, pandas, scipy, statsmodels, scikit-optimize, fastapi, uvicorn, tensorflow(可选)
- 配置文件: `assets/configs/killer_config_v60.json` (v1.0.2唯一权威配置)
- 环境变量: `KILLER_LOG_LEVEL`(日志级别,默认INFO) / `KILLER_LOG_FMT`(compact|json,默认compact)

## 操作步骤

### 推荐运行模式

**v1.0.2总控中心版**（推荐,最完整）
- 完整11层闭环 + 总控中心 + EV过滤 + 订单生命周期
- 启动: `python scripts/complete_loop_v61.py --action run_continuous --interval 60`
- 状态查询: 总控中心自动管理全局状态(7种状态: INIT/RUNNING/PAUSED/DEGRADED/SOFT_BREAKER/HARD_BREAKER/STOPPED)

**独立脚本模式**（灵活调用）
- 82个独立脚本可单独使用,JSON格式数据交换

### 标准流程(v1.0.2)

1. **配置加载与验证** — 使用统一配置管理器加载并验证配置
   - `PYTHONPATH=. python scripts/config_manager.py --config assets/configs/killer_config_v60.json --validate`

2. **总控中心启动** — 初始化全局状态、注册健康检查探针和修复策略

3. **市场状态识别与阈值适配** — 自适应阈值矩阵根据市场状态切换过滤参数
   - `PYTHONPATH=. python scripts/adaptive_threshold_matrix.py --adx 30 --vol 0.012`
   - 趋势市放宽阈值(增加交易机会),震荡市收紧阈值(过滤假信号),高波动市控制仓位

4. **11层闭环执行**(每层执行前查询全局状态):
   - 第1层: 市场扫描(market_scanner.py) — EDF调度器优先扫描高频品种
   - 第2层: 综合分析(comprehensive_analysis.py) — 技术+基本面+情绪+风险+预测
   - 第3层: 智能决策(seven_layer_system.py) — LinUCB权重优化 + 多策略投票 + 策略级熔断器检查
   - EV过滤: 预期价值计算,结合自适应阈值矩阵过滤(ev_filter.py + adaptive_threshold_matrix.py)
   - 第4层: 风控检查(开仓前7条规则) + 风控联动桥检查(GARCH/VaR异常 → 提议DEGRADED)
   - 第5层: 订单执行(order_execution_engine_v60.py) — 幂等性+TTL超时撤单
   - 第6层: 持仓管理(adaptive_stop_loss.py) — 动态止损止盈
   - 第7层: 平仓获利(close_profit_engine.py) — 5种退出模式
   - 第8层: 风控检查(持仓中6条规则) + 熔断联动 + 风控联动桥实时监控
   - 第9层: 复盘总结(review_system.py) — 归因分析(仅RUNNING状态执行)
   - 第10层: 经验学习(experience_learning.py) — 参数调优+模式识别(仅RUNNING状态执行)
   - 第11层: 自我优化(self_optimization_system.py) — 元学习+系统进化(仅RUNNING状态执行)

5. **系统健康监控** — 总控中心持续检查,修复升级协议分级处理
   - 健康检查: WebSocket/执行引擎/风控引擎/数据库 4种探针
   - 修复升级: L1轻量(5s冷却,3次) → L2中度(30s,2次) → L3软熔断(300s) → L4硬熔断(人工介入)
   - 修复后必验证: 修复动作完成后探针重新检查,健康才清零计数器

### 可选分支
- 当需要回测验证: `python scripts/backtesting_engine.py`
- 当需要Web监控: `python scripts/web_dashboard.py`
- 当需要系统评估: 读取 [references/optimization_report_v61.md](references/optimization_report_v61.md)
- 当需要日志调试: 设置 `KILLER_LOG_LEVEL=DEBUG` / `KILLER_LOG_FMT=json`
- 当需要测试验证: `PYTHONPATH=. python -m pytest tests/ -v`

## 使用示例

### 示例1: v1.0.2完整闭环运行
- 场景/输入: 启动完整11层闭环交易系统,带总控中心、EV过滤和自适应阈值
- 预期产出: 自动化交易循环,含健康监控、分级修复、风控联动
- 关键要点: 确保配置文件通过验证,总控中心状态为RUNNING时才执行交易

### 示例2: 自适应阈值与信号过滤
- 场景/输入: 市场进入趋势阶段,ADX=30,已实现波动率=0.012
- 预期产出: 阈值自动放宽至趋势市参数(mtf=0.3, signal=0.5),更多信号通过过滤
- 关键要点: `python scripts/adaptive_threshold_matrix.py --adx 30 --vol 0.012 --mtf-score 0.35 --signal-score 0.55 --confidence 0.55 --ev 0.0003`

### 示例3: 风控联动桥与系统降级
- 场景/输入: GARCH预测波动率飙升(>2σ),VaR预算使用率>80%
- 预期产出: 风控联动桥发出DEGRADED提议,总控中心评估后执行降级
- 关键要点: `python scripts/risk_controller_linkage.py --garch-vol 0.035 --hist-mean 0.01 --hist-std 0.005 --var-current 8000 --var-budget 10000`

## 资源索引

### 脚本
- **v1.0.2深度进化**(新增):
  - [scripts/adaptive_threshold_matrix.py](scripts/adaptive_threshold_matrix.py) — 自适应阈值矩阵: 市场状态分类(趋势/震荡/高波动)+三区独立阈值+反过滤器保护
  - [scripts/repair_upgrade_protocol.py](scripts/repair_upgrade_protocol.py) — 修复升级协议: 4级升级(L1→L4)+修复后必验证+冷却等待+审计日志
  - [scripts/risk_controller_linkage.py](scripts/risk_controller_linkage.py) — 风控联动桥: 预测→行为映射(GARCH/VaR→提议DEGRADED/SOFT_BREAKER)
  - [scripts/strategy_circuit_breaker.py](scripts/strategy_circuit_breaker.py) — 策略级熔断器: 连续亏损→模拟模式→自动恢复/暂停,独立于全局熔断
  - [scripts/edf_scheduler.py](scripts/edf_scheduler.py) — EDF调度器: 最早截止时间优先+延迟感知降频+品种优先级动态调整
- **v1.0.2工程加固**:
  - [scripts/logger_factory.py](scripts/logger_factory.py) — 统一日志工厂,替代print,结构化JSON/紧凑格式,环境变量控制
  - [scripts/config_manager.py](scripts/config_manager.py) — 统一配置管理器,Schema验证,点号路径访问,热加载,变更回调
- **v1.0.2总控中心**:
  - [scripts/global_controller.py](scripts/global_controller.py) — 总控中心: GlobalState(7状态+行为矩阵) + HealthChecker + RepairEngine + Dispatcher + PerformanceOptimizer + BuiltinProbes + BuiltinRepairStrategies
  - [scripts/complete_loop_v61.py](scripts/complete_loop_v61.py) — v1.0.2完整闭环,集成总控中心
- **v1.0.2智能优化**:
  - [scripts/ev_filter.py](scripts/ev_filter.py) — 预期价值过滤: EV计算+批量过滤+交易质量分级
  - [scripts/order_lifecycle_manager.py](scripts/order_lifecycle_manager.py) — 订单生命周期: 10种状态+幂等性控制+TTL超时
  - [scripts/order_execution_engine_v60.py](scripts/order_execution_engine_v60.py) — v1.0.2执行引擎: 去重+TTL撤单+异步任务管理
- **11层闭环核心**:
  - [scripts/market_scanner.py](scripts/market_scanner.py) — 第1层: 市场扫描
  - [scripts/comprehensive_analysis.py](scripts/comprehensive_analysis.py) — 第2层: 综合分析
  - [scripts/seven_layer_system.py](scripts/seven_layer_system.py) — 第3层: 智能决策(LinUCB+多策略投票)
  - [scripts/close_profit_engine.py](scripts/close_profit_engine.py) — 第7层: 平仓获利
  - [scripts/review_system.py](scripts/review_system.py) — 第9层: 复盘总结
  - [scripts/experience_learning.py](scripts/experience_learning.py) — 第10层: 经验学习
  - [scripts/self_optimization_system.py](scripts/self_optimization_system.py) — 第11层: 自我优化
- **风控体系**:
  - [scripts/risk_engine.py](scripts/risk_engine.py) — 风控引擎(13条规则)
  - [scripts/risk_pre_trade.py](scripts/risk_pre_trade.py) — 开仓前风控(7条)
  - [scripts/risk_in_trade.py](scripts/risk_in_trade.py) — 持仓中风控(6条)
  - [scripts/risk_circuit_breaker.py](scripts/risk_circuit_breaker.py) — 分级熔断(软5%/硬10%)
- **辅助模块**:
  - [scripts/backtesting_engine.py](scripts/backtesting_engine.py) — 回测引擎
  - [scripts/database_manager.py](scripts/database_manager.py) — 数据库持久层
  - [scripts/web_dashboard.py](scripts/web_dashboard.py) — Web监控仪表板
  - [scripts/guardian_daemon.py](scripts/guardian_daemon.py) — 守护进程(健康监控+自动修复)
  - [scripts/linucb_optimizer.py](scripts/linucb_optimizer.py) — LinUCB强化学习权重优化
  - [scripts/adaptive_stop_loss.py](scripts/adaptive_stop_loss.py) — 自适应止损
  - [scripts/dynamic_position.py](scripts/dynamic_position.py) — 动态仓位管理
  - [scripts/data_aggregation_engine.py](scripts/data_aggregation_engine.py) — 多源数据聚合
  - [scripts/hybrid_strategy_framework.py](scripts/hybrid_strategy_framework.py) — 混合策略框架

### 参考
- [references/optimization_report_v61.md](references/optimization_report_v61.md) — **专业优化建议报告**: 系统健康度评估(6维评分) + 13项优化建议(P0/P1/P2分级) + 分阶段路线图 + 预期收益量化
- [references/v1.0.2_INTEGRATION_GUIDE.md](references/v1.0.2_INTEGRATION_GUIDE.md) — **v1.0.2模块集成指南**: 5个高级模块(自适应阈值/修复协议/风控联动/策略熔断/EDF调度)与主流程集成示例代码

### 测试
- [tests/test_global_controller.py](tests/test_global_controller.py) — 状态机测试套件(28用例): 合法/非法转换 + 行为矩阵 + 恢复路径 + 健康检查
- [tests/test_adaptive_threshold.py](tests/test_adaptive_threshold.py) — 自适应阈值测试套件(20用例): 市场状态分类 + 阈值切换 + 信号过滤 + 反过滤器保护
- [tests/test_ev_filter.py](tests/test_ev_filter.py) — EV过滤测试套件(20用例): 正常计算 + 边界条件 + 错误处理(零价格/方向错误) + 批量过滤
- [tests/test_order_lifecycle.py](tests/test_order_lifecycle.py) — 订单生命周期测试套件(23用例): 状态机转换 + 非法拒绝 + 幂等性 + 超时撤单 + 回调
- [references/strategy_guide.md](references/strategy_guide.md) — 交易策略开发指南
- [references/risk_rules.md](references/risk_rules.md) — 风控规则详解
- [references/incremental_indicators.md](references/incremental_indicators.md) — 增量指标计算原理
- [references/orderflow_and_regime.md](references/orderflow_and_regime.md) — 订单流分析与市场状态识别

### 资产
- [assets/configs/killer_config_v60.json](assets/configs/killer_config_v60.json) — v1.0.2唯一权威配置文件

## 注意事项
- 所有脚本均为独立命令行工具,通过命令行参数接收输入,JSON格式输出结果
- **配置管理**: 使用 `config_manager.py` 加载配置,禁止直接读取配置文件;配置变更通过 `set()` 方法,自动触发回调
- **日志规范**: 使用 `logger_factory.py` 的 `get_logger()` 获取日志器,禁止使用 `print()`,支持 `KILLER_LOG_LEVEL`/`KILLER_LOG_FMT` 环境变量控制
- **系统评估**: 首次使用或定期维护时,读取 `references/optimization_report_v61.md` 评估系统健康度
- **风控优先**: 止损管理器必须在订单创建后立即挂载;5%-8%单笔止损防止重大回撤
- **自适应阈值**: 根据市场状态(趋势/震荡/高波动)自动切换过滤参数,避免静态阈值导致信号致盲
- **总控中心**: 全局状态控制每层执行权限;硬熔断时自动停止调度器
- **修复升级协议**: 修复按L1→L4逐级升级,每级有冷却时间和最大尝试次数,修复后必须验证
- **风控联动**: VaR/GARCH异常时通过联动桥提议状态变更,总控中心评估后执行
- **策略级熔断**: 每个策略独立熔断,连续亏损进入模拟模式,模拟盈利自动恢复,不影响其他策略
- **EDF调度**: 多品种并行时高频品种优先,慢扫描品种自动降频
- **本系统默认为纯模拟模式,不连接真实交易所,无资金风险**
- **旧版本模块已归档至 scripts/_archived/ 和 assets/configs/_archived/,仅保留v1.0.2闭环/v1.0.2执行引擎/v1.0.2配置**
