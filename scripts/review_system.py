#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("review_system")
except ImportError:
    import logging
    logger = logging.getLogger("review_system")
"""
复盘总结系统（第7层：复盘总结）
交易分析器 + 绩效评估系统 + 归因分析
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import pandas as pd


class TradeStatus(Enum):
    """交易状态"""
    COMPLETED = "COMPLETED"  # 已完成
    OPEN = "OPEN"  # 未平仓
    CANCELLED = "CANCELLED"  # 已取消


@dataclass
class Trade:
    """交易"""
    trade_id: str
    symbol: str
    side: str  # LONG/SHORT
    entry_price: float
    exit_price: Optional[float] = None
    quantity: float
    entry_time: float = field(default_factory=time.time)
    exit_time: Optional[float] = None
    status: TradeStatus = TradeStatus.OPEN
    pnl: float = 0.0
    pnl_pct: float = 0.0
    fees: float = 0.0
    holding_time: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    exit_reason: Optional[str] = None
    strategy: Optional[str] = None
    notes: str = ""

    def complete(self, exit_price: float, exit_time: float, exit_reason: str):
        """完成交易"""
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = exit_reason
        self.status = TradeStatus.COMPLETED
        self.holding_time = exit_time - self.entry_time

        # 计算盈亏
        if self.side == 'LONG':
            self.pnl = (exit_price - self.entry_price) * self.quantity
        else:
            self.pnl = (self.entry_price - exit_price) * self.quantity

        # 扣除手续费
        self.pnl -= self.fees

        # 计算盈亏百分比
        self.pnl_pct = self.pnl / (self.entry_price * self.quantity)

    def to_dict(self) -> Dict:
        return {
            'trade_id': self.trade_id,
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'quantity': self.quantity,
            'entry_time': self.entry_time,
            'exit_time': self.exit_time,
            'status': self.status.value,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'fees': self.fees,
            'holding_time': self.holding_time,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'exit_reason': self.exit_reason,
            'strategy': self.strategy,
            'notes': self.notes
        }


@dataclass
class PerformanceMetrics:
    """绩效指标"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_profit: float
    total_loss: float
    avg_profit: float
    avg_loss: float
    avg_holding_time: float
    max_profit: float
    max_loss: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    avg_daily_pnl: float

    def to_dict(self) -> Dict:
        return {
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'total_pnl': self.total_pnl,
            'total_profit': self.total_profit,
            'total_loss': self.total_loss,
            'avg_profit': self.avg_profit,
            'avg_loss': self.avg_loss,
            'avg_holding_time': self.avg_holding_time,
            'max_profit': self.max_profit,
            'max_loss': self.max_loss,
            'profit_factor': self.profit_factor,
            'sharpe_ratio': self.sharpe_ratio,
            'max_drawdown': self.max_drawdown,
            'avg_daily_pnl': self.avg_daily_pnl
        }


@dataclass
class AttributionAnalysis:
    """归因分析"""
    strategy_performance: Dict[str, PerformanceMetrics]
    symbol_performance: Dict[str, PerformanceMetrics]
    time_performance: Dict[str, PerformanceMetrics]
    exit_reason_performance: Dict[str, PerformanceMetrics]
    direction_performance: Dict[str, PerformanceMetrics]

    def to_dict(self) -> Dict:
        return {
            'strategy_performance': {
                k: v.to_dict() if hasattr(v, 'to_dict') else v
                for k, v in self.strategy_performance.items()
            },
            'symbol_performance': {
                k: v.to_dict() if hasattr(v, 'to_dict') else v
                for k, v in self.symbol_performance.items()
            },
            'time_performance': {
                k: v.to_dict() if hasattr(v, 'to_dict') else v
                for k, v in self.time_performance.items()
            },
            'exit_reason_performance': {
                k: v.to_dict() if hasattr(v, 'to_dict') else v
                for k, v in self.exit_reason_performance.items()
            },
            'direction_performance': {
                k: v.to_dict() if hasattr(v, 'to_dict') else v
                for k, v in self.direction_performance.items()
            }
        }


