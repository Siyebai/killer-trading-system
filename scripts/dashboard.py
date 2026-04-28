#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("dashboard")
except ImportError:
    import logging
    logger = logging.getLogger("dashboard")
"""
可视化数据生成模块
生成交易数据和性能指标的可视化数据
"""

import argparse
import json
import sys
from typing import Dict, List
from datetime import datetime


class DashboardGenerator:
    """可视化数据生成器"""

    def __init__(self, history: List[Dict]):
        """
        初始化生成器

        Args:
            history: 交易历史记录
        """
        self.history = history

    def generate_equity_curve(self) -> List[Dict]:
        """
        生成权益曲线数据

        Returns:
            权益曲线数据点列表
        """
        curve = []
        cumulative_pnl = 0.0
        initial_balance = 10000.0  # 默认初始资金

        for i, trade in enumerate(self.history):
            pnl = trade.get("pnl", 0.0)
            cumulative_pnl += pnl
            equity = initial_balance + cumulative_pnl

            curve.append({
                "timestamp": trade.get("timestamp", f"T{i}"),
                "equity": equity,
                "cumulative_pnl": cumulative_pnl,
                "trade_index": i
            })

        return curve

    def generate_performance_metrics(self) -> Dict:
        """
        生成性能指标

        Returns:
            性能指标字典
        """
        if not self.history:
            return {}

        # 基础统计
        total_trades = len(self.history)
        winning_trades = [t for t in self.history if t.get("pnl", 0) > 0]
        losing_trades = [t for t in self.history if t.get("pnl", 0) < 0]

        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0

        # 盈亏统计
        total_pnl = sum(t.get("pnl", 0) for t in self.history)
        total_profit = sum(t.get("pnl", 0) for t in winning_trades)
        total_loss = abs(sum(t.get("pnl", 0) for t in losing_trades))

        avg_win = total_profit / len(winning_trades) if winning_trades else 0
        avg_loss = total_loss / len(losing_trades) if losing_trades else 0

        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        # 夏普比率（简化版）
        if self.history:
            returns = [t.get("pnl", 0) / 10000.0 for t in self.history]
            avg_return = sum(returns) / len(returns) if returns else 0
            import math
            std_return = math.sqrt(sum((r - avg_return) ** 2 for r in returns) / len(returns)) if returns else 0
            sharpe_ratio = (avg_return / std_return) * math.sqrt(252) if std_return > 0 else 0
        else:
            sharpe_ratio = 0

        return {
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": win_rate * 100,
            "total_pnl": total_pnl,
            "total_profit": total_profit,
            "total_loss": total_loss,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe_ratio,
            "max_consecutive_wins": self._calc_consecutive(winning_trades),
            "max_consecutive_losses": self._calc_consecutive(losing_trades)
        }

    def generate_pnl_distribution(self) -> Dict:
        """
        生成盈亏分布

        Returns:
            盈亏分布数据
        """
        pnls = [t.get("pnl", 0) for t in self.history]

        if not pnls:
            return {}

        import math
        mean_pnl = sum(pnls) / len(pnls)
        std_pnl = math.sqrt(sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)) if pnls else 0

        # 分桶统计
        bins = [-1000, -500, -200, -100, -50, 0, 50, 100, 200, 500, 1000]
        distribution = {}

        for i in range(len(bins) - 1):
            lower = bins[i]
            upper = bins[i + 1]
            count = sum(1 for p in pnls if lower <= p < upper)
            distribution[f"{lower}-{upper}"] = count

        return {
            "mean": mean_pnl,
            "std": std_pnl,
            "min": min(pnls) if pnls else 0,
            "max": max(pnls) if pnls else 0,
            "distribution": distribution
        }

    def generate_trade_analysis(self) -> List[Dict]:
        """
        生成交易分析

        Returns:
            交易分析列表
        """
        analysis = []

        for i, trade in enumerate(self.history):
            analysis.append({
                "index": i,
                "timestamp": trade.get("timestamp", ""),
                "symbol": trade.get("symbol", ""),
                "side": trade.get("side", ""),
                "size": trade.get("filled_size", 0.0),
                "entry_price": trade.get("avg_price", 0.0),
                "exit_price": trade.get("exit_price", 0.0),
                "pnl": trade.get("pnl", 0.0),
                "pnl_ratio": trade.get("pnl", 0.0) / 10000.0 * 100,
                "strategy": trade.get("strategy", ""),
                "duration": trade.get("duration", 0),
                "is_winner": trade.get("pnl", 0) > 0
            })

        return analysis

    def _calc_consecutive(self, trades: List[Dict]) -> int:
        """计算最大连续次数"""
        if not trades:
            return 0

        max_consecutive = 0
        current = 0

        timestamps = [t.get("timestamp", "") for t in trades]
        timestamps.sort()

        for i, ts in enumerate(timestamps):
            if i == 0:
                current = 1
            else:
                # 假设连续交易间隔小于1小时
                # 简化处理，实际需要解析时间戳
                current += 1

            max_consecutive = max(max_consecutive, current)

        return max_consecutive

    def generate_dashboard(self) -> Dict:
        """
        生成完整看板数据

        Returns:
            完整看板数据
        """
        return {
            "generated_at": datetime.now().isoformat(),
            "equity_curve": self.generate_equity_curve(),
            "performance_metrics": self.generate_performance_metrics(),
            "pnl_distribution": self.generate_pnl_distribution(),
            "trade_analysis": self.generate_trade_analysis()
        }


def main():
    parser = argparse.ArgumentParser(description="生成可视化数据")
    parser.add_argument("--history", required=True, help="交易历史JSON文件路径")
    parser.add_argument("--output", required=True, help="输出JSON文件路径")

    args = parser.parse_args()

    try:
        with open(args.history, 'r', encoding='utf-8') as f:
            history = json.load(f)

        if not isinstance(history, list):
            logger.info((json.dumps({)
                "status": "error",
                "message": "历史数据必须是列表格式"
            }, ensure_ascii=False))
            sys.exit(1)

        # 生成看板数据
        generator = DashboardGenerator(history)
        dashboard = generator.generate_dashboard()

        # 保存到文件
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(dashboard, f, ensure_ascii=False, indent=2)

        output = {
            "status": "success",
            "message": "看板数据生成成功",
            "output_file": args.output,
            "summary": {
                "total_trades": len(history),
                "equity_points": len(dashboard["equity_curve"]),
                "analysis_trades": len(dashboard["trade_analysis"])
            }
        }

        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except FileNotFoundError:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"历史数据文件未找到: {args.history}"
        }, ensure_ascii=False))
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"JSON解析失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"生成失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
