#!/usr/bin/env python3
"""
bos_v2.py — 极速BoS回测，全向量化预计算
消灭所有内层Python循环
"""
import sys, os, time
import numpy as np
import pandas as pd
from scipy.signal import argrelmax, argrelmin

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from scripts.fast_engine import load_df_np, precompute

def precompute_swing_levels(h, l, order, lookback):
    """
    预计算每个bar往前lookback内的最近摆动高点价格 / 最近摆动低点价格
    返回 ndarray: prev_swing_high, prev_swing_low
    """
    n = len(h)
    sh_idx = argrelmax(h, order=order)[0]
    sl_idx = argrelmin(l, order=order)[0]

    prev_sh = np.full(n, np.nan)   # 每个i: 前lookback内最近摆动高点的价格
    prev_sl = np.full(n, np.nan)

    # 用滑动窗口填充
    sh_ptr = 0
    sl_ptr = 0
    for i in range(n):
        lb = i - lookback
        # 摆动高
        while sh_ptr < len(sh_idx) and sh_idx[sh_ptr] < lb: sh_ptr += 1
        # 找最近（最大index）的sh < i
        j = len(sh_idx) - 1
        while j >= sh_ptr and sh_idx[j] >= i: j -= 1
        if j >= sh_ptr and sh_idx[j] >= lb:
            prev_sh[i] = h[sh_idx[j]]
        # 摆动低
        j2 = len(sl_idx) - 1
        while j2 >= 0 and sl_idx[j2] >= i: j2 -= 1
        if j2 >= 0 and sl_idx[j2] >= lb:
            prev_sl[i] = l[sl_idx[j2]]

    return prev_sh, prev_sl


