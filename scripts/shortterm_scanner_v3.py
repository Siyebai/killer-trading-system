"""
短线策略扫描器 v3.0
Plan A: 多组TP/SL比率测试 (1:1 / 1.5:1.5 / 2:1.5 / 2.5:1.5 / 3:2)
Plan B: 顶候选策略 + 趋势过滤(EMA方向 + ADX) 深度验证
"""
import json, time
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product

DATA_DIR = Path("/root/.openclaw/workspace/killer-trading-system/data")
FEE = 0.0018
MAX_HOLD = 20
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TIMEFRAMES = ["3m", "5m", "10m", "15m"]

# ── Plan A: TP/SL组合 ──────────────────────────────────────
TP_SL_COMBOS = [
    (1.0, 1.0),   # 平衡型 盈亏平衡WR=50%
    (1.5, 1.0),   # 偏大TP 盈亏平衡WR=40%
    (2.0, 1.0),   # 大TP   盈亏平衡WR=33%
    (2.5, 1.5),   # 原配置 盈亏平衡WR=37.5%
    (2.0, 1.5),   # 小改   盈亏平衡WR=42.9%
    (3.0, 2.0),   # 高盈亏比 盈亏平衡WR=40%
]


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
            if "open" not in df.columns: df["open"] = df["close"]
            if "volume" not in df.columns: df["volume"] = 0
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["close"]).reset_index(drop=True)
    return None


