# V6.3 模块集成指南

## 概述

V6.3 实现了 5 个独立高级模块,本文档说明如何将它们集成到主交易流程中。

## 模块清单

| 模块 | 文件 | 功能 | 状态 |
|------|------|------|------|
| 自适应阈值矩阵 | `adaptive_threshold_matrix.py` | 市场状态分类+三区阈值 | 独立,需集成 |
| 修复升级协议 | `repair_upgrade_protocol.py` | 4级修复+验证 | 独立,需集成 |
| 风控联动桥 | `risk_controller_linkage.py` | 预测→行为映射 | 独立,需集成 |
| 策略级熔断器 | `strategy_circuit_breaker.py` | 策略独立熔断 | 独立,需集成 |
| EDF调度器 | `edf_scheduler.py` | 品种智能调度 | 独立,需集成 |
| 日志迁移工具 | `log_migration.py` | print→logging自动化 | 工具 |

## 集成示例

### 1. 自适应阈值矩阵集成到 ev_filter.py

```python
from scripts.adaptive_threshold_matrix import AdaptiveThresholdMatrix

class EVFilter:
    def __init__(self, config=None):
        self.config = config or {}
        self.min_ev = self.config.get('min_ev', 0.00035)

        # 集成自适应阈值矩阵
        self.adaptive_matrix = AdaptiveThresholdMatrix()

    def calculate_ev(self, input_data):
        # 获取当前市场状态下的阈值
        # 需要传入adx和已实现波动率(从K线数据计算)
        current_thresholds = self.adaptive_matrix.get_current()

        # 使用动态阈值而非静态min_ev
        min_ev_dynamic = current_thresholds.ev_min

        # EV计算逻辑...
        passed = ev > min_ev_dynamic

        return EVFilterResult(...)

    def update_market_regime(self, adx, realized_vol):
        """更新市场状态,切换阈值"""
        return self.adaptive_matrix.update(adx, realized_vol)
```

### 2. 修复升级协议集成到 global_controller.py

```python
from scripts.repair_upgrade_protocol import RepairUpgradeProtocol

class GlobalController:
    def __init__(self, config):
        # 替换原有的BuiltinRepairStrategies
        self.repair_protocol = RepairUpgradeProtocol(verify_wait_seconds=10)

        # 注册修复策略
        self.repair_protocol.register_strategies(
            "websocket_public",
            {
                RepairLevel.L1_LIGHT: self._ws_reconnect,
                RepairLevel.L2_MEDIUM: self._combined_repair,
                RepairLevel.L3_SOFT_BREAKER: lambda: False,
            },
            verify_func=self._verify_websocket
        )

    async def on_module_unhealthy(self, module_name):
        """模块不健康时触发升级修复"""
        record = await self.repair_protocol.attempt_repair(module_name)
        # 记录到审计日志
```

### 3. 风控联动桥集成到 risk_engine.py

```python
from scripts.risk_controller_linkage import RiskControllerLinkage

class RiskEngine:
    def __init__(self):
        self.linkage = RiskControllerLinkage()

    def monitor_risk(self):
        """实时监控并发起状态变更提议"""
        # GARCH波动率检查
        pred_vol = self.garch_forecast()
        self.linkage.check_garch_volatility(
            pred_vol,
            historical_mean=self.vol_mean,
            historical_std=self.vol_std
        )

        # VaR使用率检查
        current_var = self.calculate_var()
        self.linkage.check_var_usage(current_var, self.var_budget)

        # 评估并发送提议
        proposal = self.linkage.evaluate()
        if proposal:
            # 提交给总控中心
            await self.linkage.action_callback(
                proposal.proposed_action, proposal.reason
            )
```

### 4. 策略级熔断器集成到 strategy_manager.py

```python
from scripts.strategy_circuit_breaker import StrategyCircuitBreakerManager

class StrategyManager:
    def __init__(self):
        self.breaker_mgr = StrategyCircuitBreakerManager()

        # 注册策略
        for strategy_name in self.strategies:
            self.breaker_mgr.register(strategy_name)

    def execute_strategy(self, strategy_name, signal):
        """执行策略前检查熔断状态"""
        if not self.breaker_mgr.is_trading_allowed(strategy_name):
            # 如果在模拟模式,仅记录不实际交易
            if self.breaker_mgr.should_simulate(strategy_name):
                return self.simulate_trade(strategy_name, signal)
            return None

        # 获取仓位乘数(恢复后首次交易减半)
        multiplier = self.breaker_mgr.get_position_multiplier(strategy_name)
        quantity = signal.quantity * multiplier

        # 执行交易
        order = self.submit_order(quantity)

        # 记录结果用于熔断判断
        pnl = self.calculate_pnl(order)
        self.breaker_mgr.record_trade(strategy_name, pnl, pnl_pct=0)
```

### 5. EDF调度器集成到 market_scanner.py

```python
from scripts.edf_scheduler import EDFScheduler

class MarketScanner:
    def __init__(self):
        self.scheduler = EDFScheduler()

    def scan_all_symbols(self):
        """智能调度扫描多品种"""
        while True:
            symbol, timeframe = self.scheduler.get_next_symbol()
            if not symbol:
                break

            start = time.time()
            try:
                # 扫描逻辑
                klines = self.fetch_klines(symbol, timeframe)
                signals = self.analyze(symbol, klines)
            except Exception as e:
                logger.error("Scan failed", extra={"extra_data": {
                    "symbol": symbol, "error": str(e)
                }})
                success = False
            else:
                success = True

            duration_ms = (time.time() - start) * 1000
            key = f"{symbol}_{timeframe}"

            # 记录扫描结果,调度器自动降频慢品种
            self.scheduler.record_scan(key, duration_ms, success)

    def register_symbol(self, symbol, timeframe):
        self.scheduler.register_symbol(symbol, timeframe)
```

## 执行日志迁移

### 自动化迁移所有脚本

```bash
# 预览模式(不修改)
PYTHONPATH=. python scripts/log_migration.py --directory scripts

# 实际执行
PYTHONPATH=. python scripts/log_migration.py --directory scripts --apply
```

预期结果: 1725个print迁移为logger调用

## 验证清单

- [ ] ev_filter.py 集成自适应阈值矩阵
- [ ] global_controller.py 集成修复升级协议
- [ ] risk_engine.py 集成风控联动桥
- [ ] strategy_manager.py 集成策略级熔断器
- [ ] market_scanner.py 集成EDF调度器
- [ ] 执行日志迁移: 1725个print → logger
- [ ] 运行所有测试: pytest tests/ -v

## 下一步

集成完成后,系统将具备:
- 自适应交易信号过滤(趋势/震荡/高波动三区)
- 分级故障修复(L1-L4自动升级)
- 预测性风控降级(GARCH/VaR异常触发)
- 策略独立熔断(不影响其他策略)
- 智能多品种调度(高频优先,慢扫描降频)
- 全量结构化日志(故障定位<5分钟)

这些能力共同构成"自我治愈、自我优化"的交易系统基础。
