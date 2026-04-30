#!/usr/bin/env python3
"""
Real-Time Data Validator - P3 Strategy Live Verification
数据源优先级: Gate.io API (可访问) > 本地JSON文件 > Binance API (可能被阻断)
Gate.io数据自动修正 high<low 错误
"""

import argparse
import json
import time
import sys
import os
from datetime import datetime, timedelta
from collections import deque

import requests
import numpy as np
import pandas as pd

# 经 P3 验证的回测引擎（模块级导入）
import sys, os
if '/workspace/projects/trading-simulator' not in sys.path:
    sys.path.insert(0, '/workspace/projects/trading-simulator')
from scripts.optimizer_precious_metal import backtest_precious_metal, compute_indicators as ci


# ─────────────────────────────────────────────────────────────
# P3 策略核心逻辑（从 closed_loop_engine.py 移植，经 P3 修复）
# ─────────────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算所有技术指标"""
    df = df.copy()
    # 价格基础
    df['returns'] = df['close'].pct_change()
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1))

    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))

    # ATR
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['atr_pct'] = df['atr'] / df['close'] * 100  # ATR as % of price

    # EMA
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

    # EMA slope (标准化, per-bar)
    for span in [5, 10, 20]:
        col = f'ema{span}'
        if col not in df.columns:
            df[col] = df['close'].ewm(span=span, adjust=False).mean()
        vals = df[col].values
        slopes = np.zeros(len(vals))
        for i in range(span, len(vals)):
            if vals[i - span] != 0:
                slopes[i] = (vals[i] - vals[i - span]) / (vals[i - span] * span)
        df[f'ema{span}_slope'] = slopes

    # Bollinger Bands
    df['bb_mid'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2.0 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2.0 * bb_std
    bb_range = df['bb_upper'] - df['bb_lower']
    df['bb_position'] = (df['close'] - df['bb_lower']) / bb_range.replace(0, np.nan)

    # MA
    for p in [5, 10, 20, 50]:
        df[f'ma{p}'] = df['close'].rolling(p).mean()

    # Volume
    df['vol_ratio'] = df['volume'] / df['volume'].rolling(20).mean().replace(0, np.nan)
    df['volume_ma'] = df['volume'].rolling(20).mean()

    # 波动率偏度峰度
    df['realized_vol'] = df['returns'].rolling(20).std() * np.sqrt(252)
    df['skewness'] = df['returns'].rolling(20).apply(lambda x: pd.Series(x).skew() if len(x) >= 10 else np.nan)
    df['kurtosis'] = df['returns'].rolling(20).apply(lambda x: pd.Series(x).kurtosis() if len(x) >= 10 else np.nan)

    # ADX (趋势强度, Hurst 代理)
    plus_dm = df['high'].diff()
    minus_dm = -df['low'].diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    atr14 = df['atr']
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr14)
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr14)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    df['adx'] = dx.rolling(14).mean()
    df['adx_smooth'] = df['adx'].ewm(span=14, adjust=False).mean()

    # Hurst (用 ADX 代理, 0-1 范围)
    df['hurst_proxy'] = (df['adx_smooth'] / 100).clip(0, 1)

    # Range
    df['range_high'] = df['high'].rolling(20).max()
    df['range_low'] = df['low'].rolling(20).min()
    df['range_position'] = (df['close'] - df['range_low']) / (
        df['range_high'] - df['range_low'] + 1e-10)

    return df


def get_market_regime(hurst: float, adx: float) -> str:
    """判断市场状态"""
    if hurst > 0.6 or adx > 25:
        return "TREND"
    elif hurst < 0.4 or adx < 15:
        return "MEAN_REVERSION"
    else:
        return "NEUTRAL"


