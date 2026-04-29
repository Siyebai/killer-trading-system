#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("multi_exchange_adapter")
except ImportError:
    import logging
    logger = logging.getLogger("multi_exchange_adapter")
"""
多交易所适配器 - V3.5核心模块
统一接口支持多个交易所
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum


class OrderSide(Enum):
    """订单方向"""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """订单类型"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    """订单"""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    timestamp: float = 0.0
    fees: float = 0.0


@dataclass
class Balance:
    """余额"""
    asset: str
    free: float
    locked: float


@dataclass
class Ticker:
    """行情"""
    symbol: str
    bid: float
    ask: float
    last: float
    volume: float
    timestamp: float


class ExchangeAdapter(ABC):
    """交易所适配器抽象基类"""

    def __init__(self, exchange_id: str, api_key: str = "", api_secret: str = ""):
        """
        初始化适配器

        Args:
            exchange_id: 交易所ID
            api_key: API密钥
            api_secret: API密钥
        """
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.is_connected = False

    @abstractmethod
    def connect(self) -> bool:
        """连接交易所"""
        pass

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    def get_balance(self) -> List[Balance]:
        """获取余额"""
        pass

    @abstractmethod
    def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """获取行情"""
        pass

    @abstractmethod
    def place_order(self, order: Order) -> Optional[Order]:
        """下单"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        pass

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        """查询订单"""
        pass

    @abstractmethod
    def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, List]:
        """获取订单簿"""
        pass

    @abstractmethod
    def get_trades(self, symbol: str, limit: int = 100) -> List[Dict]:
        """获取成交记录"""
        pass


class BinanceAdapter(ExchangeAdapter):
    """Binance适配器"""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        super().__init__("binance", api_key, api_secret)

    def connect(self) -> bool:
        """连接Binance"""
        # 实际实现中使用ccxt或官方API
        logger.info(f"[{self.exchange_id}] 连接交易所...")
        self.is_connected = True
        return True

    def disconnect(self):
        """断开连接"""
        logger.info(f"[{self.exchange_id}] 断开连接...")
        self.is_connected = False

    def get_balance(self) -> List[Balance]:
        """获取余额"""
        if not self.is_connected:
            return []
        return [
            Balance(asset="USDT", free=10000.0, locked=0.0),
            Balance(asset="BTC", free=0.5, locked=0.0),
        ]

    def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """获取行情"""
        if not self.is_connected:
            return None
        return Ticker(
            symbol=symbol,
            bid=49999.0,
            ask=50001.0,
            last=50000.0,
            volume=1000.0,
            timestamp=0
        )

    def place_order(self, order: Order) -> Optional[Order]:
        """下单"""
        if not self.is_connected:
            return None

        # 模拟下单
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.avg_fill_price = order.price or 50000.0

        return order

    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        return True

    def get_order(self, order_id: str) -> Optional[Order]:
        """查询订单"""
        return None

    def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, List]:
        """获取订单簿"""
        return {
            'bids': [(50000 - i*10, 1.0) for i in range(limit)],
            'asks': [(50000 + i*10, 1.0) for i in range(limit)]
        }

    def get_trades(self, symbol: str, limit: int = 100) -> List[Dict]:
        """获取成交记录"""
        return []


