#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("order_executor")
except ImportError:
    import logging
    logger = logging.getLogger("order_executor")
"""
Maker/Taker混合订单执行模拟模块
模拟真实的订单簿执行过程
"""

import argparse
import json
import sys
import random
from typing import Dict, List, Tuple


class OrderBook:
    """订单簿模拟器"""

    def __init__(self, base_price: float, depth: int = 10):
        """
        初始化订单簿

        Args:
            base_price: 基准价格
            depth: 深度层数
        """
        self.base_price = base_price
        self.bids = self._generate_bids(depth)
        self.asks = self._generate_asks(depth)

    def _generate_bids(self, depth: int) -> List[Dict]:
        """生成买单深度"""
        bids = []
        for i in range(depth):
            price = self.base_price * (1 - 0.0001 * (i + 1))
            size = random.uniform(0.1, 2.0)
            bids.append({"price": price, "size": size})
        return bids

    def _generate_asks(self, depth: int) -> List[Dict]:
        """生成卖单深度"""
        asks = []
        for i in range(depth):
            price = self.base_price * (1 + 0.0001 * (i + 1))
            size = random.uniform(0.1, 2.0)
            asks.append({"price": price, "size": size})
        return asks

    def get_mid_price(self) -> float:
        """获取中间价"""
        if self.bids and self.asks:
            return (self.bids[0]["price"] + self.asks[0]["price"]) / 2
        return self.base_price

    def get_spread(self) -> float:
        """获取买卖价差"""
        if self.bids and self.asks:
            return (self.asks[0]["price"] - self.bids[0]["price"]) / self.bids[0]["price"]
        return 0.001


class OrderExecutor:
    """订单执行器"""

    def __init__(self, maker_ratio: float = 0.6):
        """
        初始化执行器

        Args:
            maker_ratio: Maker订单比例（0-1）
        """
        self.maker_ratio = maker_ratio

    def split_order(self, order: Dict) -> Tuple[Dict, Dict]:
        """
        将订单拆分为Maker和Taker两部分

        Args:
            order: 原始订单

        Returns:
            (maker_order, taker_order)
        """
        total_size = order.get("size", 0.0)
        maker_size = total_size * self.maker_ratio
        taker_size = total_size * (1 - self.maker_ratio)

        maker_order = {
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "size": maker_size,
            "price": order.get("price"),
            "type": "limit"
        }

        taker_order = {
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "size": taker_size,
            "type": "market"
        }

        return maker_order, taker_order

    def execute_maker(self, order: Dict, orderbook: OrderBook) -> Dict:
        """
        执行Maker订单（挂单等待成交）

        Args:
            order: Maker订单
            orderbook: 订单簿

        Returns:
            执行结果
        """
        side = order.get("side")
        size = order.get("size")
        price = order.get("price")

        # 模拟等待成交概率
        fill_probability = 0.7  # 70%概率成交
        filled = random.random() < fill_probability

        if filled:
            filled_size = size * random.uniform(0.8, 1.0)  # 可能部分成交
            avg_price = price

            # 计算手续费（Maker通常较低）
            fee_rate = 0.0005  # 0.05%
            fee = abs(filled_size * avg_price) * fee_rate

            return {
                "type": "maker",
                "filled": True,
                "filled_size": filled_size,
                "avg_price": avg_price,
                "fee": fee,
                "status": "filled"
            }
        else:
            return {
                "type": "maker",
                "filled": False,
                "filled_size": 0.0,
                "avg_price": 0.0,
                "fee": 0.0,
                "status": "pending"
            }

    def execute_taker(self, order: Dict, orderbook: OrderBook) -> Dict:
        """
        执行Taker订单（立即成交）

        Args:
            order: Taker订单
            orderbook: 订单簿

        Returns:
            执行结果
        """
        side = order.get("side")
        size = order.get("size")

        remaining_size = size
        filled_size = 0.0
        total_cost = 0.0

        if side == "buy":
            # 吃卖单
            for ask in orderbook.asks:
                if remaining_size <= 0:
                    break

                available = ask["size"]
                take = min(remaining_size, available)

                filled_size += take
                total_cost += take * ask["price"]
                remaining_size -= take

            avg_price = total_cost / filled_size if filled_size > 0 else 0
        else:
            # 吃买单
            for bid in orderbook.bids:
                if remaining_size <= 0:
                    break

                available = bid["size"]
                take = min(remaining_size, available)

                filled_size += take
                total_cost += take * bid["price"]
                remaining_size -= take

            avg_price = total_cost / filled_size if filled_size > 0 else 0

        # 计算手续费（Taker通常较高）
        fee_rate = 0.001  # 0.1%
        fee = abs(filled_size * avg_price) * fee_rate

        return {
            "type": "taker",
            "filled": True,
            "filled_size": filled_size,
            "avg_price": avg_price,
            "fee": fee,
            "status": "filled",
            "slippage": abs(avg_price / orderbook.get_mid_price() - 1)
        }

    def execute(self, order: Dict, orderbook: OrderBook) -> Dict:
        """
        执行混合订单

        Args:
            order: 原始订单
            orderbook: 订单簿

        Returns:
            完整执行结果
        """
        # 拆分订单
        maker_order, taker_order = self.split_order(order)

        # 执行Maker订单
        maker_result = self.execute_maker(maker_order, orderbook)

        # 执行Taker订单
        taker_result = self.execute_taker(taker_order, orderbook)

        # 汇总结果
        total_filled_size = maker_result["filled_size"] + taker_result["filled_size"]
        total_fee = maker_result["fee"] + taker_result["fee"]

        if total_filled_size > 0:
            weighted_price = (
                maker_result["filled_size"] * maker_result["avg_price"] +
                taker_result["filled_size"] * taker_result["avg_price"]
            ) / total_filled_size
        else:
            weighted_price = 0

        return {
            "symbol": order.get("symbol"),
            "side": order.get("side"),
            "order_size": order.get("size"),
            "filled_size": total_filled_size,
            "fill_rate": total_filled_size / order.get("size", 1),
            "avg_price": weighted_price,
            "total_fee": total_fee,
            "mid_price": orderbook.get_mid_price(),
            "spread": orderbook.get_spread(),
            "maker_result": maker_result,
            "taker_result": taker_result,
            "timestamp": json.dumps(order.get("timestamp", ""))
        }


