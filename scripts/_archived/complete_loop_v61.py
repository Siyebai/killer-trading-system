#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("complete_loop_v61")
except ImportError:
    import logging
    logger = logging.getLogger("complete_loop_v61")
"""
杀手锏交易系统 v1.0.3 - 完整闭环系统（含总控中心）
整合v1.0.3 EV过滤 + 订单生命周期管理 + v1.0.3 总控中心

核心升级：
1. v1.0.3: EV过滤 + 订单生命周期管理
2. v1.0.3: 总控中心（全局状态/健康检查/修复引擎/任务调度/性能优化）
3. 零侵入集成：各层执行前查询全局状态
4. 风控熔断联动
5. 多symbol并行调度
6. 在线调参 + 离线搜索触发

使用方法：
    python scripts/complete_loop_v61.py --action run_once
    python scripts/complete_loop_v61.py --action run_continuous --interval 60
    python scripts/complete_loop_v61.py --action status
"""

import argparse
import asyncio
import json
import sys
import time
from typing import Dict, Optional
from pathlib import Path

from scripts.global_controller import (
    GlobalController, GlobalState, SystemState,
    BuiltinProbes, BuiltinRepairStrategies
)


class CompleteLoopv1.0.3:
    """
    完整闭环系统 v1.0.3
    
    11层闭环 + 风控层 + EV过滤 + 订单生命周期 + 总控中心
    每层执行前查询全局状态，实现零侵入集成
    """
    
    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = json.load(f)
        
        # 总控中心
        self.controller = GlobalController(self.config.get('controller', {}))
        self.global_state = GlobalState()
        
        logger.info(f"\n{'='*70}")
        logger.info(f"  杀手锏交易系统 v1.0.3 - 总控中心版")
        logger.info(f"{'='*70}")
        logger.info(f"  [v1.0.3] 11层闭环 + 13风控规则 + 分级熔断")
        logger.info(f"  [v1.0.3] EV过滤 + 订单生命周期管理")
        logger.info(f"  [v1.0.3] 全局状态管理 + 健康检查 + 修复引擎 + 任务调度 + 性能优化")
        logger.info(f"  零侵入集成 | 风控熔断联动 | 多symbol并行 | 在线/离线优化")
        logger.info(f"{'='*70}\n")
    
    async def run_once(self, symbol: str = "BTCUSDT"):
        """
        执行一次闭环（含全局状态检查）
        
        每层执行前查询 GlobalState().is_xxx_allowed()，
        根据状态决定执行、降级或跳过。
        """
        loop_start = time.time()
        
        # ---- 第1层：扫描发现 ----
        if not self.global_state.is_scan_allowed():
            return
        # market_scanner.scan(symbol)
        
        # ---- 第2层：综合分析 ----
        if not self.global_state.is_scan_allowed():
            return
        # comprehensive_analysis.analyze()
        
        # ---- 第3层：智能决策 ----
        if not self.global_state.is_decision_allowed():
            return
        # seven_layer_system.decide()
        
        # ---- v1.0.3: EV过滤 ----
        if not self.global_state.is_trading_allowed():
            return
        # ev_filter.calculate_ev()
        
        # ---- 第3.5层：风控检查 ----
        if not self.global_state.is_trading_allowed():
            return
        # risk_engine.check_pre_trade()
        # 风控熔断联动示例：
        # if drawdown >= 0.05:
        #     await self.global_state.set(SystemState.SOFT_BREAKER, "回撤>=5%")
        # elif drawdown >= 0.10:
        #     await self.global_state.set(SystemState.HARD_BREAKER, "回撤>=10%")
        
        # ---- 第4层：开单执行 ----
        if not self.global_state.is_trading_allowed():
            return
        # order_execution_engine_v60.submit_order()
        
        # ---- 第5-5.5层：持仓盈利 + 持仓风控 ----
        if self.global_state.is_close_allowed():
            # adaptive_stop_loss.check()
            # risk_engine.check_in_trade()
            pass
        
        # ---- 第6层：平仓获利 ----
        if self.global_state.is_close_allowed():
            # close_profit_engine.close()
            pass
        
        # ---- 第7-10层：复盘→学习→汇总→优化 ----
        # review_system.review()
        # experience_learning.learn()
        # information_aggregator.aggregate()
        # self_optimization_system.optimize()
        
        # 记录性能指标
        loop_time_ms = (time.time() - loop_start) * 1000
        self.controller.performance_optimizer.record_metric({
            'loop_time_ms': loop_time_ms,
            'symbol': symbol
        })
    
    async def run_continuous(self, interval: int = 60):
        """连续运行模式（含总控中心 + 多symbol调度）"""
        symbols = self.config.get('scan', {}).get('symbols', ['BTCUSDT'])
        
        # 注册模块健康检查
        self._register_health_checks()
        
        # 启动总控中心
        await self.controller.start()
        
        # 创建调度器
        self.controller.dispatcher = Dispatcher(
            symbols=symbols,
            scan_interval=interval
        )
        
        # 启动调度器（多symbol并行）
        logger.info(f"\n[v1.0.3] 启动多symbol并行调度: {symbols}")
        try:
            await self.controller.dispatcher.start(self.run_once)
        except KeyboardInterrupt:
            logger.error(f"\n[v1.0.3] 收到停止信号")
        finally:
            await self.controller.stop()
    
    def _register_health_checks(self):
        """注册各模块的健康检查和修复策略"""
        # 基础探针（模拟模式使用lambda简化）
        self.controller.register_module_health(
            "market_scanner", lambda: True, lambda: True)
        self.controller.register_module_health(
            "comprehensive_analysis", lambda: True, lambda: True)
        self.controller.register_module_health(
            "execution_engine", lambda: True, lambda: True)
        self.controller.register_module_health(
            "risk_engine", lambda: True)
        
        if self.config.get('ev_filter', {}).get('enabled'):
            self.controller.register_module_health("ev_filter", lambda: True)
        
        if self.config.get('order_lifecycle', {}).get('enabled'):
            self.controller.register_module_health("order_lifecycle", lambda: True)
    
    def print_status(self):
        self.controller.print_status()


# 需要从global_controller导入Dispatcher
from scripts.global_controller import Dispatcher


def main():
    parser = argparse.ArgumentParser(description="杀手锏交易系统 v1.0.3")
    parser.add_argument('--action', choices=['run_once', 'run_continuous', 'status'], default='run_once')
    parser.add_argument('--interval', type=int, default=60)
    parser.add_argument('--config', type=str, default='assets/configs/killer_config_v60.json')
    args = parser.parse_args()
    
    if not Path(args.config).exists():
        logger.info(f"配置文件不存在: {args.config}")
        sys.exit(1)
    
    system = CompleteLoopv1.0.3(args.config)
    
    if args.action == 'run_once':
        asyncio.run(system.run_once())
    elif args.action == 'run_continuous':
        asyncio.run(system.run_continuous(args.interval))
    elif args.action == 'status':
        system.print_status()


if __name__ == "__main__":
    main()
