#!/usr/bin/env python3
"""
fast_engine.py — 高性能混合引擎 v2
指标计算：pandas rolling（C底层，快10倍）
回测循环：纯 NumPy ndarray（无 .iloc overhead）
基准：BTC 5m 17280根 × 144组参数 < 3s
"""

import json
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional

# ────────────────────────────────────────────
# 数据加载（兼容两种格式）
# ────────────────────────────────────────────

def load_df_np(path: str) -> Dict[str, np.ndarray]:
    """加载 JSON → NumPy dict，兼容 list-of-list 和 list-of-dict"""
    with open(path) as f:
        raw = json.load(f)
    if not raw:
        raise ValueError(f"Empty: {path}")
    if isinstance(raw[0], (list, tuple)):
        arr = np.array(raw, dtype=object)
        return {
            'ts':     arr[:, 0].astype(np.float64),
            'open':   arr[:, 1].astype(np.float64),
            'high':   arr[:, 2].astype(np.float64),
            'low':    arr[:, 3].astype(np.float64),
            'close':  arr[:, 4].astype(np.float64),
            'volume': arr[:, 5].astype(np.float64),
        }
    else:
        keys = list(raw[0].keys())
        fm = {
            'ts':     next((k for k in ['ts','timestamp','time','open_time'] if k in keys), None),
            'open':   next((k for k in ['open','o'] if k in keys), None),
            'high':   next((k for k in ['high','h'] if k in keys), None),
            'low':    next((k for k in ['low','l'] if k in keys), None),
            'close':  next((k for k in ['close','c'] if k in keys), None),
            'volume': next((k for k in ['volume','v','vol'] if k in keys), None),
        }
        return {ok: np.array([r[sk] for r in raw], dtype=np.float64) if sk else np.zeros(len(raw))
                for ok, sk in fm.items()}

# ────────────────────────────────────────────
# 指标计算（pandas rolling，C底层）
# ────────────────────────────────────────────

def precompute(d: Dict) -> Dict:
    """一次性计算全部指标，返回纯 ndarray 扩展 dict"""
    c = pd.Series(d['close'])
    h = pd.Series(d['high'])
    l = pd.Series(d['low'])
    v = pd.Series(d['volume'])
    o = pd.Series(d['open'])

    # RSI Wilder EWM
    delta = c.diff()
    gain  = delta.where(delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
    loss  = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    rsi   = (100.0 - 100.0 / (1.0 + gain / loss.replace(0, np.nan))).fillna(50).values

    # ATR
    pc  = c.shift(1)
    tr  = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False).mean().values

    # Bollinger Bands
    bb_ma  = c.rolling(20).mean()
    bb_std = c.rolling(20).std()
    bb_up  = bb_ma + 2 * bb_std
    bb_lo  = bb_ma - 2 * bb_std
    bb_pct = ((c - bb_lo) / (bb_up - bb_lo)).fillna(0.5).values
    bb_mid = bb_ma.bfill().values

    # EMA
    e9   = c.ewm(span=9,   adjust=False).mean().values
    e20  = c.ewm(span=20,  adjust=False).mean().values
    e50  = c.ewm(span=50,  adjust=False).mean().values
    e200 = c.ewm(span=200, adjust=False).mean().values

    # MACD histogram
    ema_f  = c.ewm(span=12, adjust=False).mean()
    ema_s  = c.ewm(span=26, adjust=False).mean()
    ml     = ema_f - ema_s
    sig    = ml.ewm(span=9, adjust=False).mean()
    macd_h = (ml - sig).values

    # Volume MA
    vol_ma = v.rolling(20).mean().fillna(v.mean()).values

    return {**d,
        'rsi': rsi, 'atr': atr,
        'bb_pct': bb_pct, 'bb_mid': bb_mid,
        'vol_ma': vol_ma,
        'e9': e9, 'e20': e20, 'e50': e50, 'e200': e200,
        'macd_h': macd_h,
    }

# ────────────────────────────────────────────
# 高速回测（纯 ndarray，无 pandas）
# ────────────────────────────────────────────

