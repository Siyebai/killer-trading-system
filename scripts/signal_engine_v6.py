#!/usr/bin/env python3
"""
杀手锏交易系统 - 信号引擎 v6.0
策略：极端超卖/超买 + 多时间框架确认 + 高盈亏比退出

核心改变：
- 提高入场门槛到极端水平（RSI<25, BB突破2.5σ, 短期跌幅>3×ATR）
- 大幅减少交易次数，只做最高质量信号
- 目标：50笔高质量 > 200笔噪音
- 退出：固定止盈3×ATR，极宽止损4×ATR（盈亏比3:4→只需45%胜率盈利）
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
        return 50.0
    diffs  = [closes[j] - closes[j-1] for j in range(-period, 0)]
    gains  = [max(d, 0) for d in diffs]
    losses = [abs(min(d, 0)) for d in diffs]
    ag, al = np.mean(gains), np.mean(losses)
    return float(100 - (100 / (1 + ag/al))) if al > 0 else 50.0


def calc_bollinger(closes, period=20, mult=2.0):
    if len(closes) < period:
        m = float(closes[-1]); s = m * 0.01
        return m, m+mult*s, m-mult*s, s
    w   = np.array(closes[-period:], dtype=float)
    mid = float(np.mean(w))
    std = float(np.std(w)) or mid * 0.005
    return mid, mid + mult*std, mid - mult*std, std


def calc_atr(highs, lows, closes, period=14):
    trs = [max(highs[j]-lows[j],
               abs(highs[j]-closes[j-1]),
               abs(lows[j]-closes[j-1]))
           for j in range(-period, 0)]
    return float(np.mean(trs)) or float(closes[-1]) * 0.01


def stoch_rsi(closes, rsi_period=14, stoch_period=14):
    """Stochastic RSI — 更敏感的超买超卖"""
    if len(closes) < rsi_period + stoch_period:
        return 50.0
    # 计算RSI序列
    rsi_vals = []
    for i in range(stoch_period):
        idx = len(closes) - stoch_period + i
        rsi_vals.append(calc_rsi(closes[:idx+1], rsi_period))
    lo = min(rsi_vals); hi = max(rsi_vals)
    if hi == lo:
        return 50.0
    return (rsi_vals[-1] - lo) / (hi - lo) * 100


def volume_surge(volumes, period=20):
    """成交量爆发检测"""
    if len(volumes) < period + 1:
        return 1.0
    avg = float(np.mean(volumes[-period-1:-1]))
    return float(volumes[-1]) / avg if avg > 0 else 1.0


def get_funding_bias():
    try:
        fp = Path(__file__).parent.parent / "data" / "BTCUSDT_funding_rate.json"
        with open(fp) as f:
            data = json.load(f)
        rate = float(data[-1]['fundingRate'])
        if rate > 0.001:   return 0.0, 0.06
        elif rate < -0.0005: return 0.06, 0.0
    except:
        pass
    return 0.0, 0.0


def generate_signal_v6(closes, highs, lows, opens, volumes, min_bars=30):
    """
    v6.0: 极端条件入场，高盈亏比退出

    入场条件（需3项同时满足）：
    LONG：
      1. RSI(14) < 28 OR StochRSI < 15
      2. 价格在布林下轨外（bb_pos < 0.05）
      3. 3根K线跌幅 > 2×ATR%
      4. （加分）成交量爆发 > 1.5x

    SHORT：
      1. RSI(14) > 72 OR StochRSI > 85
      2. 价格在布林上轨外（bb_pos > 0.95）
      3. 3根K线涨幅 > 2×ATR%
      4. （加分）成交量爆发 > 1.5x
    """
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'insufficient_data', 'market': 'N/A'}

    cur = float(closes[-1])

    # 指标
    rsi   = calc_rsi(closes, 14)
    srsi  = stoch_rsi(closes) if n >= 28 else 50.0
    bb_mid, bb_up, bb_lo, bb_std = calc_bollinger(closes, 20)
    bb_pos = (cur - bb_lo) / (bb_up - bb_lo) if (bb_up - bb_lo) > 0 else 0.5
    atr   = calc_atr(highs, lows, closes)
    atr_pct = atr / cur * 100

    # 3根K线变化
    ret3 = (cur - float(closes[-4])) / float(closes[-4]) * 100 if n >= 4 else 0.0

    # 成交量
    vol_surge = volume_surge(volumes)

    # EMA200趋势背景
    ep     = min(200, n-1)
    ema200 = ema_val(closes[max(0,n-ep*2):], ep)
    ratio  = cur / ema200
    market = 'BULL' if ratio >= 1.005 else ('BEAR' if ratio <= 0.995 else 'NEUTRAL_MKT')

    # 资金费率
    bias_l, bias_s = get_funding_bias()

    # ── LONG 极端条件检查 ──────────────────────
    long_conds = []

    # 条件1：RSI极端
    if rsi <= 25:
        long_conds.append(f'RSI极卖({rsi:.0f})')
    elif rsi <= 28:
        long_conds.append(f'RSI超卖({rsi:.0f})')

    # 条件2：布林极端
    if bb_pos <= 0.03:
        long_conds.append(f'BB极下轨({bb_pos:.3f})')
    elif bb_pos <= 0.07:
        long_conds.append(f'BB下轨({bb_pos:.3f})')

    # 条件3：短期急跌
    if ret3 <= -atr_pct * 2.5:
        long_conds.append(f'急跌({ret3:.1f}%)')
    elif ret3 <= -atr_pct * 1.8:
        long_conds.append(f'超跌({ret3:.1f}%)')

    # 条件4（加分）：StochRSI极端 + 成交量
    bonus_l = 0
    if srsi <= 15:
        bonus_l += 1; long_conds.append(f'SRSI极卖({srsi:.0f})')
    if vol_surge >= 1.5:
        bonus_l += 1; long_conds.append(f'量爆({vol_surge:.1f}x)')

    # 趋势过滤
    if market == 'BEAR' and ratio < 0.96:
        long_conds = []  # 大熊市不做多

    # ── SHORT 极端条件检查 ─────────────────────
    short_conds = []

    if rsi >= 75:
        short_conds.append(f'RSI极买({rsi:.0f})')
    elif rsi >= 72:
        short_conds.append(f'RSI超买({rsi:.0f})')

    if bb_pos >= 0.97:
        short_conds.append(f'BB极上轨({bb_pos:.3f})')
    elif bb_pos >= 0.93:
        short_conds.append(f'BB上轨({bb_pos:.3f})')

    if ret3 >= atr_pct * 2.5:
        short_conds.append(f'急涨({ret3:.1f}%)')
    elif ret3 >= atr_pct * 1.8:
        short_conds.append(f'超涨({ret3:.1f}%)')

    bonus_s = 0
    if srsi >= 85:
        bonus_s += 1; short_conds.append(f'SRSI极买({srsi:.0f})')
    if vol_surge >= 1.5:
        bonus_s += 1; short_conds.append(f'量爆({vol_surge:.1f}x)')

    if market == 'BULL' and ratio > 1.04:
        short_conds = []  # 大牛市不做空

    # ── 信号决策：必须满足3项基础条件 ──────────
    # 每个条件1分，bonus条件0.5分
    # 基础3项（RSI+BB+动量）各计1分，需>=2分才触发

    def score(conds):
        s = 0
        for c in conds:
            if 'RSI' in c or 'SRSI' in c: s += 1
            elif 'BB' in c: s += 1
            elif '跌' in c or '涨' in c: s += 1
            elif '量' in c: s += 0.5
        return s

    l_score = score(long_conds)
    s_score = score(short_conds)

    THRESH = 2.5  # 基础3项里需≥2.5分（相当于3项全中或2+bonus）

    def make(direction, sc, conds, bias):
        if sc < THRESH:
            return None
        # 满足条件越多，置信度越高
        conf = min(0.60 + (sc - THRESH) * 0.10 + bias, 0.92)
        return {
            'direction': direction,
            'confidence': conf,
            'reason': '|'.join(conds),
            'market': market,
            'rsi': rsi,
            'bb_pos': bb_pos,
            'score': sc,
        }

    ls = make('LONG',  l_score, long_conds,  bias_l)
    ss = make('SHORT', s_score, short_conds, bias_s)

    if ls and ss:
        return ls if ls['confidence'] >= ss['confidence'] else ss
    return ls or ss or {
        'direction': 'NEUTRAL', 'confidence': 0,
        'reason': f'score_low(L:{l_score:.1f}/S:{s_score:.1f})',
        'market': market
    }
