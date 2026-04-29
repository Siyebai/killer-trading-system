#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杀手锏交易系统 v5.2 - 多维评分信号系统
整合自 crude_oil_optimization.py 的6条件加权评分 + 趋势方向加权

核心创新：
1. 6维度评分：趋势强度/MACD/均线突破/RSI/成交量/动量
2. 趋势方向加权：上升市LONG×1.5, SHORT×0.3
3. 量比过滤：vol_ratio > 1.5时不做均值回归
4. Hurst过滤：Hurst < 0.5才允许均值回归信号
5. 动量指标：momentum = close/close.shift(10) - 1
6. 信号阈值：0.20（可配置）
"""
import argparse
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("signal_scorer_multidim")


class MultiDimSignalScorer:
    """
    多维评分信号生成器

    评分维度（共6项，最大1.40分）：
    1. 趋势强度(ADX) - 权重0.35
    2. MACD金叉/死叉 - 权重0.30
    3. 均线突破 - 权重0.25
    4. RSI超买超卖 - 权重0.20
    5. 成交量放大 - 权重0.15
    6. 动量方向 - 权重0.15
    """

    def __init__(self, config: Dict = None):
        self.version = "v5.2"
        default_config = {
            'signal_threshold': 0.20,
            'trend_direction_weight': 1.5,    # 顺势加权
            'counter_trend_weight': 0.3,      # 逆势衰减
            'volume_high_threshold': 1.5,      # 高量阈值
            'hurst_mean_rev_threshold': 0.5,   # Hurst均值回归阈值
            'rsi_oversold': 30,
            'rsi_overbought': 70,
            'bb_std': 2.5,
            'momentum_period': 10,
            'adx_trend_threshold': 25,
        }
        if config:
            default_config.update(config)
        self.config = default_config

        logger.info(f"[OK] 多维评分信号系统 {self.version} 初始化")
        logger.info(f"   信号阈值: {self.config['signal_threshold']}")
        logger.info(f"   趋势加权: 顺势×{self.config['trend_direction_weight']}, 逆势×{self.config['counter_trend_weight']}")

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        df = df.copy()

        # 均线系统
        df['ma5'] = df['close'].rolling(5).mean()
        df['ma10'] = df['close'].rolling(10).mean()
        df['ma20'] = df['close'].rolling(20).mean()
        df['ma50'] = df['close'].rolling(50).mean()
        df['ma60'] = df['close'].rolling(60).mean()

        # EMA / MACD
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        loss = loss.replace(0, np.nan)
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi'] = df['rsi'].fillna(50)

        # ATR
        hl = df['high'] - df['low']
        hc = abs(df['high'] - df['close'].shift())
        lc = abs(df['low'] - df['close'].shift())
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()
        df['atr_pct'] = df['atr'] / df['close'] * 100

        # ADX
        plus_dm = df['high'].diff()
        minus_dm = df['low'].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        atr_safe = df['atr'].replace(0, np.nan)
        plus_di = 100 * (plus_dm.ewm(alpha=1/14).mean() / atr_safe)
        minus_di = 100 * (abs(minus_dm).ewm(alpha=1/14).mean() / atr_safe)
        di_sum = (plus_di + minus_di).replace(0, np.nan)
        df['adx'] = (100 * abs(plus_di - minus_di) / di_sum).ewm(alpha=1/14).mean()
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di

        # 布林带 (2.5σ)
        df['bb_mid'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + self.config['bb_std'] * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - self.config['bb_std'] * df['bb_std']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']

        # 成交量
        df['vol_ma'] = df['volume'].rolling(20).mean()
        df['vol_ratio'] = df['volume'] / df['vol_ma'].replace(0, np.nan)

        # 动量（整合自crude_oil策略）
        mom_period = self.config['momentum_period']
        df['momentum'] = df['close'] / df['close'].shift(mom_period) - 1
        df['momentum_ma'] = df['momentum'].rolling(5).mean()

        # Hurst指数（整合自v5_ultimate策略）
        df['hurst'] = self._calculate_hurst(df['close'], window=100)

        # 趋势判断
        df['uptrend'] = (df['ma5'] > df['ma20']) & (df['ma20'] > df['ma60'])
        df['downtrend'] = (df['ma5'] < df['ma20']) & (df['ma20'] < df['ma60'])

        # 波动率状态
        df['high_vol'] = df['atr_pct'] > df['atr_pct'].rolling(20).mean()

        return df

    def _calculate_hurst(self, series: pd.Series, window: int = 100) -> pd.Series:
        """简化Hurst指数计算（整合自v5_ultimate）"""
        def hurst(ts):
            if len(ts) < 20:
                return 0.5
            try:
                lags = range(2, min(20, len(ts)))
                tau = [np.std(np.subtract(ts[lag:], ts[:-lag])) for lag in lags]
                valid = [(np.log(lag), np.log(t)) for lag, t in zip(lags, tau) if t > 0]
                if len(valid) < 3:
                    return 0.5
                x = [v[0] for v in valid]
                y = [v[1] for v in valid]
                poly = np.polyfit(x, y, 1)
                return max(0.0, min(1.0, poly[0]))
            except Exception:
                return 0.5

        return series.rolling(window).apply(hurst, raw=False)

    def generate_signal(self, df: pd.DataFrame, idx: int) -> Dict:
        """
        生成多维评分信号

        返回:
        - signal_dict: {signal, long_score, short_score, reasons, hurst}
        """
        if idx < 100:
            return {'signal': 0, 'long_score': 0, 'short_score': 0, 'reasons': [], 'hurst': 0.5}

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]

        hurst = row.get('hurst', 0.5)
        if pd.isna(hurst):
            hurst = 0.5

        # ============ LONG评分 ============
        long_score = 0.0
        long_reasons = []

        # 1. 趋势强度 (0.35)
        if row.get('uptrend', False) and row.get('adx', 0) > self.config['adx_trend_threshold']:
            long_score += 0.35
            long_reasons.append('trend_up')

        # 2. MACD金叉 (0.30)
        if row.get('macd', 0) > row.get('macd_signal', 0) and prev.get('macd', 0) <= prev.get('macd_signal', 0):
            long_score += 0.30
            long_reasons.append('macd_golden')

        # 3. 均线突破 (0.25)
        if row.get('close', 0) > row.get('ma20', 0) and prev.get('close', 0) <= prev.get('ma20', 0):
            long_score += 0.25
            long_reasons.append('ma20_breakout')

        # 4. RSI超卖反弹 (0.20)
        rsi_ob = self.config['rsi_overbought']
        rsi_os = self.config['rsi_oversold']
        if row.get('rsi', 50) < 40 and row.get('rsi', 50) > prev.get('rsi', 50):
            long_score += 0.20
            long_reasons.append('rsi_oversold')

        # 5. 成交量放大 (0.15)
        if row.get('vol_ratio', 1) > self.config['volume_high_threshold']:
            long_score += 0.15
            long_reasons.append('volume_surge')

        # 6. 动量转正 (0.15)
        if row.get('momentum', 0) > 0 and prev.get('momentum', 0) <= 0:
            long_score += 0.15
            long_reasons.append('momentum_positive')

        # 均值回归信号（Hurst < 0.5时有效）
        if hurst < self.config['hurst_mean_rev_threshold']:
            if row.get('rsi', 50) < rsi_os and row.get('close', 0) < row.get('bb_lower', 0):
                long_score += 0.25
                long_reasons.append('mean_rev_oversold')
            if row.get('rsi', 50) > prev.get('rsi', 50) and row.get('rsi', 50) < rsi_os:
                long_score += 0.10
                long_reasons.append('rsi_bounce')

        # ============ SHORT评分 ============
        short_score = 0.0
        short_reasons = []

        # 1. 趋势强度 (0.35)
        if row.get('downtrend', False) and row.get('adx', 0) > self.config['adx_trend_threshold']:
            short_score += 0.35
            short_reasons.append('trend_down')

        # 2. MACD死叉 (0.30)
        if row.get('macd', 0) < row.get('macd_signal', 0) and prev.get('macd', 0) >= prev.get('macd_signal', 0):
            short_score += 0.30
            short_reasons.append('macd_death')

        # 3. 均线跌破 (0.25)
        if row.get('close', 0) < row.get('ma20', 0) and prev.get('close', 0) >= prev.get('ma20', 0):
            short_score += 0.25
            short_reasons.append('ma20_breakdown')

        # 4. RSI超买回落 (0.20)
        if row.get('rsi', 50) > 60 and row.get('rsi', 50) < prev.get('rsi', 50):
            short_score += 0.20
            short_reasons.append('rsi_overbought')

        # 5. 成交量放大 (0.15)
        if row.get('vol_ratio', 1) > self.config['volume_high_threshold']:
            short_score += 0.15
            short_reasons.append('volume_surge')

        # 6. 动量转负 (0.15)
        if row.get('momentum', 0) < 0 and prev.get('momentum', 0) >= 0:
            short_score += 0.15
            short_reasons.append('momentum_negative')

        # 均值回归信号
        if hurst < self.config['hurst_mean_rev_threshold']:
            if row.get('rsi', 50) > rsi_ob and row.get('close', 0) > row.get('bb_upper', 0):
                short_score += 0.25
                short_reasons.append('mean_rev_overbought')

        # ============ 趋势方向加权 ============
        trend_w = self.config['trend_direction_weight']
        counter_w = self.config['counter_trend_weight']

        if row.get('uptrend', False):
            long_score *= trend_w
            short_score *= counter_w
        elif row.get('downtrend', False):
            short_score *= trend_w
            long_score *= counter_w

        # ============ 量比过滤 ============
        vol_ratio = row.get('vol_ratio', 1)
        if pd.isna(vol_ratio):
            vol_ratio = 1.0
        high_volume = vol_ratio > self.config['volume_high_threshold']

        # 高量时不做均值回归（只保留趋势信号）
        if high_volume:
            mean_rev_reasons = ['mean_rev_oversold', 'mean_rev_overbought', 'rsi_bounce']
            for reason in mean_rev_reasons:
                if reason in long_reasons:
                    long_score -= 0.25
                    long_reasons.remove(reason)
                if reason in short_reasons:
                    short_score -= 0.25
                    short_reasons.remove(reason)

        # ============ 生成最终信号 ============
        threshold = self.config['signal_threshold']
        signal = 0

        if long_score > short_score and long_score >= threshold:
            signal = 1
        elif short_score > long_score and short_score >= threshold:
            signal = -1

        return {
            'signal': signal,
            'long_score': round(long_score, 4),
            'short_score': round(short_score, 4),
            'reasons': long_reasons if signal == 1 else short_reasons if signal == -1 else [],
            'hurst': round(hurst, 4),
            'is_mean_rev': hurst < self.config['hurst_mean_rev_threshold'],
            'is_high_volume': high_volume,
            'confidence': round(max(long_score, short_score) / 1.5 * 100, 1)  # 归一化到100
        }

    def run_backtest(self, df: pd.DataFrame, symbol: str = 'UNKNOWN',
                     capital: float = 100000, sl_atr: float = 1.5,
                     tp_atr: float = 3.0) -> Dict:
        """
        运行回测（带动态保本止损）

        整合自 strategy_v5_ultimate.py 的保本止损逻辑：
        - 价格到达BB均线时移止损到成本
        """
        df = self.calculate_indicators(df)

        equity = capital
        pos = None
        entry = None
        sl = None
        tp = None
        breakeven_set = False  # 保本止损是否已设置

        trades = []
        wins = 0
        long_t, short_t, long_w, short_w = 0, 0, 0, 0
        mean_rev_t, trend_t = 0, 0
        mean_rev_w, trend_w = 0, 0

        for i in range(100, len(df)):
            row = df.iloc[i]

            if pos is not None:
                # 动态保本止损（整合自v5_ultimate）
                if pos == 1 and not breakeven_set:
                    if row['close'] >= row['bb_mid'] and sl < entry:
                        sl = entry  # 移止损到成本
                        breakeven_set = True
                elif pos == -1 and not breakeven_set:
                    if row['close'] <= row['bb_mid'] and sl > entry:
                        sl = entry
                        breakeven_set = True

                # 止损/止盈检查
                if pos == 1:
                    if row['low'] <= sl:
                        loss = (sl - entry) / entry
                        equity *= (1 - loss)
                        trades.append({'type': 'LONG', 'entry': entry, 'exit': sl,
                                      'pnl': -loss, 'result': 'LOSS', 'breakeven': breakeven_set})
                        long_t += 1
                        pos = None
                    elif row['high'] >= tp:
                        profit = (tp - entry) / entry
                        equity *= (1 + profit)
                        trades.append({'type': 'LONG', 'entry': entry, 'exit': tp,
                                      'pnl': profit, 'result': 'WIN', 'breakeven': breakeven_set})
                        long_t += 1
                        long_w += 1
                        wins += 1
                        pos = None
                else:  # SHORT
                    if row['high'] >= sl:
                        loss = (sl - entry) / entry
                        equity *= (1 - abs(loss))
                        trades.append({'type': 'SHORT', 'entry': entry, 'exit': sl,
                                      'pnl': -abs(loss), 'result': 'LOSS', 'breakeven': breakeven_set})
                        short_t += 1
                        pos = None
                    elif row['low'] <= tp:
                        profit = (entry - tp) / entry
                        equity *= (1 + profit)
                        trades.append({'type': 'SHORT', 'entry': entry, 'exit': tp,
                                      'pnl': profit, 'result': 'WIN', 'breakeven': breakeven_set})
                        short_t += 1
                        short_w += 1
                        wins += 1
                        pos = None

            if pos is None:
                sig_dict = self.generate_signal(df, i)
                sig = sig_dict['signal']

                if sig != 0:
                    entry = row['close']
                    atr = row.get('atr', row['close'] * 0.02)
                    if pd.isna(atr) or atr <= 0:
                        atr = row['close'] * 0.02

                    if sig == 1:
                        sl = entry - sl_atr * atr
                        tp = entry + tp_atr * atr
                    else:
                        sl = entry + sl_atr * atr
                        tp = entry - tp_atr * atr

                    pos = sig
                    breakeven_set = False

                    if sig_dict.get('is_mean_rev', False):
                        mean_rev_t += 1
                    else:
                        trend_t += 1

        total = len(trades)
        win_rate = wins / total * 100 if total > 0 else 0
        long_wr = long_w / long_t * 100 if long_t > 0 else 0
        short_wr = short_w / short_t * 100 if short_t > 0 else 0
        ret = (equity - capital) / capital * 100
        ev = np.mean([t['pnl'] for t in trades]) if trades else 0

        # 保本止损统计
        be_trades = [t for t in trades if t.get('breakeven', False)]
        be_wins = [t for t in be_trades if t['result'] == 'WIN']

        return {
            'symbol': symbol,
            'return': round(ret, 2),
            'trades': total,
            'wins': wins,
            'win_rate': round(win_rate, 1),
            'long_t': long_t,
            'short_t': short_t,
            'long_wr': round(long_wr, 1),
            'short_wr': round(short_wr, 1),
            'ev': round(ev, 4),
            'mean_rev_trades': mean_rev_t,
            'trend_trades': trend_t,
            'breakeven_count': len(be_trades),
            'breakeven_win_rate': round(len(be_wins) / len(be_trades) * 100, 1) if be_trades else 0,
            'final_equity': round(equity, 2),
            'trades_list': trades
        }


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='多维评分信号系统')
    parser.add_argument('--threshold', type=float, default=0.20, help='信号阈值')
    parser.add_argument('--bars', type=int, default=500, help='模拟数据条数')
    args = parser.parse_args()

    # 生成模拟数据测试
    np.random.seed(42)
    n = args.bars
    dates = pd.date_range('2025-01-01', periods=n, freq='h')
    price = 100000 * np.exp(np.cumsum(np.random.randn(n) * 0.002))

    df = pd.DataFrame({
        'open': price * (1 + np.random.randn(n) * 0.001),
        'high': price * (1 + abs(np.random.randn(n)) * 0.005),
        'low': price * (1 - abs(np.random.randn(n)) * 0.005),
        'close': price,
        'volume': np.random.randint(100, 10000, n)
    }, index=dates)

    # 运行回测
    scorer = MultiDimSignalScorer({'signal_threshold': args.threshold})
    result = scorer.run_backtest(df, 'BTCUSDT_SIM')

    output = {
        'symbol': result['symbol'],
        'return': result['return'],
        'trades': result['trades'],
        'win_rate': result['win_rate'],
        'long_trades': result['long_t'],
        'short_trades': result['short_t'],
        'mean_rev_trades': result['mean_rev_trades'],
        'trend_trades': result['trend_trades'],
        'ev': result['ev'],
        'breakeven_count': result['breakeven_count'],
        'breakeven_win_rate': result['breakeven_win_rate']
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
