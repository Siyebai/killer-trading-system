# [ARCHIVED by Round 8 Integration - 2025-04-30]
# Reason: No active callers / Superseded

#!/usr/bin/env python3
"""
信号引擎 v4.1 — ADX Regime Filter 加强版
在 v4.0 基础上新增：
  ADX < 20 → 震荡市 → 允许均值回归入场
  ADX > 25 → 趋势市 → 过滤信号，避免被趋势止损
"""
import numpy as np
from signal_engine_v4 import (generate_signal_v4, calc_atr,
                               calc_rsi, calc_bollinger, ema_val, pct_change_n)


def calc_adx(highs, lows, closes, period=14):
    """
    计算 ADX（平均趋向指数）, 标准 Wilder 方法
    返回值范围 0-100：<20 震荡，>25 趋势
    """
    n = len(closes)
    if n < period * 2 + 2:
        return 25.0  # 数据不足时返回中性值

    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, n):
        h_diff = highs[i] - highs[i-1]
        l_diff = lows[i-1] - lows[i]
        plus_dm.append(h_diff if h_diff > l_diff and h_diff > 0 else 0)
        minus_dm.append(l_diff if l_diff > h_diff and l_diff > 0 else 0)
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        tr_list.append(tr)

    # Wilder 平滑：初始值 = 前 period 根之和，后续用滚动公式
    # 这保证 DI 计算时分子分母同比例，能正确相除得到 0-100 的 DI
    def wilder_sum(data, p):
        """Wilder 平滑（保持累积形式，用于 DM/TR）"""
        s = sum(data[:p])
        result = [s]
        for v in data[p:]:
            result.append(result[-1] - result[-1]/p + v)
        return result

    def wilder_avg(data, p):
        """Wilder 平滑（均值形式，用于 DX→ADX）"""
        s = sum(data[:p]) / p
        result = [s]
        for v in data[p:]:
            result.append((result[-1] * (p - 1) + v) / p)
        return result

    if len(tr_list) < period:
        return 25.0

    atr_s = wilder_sum(tr_list, period)
    pdm_s = wilder_sum(plus_dm, period)
    mdm_s = wilder_sum(minus_dm, period)

    di_list = []
    for i in range(len(atr_s)):
        if atr_s[i] == 0:
            di_list.append(0)
            continue
        pdi = 100 * pdm_s[i] / atr_s[i]
        mdi = 100 * mdm_s[i] / atr_s[i]
        dx  = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0
        di_list.append(min(dx, 100))  # 安全截断

    if len(di_list) < period:
        return 25.0

    adx_vals = wilder_avg(di_list, period)
    return float(min(max(adx_vals[-1], 0), 100))


def generate_signal_v41(closes, highs, lows, opens, volumes, min_bars=50,
                         adx_trend_threshold=25, adx_range_threshold=22):
    """
    v4.1 信号生成：先用 ADX 判断市场状态，再调用 v4.0 信号逻辑
    
    Returns: 同 v4.0，额外包含 adx / regime 字段
    """
    n = len(closes)
    if n < min_bars:
        return {'direction': 'NEUTRAL', 'confidence': 0,
                'reason': 'insufficient_data', 'market': 'N/A', 'adx': 0, 'regime': 'N/A'}

    adx = calc_adx(highs[-50:], lows[-50:], closes[-50:], 14)

    # Regime 判断
    if adx > adx_trend_threshold:
        regime = 'TREND'       # 趋势市，均值回归危险
    elif adx < adx_range_threshold:
        regime = 'RANGE'       # 震荡市，均值回归有效
    else:
        regime = 'TRANSITION'  # 过渡区，降低仓位置信度

    # 调用 v4.0 核心逻辑
    sig = generate_signal_v4(closes, highs, lows, opens, volumes, min_bars)
    sig['adx']    = round(adx, 2)
    sig['regime'] = regime

    # ADX 过滤
    if regime == 'TREND':
        # 趋势市完全过滤均值回归信号
        sig['direction']  = 'NEUTRAL'
        sig['confidence'] = 0
        sig['reason']     = f'ADX_FILTER_趋势市(ADX={adx:.1f}>25)'
        return sig

    if regime == 'TRANSITION':
        # 过渡区降低置信度 10%
        sig['confidence'] = round(sig.get('confidence', 0) * 0.90, 3)
        if sig.get('reason') and sig['direction'] != 'NEUTRAL':
            sig['reason'] = sig['reason'] + f'|ADX过渡({adx:.1f})'

    if regime == 'RANGE':
        # 震荡市微升置信度 5%
        sig['confidence'] = round(min(sig.get('confidence', 0) * 1.05, 0.95), 3)
        if sig.get('reason') and sig['direction'] != 'NEUTRAL':
            sig['reason'] = sig['reason'] + f'|ADX震荡({adx:.1f})'

    return sig
