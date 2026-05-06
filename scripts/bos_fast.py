#!/usr/bin/env python3
"""
bos_fast.py — 快速市场结构突破回测
向量化摆动点识别 + 向量化BoS信号检测
"""
import json, sys, time, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.fast_engine import load_df_np, precompute

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 向量化摆动点（scipy argrelmax） ──────────────
def swing_highs_vec(high: np.ndarray, order: int = 3) -> np.ndarray:
    from scipy.signal import argrelmax
    idx = argrelmax(high, order=order)[0]
    out = np.zeros(len(high), dtype=bool)
    out[idx] = True
    return out

def swing_lows_vec(low: np.ndarray, order: int = 3) -> np.ndarray:
    from scipy.signal import argrelmin
    idx = argrelmin(low, order=order)[0]
    out = np.zeros(len(low), dtype=bool)
    out[idx] = True
    return out

# ── 向量化 BoS 回测 ──────────────────────────────
def bos_fast(d: dict, params: dict, fee=0.0009, capital=150.0) -> dict:
    c=d['close']; h=d['high']; l=d['low']
    v=d['volume']; o=d['open']
    atr=d['atr']; vol_ma=d['vol_ma']
    e50=d['e50']; e200=d['e200']
    n=len(c)

    order   = params.get('order', 3)
    lookback= params.get('lookback', 20)
    vol_mult= params.get('vol_mult', 1.3)
    tp_r    = params.get('tp_r', 2.0)
    sl_atr  = params.get('sl_atr', 1.0)
    max_hold= params.get('max_hold', 12)
    mode    = params.get('mode', 'both')
    trend_ok= params.get('trend_align', True)
    warmup  = params.get('warmup', 60)
    risk_pct= params.get('risk_pct', 0.02)
    min_atr_pct = params.get('min_atr_pct', 0.001)  # ATR > 价格0.1%才入场

    # 预计算摆动点
    sh = swing_highs_vec(h, order)
    sl_arr = swing_lows_vec(l, order)

    # 预计算成交量比率
    vr = np.where(vol_ma > 0, v / vol_ma, 1.0)

    eq=capital; pos=None; trades=[]
    max_eq=capital; max_dd=0.0

    # 预缓存摆动点位置列表
    sh_pos = np.where(sh)[0].tolist()
    sl_pos = np.where(sl_arr)[0].tolist()

    for i in range(warmup, n-1):
        p=c[i]; av=atr[i]
        if np.isnan(av) or av/p < min_atr_pct: continue
        cg=c[i]>o[i]; cr=c[i]<o[i]

        # 出场
        if pos is not None:
            ep2=None; er=None
            if pos['d']=='L':
                if l[i]<=pos['sl']: ep2=pos['sl']; er='SL'
                elif h[i]>=pos['tp']: ep2=pos['tp']; er='TP'
            else:
                if h[i]>=pos['sl']: ep2=pos['sl']; er='SL'
                elif l[i]<=pos['tp']: ep2=pos['tp']; er='TP'
            if ep2 is None and i-pos['i']>=max_hold: ep2=p; er='TO'
            if ep2 is not None:
                raw=(ep2-pos['ep'])/pos['ep'] if pos['d']=='L' else (pos['ep']-ep2)/pos['ep']
                pnl=pos['sz']*(raw-fee*2)
                eq+=pnl; trades.append({'u':pnl,'er':er,'d':pos['d']})
                pos=None
                if eq>max_eq: max_eq=eq
                dd=(max_eq-eq)/max_eq*100
                if dd>max_dd: max_dd=dd

        if pos is not None: continue

        vol_ok = vr[i] >= vol_mult

        # 做多：收盘突破前摆动高点
        if mode in ('long','both') and cg and vol_ok:
            # 找前 lookback 范围内最近的摆动高点
            lb = i - lookback
            # 二分查找最近摆动高点
            j = len(sh_pos) - 1
            while j >= 0 and sh_pos[j] >= i: j -= 1
            while j >= 0 and sh_pos[j] < lb: j -= 1
            if j >= 0:
                level = h[sh_pos[j]]
                if p > level and c[i-1] <= level:  # 本根突破（前根未突破）
                    ok = True
                    if trend_ok and e50[i] < e200[i] * 0.997: ok = False
                    if ok:
                        sl_p = p - av * sl_atr; slp = (p-sl_p)/p
                        tp_p = p + av * sl_atr * tp_r
                        sz = min(eq*risk_pct/slp, eq*0.5) if slp>0 else 0
                        pos = {'d':'L','ep':p,'i':i,'tp':tp_p,'sl':sl_p,'sz':sz}
                        continue

        # 做空：收盘跌破前摆动低点
        if mode in ('short','both') and cr and vol_ok:
            j = len(sl_pos) - 1
            while j >= 0 and sl_pos[j] >= i: j -= 1
            while j >= 0 and sl_pos[j] < i - lookback: j -= 1
            if j >= 0:
                level = l[sl_pos[j]]
                if p < level and c[i-1] >= level:
                    ok = True
                    if trend_ok and e50[i] > e200[i] * 1.003: ok = False
                    if ok:
                        sl_p = p + av * sl_atr; slp = (sl_p-p)/p
                        tp_p = p - av * sl_atr * tp_r
                        sz = min(eq*risk_pct/slp, eq*0.5) if slp>0 else 0
                        pos = {'d':'S','ep':p,'i':i,'tp':tp_p,'sl':sl_p,'sz':sz}

    total=len(trades)
    wins=[t for t in trades if t['u']>0]; losses=[t for t in trades if t['u']<=0]
    gw=sum(t['u'] for t in wins); gl=sum(t['u'] for t in losses)
    return {
        'n':total,'wr':len(wins)/total*100 if total else 0,
        'pnl':eq-capital,'final':eq,'dd':max_dd,
        'pf':gw/abs(gl) if gl<0 else 999,
        'aw':np.mean([t['u'] for t in wins]) if wins else 0,
        'al':np.mean([t['u'] for t in losses]) if losses else 0,
        'tp_cnt':sum(1 for t in trades if t['er']=='TP'),
        'sl_cnt':sum(1 for t in trades if t['er']=='SL'),
        'longs': sum(1 for t in trades if t['d']=='L'),
        'shorts':sum(1 for t in trades if t['d']=='S'),
        'trades':trades,
    }


