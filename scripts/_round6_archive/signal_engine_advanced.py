# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
杀手锏 — 高级策略引擎 v2.0
基于专业研究文献实现的4个策略：
1. SuperTrend (ATR动态趋势线, BTC日线实测profit factor>4)
2. Williams %R (S&P500实测70-80%胜率，<-80超卖买入)
3. CME缺口回填 (BTC周末缺口65-98%填充率)
4. SuperTrend + Williams %R 组合 (趋势+动量双确认)
"""
import numpy as np


def _atr(highs, lows, closes, p=14):
    if len(closes) < p + 1:
        return float(closes[-1]) * 0.01
    trs = [max(float(highs[j]) - float(lows[j]),
               abs(float(highs[j]) - float(closes[j-1])),
               abs(float(lows[j]) - float(closes[j-1])))
           for j in range(-p, 0)]
    return float(np.mean(trs))


def _williams_r(highs, lows, closes, p=14):
    """Williams %R: 0~-100，< -80超卖，> -20超买"""
    if len(closes) < p:
        return -50.0
    h = max(float(x) for x in highs[-p:])
    l = min(float(x) for x in lows[-p:])
    c = float(closes[-1])
    return float((h - c) / (h - l) * -100) if (h - l) > 0 else -50.0


def _supertrend(highs, lows, closes, period=10, mult=3.0):
    """
    SuperTrend 方向：1=多头，-1=空头
    返回 (方向, 止损线)
    需要至少 period+2 根K线
    """
    n = len(closes)
    if n < period + 2:
        return 0, float(closes[-1])

    # 计算所有 ATR 和基础上下轨
    atrs = []
    for i in range(1, n):
        tr = max(float(highs[i]) - float(lows[i]),
                 abs(float(highs[i]) - float(closes[i-1])),
                 abs(float(lows[i]) - float(closes[i-1])))
        atrs.append(tr)

    # 简化：只用最后 period 根
    atr_val = float(np.mean(atrs[-period:]))
    hl2 = (float(highs[-1]) + float(lows[-1])) / 2
    upper = hl2 + mult * atr_val
    lower = hl2 - mult * atr_val

    # 用最近几根确认趋势方向
    prev_hl2 = (float(highs[-2]) + float(lows[-2])) / 2
    prev_atr = float(np.mean(atrs[-period-1:-1]))
    prev_upper = prev_hl2 + mult * prev_atr
    prev_lower = prev_hl2 - mult * prev_atr

    cur = float(closes[-1])
    prev = float(closes[-2])

    # 趋势判断
    if prev <= prev_upper and cur > upper:
        direction = 1   # 突破上轨，多头
        stop = lower
    elif prev >= prev_lower and cur < lower:
        direction = -1  # 跌破下轨，空头
        stop = upper
    else:
        # 维持前一方向
        direction = 1 if cur > lower else -1
        stop = lower if direction == 1 else upper

    return direction, stop


# ── 策略1: SuperTrend 趋势跟踪 ──────────────────────────────────
def sig_supertrend(closes, highs, lows, i, period=10, mult=3.0):
    """
    SuperTrend经典策略：
    - 价格突破SuperTrend上轨→做多
    - 价格跌破SuperTrend下轨→做空
    conf由ATR倍数决定
    """
    if i < period + 5:
        return 0, 0.0
    direction, stop = _supertrend(highs[:i+1], lows[:i+1], closes[:i+1], period, mult)
    prev_dir, _ = _supertrend(highs[:i], lows[:i], closes[:i], period, mult)

    # 只在方向切换时入场（趋势翻转）
    if direction != prev_dir and direction != 0:
        atr_v = _atr(highs[:i+1], lows[:i+1], closes[:i+1], period)
        dist = abs(float(closes[i]) - stop)
        conf = min(dist / (atr_v * mult) if atr_v > 0 else 0.5, 1.0)
        return direction, max(conf, 0.4)
    return 0, 0.0


# ── 策略2: Williams %R 均值回归 ──────────────────────────────────
def sig_williams_r(closes, highs, lows, i, period=14, ob=-20, os=-80):
    """
    Williams %R 策略（Quantified Strategies文献: S&P 500实测70-80%胜率）：
    - %R < -80 (超卖) → 做多
    - %R > -20 (超买) → 做空
    - 需要前一根不在极值区确认反转
    """
    if i < period + 2:
        return 0, 0.0
    wr_cur = _williams_r(highs[:i+1], lows[:i+1], closes[:i+1], period)
    wr_prev = _williams_r(highs[:i], lows[:i], closes[:i], period)

    if wr_cur <= os and wr_prev > os:
        # 刚进入超卖区
        conf = min(abs(wr_cur - os) / 20.0, 1.0) * 0.9 + 0.1
        return 1, conf
    elif wr_cur >= ob and wr_prev < ob:
        # 刚进入超买区
        conf = min(abs(wr_cur - ob) / 20.0, 1.0) * 0.9 + 0.1
        return -1, conf
    # 极值持续加仓
    elif wr_cur < -90:
        return 1, 0.5
    elif wr_cur > -10:
        return -1, 0.5
    return 0, 0.0


# ── 策略3: CME缺口回填 ──────────────────────────────────────────
def sig_cme_gap(closes, highs, lows, i, gap_min_pct=0.003):
    """
    BTC CME缺口回填（研究数据：65-98%填充率）：
    - 识别跳空缺口（开盘价与上根收盘价差 > 0.3%）
    - 缺口向上(gap up)→做空，期待回填
    - 缺口向下(gap down)→做多，期待回填
    注：1H K线可近似识别缺口
    """
    if i < 5:
        return 0, 0.0
    prev_close = float(closes[i-1])
    cur_open = float(closes[i])   # 用收盘价近似（K线数据无单独开盘时间）
    # 用最近价格跳变估算缺口
    gap_pct = (cur_open - prev_close) / prev_close

    if gap_pct < -gap_min_pct:
        # 向下跳空，做多期待填充
        conf = min(abs(gap_pct) / 0.02, 1.0)
        return 1, conf
    elif gap_pct > gap_min_pct:
        # 向上跳空，做空期待填充
        conf = min(abs(gap_pct) / 0.02, 1.0)
        return -1, conf
    return 0, 0.0


# ── 策略4: SuperTrend + Williams %R 组合 ────────────────────────
def sig_st_wr_combo(closes, highs, lows, i, st_period=10, st_mult=3.0, wr_period=14):
    """
    SuperTrend趋势方向 × Williams %R超卖/超买确认
    逻辑：顺势做均值回归
    - SuperTrend方向=多头 + WR超卖(<-80) → 做多（顺势买入超卖回调）
    - SuperTrend方向=空头 + WR超买(>-20) → 做空（顺势卖出超买反弹）
    研究依据：趋势过滤可将均值回归胜率提升8-12%
    """
    if i < max(st_period, wr_period) + 5:
        return 0, 0.0

    st_dir, _ = _supertrend(highs[:i+1], lows[:i+1], closes[:i+1], st_period, st_mult)
    wr = _williams_r(highs[:i+1], lows[:i+1], closes[:i+1], wr_period)
    wr_prev = _williams_r(highs[:i], lows[:i], closes[:i], wr_period)

    if st_dir == 1 and wr <= -80 and wr_prev > -80:
        # 多头趋势中的超卖回调
        conf = 0.6 + min(abs(wr + 80) / 20.0, 0.35)
        return 1, conf
    elif st_dir == -1 and wr >= -20 and wr_prev < -20:
        # 空头趋势中的超买反弹
        conf = 0.6 + min(abs(wr + 20) / 20.0, 0.35)
        return -1, conf
    return 0, 0.0


STRATEGY_CATALOG = {
    "SuperTrend":    sig_supertrend,
    "Williams%R":    sig_williams_r,
    "CME缺口回填":   sig_cme_gap,
    "ST+WR组合":     sig_st_wr_combo,
}
