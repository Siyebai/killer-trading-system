#!/usr/bin/env python3
"""
market_structure_scan.py
市场结构突破信号扫描器

策略逻辑（非纯技术指标）：
1. 摆动高低点识别（Swing High/Low）
2. 结构突破确认（BoS: Break of Structure）
3. 动量确认（成交量放大 + ATR扩张）
4. 公允价值缺口（FVG: Fair Value Gap）

目标：找出胜率≥58%的信号组合
"""

import json, sys, time
import numpy as np
import pandas as pd

sys.path.insert(0, '.')
from scripts.fast_engine import load_df_np, precompute

# ─────────────────────────────────────────
# 核心：摆动高低点识别
# ─────────────────────────────────────────

def find_swing_highs(high: np.ndarray, left: int = 3, right: int = 3) -> np.ndarray:
    """识别摆动高点，返回布尔数组"""
    n = len(high)
    out = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        window = high[i - left: i + right + 1]
        if high[i] == window.max() and np.sum(window == high[i]) == 1:
            out[i] = True
    return out

def find_swing_lows(low: np.ndarray, left: int = 3, right: int = 3) -> np.ndarray:
    """识别摆动低点，返回布尔数组"""
    n = len(low)
    out = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        window = low[i - left: i + right + 1]
        if low[i] == window.min() and np.sum(window == low[i]) == 1:
            out[i] = True
    return out

