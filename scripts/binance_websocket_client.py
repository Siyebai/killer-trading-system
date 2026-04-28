#!/usr/bin/env python3
"""
Binance Testnet WebSocket 客户端 - Phase 5 P0
封装 Binance WebSocket 实时数据流，对接总控中心健康检查
"""

import json
import asyncio
import websockets
from typing import Dict, Callable, Optional, Any
from datetime import datetime

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("binance_ws")
except ImportError:
    import logging
    logger = logging.getLogger("binance_ws")


class BinanceWebSocketClient:
    """Binance WebSocket 客户端"""

    # Binance Testnet WebSocket 基础 URL
    WS_BASE_URL = "wss://testnet.binance.vision"

    def __init__(self):
        """初始化客户端"""
        self.ws_url: Optional[str] = None
        self.ws_connection: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.message_handler: Optional[Callable] = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5

    def set_message_handler(self, handler: Callable[[Dict], None]):
        """
        设置消息处理器

        Args:
            handler: 消息处理函数，接收 Dict 类型参数
        """
        self.message_handler = handler

    async def connect(self, stream: str, reconnect: bool = True) -> bool:
        """
        连接到 WebSocket 流

        Args:
            stream: 流名称（如 btcusdt@kline_1m）
            reconnect: 是否自动重连

        Returns:
            连接是否成功
        """
        try:
            self.ws_url = f"{self.WS_BASE_URL}/ws/{stream}"

            logger.info(f"正在连接 WebSocket: {self.ws_url}")

            # 第一层防御：连接超时处理
            self.ws_connection = await asyncio.wait_for(
                websockets.connect(self.ws_url),
                timeout=10
            )

            self.is_connected = True
            self.reconnect_attempts = 0

            logger.info(f"✅ WebSocket 连接成功: {stream}")

            # 启动消息接收循环
            asyncio.create_task(self._receive_messages())

            return True

        except asyncio.TimeoutError as e:
            logger.error(f"连接超时: {stream} - {e}")
            if reconnect and self.reconnect_attempts < self.max_reconnect_attempts:
                self.reconnect_attempts += 1
                await asyncio.sleep(2 ** self.reconnect_attempts)  # 指数退避
                return await self.connect(stream, reconnect=True)
            return False

        except Exception as e:
            logger.error(f"连接失败: {stream} - {e}")
            if reconnect and self.reconnect_attempts < self.max_reconnect_attempts:
                self.reconnect_attempts += 1
                await asyncio.sleep(2 ** self.reconnect_attempts)
                return await self.connect(stream, reconnect=True)
            return False

    async def _receive_messages(self):
        """接收消息循环"""
        try:
            async for message in self.ws_connection:
                try:
                    data = json.loads(message)

                    # 调用消息处理器
                    if self.message_handler:
                        self.message_handler(data)

                except json.JSONDecodeError as e:
                    logger.error(f"JSON 解析失败: {e}")
                except Exception as e:
                    logger.error(f"消息处理异常: {e}")

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"WebSocket 连接关闭: {e}")
            self.is_connected = False
        except Exception as e:
            logger.error(f"接收消息异常: {e}")
            self.is_connected = False

    async def close(self):
        """关闭连接"""
        try:
            if self.ws_connection:
                await self.ws_connection.close()
                logger.info("WebSocket 连接已关闭")
        except Exception as e:
            logger.error(f"关闭连接异常: {e}")
        finally:
            self.is_connected = False


class KlineWebSocketClient(BinanceWebSocketClient):
    """K 线 WebSocket 客户端"""

    def __init__(self, symbol: str, interval: str = '1m'):
        """
        初始化 K 线客户端

        Args:
            symbol: 交易对（如 BTCUSDT）
            interval: K 线间隔（1m/5m/15m/1h/4h/1d）
        """
        super().__init__()
        self.symbol = symbol.upper()
        self.interval = interval

        # 构建流名称
        self.stream = f"{self.symbol.lower()}@kline_{self.interval}"

    async def connect(self, reconnect: bool = True) -> bool:
        """连接 K 线流"""
        return await super().connect(self.stream, reconnect=reconnect)

    async def subscribe(self, callback: Callable[[Dict], None]):
        """
        订阅 K 线数据

        Args:
            callback: 回调函数，接收 K 线数据
        """
        def kline_handler(data):
            try:
                # 提取 K 线数据
                kline = data.get('k', {})
                if kline:
                    kline_data = {
                        'symbol': kline.get('s'),
                        'interval': kline.get('i'),
                        'open_time': kline.get('t'),
                        'open': float(kline.get('o', 0)),
                        'high': float(kline.get('h', 0)),
                        'low': float(kline.get('l', 0)),
                        'close': float(kline.get('c', 0)),
                        'volume': float(kline.get('v', 0)),
                        'close_time': kline.get('T'),
                        'is_closed': kline.get('x', False)  # K 线是否已收盘
                    }

                    # 只处理已收盘的 K 线
                    if kline_data['is_closed']:
                        callback(kline_data)

            except Exception as e:
                logger.error(f"K 线数据处理异常: {e}")

        self.set_message_handler(kline_handler)


class TradeWebSocketClient(BinanceWebSocketClient):
    """成交 WebSocket 客户端"""

    def __init__(self, symbol: str):
        """
        初始化成交客户端

        Args:
            symbol: 交易对（如 BTCUSDT）
        """
        super().__init__()
        self.symbol = symbol.upper()
        self.stream = f"{self.symbol.lower()}@trade"

    async def connect(self, reconnect: bool = True) -> bool:
        """连接成交流"""
        return await super().connect(self.stream, reconnect=reconnect)

    async def subscribe(self, callback: Callable[[Dict], None]):
        """
        订阅成交数据

        Args:
            callback: 回调函数，接收成交数据
        """
        def trade_handler(data):
            try:
                # 提取成交数据
                trade = {
                    'symbol': data.get('s'),
                    'price': float(data.get('p', 0)),
                    'quantity': float(data.get('q', 0)),
                    'time': data.get('T'),
                    'is_buyer_maker': data.get('m', False)
                }

                callback(trade)

            except Exception as e:
                logger.error(f"成交数据处理异常: {e}")

        self.set_message_handler(trade_handler)


async def test_kline_stream():
    """测试 K 线流"""
    try:
        client = KlineWebSocketClient('BTCUSDT', '1m')

        def on_kline(kline):
            logger.info(f"收到 K 线: {kline['symbol']} "
                       f"{datetime.fromtimestamp(kline['close_time']/1000)} "
                       f"Close: {kline['close']}")

        await client.subscribe(on_kline)

        if await client.connect():
            logger.info("开始接收 K 线数据（持续 30 秒）...")

            # 运行 30 秒
            await asyncio.sleep(30)

            await client.close()
            logger.info("测试完成")
            return True
        else:
            logger.error("连接失败")
            return False

    except Exception as e:
        logger.error(f"测试异常: {e}")
        return False


if __name__ == "__main__":
    # 测试 K 线流
    if asyncio.run(test_kline_stream()):
logger.debug("WebSocket 测试成功")
    else:
logger.debug("WebSocket 测试失败")
