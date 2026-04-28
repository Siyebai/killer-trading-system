#!/usr/bin/env python3
"""
杀手锏交易系统 - 信号引擎 v5.0
在 v4.0 均值回归基础上叠加三层增强：
  1. 资金费率信号加权
  2. 4H 级别趋势确认（多周期共振）
  3. 动态止盈：持仓盈利超 1×ATR 后，止损移到保本，止盈延伸到 4.5×ATR
"""
import numpy as np
import json
from pathlib import Path


def ema_val(arr, period):
    k = 2 / (period + 1)
    e = float(arr[0])
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return e


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    diffs  = [closes[j] - closes[j-1] for j in range(-period, 0)]
    gains  = [max(d, 0) for d in diffs]
    losses = [abs(min(d, 0)) for d in diffs]
    ag, al = np.mean(gains), np.mean(losses)
    return float(100 - (100 / (1 + ag/al))) if al > 0 else 50


def calc_bollinger(closes, period=20):
    if len(closes) < period:
        mid = float(closes[-1]); std = mid * 0.01
        return mid, mid + 2*std, mid - 2*std, std
    w   = np.array(closes[-period:], dtype=float)
    mid = float(np.mean(w))
    std = float(np.std(w)) or mid * 0.005
    return mid, mid + 2*std, mid - 2*std, std


def calc_atr(highs, lows, closes, period=14):
    trs = [max(highs[j] - lows[j],
               abs(highs[j] - closes[j-1]),
               abs(lows[j]  - closes[j-1]))
           for j in range(-period, 0)]
    return float(np.mean(trs)) or float(closes[-1]) * 0.01


def pct_change_n(closes, n):
    if len(closes) <= n:
        return 0.0
    return (closes[-1] - closes[-n-1]) / closes[-n-1] * 100


def get_funding_bias():
    """读取资金费率文件，返回 (bias_long, bias_short) 偏置"""
    try:
        fp = Path(__file__).parent.parent / "data" / "BTCUSDT_funding_rate.json"
        with open(fp) as f:
            data = json.load(f)
        rate = float(data[-1]['fundingRate'])
        if rate > 0.001:       # 多头付空头：做空有利
            return 0.0, 0.08
        elif rate < -0.0005:   # 空头付多头：做多有利
            return 0.08, 0.0
        elif rate > 0.0005:
            return 0.0, 0.04
        elif rate < -0.0002:
            return 0.04, 0.0
    except:
        pass
    return 0.0, 0.0


def build_4h_closes(closes_1h):
    """把 1H K线聚合成 4H，返回最近 60 根"""
    n = len(closes_1h)
    result = []
    for i in range(3, n, 4):
        result.append(closes_1h[i])
    return result[-60:]


def get_4h_trend(closes_1h):
    """
    基于 1H 数据合成 4H 趋势
    返回: 'BULL' / 'BEAR' / 'NEUTRAL'
    """
    c4h = build_4h_closes(closes_1h)
    if len(c4h) < 52:
        return 'NEUTRAL'
    ema21_4h  = ema_val(c4h[-45:], 21)
    ema50_4h  = ema_val(c4h,       50)
    cur4h     = c4h[-1]
    if cur4h > ema21_4h > ema50_4h:
        return 'BULL'
    elif cur4h < ema21_4h < ema50_4h:
        return 'BEAR'
    return 'NEUTRAL'