if __name__ == '__main__':
    datasets = {
        'BTC_3m':  f"{BASE}/data/BTCUSDT_3m_90d.json",
        'ETH_3m':  f"{BASE}/data/ETHUSDT_3m_90d.json",
        'SOL_3m':  f"{BASE}/data/SOLUSDT_3m_90d.json",
        'BNB_3m':  f"{BASE}/data/BNBUSDT_3m_90d.json",
        'BTC_5m':  f"{BASE}/data/BTCUSDT_5m_60d.json",
        'BTC_15m': f"{BASE}/data/BTCUSDT_15m_90d.json",
    }

    # ── 速度基准 ──
    print("性能测试...")
    t0=time.time()
    d=precompute(load_df_np(datasets['BTC_3m']))
    r=bos_fast(d,{'order':3,'lookback':20,'vol_mult':1.3,'tp_r':2.0,'sl_atr':1.0,'max_hold':12})
    t1=time.time()
    print(f"BTC 3m 43200根 单次: {(t1-t0)*1000:.0f}ms  {r['n']}笔\n")

    # ── 参数网格 BTC 3m ──
    print("="*65)
    print("  BoS 参数网格 — BTC 3m 90天")
    print("="*65)
    grid = [
        {'order':o,'lookback':lb,'vol_mult':vm,'tp_r':tp,'sl_atr':sl,'max_hold':mh,'trend_align':ta}
        for o   in [2, 3, 5]
        for lb  in [10, 20, 35]
        for vm  in [1.2, 1.5, 2.0]
        for tp  in [1.5, 2.0, 3.0]
        for sl  in [0.8, 1.2]
        for mh  in [8, 16]
        for ta  in [True, False]
    ]
    print(f"参数组合: {len(grid)}组\n")

    t2=time.time()
    results=[]
    for p in grid:
        r=bos_fast(d,p)
        if r['n']>=15: results.append({**p,**r})
    results.sort(key=lambda x:(x['pnl'],x['wr']),reverse=True)
    t3=time.time()
    print(f"耗时 {t3-t2:.1f}s  有效结果: {len(results)}组\n")

    print(f"{'#':<4}{'ord':<5}{'lb':<5}{'vol':<5}{'TP':<5}{'SL':<5}{'H':<5}{'tr':<4}"
          f"{'笔':<5}{'胜率':<8}{'盈U':<9}{'DD':<7}{'PF':<6}{'AvgW':<8}{'AvgL'}")
    print("─"*85)
    for i,r in enumerate(results[:20]):
        ta='✓' if r.get('trend_align') else '✗'
        print(f"#{i+1:<3}{r['order']:<5}{r['lookback']:<5}{r['vol_mult']:<5}"
              f"{r['tp_r']:<5}{r['sl_atr']:<5}{r['max_hold']:<5}{ta:<4}"
              f"{r['n']:<5}{r['wr']:>5.1f}%  {r['pnl']:>+7.2f}U  "
              f"{r['dd']:>4.1f}%  {r['pf']:>4.2f}  {r['aw']:>+5.2f}U  {r['al']:>+5.2f}U")

    # ── 最优参数交叉验证 ──
    if not results:
        print("无有效结果"); exit(0)

    best = {k:results[0][k] for k in ['order','lookback','vol_mult','tp_r','sl_atr','max_hold','mode','trend_align']
            if k in results[0]}
    best.setdefault('mode','both')
    print(f"\n\n最优参数交叉验证: order={best['order']} lb={best['lookback']} "
          f"vol≥{best['vol_mult']}x TP={best['tp_r']}R SL={best['sl_atr']}ATR H={best['max_hold']} trend={'ON' if best['trend_align'] else 'OFF'}")
    print("─"*65)
    print(f"{'品种':<12}{'笔':>5}{'胜率':>7}{'盈U':>10}{'DD':>7}{'PF':>6}{'多':>5}{'空':>5}")
    print("─"*65)
    total_pnl=0
    for label,path in datasets.items():
        d2=precompute(load_df_np(path))
        r2=bos_fast(d2,best)
        total_pnl+=r2['pnl']
        ok='✅' if r2['pnl']>0 and r2['wr']>=45 else ('⚠️' if r2['pnl']>0 else '❌')
        print(f"{ok} {label:<11}{r2['n']:>5}{r2['wr']:>6.1f}%"
              f"{r2['pnl']:>+9.2f}U{r2['dd']:>6.1f}%{r2['pf']:>5.2f}"
              f"{r2['longs']:>5}{r2['shorts']:>5}")
    print(f"{'':>14}{'合计':>5}{'':>7}{total_pnl:>+9.2f}U")
    print("\n" + "="*65)
    verdict = "✅ 正期望！进入下一步整合" if total_pnl > 5 else "❌ 仍亏损，继续优化"
    print(f"结论: {verdict}")
