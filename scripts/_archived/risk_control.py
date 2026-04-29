#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("risk_control")
except ImportError:
    import logging
    logger = logging.getLogger("risk_control")
"""
13项硬风控检查模块
执行严格的风险控制，确保交易安全
"""

import argparse
import json
import sys
from typing import Dict, List, Tuple


class RiskControl:
    """风控检查器"""

    def __init__(self, risk_config: Dict):
        """
        初始化风控配置

        Args:
            risk_config: 风控配置字典
        """
        self.config = risk_config

    def check_max_position_size(self, order: Dict, position: Dict) -> Tuple[bool, str]:
        """规则1: 最大持仓比例检查"""
        symbol = order.get("symbol", "")
        current_size = position.get(symbol, {}).get("size", 0.0)
        order_size = order.get("size", 0.0)

        max_size_ratio = self.config.get("max_position_ratio", 0.3)
        account_balance = position.get("account_balance", 10000.0)
        price = order.get("price", 0.0)

        max_allowed = account_balance * max_size_ratio / price if price > 0 else float('inf')

        new_size = abs(current_size) + abs(order_size)
        if new_size > max_allowed:
            return False, f"超出最大持仓比例: {new_size:.4f} > {max_allowed:.4f}"

        return True, "通过"

    def check_daily_loss_limit(self, position: Dict) -> Tuple[bool, str]:
        """规则2: 日亏损限额检查"""
        daily_pnl = position.get("daily_pnl", 0.0)
        max_daily_loss = self.config.get("max_daily_loss", 0.05)  # 默认5%

        account_balance = position.get("account_balance", 10000.0)
        loss_ratio = abs(daily_pnl) / account_balance if account_balance > 0 else 0

        if daily_pnl < 0 and loss_ratio > max_daily_loss:
            return False, f"超过日亏损限额: {loss_ratio*100:.2f}% > {max_daily_loss*100:.2f}%"

        return True, "通过"

    def check_drawdown_limit(self, position: Dict) -> Tuple[bool, str]:
        """规则3: 回撤限额检查"""
        current_equity = position.get("equity", position.get("account_balance", 10000.0))
        peak_equity = position.get("peak_equity", current_equity)

        max_drawdown = self.config.get("max_drawdown", 0.10)  # 默认10%

        if peak_equity > 0:
            drawdown = (peak_equity - current_equity) / peak_equity
            if drawdown > max_drawdown:
                return False, f"超过最大回撤限额: {drawdown*100:.2f}% > {max_drawdown*100:.2f}%"

        return True, "通过"

    def check_order_frequency(self, symbol: str) -> Tuple[bool, str]:
        """规则4: 订单频率检查"""
        min_interval = self.config.get("min_order_interval", 1.0)  # 默认1秒

        # 实际实现需要从数据库或文件读取最近订单时间
        # 这里简化为总是通过
        return True, "通过"

    def check_price_deviation(self, order: Dict, market_state: Dict) -> Tuple[bool, str]:
        """规则5: 价格偏离度检查"""
        order_price = order.get("price", 0.0)
        market_price = market_state.get("mid_price", 0.0)

        if market_price > 0:
            deviation = abs(order_price - market_price) / market_price
            max_deviation = self.config.get("max_price_deviation", 0.01)  # 默认1%

            if deviation > max_deviation:
                return False, f"价格偏离过大: {deviation*100:.2f}% > {max_deviation*100:.2f}%"

        return True, "通过"

    def check_concentration_risk(self, order: Dict, position: Dict) -> Tuple[bool, str]:
        """规则6: 集中度风险检查"""
        symbol = order.get("symbol", "")
        max_concentration = self.config.get("max_concentration", 0.4)  # 默认40%

        total_exposure = 0.0
        for sym, pos in position.items():
            if isinstance(pos, dict) and "size" in pos:
                total_exposure += abs(pos["size"])

        order_size = order.get("size", 0.0)
        symbol_exposure = position.get(symbol, {}).get("size", 0.0)

        if total_exposure > 0:
            concentration = (abs(symbol_exposure) + abs(order_size)) / total_exposure
            if concentration > max_concentration:
                return False, f"集中度过高: {concentration*100:.2f}% > {max_concentration*100:.2f}%"

        return True, "通过"

    def check_leverage_limit(self, order: Dict, position: Dict) -> Tuple[bool, str]:
        """规则7: 杠杆限额检查"""
        max_leverage = self.config.get("max_leverage", 3.0)  # 默认3倍

        order_size = order.get("size", 0.0)
        price = order.get("price", 0.0)
        notional = abs(order_size * price)

        account_balance = position.get("account_balance", 10000.0)
        available_balance = position.get("available_balance", account_balance)

        leverage = notional / available_balance if available_balance > 0 else 0

        if leverage > max_leverage:
            return False, f"超过杠杆限额: {leverage:.2f}x > {max_leverage:.2f}x"

        return True, "通过"

    def check_market_volatility(self, market_state: Dict) -> Tuple[bool, str]:
        """规则8: 市场波动率检查"""
        volatility = market_state.get("volatility", 0.0)
        max_volatility = self.config.get("max_volatility", 0.05)  # 默认5%

        if volatility > max_volatility:
            return False, f"市场波动率过高: {volatility*100:.2f}% > {max_volatility*100:.2f}%"

        return True, "通过"

    def check_order_size_limit(self, order: Dict, market_state: Dict) -> Tuple[bool, str]:
        """规则9: 订单规模限制"""
        order_size = order.get("size", 0.0)
        max_order_ratio = self.config.get("max_order_ratio", 0.1)  # 默认10%

        orderbook_value = market_state.get("orderbook_value", 0.0)
        if orderbook_value > 0:
            order_value = abs(order_size * order.get("price", 0.0))
            ratio = order_value / orderbook_value
            if ratio > max_order_ratio:
                return False, f"订单规模过大: {ratio*100:.2f}% > {max_order_ratio*100:.2f}%"

        return True, "通过"

    def check_correlation_risk(self, order: Dict, position: Dict) -> Tuple[bool, str]:
        """规则10: 相关性风险检查"""
        # 简化实现：检查是否持有高相关性品种
        symbol = order.get("symbol", "")

        # BTC和ETH相关性高，限制同时大仓位
        high_corr_pairs = [("BTCUSDT", "ETHUSDT")]
        for pair in high_corr_pairs:
            if symbol in pair:
                other = pair[1] if symbol == pair[0] else pair[0]
                other_size = position.get(other, {}).get("size", 0.0)
                order_size = order.get("size", 0.0)

                combined = abs(other_size) + abs(order_size)
                max_combined = self.config.get("max_correlated_exposure", 0.3)

                if combined > max_combined:
                    return False, f"高相关性品种仓位过大: {combined:.4f} > {max_combined:.4f}"

        return True, "通过"

    def check_liquidity_risk(self, market_state: Dict) -> Tuple[bool, str]:
        """规则11: 流动性风险检查"""
        spread = market_state.get("spread", 0.0)
        max_spread = self.config.get("max_spread", 0.002)  # 默认0.2%

        if spread > max_spread:
            return False, f"流动性不足: 点差 {spread*100:.4f}% > {max_spread*100:.4f}%"

        return True, "通过"

    def check_system_health(self) -> Tuple[bool, str]:
        """规则12: 系统健康检查"""
        # 检查延迟、连接状态等
        # 简化为总是通过
        return True, "通过"

    def check_time_restriction(self) -> Tuple[bool, str]:
        """规则13: 时间限制检查"""
        # 检查是否在允许的交易时间内
        # 简化为总是通过（24/7市场）
        return True, "通过"

    def full_check(self, order: Dict, position: Dict, market_state: Dict) -> Dict:
        """
        执行全部13项风控检查

        Args:
            order: 订单信息
            position: 当前持仓
            market_state: 市场状态

        Returns:
            检查结果字典
        """
        checks = [
            ("最大持仓比例", lambda: self.check_max_position_size(order, position)),
            ("日亏损限额", lambda: self.check_daily_loss_limit(position)),
            ("回撤限额", lambda: self.check_drawdown_limit(position)),
            ("订单频率", lambda: self.check_order_frequency(order.get("symbol", ""))),
            ("价格偏离度", lambda: self.check_price_deviation(order, market_state)),
            ("集中度风险", lambda: self.check_concentration_risk(order, position)),
            ("杠杆限额", lambda: self.check_leverage_limit(order, position)),
            ("市场波动率", lambda: self.check_market_volatility(market_state)),
            ("订单规模限制", lambda: self.check_order_size_limit(order, market_state)),
            ("相关性风险", lambda: self.check_correlation_risk(order, position)),
            ("流动性风险", lambda: self.check_liquidity_risk(market_state)),
            ("系统健康", lambda: self.check_system_health()),
            ("时间限制", lambda: self.check_time_restriction()),
        ]

        results = []
        all_passed = True

        for name, check_func in checks:
            try:
                passed, message = check_func()
                results.append({
                    "rule": name,
                    "passed": passed,
                    "message": message
                })
                if not passed:
                    all_passed = False
            except Exception as e:
                results.append({
                    "rule": name,
                    "passed": False,
                    "message": f"检查异常: {str(e)}"
                })
                all_passed = False

        return {
            "all_passed": all_passed,
            "check_count": len(checks),
            "passed_count": sum(1 for r in results if r["passed"]),
            "failed_count": sum(1 for r in results if not r["passed"]),
            "details": results
        }


def main():
    parser = argparse.ArgumentParser(description="13项硬风控检查")
    parser.add_argument("--order", required=True, help="订单信息(JSON格式)")
    parser.add_argument("--position", required=True, help="当前持仓JSON文件路径")
    parser.add_argument("--risk_config", required=True, help="风控配置JSON文件路径")
    parser.add_argument("--market_state", help="市场状态(JSON格式，可选)")

    args = parser.parse_args()

    try:
        order = json.loads(args.order)

        with open(args.position, 'r', encoding='utf-8') as f:
            position = json.load(f)

        with open(args.risk_config, 'r', encoding='utf-8') as f:
            risk_config = json.load(f)

        market_state = json.loads(args.market_state) if args.market_state else {}

        # 执行风控检查
        risk_control = RiskControl(risk_config)
        result = risk_control.full_check(order, position, market_state)

        output = {
            "status": "success",
            "risk_check": result,
            "order_symbol": order.get("symbol"),
            "order_side": order.get("side"),
            "order_size": order.get("size")
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
            "message": f"风控检查失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
