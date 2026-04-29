#!/usr/bin/env python3
"""
杀手锏交易系统 - 信号引擎 v3.0
核心洞察：EMA全排列 = 趋势已结束 = 追高陷阱

v2.0 的错误：给"EMA全多头"加分 → 越高分越是追高 → 胜率反而更低
v3.0 的修正：
  1. 惩罚全排列（过热），奖励"刚刚确认"（早期信号）
  2. 进场条件：价格触碰 EMA21 后出现反转K线（确认弹起/压回）
  3. 短周期动量：3根K线斜率判断最近动量方向
  4. 量能加权：入场K线成交量必须 > 均量
"""
import numpy as np


def ema_series(arr, period):
    k = 2 / (period + 1)
    result = [float(arr[0])]
    for v in arr[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def calc_adx(highs, lows, closes, period=14):
    n = len(closes)
    if n < period * 2 + 1:
        return 20
    h, l, c = highs[-(period*2+1):], lows[-(period*2+1):], closes[-(period*2+1):]
    pdm, mdm, trs = [], [], []
    for i in range(1, len(c)):
        up, dn = h[i]-h[i-1], l[i-1]-l[i]
        pdm.append(up if up>dn and up>0 else 0)
        mdm.append(dn if dn>up and dn>0 else 0)
        trs.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    tr_s  = sum(trs[-period:]) or 1e-9
    pdi   = 100 * sum(pdm[-period:]) / tr_s
    mdi   = 100 * sum(mdm[-period:]) / tr_s
    dx    = 100 * abs(pdi-mdi) / (pdi+mdi) if (pdi+mdi) > 0 else 0
    return dx


def slope3(arr):
    """3根K线的平均斜率（归一化）"""
    if len(arr) < 3:
        return 0
    mid = arr[-2]
    if mid == 0:
        return 0
    return ((arr[-1] - arr[-3]) / (2 * mid)) * 100


def reversal_candle(opens, closes, highs, lows, direction):
    """
    检测反转K线形态
    LONG：阳线（收盘>开盘）且影线较小
    SHORT：阴线（收盘<开盘）且影线较小
    返回 0~1 的信号强度
    """
    if len(closes) < 2:
        return 0
    o, c, h, l = opens[-1], closes[-1], highs[-1], lows[-1]
    body = abs(c - o)
    full = h - l or 1e-9
    body_ratio = body / full  # 实体占比，越大越干净

    if direction == 'LONG':
        if c > o and body_ratio > 0.4:  # 阳线，实体占40%+
            # 额外加分：收盘靠近最高
            upper_shadow = (h - c) / full
            return min(body_ratio + (1 - upper_shadow) * 0.3, 1.0)
    elif direction == 'SHORT':
        if c < o and body_ratio > 0.4:  # 阴线
            lower_shadow = (c - l) / full
            return min(body_ratio + (1 - lower_shadow) * 0.3, 1.0)
    return 0


def generate_signal_v3(closes, highs, lows, opens, volumes, min_bars=250):
    """
    信号生成 v3.0 — 触碰均线后反转入场

    核心逻辑：
    1. 趋势确认（EMA200方向）
    2. 等价格回调/反弹到 EMA21（触碰均线）
    3. 当前K线出现反转形态（弹起/压回）
    4. 短期动量刚刚转向
    5. 成交量确认
    """
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'insufficient_data', 'market': 'N/A'}

    def e(p):
        return ema_series(closes[max(0, n - p * 3):], p)[-1]

    ema9   = e(9)
    ema21  = e(21)
    ema50  = e(50)
    ema200 = e(200)

    cur  = closes[-1]
    prev = closes[-2] if n >= 2 else cur

    # ATR
    atr_w = [max(highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1]))
             for j in range(n-14, n)]
    atr = np.mean(atr_w) or cur * 0.01

    # RSI(9) — 更敏感
    diffs  = [closes[j]-closes[j-1] for j in range(n-9, n)]
    gains  = [max(d, 0) for d in diffs]
    losses = [abs(min(d, 0)) for d in diffs]
    ag, al = np.mean(gains), np.mean(losses)
    rsi = 100 - (100/(1+ag/al)) if al > 0 else 50

    # 短期动量（3根K线斜率）
    mom3 = slope3(closes[n-3:n])

    # ADX
    adx = calc_adx(highs, lows, closes)

    # 成交量
    vol_ma    = np.mean(volumes[-20:])
    vol_ratio = volumes[-1] / vol_ma if vol_ma > 0 else 1

    # 市场状态
    ratio = cur / ema200
    if ratio >= 1.008:
        market = 'BULL'
    elif ratio <= 0.992:
        market = 'BEAR'
    else:
        market = 'NEUTRAL_MKT'

    # ADX 过滤
    if adx < 20:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': f'adx_weak({adx:.0f})', 'market': market}

    # ── LONG 评分 ─────────────────────────────────────────────

    long_score = 0
    long_reasons = []

    # 1. 趋势背景（ema200方向）
    if cur > ema200 * 1.003:
        long_score += 2
        long_reasons.append('价格在EMA200上方')
    elif cur < ema200 * 0.997:
        long_score -= 4  # 在EMA200下方不做多
        long_reasons.append('趋势不利做多')

    # 2. ★核心★ 刚触碰EMA21（触碰后弹起，不是全排列）
    dist_ema21 = (cur - ema21) / atr
    prev_dist  = (prev - ema21) / atr

    if -0.5 <= dist_ema21 <= 1.2 and prev_dist < dist_ema21:
        # 价格在EMA21附近且在向上弹
        long_score += 4
        long_reasons.append(f'EMA21弹起({dist_ema21:.1f}ATR)')
    elif -1.5 <= dist_ema21 < -0.5:
        # 略低于EMA21，可能还在回调
        long_score += 2
        long_reasons.append(f'EMA21下方回调({dist_ema21:.1f}ATR)')
    elif dist_ema21 > 2.5:
        # 太高了，追涨
        long_score -= 5
        long_reasons.append('价格过高禁追涨')

    # 3. EMA 部分排列（不要求全排列）
    if ema21 > ema50:
        long_score += 2
        long_reasons.append('EMA21>EMA50')
    if ema9 > ema21 and dist_ema21 < 1.5:
        long_score += 1
        long_reasons.append('EMA9>EMA21')
    # 全排列是追高信号，不加分

    # 4. RSI 回调区（40-55）
    if 40 <= rsi <= 55:
        long_score += 3
        long_reasons.append(f'RSI回调区({rsi:.0f})')
    elif rsi < 40:
        long_score += 2
        long_reasons.append(f'RSI超卖({rsi:.0f})')
    elif 55 < rsi <= 65:
        long_score += 0  # 中性
    elif rsi > 65:
        long_score -= 2  # 过热
        long_reasons.append(f'RSI过热({rsi:.0f})')

    # 5. 短期动量刚转正
    if mom3 > 0.05:
        long_score += 2
        long_reasons.append(f'动量转正({mom3:.2f}%)')
    elif mom3 > 0:
        long_score += 1
        long_reasons.append('动量微正')
    elif mom3 < -0.1:
        long_score -= 2
        long_reasons.append('动量仍负')

    # 6. 反转K线形态
    rev = reversal_candle(opens, closes, highs, lows, 'LONG')
    if rev > 0.6:
        long_score += 3
        long_reasons.append(f'反转阳线({rev:.2f})')
    elif rev > 0.3:
        long_score += 1
        long_reasons.append('弱阳线')

    # 7. 成交量
    if vol_ratio >= 1.4:
        long_score += 2
        long_reasons.append(f'放量({vol_ratio:.1f}x)')
    elif vol_ratio >= 1.1:
        long_score += 1

    # ── SHORT 评分 ───────────────────────────────────────────

    short_score = 0
    short_reasons = []

    if cur < ema200 * 0.997:
        short_score += 2
        short_reasons.append('价格在EMA200下方')
    elif cur > ema200 * 1.003:
        short_score -= 4
        short_reasons.append('趋势不利做空')

    dist_ema21_s = (ema21 - cur) / atr
    prev_dist_s  = (ema21 - prev) / atr

    if -0.5 <= dist_ema21_s <= 1.2 and prev_dist_s < dist_ema21_s:
        short_score += 4
        short_reasons.append(f'EMA21压回({dist_ema21_s:.1f}ATR)')
    elif -1.5 <= dist_ema21_s < -0.5:
        short_score += 2
        short_reasons.append(f'EMA21上方反弹({dist_ema21_s:.1f}ATR)')
    elif dist_ema21_s > 2.5:
        short_score -= 5
        short_reasons.append('价格过低禁追跌')

    if ema21 < ema50:
        short_score += 2
        short_reasons.append('EMA21<EMA50')
    if ema9 < ema21 and dist_ema21_s < 1.5:
        short_score += 1
        short_reasons.append('EMA9<EMA21')

    if 45 <= rsi <= 60:
        short_score += 3
        short_reasons.append(f'RSI反弹区({rsi:.0f})')
    elif rsi > 60:
        short_score += 2
        short_reasons.append(f'RSI偏高({rsi:.0f})')
    elif rsi < 35:
        short_score -= 2
        short_reasons.append(f'RSI超卖({rsi:.0f})')

    if mom3 < -0.05:
        short_score += 2
        short_reasons.append(f'动量转负({mom3:.2f}%)')
    elif mom3 < 0:
        short_score += 1
        short_reasons.append('动量微负')
    elif mom3 > 0.1:
        short_score -= 2
        short_reasons.append('动量仍正')

    rev_s = reversal_candle(opens, closes, highs, lows, 'SHORT')
    if rev_s > 0.6:
        short_score += 3
        short_reasons.append(f'反转阴线({rev_s:.2f})')
    elif rev_s > 0.3:
        short_score += 1
        short_reasons.append('弱阴线')

    if vol_ratio >= 1.4:
        short_score += 2
        short_reasons.append(f'放量({vol_ratio:.1f}x)')
    elif vol_ratio >= 1.1:
        short_score += 1

    # ── 信号决策 ─────────────────────────────────────────────
    THRESH = 8  # 提高阈值，减少低质量信号

    if market == 'BULL' and long_score >= THRESH:
        conf = min(0.50 + (long_score - THRESH) * 0.07, 0.92)
        return {'direction': 'LONG', 'confidence': conf,
                'reason': '|'.join(long_reasons), 'market': market,
                'score': long_score, 'adx': adx, 'rsi': rsi}

    elif market == 'BEAR' and short_score >= THRESH:
        conf = min(0.50 + (short_score - THRESH) * 0.07, 0.92)
        return {'direction': 'SHORT', 'confidence': conf,
                'reason': '|'.join(short_reasons), 'market': market,
                'score': short_score, 'adx': adx, 'rsi': rsi}

    elif market == 'NEUTRAL_MKT':
        if long_score >= THRESH + 2:
            conf = min(0.50 + (long_score - THRESH - 2) * 0.06, 0.85)
            return {'direction': 'LONG', 'confidence': conf,
                    'reason': '|'.join(long_reasons), 'market': market,
                    'score': long_score, 'adx': adx, 'rsi': rsi}
        elif short_score >= THRESH + 2:
            conf = min(0.50 + (short_score - THRESH - 2) * 0.06, 0.85)
            return {'direction': 'SHORT', 'confidence': conf,
                    'reason': '|'.join(short_reasons), 'market': market,
                    'score': short_score, 'adx': adx, 'rsi': rsi}

    return {'direction': 'NEUTRAL', 'confidence': 0,
            'reason': f'no_signal(L:{long_score} S:{short_score})',
            'market': market}