def compute_signal_p3(df: pd.DataFrame, idx: int, gold: bool = False) -> dict:
    """
    P3 信号计算 - Hurst 修正版
    - Hurst>0.6 → 趋势市场 → 增强趋势策略 (boost 1.3), 抑制均值回归 (boost 0.7)
    - Hurst<0.4 → 均值回归市场 → 增强均值回归 (boost 1.3), 抑制趋势 (boost 0.7)
    - 突破阈值: 0.3x ATR (P3-2 降低)
    - 时间止损: 24 根 K 线
    - SOL/BNB 模式: 纯突破检测
    """
    row = df.iloc[idx]
    n = len(df)

    mr_score = 0.0
    tf_score = 0.0

    # ── 均值回归因子 ──
    rsi = row.get('rsi', 50)
    bb_pos = row.get('bb_position', 0.5)
    if pd.isna(bb_pos):
        bb_pos = 0.5
    vol_ratio = row.get('vol_ratio', 1.0)
    if pd.isna(vol_ratio):
        vol_ratio = 1.0

    if rsi < 30:
        mr_score += 0.35
    elif rsi < 40:
        mr_score += 0.20
    if rsi > 70:
        mr_score += 0.35
    elif rsi > 60:
        mr_score += 0.20
    if bb_pos < 0.15:
        mr_score += 0.30
    elif bb_pos < 0.30:
        mr_score += 0.15
    if bb_pos > 0.85:
        mr_score += 0.30
    elif bb_pos > 0.70:
        mr_score += 0.15
    if vol_ratio < 1.5:
        mr_score += 0.15

    # ── 趋势因子 (P3-2: 门槛降低) ──
    e12 = row.get('ema12', row['close'])
    e26 = row.get('ema26', row['close'])
    e20 = row.get('ema20', row['close'])

    # EMA 斜率 (5-bar)
    ema_slope = row.get('ema5_slope', 0)
    if ema_slope > 0.001:
        tf_score += 0.30
    elif ema_slope < -0.001:
        tf_score += 0.30

    # EMA 排列
    if e12 > e26:
        tf_score += 0.15
    if e12 < e26:
        tf_score += 0.15

    # 突破确认 (P3-2: 0.5x → 0.3x ATR)
    if idx >= 20:
        lookback = min(20, idx)
        rh = df['high'].iloc[idx - lookback:idx].max()
        rl = df['low'].iloc[idx - lookback:idx].min()
        atr_now = row.get('atr', 0)
        atr_pct = row.get('atr_pct', 0)

        # 突破 + 波动率过滤
        vol_filter = 0.15 if gold else 0.25  # 贵金属更低
        breakout_th = 0.3  # P3-2: 降低门槛

        if row['close'] > rh + breakout_th * atr_now:
            tf_score += 0.25
        if row['close'] < rl - breakout_th * atr_now:
            tf_score += 0.25
        if atr_pct > vol_filter:  # 波动率过滤
            tf_score += 0.10

    # ── Hurst 市场状态修正 (P3-1 核心修复) ──
    hurst = row.get('hurst_proxy', 0.5)
    adx = row.get('adx_smooth', 20)
    regime = get_market_regime(hurst, adx)

    if regime == "TREND":
        tf_boost = 1.3   # 趋势市场 → 增强趋势信号
        mr_boost = 0.7   # 趋势市场 → 抑制均值回归
    elif regime == "MEAN_REVERSION":
        tf_boost = 0.7   # 均值回归市场 → 抑制趋势
        mr_boost = 1.3   # 均值回归市场 → 增强均值回归信号
    else:
        tf_boost = 1.0
        mr_boost = 1.0

    long_score = mr_score * mr_boost * 0.4 + tf_score * tf_boost * 0.6
    short_score = mr_score * mr_boost * 0.4 + tf_score * tf_boost * 0.6

    return {
        'regime': regime,
        'hurst': hurst,
        'adx': adx,
        'mr_score': mr_score,
        'tf_score': tf_score,
        'long_score': long_score,
        'short_score': short_score,
        'rsi': rsi,
        'bb_pos': bb_pos,
        'vol_ratio': vol_ratio,
        'atr_pct': row.get('atr_pct', 0),
        'ema_slope': ema_slope,
    }


