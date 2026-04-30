#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杀手锏交易系统 v5.2 - 期货数据获取器
数据源：东方财富API
支持品种：黄金(AU)/白银(AG)/原油(SC) + 扩展品种

整合自 strategy_v5_ultimate.py 的 MultiAssetDataFetcher
"""
import argparse
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
import logging

import time

try:
    import requests
except ImportError:
    requests = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("futures_data_fetcher")


# 期货品种配置
FUTURES_CONFIG = {
    'GOLD': {
        'name': '黄金',
        'code': 'AU2606',
        'market': '113',
        'multiplier': 1000,
        'margin_rate': 0.08,
        'tick_size': 0.02,
        'min_volume': 1,
        'session': 'night'
    },
    'SILVER': {
        'name': '白银',
        'code': 'AG2606',
        'market': '113',
        'multiplier': 15,
        'margin_rate': 0.07,
        'tick_size': 1,
        'min_volume': 1,
        'session': 'night'
    },
    'CRUDE_OIL': {
        'name': '原油',
        'code': 'SC2606',
        'market': '142',
        'multiplier': 1000,
        'margin_rate': 0.10,
        'tick_size': 0.1,
        'min_volume': 1,
        'session': 'night'
    },
    'COPPER': {
        'name': '铜',
        'code': 'CU2606',
        'market': '113',
        'multiplier': 5,
        'margin_rate': 0.09,
        'tick_size': 10,
        'min_volume': 1,
        'session': 'night'
    },
    'IRON_ORE': {
        'name': '铁矿石',
        'code': 'I2606',
        'market': '114',
        'multiplier': 100,
        'margin_rate': 0.10,
        'tick_size': 0.5,
        'min_volume': 1,
        'session': 'night'
    }
}


class FuturesDataFetcher:
    """东方财富期货数据获取器"""

    def __init__(self):
        self.version = "v5.2"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://quote.eastmoney.com'
        }
        self.base_url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def fetch_kline(self, symbol: str, period: str = '1d', count: int = 500) -> Optional[pd.DataFrame]:
        """
        获取期货K线数据

        参数:
        - symbol: 品种名(GOLD/SILVER/CRUDE_OIL等)或secid格式(113.AU2606)
        - period: 周期(1d/1h/4h)
        - count: 数量

        返回:
        - DataFrame(OHLCV) 或 None
        """
        if requests is None:
            logger.error("requests库未安装")
            return None

        secid = self._resolve_secid(symbol)
        if secid is None:
            return None

        klt = {'1d': '101', '1h': '60', '4h': '101', '15m': '15', '5m': '5'}.get(period, '101')
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58',
            'klt': klt, 'fqt': '0', 'end': '20500101', 'lmt': str(count)
        }

        for attempt in range(3):
            try:
                resp = requests.get(self.base_url, params=params, headers=self.headers, timeout=60)
                return self._process_response(resp.json(), symbol)
            except requests.exceptions.Timeout:
                logger.warning(f"请求超时: {symbol} (attempt {attempt+1}/3)")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1)); continue
            except Exception as e:
                logger.warning(f"数据获取失败: {symbol} - {e} (attempt {attempt+1}/3)")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1)); continue
                logger.error(f"数据获取最终失败: {symbol}")
            return None
        return None

    def _resolve_secid(self, symbol: str) -> Optional[str]:
        """解析品种代码为secid格式"""
        config = FUTURES_CONFIG.get(symbol)
        if config:
            return f"{config['market']}.{config['code']}"
        if '.' in symbol:
            return symbol
        logger.error(f"未知品种: {symbol}")
        return None

    def _process_response(self, data: Dict, symbol: str) -> Optional[pd.DataFrame]:
        """解析API响应并构建DataFrame"""
        if not data.get('data') or not data['data'].get('klines'):
            logger.warning(f"无数据返回: {symbol}")
            return None

        records = []
        for kline in data['data']['klines']:
            rec = self._parse_kline(kline)
            if rec:
                records.append(rec)

        if not records:
            return None

        df = pd.DataFrame(records)
        df.set_index('timestamp', inplace=True)
        if len(df) < 50:
            logger.warning(f"数据不足50条: {symbol}({len(df)}条)")
            return None

        logger.info(f"[OK] {symbol}: {len(df)}条数据, {df.index[0]} ~ {df.index[-1]}, "
                     f"价格范围 {df['close'].min():.2f} ~ {df['close'].max():.2f}")
        return df

    def _parse_kline(self, kline: str) -> Optional[Dict]:
        """解析单条K线数据"""
        try:
            parts = kline.split(',')
            if len(parts) < 6:
                return None
            o, c, h, l, v = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]), float(parts[5])
            if 0 < c < 100000 and h >= l and o > 0:
                return {'timestamp': pd.to_datetime(parts[0]), 'open': o, 'close': c, 'high': h, 'low': l, 'volume': v}
        except (ValueError, IndexError):
            pass
        return None

    def fetch_multiple(self, symbols: List[str] = None, period: str = '1d', count: int = 500) -> Dict[str, pd.DataFrame]:
        """批量获取多品种数据"""
        if symbols is None:
            symbols = list(FUTURES_CONFIG.keys())

        results = {}
        for symbol in symbols:
            df = self.fetch_kline(symbol, period, count)
            if df is not None:
                results[symbol] = df

        logger.info(f"[OK] 成功获取 {len(results)}/{len(symbols)} 个品种数据")
        return results

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """获取品种信息"""
        config = FUTURES_CONFIG.get(symbol)
        if config:
            return {
                'symbol': symbol,
                'name': config['name'],
                'code': config['code'],
                'market': config['market'],
                'multiplier': config['multiplier'],
                'margin_rate': config['margin_rate'],
                'tick_size': config['tick_size'],
                'min_volume': config['min_volume']
            }
        return None


class CryptoDataFetcher:
    """币安加密货币数据获取器（从strategy_v5_ultimate.py整合）"""

    def __init__(self):
        self.version = "v5.2"
        self.base_url = "https://api.binance.com/api/v3/klines"
        self.headers = {'User-Agent': 'Mozilla/5.0'}

    def fetch_kline(self, symbol: str = 'BTCUSDT', interval: str = '1h', limit: int = 500) -> Optional[pd.DataFrame]:
        """获取加密货币K线数据"""
        if requests is None:
            logger.error("requests库未安装")
            return None

        params = {'symbol': symbol, 'interval': interval, 'limit': limit}

        try:
            resp = requests.get(self.base_url, params=params, headers=self.headers, timeout=30)
            data = resp.json()

            if not data:
                return None

            records = []
            for item in data:
                records.append({
                    'timestamp': pd.to_datetime(item[0], unit='ms'),
                    'open': float(item[1]),
                    'high': float(item[2]),
                    'low': float(item[3]),
                    'close': float(item[4]),
                    'volume': float(item[5])
                })

            df = pd.DataFrame(records)
            df.set_index('timestamp', inplace=True)

            logger.info(f"[OK] {symbol}: {len(df)}条数据, "
                       f"{df.index[0]} ~ {df.index[-1]}")
            return df

        except Exception as e:
            logger.error(f"加密货币数据获取失败: {symbol} - {e}")
            return None


class UnifiedDataFetcher:
    """统一数据获取器 - 加密货币 + 期货"""

    CRYPTO_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT']
    FUTURES_SYMBOLS = list(FUTURES_CONFIG.keys())

    def __init__(self):
        self.crypto_fetcher = CryptoDataFetcher()
        self.futures_fetcher = FuturesDataFetcher()

    def fetch(self, symbol: str, period: str = '1d', count: int = 500) -> Optional[pd.DataFrame]:
        """
        统一获取接口

        自动判断品种类型并调用对应API
        """
        # 判断是加密货币还是期货
        if symbol.endswith('USDT') or symbol in self.CRYPTO_SYMBOLS:
            interval_map = {'1d': '1d', '1h': '1h', '4h': '4h', '15m': '15m', '5m': '5m'}
            interval = interval_map.get(period, '1h')
            return self.crypto_fetcher.fetch_kline(symbol, interval, count)
        else:
            return self.futures_fetcher.fetch_kline(symbol, period, count)

    def fetch_all(self, include_crypto: bool = True, include_futures: bool = True,
                  period: str = '1d', count: int = 500) -> Dict[str, pd.DataFrame]:
        """获取所有品种数据"""
        results = {}

        if include_crypto:
            for symbol in self.CRYPTO_SYMBOLS:
                interval_map = {'1d': '1d', '1h': '1h', '4h': '4h', '15m': '15m'}
                interval = interval_map.get(period, '1h')
                df = self.crypto_fetcher.fetch_kline(symbol, interval, count)
                if df is not None:
                    results[symbol] = df

        if include_futures:
            for symbol in self.FUTURES_SYMBOLS:
                df = self.futures_fetcher.fetch_kline(symbol, period, count)
                if df is not None:
                    results[symbol] = df

        logger.info(f"[OK] 共获取 {len(results)} 个品种数据")
        return results


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='期货/加密货币数据获取器')
    parser.add_argument('--symbol', type=str, default='GOLD', help='品种(GOLD/SILVER/CRUDE_OIL/BTCUSDT等)')
    parser.add_argument('--period', type=str, default='1d', help='周期(1d/1h/4h/15m)')
    parser.add_argument('--count', type=int, default=100, help='数据条数')
    parser.add_argument('--all', action='store_true', help='获取所有品种')
    args = parser.parse_args()

    fetcher = UnifiedDataFetcher()

    if args.all:
        results = fetcher.fetch_all(period=args.period, count=args.count)
        summary = {}
        for symbol, df in results.items():
            summary[symbol] = {
                'bars': len(df),
                'start': str(df.index[0]),
                'end': str(df.index[-1]),
                'price_range': f"{df['close'].min():.2f} ~ {df['close'].max():.2f}"
            }
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    else:
        df = fetcher.fetch(args.symbol, args.period, args.count)
        if df is not None:
            result = {
                'symbol': args.symbol,
                'bars': len(df),
                'start': str(df.index[0]),
                'end': str(df.index[-1]),
                'latest_close': float(df['close'].iloc[-1]),
                'price_range': f"{df['close'].min():.2f} ~ {df['close'].max():.2f}"
            }
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            print(json.dumps({'error': f'无法获取 {args.symbol} 数据'}, ensure_ascii=False))


if __name__ == "__main__":
    main()
