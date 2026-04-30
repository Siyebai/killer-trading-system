#!/usr/bin/env python3
"""
杀手锏交易系统 - 信号引擎 v4.0
策略转型：从趋势跟踪 → 均值回归 + 统计套利

核心发现：
- v1-v3 均基于 MA/EMA 趋势信号，LONG 胜率持续 30% 以下
- 真实 BTC 数据显示：价格大部分时间处于均值回归状态
- 新策略：当价格偏离统计均值过远时，下注回归

信号逻辑：
1. RSI 极值反转（RSI<30 做多，RSI>70 做空）
2. 布林带突破反转（价格触及 2σ 带外做反向）
3. 短期超涨超跌（N根K线内涨/跌幅超过阈值）
4. EMA200 趋势方向做同向均值回归（不逆势）
"""
import numpy as np
from typing import Tuple


def ema_val(arr, period):
    k = 2 / (period + 1)
    e = float(arr[0])
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return e


def calc_rsi(closes, period=14):
    # [FIX] 数组长度不足时返回中性值50，防止IndexError
    if len(closes) < period + 1:
        return 50.0
    diffs  = [closes[j]-closes[j-1] for j in range(-period, 0)]
    gains  = [max(d, 0) for d in diffs]
    losses = [abs(min(d, 0)) for d in diffs]
    ag, al = np.mean(gains), np.mean(losses)
    if al == 0:
        return 100.0 if ag > 0 else 50.0   # [FIX] 全涨→100，横盘→50，不返回div-zero
    return 100 - (100 / (1 + ag / al))


def calc_bollinger(closes, period=20):
    # [FIX] 数组长度不足时退化处理
    if len(closes) < period:
        mid = float(np.mean(closes))
        return mid, mid, mid, 0.0
    window = np.array(closes[-period:])
    mid    = float(np.mean(window))
    std    = float(np.std(window))
    return mid, mid + 2*std, mid - 2*std, std


def calc_atr(highs, lows, closes, period=14):
    trs = [max(highs[j]-lows[j],
               abs(highs[j]-closes[j-1]),
               abs(lows[j]-closes[j-1]))
           for j in range(-period, 0)]
    return float(np.mean(trs))


def pct_change_n(closes, n):
    """过去N根K线的涨跌幅"""
    if len(closes) <= n:
        return 0
    return (closes[-1] - closes[-n-1]) / closes[-n-1] * 100


def _signal_A(closes, rsi14: float) -> Tuple[bool, bool, float]:
    """信号A: RSI极端反转"""
    if rsi14 <= 28:
        return True, False, (30 - rsi14) / 30
    elif rsi14 >= 72:
        return False, True, (rsi14 - 70) / 30
    return False, False, 0.0

def _signal_B(cur: float, prev: float, bb_pos: float, bb_lower: float, bb_upper: float, bb_std: float) -> Tuple[bool, bool, float]:
    """信号B: 布林带突破反转"""
    sig_long, sig_short, strength = False, False, 0.0
    if bb_pos <= 0.05 and prev < bb_lower:
        sig_long = True; strength = min((bb_lower - cur) / bb_std, 1.5) / 1.5
    elif bb_pos >= 0.95 and prev > bb_upper:
        sig_short = True; strength = min((cur - bb_upper) / bb_std, 1.5) / 1.5
    if not sig_long and bb_pos <= 0.08:
        sig_long = True; strength = max(strength, 0.4)
    if not sig_short and bb_pos >= 0.92:
        sig_short = True; strength = max(strength, 0.4)
    return sig_long, sig_short, strength

def _signal_C(ret3: float, ret6: float, atr_pct: float) -> Tuple[bool, bool, float]:
    """信号C: 短期超涨超跌"""
    sig_long, sig_short, strength = False, False, 0.0
    if ret3 < -atr_pct * 1.2:
        sig_long = True; strength = min(abs(ret3) / (atr_pct * 2), 1.0)
    elif ret3 > atr_pct * 1.2:
        sig_short = True; strength = min(ret3 / (atr_pct * 2), 1.0)
    if not sig_long and ret6 < -atr_pct * 1.8:
        sig_long = True; strength = max(strength, min(abs(ret6) / (atr_pct * 3), 0.8))
    if not sig_short and ret6 > atr_pct * 1.8:
        sig_short = True; strength = max(strength, min(ret6 / (atr_pct * 3), 0.8))
    return sig_long, sig_short, strength