class TradeAnalyzer:
    """交易分析器"""

    def __init__(self):
        self.trades: List[Trade] = []

    def add_trade(self, trade: Trade):
        """添加交易"""
        self.trades.append(trade)

    def load_trades(self, trades_data: List[Dict]):
        """加载交易数据"""
        for trade_data in trades_data:
            trade = Trade(**trade_data)
            self.trades.append(trade)

    def get_completed_trades(self) -> List[Trade]:
        """获取已完成的交易"""
        return [t for t in self.trades if t.status == TradeStatus.COMPLETED]

    def calculate_performance(self, trades: List[Trade]) -> PerformanceMetrics:
        """计算绩效指标"""
        completed_trades = [t for t in trades if t.status == TradeStatus.COMPLETED]

        if not completed_trades:
            return PerformanceMetrics(
                total_trades=0, winning_trades=0, losing_trades=0, win_rate=0.0,
                total_pnl=0.0, total_profit=0.0, total_loss=0.0,
                avg_profit=0.0, avg_loss=0.0, avg_holding_time=0.0,
                max_profit=0.0, max_loss=0.0, profit_factor=0.0,
                sharpe_ratio=0.0, max_drawdown=0.0, avg_daily_pnl=0.0
            )

        total_trades = len(completed_trades)
        winning_trades = [t for t in completed_trades if t.pnl > 0]
        losing_trades = [t for t in completed_trades if t.pnl <= 0]

        win_count = len(winning_trades)
        loss_count = len(losing_trades)

        win_rate = win_count / total_trades if total_trades > 0 else 0.0

        total_pnl = sum(t.pnl for t in completed_trades)
        total_profit = sum(t.pnl for t in winning_trades) if winning_trades else 0.0
        total_loss = sum(t.pnl for t in losing_trades) if losing_trades else 0.0

        avg_profit = total_profit / win_count if win_count > 0 else 0.0
        avg_loss = total_loss / loss_count if loss_count > 0 else 0.0

        avg_holding_time = sum(t.holding_time for t in completed_trades) / total_trades

        max_profit = max((t.pnl for t in winning_trades), default=0.0)
        max_loss = min((t.pnl for t in losing_trades), default=0.0)

        profit_factor = abs(total_profit / total_loss) if total_loss != 0 else float('inf')

        # 夏普比率（简化版）
        if completed_trades:
            pnl_returns = [t.pnl_pct for t in completed_trades]
            sharpe_ratio = np.mean(pnl_returns) / (np.std(pnl_returns) + 1e-10)
        else:
            sharpe_ratio = 0.0

        # 最大回撤
        if completed_trades:
            cumulative_pnl = np.cumsum([t.pnl for t in completed_trades])
            running_max = np.maximum.accumulate(cumulative_pnl)
            drawdown = running_max - cumulative_pnl
            max_drawdown = max(drawdown)
        else:
            max_drawdown = 0.0

        # 平均每日盈亏
        if completed_trades:
            time_range = max(t.exit_time for t in completed_trades) - min(t.entry_time for t in completed_trades)
            days = max(time_range / 86400, 1)
            avg_daily_pnl = total_pnl / days
        else:
            avg_daily_pnl = 0.0

        return PerformanceMetrics(
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate=win_rate,
            total_pnl=total_pnl,
            total_profit=total_profit,
            total_loss=total_loss,
            avg_profit=avg_profit,
            avg_loss=avg_loss,
            avg_holding_time=avg_holding_time,
            max_profit=max_profit,
            max_loss=max_loss,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            avg_daily_pnl=avg_daily_pnl
        )


