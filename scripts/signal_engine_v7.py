#!/usr/bin/env python3
"""
杀手锏交易系统 - 信号引擎 v7.0
核心 alpha：量价背离（Order Flow Divergence）

发现：
  - 价格创20根新高 + 近6根买压均值<0.50 → 做空  胜率57.2%(236笔)
  - 价格创20根新低 + 近6根卖压均值>0.50 → 做多  胜率53.0%(100笔)
  - 单根极端买压>0.65 → LONG 胜率56.5%(23笔)

策略：
  主信号 = 量价背离（必须满足）
  增强确认 = RSI/BB/ATR动量（≥1项加分）
  盈亏比目标 = 2.5:1（SL=1.5ATR, TP=3.75ATR）
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
    return float(100 - (100 / (1 + ag / al))) if al > 0 else 50.0


def calc_bollinger(closes, period=20):
    if len(closes) < period:
        m = float(closes[-1]); s = m * 0.01
        return m, m + 2*s, m - 2*s, s
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


def get_flow_ratio(tbvol, vol, n=6):
    """近n根累积主动买压比"""
    t = sum(vol[-n:])
    tb = sum(tbvol[-n:])
    return tb / t if t > 0 else 0.5


def generate_signal_v7(closes, highs, lows, opens, volumes,
                       taker_buy_vols=None, min_bars=25):
    """
    v7.0 量价背离信号引擎

    requires: taker_buy_vols 列表（从 BTCUSDT_1h_futures.json 读取）
    fallback: 如无 taker_buy 数据则降级到 v4 均值回归逻辑
    """
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'insufficient_data', 'market': 'N/A'}

    cur = float(closes[-1])

    # 基础指标
    rsi      = calc_rsi(closes, 14)
    bb_mid, bb_up, bb_lo, bb_std = calc_bollinger(closes, 20)
    bb_pos   = (cur - bb_lo) / (bb_up - bb_lo) if (bb_up - bb_lo) > 0 else 0.5
    atr      = calc_atr(highs, lows, closes)
    atr_pct  = atr / cur * 100

    # EMA200
    ep     = min(200, n - 1)
    ema200 = ema_val(closes[max(0, n - ep*2):], ep)
    ratio  = cur / ema200
    market = 'BULL' if ratio >= 1.005 else ('BEAR' if ratio <= 0.995 else 'NEUTRAL_MKT')

    ret3 = (cur - float(closes[-4])) / float(closes[-4]) * 100 if n >= 4 else 0.0

    # ── 量价背离主信号（需要 taker_buy 数据）──────
    has_flow = taker_buy_vols is not None and len(taker_buy_vols) >= n
    flow_long = flow_short = False
    flow_conf = 0.0

    if has_flow:
        tbv = list(taker_buy_vols)
        # 近6根累积买压比
        flow6  = get_flow_ratio(tbv[-6:], list(volumes)[-6:], 6)
        flow3  = get_flow_ratio(tbv[-3:], list(volumes)[-3:], 3)

        # 价格创近20根新高 + 买压弱 → 做空
        hi20 = max(closes[-21:-1]) if n >= 21 else max(closes[:-1])
        lo20 = min(closes[-21:-1]) if n >= 21 else min(closes[:-1])

        if cur >= hi20 * 0.999 and flow6 < 0.50:
            flow_short = True
            flow_conf  = 0.55 + (0.50 - flow6) * 1.5  # 买压越弱置信度越高

        elif cur <= lo20 * 1.001 and flow6 > 0.50:
            flow_long  = True
            flow_conf  = 0.55 + (flow6 - 0.50) * 1.5

        # 单根极端买压（>0.65 做多；<0.35 做空）
        last_ratio = tbv[-1] / volumes[-1] if volumes[-1] > 0 else 0.5
        if last_ratio >= 0.65 and not flow_short:
            flow_long  = True
            flow_conf  = max(flow_conf, 0.55 + (last_ratio - 0.65) * 2)
        elif last_ratio <= 0.35 and not flow_long:
            flow_short = True
            flow_conf  = max(flow_conf, 0.55 + (0.35 - last_ratio) * 2)

        flow_conf = min(flow_conf, 0.90)

    # ── 确认信号（加分，不是必须条件）──────────
    confirm_long = confirm_short = 0

    # RSI 确认
    if rsi <= 35:     confirm_long  += 1
    elif rsi >= 65:   confirm_short += 1

    # BB 确认
    if bb_pos <= 0.20:  confirm_long  += 1
    elif bb_pos >= 0.80: confirm_short += 1

    # 动量确认
    if ret3 < -atr_pct:  confirm_long  += 1
    elif ret3 > atr_pct: confirm_short += 1

    # ── 信号合并 ─────────────────────────────────
    direction = 'NEUTRAL'
    confidence = 0.0
    reasons = []

    if has_flow:
        if flow_long:
            direction  = 'LONG'
            confidence = flow_conf + confirm_long * 0.04
            reasons.append('量价背离做多')
        elif flow_short:
            direction  = 'SHORT'
            confidence = flow_conf + confirm_short * 0.04
            reasons.append('量价背离做空')
    else:
        # 降级：v4 均值回归
        if rsi <= 28 and bb_pos <= 0.08 and ret3 < -atr_pct * 1.5:
            direction  = 'LONG'
            confidence = 0.74
            reasons.append('均值回归_LONG(降级)')
        elif rsi >= 72 and bb_pos >= 0.92 and ret3 > atr_pct * 1.5:
            direction  = 'SHORT'
            confidence = 0.74
            reasons.append('均值回归_SHORT(降级)')

    if direction == 'NEUTRAL':
        return {
            'direction': 'NEUTRAL', 'confidence': 0,
            'reason': (f'no_sig(flow:{int(flow_long)}/{int(flow_short)} '
                       f'flow6:{flow6:.2f} ' if has_flow else
                       f'no_sig(no_flow RSI:{rsi:.0f} BB:{bb_pos:.2f})'),
            'market': market
        }

    # 趋势过滤（避免顺势信号方向错误）
    if direction == 'LONG'  and market == 'BEAR' and ratio < 0.97:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'filtered_bear', 'market': market}
    if direction == 'SHORT' and market == 'BULL' and ratio > 1.03:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'filtered_bull', 'market': market}

    conf_cnt   = confirm_short if direction == 'SHORT' else confirm_long
    confidence = float(np.clip(confidence, 0.50, 0.92))
    return {
        'direction':  direction,
        'confidence': confidence,
        'reason':     '|'.join(reasons) + f'(conf{conf_cnt})',
        'market':     market,
        'rsi':        rsi,
        'bb_pos':     bb_pos,
        'flow6':      float(flow6) if has_flow else None,
    }
