#!/usr/bin/env python3
"""
data_fetcher.py — 杀手锏交易系统统一数据管道
=======================================================
功能:
  1. Gate.io 实时数据获取 (支持历史分页)
  2. Binance Vision CSV 下载 (历史数据)
  3. 本地 JSON 数据加载与格式转换
  4. 多数据源交叉验证

支持品种: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT
支持周期: 1H (默认), 4H, 1D

使用示例:
  python3 scripts/data_fetcher.py --symbol BTCUSDT --interval 1h --days 365 --source gateio
  python3 scripts/data_fetcher.py --symbol BTCUSDT --interval 1h --source binance_vision
  python3 scripts/data_fetcher.py --symbol BTCUSDT --interval 1h --days 90 --verify
  python3 scripts/data_fetcher.py --all --interval 1h --days 205
"""

import argparse
import datetime
import json
import math
import os
import sys
import time
import zipfile
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import pandas as pd

# Gate.io <-> symbol mapping
GATEIO_SYMBOLS = {
    'BTCUSDT': 'BTC_USDT', 'ETHUSDT': 'ETH_USDT',
    'SOLUSDT': 'SOL_USDT', 'BNBUSDT': 'BNB_USDT',
    'XRPUSDT': 'XRP_USDT', 'DOGEUSDT': 'DOGE_USDT',
}

# Binance kline column names
BINANCE_COLS = ['ts', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_vol', 'n_trades',
                'taker_buy_vol', 'taker_buy_quote_vol', 'ignore']


# ---------------------------------------------------------------------------
# Gate.io data fetcher
# ---------------------------------------------------------------------------
def fetch_gateio(symbol: str, interval: str = '1h', days: int = 205,
                 batch_days: int = 41, max_batches: int = 5) -> list:
    """
    Fetch historical klines from Gate.io API with proper pagination.

    Gate.io limitations:
      - Max 1000 candles per request (~41 days at 1H)
      - from/to must span at most 1000 candles
      - Data returned in ASCENDING order (oldest first)
    """
    gate_sym = GATEIO_SYMBOLS.get(symbol, symbol.replace('USDT', '_USDT'))
    url = 'https://api.gateio.ws/api/v4/spot/candlesticks'
    interval_map = {'1h': '1h', '4h': '4h', '1d': '1d'}
    gate_interval = interval_map.get(interval, '1h')

    candles = []
    end_ts = int(time.time())
    batch_count = min(max_batches, math.ceil(days / batch_days))

    print(f'[Gate.io] Fetching {symbol} {interval} x {days} days ({batch_count} batches)')

    for i in range(batch_count):
        start_ts = end_ts - batch_days * 86400
        if start_ts < 0:
            start_ts = 1

        params = {
            'currency_pair': gate_sym,
            'interval': gate_interval,
            'limit': 1000,
            'from': start_ts,
            'to': end_ts,
        }

        try:
            r = requests.get(url, params=params, timeout=15)
            batch = r.json()

            if not isinstance(batch, list):
                label = batch.get('label', 'UNKNOWN')
                msg = batch.get('message', '')
                print(f'  Batch {i}: Error {label} — {msg}')
                if label == 'INVALID_PARAM_VALUE' and 'too broad' in msg:
                    # Reduce batch size
                    batch_days = 30
                    end_ts = end_ts + batch_days * 86400  # Retry same range
                    time.sleep(0.5)
                    continue
                break

            if not batch:
                print(f'  Batch {i}: Empty')
                break

            for c in batch:
                try:
                    ts_sec = int(c[0])
                    o = float(c[2])
                    cc = float(c[3])
                    h = float(c[4])
                    l = float(c[5])
                    v = float(c[6])
                    # Fix high < low data quality issues
                    h = max(o, cc, h, l)
                    l = min(o, cc, h, l)
                    candles.append({
                        'timestamp': ts_sec * 1000,
                        'datetime': datetime.datetime.utcfromtimestamp(ts_sec).strftime('%Y-%m-%d %H:%M:%S'),
                        'open': o, 'close': cc,
                        'high': h, 'low': l,
                        'volume': v,
                    })
                except (ValueError, IndexError):
                    continue

            # Next batch: from oldest_ts - 1 second
            oldest_ts = int(batch[0][0])
            end_ts = oldest_ts - 3600
            print(f'  Batch {i}: {len(batch)} candles, oldest={batch[0][0]}, total={len(candles)}')

            if i < batch_count - 1:
                time.sleep(0.3)

        except requests.RequestException as e:
            print(f'  Batch {i}: Network error: {e}')
            break

    # Sort ascending, deduplicate
    candles.sort(key=lambda x: x['timestamp'])
    seen = set()
    deduped = [c for c in candles if c['timestamp'] not in seen and not seen.add(c['timestamp'])]

    print(f'[Gate.io] Total: {len(deduped)} candles ({len(deduped)/24:.0f} days)')
    return deduped


