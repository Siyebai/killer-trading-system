"""
模块1: Binance WebSocket K线监听器
- 订阅 BTCUSDT 15m K线流
- 维护本地滑动窗口（最新250根K线）
- 支持断线自动重连（指数退避）
- 线程安全，供信号引擎消费
"""
import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Deque, Dict, List, Optional

import websockets

logger = logging.getLogger("ws_feeder")


class Kline:
    __slots__ = ["ts", "open", "high", "low", "close", "volume", "closed"]

    def __init__(self, ts, o, h, l, c, v, closed):
        self.ts = ts          # open_time ms
        self.open = float(o)
        self.high = float(h)
        self.low = float(l)
        self.close = float(c)
        self.volume = float(v)
        self.closed = closed  # bool: K线是否已收盘


class KlineBuffer:
    """线程安全的K线滑动窗口，最大保留 maxlen 根已收盘K线"""

    def __init__(self, maxlen: int = 300):
        self._buf: Deque[Kline] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()
        self._current: Optional[Kline] = None  # 当前未收盘K线

    async def update(self, kline: Kline) -> bool:
        """更新K线，返回True表示有新K线收盘"""
        async with self._lock:
            if kline.closed:
                self._buf.append(kline)
                self._current = None
                return True
            else:
                self._current = kline
                return False

    def snapshot(self) -> List[Kline]:
        """返回已收盘K线列表（含当前未收盘作为最后一根）"""
        result = list(self._buf)
        if self._current:
            result.append(self._current)
        return result

    def closed_bars(self) -> List[Kline]:
        return list(self._buf)

    def __len__(self):
        return len(self._buf)


class BinanceWSFeeder:
    """
    Binance WebSocket K线订阅器
    支持: 断线重连(指数退避, 最大60s), 心跳检测
    """
    WS_BASE = "wss://fstream.binance.com/ws"   # 合约; 现货用 stream.binance.com

    def __init__(
        self,
        symbol: str,
        interval: str,
        buffer: KlineBuffer,
        on_closed: Optional[Callable] = None,
        testnet: bool = False,
    ):
        self.symbol = symbol.lower()
        self.interval = interval
        self.buffer = buffer
        self.on_closed = on_closed  # 新K线收盘回调
        self._running = False
        self._reconnect_delay = 1.0
        if testnet:
            self.WS_BASE = "wss://stream.binancefuture.com/ws"

    def _stream_url(self) -> str:
        return f"{self.WS_BASE}/{self.symbol}@kline_{self.interval}"

    def _parse(self, msg: dict) -> Optional[Kline]:
        k = msg.get("k", {})
        if not k:
            return None
        return Kline(
            ts=int(k["t"]),
            o=k["o"], h=k["h"], l=k["l"], c=k["c"],
            v=k["v"],
            closed=bool(k.get("x", False)),
        )

    async def run(self):
        self._running = True
        logger.info(f"[WS] 启动订阅: {self.symbol} {self.interval}")
        while self._running:
            try:
                async with websockets.connect(
                    self._stream_url(),
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._reconnect_delay = 1.0  # 连接成功重置退避
                    logger.info(f"[WS] 已连接: {self._stream_url()}")
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("e") != "kline":
                            continue
                        kline = self._parse(msg)
                        if kline is None:
                            continue
                        new_closed = await self.buffer.update(kline)
                        if new_closed and self.on_closed:
                            await self.on_closed(kline)
            except (websockets.ConnectionClosed, ConnectionResetError, OSError) as e:
                logger.warning(f"[WS] 断线: {e}，{self._reconnect_delay:.1f}s 后重连")
            except Exception as e:
                logger.error(f"[WS] 异常: {e}，{self._reconnect_delay:.1f}s 后重连")

            if not self._running:
                break
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)

    def stop(self):
        self._running = False
        logger.info("[WS] 停止订阅")


async def init_buffer_from_rest(
    symbol: str,
    interval: str,
    buffer: KlineBuffer,
    limit: int = 250,
    testnet: bool = False,
) -> None:
    """
    启动时从REST API预填充历史K线，避免等待WS攒够数据
    """
    import aiohttp

    base = "https://fapi.binance.com" if not testnet else "https://testnet.binancefuture.com"
    url = f"{base}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()

    logger.info(f"[REST] 预加载 {len(data)} 根K线")
    for row in data[:-1]:  # 最后一根可能未收盘，跳过
        k = Kline(
            ts=int(row[0]),
            o=row[1], h=row[2], l=row[3], c=row[4],
            v=row[5],
            closed=True,
        )
        await buffer.update(k)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def _test():
        buf = KlineBuffer(maxlen=300)
        await init_buffer_from_rest("BTCUSDT", "15m", buf, limit=10)
        bars = buf.closed_bars()
        print(f"预加载: {len(bars)}根K线")
        if bars:
            last = bars[-1]
            ts_str = datetime.fromtimestamp(last.ts/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"最新K线: {ts_str} O={last.open} H={last.high} L={last.low} C={last.close}")

    asyncio.run(_test())