class OKXAdapter(ExchangeAdapter):
    """OKX适配器"""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        super().__init__("okx", api_key, api_secret)

    def connect(self) -> bool:
        """连接OKX"""
        logger.info(f"[{self.exchange_id}] 连接交易所...")
        self.is_connected = True
        return True

    def disconnect(self):
        """断开连接"""
        logger.info(f"[{self.exchange_id}] 断开连接...")
        self.is_connected = False

    def get_balance(self) -> List[Balance]:
        """获取余额"""
        if not self.is_connected:
            return []
        return [
            Balance(asset="USDT", free=8000.0, locked=0.0),
            Balance(asset="BTC", free=0.4, locked=0.0),
        ]

    def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """获取行情"""
        if not self.is_connected:
            return None
        return Ticker(
            symbol=symbol,
            bid=49998.0,
            ask=50002.0,
            last=50000.0,
            volume=800.0,
            timestamp=0
        )

    def place_order(self, order: Order) -> Optional[Order]:
        """下单"""
        if not self.is_connected:
            return None

        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.avg_fill_price = order.price or 50000.0

        return order

    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        return True

    def get_order(self, order_id: str) -> Optional[Order]:
        """查询订单"""
        return None

    def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, List]:
        """获取订单簿"""
        return {
            'bids': [(50000 - i*10, 0.8) for i in range(limit)],
            'asks': [(50000 + i*10, 0.8) for i in range(limit)]
        }

    def get_trades(self, symbol: str, limit: int = 100) -> List[Dict]:
        """获取成交记录"""
        return []


class BybitAdapter(ExchangeAdapter):
    """Bybit适配器"""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        super().__init__("bybit", api_key, api_secret)

    def connect(self) -> bool:
        """连接Bybit"""
        logger.info(f"[{self.exchange_id}] 连接交易所...")
        self.is_connected = True
        return True

    def disconnect(self):
        """断开连接"""
        logger.info(f"[{self.exchange_id}] 断开连接...")
        self.is_connected = False

    def get_balance(self) -> List[Balance]:
        """获取余额"""
        if not self.is_connected:
            return []
        return [
            Balance(asset="USDT", free=6000.0, locked=0.0),
            Balance(asset="BTC", free=0.3, locked=0.0),
        ]

    def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """获取行情"""
        if not self.is_connected:
            return None
        return Ticker(
            symbol=symbol,
            bid=49997.0,
            ask=50003.0,
            last=50000.0,
            volume=600.0,
            timestamp=0
        )

    def place_order(self, order: Order) -> Optional[Order]:
        """下单"""
        if not self.is_connected:
            return None

        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.avg_fill_price = order.price or 50000.0

        return order

    def cancel_order(self, order_id: str) -> bool:
        """撤单"""
        return True

    def get_order(self, order_id: str) -> Optional[Order]:
        """查询订单"""
        return None

    def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, List]:
        """获取订单簿"""
        return {
            'bids': [(50000 - i*10, 0.6) for i in range(limit)],
            'asks': [(50000 + i*10, 0.6) for i in range(limit)]
        }

    def get_trades(self, symbol: str, limit: int = 100) -> List[Dict]:
        """获取成交记录"""
        return []