def backtest_live_p3(df: pd.DataFrame, symbol: str, gold: bool = False,
                     threshold: float = 0.55, min_conf: int = 3,
                     vol_filter: float = 0.25, sl_mult: float = 1.8) -> dict:
    """
    P3 策略回测 - 含时间止损
    时间止损: 24 根 K 线强制平仓
    """
    df = compute_indicators(df)
    df = df.dropna(subset=['rsi', 'atr', 'bb_position']).reset_index(drop=True)

    capital = 10000.0
    position = None
    entry_price = 0.0
    entry_bar = 0
    returns = []
    exit_reasons = []
    strategies = []
    regimes = []

    trades_by_regime = {'TREND': [], 'MEAN_REVERSION': [], 'NEUTRAL': []}

    for i in range(50, len(df)):
        row = df.iloc[i]
        atr = row.get('atr', 0)
        close = row['close']
        high = row['high']
        low = row['low']
        vol_ratio = row.get('vol_ratio', 1.0)
        if pd.isna(vol_ratio):
            vol_ratio = 1.0

        bars_held = i - entry_bar

        # ── 平仓逻辑 ──
        if position == 'LONG':
            sl_price = entry_price * (1 - sl_mult * atr / entry_price)
            tp_price = entry_price * (1 + sl_mult * atr / entry_price * 2.0)

            closed = False
            reason = ""

            if low <= sl_price:
                pnl = (sl_price - entry_price) / entry_price - 0.0009
                capital *= (1 + pnl)
                returns.append(pnl)
                strategies.append('TREND' if regimes[-1] == 'TREND' else 'MEAN_REVERSION')
                exit_reasons.append('SL')
                closed = True
            elif high >= tp_price:
                pnl = (tp_price - entry_price) / entry_price - 0.0009
                capital *= (1 + pnl)
                returns.append(pnl)
                strategies.append('TREND' if regimes[-1] == 'TREND' else 'MEAN_REVERSION')
                exit_reasons.append('TP')
                closed = True
            # P3-2: 时间止损
            elif bars_held >= 24:
                pnl = (close - entry_price) / entry_price - 0.0009
                capital *= (1 + pnl)
                returns.append(pnl)
                strategies.append('TIME_STOP')
                exit_reasons.append('TIME')
                closed = True

            if closed:
                position = None
                entry_price = 0.0

        elif position == 'SHORT':
            sl_price = entry_price * (1 + sl_mult * atr / entry_price)
            tp_price = entry_price * (1 - sl_mult * atr / entry_price * 2.0)

            closed = False
            reason = ""

            if high >= sl_price:
                pnl = (entry_price - sl_price) / entry_price - 0.0009
                capital *= (1 + pnl)
                returns.append(pnl)
                strategies.append('TREND' if regimes[-1] == 'TREND' else 'MEAN_REVERSION')
                exit_reasons.append('SL')
                closed = True
            elif low <= tp_price:
                pnl = (entry_price - tp_price) / entry_price - 0.0009
                capital *= (1 + pnl)
                returns.append(pnl)
                strategies.append('TREND' if regimes[-1] == 'TREND' else 'MEAN_REVERSION')
                exit_reasons.append('TP')
                closed = True
            # P3-2: 时间止损
            elif bars_held >= 24:
                pnl = (entry_price - close) / entry_price - 0.0009
                capital *= (1 + pnl)
                returns.append(pnl)
                strategies.append('TIME_STOP')
                exit_reasons.append('TIME')
                closed = True

            if closed:
                position = None
                entry_price = 0.0

        # ── 开仓逻辑 ──
        if position is None and i >= 50:
            sig = compute_signal_p3(df, i, gold)

            # 确认计数
            confirms = 0
            if sig['rsi'] < 30 or sig['rsi'] > 70:
                confirms += 1
            if sig['bb_pos'] < 0.15 or sig['bb_pos'] > 0.85:
                confirms += 1
            if abs(sig['ema_slope']) > 0.001:
                confirms += 1
            if abs(sig['long_score'] - sig['short_score']) > 0.1:
                confirms += 1
            if sig['atr_pct'] > vol_filter:
                confirms += 1

            if confirms >= min_conf:
                if sig['long_score'] > sig['short_score'] and sig['long_score'] >= threshold:
                    position = 'LONG'
                    entry_price = close * 1.0005
                    entry_bar = i
                elif sig['short_score'] > sig['long_score'] and sig['short_score'] >= threshold:
                    position = 'SHORT'
                    entry_price = close * 0.9995
                    entry_bar = i

            regimes.append(sig['regime'])

    if not returns:
        return {'capital': capital, 'n': 0, 'returns': []}

    rets = np.array(returns)
    wr = float((rets > 0).mean())
    total_ret = capital / 10000 - 1
    sharpe = float(np.mean(rets) / (np.std(rets) + 1e-10) * np.sqrt(252 / len(rets)))
    cp = (1 + rets).cumprod()
    rm = np.maximum.accumulate(cp)
    max_dd = float(abs(np.min(cp / rm - 1)))
    pf = float(sum(rets[rets > 0]) / (abs(sum(rets[rets < 0])) + 1e-10))

    return {
        'capital': capital,
        'n': len(returns),
        'returns': returns,
        'win_rate': wr,
        'total_ret': total_ret,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'profit_factor': pf,
        'exit_reasons': exit_reasons,
        'strategies': strategies,
    }


