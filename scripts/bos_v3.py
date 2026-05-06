#!/usr/bin/env python3
"""
bos_v3.py — 全向量化BoS回测 v3（ms级）
预计算耗时 < 10ms，648组网格 < 15s
"""
import sys, os, time
import numpy as np
import pandas as pd
from scipy.signal import argrelmax, argrelmin

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from scripts.fast_engine import load_df_np, precompute


def precompute_bos(d: dict, order: int, lookback: int) -> dict:
    """向量化预计算摆动点价格（4ms级）"""
    h = d['high']; l = d['low']; n = len(h)
    sh_idx = argrelmax(h, order=order)[0]
    sl_idx = argrelmin(l, order=order)[0]
    all_i  = np.arange(n)

    # 每个i对应的：前lookback内最近摆动高点价格
    pos_sh = np.searchsorted(sh_idx, all_i, side='left') - 1
    clip_sh = np.clip(pos_sh, 0, len(sh_idx)-1)
    valid_sh = (pos_sh >= 0) & (sh_idx[clip_sh] >= all_i - lookback)
    prev_sh = np.where(valid_sh, h[sh_idx[clip_sh]], np.nan)

    # 每个i对应的：前lookback内最近摆动低点价格
    pos_sl = np.searchsorted(sl_idx, all_i, side='left') - 1
    clip_sl = np.clip(pos_sl, 0, len(sl_idx)-1)
    valid_sl = (pos_sl >= 0) & (sl_idx[clip_sl] >= all_i - lookback)
    prev_sl = np.where(valid_sl, l[sl_idx[clip_sl]], np.nan)

    return {**d, 'prev_sh': prev_sh, 'prev_sl': prev_sl,
            'sh_n': len(sh_idx), 'sl_n': len(sl_idx)}


def bos_v3(d_bos: dict, params: dict, fee=0.0009, capital=150.0) -> dict:
    """向量化信号筛选 + 极简回测循环"""
    c=d_bos['close']; h=d_bos['high']; l=d_bos['low']
    v=d_bos['volume']; o=d_bos['open']
    atr=d_bos['atr']; vol_ma=d_bos['vol_ma']
    e50=d_bos['e50']; e200=d_bos['e200']
    prev_sh=d_bos['prev_sh']; prev_sl=d_bos['prev_sl']
    n=len(c)

    vol_mult = params.get('vol_mult', 1.3)
    tp_r     = params.get('tp_r', 2.0)
    sl_atr   = params.get('sl_atr', 1.0)
    max_hold = params.get('max_hold', 12)
    trend_ok = params.get('trend_align', True)
    risk_pct = params.get('risk_pct', 0.02)
    warmup   = params.get('warmup', 80)

    vr = np.where(vol_ma>0, v/vol_ma, 1.0)

    # 向量化信号
    idx = np.arange(warmup, n-1)
    cg = c[idx] > o[idx]; cr = c[idx] < o[idx]
    vok = vr[idx] >= vol_mult
    prev_c = c[idx-1]

    sh_lev = prev_sh[idx]; sl_lev = prev_sl[idx]

    long_mask  = cg & vok & (~np.isnan(sh_lev)) & (c[idx]>sh_lev) & (prev_c<=sh_lev)
    short_mask = cr & vok & (~np.isnan(sl_lev)) & (c[idx]<sl_lev) & (prev_c>=sl_lev)
    if trend_ok:
        long_mask  &= (e50[idx] >= e200[idx]*0.997)
        short_mask &= (e50[idx] <= e200[idx]*1.003)

    long_set  = set(idx[long_mask].tolist())
    short_set = set(idx[short_mask].tolist())

    eq=capital; pos=None; trades=[]
    max_eq=capital; max_dd=0.0

    for i in range(warmup, n-1):
        p=c[i]; av=atr[i]
        if np.isnan(av) or av==0: continue
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
            sl_p=p-av*sl_atr; slp=(p-sl_p)/p
            sz=min(eq*risk_pct/slp,eq*0.5) if slp>0 else 0
            pos={'d':'L','ep':p,'i':i,'tp':p+av*sl_atr*tp_r,'sl':sl_p,'sz':sz}
            continue
        if i in short_set:
            sl_p=p+av*sl_atr; slp=(sl_p-p)/p
            sz=min(eq*risk_pct/slp,eq*0.5) if slp>0 else 0
            pos={'d':'S','ep':p,'i':i,'tp':p-av*sl_atr*tp_r,'sl':sl_p,'sz':sz}

    total=len(trades)
    wins=[t for t in trades if t['u']>0]; losses=[t for t in trades if t['u']<=0]
    gw=sum(t['u'] for t in wins); gl=sum(t['u'] for t in losses)
    return {'n':total,'wr':len(wins)/total*100 if total else 0,
            'pnl':eq-capital,'final':eq,'dd':max_dd,
            'pf':gw/abs(gl) if gl<0 else 999,
            'aw':np.mean([t['u'] for t in wins]) if wins else 0,
            'al':np.mean([t['u'] for t in losses]) if losses else 0,
            'tp_cnt':sum(1 for t in trades if t['er']=='TP'),
            'sl_cnt':sum(1 for t in trades if t['er']=='SL'),
            'longs': sum(1 for t in trades if t['d']=='L'),
            'shorts':sum(1 for t in trades if t['d']=='S'),
            'trades':trades}


