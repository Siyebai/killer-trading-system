"""
任务A: S4_MomReversal SHORT — 三重条件组合深挖
条件1: 美盘时段 (UTC 16-24h)
条件2: 熊市环境 (EMA趋势下行 or 近期价格下跌)
条件3: n=6连涨 + pct≥0.005 + ADX≥20

验证维度:
- 三重组合WR + 样本量
- 不同熊市定义 (EMA距离 / 近N根K线涨跌)
- TP/SL比 扫描 (TP1.0~2.0, SL0.5~1.0)
- 多品种验证 (ETH/SOL/BNB)
"""
import json, time
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path("/root/.openclaw/workspace/killer-trading-system/data")
FEE      = 0.0018
MAX_HOLD = 20

def load_df(fpath):
    raw  = json.load(open(fpath))
    data = raw if isinstance(raw, list) else raw.get("data", [])
    if not data: return None
    df = pd.DataFrame(data)
    if isinstance(data[0], (list, tuple)):
        df.columns = (["ts","open","high","low","close","volume"]
                      + [f"x{i}" for i in range(6, len(df.columns))])[:len(df.columns)]
    else:
        rmap = {}
        for c in df.columns:
            cl = c.lower()
            if cl in ("ts","time","timestamp","open_time","opentime"): rmap[c]="ts"
            elif cl in ("o","open"):   rmap[c]="open"
            elif cl in ("h","high"):   rmap[c]="high"
            elif cl in ("l","low"):    rmap[c]="low"
            elif cl in ("c","close"):  rmap[c]="close"
            elif cl in ("v","volume","vol"): rmap[c]="volume"
        df = df.rename(columns=rmap)
        if "open" not in df.columns: df["open"] = df["close"]
        if "volume" not in df.columns: df["volume"] = 0
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["close"]).reset_index(drop=True)

def ema_vec(s, n):
    a = 2/(n+1); out = np.zeros(len(s)); out[0] = s[0]
    for i in range(1, len(s)): out[i] = s[i]*a + out[i-1]*(1-a)
    return out