# ---------------------------------------------------------------------------
# Huobi (火币) kline fetcher
# ---------------------------------------------------------------------------
def fetch_huobi(symbol: str, interval: str = '1h', days: int = 365) -> list:
    """Huobi Pro API. Max 2000 candles/request (~83 days 1H). Period: 1h->60min."""
    period_map = {'1h': '60min', '4h': '4hour', '1d': '1day'}
    interval_hb = period_map.get(interval, '60min')
    sym_hb = symbol.lower().replace('USDT', 'usdt')

    all_candles = []
    end_ts = int(time.time())

    for i in range((days // 83) + 2):
        start_ts = end_ts - 83 * 86400
        if start_ts < 0: start_ts = 1

        params = {'symbol': sym_hb, 'period': interval_hb, 'size': 2000, 'from': start_ts, 'to': end_ts}
        try:
            r = requests.get('https://api.huobi.pro/market/history/kline', params=params, timeout=15)
            data = r.json()
        except Exception as e:
            print(f'[Huobi] Request error: {e}'); break

        batch = data.get('data', []) if data.get('status') == 'ok' else []
        if not batch: break

        for item in batch:
            try:
                ts_sec = int(item['id'])
                all_candles.append({'timestamp': ts_sec * 1000,
                    'datetime': datetime.datetime.utcfromtimestamp(ts_sec).strftime('%Y-%m-%d %H:%M:%S'),
                    'open': float(item['open']), 'close': float(item['close']),
                    'high': float(item['high']), 'low': float(item['low']),
                    'volume': float(item['vol'])})
            except (KeyError, ValueError): continue

        end_ts = int(batch[0]['id']) - 1
        print(f'[Huobi] Batch {i}: {len(batch)} candles')
        if i < (days // 83) + 1: time.sleep(0.3)
        if len(batch) < 1990: break

    seen = set()
    deduped = [c for c in sorted(all_candles, key=lambda x: x['timestamp'])
               if c['timestamp'] not in seen and not seen.add(c['timestamp'])]
    print(f'[Huobi] Total: {len(deduped)} candles ({len(deduped)/24:.0f} days)')
    return deduped


# ---------------------------------------------------------------------------
# CoinEx kline fetcher
# ---------------------------------------------------------------------------
def fetch_coinex(symbol: str, interval: str = '1h', days: int = 365) -> list:
    """CoinEx API. Max 1000 candles/request (~41 days 1H). Period: 1h->1hour."""
    interval_map = {'1h': '1hour', '4h': '4hour', '1d': '1day'}
    interval_ce = interval_map.get(interval, '1hour')

    all_candles = []
    for i in range((days // 41) + 2):
        params = {'market': symbol, 'type': interval_ce, 'limit': 1000}
        try:
            r = requests.get('https://api.coinex.com/v1/market/kline', params=params, timeout=15)
            data = r.json()
        except Exception as e:
            print(f'[CoinEx] Request error: {e}'); break

        if data.get('code') != 0: break
        batch = data['data']
        if not batch: break

        for item in batch:
            try:
                ts_sec = int(item[0])
                all_candles.append({'timestamp': ts_sec * 1000,
                    'datetime': datetime.datetime.utcfromtimestamp(ts_sec).strftime('%Y-%m-%d %H:%M:%S'),
                    'open': float(item[1]), 'close': float(item[2]),
                    'high': float(item[3]), 'low': float(item[4]),
                    'volume': float(item[5])})
            except (ValueError, IndexError): continue

        print(f'[CoinEx] Batch {i}: {len(batch)} candles')
        if i < (days // 41) + 1: time.sleep(0.3)
        if len(batch) < 990: break

    seen = set()
    deduped = [c for c in sorted(all_candles, key=lambda x: x['timestamp'])
               if c['timestamp'] not in seen and not seen.add(c['timestamp'])]
    print(f'[CoinEx] Total: {len(deduped)} candles ({len(deduped)/24:.0f} days)')
    return deduped


# ---------------------------------------------------------------------------
# Binance Vision CSV fetcher
# ---------------------------------------------------------------------------
def fetch_binance_vision(symbol: str, interval: str = '1h', days: int = 90) -> list:
    """
    Download historical klines from Binance Vision CSV archives.
    URL: https://data.binance.vision/data/spot/daily/klines/{symbol}/1h/{symbol}-1h-{date}.zip

    Notes:
      - Timestamps in CSV are in MILLISECONDS
      - Each day = 1440 minutes / 60 = 24 files at 1H
      - Slow: ~5 minutes for 90 days with 10 workers
    """
    interval_map = {'1h': '1h', '4h': '4h', '1d': '1d'}
    bin_interval = interval_map.get(interval, '1h')

    now = datetime.datetime.utcnow()
    dates = []
    current = now - datetime.timedelta(days=days)
    while current <= now:
        dates.append(current.strftime('%Y-%m-%d'))
        current += datetime.timedelta(days=1)

    print(f'[Binance Vision] {symbol} {interval} x {days} days = {len(dates)} files')

    # Group into weekly batches for parallel download
    batches = [dates[i:i+7] for i in range(0, len(dates), 7)]
    all_rows = []
    seen = set()

    for batch_idx, batch_dates in enumerate(batches):
        urls = []
        for date in batch_dates:
            fname = f'{symbol}-{bin_interval}-{date}.zip'
            url = f'https://data.binance.vision/data/spot/daily/klines/{symbol}/{bin_interval}/{fname}'
            urls.append((url, date))

        def download_one(url_date_tuple):
            url, date = url_date_tuple
            try:
                r = requests.get(url, timeout=60)
                if r.status_code != 200:
                    return []
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    csv_name = url.split('/')[-1].replace('.zip', '.csv')
                    if csv_name not in z.namelist():
                        return []
                    with z.open(csv_name) as f:
                        lines = f.read().decode('utf-8').strip().split('\n')
                        rows = []
                        for line in lines:
                            parts = line.split(',')
                            if len(parts) < 6:
                                continue
                            try:
                                ts_sec = int(parts[0]) // 1000  # ms -> sec
                                rows.append({
                                    'timestamp': int(parts[0]),
                                    'datetime': datetime.datetime.utcfromtimestamp(ts_sec).strftime('%Y-%m-%d %H:%M:%S'),
                                    'open': float(parts[1]),
                                    'high': float(parts[2]),
                                    'low': float(parts[3]),
                                    'close': float(parts[4]),
                                    'volume': float(parts[5]),
                                })
                            except (ValueError, IndexError):
                                continue
                        return rows
            except Exception:
                return []

        print(f'  Batch {batch_idx+1}/{len(batches)}: downloading {len(urls)} files...')
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(download_one, u): u for u in urls}
            for future in as_completed(futures):
                rows = future.result()
                for r in rows:
                    if r['timestamp'] not in seen:
                        seen.add(r['timestamp'])
                        all_rows.append(r)

        time.sleep(0.5)

    all_rows.sort(key=lambda x: x['timestamp'])
    print(f'[Binance Vision] Total: {len(all_rows)} candles ({len(all_rows)/24:.0f} days)')
    return all_rows


# ---------------------------------------------------------------------------
# Local data loader
# ---------------------------------------------------------------------------
def load_local(symbol: str, prefer_source: str = None) -> list:
    """
    Load local JSON data. Supports multiple format variants.
    Returns list of candle dicts.
    """
    data_dir = Path('data')
    candidates = []

    # Priority: prefer_source > specific name > generic patterns
    if prefer_source == 'gate':
        candidates = list(data_dir.glob(f'{symbol}_gate*.json'))
    elif prefer_source == 'binance':
        candidates = list(data_dir.glob(f'{symbol}*binance*.json'))
    elif prefer_source == 'local':
        candidates = list(data_dir.glob(f'{symbol}_1h*.json'))
    else:
        candidates = list(data_dir.glob(f'{symbol}*.json'))

    for fpath in candidates:
        try:
            with open(fpath) as f:
                raw = json.load(f)

            if not raw:
                continue

            # Determine format
            first = raw[0]
            if isinstance(first, list):
                # Gate.io/Binance raw format
                return _normalize_list_format(raw, symbol)
            elif isinstance(first, dict):
                cols = list(first.keys())
                # Standard format: timestamp + OHLCV
                if 'timestamp' in cols or 'ts' in cols:
                    return _normalize_dict_format(raw)
                # East money format: c/o/h/l/v
                if 'c' in cols and 'o' in cols and 'h' in cols:
                    return _normalize_eastmoney_format(raw)

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f'    Failed to load {fpath}: {e}')
            continue

    print(f'[Local] No valid data found for {symbol}')
    return []


def _normalize_list_format(raw: list, symbol: str) -> list:
    """Normalize list-of-lists format (Gate.io / Binance)."""
    candles = []
    for item in raw:
        try:
            if len(item) < 6:
                continue
            ts_raw = item[0]
            if isinstance(ts_raw, str):
                ts_raw = int(ts_raw)
            # Handle nanoseconds (Binance Vision sometimes)
            if ts_raw > 1e12:
                ts_sec = ts_raw // 1000 if ts_raw > 1e15 else ts_raw // 1000
            else:
                ts_sec = ts_raw

            if ts_sec > 1e12:  # milliseconds
                ts_ms = ts_sec
            elif ts_sec > 1e9:  # seconds
                ts_ms = ts_sec * 1000
            else:  # already ms
                ts_ms = ts_sec

            o = float(item[2]) if len(item) > 2 else float(item[1])
            cc = float(item[3]) if len(item) > 3 else float(item[4])
            h = float(item[4]) if len(item) > 4 else max(o, cc)
            l = float(item[5]) if len(item) > 5 else min(o, cc)
            v = float(item[6]) if len(item) > 6 else 0.0

            h = max(o, cc, h, l)
            l = min(o, cc, h, l)

            candles.append({
                'timestamp': ts_ms,
                'datetime': datetime.datetime.utcfromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                'open': o, 'close': cc, 'high': h, 'low': l, 'volume': v,
            })
        except (ValueError, IndexError):
            continue
    candles.sort(key=lambda x: x['timestamp'])
    seen = set()
    return [c for c in candles if c['timestamp'] not in seen and not seen.add(c['timestamp'])]


def _normalize_dict_format(raw: list) -> list:
    """Normalize list-of-dicts with timestamp key."""
    candles = []
    for item in raw:
        try:
            ts = item.get('timestamp') or item.get('ts')
            if ts is None:
                continue
            if isinstance(ts, str):
                ts = int(ts)
            if ts > 1e12:
                ts_ms = ts
            elif ts > 1e9:
                ts_ms = ts * 1000
            else:
                ts_ms = ts

            o = float(item.get('open', item.get('o', 0)))
            cc = float(item.get('close', item.get('c', 0)))
            h = float(item.get('high', item.get('h', max(o, cc))))
            l = float(item.get('low', item.get('l', min(o, cc))))
            v = float(item.get('volume', item.get('v', 0)))

            h = max(o, cc, h, l)
            l = min(o, cc, h, l)

            candles.append({
                'timestamp': ts_ms,
                'datetime': datetime.datetime.utcfromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                'open': o, 'close': cc, 'high': h, 'low': l, 'volume': v,
            })
        except (ValueError, KeyError, IndexError):
            continue
    candles.sort(key=lambda x: x['timestamp'])
    seen = set()
    return [c for c in candles if c['timestamp'] not in seen and not seen.add(c['timestamp'])]


def _normalize_eastmoney_format(raw: list) -> list:
    """Normalize East Money format: {c, o, h, l, v, ts}."""
    candles = []
    for item in raw:
        try:
            ts = item.get('ts') or item.get('timestamp')
            if ts is None:
                continue
            ts_ms = int(ts) if isinstance(ts, (int, float)) else int(ts)
            if ts_ms > 1e12:
                ts_ms = ts_ms
            elif ts_ms > 1e9:
                ts_ms = ts_ms * 1000

            o = float(item['o']); cc = float(item['c'])
            h = float(item['h']); l = float(item['l']); v = float(item['v'])
            h = max(o, cc, h, l); l = min(o, cc, h, l)

            candles.append({
                'timestamp': ts_ms,
                'datetime': datetime.datetime.utcfromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                'open': o, 'close': cc, 'high': h, 'low': l, 'volume': v,
            })
        except (ValueError, KeyError):
            continue
    candles.sort(key=lambda x: x['timestamp'])
    seen = set()
    return [c for c in candles if c['timestamp'] not in seen and not seen.add(c['timestamp'])]


# ---------------------------------------------------------------------------
# Data verification
# ---------------------------------------------------------------------------
def verify_data(candles: list, symbol: str) -> dict:
    """Verify data quality and return statistics."""
    if not candles:
        return {'status': 'EMPTY', 'n': 0}

    df = pd.DataFrame(candles)
    high_low_errors = (df['high'] < df['low']).sum()
    zero_volume = (df['volume'] <= 0).sum()
    missing_ohlc = df[['open', 'high', 'low', 'close']].isna().sum().to_dict()

    # Check for duplicates
    dup_ts = df['timestamp'].duplicated().sum()

    # Check for time gaps (> 2 hours at 1H)
    df = df.sort_values('timestamp')
    time_diffs = df['timestamp'].diff()
    gaps = (time_diffs > 2 * 3600 * 1000).sum()

    atr = _compute_atr(df)
    atr_valid = (~atr.isna()).sum()
    atr_pct_mean = (atr / df['close'] * 100).dropna().mean()

    return {
        'status': 'OK' if high_low_errors == 0 else 'HAS_ERRORS',
        'n': len(candles),
        'days': len(candles) / 24,
        'high_low_errors': int(high_low_errors),
        'duplicate_timestamps': int(dup_ts),
        'time_gaps': int(gaps),
        'zero_volume': int(zero_volume),
        'missing_ohlc': missing_ohlc,
        'atr_valid_pct': f'{atr_valid / len(atr) * 100:.1f}%',
        'atr_pct_mean': f'{atr_pct_mean:.3f}%',
        'price_range': f'{df["close"].iloc[0]:.2f} -> {df["close"].iloc[-1]:.2f}',
        'date_range': f'{df["datetime"].iloc[0][:10]} -> {df["datetime"].iloc[-1][:10]}',
    }


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute ATR from OHLC data."""
    df = df.copy()
    df['tr_hl'] = df['high'] - df['low']
    df['tr_hc'] = (df['high'] - df['close'].shift(1)).abs()
    df['tr_lc'] = (df['low'] - df['close'].shift(1)).abs()
    df['tr'] = df[['tr_hl', 'tr_hc', 'tr_lc']].max(axis=1)
    return df['tr'].rolling(period).mean()


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description='统一数据获取工具')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='交易品种')
    parser.add_argument('--interval', type=str, default='1h', choices=['1h', '4h', '1d'], help='K线周期')
    parser.add_argument('--days', type=int, default=205, help='获取天数')
    parser.add_argument('--source', type=str, default='gateio',
                        choices=['gateio', 'huobi', 'coinex', 'binance_vision', 'local', 'auto'],
                        help='数据源: gateio/huobi/coinex(分页下载)|binance_vision(历史CSV)|local(本地JSON)|auto(优先本地)')
    parser.add_argument('--verify', action='store_true', help='验证数据质量')
    parser.add_argument('--output', type=str, default=None, help='输出文件路径')
    parser.add_argument('--all', action='store_true', help='下载所有品种')
    parser.add_argument('--symbols', type=str, default='BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT',
                        help='品种列表(逗号分隔)')
    parser.add_argument('--compare', action='store_true', help='对比所有数据源')

    args = parser.parse_args()

    symbols = args.symbols.split(',') if args.all else [args.symbol]

    print('=' * 70)
    print(f'数据管道 - {", ".join(symbols)} | {args.interval} | {args.days}天 | source={args.source}')
    print('=' * 70)

    for sym in symbols:
        print(f'\n--- {sym} ---')

        if args.source in ('gateio', 'auto'):
            candles = fetch_gateio(sym, args.interval, args.days)
            if candles:
                _save_and_verify(sym, candles, 'gateio', args.verify, args.output, args.days)
                if args.source == 'gateio':
                    continue

        if args.source == 'huobi':
            candles = fetch_huobi(sym, args.interval, args.days)
            if candles:
                _save_and_verify(sym, candles, 'huobi', args.verify, args.output, args.days)
            continue

        if args.source == 'coinex':
            candles = fetch_coinex(sym, args.interval, args.days)
            if candles:
                _save_and_verify(sym, candles, 'coinex', args.verify, args.output, args.days)
            continue

        if args.source in ('binance_vision', 'auto'):
            candles = fetch_binance_vision(sym, args.interval, args.days)
            if candles:
                _save_and_verify(sym, candles, 'binance_vision', args.verify, args.output, args.days)
                if args.source == 'binance_vision':
                    continue

        if args.source in ('local', 'auto'):
            local_data = load_local(sym)
            if local_data:
                print(f'[Local] Loaded {len(local_data)} candles from local files')
                _save_and_verify(sym, local_data, 'local', args.verify, args.output, args.days)
            elif args.source == 'local':
                print(f'[Local] No local data found for {sym}')

        if args.compare:
            _compare_sources(sym, args.days)


def _save_and_verify(sym: str, candles: list, source: str, verify: bool, output: str, days: int = 205):
    """Save data and optionally verify."""
    if not candles:
        return

    if output:
        fpath = Path(output)
    else:
        fpath = Path('data') / f'{sym}_{source}_{days}d.json'

    fpath.parent.mkdir(parents=True, exist_ok=True)

    with open(fpath, 'w') as f:
        json.dump(candles, f, separators=(',', ':'))

    print(f'  -> Saved: {fpath} ({len(candles)} candles)')

    if verify:
        stats = verify_data(candles, sym)
        print(f'  Verification:')
        for k, v in stats.items():
            print(f'    {k}: {v}')


def _compare_sources(sym: str, days: int):
    """Compare all available data sources for a symbol."""
    print(f'\n  [Compare] {sym} — all sources:')

    local_candles = load_local(sym)
    if local_candles:
        stats = verify_data(local_candles, sym)
        print(f'    Local:   {stats["n"]} candles, {stats["date_range"]}, {stats["status"]}, ATR%={stats["atr_pct_mean"]}')
    else:
        print(f'    Local:   No data')


if __name__ == '__main__':
    main()
