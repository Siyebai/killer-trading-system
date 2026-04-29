#!/usr/bin/env python3
"""
杀手锏 v9.0 — 15分钟多因子信号引擎
数据基础：BTCUSDT 15m，90天，8640根

Alpha来源（实测，训练集验证）：
  - RSI7 < 21        做多  胜率54.8%
  - RSI7 > 78        做空  胜率59.6%
  - BB位置 < -0.88σ  做多  胜率57.2%
  - 3根动量 < -0.60% 做多  胜率58.4%
  - flow6 > 0.53     做空  胜率57.1%

策略逻辑：
  - 需要至少2个因子同向触发
  - 信号越多、越极端 → 置信度越高
  - 出场：RSI7 回中（50±10）OR BB中轨 OR 最长20根（5小时）
"""
import numpy as np


def _rsi(arr, p):
    if len(arr) < p + 1: return 50.0
    d  = np.diff(arr[-p-1:])
    g  = np.where(d > 0, d, 0.0)
    lo = np.where(d < 0, -d, 0.0)
    ag, al = g.mean(), lo.mean()
    return float(100 - 100 / (1 + ag / al)) if al > 0 else 100.0


def _bb(arr, p=20):
    """返回 (mid, upper, lower, pos)  pos = (cur-mid)/std"""
    if len(arr) < p:
        m = float(arr[-1]); return m, m, m, 0.0
    w   = np.array(arr[-p:], dtype=float)
    mid = float(w.mean())
    std = float(w.std()) or float(arr[-1]) * 0.005
    cur = float(arr[-1])
    return mid, mid + 2*std, mid - 2*std, (cur - mid) / std


def _atr(highs, lows, closes, p=14):
    trs = [max(highs[j]-lows[j],
               abs(highs[j]-closes[j-1]),
               abs(lows[j]-closes[j-1]))
           for j in range(-p, 0)]
    return float(np.mean(trs)) or float(closes[-1]) * 0.005


def _flow(tbvols, vols, n=6):
    t  = sum(vols[-n:])
    tb = sum(tbvols[-n:])
    return tb / t if t > 0 else 0.5


def generate_signal_v9(closes, highs, lows, opens, volumes,
                       taker_buy_vols=None, min_bars=25):
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'insufficient_data'}

    # 核心指标
    r7   = _rsi(closes, 7)
    r14  = _rsi(closes, 14)
    r2   = _rsi(closes, 2)
    bb_mid, bb_up, bb_lo, bb_pos = _bb(closes, 20)
    atr  = _atr(highs, lows, closes, 14)
    cur  = float(closes[-1])

    ret3 = (cur - float(closes[-4])) / float(closes[-4]) * 100 if n >= 4 else 0.0
    ret6 = (cur - float(closes[-7])) / float(closes[-7]) * 100 if n >= 7 else 0.0

    has_flow = taker_buy_vols is not None and len(taker_buy_vols) >= n
    flow6    = _flow(list(taker_buy_vols[-6:]), list(volumes[-6:])) if has_flow else 0.5

    # EMA50 趋势
    k50  = 2 / 51
    e50  = float(closes[-1])
    for v in list(closes)[-51:]:
        e50 = v * k50 + e50 * (1 - k50)
    trend = 'BULL' if cur > e50 * 1.002 else ('BEAR' if cur < e50 * 0.998 else 'FLAT')

    # ── LONG 信号计分 ─────────────────────────
    long_score  = 0.0
    long_tags   = []

    if r7 <= 21:
        s = min((21 - r7) / 21, 1.0)
        long_score += 1.0 + s * 0.5
        long_tags.append(f'RSI7超卖({r7:.0f})')
    elif r7 <= 30:
        long_score += 0.6
        long_tags.append(f'RSI7弱卖({r7:.0f})')

    if bb_pos <= -0.88:
        s = min((-0.88 - bb_pos) / 0.5, 1.0)
        long_score += 1.0 + s * 0.4
        long_tags.append(f'BB极下({bb_pos:.2f}σ)')
    elif bb_pos <= -0.5:
        long_score += 0.5
        long_tags.append(f'BB下({bb_pos:.2f}σ)')

    if ret3 <= -0.60:
        s = min((-0.60 - ret3) / 1.0, 1.0)
        long_score += 0.8 + s * 0.4
        long_tags.append(f'急跌({ret3:.2f}%)')
    elif ret3 <= -0.27:
        long_score += 0.4
        long_tags.append(f'跌({ret3:.2f}%)')

    if has_flow and flow6 <= 0.45:
        long_score += 0.5
        long_tags.append(f'买压弱({flow6:.2f})')

    # 趋势加成/减分
    if trend == 'BULL':  long_score += 0.3
    elif trend == 'BEAR': long_score -= 0.4

    # ── SHORT 信号计分 ────────────────────────
    short_score = 0.0
    short_tags  = []

    if r7 >= 78:
        s = min((r7 - 78) / 22, 1.0)
        short_score += 1.0 + s * 0.5
        short_tags.append(f'RSI7超买({r7:.0f})')
    elif r7 >= 70:
        short_score += 0.6
        short_tags.append(f'RSI7弱买({r7:.0f})')

    if bb_pos >= 0.88:
        s = min((bb_pos - 0.88) / 0.5, 1.0)
        short_score += 1.0 + s * 0.4
        short_tags.append(f'BB极上({bb_pos:.2f}σ)')
    elif bb_pos >= 0.5:
        short_score += 0.5
        short_tags.append(f'BB上({bb_pos:.2f}σ)')

    if ret3 >= 0.58:
        s = min((ret3 - 0.58) / 1.0, 1.0)
        short_score += 0.8 + s * 0.4
        short_tags.append(f'急涨({ret3:.2f}%)')
    elif ret3 >= 0.26:
        short_score += 0.4
        short_tags.append(f'涨({ret3:.2f}%)')

    if has_flow and flow6 >= 0.53:
        short_score += 0.8
        short_tags.append(f'买压强({flow6:.2f})')

    if trend == 'BEAR':  short_score += 0.3
    elif trend == 'BULL': short_score -= 0.4

    # ── 入场阈值：≥ 2.0分 ───────────────────
    THRESHOLD = 2.0

    long_score  = max(long_score, 0.0)
    short_score = max(short_score, 0.0)

    if long_score < THRESHOLD and short_score < THRESHOLD:
        return {
            'direction': 'NEUTRAL', 'confidence': 0,
            'reason': f'score_low(L:{long_score:.1f}/S:{short_score:.1f})',
        }

    if long_score >= THRESHOLD and short_score >= THRESHOLD:
        if long_score >= short_score:
            direction, score, tags = 'LONG', long_score, long_tags
        else:
            direction, score, tags = 'SHORT', short_score, short_tags
    elif long_score >= THRESHOLD:
        direction, score, tags = 'LONG', long_score, long_tags
    else:
        direction, score, tags = 'SHORT', short_score, short_tags

    conf = float(np.clip(0.55 + (score - THRESHOLD) * 0.08, 0.55, 0.92))

    return {
        'direction':  direction,
        'confidence': conf,
        'reason':     '|'.join(tags),
        'score':      score,
        'r7': r7, 'bb_pos': bb_pos, 'ret3': ret3,
        'flow6': float(flow6), 'trend': trend,
        'bb_mid': bb_mid,
    }