def find_fvg(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> tuple:
    """
    公允价值缺口（FVG）
    多头FVG：K[-3].high < K[-1].low（价格跳过一段区域向上）
    空头FVG：K[-3].low  > K[-1].high（价格跳过一段区域向下）
    """
    n = len(close)
    bull_fvg = np.zeros(n, dtype=bool)
    bear_fvg = np.zeros(n, dtype=bool)
    for i in range(2, n):
        if low[i] > high[i - 2]:      # 多头FVG
            bull_fvg[i] = True
        if high[i] < low[i - 2]:      # 空头FVG
            bear_fvg[i] = True
    return bull_fvg, bear_fvg

# ─────────────────────────────────────────
# 市场结构突破策略回测
# ─────────────────────────────────────────

def bos_backtest(d: dict, params: dict, fee: float = 0.0009, capital: float = 150.0) -> dict:
    """
    BoS策略：
    做多：价格突破前N根摆动高点 + 成交量放大 + ATR扩张
    做空：价格跌破前N根摆动低点 + 成交量放大 + ATR扩张
    """
    c = d['close']; h = d['high']; l = d['low']
    v = d['volume']; o = d['open']
    atr = d['atr']; vol_ma = d['vol_ma']
    e20 = d['e20']; e50 = d['e50']; e200 = d['e200']
    rsi = d['rsi']
    n = len(c)

    swing_n     = params.get('swing_n', 3)       # 摆动点左右bars
    lookback    = params.get('lookback', 20)      # 查找前多少根内的摆动点
    vol_mult    = params.get('vol_mult', 1.3)     # 成交量放大倍数
    atr_mult    = params.get('atr_mult', 1.1)     # ATR扩张倍数
    tp_r        = params.get('tp_r', 2.0)         # 盈亏比
    sl_atr      = params.get('sl_atr', 1.0)       # SL = entry ± sl_atr * ATR
    max_hold    = params.get('max_hold', 12)
    mode        = params.get('mode', 'both')
    trend_align = params.get('trend_align', True) # 顺势过滤
    fvg_filter  = params.get('fvg_filter', False) # FVG确认
    warmup      = params.get('warmup', 60)
    risk_pct    = params.get('risk_pct', 0.02)

    # 预计算摆动点
    sh = find_swing_highs(h, swing_n, swing_n)
    sl_pts = find_swing_lows(l, swing_n, swing_n)
    bull_fvg, bear_fvg = find_fvg(h, l, c)

    # ATR移动平均（判断ATR扩张）
    atr_ma = pd.Series(atr).rolling(20).mean().values

    eq = capital; pos = None; trades = []
    max_eq = capital; max_dd = 0.0

    for i in range(warmup, n - 1):
        p = c[i]; av = atr[i]
        if np.isnan(av) or av == 0: continue

        vm = vol_ma[i]; vr = v[i] / vm if vm > 0 else 1.0
        atr_expand = av > atr_ma[i] * atr_mult if not np.isnan(atr_ma[i]) else True
        cg = c[i] > o[i]; cr = c[i] < o[i]

        # 出场逻辑
        if pos is not None:
            ep2 = None; er = None
            if pos['d'] == 'L':
                if l[i] <= pos['sl']: ep2 = pos['sl']; er = 'SL'
                elif h[i] >= pos['tp']: ep2 = pos['tp']; er = 'TP'
            else:
                if h[i] >= pos['sl']: ep2 = pos['sl']; er = 'SL'
                elif l[i] <= pos['tp']: ep2 = pos['tp']; er = 'TP'
            if ep2 is None and i - pos['i'] >= max_hold:
                ep2 = p; er = 'TO'
            if ep2 is not None:
                raw = (ep2 - pos['ep']) / pos['ep'] if pos['d'] == 'L' \
                      else (pos['ep'] - ep2) / pos['ep']
                pnl = pos['sz'] * (raw - fee * 2)
                eq += pnl; trades.append({'u': pnl, 'er': er, 'd': pos['d']})
                pos = None
                if eq > max_eq: max_eq = eq
                dd = (max_eq - eq) / max_eq * 100
                if dd > max_dd: max_dd = dd

        if pos is not None: continue

        # 查找前 lookback 根内的最近摆动点
        lb_start = max(warmup, i - lookback)

        # ── 做多入场：突破前摆动高点 ──
        if mode in ('long', 'both'):
            sh_indices = np.where(sh[lb_start:i])[0]
            if len(sh_indices) > 0:
                last_sh_idx = lb_start + sh_indices[-1]
                level = h[last_sh_idx]
                breakout = c[i] > level and l[i] < level  # 本根突破（收盘上穿）

                if breakout and cg and vr >= vol_mult and atr_expand:
                    ok = True
                    if trend_align and e50[i] < e200[i] * 0.998: ok = False  # 大趋势看空时不做多
                    if fvg_filter and not bull_fvg[i]: ok = False
                    if ok:
                        sl_price = p - av * sl_atr
                        sl_pct = (p - sl_price) / p
                        tp_price = p + av * sl_atr * tp_r
                        sz = min(eq * risk_pct / sl_pct, eq * 0.5) if sl_pct > 0 else 0
                        pos = {'d': 'L', 'ep': p, 'i': i, 'tp': tp_price, 'sl': sl_price, 'sz': sz}
                        continue

        # ── 做空入场：跌破前摆动低点 ──
        if mode in ('short', 'both'):
            sl_indices = np.where(sl_pts[lb_start:i])[0]
            if len(sl_indices) > 0:
                last_sl_idx = lb_start + sl_indices[-1]
                level = l[last_sl_idx]
                breakout = c[i] < level and h[i] > level  # 本根跌破

                if breakout and cr and vr >= vol_mult and atr_expand:
                    ok = True
                    if trend_align and e50[i] > e200[i] * 1.002: ok = False  # 大趋势看多时不做空
                    if fvg_filter and not bear_fvg[i]: ok = False
                    if ok:
                        sl_price = p + av * sl_atr
                        sl_pct = (sl_price - p) / p
                        tp_price = p - av * sl_atr * tp_r
                        sz = min(eq * risk_pct / sl_pct, eq * 0.5) if sl_pct > 0 else 0
                        pos = {'d': 'S', 'ep': p, 'i': i, 'tp': tp_price, 'sl': sl_price, 'sz': sz}

    total = len(trades)
    wins = [t for t in trades if t['u'] > 0]
    losses = [t for t in trades if t['u'] <= 0]
    gw = sum(t['u'] for t in wins)
    gl = sum(t['u'] for t in losses)
    return {
        'n': total, 'wr': len(wins) / total * 100 if total else 0,
        'pnl': eq - capital, 'final': eq, 'dd': max_dd,
        'pf': gw / abs(gl) if gl < 0 else 999,
        'aw': np.mean([t['u'] for t in wins]) if wins else 0,
        'al': np.mean([t['u'] for t in losses]) if losses else 0,
        'tp_cnt': sum(1 for t in trades if t['er'] == 'TP'),
        'sl_cnt': sum(1 for t in trades if t['er'] == 'SL'),
        'longs':  sum(1 for t in trades if t['d'] == 'L'),
        'shorts': sum(1 for t in trades if t['d'] == 'S'),
        'trades': trades,
    }


if __name__ == '__main__':
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    datasets = {
        'BTC_3m':  f"{base}/data/BTCUSDT_3m_90d.json",
        'ETH_3m':  f"{base}/data/ETHUSDT_3m_90d.json",
        'SOL_3m':  f"{base}/data/SOLUSDT_3m_90d.json",
        'BNB_3m':  f"{base}/data/BNBUSDT_3m_90d.json",
        'BTC_5m':  f"{base}/data/BTCUSDT_5m_60d.json",
        'BTC_15m': f"{base}/data/BTCUSDT_15m_90d.json",
    }

    print("=" * 65)
    print("  市场结构突破(BoS) 参数网格扫描")
    print("=" * 65)

    # 参数网格
    param_grid = [
        {'swing_n': sn, 'lookback': lb, 'vol_mult': vm,
         'tp_r': tp, 'sl_atr': sl, 'max_hold': mh,
         'mode': md, 'trend_align': ta}
        for sn  in [2, 3, 5]
        for lb  in [15, 25, 40]
        for vm  in [1.2, 1.5]
        for tp  in [1.5, 2.0, 2.5]
        for sl  in [0.8, 1.2]
        for mh  in [8, 16]
        for md  in ['both']
        for ta  in [True, False]
    ]
    print(f"参数组合数: {len(param_grid)}\n")

    # 只用BTC_3m先跑参数优化，速度快
    print("▶ BTC 3m 参数优化...")
    t0 = time.time()
    d = precompute(load_df_np(datasets['BTC_3m']))
    results = []
    for p in param_grid:
        r = bos_backtest(d, p)
        if r['n'] >= 20:
            results.append({**p, **r})
    results.sort(key=lambda x: (x['pnl'], x['wr']), reverse=True)
    t1 = time.time()
    print(f"完成 {len(results)}个有效结果，耗时{t1-t0:.1f}s\n")

    # 打印TOP15
    print(f"{'排名':<4}{'swing':<7}{'lb':<5}{'vol':<5}{'TP':<5}{'SL':<5}{'H':<5}{'trend':<7}{'笔':<5}{'胜率':<8}{'盈U':<9}{'DD':<7}{'PF':<6}")
    print("─" * 78)
    for i, r in enumerate(results[:15]):
        ta = '✓' if r.get('trend_align') else '✗'
        print(f"#{i+1:<3} {r['swing_n']:<7}{r['lookback']:<5}{r['vol_mult']:<5}"
              f"{r['tp_r']:<5}{r['sl_atr']:<5}{r['max_hold']:<5}{ta:<7}"
              f"{r['n']:<5}{r['wr']:>5.1f}%  {r['pnl']:>+7.2f}U  {r['dd']:>4.1f}%  {r['pf']:>4.2f}")

    # 取最优参数做4品种×3时间框架交叉验证
    if results:
        best = {k: results[0][k] for k in ['swing_n','lookback','vol_mult','tp_r','sl_atr','max_hold','mode','trend_align']}
        print(f"\n\n最优参数交叉验证: swing={best['swing_n']} lb={best['lookback']} "
              f"vol={best['vol_mult']} TP={best['tp_r']}R SL={best['sl_atr']}ATR")
        print("─" * 65)
        print(f"{'品种':<12}{'笔':>5}{'胜率':>7}{'盈U':>10}{'DD':>7}{'PF':>6}{'AvgW':>8}{'AvgL':>8}")
        print("─" * 65)
        total_pnl = 0
        for label, path in datasets.items():
            d2 = precompute(load_df_np(path))
            r2 = bos_backtest(d2, best)
            ok = '✅' if r2['pnl'] > 0 and r2['wr'] >= 45 else ('⚠️ ' if r2['pnl'] > 0 else '❌')
            total_pnl += r2['pnl']
            print(f"{ok}{label:<11}{r2['n']:>5}{r2['wr']:>6.1f}%"
                  f"{r2['pnl']:>+9.2f}U{r2['dd']:>6.1f}%{r2['pf']:>5.2f}"
                  f"{r2['aw']:>+7.2f}U{r2['al']:>+7.2f}U")
        print(f"{'合计':<15}{'':>5}{'':>7}{total_pnl:>+9.2f}U")

    print("\n" + "=" * 65)
    print("扫描完成")