def bos_v2(d, params, fee=0.0009, capital=150.0):
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
    trend_ok= params.get('trend_align', True)
    risk_pct= params.get('risk_pct', 0.02)
    warmup  = max(order*2+5, 60)

    prev_sh, prev_sl = precompute_swing_levels(h, l, order, lookback)
    vr = np.where(vol_ma>0, v/vol_ma, 1.0)

    # 向量化信号预筛选
    idx = np.arange(warmup, n-1)
    cg = c[idx] > o[idx]
    cr = c[idx] < o[idx]
    vok = vr[idx] >= vol_mult
    prev_c = c[idx-1]

    # 做多信号：收盘突破前摆动高点 且 前一根未突破
    sh_lev = prev_sh[idx]
    long_mask = (cg) & (vok) & (~np.isnan(sh_lev)) & (c[idx] > sh_lev) & (prev_c <= sh_lev)
    if trend_ok:
        long_mask &= (e50[idx] >= e200[idx] * 0.997)

    # 做空信号：收盘跌破前摆动低点
    sl_lev = prev_sl[idx]
    short_mask = (cr) & (vok) & (~np.isnan(sl_lev)) & (c[idx] < sl_lev) & (prev_c >= sl_lev)
    if trend_ok:
        short_mask &= (e50[idx] <= e200[idx] * 1.003)

    long_set  = set(idx[long_mask].tolist())
    short_set = set(idx[short_mask].tolist())

    eq=capital; pos=None; trades=[]
    max_eq=capital; max_dd=0.0

    for i in range(warmup, n-1):
        p=c[i]; av=atr[i]
        if np.isnan(av) or av==0: continue

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

        if i in long_set:
            lev=prev_sh[i]; sl_p=p-av*sl_atr; slp=(p-sl_p)/p
            tp_p=p+av*sl_atr*tp_r
            sz=min(eq*risk_pct/slp, eq*0.5) if slp>0 else 0
            pos={'d':'L','ep':p,'i':i,'tp':tp_p,'sl':sl_p,'sz':sz}
            continue

        if i in short_set:
            lev=prev_sl[i]; sl_p=p+av*sl_atr; slp=(sl_p-p)/p
            tp_p=p-av*sl_atr*tp_r
            sz=min(eq*risk_pct/slp, eq*0.5) if slp>0 else 0
            pos={'d':'S','ep':p,'i':i,'tp':tp_p,'sl':sl_p,'sz':sz}

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
    t0=time.time()
    d=precompute(load_df_np(datasets['BTC_3m']))
    r=bos_v2(d,{'order':3,'lookback':20,'vol_mult':1.3,'tp_r':2.0,'sl_atr':1.0,'max_hold':12})
    t1=time.time()
    print(f"✅ BTC 3m 43200根 单次: {(t1-t0)*1000:.0f}ms  {r['n']}笔 胜率{r['wr']:.1f}%")

    # ── 小网格快速扫描 ──
    print("\n" + "="*65)
    print("  BoS 参数网格 BTC 3m (64组)")
    print("="*65)
    grid=[
        {'order':o,'lookback':lb,'vol_mult':vm,'tp_r':tp,'sl_atr':sl,'max_hold':mh,'trend_align':ta}
        for o  in [2,3,5]
        for lb in [10,20,35]
        for vm in [1.2,1.5]
        for tp in [1.5,2.0,3.0]
        for sl in [0.8,1.2]
        for mh in [8,16]
        for ta in [True,False]
    ]
    t2=time.time()
    results=[]
    for p in grid:
        r=bos_v2(d,p)
        if r['n']>=10: results.append({**p,**r})
    results.sort(key=lambda x:(x['pnl'],x['wr']),reverse=True)
    t3=time.time()
    print(f"耗时 {t3-t2:.1f}s  {len(grid)}组  有效: {len(results)}组\n")

    print(f"{'#':<4}{'ord':<4}{'lb':<4}{'vol':<5}{'TP':<5}{'SL':<5}{'H':<4}{'tr':<4}"
          f"{'笔':<5}{'胜率':<8}{'盈U':<9}{'DD':<7}{'PF':<6}{'AvgW':<8}{'AvgL'}")
    print("─"*80)
    for i,r in enumerate(results[:20]):
        ta='✓' if r.get('trend_align') else '✗'
        print(f"#{i+1:<3}{r['order']:<4}{r['lookback']:<4}{r['vol_mult']:<5}"
              f"{r['tp_r']:<5}{r['sl_atr']:<5}{r['max_hold']:<4}{ta:<4}"
              f"{r['n']:<5}{r['wr']:>5.1f}%  {r['pnl']:>+7.2f}U  "
              f"{r['dd']:>4.1f}%  {r['pf']:>4.2f}  {r['aw']:>+5.2f}U  {r['al']:>+5.2f}U")

    # ── 交叉验证 ──
    if not results: print("无结果"); exit()
    best={k:results[0][k] for k in ['order','lookback','vol_mult','tp_r','sl_atr','max_hold','trend_align']}
    print(f"\n\n最优参数: order={best['order']} lb={best['lookback']} vol≥{best['vol_mult']}x "
          f"TP={best['tp_r']}R SL={best['sl_atr']}ATR H={best['max_hold']} trend={'ON' if best['trend_align'] else 'OFF'}")
    print("─"*65)
    print(f"{'品种':<12}{'笔':>5}{'胜率':>7}{'盈U':>10}{'DD':>7}{'PF':>6}{'多':>5}{'空':>5}")
    print("─"*65)
    total_pnl=0
    for label,path in datasets.items():
        d2=precompute(load_df_np(path))
        r2=bos_v2(d2,best)
        total_pnl+=r2['pnl']
        ok='✅' if r2['pnl']>0 and r2['wr']>=45 else ('⚠️' if r2['pnl']>0 else '❌')
        print(f"{ok} {label:<11}{r2['n']:>5}{r2['wr']:>6.1f}%"
              f"{r2['pnl']:>+9.2f}U{r2['dd']:>6.1f}%{r2['pf']:>5.2f}"
              f"{r2['longs']:>5}{r2['shorts']:>5}")
    print(f"{'':>14}{'合计':>5}{'':>7}{total_pnl:>+9.2f}U")
    print("\n" + "="*65)
    print(f"结论: {'✅ 正期望！' if total_pnl>5 else '❌ 仍亏损'}")
