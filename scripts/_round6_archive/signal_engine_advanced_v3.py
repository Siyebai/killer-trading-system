# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
杀手锏 — 高级策略引擎 v3.0（修复版）
策略：
1. SuperTrend v2   — 正确的有状态实现（Wilder ATR + 连续上下轨）
2. MACD+RSI背离   — 文献实测55-73%胜率
3. SuperTrend+RSI  — 趋势过滤×均值回归组合
4. MACD趋势跟踪   — MACD金叉×EMA趋势过滤
"""
import numpy as np


# ── 基础指标 ─────────────────────────────────────────────────────

def _wilder_atr(highs, lows, closes, period=10):
    """Wilder平滑ATR（与TradingView SuperTrend一致）"""
    n = len(closes)
    if n < period + 1:
        return float(closes[-1]) * 0.01
    trs = []
    for i in range(1, n):
        tr = max(float(highs[i]) - float(lows[i]),
                 abs(float(highs[i]) - float(closes[i-1])),
                 abs(float(lows[i]) - float(closes[i-1])))
        trs.append(tr)
    # Wilder平滑 = EMA with alpha=1/period
    atr = float(np.mean(trs[:period]))
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _compute_supertrend_series(highs, lows, closes, period=10, mult=3.0):
    """
    正确的SuperTrend序列计算（有状态，连续更新）
    返回 directions列表（1=多头, -1=空头）和 stops列表
    """
    n = len(closes)
    if n < period + 2:
        return [0] * n, [float(closes[-1])] * n

    # 先计算全序列Wilder ATR
    trs = [0.0]
    for i in range(1, n):
        tr = max(float(highs[i]) - float(lows[i]),
                 abs(float(highs[i]) - float(closes[i-1])),
                 abs(float(lows[i]) - float(closes[i-1])))
        trs.append(tr)

    atrs = [0.0] * n
    atrs[period] = float(np.mean(trs[1:period+1]))
    for i in range(period + 1, n):
        atrs[i] = (atrs[i-1] * (period - 1) + trs[i]) / period

    # 计算SuperTrend（有状态）
    final_upper = [0.0] * n
    final_lower = [0.0] * n
    directions = [0] * n
    stops = [float(closes[-1])] * n

    for i in range(period + 1, n):
        hl2 = (float(highs[i]) + float(lows[i])) / 2
        basic_upper = hl2 + mult * atrs[i]
        basic_lower = hl2 - mult * atrs[i]

        # 上轨：只能下调（棘轮效应）
        if i == period + 1:
            final_upper[i] = basic_upper
            final_lower[i] = basic_lower
        else:
            if basic_upper < final_upper[i-1] or float(closes[i-1]) > final_upper[i-1]:
                final_upper[i] = basic_upper
            else:
                final_upper[i] = final_upper[i-1]

            if basic_lower > final_lower[i-1] or float(closes[i-1]) < final_lower[i-1]:
                final_lower[i] = basic_lower
            else:
                final_lower[i] = final_lower[i-1]

        # 方向
        if float(closes[i]) > final_upper[i]:
            directions[i] = 1   # 多头
            stops[i] = final_lower[i]
        else:
            directions[i] = -1  # 空头
            stops[i] = final_upper[i]

    return directions, stops


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    d = np.diff(np.array(closes[-period-1:], dtype=float))
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    ag, al = g.mean(), l.mean()
    return float(100 - 100 / (1 + ag / al)) if al > 0 else 100.0


def _macd(closes, fast=12, slow=26, signal=9):
    """返回 (macd_line, signal_line, histogram)"""
    n = len(closes)
    if n < slow + signal:
        return 0., 0., 0.
    arr = np.array(closes, dtype=float)
    # EMA
    def ema_series(a, p):
        k = 2 / (p + 1); e = a[0]
        result = [e]
        for v in a[1:]: e = v * k + e * (1 - k); result.append(e)
        return np.array(result)
    ema_f = ema_series(arr, fast)
    ema_s = ema_series(arr, slow)
    macd_line = ema_f - ema_s
    sig_line = ema_series(macd_line[slow-1:], signal)
    hist = macd_line[slow-1:] - sig_line
    # 返回最新值
    ml = float(macd_line[-1])
    sl = float(sig_line[-1]) if len(sig_line) > 0 else 0.
    hi = float(hist[-1]) if len(hist) > 0 else 0.
    ml_prev = float(macd_line[-2]) if len(macd_line) > 1 else ml
    sl_prev = float(sig_line[-2]) if len(sig_line) > 1 else sl
    return ml, sl, hi, ml_prev, sl_prev


# ── 策略1: SuperTrend v2（正确实现）────────────────────────────

# 缓存：避免每根K线重算全序列
_st_cache = {}

def sig_supertrend_v2(closes, highs, lows, i, period=10, mult=3.0):
    """
    SuperTrend正确实现：有状态连续计算
    买入信号：方向从-1变为1（趋势翻多）
    卖出信号：方向从1变为-1（趋势翻空）
    """
    if i < period + 3:
        return 0, 0.0

    # 只计算到当前位置
    dirs, stops = _compute_supertrend_series(
        highs[:i+1], lows[:i+1], closes[:i+1], period, mult)

    cur_dir = dirs[i]
    prev_dir = dirs[i-1]

    if cur_dir != prev_dir and cur_dir != 0:
        atr_v = _wilder_atr(highs[:i+1], lows[:i+1], closes[:i+1], period)
        dist = abs(float(closes[i]) - stops[i])
        conf = min(0.5 + dist / (atr_v * mult + 1e-9) * 0.4, 0.95)
        return cur_dir, conf
    return 0, 0.0


# ── 策略2: MACD+RSI背离（文献55-73%胜率）──────────────────────

def sig_macd_rsi_divergence(closes, highs, lows, i):
    """
    MACD+RSI双重背离：
    - 价格新低 + RSI更高低点 + MACD金叉 → 做多（看涨背离）
    - 价格新高 + RSI更低高点 + MACD死叉 → 做空（看跌背离）
    参考：quantifiedstrategies.com 实测73%胜率（多头背离）
    """
    if i < 35:
        return 0, 0.0

    cur = float(closes[i])
    # 回溯窗口（5-20根找背离）
    lookback = min(20, i - 14)
    window_closes = closes[i-lookback:i+1]
    window_lows = lows[i-lookback:i+1]
    window_highs = highs[i-lookback:i+1]

    rsi_cur = _rsi(closes[:i+1], 14)
    rsi_prev = _rsi(closes[:i+1-lookback//2], 14)

    ml, sl, hi, ml_prev, sl_prev = _macd(closes[:i+1])

    # 看涨背离：价格低点更低，RSI低点更高，MACD从负转正
    price_lower_low = cur <= min(window_closes[:-1]) * 1.002
    rsi_higher_low = rsi_cur > rsi_prev and rsi_cur < 45
    macd_cross_up = ml > sl and ml_prev <= sl_prev and ml < 0  # 金叉且仍在零轴下

    if price_lower_low and rsi_higher_low and macd_cross_up:
        conf = 0.6 + min((45 - rsi_cur) / 45 * 0.3, 0.3)
        return 1, conf

    # 看跌背离：价格高点更高，RSI高点更低，MACD从正转负
    price_higher_high = cur >= max(window_closes[:-1]) * 0.998
    rsi_lower_high = rsi_cur < rsi_prev and rsi_cur > 55
    macd_cross_dn = ml < sl and ml_prev >= sl_prev and ml > 0  # 死叉且仍在零轴上

    if price_higher_high and rsi_lower_high and macd_cross_dn:
        conf = 0.6 + min((rsi_cur - 55) / 45 * 0.3, 0.3)
        return -1, conf

    return 0, 0.0


# ── 策略3: SuperTrend + RSI组合──────────────────────────────────

def sig_st_rsi(closes, highs, lows, i, period=10, mult=3.0):
    """
    顺势均值回归：
    - SuperTrend多头 + RSI超卖(<35) → 做多（顺势买回调）
    - SuperTrend空头 + RSI超买(>65) → 做空（顺势卖反弹）
    """
    if i < period + 5:
        return 0, 0.0

    dirs, _ = _compute_supertrend_series(
        highs[:i+1], lows[:i+1], closes[:i+1], period, mult)
    st_dir = dirs[i]
    rsi_v = _rsi(closes[:i+1], 14)
    rsi_prev = _rsi(closes[:i], 14)

    if st_dir == 1 and rsi_v < 35 and rsi_prev >= 35:
        conf = 0.55 + min((35 - rsi_v) / 35 * 0.35, 0.35)
        return 1, conf
    elif st_dir == -1 and rsi_v > 65 and rsi_prev <= 65:
        conf = 0.55 + min((rsi_v - 65) / 35 * 0.35, 0.35)
        return -1, conf
    return 0, 0.0


# ── 策略4: MACD趋势跟踪（EMA200过滤）────────────────────────────

def sig_macd_trend(closes, highs, lows, i):
    """
    MACD金叉/死叉 × EMA200趋势过滤
    只在EMA200方向做顺势交易
    """
    if i < 35:
        return 0, 0.0

    # EMA200趋势
    ep = min(200, i)
    arr = np.array(closes[max(0, i-ep*2):i+1], dtype=float)
    k = 2 / (ep + 1); e = arr[0]
    for v in arr[1:]: e = v * k + e * (1 - k)
    ema200 = e
    trend = 1 if float(closes[i]) > ema200 * 1.001 else (-1 if float(closes[i]) < ema200 * 0.999 else 0)

    ml, sl, hi, ml_prev, sl_prev = _macd(closes[:i+1])

    # 多头：价格在EMA200上方，MACD金叉
    if trend == 1 and ml > sl and ml_prev <= sl_prev:
        conf = 0.5 + min(abs(ml - sl) / (abs(ml) + 1e-9) * 0.4, 0.4)
        return 1, conf

    # 空头：价格在EMA200下方，MACD死叉
    if trend == -1 and ml < sl and ml_prev >= sl_prev:
        conf = 0.5 + min(abs(ml - sl) / (abs(ml) + 1e-9) * 0.4, 0.4)
        return -1, conf

    return 0, 0.0


STRATEGY_CATALOG_V3 = {
    "SuperTrend":     sig_supertrend_v2,
    "MACD+RSI背离":   sig_macd_rsi_divergence,
    "ST+RSI组合":     sig_st_rsi,
    "MACD趋势":       sig_macd_trend,
}
