#!/usr/bin/env python3
"""
bos_v4.py — 向量化出场搜索，消灭主循环
单次BTC 3m < 5ms，648组网格 < 30s
"""
import sys, os, time
import numpy as np
from scipy.signal import argrelmax, argrelmin

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from scripts.fast_engine import load_df_np, precompute


def precompute_bos(d: dict, order: int, lookback: int) -> dict:
    h=d['high']; l=d['low']; n=len(h)
    sh_idx = argrelmax(h, order=order)[0]
    sl_idx = argrelmin(l, order=order)[0]
    all_i  = np.arange(n)

    pos_sh = np.searchsorted(sh_idx, all_i, side='left') - 1
    clip_sh = np.clip(pos_sh, 0, max(len(sh_idx)-1,0))
    valid_sh = (pos_sh >= 0) & (len(sh_idx)>0) & (sh_idx[clip_sh] >= all_i - lookback)
    prev_sh = np.where(valid_sh, h[sh_idx[clip_sh]], np.nan)

    pos_sl = np.searchsorted(sl_idx, all_i, side='left') - 1
    clip_sl = np.clip(pos_sl, 0, max(len(sl_idx)-1,0))
    valid_sl = (pos_sl >= 0) & (len(sl_idx)>0) & (sl_idx[clip_sl] >= all_i - lookback)
    prev_sl = np.where(valid_sl, l[sl_idx[clip_sl]], np.nan)

    return {**d, 'prev_sh': prev_sh, 'prev_sl': prev_sl}