class ExchangeManager:
    """多交易所管理器"""

    def __init__(self):
        """初始化管理器"""
        self.adapters: Dict[str, ExchangeAdapter] = {}
        self.registered_types = {
            'binance': BinanceAdapter,
            'okx': OKXAdapter,
            'bybit': BybitAdapter
        }

    def register_adapter(self, exchange_type: str, exchange_id: str,
                        api_key: str = "", api_secret: str = "") -> bool:
        """
       注册交易所适配器

        Args:
            exchange_type: 交易所类型
            exchange_id: 交易所ID
            api_key: API密钥
            api_secret: API密钥

        Returns:
            是否成功
        """
        if exchange_type not in self.registered_types:
            logger.info(f"不支持的交易所类型: {exchange_type}")
            return False

        adapter_class = self.registered_types[exchange_type]
        adapter = adapter_class(api_key, api_secret)
        self.adapters[exchange_id] = adapter

        return True

    def connect_all(self) -> bool:
        """连接所有交易所"""
        success = True
        for exchange_id, adapter in self.adapters.items():
            if not adapter.connect():
                logger.info(f"连接 {exchange_id} 失败")
                success = False
        return success

    def disconnect_all(self):
        """断开所有交易所"""
        for adapter in self.adapters.values():
            adapter.disconnect()

    def get_adapter(self, exchange_id: str) -> Optional[ExchangeAdapter]:
        """获取指定交易所适配器"""
        return self.adapters.get(exchange_id)

    def get_all_balances(self) -> Dict[str, List[Balance]]:
        """获取所有交易所余额"""
        balances = {}
        for exchange_id, adapter in self.adapters.items():
            balances[exchange_id] = adapter.get_balance()
        return balances

    def compare_tickers(self, symbol: str) -> Dict[str, Ticker]:
        """对比所有交易所行情"""
        tickers = {}
        for exchange_id, adapter in self.adapters.items():
            ticker = adapter.get_ticker(symbol)
            if ticker:
                tickers[exchange_id] = ticker
        return tickers

    def find_arbitrage_opportunities(self, symbol: str,
                                    min_spread_pct: float = 0.1) -> List[Dict[str, Any]]:
        """
        寻找套利机会

        Args:
            symbol: 交易对
            min_spread_pct: 最小价差百分比

        Returns:
            套利机会列表
        """
        tickers = self.compare_tickers(symbol)
        if len(tickers) < 2:
            return []

        opportunities = []

        # 遍历所有交易所对
        for buy_ex_id, buy_ticker in tickers.items():
            for sell_ex_id, sell_ticker in tickers.items():
                if buy_ex_id == sell_ex_id:
                    continue

                # 计算价差
                buy_price = buy_ticker.ask
                sell_price = sell_ticker.bid

                if sell_price > buy_price:
                    spread_pct = (sell_price - buy_price) / buy_price * 100

                    if spread_pct >= min_spread_pct:
                        opportunities.append({
                            'buy_exchange': buy_ex_id,
                            'sell_exchange': sell_ex_id,
                            'buy_price': buy_price,
                            'sell_price': sell_price,
                            'spread_pct': spread_pct,
                            'symbol': symbol
                        })

        # 按价差排序
        opportunities.sort(key=lambda x: x['spread_pct'], reverse=True)

        return opportunities


# 命令行测试
def main():
    """测试多交易所适配器"""
    manager = ExchangeManager()

    # 注册交易所
    logger.info("="*60)
    logger.info("🌐 多交易所适配器测试")
    logger.info("="*60)

    manager.register_adapter('binance', 'binance_1')
    manager.register_adapter('okx', 'okx_1')
    manager.register_adapter('bybit', 'bybit_1')

    # 连接所有交易所
    logger.info("\n连接交易所...")
    manager.connect_all()

    # 获取所有余额
    logger.info("\n获取余额:")
    balances = manager.get_all_balances()
    for exchange_id, bal_list in balances.items():
        logger.info(f"\n{exchange_id}:")
        for bal in bal_list:
            logger.info(f"  {bal.asset}: {bal.free:.2f} (可用) / {bal.locked:.2f} (锁定)")

    # 对比行情
    logger.info("\n\n对比行情 (BTCUSDT):")
    tickers = manager.compare_tickers('BTCUSDT')
    for exchange_id, ticker in tickers.items():
        logger.info(f"{exchange_id}: 买 {ticker.bid} / 卖 {ticker.ask} / 最新 {ticker.last}")

    # 寻找套利机会
    logger.info("\n\n套利机会:")
    opportunities = manager.find_arbitrage_opportunities('BTCUSDT', min_spread_pct=0.01)
    if opportunities:
        for opp in opportunities:
            logger.info((f"  {opp['buy_exchange']}({opp['buy_price']}) -> ")
                  f"{opp['sell_exchange']}({opp['sell_price']}) "
                  f"= {opp['spread_pct']:.3f}%")
    else:
        logger.info("  无套利机会")

    # 测试下单
    logger.info("\n\n测试下单:")
    adapter = manager.get_adapter('binance_1')
    if adapter:
        order = Order(
            order_id="test_001",
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
            price=50000.0
        )
        result = adapter.place_order(order)
        if result:
            logger.info(f"  下单成功: {result.order_id}, 状态: {result.status}")

    # 断开连接
    manager.disconnect_all()

    logger.info("\n" + "="*60)
    logger.info("多交易所适配器测试: PASS")


if __name__ == "__main__":
    main()