if __name__ == '__main__':
    datasets = {
        'BTC_3m':  f"{BASE}/data/BTCUSDT_3m_90d.json",
        'ETH_3m':  f"{BASE}/data/ETHUSDT_3m_90d.json",
        'SOL_3m':  f"{BASE}/data/SOLUSDT_3m_90d.json",
        'BNB_3m':  f"{BASE}/data/BNBUSDT_3m_90d.json",
        'BTC_5m':  f"{BASE}/data/BTCUSDT_5m_60d.json",
        'BTC_15m': f"{BASE}/data/BTCUSDT_15m_90d.json",
    }

    # 速度基准
    t0=time.time()
    raw=load_df_np(datasets['BTC_3m']); d=precompute(raw)
    d_bos=precompute_bos(d,3,20); t1=time.time()
    r=bos_v3(d_bos,{'vol_mult':1.3,'tp_r':2.0,'sl_atr':1.0,'max_hold':12}); t2=time.time()
    print(f"BTC 3m | 预计算:{(t1-t0)*1000:.0f}ms 单次:{(t2-t1)*1000:.0f}ms | {r['n']}笔 胜率{r['wr']:.1f}%")

    # 参数网格 —— 对每组(order,lookback)只预计算一次摆动点
    print("\n" + "="*70)
    print("  BoS 参数网格 BTC 3m 90天")
    print("="*70)

    configs = [
        (order, lb, vm, tp, sl, mh, ta)
        for order in [2, 3, 5]
        for lb    in [10, 20, 35]
        for vm    in [1.2, 1.5, 2.0]
        for tp    in [1.5, 2.0, 3.0]
        for sl    in [0.8, 1.2]
        for mh    in [8, 16]
        for ta    in [True, False]
    ]
    print(f"参数组合: {len(configs)}组\n")

    t3=time.time()
    results=[]
    cache={}  # (order,lb) → d_bos
    for (order,lb,vm,tp,sl,mh,ta) in configs:
        key=(order,lb)
        if key not in cache:
            cache[key]=precompute_bos(d, order, lb)
        r=bos_v3(cache[key],{'vol_mult':vm,'tp_r':tp,'sl_atr':sl,'max_hold':mh,'trend_align':ta,'order':order,'lookback':lb})
        if r['n']>=10: results.append({'order':order,'lookback':lb,'vol_mult':vm,'tp_r':tp,'sl_atr':sl,'max_hold':mh,'trend_align':ta,**r})
    results.sort(key=lambda x:(x['pnl'],x['wr']),reverse=True)
    t4=time.time()
    print(f"耗时 {t4-t3:.1f}s  有效结果: {len(results)}组\n")

    print(f"{'#':<4}{'ord':<4}{'lb':<4}{'vol':<5}{'TP':<5}{'SL':<5}{'H':<4}{'tr':<4}"
          f"{'笔':<5}{'胜率':<8}{'盈U':<9}{'DD':<7}{'PF':<6}{'AvgW':<8}{'AvgL'}")
    print("─"*82)
    for i,r in enumerate(results[:20]):
        ta='✓' if r.get('trend_align') else '✗'
        print(f"#{i+1:<3}{r['order']:<4}{r['lookback']:<4}{r['vol_mult']:<5}"
              f"{r['tp_r']:<5}{r['sl_atr']:<5}{r['max_hold']:<4}{ta:<4}"
              f"{r['n']:<5}{r['wr']:>5.1f}%  {r['pnl']:>+7.2f}U  "
              f"{r['dd']:>4.1f}%  {r['pf']:>4.2f}  {r['aw']:>+5.2f}U  {r['al']:>+5.2f}U")

    if not results: print("无结果"); exit()

    best={k:results[0][k] for k in ['order','lookback','vol_mult','tp_r','sl_atr','max_hold','trend_align']}
    print(f"\n\n最优参数: order={best['order']} lb={best['lookback']} vol≥{best['vol_mult']}x "
          f"TP={best['tp_r']}R SL={best['sl_atr']}ATR H={best['max_hold']} trend={'ON' if best['trend_align'] else 'OFF'}")

    # 交叉验证
    print("─"*65)
    print(f"{'品种':<12}{'笔':>5}{'胜率':>7}{'盈U':>10}{'DD':>7}{'PF':>6}{'多':>5}{'空':>5}")
    print("─"*65)
    total_pnl=0
    for label,path in datasets.items():
        d2=precompute(load_df_np(path))
        d2_bos=precompute_bos(d2, best['order'], best['lookback'])
        r2=bos_v3(d2_bos,best)
        total_pnl+=r2['pnl']
        ok='✅' if r2['pnl']>0 and r2['wr']>=45 else ('⚠️' if r2['pnl']>0 else '❌')
        print(f"{ok} {label:<11}{r2['n']:>5}{r2['wr']:>6.1f}%"
              f"{r2['pnl']:>+9.2f}U{r2['dd']:>6.1f}%{r2['pf']:>5.2f}"
              f"{r2['longs']:>5}{r2['shorts']:>5}")
    print(f"{'':>14}{'合计':>5}{'':>7}{total_pnl:>+9.2f}U")
    print("\n" + "="*65)
    print(f"结论: {'✅ 正期望！进入整合' if total_pnl>5 else '❌ 仍亏损，调整方向'}")
