#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("reconciliation")
except ImportError:
    import logging
    logger = logging.getLogger("reconciliation")
"""
实时对账模块
计算资金变动、持仓状态、盈亏等
"""

import argparse
import json
import sys
from typing import Dict, List


class Reconciliation:
    """对账计算器"""

    def __init__(self, account: Dict, position: Dict):
        """
        初始化对账器

        Args:
            account: 账户信息
            position: 当前持仓
        """
        self.account = account
        self.position = position
        self.initial_balance = account.get("balance", 10000.0)

    def calculate_trade_pnl(self, trade: Dict) -> float:
        """
        计算单笔交易盈亏

        Args:
            trade: 交易记录

        Returns:
            盈亏金额
        """
        side = trade.get("side")
        filled_size = trade.get("filled_size", 0.0)
        avg_price = trade.get("avg_price", 0.0)
        fee = trade.get("total_fee", 0.0)

        if side == "buy":
            # 买入：成本增加
            cost = filled_size * avg_price + fee
            return -cost
        else:
            # 卖出：收入增加
            revenue = filled_size * avg_price - fee
            return revenue

    def update_position(self, trade: Dict, current_price: float) -> Dict:
        """
        更新持仓

        Args:
            trade: 交易记录
            current_price: 当前价格

        Returns:
            更新后的持仓
        """
        symbol = trade.get("symbol")
        side = trade.get("side")
        filled_size = trade.get("filled_size", 0.0)
        avg_price = trade.get("avg_price", 0.0)

        # 获取当前持仓
        if symbol not in self.position:
            self.position[symbol] = {
                "size": 0.0,
                "avg_entry_price": 0.0,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0
            }

        pos = self.position[symbol]

        if side == "buy":
            # 买入更新平均成本
            if pos["size"] >= 0:
                # 加仓
                total_cost = pos["size"] * pos["avg_entry_price"] + filled_size * avg_price
                new_size = pos["size"] + filled_size
                pos["avg_entry_price"] = total_cost / new_size if new_size > 0 else 0
                pos["size"] = new_size
            else:
                # 减空头
                realized = abs(pos["size"]) * (pos["avg_entry_price"] - avg_price)
                pos["realized_pnl"] += realized
                pos["size"] += filled_size

                if pos["size"] > 0:
                    pos["avg_entry_price"] = avg_price

        else:
            # 卖出
            if pos["size"] > 0:
                # 减多头
                realized = (avg_price - pos["avg_entry_price"]) * filled_size
                pos["realized_pnl"] += realized
                pos["size"] -= filled_size

                if pos["size"] < 0:
                    pos["avg_entry_price"] = avg_price
            else:
                # 加空
                total_cost = abs(pos["size"]) * pos["avg_entry_price"] + filled_size * avg_price
                new_size = abs(pos["size"]) + filled_size
                pos["avg_entry_price"] = total_cost / new_size if new_size > 0 else 0
                pos["size"] = -new_size

        # 计算未实现盈亏
        if pos["size"] != 0:
            if pos["size"] > 0:
                pos["unrealized_pnl"] = (current_price - pos["avg_entry_price"]) * pos["size"]
            else:
                pos["unrealized_pnl"] = (pos["avg_entry_price"] - current_price) * abs(pos["size"])
        else:
            pos["unrealized_pnl"] = 0.0

        return self.position

    def reconcile(self, trades: List[Dict], current_prices: Dict[str, float]) -> Dict:
        """
        执行完整对账

        Args:
            trades: 已执行交易列表
            current_prices: 当前价格字典

        Returns:
            对账结果
        """
        total_realized_pnl = 0.0
        total_unrealized_pnl = 0.0
        total_fees = 0.0
        total_volume = 0.0

        trade_count = 0

        # 处理每笔交易
        for trade in trades:
            trade_count += 1
            total_fees += trade.get("total_fee", 0.0)
            total_volume += trade.get("filled_size", 0.0) * trade.get("avg_price", 0.0)

            # 更新持仓
            symbol = trade.get("symbol")
            current_price = current_prices.get(symbol, trade.get("avg_price", 0.0))
            self.update_position(trade, current_price)

        # 计算总盈亏
        for symbol, pos in self.position.items():
            if isinstance(pos, dict):
                total_realized_pnl += pos.get("realized_pnl", 0.0)
                total_unrealized_pnl += pos.get("unrealized_pnl", 0.0)

        total_pnl = total_realized_pnl + total_unrealized_pnl

        # 更新账户
        current_balance = self.initial_balance + total_pnl
        equity = current_balance + total_unrealized_pnl

        # 计算指标
        pnl_ratio = (total_pnl / self.initial_balance) * 100 if self.initial_balance > 0 else 0
        max_drawdown = self._calculate_max_drawdown()

        return {
            "account": {
                "initial_balance": self.initial_balance,
                "current_balance": current_balance,
                "equity": equity,
                "available_balance": current_balance
            },
            "performance": {
                "total_pnl": total_pnl,
                "realized_pnl": total_realized_pnl,
                "unrealized_pnl": total_unrealized_pnl,
                "pnl_ratio": pnl_ratio,
                "max_drawdown": max_drawdown,
                "total_fees": total_fees,
                "total_volume": total_volume,
                "trade_count": trade_count
            },
            "positions": self.position
        }

    def _calculate_max_drawdown(self) -> float:
        """计算最大回撤"""
        # 简化实现：基于当前权益和初始余额
        equity = self.account.get("equity", self.initial_balance)
        peak = max(equity, self.initial_balance)

        if peak > 0:
            return ((peak - equity) / peak) * 100
        return 0.0


def main():
    parser = argparse.ArgumentParser(description="实时对账")
    parser.add_argument("--trades", required=True, help="已执行交易JSON文件路径")
    parser.add_argument("--position", required=True, help="当前持仓JSON文件路径")
    parser.add_argument("--account", required=True, help="账户信息JSON文件路径")
    parser.add_argument("--current_prices", help="当前价格JSON字符串")

    args = parser.parse_args()

    try:
        with open(args.trades, 'r', encoding='utf-8') as f:
            trades = json.load(f)

        with open(args.position, 'r', encoding='utf-8') as f:
            position = json.load(f)

        with open(args.account, 'r', encoding='utf-8') as f:
            account = json.load(f)

        current_prices = json.loads(args.current_prices) if args.current_prices else {}

        # 执行对账
        reconciliation = Reconciliation(account, position)
        result = reconciliation.reconcile(trades, current_prices)

        output = {
            "status": "success",
            "reconciliation": result
        }

        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except FileNotFoundError as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"文件未找到: {str(e)}"
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
            "message": f"对账失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
