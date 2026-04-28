#!/usr/bin/env python3
"""
策略级微观熔断器 — 杀手锏交易系统 V6.3
解决单策略可能连续亏损耗尽资金池配额(全局熔断触发前已造成可观回撤)

核心设计:
1. StrategyCircuitBreaker — 策略级独立熔断器
   - 连续亏损N笔 → SOFT(暂停实盘,后台继续模拟)
   - 后续M笔模拟盈利 → 自动恢复
   - 否则升级为 HARD(完全暂停,需人工审核)
2. StrategyCircuitBreakerManager — 管理所有策略的熔断器实例
3. 与GlobalState联动: 策略级熔断不影响其他策略运行
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("strategy_breaker")
except ImportError:
    import logging
    logger = logging.getLogger("strategy_breaker")


# ============================================================
# 1. 策略熔断状态
# ============================================================

class BreakerState(Enum):
    """策略级熔断状态"""
    ACTIVE = "ACTIVE"             # 活跃(正常交易)
    SIMULATING = "SIMULATING"     # 模拟模式(暂停实盘,后台继续模拟)
    SUSPENDED = "SUSPENDED"       # 暂停(需人工审核恢复)


@dataclass
class BreakerConfig:
    """策略级熔断器配置"""
    consecutive_loss_limit: int = 3       # 连续亏损N笔触发SOFT
    simulation_recovery_wins: int = 2     # 模拟模式需M笔盈利恢复
    simulation_max_trades: int = 10       # 模拟模式最大评估交易数
    position_reduction_on_soft: float = 0.5  # SOFT状态仓位缩减比例
    strategy_name: str = ""


@dataclass
class TradeResult:
    """交易结果"""
    strategy: str
    pnl: float              # 盈亏金额
    pnl_pct: float          # 盈亏百分比
    is_simulation: bool     # 是否为模拟交易
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


# ============================================================
# 2. 策略级熔断器
# ============================================================

class StrategyCircuitBreaker:
    """
    单策略熔断器

    状态转换:
    ACTIVE →(连续亏损N笔)→ SIMULATING →(模拟M笔盈利)→ ACTIVE
                                    →(模拟评估失败)→ SUSPENDED
    SUSPENDED →(人工审核通过)→ ACTIVE

    特性:
    - SOFT状态: 暂停实盘,策略继续在模拟环境运行
    - 模拟盈利达到恢复条件 → 自动恢复实盘
    - 仓位缩减: SOFT状态恢复后首次交易仓位减半
    """

    def __init__(self, config: BreakerConfig):
        self.config = config
        self.state = BreakerState.ACTIVE
        self.consecutive_losses = 0
        self.simulation_trades: List[TradeResult] = []
        self.simulation_wins = 0
        self.trade_history: List[Dict] = []
        self._state_changed_at = time.time()
        self._total_real_trades = 0
        self._total_sim_trades = 0

    def record_trade(self, pnl: float, pnl_pct: float,
                     is_simulation: bool = False) -> Dict:
        """
        记录交易结果并更新熔断状态。

        Args:
            pnl: 盈亏金额
            pnl_pct: 盈亏百分比
            is_simulation: 是否为模拟交易

        Returns:
            状态变更信息
        """
        trade = TradeResult(
            strategy=self.config.strategy_name,
            pnl=pnl, pnl_pct=pnl_pct,
            is_simulation=is_simulation
        )
        self.trade_history.append({
            "pnl": pnl, "pnl_pct": pnl_pct,
            "is_simulation": is_simulation,
            "state_before": self.state.value,
            "timestamp": trade.timestamp,
        })

        state_changed = False
        old_state = self.state
        message = ""

        if is_simulation:
            self._total_sim_trades += 1
            self.simulation_trades.append(trade)
            if trade.is_win:
                self.simulation_wins += 1

            # 检查模拟恢复条件
            if self.state == BreakerState.SIMULATING:
                if self.simulation_wins >= self.config.simulation_recovery_wins:
                    self.state = BreakerState.ACTIVE
                    self.consecutive_losses = 0
                    self.simulation_trades.clear()
                    self.simulation_wins = 0
                    state_changed = True
                    message = f"Strategy {self.config.strategy_name} recovered from simulation"
                    logger.info("Strategy recovered from simulation", extra={"extra_data": {
                        "strategy": self.config.strategy_name,
                    }})
                elif len(self.simulation_trades) >= self.config.simulation_max_trades:
                    self.state = BreakerState.SUSPENDED
                    state_changed = True
                    message = f"Strategy {self.config.strategy_name} suspended after {len(self.simulation_trades)} sim trades"
                    logger.warning("Strategy suspended", extra={"extra_data": {
                        "strategy": self.config.strategy_name,
                        "sim_trades": len(self.simulation_trades),
                        "sim_wins": self.simulation_wins,
                    }})
        else:
            self._total_real_trades += 1
            if trade.is_win:
                self.consecutive_losses = 0
            else:
                self.consecutive_losses += 1

            # 检查SOFT触发条件
            if (self.state == BreakerState.ACTIVE and
                    self.consecutive_losses >= self.config.consecutive_loss_limit):
                self.state = BreakerState.SIMULATING
                self.simulation_trades.clear()
                self.simulation_wins = 0
                state_changed = True
                message = f"Strategy {self.config.strategy_name} entered simulation mode after {self.consecutive_losses} consecutive losses"
                logger.warning("Strategy entered simulation", extra={"extra_data": {
                    "strategy": self.config.strategy_name,
                    "consecutive_losses": self.consecutive_losses,
                }})

        if state_changed:
            self._state_changed_at = time.time()

        result = {
            "strategy": self.config.strategy_name,
            "state_before": old_state.value,
            "state_after": self.state.value,
            "state_changed": state_changed,
            "message": message,
            "is_simulation": is_simulation,
            "consecutive_losses": self.consecutive_losses,
        }

        if state_changed:
            logger.info("Strategy breaker state changed", extra={"extra_data": result})

        return result

    def manual_recover(self) -> bool:
        """人工审核恢复(仅SUSPENDED→ACTIVE)"""
        if self.state == BreakerState.SUSPENDED:
            self.state = BreakerState.ACTIVE
            self.consecutive_losses = 0
            self.simulation_trades.clear()
            self.simulation_wins = 0
            self._state_changed_at = time.time()
            logger.info("Strategy manually recovered", extra={"extra_data": {
                "strategy": self.config.strategy_name,
            }})
            return True
        return False

    def is_trading_allowed(self) -> bool:
        """是否允许实盘交易"""
        return self.state == BreakerState.ACTIVE

    def should_simulate(self) -> bool:
        """是否应在模拟模式运行"""
        return self.state == BreakerState.SIMULATING

    def get_position_multiplier(self) -> float:
        """获取仓位乘数(恢复后首次交易减半)"""
        if self.state == BreakerState.SIMULATING:
            return 0.0  # 模拟模式不实际交易
        if self.state == BreakerState.SUSPENDED:
            return 0.0
        # 刚从模拟恢复,仓位缩减
        time_since_change = time.time() - self._state_changed_at
        if time_since_change < 300:  # 5分钟内
            return self.config.position_reduction_on_soft
        return 1.0

    def get_stats(self) -> Dict:
        return {
            "strategy": self.config.strategy_name,
            "state": self.state.value,
            "consecutive_losses": self.consecutive_losses,
            "simulation_wins": self.simulation_wins,
            "total_real_trades": self._total_real_trades,
            "total_sim_trades": self._total_sim_trades,
            "position_multiplier": self.get_position_multiplier(),
            "state_duration_s": round(time.time() - self._state_changed_at, 1),
        }


# ============================================================
# 3. 策略熔断器管理器
# ============================================================

class StrategyCircuitBreakerManager:
    """
    管理所有策略的独立熔断器实例

    特性:
    - 策略级熔断不影响其他策略运行
    - 统一查询接口
    - 与GlobalState联动: 仅当所有策略都SUSPENDED时才考虑全局降级
    """

    def __init__(self):
        self.breakers: Dict[str, StrategyCircuitBreaker] = {}

    def register(self, strategy_name: str, config: Optional[BreakerConfig] = None):
        """注册策略熔断器"""
        if config is None:
            config = BreakerConfig(strategy_name=strategy_name)
        else:
            config.strategy_name = strategy_name
        self.breakers[strategy_name] = StrategyCircuitBreaker(config)
        logger.info("Strategy breaker registered", extra={"extra_data": {
            "strategy": strategy_name
        }})

    def record_trade(self, strategy_name: str, pnl: float, pnl_pct: float,
                     is_simulation: bool = False) -> Dict:
        """记录交易结果"""
        if strategy_name not in self.breakers:
            self.register(strategy_name)
        return self.breakers[strategy_name].record_trade(pnl, pnl_pct, is_simulation)

    def is_trading_allowed(self, strategy_name: str) -> bool:
        """查询策略是否允许实盘交易"""
        if strategy_name not in self.breakers:
            return True  # 未注册的策略默认允许
        return self.breakers[strategy_name].is_trading_allowed()

    def should_simulate(self, strategy_name: str) -> bool:
        """查询策略是否应在模拟模式运行"""
        if strategy_name not in self.breakers:
            return False
        return self.breakers[strategy_name].should_simulate()

    def get_position_multiplier(self, strategy_name: str) -> float:
        """获取策略仓位乘数"""
        if strategy_name not in self.breakers:
            return 1.0
        return self.breakers[strategy_name].get_position_multiplier()

    def get_active_strategies(self) -> List[str]:
        """获取所有活跃策略"""
        return [n for n, b in self.breakers.items() if b.state == BreakerState.ACTIVE]

    def get_simulating_strategies(self) -> List[str]:
        """获取所有模拟中策略"""
        return [n for n, b in self.breakers.items() if b.state == BreakerState.SIMULATING]

    def get_suspended_strategies(self) -> List[str]:
        """获取所有暂停策略"""
        return [n for n, b in self.breakers.items() if b.state == BreakerState.SUSPENDED]

    def all_suspended(self) -> bool:
        """是否所有策略都已暂停"""
        if not self.breakers:
            return False
        return all(b.state == BreakerState.SUSPENDED for b in self.breakers.values())

    def get_dashboard(self) -> Dict:
        """获取策略熔断仪表板"""
        return {
            "total_strategies": len(self.breakers),
            "active": len(self.get_active_strategies()),
            "simulating": len(self.get_simulating_strategies()),
            "suspended": len(self.get_suspended_strategies()),
            "all_suspended": self.all_suspended(),
            "breakers": {n: b.get_stats() for n, b in self.breakers.items()},
        }

    def manual_recover(self, strategy_name: str) -> bool:
        """人工恢复策略"""
        if strategy_name in self.breakers:
            return self.breakers[strategy_name].manual_recover()
        return False


# ============================================================
# 命令行接口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="策略级微观熔断器")
    parser.add_argument("--register", type=str, default=None, help="注册策略")
    parser.add_argument("--record", type=str, default=None, help="记录交易结果(策略名)")
    parser.add_argument("--pnl", type=float, default=0.0, help="盈亏金额")
    parser.add_argument("--pnl-pct", type=float, default=0.0, help="盈亏百分比")
    parser.add_argument("--sim", action="store_true", help="模拟交易")
    parser.add_argument("--dashboard", action="store_true", help="输出仪表板")
    parser.add_argument("--recover", type=str, default=None, help="人工恢复策略")
    parser.add_argument("--simulate-run", action="store_true", help="模拟完整熔断流程")
    args = parser.parse_args()

    mgr = StrategyCircuitBreakerManager()

    if args.simulate_run:
        # 模拟完整熔断流程
        strategies = ["ma_trend", "rsi_mean_revert", "orderflow_break"]
        for s in strategies:
            mgr.register(s)

        results = []

        # 阶段1: 连续亏损触发SOFT
        for i in range(4):
            r = mgr.record_trade("ma_trend", pnl=-50, pnl_pct=-0.005)
            results.append(r)

        # 阶段2: 模拟模式交易
        for i in range(3):
            r = mgr.record_trade("ma_trend", pnl=30 if i > 0 else -10,
                               pnl_pct=0.003 if i > 0 else -0.001, is_simulation=True)
            results.append(r)

        # 其他策略正常
        mgr.record_trade("rsi_mean_revert", pnl=100, pnl_pct=0.01)
        mgr.record_trade("orderflow_break", pnl=-30, pnl_pct=-0.003)

        logger.info(json.dumps({
            "simulation_results": results,
            "dashboard": mgr.get_dashboard()
        }, ensure_ascii=False, indent=2, default=str))
        return

    if args.register:
        mgr.register(args.register)
        logger.info(json.dumps({"status": "registered", "strategy": args.register}))

    if args.record:
        r = mgr.record_trade(args.record, args.pnl, args.pnl_pct, args.sim)
        logger.info(json.dumps(r, ensure_ascii=False))

    if args.dashboard:
        logger.info(json.dumps(mgr.get_dashboard(), ensure_ascii=False, indent=2))

    if args.recover:
        ok = mgr.manual_recover(args.recover)
        logger.info((json.dumps({\n        "status": "recovered" if ok else "not_suspended",
                         "strategy": args.recover}))


if __name__ == "__main__":
    main()
