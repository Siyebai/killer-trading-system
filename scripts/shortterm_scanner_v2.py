"""
短线策略扫描器 v2.0 — 全向量化，速度优先
5策略 × 4品种 × 4周期 = 80组
"""
import json, os, time
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path("/root/.openclaw/workspace/killer-trading-system/data")
FEE = 0.0018   # 双边 0.18%
SL_MULT = 1.5
TP_MULT = 2.5
MAX_HOLD = 20
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TIMEFRAMES = ["3m", "5m", "10m", "15m"]


def load_df(symbol, tf):
    for fname in [f"{symbol}_{tf}_90d.json", f"{symbol}_{tf}.json", f"{symbol}_{tf}_live.json"]:
        p = DATA_DIR / fname
        if not p.exists(): continue
        raw = json.load(open(p))
        data = raw if isinstance(raw, list) else raw.get("data", [])
        if not data: continue
        df = pd.DataFrame(data)
        if isinstance(data[0], (list, tuple)):
            df.columns = (["ts","open","high","low","close","volume"]+[f"x{i}" for i in range(6,len(df.columns))])[:len(df.columns)]
        else:
            rmap = {}
            for c in df.columns:
                cl = c.lower()
                if cl in ("ts","time","timestamp","open_time"): rmap[c]="ts"
                elif cl in ("o","open"): rmap[c]="open"
                elif cl in ("h","high"): rmap[c]="high"
                elif cl in ("l","low"):  rmap[c]="low"
                elif cl in ("c","close"): rmap[c]="close"
                elif cl in ("v","volume","vol"): rmap[c]="volume"
            df = df.rename(columns=rmap)
            if "open" not in df.columns: df["open"]=df["close"]
            if "volume" not in df.columns: df["volume"]=0
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["close"]).reset_index(drop=True)
    return None


def calc_atr(df, n=14):
    h,l,c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    tr[0]=h[0]-l[0]
    atr=np.zeros(len(tr)); atr[:n]=tr[:n].mean()
    for i in range(n,len(tr)): atr[i]=atr[i-1]*(n-1)/n+tr[i]/n
    return atr


def vectorized_backtest(entry_idx, direction, df):
    """完全向量化回测，返回 (wr, ev, n)"""
    at  = calc_atr(df)
    c   = df["close"].values
    h   = df["high"].values
    l   = df["low"].values
    N   = len(c)
    wins=0; losses=0; max_holds=0
    for i in entry_idx:
        if i+MAX_HOLD>=N: continue
        entry=c[i]; sl_d=at[i]*SL_MULT; tp_d=at[i]*TP_MULT
        if sl_d<1e-9: continue
        sl=entry-direction*sl_d; tp=entry+direction*tp_d
        outcome=2  # max_hold
        for j in range(i+1, min(i+MAX_HOLD+1, N)):
            if direction==1:
                if l[j]<=sl: outcome=0; break
                if h[j]>=tp: outcome=1; break
            else:
                if h[j]>=sl: outcome=0; break
                if l[j]<=tp: outcome=1; break
        if outcome==1: wins+=1
        elif outcome==0: losses+=1
        else:
            pnl=(c[i+MAX_HOLD]-entry)*direction/entry
            if pnl>FEE: wins+=1
            else: losses+=1
    n=wins+losses
    if n==0: return 0,0,0
    wr=wins/n
    ev=wr*TP_MULT-(1-wr)*SL_MULT-FEE
    return wr,ev,n


def ema_vec(s, n):
    a=2/(n+1); out=np.zeros(len(s)); out[0]=s[0]
    for i in range(1,len(s)): out[i]=s[i]*a+out[i-1]*(1-a)
    return out


# ── 5 strategies ────────────────────────────────────────────
def s1_structure_break(df, lb=10):
    c=df["close"].values; h=df["high"].values; l=df["low"].values
    longs,shorts=[],[]
    for i in range(lb+1,len(c)-1):
        ph=h[i-lb:i].max(); pl=l[i-lb:i].min()
        if c[i]>ph and c[i-1]<=ph: longs.append(i)
        elif c[i]<pl and c[i-1]>=pl: shorts.append(i)
    return longs, shorts

def s2_ema_pullback(df):
    c=df["close"].values
    e9=ema_vec(c,9); e21=ema_vec(c,21); e55=ema_vec(c,55)
    longs,shorts=[],[]
    for i in range(60,len(c)-1):
        if e9[i]>e21[i]>e55[i] and c[i-1]>e21[i-1] and c[i]<=e21[i]: longs.append(i)
        elif e9[i]<e21[i]<e55[i] and c[i-1]<e21[i-1] and c[i]>=e21[i]: shorts.append(i)
    return longs, shorts