# ─────────────────────────────────────────────────────────────
# Binance 真实数据获取
# ─────────────────────────────────────────────────────────────

def fetch_binance_klines(symbol: str, interval: str = '1h',
                          start_time: int = None, limit: int = 500) -> pd.DataFrame:
    """
    从 Binance REST API 获取 K 线数据
    symbol: BTCUSDT, ETHUSDT, etc.
    interval: 1m, 5m, 15m, 1h, 4h, 1d
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {
        'symbol': symbol.upper(),
        'interval': interval,
        'limit': limit,
    }
    if start_time:
        params['startTime'] = start_time

    print(f"[{symbol}] Fetching {limit} klines from Binance...")
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        raise ValueError(f"No data returned for {symbol}")

    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])

    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df['datetime'] = pd.to_datetime(df['open_time'], unit='ms')
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume']].copy()
    df = df.reset_index(drop=True)

    print(f"[{symbol}] Got {len(df)} bars: {df['datetime'].iloc[0]} → {df['datetime'].iloc[-1]}")
    return df


def fetch_binance_recent(symbol: str, interval: str = '1h',
                          days_back: int = 365) -> pd.DataFrame:
    """获取最近 N 天的 K 线数据（自动分页）"""
    ms_per_day = 86400 * 1000
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=days_back)).timestamp() * 1000)

    all_data = []
    current_start = start_time

    while current_start < end_time:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            'symbol': symbol.upper(),
            'interval': interval,
            'limit': 1000,
            'startTime': current_start,
            'endTime': min(current_start + 1000 * ms_per_day, end_time),
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_data.extend(batch)
        current_start = batch[-1][0] + 1

    df = pd.DataFrame(all_data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['datetime'] = pd.to_datetime(df['open_time'], unit='ms')
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume']].copy()
    df = df.drop_duplicates(subset=['datetime']).reset_index(drop=True)

    print(f"[{symbol}] Total: {len(df)} bars over ~{days_back} days")
    return df


# ─────────────────────────────────────────────────────────────
# Gate.io 数据获取（沙箱唯一可访问的加密货币API，自动修正high<low）
# ─────────────────────────────────────────────────────────────

INTERVAL_MAP = {'1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '4h': '4h', '1d': '1d'}

def fetch_gate_recent(symbol: str, interval: str = '1h', limit: int = 1000) -> pd.DataFrame:
    """
    从 Gate.io Spot API 获取 K 线数据
    自动修正 high < low 的数据质量问题
    """
    gate_symbol = symbol.replace('USDT', '_USDT').replace('BTC', 'BTC')
    gate_interval = INTERVAL_MAP.get(interval, '1h')
    
    url = f"https://api.gateio.ws/api/v4/spot/candlesticks"
    params = {'currency_pair': gate_symbol, 'interval': gate_interval, 'limit': str(limit)}
    
    print(f"[{symbol}] Fetching {limit} klines from Gate.io ({gate_interval})...")
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    raw = resp.json()
    
    if not raw or not isinstance(raw, list) or len(raw) == 0:
        raise ValueError(f"No data returned for {symbol}")
    
    # Gate.io格式: [ts_sec, quote_vol, open, close, high, low, vol, is_closed]
    rows = []
    for item in raw:
        if len(item) < 7:
            continue
        ts_sec = int(item[0])
        open_p = float(item[2])
        close_p = float(item[3])
        high_p = float(item[4])
        low_p = float(item[5])
        vol = float(item[6])
        
        # P3修复: 强制 high = max(o,h,l,c), low = min(o,h,l,c)
        high_p = max(open_p, close_p, high_p, low_p)
        low_p = min(open_p, close_p, high_p, low_p)
        
        rows.append({
            'datetime': datetime.utcfromtimestamp(ts_sec),
            'open': open_p, 'high': high_p, 'low': low_p,
            'close': close_p, 'volume': vol,
            'timestamp': ts_sec * 1000,
        })
    
    df = pd.DataFrame(rows)
    df = df.sort_values('datetime').reset_index(drop=True)
    print(f"[{symbol}] Gate.io: {len(df)} bars | {df['datetime'].iloc[0]} → {df['datetime'].iloc[-1]}")
    
    # 检查数据质量
    bad = (df['high'] < df['low']).sum()
    if bad > 0:
        print(f"[{symbol}] WARNING: {bad} high<low errors found and auto-fixed")
    
    return df


def fetch_local_json(symbol: str) -> pd.DataFrame:
    """从本地JSON文件加载历史数据，统一列名"""
    candidates = [
        f'data/{symbol}_1h_365d.json',
        f'data/{symbol}_1h.json',
        f'data/{symbol}_gateio_90d.json',       # Gate.io 123天历史数据(新)
        f'data/{symbol}_gate_historical.json',   # Gate.io 205天历史数据
        f'data/{symbol}_gate_realtime_fixed.json',
        f'data/{symbol}_gate_realtime.json',
        f'data/{symbol}_1h_binance_90d.json',
    ]
    # 列名映射（支持多种格式）
    col_map = {
        'ts': 'timestamp', 'o': 'open', 'h': 'high', 'l': 'low',
        'c': 'close', 'datetime': 'datetime', 'dt': 'datetime',
        'tbv': 'volume', 'v': 'quote_volume',
    }
    for path in candidates:
        if os.path.exists(path):
            print(f"[{symbol}] Loading from local: {path}")
            with open(path) as f: raw = json.load(f)
            df = pd.DataFrame(raw)
            
            # 重命名列
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            
            # 标准化列名（大小写兼容）
            for old, new in [('Open','open'),('High','high'),('Low','low'),
                              ('Close','close'),('Volume','volume'),('Timestamp','timestamp')]:
                if old in df.columns and new not in df.columns:
                    df = df.rename(columns={old: new})
            
            # 解析时间戳
            if 'datetime' not in df.columns:
                if 'timestamp' in df.columns:
                    ts = df['timestamp']
                    # 判断是秒还是毫秒
                    if ts.max() < 1e11:  # 秒
                        df['datetime'] = pd.to_datetime(ts, unit='s', utc=True)
                    else:  # 毫秒
                        df['datetime'] = pd.to_datetime(ts, unit='ms', utc=True)
                elif df.index.name == 'timestamp':
                    df['datetime'] = pd.to_datetime(df.index, unit='ms', utc=True)
            else:
                df['datetime'] = pd.to_datetime(df['datetime'], utc=True, errors='coerce')
            
            # 确保必需列存在
            required = ['open','high','low','close','volume']
            missing = [c for c in required if c not in df.columns]
            if missing:
                print(f"[{symbol}] WARNING: missing columns {missing}, skipping {path}")
                continue
            
            # 修正 high<low
            df['high'] = df[['open','close','high','low']].max(axis=1)
            df['low'] = df[['open','close','high','low']].min(axis=1)
            df = df.dropna(subset=['datetime']).sort_values('datetime').reset_index(drop=True)
            print(f"[{symbol}] Local: {len(df)} bars | {df['datetime'].iloc[0]} → {df['datetime'].iloc[-1]}")
            return df
    raise FileNotFoundError(f"No local data found for {symbol}")


# ─────────────────────────────────────────────────────────────
# 过拟合检测 (CSCV/PBO/DSR)
# ─────────────────────────────────────────────────────────────

def detect_overfitting(returns: list) -> dict:
    """简化过拟合检测"""
    if len(returns) < 8:
        return {'pbo': None, 'dsr': None, 'quality': 0, 'risk': 'N/A'}

    rets = np.array(returns)
    n = len(rets)
    mean_ret = np.mean(rets)
    std_ret = np.std(rets)

    # Sharpe
    sharpe = mean_ret / (std_ret + 1e-10) * np.sqrt(252 / n) if std_ret > 0 else 0

    # DSR (deflated sharpe ratio) - simplified
    expected_max = np.sqrt(2 * np.log(n)) * std_ret
    dsr = max(sharpe - expected_max, 0) / (std_ret + 1e-10)

    # PBO - bootstrap based (proportion of bootstrap samples worse than 0)
    pbo_count = 0
    n_bootstrap = min(200, 2**n)
    for _ in range(min(200, 2**n)):
        sample = np.random.choice(rets, size=n, replace=True)
        if np.mean(sample) < 0:
            pbo_count += 1
    pbo = pbo_count / 200 if n_bootstrap == 200 else None

    # Quality score (0-100)
    quality = 0
    if mean_ret > 0:
        quality += 30
    if std_ret < 0.05:
        quality += 20
    if sharpe > 0.5:
        quality += 25
    elif sharpe > 0.2:
        quality += 15
    if pbo is None or pbo < 0.3:
        quality += 25

    risk = 'LOW' if quality >= 70 else ('MEDIUM' if quality >= 40 else 'HIGH')

    return {
        'sharpe': sharpe,
        'pbo': pbo,
        'dsr': dsr,
        'quality': quality,
        'risk': risk,
        'n_trades': n,
    }


# ─────────────────────────────────────────────────────────────
# 主验证流程
# ─────────────────────────────────────────────────────────────

def validate_pair(symbol: str, interval: str = '1h', days: int = 365,
                 gold: bool = False, threshold: float = 0.55) -> dict:
    """对单个交易对进行完整验证（数据源优先级: Gate.io > 本地JSON > Binance）"""
    print(f"\n{'='*70}")
    print(f"REAL-TIME VALIDATION: {symbol} ({interval})")
    print(f"{'='*70}")

    # 获取数据: 优先级1 本地JSON(365d) > 2 Gate.io(实时/最新) > 3 Binance(可能阻断)
    df = None
    source = None
    try:
        # 1. 本地JSON文件（365天，最完整）
        df = fetch_local_json(symbol)
        source = 'Local JSON (365d)'
    except Exception as e1:
        print(f"[{symbol}] Local JSON failed: {e1}")
        try:
            # 2. Gate.io API (1000根K线，最新鲜)
            df = fetch_gate_recent(symbol, interval, limit=1000)
            source = 'Gate.io API'
        except Exception as e2:
            print(f"[{symbol}] Gate.io failed: {e2}")
            try:
                # 3. Binance REST API (可能被阻断)
                df = fetch_binance_recent(symbol, interval, days)
                source = 'Binance API'
            except Exception as e3:
                print(f"[{symbol}] Binance API failed: {e3}")
                print(f"[{symbol}] FATAL: No data source available")
                return None

    print(f"[{symbol}] Data source: {source}")
    print(f"[{symbol}] Data range: {df['datetime'].iloc[0]} → {df['datetime'].iloc[-1]}")
    print(f"[{symbol}] Price range: {df['low'].min():.2f} – {df['high'].max():.2f}")

    # 波动率统计
    df['ret'] = df['close'].pct_change()
    vol = df['ret'].std() * 100
    skew = df['ret'].skew()
    kurt = df['ret'].kurtosis()
    print(f"[{symbol}] Vol: {vol:.3f}%, Skew: {skew:.2f}, Kurtosis: {kurt:.1f}")

    # 计算指标 (使用 optimizer_precious_metal 版本，含 Hurst 计算)
    df = ci(df)

    # IS / OOS 分割
    n = len(df)
    is_end = int(n * 0.80)

    df_is = df.iloc[:is_end].reset_index(drop=True)
    df_oos = df.iloc[is_end:].reset_index(drop=True)
    df_is = ci(df_is)
    df_oos = ci(df_oos)

    print(f"[{symbol}] IS: {len(df_is)} bars, OOS: {len(df_oos)} bars")
    print(f"[{symbol}] IS dates: {df_is['datetime'].iloc[0]} → {df_is['datetime'].iloc[-1]}")
    print(f"[{symbol}] OOS dates: {df_oos['datetime'].iloc[0]} → {df_oos['datetime'].iloc[-1]}")

    # IS 回测 (使用 optimizer_precious_metal 经 P3 验证的回测引擎)
    r_is = backtest_precious_metal(df_is, threshold, 3, 1.6, 1.6, gold, 0.25)
    rets_is = np.array(r_is.get('returns', []))
    wr_is = float((rets_is > 0).mean()) if len(rets_is) > 0 else 0

    # OOS 回测
    r_oos = backtest_precious_metal(df_oos, threshold, 3, 1.6, 1.6, gold, 0.25)
    rets_oos = np.array(r_oos.get('returns', []))
    wr_oos = float((rets_oos > 0).mean()) if len(rets_oos) > 0 else 0

    # 过拟合检测 (OOS)
    of_result = detect_overfitting(r_oos.get('returns', []))

    # 计算收益和夏普
    ret_is = r_is['capital'] / 10000 - 1
    ret_oos = r_oos['capital'] / 10000 - 1
    rets = np.array(r_oos.get('returns', []))
    sharpe_oos = (rets.mean() / (rets.std() + 1e-10) * np.sqrt(252 / len(rets))) if len(rets) >= 3 else 0

    # 打印结果
    print(f"\n{'─'*60}")
    print(f"IS 段: {r_is['n']} 笔 | WR={wr_is:.1%} | Ret={ret_is:+.2%} | Capital={r_is['capital']:.0f}")
    print(f"OOS 段: {r_oos['n']} 笔 | WR={wr_oos:.1%} | Ret={ret_oos:+.2%} | Sharpe={sharpe_oos:+.2f}")
    pbo_str = f"{of_result['pbo']:.1%}" if of_result['pbo'] is not None else "N/A"
    dsr_str = f"{of_result['dsr']:.3f}" if of_result['dsr'] is not None else "N/A"
    print(f"过拟合: PBO={pbo_str} | DSR={dsr_str} | Q={of_result['quality']} | Risk={of_result['risk']}")

    # 改进评估
    baseline_wr = 0.079 if not gold else 0.055
    improvement = wr_oos - baseline_wr
    grade = 'A' if wr_oos >= 0.50 else ('B' if wr_oos >= 0.35 else ('C' if wr_oos >= 0.25 else ('D' if wr_oos >= 0.15 else 'F')))

    print(f"\n{'─'*60}")
    print(f"基线 OOS 胜率: {baseline_wr:.1%}")
    print(f"P3 修复后 OOS 胜率: {wr_oos:.1%}")
    print(f"提升: +{improvement:.1%} ({improvement/baseline_wr:.1f}x)" if baseline_wr > 0 else "")
    print(f"Grade: {grade}")

    return {
        'symbol': symbol,
        'source': source,
        'n_is': r_is['n'],
        'n_oos': r_oos['n'],
        'wr_is': wr_is,
        'wr_oos': wr_oos,
        'ret_oos': ret_oos,
        'sharpe_oos': sharpe_oos,
        'pbo': of_result['pbo'],
        'dsr': of_result['dsr'],
        'quality': of_result['quality'],
        'risk': of_result['risk'],
        'improvement': improvement,
        'grade': grade,
    }


def main():
    parser = argparse.ArgumentParser(description='P3 Strategy Real-Time Data Validator')
    parser.add_argument('--symbol', type=str, default='BTCUSDT',
                        help='交易对 (BTCUSDT, ETHUSDT, SOLUSDT, etc.)')
    parser.add_argument('--interval', type=str, default='1h',
                        help='K线周期 (1m, 5m, 15m, 1h, 4h, 1d)')
    parser.add_argument('--days', type=int, default=365,
                        help='获取历史天数')
    parser.add_argument('--threshold', type=float, default=0.55,
                        help='信号确认阈值 (默认 0.55)')
    parser.add_argument('--gold', action='store_true',
                        help='贵金属模式 (更低波动率过滤)')
    parser.add_argument('--pairs', type=str, default='',
                        help='逗号分隔多品种, 如 BTCUSDT,ETHUSDT')
    args = parser.parse_args()

    print(f"\n{'#'*70}")
    print(f"#  KILLER TRADING SYSTEM v1.3 - P3 REAL-TIME DATA VALIDATOR")
    print(f"#  Data: Gate.io API (primary) | Local JSON | Binance API")
    print(f"#  Thresh: {args.threshold:.2f} | Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*70}")

    symbols = [s.strip() for s in args.pairs.split(',') if s.strip()] if args.pairs else [args.symbol]

    all_results = []
    for sym in symbols:
        gold = args.gold or sym in ['XAUUSD', 'XAGUSD', 'GOLD', 'SILVER']
        result = validate_pair(sym, args.interval, args.days, gold, args.threshold)
        if result:
            all_results.append(result)
        time.sleep(1)  # 避免触发 Binance 限流

    # ── 综合报告 ──
    if len(all_results) > 1:
        print(f"\n{'='*70}")
        print(f"COMBINED VALIDATION REPORT ({len(all_results)} pairs)")
        print(f"{'='*70}")

        total_n = sum(r['n_oos'] for r in all_results)
        weighted_wr = sum(r['wr_oos'] * r['n_oos'] for r in all_results) / total_n if total_n > 0 else 0
        avg_ret = np.mean([r['ret_oos'] for r in all_results])
        avg_sharpe = np.mean([r['sharpe_oos'] for r in all_results])

        print(f"\n{'品种':<10} {'IS笔':>6} {'OOS笔':>6} {'IS WR':>7} {'OOS WR':>7} "
              f"{'OOS Ret':>9} {'Sharpe':>7} {'PBO':>6} {'Grade':>6} {'数据源':>10}")
        print('─' * 75)
        for r in all_results:
            pbo_str = f"{r['pbo']:.0%}" if r['pbo'] is not None else "N/A"
            print(f"{r['symbol']:<10} {r['n_is']:>6} {r['n_oos']:>6} "
                  f"{r['wr_is']:>6.1%} {r['wr_oos']:>7.1%} "
                  f"{r['ret_oos']:>+9.2%} {r['sharpe_oos']:>+7.3f} "
                  f"{pbo_str:>6} {r['grade']:>6} {r.get('source','?'):>10}")

        print('─' * 75)
        print(f"{'加权平均':<10} {'':<6} {total_n:>6} {'':<6} "
              f"{weighted_wr:>7.1%} {avg_ret:>+9.2%} {avg_sharpe:>+7.3f}")
        print()
        print(f"验收标准: 平均 OOS 胜率 ≥ 45% → 实际 {weighted_wr:.1%} "
              f"{'✓' if weighted_wr >= 0.45 else '✗ (差距' + f'{0.45-weighted_wr:.1%})'}")

        # 输出 JSON 结果
        output = {
            'timestamp': datetime.now().isoformat(),
            'n_pairs': len(all_results),
            'weighted_oos_wr': weighted_wr,
            'avg_oos_ret': avg_ret,
            'avg_sharpe': avg_sharpe,
            'total_oos_trades': total_n,
            'pairs': all_results,
        }
        fname = f"p3_realtime_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(fname, 'w') as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\n结果已保存: {fname}")


if __name__ == '__main__':
    main()
