# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
Binance Testnet REST API 客户端 - Phase 5 P0
封装 Binance Testnet REST API 接口，提供行情数据获取和模拟交易功能
"""

import os
import time
import hmac
import hashlib
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("binance_testnet")
except ImportError:
    import logging
    logger = logging.getLogger("binance_testnet")


class BinanceTestnetClient:
    """Binance Testnet REST API 客户端"""

    # Binance Testnet 基础 URL
    BASE_URL = "https://testnet.binance.vision"
    API_KEY_ENV = "BINANCE_TESTNET_API_KEY"
    SECRET_KEY_ENV = "BINANCE_TESTNET_SECRET_KEY"

    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None):
        """
        初始化客户端

        Args:
            api_key: API 密钥（可选，从环境变量读取）
            secret_key: 密钥（可选，从环境变量读取）
        """
        self.api_key = api_key or os.environ.get(self.API_KEY_ENV)
        self.secret_key = secret_key or os.environ.get(self.SECRET_KEY_ENV)

        if not self.api_key:
            logger.warning(f"未提供 API 密钥，仅支持公开接口（从环境变量 {self.API_KEY_ENV} 读取）")
        if not self.secret_key:
            logger.warning(f"未提供密钥，仅支持公开接口（从环境变量 {self.SECRET_KEY_ENV} 读取）")

        self.session = requests.Session()
        self.session.headers.update({
            'X-MBX-APIKEY': self.api_key if self.api_key else ''
        })

    def _generate_signature(self, params: Dict) -> str:
        """生成请求签名"""
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        return hmac.new(
            self.secret_key.encode('utf-8') if self.secret_key else b'',
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _request(self, method: str, endpoint: str, params: Optional[Dict] = None,
                 signed: bool = False) -> Dict:
        """
        发送 HTTP 请求

        Args:
            method: HTTP 方法（GET/POST）
            endpoint: API 端点
            params: 请求参数
            signed: 是否需要签名

        Returns:
            响应数据
        """
        try:
            # 第一层防御：参数校验
            if params is None:
                params = {}

            # 添加时间戳
            if signed:
                params['timestamp'] = int(time.time() * 1000)
                params['signature'] = self._generate_signature(params)

            url = f"{self.BASE_URL}{endpoint}"

            # 第二层防御：请求异常处理
            if method == 'GET':
                response = self.session.get(url, params=params, timeout=10)
            else:
                response = self.session.post(url, data=params, timeout=10)

            response.raise_for_status()

            return response.json()

        except requests.exceptions.Timeout as e:
            logger.error(f"请求超时: {endpoint} - {e}")
            return {'error': 'timeout', 'message': str(e)}
        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {endpoint} - {e}")
            return {'error': 'request_error', 'message': str(e)}
        except Exception as e:
            logger.error(f"未知错误: {endpoint} - {e}")
            return {'error': 'unknown', 'message': str(e)}

    # 公开接口（无需签名）

    def get_server_time(self) -> Dict:
        """获取服务器时间"""
        return self._request('GET', '/api/v3/time')

    def get_exchange_info(self) -> Dict:
        """获取交易规则和交易对信息"""
        return self._request('GET', '/api/v3/exchangeInfo')

    def get_klines(self, symbol: str, interval: str = '1h', limit: int = 100) -> List:
        """
        获取 K 线数据

        Args:
            symbol: 交易对（如 BTCUSDT）
            interval: K 线间隔（1m/5m/15m/1h/4h/1d）
            limit: 数量限制（1-1000）

        Returns:
            K 线数据列表 [[开盘时间, 开盘价, 最高价, 最低价, 收盘价, 成交量, ...], ...]
        """
        try:
            params = {
                'symbol': symbol.upper(),
                'interval': interval,
                'limit': limit
            }

            response = self._request('GET', '/api/v3/klines', params=params)

            if 'error' in response:
                logger.error(f"获取K线失败: {response}")
                return []

            return response

        except Exception as e:
            logger.error(f"获取K线异常: {e}")
            return []

    def get_ticker_price(self, symbol: Optional[str] = None) -> Dict:
        """获取最新价格"""
        params = {}
        if symbol:
            params['symbol'] = symbol.upper()

        return self._request('GET', '/api/v3/ticker/price', params=params)

    def get_order_book(self, symbol: str, limit: int = 100) -> Dict:
        """获取深度信息"""
        params = {
            'symbol': symbol.upper(),
            'limit': limit
        }

        return self._request('GET', '/api/v3/depth', params=params)

    # 交易接口（需要签名）

    def create_order(self, symbol: str, side: str, order_type: str,
                    quantity: float, price: Optional[float] = None,
                    time_in_force: str = 'GTC') -> Dict:
        """
        创建订单

        Args:
            symbol: 交易对
            side: 买卖方向（BUY/SELL）
            order_type: 订单类型（MARKET/LIMIT）
            quantity: 数量
            price: 价格（LIMIT订单必需）
            time_in_force: 有效期（GTC/IOC/FOK）

        Returns:
            订单信息
        """
        try:
            # 第一层防御：参数校验
            if not self.api_key or not self.secret_key:
                logger.error("未提供 API 密钥，无法创建订单")
                return {'error': 'no_credentials'}

            side = side.upper()
            if side not in ['BUY', 'SELL']:
                logger.error(f"无效的买卖方向: {side}")
                return {'error': 'invalid_side'}

            order_type = order_type.upper()
            if order_type not in ['MARKET', 'LIMIT']:
                logger.error(f"无效的订单类型: {order_type}")
                return {'error': 'invalid_type'}

            if quantity <= 0:
                logger.error(f"无效的数量: {quantity}")
                return {'error': 'invalid_quantity'}

            # 第二层防御：除零保护
            if quantity == 0 or np.isinf(quantity) or np.isnan(quantity):
                logger.error(f"数量异常: {quantity}")
                return {'error': 'invalid_quantity'}

            params = {
                'symbol': symbol.upper(),
                'side': side,
                'type': order_type,
                'quantity': f'{quantity:.6f}',
                'timeInForce': time_in_force
            }

            if order_type == 'LIMIT':
                if price is None:
                    logger.error("LIMIT 订单必须提供价格")
                    return {'error': 'price_required'}
                params['price'] = f'{price:.2f}'

            # 第三层防御：异常兜底
            response = self._request('POST', '/api/v3/order', params=params, signed=True)

            if 'error' in response:
                logger.error(f"创建订单失败: {response}")
                return response

            logger.info(f"订单创建成功: {response.get('orderId', 'N/A')}")

            return response

        except Exception as e:
            logger.error(f"创建订单异常: {e}")
            return {'error': 'exception', 'message': str(e)}

    def cancel_order(self, symbol: str, order_id: Optional[int] = None,
                     orig_client_order_id: Optional[str] = None) -> Dict:
        """撤销订单"""
        try:
            if not self.api_key or not self.secret_key:
                logger.error("未提供 API 密钥，无法撤销订单")
                return {'error': 'no_credentials'}

            params = {'symbol': symbol.upper()}

            if order_id:
                params['orderId'] = order_id
            elif orig_client_order_id:
                params['origClientOrderId'] = orig_client_order_id
            else:
                logger.error("必须提供 orderId 或 origClientOrderId")
                return {'error': 'no_order_id'}

            response = self._request('DELETE', '/api/v3/order', params=params, signed=True)

            if 'error' in response:
                logger.error(f"撤销订单失败: {response}")
                return response

            logger.info(f"订单撤销成功: {response.get('orderId', 'N/A')}")

            return response

        except Exception as e:
            logger.error(f"撤销订单异常: {e}")
            return {'error': 'exception', 'message': str(e)}

    def get_account(self) -> Dict:
        """获取账户信息"""
        try:
            if not self.api_key or not self.secret_key:
                logger.error("未提供 API 密钥，无法获取账户信息")
                return {'error': 'no_credentials'}

            response = self._request('GET', '/api/v3/account', signed=True)

            if 'error' in response:
                logger.error(f"获取账户信息失败: {response}")
                return response

            return response

        except Exception as e:
            logger.error(f"获取账户信息异常: {e}")
            return {'error': 'exception', 'message': str(e)}


# 导入 numpy 用于数值校验
try:
    import numpy as np
except ImportError:
    np = None


def test_connection():
    """测试连接"""
    try:
        client = BinanceTestnetClient()

        # 测试获取服务器时间
        server_time = client.get_server_time()
        if 'serverTime' in server_time:
            logger.info(f"✅ 连接成功，服务器时间: {datetime.fromtimestamp(server_time['serverTime']/1000)}")
            return True
        else:
            logger.error(f"❌ 连接失败: {server_time}")
            return False

    except Exception as e:
        logger.error(f"测试连接异常: {e}")
        return False


if __name__ == "__main__":
    # 测试连接
    if test_connection():
        print("Binance Testnet 连接测试成功")
    else:
        print("Binance Testnet 连接测试失败")