def calc_atr(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    tr[0] = h[0]-l[0]
    atr = np.zeros(len(tr)); atr[:n] = tr[:n].mean()
    for i in range(n, len(tr)): atr[i] = atr[i-1]*(n-1)/n + tr[i]/n
    return atr


def ema_vec(s, n):
    a = 2/(n+1); out = np.zeros(len(s)); out[0] = s[0]
    for i in range(1, len(s)): out[i] = s[i]*a + out[i-1]*(1-a)
    return out


def calc_adx(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    tr[0] = h[0]-l[0]
    pdm = np.where((h - np.roll(h,1) > np.roll(l,1) - l) & (h - np.roll(h,1) > 0), h - np.roll(h,1), 0.0)
    ndm = np.where((np.roll(l,1) - l > h - np.roll(h,1)) & (np.roll(l,1) - l > 0), np.roll(l,1) - l, 0.0)
    pdm[0] = ndm[0] = 0
    atr14 = np.zeros(len(tr)); atr14[:n] = tr[:n].mean()
    pdi14 = np.zeros(len(tr)); pdi14[:n] = pdm[:n].mean()
    ndi14 = np.zeros(len(tr)); ndi14[:n] = ndm[:n].mean()
    for i in range(n, len(tr)):
        atr14[i] = atr14[i-1]*(n-1)/n + tr[i]/n
        pdi14[i] = pdi14[i-1]*(n-1)/n + pdm[i]/n
        ndi14[i] = ndi14[i-1]*(n-1)/n + ndm[i]/n
    with np.errstate(divide='ignore', invalid='ignore'):
        pdi = np.where(atr14>0, 100*pdi14/atr14, 0)
        ndi = np.where(atr14>0, 100*ndi14/atr14, 0)
        dx  = np.where((pdi+ndi)>0, 100*np.abs(pdi-ndi)/(pdi+ndi), 0)
    adx = np.zeros(len(dx)); adx[:n] = dx[:n].mean()
    for i in range(n, len(dx)): adx[i] = adx[i-1]*(n-1)/n + dx[i]/n
    return adx


def vectorized_backtest(entry_idx, direction, df, tp_mult=2.5, sl_mult=1.5):
    at = calc_atr(df)
    c  = df["close"].values
    h  = df["high"].values
    l  = df["low"].values
    N  = len(c)
    wins = losses = 0
    for i in entry_idx:
        if i+MAX_HOLD >= N: continue
        entry = c[i]; sl_d = at[i]*sl_mult; tp_d = at[i]*tp_mult
        if sl_d < 1e-9: continue
        sl = entry - direction*sl_d; tp = entry + direction*tp_d
        outcome = 2
        for j in range(i+1, min(i+MAX_HOLD+1, N)):
            if direction == 1:
                if l[j] <= sl: outcome = 0; break
                if h[j] >= tp: outcome = 1; break
            else:
                if h[j] >= sl: outcome = 0; break
                if l[j] <= tp: outcome = 1; break
        if outcome == 1: wins += 1
        elif outcome == 0: losses += 1
        else:
            pnl = (c[i+MAX_HOLD]-entry)*direction/entry
            if pnl > FEE: wins += 1
            else: losses += 1
    n = wins + losses
    if n == 0: return 0, 0, 0
    wr = wins/n
    ev = wr*tp_mult - (1-wr)*sl_mult - FEE
    return wr, ev, n


def three_fold(idx_all, direction, df, tp_mult=2.5, sl_mult=1.5):
    n = len(idx_all)
    if n < 30: return None
    segs = [idx_all[:n//3], idx_all[n//3:2*n//3], idx_all[2*n//3:]]
    return [vectorized_backtest(s, direction, df, tp_mult, sl_mult)[:2] for s in segs]


# ── 策略信号生成 ──────────────────────────────────────────

def s2_ema_pullback(df):
    c = df["close"].values
    e9 = ema_vec(c, 9); e21 = ema_vec(c, 21); e55 = ema_vec(c, 55)
    longs, shorts = [], []
    for i in range(60, len(c)-1):
        if e9[i]>e21[i]>e55[i] and c[i-1]>e21[i-1] and c[i]<=e21[i]: longs.append(i)
        elif e9[i]<e21[i]<e55[i] and c[i-1]<e21[i-1] and c[i]>=e21[i]: shorts.append(i)
    return longs, shorts


def s4_momentum_reversal(df, n=4, min_pct=0.003):
    c = df["close"].values
    longs, shorts = [], []
    for i in range(n+1, len(c)-1):
        mvs = [c[i-k]-c[i-k-1] for k in range(n)]
        cum = (c[i]-c[i-n])/c[i-n]
        if all(m>0 for m in mvs) and cum>=min_pct: shorts.append(i)
        elif all(m<0 for m in mvs) and abs(cum)>=min_pct: longs.append(i)
    return longs, shorts


def s1_structure_break(df, lb=10):
    c = df["close"].values; h = df["high"].values; l = df["low"].values
    longs, shorts = [], []
    for i in range(lb+1, len(c)-1):
        ph = h[i-lb:i].max(); pl = l[i-lb:i].min()
        if c[i]>ph and c[i-1]<=ph: longs.append(i)
        elif c[i]<pl and c[i-1]>=pl: shorts.append(i)
    return longs, shorts


def s5_sr_bounce(df, lb=50, tol=0.002):
    c = df["close"].values; h = df["high"].values; l = df["low"].values
    longs, shorts = [], []
    for i in range(lb+2, len(c)-1):
        sup = np.percentile(l[i-lb:i-2], 15); res = np.percentile(h[i-lb:i-2], 85)
        if abs(l[i]-sup)/sup < tol and c[i]>c[i-1]: longs.append(i)
        elif abs(h[i]-res)/res < tol and c[i]<c[i-1]: shorts.append(i)
    return longs, shorts


# ── Plan B: 趋势过滤器 ────────────────────────────────────
def apply_trend_filter(idx, direction, df, ema_period=55, adx_min=20):
    """
    过滤条件（同时满足）：
    1. EMA55方向与信号一致（LONG要求close>EMA55，SHORT要求close<EMA55）
    2. ADX(14) >= adx_min（有趋势）
    """
    c    = df["close"].values
    e55  = ema_vec(c, ema_period)
    adx  = calc_adx(df)
    filtered = []
    for i in idx:
        if i >= len(c): continue
        trend_ok = (c[i] > e55[i]) if direction == 1 else (c[i] < e55[i])
        adx_ok   = adx[i] >= adx_min
        if trend_ok and adx_ok:
            filtered.append(i)
    return filtered


def apply_vol_filter(idx, df, vol_mult=1.5):
    """成交量放大过滤：当前vol > MA20 * vol_mult"""
    vol = df["volume"].values
    vol_ma = np.zeros(len(vol))
    for i in range(20, len(vol)):
        vol_ma[i] = vol[i-20:i].mean()
    filtered = [i for i in idx if i >= 20 and vol_ma[i] > 0 and vol[i] >= vol_ma[i] * vol_mult]
    return filtered


# ── PLAN A: TP/SL扫描 ─────────────────────────────────────
def run_plan_a():
    print("\n" + "="*100)
    print("PLAN A — TP/SL比率对比（TOP候选策略）")
    print("="*100)

    # 只测试v2中EV>0的顶级组合
    TOP_COMBOS = [
        ("SOLUSDT", "15m", "S2_EMAPullback", -1),
        ("ETHUSDT", "15m", "S2_EMAPullback", -1),
        ("BTCUSDT", "15m", "S4_MomReversal", -1),
        ("BNBUSDT", "15m", "S2_EMAPullback", -1),
        ("SOLUSDT",  "5m", "S2_EMAPullback", -1),
        ("ETHUSDT",  "5m", "S5_SRBounce",   -1),
        ("SOLUSDT",  "3m", "S4_MomReversal", -1),
        ("BTCUSDT",  "5m", "S4_MomReversal",  1),
        ("BNBUSDT",  "5m", "S4_MomReversal",  1),
        ("BTCUSDT", "15m", "S4_MomReversal",  1),
    ]

    STRAT_MAP = {
        "S2_EMAPullback":   s2_ema_pullback,
        "S4_MomReversal":   s4_momentum_reversal,
        "S5_SRBounce":      s5_sr_bounce,
        "S1_StructureBreak": s1_structure_break,
    }

    print(f"{'Symbol':<10} {'TF':<5} {'Strategy':<22} {'Dir':<6} ", end="")
    for tp, sl in TP_SL_COMBOS:
        print(f"  TP{tp}/SL{sl}({tp/(tp+sl):.0%})", end="")
    print()
    print("-"*130)

    best_cells = []  # (ev, wr, tp, sl, sym, tf, strat, d, n)

    for sym, tf, sname, direction in TOP_COMBOS:
        df = load_df(sym, tf)
        if df is None or len(df) < 200: continue
        sfunc = STRAT_MAP[sname]
        longs, shorts = sfunc(df)
        idx = longs if direction == 1 else shorts
        if len(idx) < 20: continue
        dname = "LONG" if direction == 1 else "SHORT"
        print(f"{sym:<10} {tf:<5} {sname:<22} {dname:<6} ", end="")
        for tp, sl in TP_SL_COMBOS:
            wr, ev, n = vectorized_backtest(idx, direction, df, tp, sl)
            flag = "✅" if wr >= 0.50 and ev > 0 else ("⬆" if wr >= 0.45 and ev > 0 else ("+" if ev > 0 else " "))
            print(f"  {wr:>5.1%}/{ev:>+.3f}{flag}", end="")
            if ev > 0 and wr > 0:
                best_cells.append((ev, wr, tp, sl, sym, tf, sname, dname, n))
        print()

    print()
    print("▶ PLAN A 最优单元格 (EV>0, 按EV降序):")
    best_cells.sort(reverse=True)
    for ev, wr, tp, sl, sym, tf, sname, dname, n in best_cells[:15]:
        be = sl/(tp+sl)
        print(f"  {sym} {tf} {sname} {dname}  TP={tp}/SL={sl}(盈亏平衡={be:.0%})  WR={wr:.1%}  EV={ev:.4f}  n={n}")


# ── PLAN B: 趋势过滤深度验证 ──────────────────────────────
def run_plan_b():
    print("\n" + "="*100)
    print("PLAN B — 趋势过滤器对比（EMA55 + ADX）")
    print("="*100)

    TOP_COMBOS = [
        ("SOLUSDT", "15m", "S2_EMAPullback", -1),
        ("ETHUSDT", "15m", "S2_EMAPullback", -1),
        ("BTCUSDT", "15m", "S4_MomReversal", -1),
        ("BNBUSDT", "15m", "S2_EMAPullback", -1),
        ("SOLUSDT",  "5m", "S2_EMAPullback", -1),
        ("ETHUSDT",  "5m", "S5_SRBounce",   -1),
        ("SOLUSDT",  "3m", "S4_MomReversal", -1),
        ("BTCUSDT",  "5m", "S4_MomReversal",  1),
        ("BNBUSDT",  "5m", "S4_MomReversal",  1),
        ("BTCUSDT", "15m", "S4_MomReversal",  1),
    ]

    STRAT_MAP = {
        "S2_EMAPullback":    s2_ema_pullback,
        "S4_MomReversal":    s4_momentum_reversal,
        "S5_SRBounce":       s5_sr_bounce,
        "S1_StructureBreak": s1_structure_break,
    }

    ADX_LEVELS = [15, 20, 25]

    hdr = f"{'Symbol':<10} {'TF':<5} {'Strategy':<22} {'Dir':<6} {'原始':>14}"
    for adx in ADX_LEVELS:
        hdr += f"  {'EMA+ADX>='+str(adx):>18}"
    hdr += f"  {'EMA+ADX+Vol1.5':>20}"
    print(hdr)
    print("-"*130)

    plan_b_best = []

    for sym, tf, sname, direction in TOP_COMBOS:
        df = load_df(sym, tf)
        if df is None or len(df) < 200: continue
        sfunc = STRAT_MAP[sname]
        longs, shorts = sfunc(df)
        idx_raw = longs if direction == 1 else shorts
        if len(idx_raw) < 20: continue
        dname = "LONG" if direction == 1 else "SHORT"

        wr0, ev0, n0 = vectorized_backtest(idx_raw, direction, df)
        line = f"{sym:<10} {tf:<5} {sname:<22} {dname:<6} n={n0:>4} WR={wr0:.1%} EV={ev0:+.3f}"

        for adx_min in ADX_LEVELS:
            idx_f = apply_trend_filter(idx_raw, direction, df, adx_min=adx_min)
            if len(idx_f) < 15:
                line += f"  {'n<15':>18}"
                continue
            wr, ev, n = vectorized_backtest(idx_f, direction, df)
            fold = three_fold(idx_f, direction, df)
            fold_s = "/".join([f"{r[0]:.0%}" for r in fold]) if fold else "N/A"
            flag = "✅" if wr >= 0.50 and ev > 0 else ("⬆" if wr >= 0.45 and ev > 0 else ("+" if ev > 0 else " "))
            line += f"  n={n:>4} WR={wr:.1%} EV={ev:+.3f}{flag}"
            if ev > 0:
                plan_b_best.append((ev, wr, adx_min, "EMA+ADX", sym, tf, sname, dname, n, fold_s))

        # EMA + ADX20 + Vol过滤
        idx_f2 = apply_trend_filter(idx_raw, direction, df, adx_min=20)
        idx_fv = apply_vol_filter(idx_f2, df, vol_mult=1.5)
        if len(idx_fv) >= 15:
            wr, ev, n = vectorized_backtest(idx_fv, direction, df)
            fold = three_fold(idx_fv, direction, df)
            fold_s = "/".join([f"{r[0]:.0%}" for r in fold]) if fold else "N/A"
            flag = "✅" if wr >= 0.50 and ev > 0 else ("⬆" if wr >= 0.45 and ev > 0 else ("+" if ev > 0 else " "))
            line += f"  n={n:>4} WR={wr:.1%} EV={ev:+.3f}{flag}"
            if ev > 0:
                plan_b_best.append((ev, wr, 20, "EMA+ADX+Vol", sym, tf, sname, dname, n, fold_s))
        else:
            line += f"  {'n<15':>20}"

        print(line)

    print()
    print("▶ PLAN B TOP候选 (EV>0):")
    plan_b_best.sort(reverse=True)
    for ev, wr, adx_min, ftype, sym, tf, sname, dname, n, fold_s in plan_b_best[:20]:
        print(f"  {sym} {tf} {sname} {dname}  过滤={ftype}(ADX>={adx_min})  n={n}  WR={wr:.1%}  EV={ev:.4f}  3-fold=[{fold_s}]")


# ── PLAN A+B 联合：最优过滤 × 最优TP/SL ──────────────────
def run_combined():
    print("\n" + "="*100)
    print("COMBINED — 最优过滤 × 多TP/SL（穷举TOP候选）")
    print("="*100)

    TOP_COMBOS = [
        ("SOLUSDT", "15m", "S2_EMAPullback", -1),
        ("ETHUSDT", "15m", "S2_EMAPullback", -1),
        ("BNBUSDT", "15m", "S2_EMAPullback", -1),
        ("BTCUSDT", "15m", "S4_MomReversal", -1),
        ("SOLUSDT",  "5m", "S2_EMAPullback", -1),
    ]

    STRAT_MAP = {
        "S2_EMAPullback":  s2_ema_pullback,
        "S4_MomReversal":  s4_momentum_reversal,
    }

    all_results = []
    for sym, tf, sname, direction in TOP_COMBOS:
        df = load_df(sym, tf)
        if df is None or len(df) < 200: continue
        sfunc = STRAT_MAP[sname]
        longs, shorts = sfunc(df)
        idx_raw = longs if direction == 1 else shorts
        dname = "LONG" if direction == 1 else "SHORT"

        for adx_min in [15, 20, 25]:
            idx_f = apply_trend_filter(idx_raw, direction, df, adx_min=adx_min)
            if len(idx_f) < 15: continue
            for tp, sl in TP_SL_COMBOS:
                wr, ev, n = vectorized_backtest(idx_f, direction, df, tp, sl)
                if ev > 0 and n >= 15:
                    fold = three_fold(idx_f, direction, df, tp, sl)
                    if fold:
                        min_wr = min(r[0] for r in fold)
                        fold_s = "/".join([f"{r[0]:.0%}" for r in fold])
                    else:
                        min_wr = 0; fold_s = "N/A"
                    all_results.append((ev, wr, min_wr, tp, sl, adx_min, sym, tf, sname, dname, n, fold_s))

    all_results.sort(reverse=True)
    print(f"{'Symbol':<10} {'TF':<5} {'Strategy':<22} {'Dir':<6} {'ADX':>5} {'TP/SL':>8} {'n':>5} {'WR':>7} {'EV':>8} {'min_fold':>9}  3-fold")
    print("-"*120)
    seen = set()
    for ev, wr, min_wr, tp, sl, adx_min, sym, tf, sname, dname, n, fold_s in all_results[:30]:
        key = f"{sym}{tf}{sname}{dname}"
        marker = " ★" if key not in seen else ""
        seen.add(key)
        flag = "✅✅" if wr >= 0.52 and min_wr >= 0.45 else ("✅" if wr >= 0.48 and ev > 0.05 else ("⬆" if wr >= 0.45 else ""))
        print(f"{sym:<10} {tf:<5} {sname:<22} {dname:<6} {adx_min:>5} {str(tp)+'/'+str(sl):>8} {n:>5} {wr:>7.1%} {ev:>8.4f} {min_wr:>9.1%}  [{fold_s}]{flag}{marker}")


# ── MAIN ─────────────────────────────────────────────────
if __name__ == "__main__":
    t0 = time.time()
    run_plan_a()
    run_plan_b()
    run_combined()
    print(f"\n[总耗时 {time.time()-t0:.1f}s]")
