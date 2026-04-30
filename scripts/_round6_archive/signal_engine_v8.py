# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
杀手锏交易系统 - 信号引擎 v8.0
基于专业学术框架：Larry Connors RSI(2) 均值回归系统

核心知识来源：
- Larry Connors RSI(2) 策略（10-period RSI 胜率 86.84%）
- Bollinger Band 标准参数（20周期, 2σ）
- 关键结论：固定止损降低均值回归策略收益，应用 RSI(2) 出场代替ATR止盈

参数框架（专业标准）：
  入场：RSI(14) < 30 AND 价格 < BB下轨(20,2σ) AND 短期超跌（2×条件双确认）
  出场：RSI(2) 上穿 65 → LONG平仓 / RSI(2) 下穿 35 → SHORT平仓
  备选出场：价格回到 BB 中轨（20日SMA） → 平仓（Connors 5日SMA变体）
  紧急出场：最多持仓 N 根K线（时间保护），无固定ATR止损
  仓位：每笔 2% 风险（标准均值回归仓位管理）
"""
import numpy as np


def calc_rsi(closes, period):
    """标准 Wilder RSI"""
    if len(closes) < period + 1:
        return 50.0
    diffs  = [closes[j] - closes[j-1] for j in range(-period, 0)]
    gains  = [max(d, 0) for d in diffs]
    losses = [abs(min(d, 0)) for d in diffs]
    ag = float(np.mean(gains))
    al = float(np.mean(losses))
    return float(100 - 100 / (1 + ag / al)) if al > 0 else 100.0


def calc_bollinger(closes, period=20, mult=2.0):
    """标准布林带 (20, 2σ) — Connors 推荐标准"""
    if len(closes) < period:
        m = float(closes[-1]); s = m * 0.01
        return m, m + mult*s, m - mult*s, s
    w   = np.array(closes[-period:], dtype=float)
    mid = float(np.mean(w))
    std = float(np.std(w, ddof=0)) or mid * 0.005
    return mid, mid + mult*std, mid - mult*std, std


def calc_atr(highs, lows, closes, period=14):
    trs = [max(highs[j]-lows[j],
               abs(highs[j]-closes[j-1]),
               abs(lows[j]-closes[j-1]))
           for j in range(-period, 0)]
    return float(np.mean(trs)) or float(closes[-1]) * 0.01


def ema_val(arr, period):
    k = 2 / (period + 1); e = float(arr[0])
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return e


def generate_signal_v8(closes, highs, lows, opens, volumes, min_bars=22):
    """
    v8.0 专业均值回归入场信号

    入场条件（双重确认 — 专业标准）：
    LONG:  RSI(14) < 30  AND  收盘价 < BB下轨(20,2σ)
    SHORT: RSI(14) > 70  AND  收盘价 > BB上轨(20,2σ)

    置信度加权：
    - RSI(2) < 5  → 极端超卖，加分（Connors 最高胜率区间）
    - RSI(14) < 25 → 更极端，加分
    - 连续下跌 K 线 → 加分（Connors 多日连跌入场法）
    - EMA200 趋势滤网（避免在强烈趋势中逆势做均值回归）
    """
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'insufficient_data', 'market': 'N/A'}

    cur = float(closes[-1])

    # ── 核心指标 ────────────────────────────────
    rsi14 = calc_rsi(closes, 14)
    rsi2  = calc_rsi(closes, 2) if n >= 4 else 50.0
    bb_mid, bb_up, bb_lo, bb_std = calc_bollinger(closes, 20, 2.0)
    bb_pos = (cur - bb_lo) / (bb_up - bb_lo) if (bb_up - bb_lo) > 0 else 0.5
    atr    = calc_atr(highs, lows, closes, 14)

    # EMA200 趋势背景
    ep     = min(200, n - 1)
    ema200 = ema_val(closes[max(0, n - ep*2):], ep)
    ratio  = cur / ema200
    market = 'BULL' if ratio >= 1.005 else ('BEAR' if ratio <= 0.995 else 'NEUTRAL_MKT')

    # 连续下跌/上涨 K 线数（Connors 经典多日连跌入场）
    consec_down = consec_up = 0
    for j in range(-1, -min(6, n), -1):
        if closes[j] < closes[j-1]: consec_down += 1
        else: break
    for j in range(-1, -min(6, n), -1):
        if closes[j] > closes[j-1]: consec_up += 1
        else: break

    # 短期动量（3根）
    ret3 = (cur - float(closes[-4])) / float(closes[-4]) * 100 if n >= 4 else 0.0

    # ── LONG 信号（必须满足：RSI14<30 AND 价格<BB下轨）──
    long_valid  = rsi14 < 30 and cur < bb_lo
    short_valid = rsi14 > 70 and cur > bb_up

    # ── 趋势滤网（避免在强烈趋势中硬拉均值回归）────
    # 大熊市（跌破EMA200超过3%）不做多；大牛市（超EMA200超3%）不做空
    if long_valid  and market == 'BEAR' and ratio < 0.97:
        long_valid = False
    if short_valid and market == 'BULL' and ratio > 1.03:
        short_valid = False

    if not long_valid and not short_valid:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': f'no_entry(RSI14:{rsi14:.0f} BB:{bb_pos:.2f})',
                'market': market, 'rsi14': rsi14, 'rsi2': rsi2}

    def score(is_long):
        s = 0.65  # 基础（双确认已满足）

        if is_long:
            if rsi14 < 25: s += 0.06   # 更极端超卖
            if rsi14 < 20: s += 0.04
            if rsi2  < 5:  s += 0.06   # Connors 最高胜率区间
            if rsi2  < 2:  s += 0.04
            if consec_down >= 3: s += 0.04  # 连跌3天，Connors经典信号
            if consec_down >= 4: s += 0.03
            if bb_pos < 0.0:   s += 0.04  # 价格完全突破BB下轨
            if ret3 < -atr/cur*100*1.5: s += 0.03  # 短期急跌加分
        else:
            if rsi14 > 75: s += 0.06
            if rsi14 > 80: s += 0.04
            if rsi2  > 95: s += 0.06
            if rsi2  > 98: s += 0.04
            if consec_up >= 3: s += 0.04
            if consec_up >= 4: s += 0.03
            if bb_pos > 1.0:   s += 0.04
            if ret3 > atr/cur*100*1.5: s += 0.03

        return min(float(s), 0.95)

    if long_valid and short_valid:
        ls, ss = score(True), score(False)
        direction = 'LONG' if ls >= ss else 'SHORT'
        confidence = ls if ls >= ss else ss
    elif long_valid:
        direction, confidence = 'LONG', score(True)
    else:
        direction, confidence = 'SHORT', score(False)

    return {
        'direction':   direction,
        'confidence':  confidence,
        'reason':      f'BB+RSI14({rsi14:.0f})+RSI2({rsi2:.0f})+consec({consec_down if direction=="LONG" else consec_up})',
        'market':      market,
        'rsi14':       rsi14,
        'rsi2':        rsi2,
        'bb_pos':      bb_pos,
        'bb_mid':      bb_mid,
        'consec_down': consec_down,
        'consec_up':   consec_up,
    }
