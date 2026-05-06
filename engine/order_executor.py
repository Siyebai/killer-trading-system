"""
模块4: 订单执行器
- Binance Futures REST API 下单/平仓
- HMAC签名，支持主网/测试网
- 市价单开仓 + 条件单SL/TP
- 持仓查询 / 订单状态轮询
- 断线续单（启动时恢复未平仓位）
"""
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional, Dict, Any

import requests

logger = logging.getLogger("order_executor")


@dataclass
class Position:
    symbol: str
    direction: str       # "LONG" / "SHORT"
    entry_price: float
    quantity: float
    sl_price: float
    tp_price: float
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    open_time: int = 0


class BinanceExecutor:
    """
    Binance USDM Futures 执行器
    使用 LIMIT 开仓（可改 MARKET），STOP_MARKET + TAKE_PROFIT_MARKET 止损止盈
    """

    MAINNET_BASE = "https://fapi.binance.com"
    TESTNET_BASE = "https://testnet.binancefuture.com"

    def __init__(self, api_key: str, secret: str, testnet: bool = False):
        self.api_key = api_key
        self.secret = secret
        self.base_url = self.TESTNET_BASE if testnet else self.MAINNET_BASE
        self.testnet = testnet
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        })

    def _sign(self, params: dict) -> dict:
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def _request(self, method: str, path: str, params: dict, signed: bool = True, retries: int = 3) -> dict:
        """带限流重试的通用请求方法"""
        for attempt in range(retries):
            params["timestamp"] = int(time.time() * 1000)
            if signed:
                params = self._sign(params.copy())
            try:
                if method == "GET":
                    resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=10)
                elif method == "POST":
                    resp = self.session.post(f"{self.base_url}{path}", data=params, timeout=10)
                elif method == "DELETE":
                    resp = self.session.delete(f"{self.base_url}{path}", params=params, timeout=10)
                else:
                    raise ValueError(f"未知方法: {method}")

                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 5)) + attempt * 2
                    logger.warning(f"[Exec] 限流429，等待{wait}s重试(第{attempt+1}次)")
                    time.sleep(wait)
                    continue
                if resp.status_code == 418:
                    logger.error("[Exec] IP被封禁418，停止重试")
                    raise RuntimeError("IP banned by Binance (418)")

                data = resp.json()
                if isinstance(data, dict) and "code" in data and data["code"] < 0:
                    raise RuntimeError(f"Binance API错误: {data}")
                return data

            except (requests.Timeout, requests.ConnectionError) as e:
                wait = 2 ** attempt
                logger.warning(f"[Exec] 网络错误({e})，{wait}s后重试")
                time.sleep(wait)

        raise RuntimeError(f"请求失败，已重试{retries}次: {method} {path}")

    def _get(self, path: str, params: dict = None, signed: bool = True) -> dict:
        return self._request("GET", path, params or {}, signed)

    def _post(self, path: str, params: dict, signed: bool = True) -> dict:
        return self._request("POST", path, params, signed)

    def _delete(self, path: str, params: dict, signed: bool = True) -> dict:
        return self._request("DELETE", path, params, signed)

    # ── 账户信息 ─────────────────────────────────

    def get_balance(self) -> float:
        """返回USDT余额"""
        data = self._get("/fapi/v2/balance")
        for item in data:
            if item.get("asset") == "USDT":
                return float(item.get("availableBalance", 0))
        return 0.0

    def get_positions(self) -> list:
        """返回当前持仓列表（非零仓位）"""
        data = self._get("/fapi/v2/positionRisk")
        return [p for p in data if float(p.get("positionAmt", 0)) != 0]

    def get_open_orders(self, symbol: str) -> list:
        return self._get("/fapi/v1/openOrders", {"symbol": symbol})

    def get_symbol_info(self, symbol: str) -> dict:
        """获取交易对精度信息"""
        data = self._get("/fapi/v1/exchangeInfo", signed=False)
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                return s
        return {}

    def _get_qty_precision(self, symbol: str) -> int:
        """获取数量精度"""
        info = self.get_symbol_info(symbol)
        for f in info.get("filters", []):
            if f["filterType"] == "LOT_SIZE":
                step = f["stepSize"]
                if "." in step:
                    return len(step.rstrip("0").split(".")[1])
                return 0
        return 3

    def _get_price_precision(self, symbol: str) -> int:
        info = self.get_symbol_info(symbol)
        return info.get("pricePrecision", 2)

    # ── 开仓 ──────────────────────────────────────

    def open_position(
        self,
        symbol: str,
        direction: str,
        quantity: float,
        sl_price: float,
        tp_price: float,
    ) -> Optional[Position]:
        """
        市价开仓 + 同时挂SL/TP条件单
        direction: "LONG" / "SHORT"
        返回 Position 对象
        """
        side = "BUY" if direction == "LONG" else "SELL"
        pos_side = "LONG" if direction == "LONG" else "SHORT"  # 双向持仓模式
        qty_precision = self._get_qty_precision(symbol)
        qty_str = f"{quantity:.{qty_precision}f}"
        price_precision = self._get_price_precision(symbol)

        logger.info(f"[Exec] 开仓: {direction} {symbol} qty={qty_str} SL={sl_price} TP={tp_price}")

        # 1. 市价开仓
        try:
            order = self._post("/fapi/v1/order", {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": qty_str,
                "positionSide": pos_side,
            })
            entry_price = float(order.get("avgPrice", 0)) or float(order.get("price", 0))
            open_time = int(order.get("updateTime", int(time.time() * 1000)))
            logger.info(f"[Exec] 开仓成功: orderId={order.get('orderId')} avgPrice={entry_price}")
        except Exception as e:
            logger.error(f"[Exec] 开仓失败: {e}")
            return None

        # 2. 止损单 STOP_MARKET
        sl_order_id = None
        sl_side = "SELL" if direction == "LONG" else "BUY"
        try:
            sl_order = self._post("/fapi/v1/order", {
                "symbol": symbol,
                "side": sl_side,
                "type": "STOP_MARKET",
                "stopPrice": f"{sl_price:.{price_precision}f}",
                "quantity": qty_str,
                "positionSide": pos_side,
                "timeInForce": "GTE_GTC",
                "workingType": "MARK_PRICE",
                "priceProtect": "TRUE",
            })
            sl_order_id = str(sl_order.get("orderId", ""))
            logger.info(f"[Exec] 止损单挂载: orderId={sl_order_id} stopPrice={sl_price}")
        except Exception as e:
            logger.error(f"[Exec] 止损单挂载失败: {e}")

        # 3. 止盈单 TAKE_PROFIT_MARKET
        tp_order_id = None
        try:
            tp_order = self._post("/fapi/v1/order", {
                "symbol": symbol,
                "side": sl_side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": f"{tp_price:.{price_precision}f}",
                "quantity": qty_str,
                "positionSide": pos_side,
                "timeInForce": "GTE_GTC",
                "workingType": "MARK_PRICE",
                "priceProtect": "TRUE",
            })
            tp_order_id = str(tp_order.get("orderId", ""))
            logger.info(f"[Exec] 止盈单挂载: orderId={tp_order_id} stopPrice={tp_price}")
        except Exception as e:
            logger.error(f"[Exec] 止盈单挂载失败: {e}")

        return Position(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            quantity=quantity,
            sl_price=sl_price,
            tp_price=tp_price,
            sl_order_id=sl_order_id,
            tp_order_id=tp_order_id,
            open_time=open_time,
        )

    # ── 平仓 ─────────────────────────────────────

    def close_position(self, position: Position) -> bool:
        """市价强制平仓（紧急使用，正常由SL/TP条件单触发）"""
        side = "SELL" if position.direction == "LONG" else "BUY"
        pos_side = position.direction
        qty_precision = self._get_qty_precision(position.symbol)
        qty_str = f"{position.quantity:.{qty_precision}f}"

        try:
            self._post("/fapi/v1/order", {
                "symbol": position.symbol,
                "side": side,
                "type": "MARKET",
                "quantity": qty_str,
                "positionSide": pos_side,
                "reduceOnly": "true",
            })
            logger.info(f"[Exec] 强制平仓: {position.direction} {position.symbol}")
            return True
        except Exception as e:
            logger.error(f"[Exec] 平仓失败: {e}")
            return False

    def cancel_all_orders(self, symbol: str) -> bool:
        """取消某品种所有挂单"""
        try:
            self._delete("/fapi/v1/allOpenOrders", {"symbol": symbol})
            logger.info(f"[Exec] 已取消 {symbol} 所有挂单")
            return True
        except Exception as e:
            logger.error(f"[Exec] 取消挂单失败: {e}")
            return False

    def check_order_status(self, symbol: str, order_id: str) -> str:
        """
        返回订单状态: NEW / FILLED / CANCELED / EXPIRED / ...
        """
        try:
            data = self._get("/fapi/v1/order", {"symbol": symbol, "orderId": int(order_id)})
            return data.get("status", "UNKNOWN")
        except Exception as e:
            logger.error(f"[Exec] 查询订单状态失败: {e}")
            return "UNKNOWN"

    # ── 断线续单：启动恢复 ────────────────────────

    def recover_positions(self, symbol: str) -> Optional[Position]:
        """
        系统重启时检查是否有未平仓位，恢复 Position 对象
        """
        try:
            positions = self.get_positions()
            for p in positions:
                if p["symbol"] == symbol:
                    amt = float(p["positionAmt"])
                    if amt == 0:
                        continue
                    direction = "LONG" if amt > 0 else "SHORT"
                    entry = float(p.get("entryPrice", 0))
                    qty = abs(amt)
                    logger.info(f"[Exec] 恢复持仓: {direction} {symbol} qty={qty} entry={entry}")

                    # 查找对应的SL/TP订单
                    open_orders = self.get_open_orders(symbol)
                    sl_id = tp_id = None
                    for o in open_orders:
                        if o.get("type") == "STOP_MARKET":
                            sl_id = str(o["orderId"])
                        elif o.get("type") == "TAKE_PROFIT_MARKET":
                            tp_id = str(o["orderId"])

                    return Position(
                        symbol=symbol, direction=direction,
                        entry_price=entry, quantity=qty,
                        sl_price=float(p.get("liquidationPrice", entry * 0.95)),
                        tp_price=0.0,
                        sl_order_id=sl_id, tp_order_id=tp_id,
                        open_time=int(time.time() * 1000),
                    )
        except Exception as e:
            logger.error(f"[Exec] 恢复持仓失败: {e}")
        return None


if __name__ == "__main__":
    # 连接测试（不下单）
    logging.basicConfig(level=logging.INFO)
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # 读取配置
    cfg = json.load(open(Path(__file__).parent.parent / "config" / "strategy_v12.json"))
    # 使用测试网
    TESTNET_KEY = "Viubn6nQeiIIo5s2JMjtzvsH4GiSV32LZzyChHnSsIQuAAJgFUFvtcSwMlQhiIMU"
    TESTNET_SECRET = "c56EysrokO9u8G82bXQp3h0sgx93tYDJowcQGEQ3rr84gefIa8GwZkPk0PBCNsFJ"

    exec_engine = BinanceExecutor(TESTNET_KEY, TESTNET_SECRET, testnet=True)
    try:
        bal = exec_engine.get_balance()
        print(f"✅ 测试网连接成功，USDT余额: {bal:.2f}U")
        positions = exec_engine.get_positions()
        print(f"当前持仓: {len(positions)}个")
        for p in positions:
            print(f"  {p['symbol']}: amt={p['positionAmt']} entry={p['entryPrice']}")
    except Exception as e:
        print(f"❌ 连接失败: {e}")