def calc_atr(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    tr[0] = h[0]-l[0]
    atr = np.zeros(len(tr)); atr[:n] = tr[:n].mean()
    for i in range(n, len(tr)): atr[i] = atr[i-1]*(n-1)/n + tr[i]/n
    return atr

def calc_adx(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
    tr[0] = h[0]-l[0]
    pdm = np.where((h-np.roll(h,1) > np.roll(l,1)-l) & (h-np.roll(h,1) > 0), h-np.roll(h,1), 0.0)
    ndm = np.where((np.roll(l,1)-l > h-np.roll(h,1)) & (np.roll(l,1)-l > 0), np.roll(l,1)-l, 0.0)
    pdm[0] = ndm[0] = 0
    atr14 = np.zeros(len(tr)); atr14[:n] = tr[:n].mean()
    pdi14 = np.zeros(len(tr)); pdi14[:n] = pdm[:n].mean()
    ndi14 = np.zeros(len(tr)); ndi14[:n] = ndm[:n].mean()
    for i in range(n, len(tr)):
        atr14[i] = atr14[i-1]*(n-1)/n + tr[i]/n
        pdi14[i] = pdi14[i-1]*(n-1)/n + pdm[i]/n
        ndi14[i] = ndi14[i-1]*(n-1)/n + ndm[i]/n
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = np.where(atr14>0, 100*pdi14/atr14, 0)
        ndi = np.where(atr14>0, 100*ndi14/atr14, 0)
        dx  = np.where((pdi+ndi)>0, 100*np.abs(pdi-ndi)/(pdi+ndi), 0)
    adx = np.zeros(len(dx)); adx[:n] = dx[:n].mean()
    for i in range(n, len(dx)): adx[i] = adx[i-1]*(n-1)/n + dx[i]/n
    return adx

def s4_momentum_reversal(df, n=6, min_pct=0.005):
    """连续n根上涨后做空"""
    c = df["close"].values
    shorts = []
    for i in range(n+1, len(c)-1):
        mvs = [c[i-k]-c[i-k-1] for k in range(n)]
        cum = (c[i]-c[i-n])/c[i-n]
        if all(m > 0 for m in mvs) and cum >= min_pct:
            shorts.append(i)
    return shorts

def bear_market_filter(df, method="ema", lookback=96):
    """
    熊市过滤:
    method='ema'   : close < EMA50 且 EMA20 < EMA50
    method='slope' : 近lookback根K线价格下行
    method='both'  : 两者均满足
    """
    c = df["close"].values
    ema20 = ema_vec(c, 20)
    ema50 = ema_vec(c, 50)
    bear_ema = np.zeros(len(c), dtype=bool)
    for i in range(50, len(c)):
        bear_ema[i] = (c[i] < ema50[i]) and (ema20[i] < ema50[i])
    bear_slope = np.zeros(len(c), dtype=bool)
    for i in range(lookback, len(c)):
        slope = (c[i] - c[i-lookback]) / c[i-lookback]
        bear_slope[i] = slope < -0.03  # 近lookback根下跌超3%
    if method == "ema":    return bear_ema
    if method == "slope":  return bear_slope
    if method == "both":   return bear_ema & bear_slope
    return bear_ema

def us_session_filter(df):
    """美盘 UTC 16-24h"""
    ts = df["ts"].values
    mask = np.zeros(len(ts), dtype=bool)
    for i in range(len(ts)):
        hour = (int(ts[i]) // 3600000) % 24
        mask[i] = (hour >= 16)
    return mask

def apply_filters(raw_idx, df, adx_arr, bear_mask, us_mask,
                  use_adx=True, use_bear=True, use_us=True, adx_min=20):
    result = []
    for i in raw_idx:
        if use_adx  and adx_arr[i] < adx_min: continue
        if use_bear and not bear_mask[i]:      continue
        if use_us   and not us_mask[i]:        continue
        result.append(i)
    return result

def backtest(entry_idx, direction, df, tp_mult=1.0, sl_mult=1.0):
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
        sl = entry - direction*sl_d
        tp = entry + direction*tp_d
        outcome = 2
        for j in range(i+1, min(i+MAX_HOLD+1, N)):
            if direction == -1:
                if h[j] >= sl: outcome = 0; break
                if l[j] <= tp: outcome = 1; break
            else:
                if l[j] <= sl: outcome = 0; break
                if h[j] >= tp: outcome = 1; break
        if outcome == 1: wins += 1
        elif outcome == 0: losses += 1
        else:
            pnl_dir = (entry - c[i+MAX_HOLD])/entry if direction==-1 else (c[i+MAX_HOLD]-entry)/entry
            if pnl_dir > FEE: wins += 1
            else: losses += 1
    n = wins + losses
    if n == 0: return 0.0, 0.0, 0
    wr = wins / n
    ev = wr*tp_mult - (1-wr)*sl_mult - FEE
    return wr, ev, n

def flag(wr, ev, n):
    if n < 30: return f"⚠n={n}"
    if wr >= 0.58 and ev > 0: return "✅✅"
    if wr >= 0.55 and ev > 0: return "✅"
    if wr >= 0.50 and ev > 0: return "⬆"
    return ""

# ══════════════════════════════════════════════════
def main():
    t0 = time.time()

    # 主数据 BTC 15m 180d
    fp = DATA_DIR / "BTCUSDT_15m_180d.json"
    df = load_df(fp)
    if df is None or len(df) < 500:
        print("❌ 数据不可用"); return
    print(f"✅ BTC 15m 180d: {len(df)}根K线")

    adx_arr  = calc_adx(df)
    us_mask  = us_session_filter(df)
    raw_idx  = s4_momentum_reversal(df, n=6, min_pct=0.005)
    direction = -1  # SHORT

    # ══ 任务A1: 三重条件组合矩阵 ══
    print("\n" + "="*70)
    print("任务A1: 三重条件组合矩阵 (n=6, pct=0.005)")
    print("="*70)
    print(f"  {'条件组合':<28} {'n':>5} {'WR':>7} {'EV':>8}  flag")
    print("-"*60)

    combos = [
        ("全量(无过滤)",        False,False,False),
        ("仅ADX≥20",            True, False,False),
        ("仅美盘",              False,False,True),
        ("仅熊市(EMA)",         False,True, False),
        ("ADX+美盘",            True, False,True),
        ("ADX+熊市(EMA)",       True, True, False),
        ("美盘+熊市(EMA)",      False,True, True),
        ("ADX+美盘+熊市(EMA)",  True, True, True),   # 三重
    ]

    for label, ua, ub, uu in combos:
        bear_mask = bear_market_filter(df, "ema")
        idx = apply_filters(raw_idx, df, adx_arr, bear_mask, us_mask, ua, ub, uu)
        wr, ev, n = backtest(idx, direction, df)
        f = flag(wr, ev, n)
        print(f"  {label:<28} {n:>5} {wr:>7.1%} {ev:>8.4f}  {f}")

    # ══ 任务A2: 熊市定义对比 (三重条件下) ══
    print("\n" + "="*70)
    print("任务A2: 熊市定义对比 (ADX≥20 + 美盘 + 不同熊市定义)")
    print("="*70)
    print(f"  {'熊市定义':<30} {'n':>5} {'WR':>7} {'EV':>8}  flag")
    print("-"*60)

    for method, lb in [("ema", 96), ("slope_24", 24), ("slope_48", 48), ("slope_96", 96), ("both", 96)]:
        if method.startswith("slope"):
            bm = bear_market_filter(df, "slope", lookback=int(method.split("_")[1]))
            lbl = f"slope(lookback={method.split('_')[1]})"
        else:
            bm = bear_market_filter(df, method, lookback=lb)
            lbl = method
        idx = apply_filters(raw_idx, df, adx_arr, bm, us_mask, True, True, True)
        wr, ev, n = backtest(idx, direction, df)
        f = flag(wr, ev, n)
        print(f"  {lbl:<30} {n:>5} {wr:>7.1%} {ev:>8.4f}  {f}")

    # ══ 任务A3: TP/SL扫描 (最优三重条件) ══
    print("\n" + "="*70)
    print("任务A3: TP/SL 比率扫描 (ADX≥20 + 美盘 + 熊市EMA)")
    print("="*70)
    bear_mask = bear_market_filter(df, "ema")
    idx_best = apply_filters(raw_idx, df, adx_arr, bear_mask, us_mask, True, True, True)
    print(f"  基础样本量: {len(idx_best)}")
    print(f"  {'TP':>5} {'SL':>5} {'WR':>7} {'EV':>8}  flag")
    print("-"*40)
    for tp in [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]:
        for sl in [0.5, 0.8, 1.0, 1.5]:
            wr, ev, n = backtest(idx_best, direction, df, tp_mult=tp, sl_mult=sl)
            if n < 10: continue
            f = flag(wr, ev, n)
            if ev > 0 or tp/sl >= 1.5:
                print(f"  TP={tp:.1f} SL={sl:.1f}  {wr:>7.1%} {ev:>8.4f}  {f}")

    # ══ 任务A4: 多品种验证 ══
    print("\n" + "="*70)
    print("任务A4: 多品种验证 (n=6, pct=0.005, ADX≥20+美盘+熊市EMA)")
    print("="*70)
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    for sym in symbols:
        fp2 = DATA_DIR / f"{sym}_15m_live.json"
        if not fp2.exists():
            fp2 = DATA_DIR / f"{sym}_15m_180d.json"
        if not fp2.exists():
            print(f"  {sym}: 无数据文件"); continue
        df2 = load_df(fp2)
        if df2 is None or len(df2) < 200:
            print(f"  {sym}: 数据不足"); continue
        adx2 = calc_adx(df2)
        us2  = us_session_filter(df2)
        bm2  = bear_market_filter(df2, "ema")
        ri2  = s4_momentum_reversal(df2, n=6, min_pct=0.005)
        idx2 = apply_filters(ri2, df2, adx2, bm2, us2, True, True, True)
        wr, ev, n = backtest(idx2, direction, df2)
        f = flag(wr, ev, n)
        print(f"  {sym}: n={n:>4}  WR={wr:.1%}  EV={ev:.4f}  {f}")

    print(f"\n[总耗时 {time.time()-t0:.1f}s]")

if __name__ == "__main__":
    main()