def s3_atr_squeeze(df, cp=20, bp=5):
    at=calc_atr(df); c=df["close"].values; h=df["high"].values; l=df["low"].values
    longs,shorts=[],[]
    for i in range(cp+bp, len(c)-1):
        hist=np.median(at[i-cp:i])
        if at[i]>hist*0.6: continue
        rh=h[i-bp:i].max(); rl=l[i-bp:i].min()
        if c[i]>rh and c[i-1]<=rh: longs.append(i)
        elif c[i]<rl and c[i-1]>=rl: shorts.append(i)
    return longs, shorts

def s4_momentum_reversal(df, n=4, min_pct=0.003):
    c=df["close"].values
    longs,shorts=[],[]
    for i in range(n+1,len(c)-1):
        mvs=[c[i-k]-c[i-k-1] for k in range(n)]
        cum=(c[i]-c[i-n])/c[i-n]
        if all(m>0 for m in mvs) and cum>=min_pct: shorts.append(i)
        elif all(m<0 for m in mvs) and abs(cum)>=min_pct: longs.append(i)
    return longs, shorts

def s5_sr_bounce(df, lb=50, tol=0.002):
    c=df["close"].values; h=df["high"].values; l=df["low"].values
    longs,shorts=[],[]
    for i in range(lb+2,len(c)-1):
        sup=np.percentile(l[i-lb:i-2],15); res=np.percentile(h[i-lb:i-2],85)
        if abs(l[i]-sup)/sup<tol and c[i]>c[i-1]: longs.append(i)
        elif abs(h[i]-res)/res<tol and c[i]<c[i-1]: shorts.append(i)
    return longs, shorts


STRATS = {
    "S1_StructureBreak": s1_structure_break,
    "S2_EMAPullback":    s2_ema_pullback,
    "S3_ATRSqueeze":     s3_atr_squeeze,
    "S4_MomReversal":    s4_momentum_reversal,
    "S5_SRBounce":       s5_sr_bounce,
}

# ── 三段验证 ────────────────────────────────────────────────
def three_fold(idx_all, direction, df):
    n=len(idx_all)
    if n<30: return None
    segs=[idx_all[:n//3], idx_all[n//3:2*n//3], idx_all[2*n//3:]]
    return [vectorized_backtest(s, direction, df)[:2] for s in segs]


def main():
    results=[]
    hdr=f"{'Symbol':<10} {'TF':<5} {'Strategy':<22} {'Dir':<5} {'n':>5} {'WR':>6} {'EV':>7}  3-fold"
    print(hdr); print("-"*90)
    t0=time.time()
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            df=load_df(sym,tf)
            if df is None or len(df)<200:
                print(f"{sym:<10} {tf:<5} NO DATA"); continue
            for sname, sfunc in STRATS.items():
                try:
                    longs, shorts = sfunc(df)
                    for direction, idx in [(1,longs),(-1,shorts)]:
                        if len(idx)<20: continue
                        wr,ev,n=vectorized_backtest(idx, direction, df)
                        fold=three_fold(idx, direction, df)
                        fold_s=""
                        if fold:
                            fold_s=" | ".join([f"WR{r[0]:.0%}" for r in fold])
                        flag=""
                        if wr>=0.57 and ev>0: flag=" ✅✅"
                        elif wr>=0.53 and ev>0: flag=" ✅"
                        elif wr>=0.50 and ev>0: flag=" ⚠️"
                        dname="LONG " if direction==1 else "SHORT"
                        print(f"{sym:<10} {tf:<5} {sname:<22} {dname} {n:>5} {wr:>6.1%} {ev:>7.4f}  [{fold_s}]{flag}")
                        results.append(dict(sym=sym,tf=tf,strat=sname,dir=dname,n=n,wr=wr,ev=ev,fold=fold))
                except Exception as e:
                    print(f"{sym:<10} {tf:<5} {sname} ERROR:{e}")
    elapsed=time.time()-t0
    print(f"\n[完成 {elapsed:.1f}s]\n")
    print("="*90)
    print("▶ TOP CANDIDATES (WR≥53%, EV>0):")
    top=[r for r in results if r["wr"]>=0.53 and r["ev"]>0]
    top.sort(key=lambda x:-x["ev"])
    if not top:
        print("  ⚠️  无WR≥53%候选，显示 WR≥50% EV>0:")
        top=[r for r in results if r["wr"]>=0.50 and r["ev"]>0]
        top.sort(key=lambda x:-x["ev"])
    for r in top[:20]:
        fold_s=""
        if r["fold"]:
            fold_s=" | ".join([f"WR{x[0]:.0%}/EV{x[1]:.3f}" for x in r["fold"]])
        print(f"  {r['sym']} {r['tf']} {r['strat']} {r['dir']}: WR={r['wr']:.1%} EV={r['ev']:.4f} n={r['n']}  [{fold_s}]")
    return results

if __name__=="__main__":
    main()