def generate_signal_v5(closes, highs, lows, opens, volumes, min_bars=50):
    """
    信号引擎 v5.0
    = v4.0 均值回归 + 资金费率 + 4H趋势 + 动态止盈标记
    """
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'insufficient_data', 'market': 'N/A',
                'trailing': False}

    cur  = float(closes[-1])
    prev = float(closes[-2]) if n >= 2 else cur

    # 指标
    rsi14 = calc_rsi(closes, 14)
    bb_mid, bb_upper, bb_lower, bb_std = calc_bollinger(closes)
    atr   = calc_atr(highs, lows, closes)
    bb_range = (bb_upper - bb_lower) or 1e-9
    bb_pos   = (cur - bb_lower) / bb_range
    ret3     = pct_change_n(closes, 3)
    ret6     = pct_change_n(closes, 6)
    vol_ma   = float(np.mean(volumes[-20:])) if n >= 20 else float(volumes[-1])
    vol_ratio = float(volumes[-1]) / vol_ma if vol_ma > 0 else 1.0

    # EMA200 趋势
    ep = min(200, n - 1)
    ema200 = ema_val(closes[max(0, n - ep*2):], ep)
    ratio  = cur / ema200
    market = 'BULL' if ratio >= 1.005 else ('BEAR' if ratio <= 0.995 else 'NEUTRAL_MKT')

    # 4H 趋势
    trend4h = get_4h_trend(list(closes))

    # 资金费率偏置
    bias_long, bias_short = get_funding_bias()

    # ── 信号 A：RSI 极端 ───────────────────────
    sig_A_long = sig_A_short = False
    A_str = 0.0
    if rsi14 <= 28:
        sig_A_long = True;  A_str = (30 - rsi14) / 30
    elif rsi14 >= 72:
        sig_A_short = True; A_str = (rsi14 - 70) / 30

    # ── 信号 B：布林带极端 ──────────────────────
    sig_B_long = sig_B_short = False
    B_str = 0.0
    if bb_pos <= 0.08:
        sig_B_long  = True; B_str = min((bb_lower - cur) / bb_std + 1, 1.5) / 1.5
    elif bb_pos >= 0.92:
        sig_B_short = True; B_str = min((cur - bb_upper) / bb_std + 1, 1.5) / 1.5
    B_str = max(B_str, 0.0)

    # ── 信号 C：短期超涨超跌 ────────────────────
    sig_C_long = sig_C_short = False
    C_str = 0.0
    atr_pct = atr / cur * 100
    if ret3 < -atr_pct * 1.1:
        sig_C_long  = True; C_str = min(abs(ret3) / (atr_pct * 2), 1.0)
    elif ret3 > atr_pct * 1.1:
        sig_C_short = True; C_str = min(ret3 / (atr_pct * 2), 1.0)
    if not sig_C_long  and ret6 < -atr_pct * 1.6:
        sig_C_long  = True; C_str = max(C_str, min(abs(ret6)/(atr_pct*2.5), 0.8))
    if not sig_C_short and ret6 > atr_pct * 1.6:
        sig_C_short = True; C_str = max(C_str, min(ret6/(atr_pct*2.5), 0.8))

    long_hits  = sum([sig_A_long,  sig_B_long,  sig_C_long])
    short_hits = sum([sig_A_short, sig_B_short, sig_C_short])

    def avg_str(bits, strs):
        vals = [s for s, b in zip(strs, bits) if b]
        return float(np.mean(vals)) if vals else 0.0

    long_str  = avg_str([sig_A_long,  sig_B_long,  sig_C_long],  [A_str, B_str, C_str])
    short_str = avg_str([sig_A_short, sig_B_short, sig_C_short], [A_str, B_str, C_str])

    # ── 趋势过滤调整票数 ────────────────────────
    # EMA200 过滤
    if market == 'BEAR' and ratio < 0.97:
        long_hits = max(0, long_hits - 1)
    if market == 'BULL' and ratio > 1.03:
        short_hits = max(0, short_hits - 1)

    # 4H 趋势同向加一票，逆向减一票
    if trend4h == 'BULL':
        long_hits  = min(long_hits  + 1, 3)
        short_hits = max(short_hits - 1, 0)
    elif trend4h == 'BEAR':
        short_hits = min(short_hits + 1, 3)
        long_hits  = max(long_hits  - 1, 0)

    # 成交量 boost
    vol_boost = 0.05 if vol_ratio >= 1.5 else 0.0

    def make_sig(direction, hits, strength, reasons, bias):
        if hits < 2:
            return None
        conf = min(0.45 + hits * 0.14 + strength * 0.18 + vol_boost + bias, 0.95)
        # 标记是否需要动态追踪止盈（三信号同触发）
        trailing = hits == 3
        return {
            'direction': direction,
            'confidence': conf,
            'reason': '|'.join(reasons),
            'market': market,
            'trend4h': trend4h,
            'hits': hits,
            'strength': strength,
            'rsi': rsi14,
            'bb_pos': bb_pos,
            'vol_ratio': vol_ratio,
            'trailing': trailing   # ← 动态止盈标记
        }

    long_reasons  = []
    short_reasons = []
    if sig_A_long:  long_reasons.append(f'RSI超卖({rsi14:.0f})')
    if sig_B_long:  long_reasons.append(f'BB下轨({bb_pos:.2f})')
    if sig_C_long:  long_reasons.append(f'超跌({ret3:.1f}%)')
    if sig_A_short: short_reasons.append(f'RSI超买({rsi14:.0f})')
    if sig_B_short: short_reasons.append(f'BB上轨({bb_pos:.2f})')
    if sig_C_short: short_reasons.append(f'超涨({ret3:.1f}%)')
    if trend4h != 'NEUTRAL':
        (long_reasons if trend4h=='BULL' else short_reasons).append(f'4H{trend4h}')

    ls = make_sig('LONG',  long_hits,  long_str,  long_reasons,  bias_long)
    ss = make_sig('SHORT', short_hits, short_str, short_reasons, bias_short)

    if ls and ss:
        return ls if ls['confidence'] >= ss['confidence'] else ss
    return ls or ss or {
        'direction': 'NEUTRAL', 'confidence': 0,
        'reason': f'no_sig(A:{int(sig_A_long)}/{int(sig_A_short)} '
                  f'B:{int(sig_B_long)}/{int(sig_B_short)} '
                  f'C:{int(sig_C_long)}/{int(sig_C_short)})',
        'market': market, 'trailing': False
    }