class AttributionAnalyzer:
    """归因分析器"""

    def __init__(self):
        self.trade_analyzer = TradeAnalyzer()

    def analyze(self, trades: List[Trade]) -> AttributionAnalysis:
        """执行归因分析"""
        completed_trades = [t for t in trades if t.status == TradeStatus.COMPLETED]

        # 按策略分组
        strategy_groups = {}
        for trade in completed_trades:
            strategy = trade.strategy or 'unknown'
            if strategy not in strategy_groups:
                strategy_groups[strategy] = []
            strategy_groups[strategy].append(trade)

        strategy_performance = {}
        for strategy, group_trades in strategy_groups.items():
            strategy_performance[strategy] = self.trade_analyzer.calculate_performance(group_trades)

        # 按品种分组
        symbol_groups = {}
        for trade in completed_trades:
            symbol = trade.symbol
            if symbol not in symbol_groups:
                symbol_groups[symbol] = []
            symbol_groups[symbol].append(trade)

        symbol_performance = {}
        for symbol, group_trades in symbol_groups.items():
            symbol_performance[symbol] = self.trade_analyzer.calculate_performance(group_trades)

        # 按时间段分组（简化版）
        time_groups = {}
        for trade in completed_trades:
            hour = int((trade.entry_time % 86400) / 3600)
            time_key = f"{hour:02d}:00-{(hour+1)%24:02d}:00"
            if time_key not in time_groups:
                time_groups[time_key] = []
            time_groups[time_key].append(trade)

        time_performance = {}
        for time_key, group_trades in time_groups.items():
            time_performance[time_key] = self.trade_analyzer.calculate_performance(group_trades)

        # 按退出原因分组
        exit_reason_groups = {}
        for trade in completed_trades:
            exit_reason = trade.exit_reason or 'unknown'
            if exit_reason not in exit_reason_groups:
                exit_reason_groups[exit_reason] = []
            exit_reason_groups[exit_reason].append(trade)

        exit_reason_performance = {}
        for exit_reason, group_trades in exit_reason_groups.items():
            exit_reason_performance[exit_reason] = self.trade_analyzer.calculate_performance(group_trades)

        # 按方向分组
        direction_groups = {}
        for trade in completed_trades:
            direction = trade.side
            if direction not in direction_groups:
                direction_groups[direction] = []
            direction_groups[direction].append(trade)

        direction_performance = {}
        for direction, group_trades in direction_groups.items():
            direction_performance[direction] = self.trade_analyzer.calculate_performance(group_trades)

        return AttributionAnalysis(
            strategy_performance=strategy_performance,
            symbol_performance=symbol_performance,
            time_performance=time_performance,
            exit_reason_performance=exit_reason_performance,
            direction_performance=direction_performance
        )