def generate_signal_v4(closes, highs, lows, opens, volumes, min_bars=50):
    """
    信号生成 v4.0 — 统计套利 + 均值回归

    三类信号：
    A. RSI 极端反转
    B. 布林带突破反转
    C. 短期超涨超跌反转
    任意两类同时触发 → 入场
    """
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'insufficient_data', 'market': 'N/A'}

    cur  = closes[-1]
    prev = closes[-2] if n >= 2 else cur

    # 基础指标
    rsi14 = calc_rsi(closes, 14)
    rsi9  = calc_rsi(closes[-10:], 9) if n >= 10 else rsi14
    bb_mid, bb_upper, bb_lower, bb_std = calc_bollinger(closes)
    atr   = calc_atr(highs, lows, closes)

    # 价格在布林带的位置 (0=下轨, 1=上轨)
    bb_range = bb_upper - bb_lower
    if bb_range < 1e-9:   # [FIX] 零方差保护，横盘市场直接返回NEUTRAL
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'bb_range_zero(flat_market)', 'market': 'NEUTRAL_MKT'}
    bb_pos = (cur - bb_lower) / bb_range

    # 短期动量
    ret3  = pct_change_n(closes, 3)
    ret6  = pct_change_n(closes, 6)
    ret12 = pct_change_n(closes, 12)

    # 成交量
    vol_ma    = float(np.mean(volumes[-20:])) if n >= 20 else float(volumes[-1])
    vol_ratio = volumes[-1] / vol_ma if vol_ma > 0 else 1

    # EMA200 趋势背景
    ema_period = min(200, n-1)
    ema200 = ema_val(closes[max(0,n-ema_period*2):], ema_period)
    ratio  = cur / ema200
    market = 'BULL' if ratio >= 1.005 else ('BEAR' if ratio <= 0.995 else 'NEUTRAL_MKT')

    # 三类信号独立计算
    sig_A_long, sig_A_short, A_str = _signal_A(closes, rsi14)
    sig_B_long, sig_B_short, B_str = _signal_B(cur, prev, bb_pos, bb_lower, bb_upper, bb_std)
    sig_C_long, sig_C_short, C_str = _signal_C(ret3, ret6, atr / cur * 100)

    # 综合决策：任意 2 类信号同时触发
    long_hits  = sum([sig_A_long,  sig_B_long,  sig_C_long])
    short_hits = sum([sig_A_short, sig_B_short, sig_C_short])

    long_strength  = np.mean([s for s, b in [(A_str,sig_A_long),(B_str,sig_B_long),(C_str,sig_C_long)] if b]) if long_hits else 0
    short_strength = np.mean([s for s, b in [(A_str,sig_A_short),(B_str,sig_B_short),(C_str,sig_C_short)] if b]) if short_hits else 0

    # 趋势过滤
    if market == 'BEAR' and ratio < 0.97:
        long_hits = max(0, long_hits - 1)
    if market == 'BULL' and ratio > 1.03:
        short_hits = max(0, short_hits - 1)

    # 成交量确认
    vol_boost = 0.05 if vol_ratio >= 1.5 else 0

    def build_signal(direction, hits, strength, reasons):
        if hits < 2:
            return None
        conf = min(0.45 + hits * 0.15 + strength * 0.20 + vol_boost, 0.95)
        return {'direction': direction, 'confidence': conf, 'reason': '|'.join(reasons),
                'market': market, 'hits': hits, 'strength': strength, 'rsi': rsi14, 'bb_pos': bb_pos, 'ret3': ret3}

    long_reasons  = []
    short_reasons = []
    if sig_A_long:  long_reasons.append(f'RSI超卖({rsi14:.0f})')
    if sig_B_long:  long_reasons.append(f'BB下轨({bb_pos:.2f})')
    if sig_C_long:  long_reasons.append(f'短期超跌({ret3:.1f}%)')
    if sig_A_short: short_reasons.append(f'RSI超买({rsi14:.0f})')
    if sig_B_short: short_reasons.append(f'BB上轨({bb_pos:.2f})')
    if sig_C_short: short_reasons.append(f'短期超涨({ret3:.1f}%)')

    long_sig  = build_signal('LONG',  long_hits,  long_strength,  long_reasons)
    short_sig = build_signal('SHORT', short_hits, short_strength, short_reasons)

    if long_sig and short_sig:
        return long_sig if long_sig['confidence'] >= short_sig['confidence'] else short_sig
    elif long_sig:
        return long_sig
    elif short_sig:
        return short_sig

    return {'direction': 'NEUTRAL', 'confidence': 0,
            'reason': f'no_trigger(A:{int(sig_A_long)}/{int(sig_A_short)} '
                      f'B:{int(sig_B_long)}/{int(sig_B_short)} '
                      f'C:{int(sig_C_long)}/{int(sig_C_short)})',
            'market': market}