def bos_v4(d_bos: dict, params: dict, fee=0.0009, capital=150.0) -> dict:
    """
    向量化出场搜索：
    1. 向量化找所有入场信号点
    2. 对每个信号点，searchsorted找最早触及TP/SL/超时的bar
    3. 顺序模拟（跳过持仓中的信号）
    """
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
    idx = np.arange(warmup, n-1)
    cg=c[idx]>o[idx]; cr=c[idx]<o[idx]
    vok=vr[idx]>=vol_mult; prev_c=c[idx-1]
    sh_lev=prev_sh[idx]; sl_lev=prev_sl[idx]

    long_mask  = cg & vok & (~np.isnan(sh_lev)) & (c[idx]>sh_lev) & (prev_c<=sh_lev)
    short_mask = cr & vok & (~np.isnan(sl_lev)) & (c[idx]<sl_lev) & (prev_c>=sl_lev)
    if trend_ok:
        long_mask  &= e50[idx] >= e200[idx]*0.997
        short_mask &= e50[idx] <= e200[idx]*1.003

    long_idx  = idx[long_mask]
    short_idx = idx[short_mask]

    # 合并所有信号，按时间排序
    if len(long_idx)==0 and len(short_idx)==0:
        return {'n':0,'wr':0,'pnl':0,'dd':0,'pf':999,'aw':0,'al':0,'longs':0,'shorts':0,'tp_cnt':0,'sl_cnt':0,'trades':[]}

    sig_i = np.concatenate([long_idx, short_idx])
    sig_d = np.concatenate([np.ones(len(long_idx),dtype=np.int8), -np.ones(len(short_idx),dtype=np.int8)])
    order_ = np.argsort(sig_i, kind='stable')
    sig_i = sig_i[order_]; sig_d = sig_d[order_]

    eq=capital; max_eq=capital; max_dd=0.0
    trades=[]; last_exit=-1

    for k in range(len(sig_i)):
        si = sig_i[k]; di = sig_d[k]
        if si <= last_exit: continue

        entry = c[si]; av = atr[si]
        if np.isnan(av) or av == 0: continue

        if di == 1:  # 做多
            sl_p = entry - av*sl_atr; tp_p = entry + av*sl_atr*tp_r
            sl_pct = (entry-sl_p)/entry
        else:        # 做空
            sl_p = entry + av*sl_atr; tp_p = entry - av*sl_atr*tp_r
            sl_pct = (sl_p-entry)/entry

        sz = min(eq*risk_pct/sl_pct, eq*0.5) if sl_pct>0 else 0

        # 向量化搜索出场
        end = min(si+max_hold+1, n)
        fh = h[si+1:end]; fl = l[si+1:end]

        if di == 1:
            hit_sl = np.where(fl <= sl_p)[0]
            hit_tp = np.where(fh >= tp_p)[0]
        else:
            hit_sl = np.where(fh >= sl_p)[0]
            hit_tp = np.where(fl <= tp_p)[0]

        cands = {}
        if len(hit_sl): cands['SL'] = (hit_sl[0], sl_p)
        if len(hit_tp): cands['TP'] = (hit_tp[0], tp_p)
        if cands:
            er = min(cands, key=lambda k2: cands[k2][0])
            exit_bar = si+1+cands[er][0]; exit_p = cands[er][1]
        else:
            exit_bar = si+max_hold; exit_p = c[min(si+max_hold,n-1)]; er='TO'

        last_exit = exit_bar
        raw = (exit_p-entry)/entry if di==1 else (entry-exit_p)/entry
        pnl = sz*(raw - fee*2)
        eq += pnl
        trades.append({'u':pnl,'er':er,'d':'L' if di==1 else 'S'})
        if eq>max_eq: max_eq=eq
        dd=(max_eq-eq)/max_eq*100
        if dd>max_dd: max_dd=dd

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
    d=precompute(load_df_np(datasets['BTC_3m']))
    t0=time.time(); db=precompute_bos(d,3,20); t1=time.time()
    r=bos_v4(db,{'vol_mult':1.3,'tp_r':2.0,'sl_atr':1.0,'max_hold':12}); t2=time.time()
    print(f"BTC 3m | 预计算:{(t1-t0)*1000:.0f}ms 单次:{(t2-t1)*1000:.0f}ms | {r['n']}笔 胜率{r['wr']:.1f}% 盈亏{r['pnl']:+.2f}U")

    # 参数网格
    print("\n" + "="*72)
    print("  BoS v4 参数网格 — BTC 3m 90天")
    print("="*72)
    configs=[
        (ord_,lb,vm,tp,sl,mh,ta)
        for ord_ in [2,3,5]
        for lb   in [10,20,35]
        for vm   in [1.2,1.5,2.0]
        for tp   in [1.5,2.0,3.0]
        for sl   in [0.8,1.2]
        for mh   in [8,16]
        for ta   in [True,False]
    ]
    print(f"共 {len(configs)} 组参数\n")
    t3=time.time(); results=[]; cache={}
    for (ord_,lb,vm,tp,sl,mh,ta) in configs:
        key=(ord_,lb)
        if key not in cache: cache[key]=precompute_bos(d,ord_,lb)
        r=bos_v4(cache[key],{'vol_mult':vm,'tp_r':tp,'sl_atr':sl,'max_hold':mh,'trend_align':ta,'order':ord_,'lookback':lb})
        if r['n']>=10: results.append({'order':ord_,'lookback':lb,'vol_mult':vm,'tp_r':tp,'sl_atr':sl,'max_hold':mh,'trend_align':ta,**r})
    results.sort(key=lambda x:(x['pnl'],x['wr']),reverse=True)
    t4=time.time()
    print(f"耗时 {t4-t3:.1f}s | 有效结果: {len(results)}组\n")

    print(f"{'#':<4}{'ord':<4}{'lb':<4}{'vol':<5}{'TP':<5}{'SL':<5}{'H':<4}{'tr':<4}"
          f"{'笔':<5}{'胜率':<8}{'盈U':<9}{'DD':<7}{'PF':<6}{'AvgW':<8}{'AvgL'}")
    print("─"*82)
    positive = [r for r in results if r['pnl']>0]
    show = results[:20]
    for i,r in enumerate(show):
        ta='✓' if r.get('trend_align') else '✗'
        flag='✅' if r['pnl']>0 and r['wr']>=45 else ('⚠️' if r['pnl']>0 else '  ')
        print(f"{flag}#{i+1:<2}{r['order']:<4}{r['lookback']:<4}{r['vol_mult']:<5}"
              f"{r['tp_r']:<5}{r['sl_atr']:<5}{r['max_hold']:<4}{ta:<4}"
              f"{r['n']:<5}{r['wr']:>5.1f}%  {r['pnl']:>+7.2f}U  "
              f"{r['dd']:>4.1f}%  {r['pf']:>4.2f}  {r['aw']:>+5.2f}U  {r['al']:>+5.2f}U")

    print(f"\n正期望组合: {len(positive)}个 / {len(results)}个")

    if not results: print("无结果"); exit()
    # 选正期望且笔数最多的作为最优
    best_candidates = [r for r in results if r['pnl']>0 and r['wr']>=40]
    if not best_candidates: best_candidates = [results[0]]
    best_candidates.sort(key=lambda x:x['n'], reverse=True)
    best = best_candidates[0]
    best_p={k:best[k] for k in ['order','lookback','vol_mult','tp_r','sl_atr','max_hold','trend_align']}

    print(f"\n\n▶ 最优参数交叉验证: order={best_p['order']} lb={best_p['lookback']} "
          f"vol≥{best_p['vol_mult']}x TP={best_p['tp_r']}R SL={best_p['sl_atr']}ATR "
          f"H={best_p['max_hold']} trend={'ON' if best_p['trend_align'] else 'OFF'}")
    print("─"*65)
    print(f"{'品种':<12}{'笔':>5}{'胜率':>7}{'盈U':>10}{'DD':>7}{'PF':>6}{'多':>5}{'空':>5}")
    print("─"*65)
    total_pnl=0
    for label,path in datasets.items():
        d2=precompute(load_df_np(path))
        db2=precompute_bos(d2,best_p['order'],best_p['lookback'])
        r2=bos_v4(db2,best_p)
        total_pnl+=r2['pnl']
        ok='✅' if r2['pnl']>0 and r2['wr']>=45 else ('⚠️ ' if r2['pnl']>0 else '❌ ')
        print(f"{ok}{label:<11}{r2['n']:>5}{r2['wr']:>6.1f}%"
              f"{r2['pnl']:>+9.2f}U{r2['dd']:>6.1f}%{r2['pf']:>5.2f}"
              f"{r2['longs']:>5}{r2['shorts']:>5}")
    print(f"{'合计':>14}{'':>5}{'':>7}{total_pnl:>+9.2f}U")
    print("\n" + "="*65)
    print(f"结论: {'✅ 正期望！进入整合' if total_pnl>5 else ('⚠️ 部分正期望' if total_pnl>0 else '❌ 仍亏损')}")
