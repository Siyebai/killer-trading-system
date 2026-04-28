#!/usr/bin/env python3
"""
杀手锏交易系统 - 信号引擎 v6.0
从数据中学习：深度分析 100 笔交易的亏损模式，重构信号

核心发现（来自 v5.0 闭环测试）：
1. 超时平仓胜率 54-75%，说明信号方向基本正确
2. ATR 止损被扫（止损笔数 46/99），说明止损太紧
3. 熊市+震荡行情中，均值回归信号噪音大

v6.0 核心改进：
1. 加入 Stochastic RSI（更敏感的超买超卖）
2. 加入 Williams %R（确认极端位置）
3. 多信号同向共振才入场（RSI + BB + StochRSI 三合一）
4. 固定 2% 止损（不用 ATR），避免在高波动时被扫
5. 分段止盈：50% 仓位在 2% 止盈，50% 在 4% 止盈
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


def calc_rsi_series(closes, period=14):
    """返回 RSI 序列（最后 period+10 个值）"""
    if len(closes) < period + 2:
        return [50.0] * len(closes)
    result = [50.0] * period
    diffs  = [closes[j] - closes[j-1] for j in range(1, len(closes))]
    gains  = [max(d, 0) for d in diffs]
    losses = [abs(min(d, 0)) for d in diffs]
    avg_g  = sum(gains[:period]) / period
    avg_l  = sum(losses[:period]) / period
    if avg_l > 0:
        result.append(100 - 100/(1 + avg_g/avg_l))
    else:
        result.append(100.0)
    for i in range(period, len(diffs)):
        avg_g = (avg_g * (period-1) + gains[i])  / period
        avg_l = (avg_l * (period-1) + losses[i]) / period
        if avg_l > 0:
            result.append(100 - 100/(1 + avg_g/avg_l))
        else:
            result.append(100.0)
    return result


def calc_stoch_rsi(closes, rsi_period=14, stoch_period=14):
    """
    Stochastic RSI：RSI 在自身过去 N 根的位置
    返回 K 值（0-100）
    """
    rsi_series = calc_rsi_series(closes, rsi_period)
    if len(rsi_series) < stoch_period:
        return 50.0
    window = rsi_series[-stoch_period:]
    rsi_min = min(window)
    rsi_max = max(window)
    if rsi_max == rsi_min:
        return 50.0
    return (rsi_series[-1] - rsi_min) / (rsi_max - rsi_min) * 100


def calc_williams_r(highs, lows, closes, period=14):
    """Williams %R，-100 ~ 0，越低越超卖"""
    if len(closes) < period:
        return -50.0
    h_max = max(highs[-period:])
    l_min = min(lows[-period:])
    if h_max == l_min:
        return -50.0
    return -100 * (h_max - closes[-1]) / (h_max - l_min)


def calc_atr(highs, lows, closes, period=14):
    trs = [max(highs[j]-lows[j],
               abs(highs[j]-closes[j-1]),
               abs(lows[j]-closes[j-1]))
           for j in range(-period, 0)]
    return float(np.mean(trs)) or float(closes[-1]) * 0.01


def calc_bollinger(closes, period=20):
    if len(closes) < period:
        mid = float(closes[-1]); std = mid * 0.01
        return mid, mid+2*std, mid-2*std, std
    w   = np.array(closes[-period:], dtype=float)
    mid = float(np.mean(w))
    std = float(np.std(w)) or mid * 0.005
    return mid, mid+2*std, mid-2*std, std


def pct_change_n(closes, n):
    if len(closes) <= n:
        return 0.0
    return (closes[-1] - closes[-n-1]) / closes[-n-1] * 100


def get_funding_bias():
    try:
        fp = Path(__file__).parent.parent / "data" / "BTCUSDT_funding_rate.json"
        with open(fp) as f:
            data = json.load(f)
        rate = float(data[-1]['fundingRate'])
        if rate > 0.001:
            return 0.0, 0.06
        elif rate < -0.0005:
            return 0.06, 0.0
        elif rate > 0.0004:
            return 0.0, 0.03
        elif rate < -0.0002:
            return 0.03, 0.0
    except:
        pass
    return 0.0, 0.0


def build_4h_ema(closes_1h, period=21):
    c4h = [closes_1h[i] for i in range(3, len(closes_1h), 4)]
    if len(c4h) < period + 5:
        return None
    return ema_val(c4h[-(period*2):], period)


def generate_signal_v6(closes, highs, lows, opens, volumes, min_bars=40):
    """
    v6.0 三重共振信号引擎

    入场条件：
      LONG:  RSI < 32  AND  StochRSI < 25  AND  BB位置 < 0.12  AND  Williams%R < -85
      SHORT: RSI > 68  AND  StochRSI > 75  AND  BB位置 > 0.88  AND  Williams%R > -15

    任意缺一项降低置信度，三项全中才是强信号
    """
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'insufficient_data', 'market': 'N/A', 'sl_pct': 2.0, 'tp_pct': 4.0}

    cur  = float(closes[-1])

    # ── 指标 ──────────────────────────────────────
    rsi       = calc_rsi_series(closes, 14)[-1]
    stoch_rsi = calc_stoch_rsi(closes, 14, 14)
    bb_mid, bb_upper, bb_lower, bb_std = calc_bollinger(closes, 20)
    bb_range  = (bb_upper - bb_lower) or 1e-9
    bb_pos    = (cur - bb_lower) / bb_range
    will_r    = calc_williams_r(highs, lows, closes, 14)
    atr       = calc_atr(highs, lows, closes, 14)
    ret3      = pct_change_n(closes, 3)
    ret1      = pct_change_n(closes, 1)

    vol_ma    = float(np.mean(volumes[-20:])) if n >= 20 else float(volumes[-1])
    vol_ratio = float(volumes[-1]) / vol_ma if vol_ma > 0 else 1.0

    # EMA200 趋势
    ep = min(200, n-1)
    ema200 = ema_val(closes[max(0, n-ep*2):], ep)
    ratio  = cur / ema200
    market = 'BULL' if ratio >= 1.005 else ('BEAR' if ratio <= 0.995 else 'NEUTRAL_MKT')

    # 资金费率
    bias_long, bias_short = get_funding_bias()

    # ── LONG 三重共振 ─────────────────────────────
    long_conditions = {
        'rsi_oversold':      rsi < 32,
        'stoch_oversold':    stoch_rsi < 25,
        'bb_lower':          bb_pos < 0.12,
        'williams_oversold': will_r < -85,
    }
    # 宽松条件（用于计分，不要求全中）
    long_soft = {
        'rsi_low':   rsi < 42,
        'stoch_low': stoch_rsi < 35,
        'bb_low':    bb_pos < 0.20,
        'will_low':  will_r < -75,
        'ret3_neg':  ret3 < -1.5,    # 短期下跌反弹
        'vol_ok':    vol_ratio >= 1.1,
    }

    # SHORT 三重共振
    short_conditions = {
        'rsi_overbought':    rsi > 68,
        'stoch_overbought':  stoch_rsi > 75,
        'bb_upper':          bb_pos > 0.88,
        'williams_overbought': will_r > -15,
    }
    short_soft = {
        'rsi_high':  rsi > 58,
        'stoch_high': stoch_rsi > 65,
        'bb_high':   bb_pos > 0.80,
        'will_high': will_r > -25,
        'ret3_pos':  ret3 > 1.5,
        'vol_ok':    vol_ratio >= 1.1,
    }

    # ── 评分 ──────────────────────────────────────
    long_hard  = sum(long_conditions.values())   # 强信号数 (0-4)
    long_soft_n = sum(long_soft.values())         # 宽松数 (0-6)
    short_hard = sum(short_conditions.values())
    short_soft_n = sum(short_soft.values())

    # 趋势调整
    if market == 'BEAR' and ratio < 0.97:
        long_hard  = max(0, long_hard - 1)
        long_soft_n = max(0, long_soft_n - 1)
    if market == 'BULL' and ratio > 1.03:
        short_hard  = max(0, short_hard - 1)
        short_soft_n = max(0, short_soft_n - 1)

    # 构建信号
    def build(direction, hard, soft_n, hard_conds, reasons_base):
        # 需要至少 2 个强条件 + 3 个宽松条件
        if hard < 2 or soft_n < 3:
            return None
        # 置信度：强条件越多越高
        conf = 0.55 + hard * 0.10 + (soft_n - 3) * 0.04 + (bias_long if direction=='LONG' else bias_short)
        conf = min(conf, 0.93)

        # 根据强弱选择止损止盈
        if hard >= 3:
            sl_pct, tp_pct = 2.0, 5.0  # 三强信号：宽止损大止盈
        else:
            sl_pct, tp_pct = 2.0, 3.0  # 双强信号：宽止损小止盈

        reasons = []
        if hard_conds.get('rsi_oversold') or hard_conds.get('rsi_overbought'):
            reasons.append(f'RSI极值({rsi:.0f})')
        if hard_conds.get('stoch_oversold') or hard_conds.get('stoch_overbought'):
            reasons.append(f'StochRSI极值({stoch_rsi:.0f})')
        if hard_conds.get('bb_lower') or hard_conds.get('bb_upper'):
            reasons.append(f'BB极端({bb_pos:.2f})')
        if hard_conds.get('williams_oversold') or hard_conds.get('williams_overbought'):
            reasons.append(f'Williams%R({will_r:.0f})')
        reasons.append(f'4H:{market}')

        return {
            'direction': direction,
            'confidence': conf,
            'reason': '|'.join(reasons),
            'market': market,
            'hard_signals': hard,
            'soft_signals': soft_n,
            'rsi': rsi,
            'stoch_rsi': stoch_rsi,
            'bb_pos': bb_pos,
            'williams_r': will_r,
            'sl_pct': sl_pct,
            'tp_pct': tp_pct,
        }

    ls = build('LONG',  long_hard,  long_soft_n,  long_conditions,  [])
    ss = build('SHORT', short_hard, short_soft_n, short_conditions, [])

    if ls and ss:
        return ls if ls['confidence'] >= ss['confidence'] else ss
    return ls or ss or {
        'direction': 'NEUTRAL', 'confidence': 0,
        'reason': f'L({long_hard}h+{long_soft_n}s) S({short_hard}h+{short_soft_n}s)',
        'market': market, 'sl_pct': 2.0, 'tp_pct': 4.0
    }