class ReviewSystem:
    """复盘总结系统"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化复盘总结系统

        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.trade_analyzer = TradeAnalyzer()
        self.attribution_analyzer = AttributionAnalyzer()

    def load_trades(self, trades_data: List[Dict]):
        """加载交易数据"""
        self.trade_analyzer.load_trades(trades_data)

    def review(self) -> Dict[str, Any]:
        """执行复盘"""
        logger.info(f"[复盘开始] 加载交易数据...")

        # 获取所有交易
        all_trades = self.trade_analyzer.trades
        completed_trades = self.trade_analyzer.get_completed_trades()

        logger.info(f"[复盘数据] 总交易数: {len(all_trades)}")
        logger.info(f"[复盘数据] 已完成交易: {len(completed_trades)}")

        if not completed_trades:
            return {
                "status": "success",
                "message": "没有已完成的交易可供复盘",
                "performance": None,
                "attribution": None
            }

        # 计算整体绩效
        logger.info(f"[复盘分析] 计算整体绩效...")
        overall_performance = self.trade_analyzer.calculate_performance(all_trades)

        # 归因分析
        logger.info(f"[复盘分析] 执行归因分析...")
        attribution = self.attribution_analyzer.analyze(all_trades)

        # 生成复盘报告
        report = self.generate_report(overall_performance, attribution)

        return {
            "status": "success",
            "performance": overall_performance.to_dict(),
            "attribution": attribution.to_dict(),
            "report": report
        }

    def generate_report(self, performance: PerformanceMetrics, attribution: AttributionAnalysis) -> Dict[str, Any]:
        """生成复盘报告"""
        report = {
            "summary": "",
            "key_findings": [],
            "recommendations": [],
            "top_performers": {},
            "areas_for_improvement": []
        }

        # 摘要
        report["summary"] = f"本阶段共完成{performance.total_trades}笔交易，胜率{performance.win_rate:.1%}，" \
                           f"总盈亏{performance.total_pnl:.2f}，夏普比率{performance.sharpe_ratio:.2f}"

        # 关键发现
        if performance.win_rate < 0.5:
            report["key_findings"].append(f"胜率较低（{performance.win_rate:.1%}），建议优化策略")
        else:
            report["key_findings"].append(f"胜率良好（{performance.win_rate:.1%}）")

        if performance.sharpe_ratio < 1.0:
            report["key_findings"].append(f"夏普比率偏低（{performance.sharpe_ratio:.2f}），需要优化风险调整收益")
        else:
            report["key_findings"].append(f"夏普比率良好（{performance.sharpe_ratio:.2f}）")

        if performance.max_drawdown > 0.2:
            report["key_findings"].append(f"最大回撤较大（{performance.max_drawdown:.2f}），需要加强风控")

        # 最佳表现
        if attribution.strategy_performance:
            best_strategy = max(attribution.strategy_performance.items(),
                               key=lambda x: x[1].win_rate if hasattr(x[1], 'win_rate') else 0)
            report["top_performers"]["best_strategy"] = {
                "name": best_strategy[0],
                "win_rate": best_strategy[1].win_rate if hasattr(best_strategy[1], 'win_rate') else 0
            }

        if attribution.direction_performance:
            best_direction = max(attribution.direction_performance.items(),
                               key=lambda x: x[1].win_rate if hasattr(x[1], 'win_rate') else 0)
            report["top_performers"]["best_direction"] = {
                "name": best_direction[0],
                "win_rate": best_direction[1].win_rate if hasattr(best_direction[1], 'win_rate') else 0
            }

        # 建议
        if performance.win_rate < 0.6:
            report["recommendations"].append("提高信号质量，优化入场时机")

        if performance.profit_factor < 1.5:
            report["recommendations"].append("优化盈亏比，加强止盈管理")

        if performance.max_drawdown > 0.15:
            report["recommendations"].append("降低仓位或收紧止损")

        if performance.avg_holding_time > 86400:  # 超过24小时
            report["recommendations"].append("优化持仓时间，避免长期套牢")

        return report


def main():
    parser = argparse.ArgumentParser(description="复盘总结系统（第7层：复盘总结）")
    parser.add_argument("--action", choices=["review", "test"], default="test", help="操作类型")
    parser.add_argument("--trades_file", help="交易数据JSON文件路径")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r') as f:
                config = json.load(config)

        # 创建复盘系统
        review_system = ReviewSystem(config)

        logger.info("=" * 70)
        logger.info("✅ 杀手锏交易系统 - 复盘总结系统（第7层：复盘总结）")
        logger.info("=" * 70)

        if args.action == "review":
            # 加载交易数据
            if not args.trades_file:
                logger.info("错误: 请提供交易数据文件")
                sys.exit(1)

            with open(args.trades_file, 'r') as f:
                trades_data = json.load(f)

            review_system.load_trades(trades_data)

            # 执行复盘
            logger.info(f"\n[复盘执行] 开始复盘分析...")
            result = review_system.review()

            logger.info(f"\n[复盘完成]")
            if result["performance"]:
                perf = result["performance"]
                logger.info(f"  总交易数: {perf['total_trades']}")
                logger.info(f"  胜率: {perf['win_rate']:.1%}")
                logger.info(f"  总盈亏: {perf['total_pnl']:.2f}")
                logger.info(f"  夏普比率: {perf['sharpe_ratio']:.2f}")
                logger.info(f"  最大回撤: {perf['max_drawdown']:.2f}")
                logger.info(f"  盈亏比: {perf['profit_factor']:.2f}")

            if result["report"]:
                report = result["report"]
                logger.info(f"\n[复盘摘要] {report['summary']}")
                logger.info(f"\n[关键发现]")
                for finding in report["key_findings"]:
                    logger.info(f"  - {finding}")

                logger.info(f"\n[优化建议]")
                for rec in report["recommendations"]:
                    logger.info(f"  - {rec}")

            output = result

        elif args.action == "test":
            # 测试模式
            # 生成测试交易数据
            test_trades = []
            base_time = time.time() - 86400 * 30  # 30天前

            for i in range(100):
                is_profit = np.random.random() > 0.4  # 60%胜率
                side = 'LONG' if np.random.random() > 0.5 else 'SHORT'
                entry_price = 50000.0 + np.random.uniform(-1000, 1000)

                if is_profit:
                    exit_price = entry_price * (1 + np.random.uniform(0.005, 0.02))
                else:
                    exit_price = entry_price * (1 - np.random.uniform(0.005, 0.02))

                trade_data = {
                    'trade_id': f'trade_{i}',
                    'symbol': 'BTCUSDT',
                    'side': side,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'quantity': 0.1,
                    'entry_time': base_time + i * 3600,
                    'exit_time': base_time + i * 3600 + np.random.randint(1800, 7200),
                    'status': 'COMPLETED',
                    'strategy': 'trend_following' if i % 3 == 0 else 'mean_reversion',
                    'fees': 10.0
                }

                test_trades.append(trade_data)

            review_system.load_trades(test_trades)
            result = review_system.review()

            output = {
                "status": "success",
                "test_result": result
            }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        import traceback
        logger.error((json.dumps({)
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