def load_market_depth(depth_path: str, base_price: float = 50000.0) -> OrderBook:
    """加载市场深度数据"""
    try:
        with open(depth_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 从数据中提取买卖单
        orderbook = OrderBook(base_price)
        if "bids" in data:
            orderbook.bids = data["bids"]
        if "asks" in data:
            orderbook.asks = data["asks"]

        return orderbook
    except (FileNotFoundError, json.JSONDecodeError):
        # 使用默认订单簿
        return OrderBook(base_price)


def main():
    parser = argparse.ArgumentParser(description="Maker/Taker混合执行")
    parser.add_argument("--order", required=True, help="订单信息(JSON格式)")
    parser.add_argument("--market_depth", help="市场深度JSON文件路径")
    parser.add_argument("--base_price", type=float, default=50000.0, help="基准价格")
    parser.add_argument("--maker_ratio", type=float, default=0.6, help="Maker订单比例(0-1)")

    args = parser.parse_args()

    try:
        order = json.loads(args.order)

        # 验证maker_ratio
        if not 0 <= args.maker_ratio <= 1:
            logger.info(json.dumps({
                "status": "error",
                "message": "maker_ratio必须在0到1之间"
            }, ensure_ascii=False))
            sys.exit(1)

        # 加载订单簿
        if args.market_depth:
            orderbook = load_market_depth(args.market_depth, args.base_price)
        else:
            orderbook = OrderBook(args.base_price)

        # 执行订单
        executor = OrderExecutor(args.maker_ratio)
        result = executor.execute(order, orderbook)

        output = {
            "status": "success",
            "execution": result
        }

        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except json.JSONDecodeError as e:
        logger.error(json.dumps({
            "status": "error",
            "message": f"JSON解析失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        logger.error(json.dumps({
            "status": "error",
            "message": f"订单执行失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