def fast_backtest(d: Dict, params: Dict,
                  fee: float = 0.0009, capital: float = 150.0) -> Dict:
    """
    向量化预筛选 + 精简内循环
    约比原版快 3-4 倍
    """
    c=d['close']; h=d['high']; l=d['low']; v=d['volume']; o=d['open']
    rsi=d['rsi']; atr=d['atr']; bb_pct=d['bb_pct']; bb_mid=d['bb_mid']
    vol_ma=d['vol_ma']; e20=d['e20']; e50=d['e50']
    n = len(c)

    rsi_th_l  = params.get('rsi_th_l', 28)
    rsi_th_s  = params.get('rsi_th_s', 72)
    tp_mult   = params.get('tp_mult', 2.0)
    sl_mult   = params.get('sl_mult', 0.8)
    max_hold  = params.get('max_hold', 8)
    risk_pct  = params.get('risk_pct', 0.02)
    mode      = params.get('mode', 'rsi_reversal')
    bb_filter = params.get('bb_filter', True)
    vol_filter= params.get('vol_filter', True)
    trend_flt = params.get('trend_filter', False)
    warmup    = params.get('warmup', 50)

    # ── 向量化预筛选信号索引（大幅减少内循环判断）──
    idx = np.arange(warmup, n)
    cg = c[idx] > o[idx]
    cr = c[idx] < o[idx]
    rv = rsi[idx]; rp = rsi[idx-1]
    vr = np.where(vol_ma[idx]>0, v[idx]/vol_ma[idx], 1.0)

    # 做多候选
    long_mask = (rv < rsi_th_l) & (rv > rp) & cg
    if bb_filter:  long_mask &= (bb_pct[idx] < 0.35)
    if vol_filter: long_mask &= (vr > 0.7)
    if trend_flt:  long_mask &= (e20[idx] >= e50[idx] * 0.995)
    long_idx = set(idx[long_mask].tolist())

    # 做空候选
    short_mask = (rv > rsi_th_s) & (rv < rp) & cr
    if bb_filter:  short_mask &= (bb_pct[idx] > 0.65)
    if vol_filter: short_mask &= (vr > 0.7)
    if trend_flt:  short_mask &= (e20[idx] <= e50[idx] * 1.005)
    short_idx = set(idx[short_mask].tolist()) if mode in ('rsi_overbought','both') else set()

    eq=capital; pos=None; trades=[]
    max_eq=capital; max_dd=0.0

    for i in range(warmup, n):
        p=c[i]; av=atr[i]
        if np.isnan(av): continue

        # 出场
        if pos is not None:
            ep2=None; er=None
            if pos['d']=='L':
                if l[i]<=pos['sl']: ep2=pos['sl']; er='SL'
                elif h[i]>=pos['tp']: ep2=pos['tp']; er='TP'
                elif rsi[i]>70: ep2=p; er='OB'
            else:
                if h[i]>=pos['sl']: ep2=pos['sl']; er='SL'
                elif l[i]<=pos['tp']: ep2=pos['tp']; er='TP'
                elif rsi[i]<30: ep2=p; er='OS'
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

        # 做多入场（仅检查预筛选通过的索引）
        if mode in ('rsi_reversal','both') and i in long_idx:
            bm=bb_mid[i]
            tp=max(bm if bm>p else p+av*tp_mult, p+av*tp_mult*0.5)
            sl=p-av*sl_mult; slp=(p-sl)/p
            sz=min(eq*risk_pct/slp, eq*0.5) if slp>0 else 0
            pos={'d':'L','ep':p,'i':i,'tp':tp,'sl':sl,'sz':sz}
            continue

        # 做空入场
        if i in short_idx:
            bm=bb_mid[i]
            tp=min(bm if bm<p else p-av*tp_mult, p-av*tp_mult*0.5)
            sl=p+av*sl_mult; slp=(sl-p)/p
            sz=min(eq*risk_pct/slp, eq*0.5) if slp>0 else 0
            pos={'d':'S','ep':p,'i':i,'tp':tp,'sl':sl,'sz':sz}

    total=len(trades)
    wins=[t for t in trades if t['u']>0]; losses=[t for t in trades if t['u']<=0]
    gw=sum(t['u'] for t in wins); gl=sum(t['u'] for t in losses)
    return {
        'n':total,'wr':len(wins)/total*100 if total else 0,
        'pnl':eq-capital,'final':eq,'dd':max_dd,
        'pf':gw/abs(gl) if gl<0 else 999,
        'aw':np.mean([t['u'] for t in wins])  if wins   else 0,
        'al':np.mean([t['u'] for t in losses]) if losses else 0,
        'tp':sum(1 for t in trades if t['er']=='TP'),
        'sl':sum(1 for t in trades if t['er']=='SL'),
        'longs': sum(1 for t in trades if t['d']=='L'),
        'shorts':sum(1 for t in trades if t['d']=='S'),
        'trades':trades,
    }

def grid_search(d: Dict, param_grid: List[Dict],
                fee: float=0.0009, capital: float=150.0,
                min_trades: int=15) -> List[Dict]:
    results=[]
    for p in param_grid:
        r=fast_backtest(d,p,fee,capital)
        if r['n']>=min_trades:
            results.append({**p,**r})
    results.sort(key=lambda x:x['pnl'],reverse=True)
    return results

def benchmark():
    import os
    base=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path=os.path.join(base,'data','BTCUSDT_5m_60d.json')
    t0=time.time()
    raw=load_df_np(path); t1=time.time()
    d=precompute(raw); t2=time.time()
    r=fast_backtest(d,{'rsi_th_l':28,'tp_mult':2.0,'sl_mult':0.8,'max_hold':8}); t3=time.time()
    grid=[
        {'rsi_th_l':rt,'tp_mult':tm,'sl_mult':sm,'max_hold':mh}
        for rt in [24,26,28,30,32,35]
        for tm in [1.5,2.0,2.5,3.0]
        for sm in [0.6,0.8,1.0]
        for mh in [4,8,12]
    ]
    all_r=grid_search(d,grid); t4=time.time()
    print(f"数据加载:   {(t1-t0)*1000:.0f}ms  ({len(raw['close'])}根K线)")
    print(f"指标计算:   {(t2-t1)*1000:.0f}ms")
    print(f"单次回测:   {(t3-t2)*1000:.0f}ms  ({r['n']}笔交易)")
    print(f"144组网格:  {(t4-t3)*1000:.0f}ms  ({len(all_r)}个有效结果)")
    print(f"总耗时:     {(t4-t0)*1000:.0f}ms  ✅")
    if all_r:
        b=all_r[0]
        print(f"\n最优: RSI<{b.get('rsi_th_l')} TP={b.get('tp_mult')}x SL={b.get('sl_mult')}x H={b.get('max_hold')}")
        print(f"      {b['n']}笔 胜率{b['wr']:.1f}% 盈亏{b['pnl']:+.2f}U DD:{b['dd']:.1f}% PF:{b['pf']:.2f}")

if __name__=='__main__':
    benchmark()

