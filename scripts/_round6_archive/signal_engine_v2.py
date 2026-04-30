# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
杀手锏交易系统 - 信号引擎 v2.0
核心改进：追涨 → 回调入场 + 多维度过滤

改进点：
1. LONG：等价格回调到 EMA21 附近再入，不追涨
2. SHORT：等价格反弹到 EMA21 附近再入，不追跌
3. 加 ADX 趋势强度过滤，震荡市不开仓
4. 加布林带位置过滤，极端位置反向
5. 量能确认：入场必须有放量
"""
import numpy as np


def ema_series(arr, period):
    """计算 EMA 序列（返回最后 N 个值）"""
    k = 2 / (period + 1)
    result = [arr[0]]
    for v in arr[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def calc_adx(highs, lows, closes, period=14):
    """计算 ADX 趋势强度"""
    if len(closes) < period * 2:
        return 25  # 默认中性
    
    h, l, c = highs[-period*2:], lows[-period*2:], closes[-period*2:]
    
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(c)):
        up   = h[i] - h[i-1]
        down = l[i-1] - l[i]
        plus_dm.append(up   if up > down and up > 0   else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr_list.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    
    tr_s  = sum(tr_list[-period:])
    pdm_s = sum(plus_dm[-period:])
    mdm_s = sum(minus_dm[-period:])
    
    if tr_s == 0:
        return 25
    
    pdi = 100 * pdm_s / tr_s
    mdi = 100 * mdm_s / tr_s
    dx  = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0
    return dx


def calc_bollinger(closes, period=20, std_mult=2.0):
    """布林带位置 0=下轨, 1=上轨"""
    if len(closes) < period:
        return 0.5
    window = closes[-period:]
    mid  = np.mean(window)
    std  = np.std(window)
    if std == 0:
        return 0.5
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return (closes[-1] - lower) / (upper - lower)


def generate_signal_v2(closes, highs, lows, volumes, min_bars=250):
    """
    信号生成 v2.0 — 回调入场策略

    返回: {'direction': 'LONG'/'SHORT'/'NEUTRAL', 'confidence': 0~1,
           'reason': str, 'market': str}
    """
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0, 'reason': 'insufficient_data', 'market': 'N/A'}

    # ── 基础指标 ──────────────────────────────
    def e(p): return ema_series(closes[max(0, n-p*3):], p)[-1]

    ema9   = e(9)
    ema21  = e(21)
    ema50  = e(50)
    ema200 = e(200)

    cur = closes[-1]
    atr_window = []
    for j in range(n-14, n):
        atr_window.append(max(
            highs[j] - lows[j],
            abs(highs[j] - closes[j-1]),
            abs(lows[j]  - closes[j-1])
        ))
    atr = np.mean(atr_window)

    # RSI(14)
    diffs  = [closes[j] - closes[j-1] for j in range(n-14, n)]
    gains  = [max(d, 0) for d in diffs]
    losses = [abs(min(d, 0)) for d in diffs]
    ag, al = np.mean(gains), np.mean(losses)
    rsi    = 100 - (100 / (1 + ag/al)) if al > 0 else 50

    # MACD
    macd_cur  = ema_series(closes[max(0,n-80):], 12)[-1] - ema_series(closes[max(0,n-80):], 26)[-1]
    macd_prev = ema_series(closes[max(0,n-81):-1], 12)[-1] - ema_series(closes[max(0,n-81):-1], 26)[-1]

    # ADX 趋势强度
    adx = calc_adx(highs, lows, closes)

    # 布林带位置
    bb_pos = calc_bollinger(closes)

    # 成交量
    vol_ma  = np.mean(volumes[-20:])
    vol_ratio = volumes[-1] / vol_ma if vol_ma > 0 else 1

    # ── 市场状态（EMA200）────────────────────
    ratio  = cur / ema200
    if ratio >= 1.008:
        market = 'BULL'
    elif ratio <= 0.992:
        market = 'BEAR'
    else:
        market = 'NEUTRAL'

    # ── ADX 过滤：趋势太弱不开仓 ─────────────
    if adx < 18:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': f'adx_too_weak({adx:.1f})', 'market': market}

    # ── 核心改进：回调入场条件 ────────────────

    # LONG 条件（回调入场，不追涨）
    long_score = 0
    long_reasons = []

    # 1. EMA 多头排列（趋势确认）
    if ema9 > ema21 > ema50 > ema200:
        long_score += 4
        long_reasons.append('EMA全多头')
    elif ema21 > ema50 and cur > ema200:
        long_score += 2
        long_reasons.append('EMA部分多头')

    # 2. ★核心★ 价格回调到 EMA21 附近（0.5~2.5 ATR 内），不在高位追涨
    dist_to_ema21 = cur - ema21
    if 0 < dist_to_ema21 < atr * 2.5:   # 在EMA21上方但不远
        long_score += 3
        long_reasons.append(f'回调至EMA21附近({dist_to_ema21/atr:.1f}ATR)')
    elif dist_to_ema21 > atr * 2.5:       # 价格太高，不追涨
        long_score -= 3
        long_reasons.append('价格过高禁追涨')

    # 3. RSI 回调到中性区（40-52），有反弹空间
    if 40 <= rsi <= 52:
        long_score += 3
        long_reasons.append(f'RSI回调区({rsi:.0f})')
    elif rsi < 40:
        long_score += 1
        long_reasons.append(f'RSI超卖({rsi:.0f})')
    elif rsi > 65:
        long_score -= 2  # 过热
        long_reasons.append(f'RSI过热({rsi:.0f})')

    # 4. MACD 动量向上
    if macd_cur > 0 and macd_cur > macd_prev:
        long_score += 2
        long_reasons.append('MACD动量向上')
    elif macd_cur > macd_prev and macd_cur > -abs(macd_cur)*0.3:
        long_score += 1
        long_reasons.append('MACD转强')

    # 5. 布林带位置适中（不在极端上方）
    if 0.3 <= bb_pos <= 0.7:
        long_score += 1
        long_reasons.append(f'BB中性区({bb_pos:.2f})')
    elif bb_pos > 0.85:
        long_score -= 2
        long_reasons.append('BB上轨过热')

    # 6. 成交量确认（有量才信号）
    if vol_ratio >= 1.3:
        long_score += 1
        long_reasons.append(f'放量({vol_ratio:.1f}x)')

    # SHORT 条件（反弹入场，不追跌）
    short_score = 0
    short_reasons = []

    if ema9 < ema21 < ema50 < ema200:
        short_score += 4
        short_reasons.append('EMA全空头')
    elif ema21 < ema50 and cur < ema200:
        short_score += 2
        short_reasons.append('EMA部分空头')

    dist_to_ema21_short = ema21 - cur
    if 0 < dist_to_ema21_short < atr * 2.5:
        short_score += 3
        short_reasons.append(f'反弹至EMA21附近({dist_to_ema21_short/atr:.1f}ATR)')
    elif dist_to_ema21_short > atr * 2.5:
        short_score -= 3
        short_reasons.append('价格过低禁追跌')

    if 48 <= rsi <= 60:
        short_score += 3
        short_reasons.append(f'RSI反弹区({rsi:.0f})')
    elif rsi > 60:
        short_score += 1
        short_reasons.append(f'RSI偏高({rsi:.0f})')
    elif rsi < 35:
        short_score -= 2
        short_reasons.append(f'RSI超卖({rsi:.0f})')

    if macd_cur < 0 and macd_cur < macd_prev:
        short_score += 2
        short_reasons.append('MACD动量向下')
    elif macd_cur < macd_prev and macd_cur < abs(macd_cur)*0.3:
        short_score += 1
        short_reasons.append('MACD转弱')

    if 0.3 <= bb_pos <= 0.7:
        short_score += 1
        short_reasons.append(f'BB中性区({bb_pos:.2f})')
    elif bb_pos < 0.15:
        short_score -= 2
        short_reasons.append('BB下轨过冷')

    if vol_ratio >= 1.3:
        short_score += 1
        short_reasons.append(f'放量({vol_ratio:.1f}x)')

    # ── 信号决策（趋势过滤 + 阈值）──────────
    LONG_THRESH  = 7
    SHORT_THRESH = 7

    if market == 'BULL' and long_score >= LONG_THRESH:
        conf = min(0.5 + (long_score - LONG_THRESH) * 0.08, 0.95)
        return {'direction': 'LONG', 'confidence': conf,
                'reason': '|'.join(long_reasons), 'market': market,
                'score': long_score, 'adx': adx}

    elif market == 'BEAR' and short_score >= SHORT_THRESH:
        conf = min(0.5 + (short_score - SHORT_THRESH) * 0.08, 0.95)
        return {'direction': 'SHORT', 'confidence': conf,
                'reason': '|'.join(short_reasons), 'market': market,
                'score': short_score, 'adx': adx}

    elif market == 'NEUTRAL':
        if long_score >= LONG_THRESH + 2:
            conf = min(0.5 + (long_score - LONG_THRESH - 2) * 0.07, 0.88)
            return {'direction': 'LONG', 'confidence': conf,
                    'reason': '|'.join(long_reasons), 'market': market,
                    'score': long_score, 'adx': adx}
        elif short_score >= SHORT_THRESH + 2:
            conf = min(0.5 + (short_score - SHORT_THRESH - 2) * 0.07, 0.88)
            return {'direction': 'SHORT', 'confidence': conf,
                    'reason': '|'.join(short_reasons), 'market': market,
                    'score': short_score, 'adx': adx}

    return {'direction': 'NEUTRAL', 'confidence': 0,
            'reason': f'no_signal(L:{long_score} S:{short_score} ADX:{adx:.0f})',
            'market': market}
