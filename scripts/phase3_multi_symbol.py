"""
Phase 3: 多品种完整回测
- BTC/ETH/SOL/BNB 各自用180d数据验证
- SHORT+LONG组合，同参数
- 输出各品种净值曲线、月度盈亏、最大回撤
- 汇总多品种综合绩效
"""
import json, time
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path("/root/.openclaw/workspace/killer-trading-system/data")
FEE      = 0.0018
MAX_HOLD = 20
CAPITAL  = 150.0
RISK_PCT = 0.02

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
            elif cl in ("o","open"): rmap[c]="open"
            elif cl in ("h","high"): rmap[c]="high"
            elif cl in ("l","low"): rmap[c]="low"
            elif cl in ("c","close"): rmap[c]="close"
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

def s4_short(df, n=6, min_pct=0.002):
    c = df["close"].values
    out = []
    for i in range(n+1, len(c)-1):
        mvs = [c[i-k]-c[i-k-1] for k in range(n)]
        cum = (c[i]-c[i-n])/c[i-n]
        if all(m > 0 for m in mvs) and cum >= min_pct: out.append(i)
    return out

def s4_long(df, n=4, min_pct=0.002):
    c = df["close"].values
    out = []
    for i in range(n+1, len(c)-1):
        mvs = [c[i-k]-c[i-k-1] for k in range(n)]
        cum = (c[i-n]-c[i])/c[i-n]
        if all(m < 0 for m in mvs) and cum >= min_pct: out.append(i)
    return out

def backtest_trades(entry_idx, direction, df, tp_mult=1.0, sl_mult=1.0):
    at = calc_atr(df)
    c = df["close"].values; h = df["high"].values; l = df["low"].values
    ts_v = df["ts"].values if "ts" in df.columns else np.arange(len(c)) * 900000
    N = len(c)
    trades = []
    for i in entry_idx:
        if i+MAX_HOLD >= N: continue
        entry = c[i]; sl_d = at[i]*sl_mult; tp_d = at[i]*tp_mult
        if sl_d < 1e-9: continue
        sl_p = entry - direction*sl_d; tp_p = entry + direction*tp_d
        outcome = "timeout"
        for j in range(i+1, min(i+MAX_HOLD+1, N)):
            if direction == -1:
                if h[j] >= sl_p: outcome = "loss"; break
                if l[j] <= tp_p: outcome = "win"; break
            else:
                if l[j] <= sl_p: outcome = "loss"; break
                if h[j] >= tp_p: outcome = "win"; break
        if outcome == "timeout":
            pnl = (entry-c[i+MAX_HOLD])/entry if direction==-1 else (c[i+MAX_HOLD]-entry)/entry
            outcome = "win" if pnl > FEE else "loss"
        pnl_r = tp_mult if outcome=="win" else -sl_mult
        trades.append({"ts": int(ts_v[i]), "dir": direction, "outcome": outcome, "pnl_r": pnl_r - FEE})
    return trades

def calc_equity(trades, capital=CAPITAL, risk_pct=RISK_PCT):
    cap = capital; peak = capital; max_dd = 0
    monthly = {}
    for t in trades:
        risk_u = cap * risk_pct
        pnl_u  = t["pnl_r"] * risk_u
        cap += pnl_u
        if cap > peak: peak = cap
        dd = (peak - cap) / peak
        if dd > max_dd: max_dd = dd
        month = datetime.fromtimestamp(t["ts"]/1000, tz=timezone.utc).strftime("%Y-%m")
        monthly[month] = monthly.get(month, 0) + pnl_u
    wins = sum(1 for t in trades if t["outcome"]=="win")
    n = len(trades)
    wr = wins/n if n > 0 else 0
    ret = (cap - capital) / capital
    days = (trades[-1]["ts"] - trades[0]["ts"]) / 86400000 if len(trades) > 1 else 180
    monthly_ret = ret / (days/30) if days > 0 else 0
    pf_num = sum(t["pnl_r"] for t in trades if t["pnl_r"]>0)
    pf_den = abs(sum(t["pnl_r"] for t in trades if t["pnl_r"]<0)) or 0.001
    return {
        "cap": cap, "ret": ret, "max_dd": max_dd, "wr": wr, "n": n,
        "monthly_avg": monthly_ret, "monthly": monthly, "pf": pf_num/pf_den
    }

def flag(wr, n, ret):
    if n < 30: return f"⚠n={n}"
    if wr >= 0.58 and ret > 0.3: return "✅✅"
    if wr >= 0.55 and ret > 0.1: return "✅"
    if wr >= 0.50 and ret > 0: return "⬆"
    return ""

def run_symbol(sym, df):
    c_vals = df["close"].values
    adx_arr = calc_adx(df)
    ema200  = ema_vec(c_vals, 200)
    # SHORT
    s_raw = s4_short(df, n=6, min_pct=0.002)
    s_idx = [i for i in s_raw if adx_arr[i] >= 20]
    # LONG
    l_raw = s4_long(df, n=4, min_pct=0.002)
    l_idx = [i for i in l_raw if adx_arr[i] >= 20 and c_vals[i] > ema200[i]]
    # 互斥
    s_set = set(s_idx); l_set = set(l_idx)
    s_clean = [i for i in s_idx if i not in l_set]
    l_clean = [i for i in l_idx if i not in s_set]
    # 回测
    s_trades = backtest_trades(s_clean, -1, df, tp_mult=1.0, sl_mult=1.0)
    l_trades = backtest_trades(l_clean,  1, df, tp_mult=0.8, sl_mult=1.0)
    all_trades = sorted(s_trades + l_trades, key=lambda x: x["ts"])
    if not all_trades:
        return None, None, None
    r = calc_equity(all_trades)
    rs = calc_equity(s_trades) if s_trades else None
    rl = calc_equity(l_trades) if l_trades else None
    return r, rs, rl

def main():
    t0 = time.time()
    symbols_files = {
        "BTCUSDT": [DATA_DIR/"BTCUSDT_15m_180d.json", DATA_DIR/"BTCUSDT_15m_live.json"],
        "ETHUSDT": [DATA_DIR/"ETHUSDT_15m_live.json"],
        "SOLUSDT": [DATA_DIR/"SOLUSDT_15m_live.json"],
        "BNBUSDT": [DATA_DIR/"BNBUSDT_15m_live.json"],
    }

    print("="*70)
    print("Phase3: 多品种综合回测 (SHORT n=6 + LONG n=4+EMA200)")
    print("="*70)
    print(f"  {'品种':<10} {'n':>5} {'WR':>7} {'收益':>8} {'月均':>7} {'回撤':>7} {'PF':>5}  flag")
    print("-"*70)

    all_results = []
    for sym, files in symbols_files.items():
        df = None
        for fp in files:
            if fp.exists():
                df = load_df(fp)
                if df is not None and len(df) >= 300: break
        if df is None:
            print(f"  {sym:<10} 无数据"); continue

        r, rs, rl = run_symbol(sym, df)
        if r is None:
            print(f"  {sym:<10} 无信号"); continue

        f = flag(r["wr"], r["n"], r["ret"])
        print(f"  {sym:<10} {r['n']:>5} {r['wr']:>7.1%} {r['ret']:>+8.1%} {r['monthly_avg']:>+6.1%}/mo {r['max_dd']:>6.1%} {r['pf']:>5.2f}  {f}")
        all_results.append((sym, r))

        # SHORT/LONG分开
        if rs and rs["n"] > 0:
            print(f"    ↳ SHORT: n={rs['n']} WR={rs['wr']:.1%} ret={rs['ret']:+.1%} dd={rs['max_dd']:.1%}")
        if rl and rl["n"] > 0:
            print(f"    ↳ LONG:  n={rl['n']} WR={rl['wr']:.1%} ret={rl['ret']:+.1%} dd={rl['max_dd']:.1%}")

    # 月度汇总（BTC为基准）
    btc_r = next((r for sym,r in all_results if sym=="BTCUSDT"), None)
    if btc_r and btc_r.get("monthly"):
        print(f"\n{'='*70}")
        print(f"BTC 月度收益明细 (150U本金):")
        for month in sorted(btc_r["monthly"].keys()):
            pnl = btc_r["monthly"][month]
            pct = pnl/150*100
            bar = "█" * max(int(abs(pct)/1.5), 0)
            sign = "+" if pnl>=0 else ""
            print(f"  {month}: {sign}{pnl:.2f}U ({sign}{pct:.1f}%)  {bar}")

    # 综合结论
    print(f"\n{'='*70}")
    print("综合结论:")
    ok = [(sym,r) for sym,r in all_results if r["wr"]>=0.55 and r["ret"]>0.1]
    weak = [(sym,r) for sym,r in all_results if r not in [x[1] for x in ok]]
    if ok:
        syms = [s for s,_ in ok]
        print(f"  ✅ 有效品种: {syms}")
    if weak:
        syms = [s for s,_ in weak]
        print(f"  ⚠️  弱效品种: {syms} (单独过滤或参数调整)")

    print(f"\n[总耗时 {time.time()-t0:.1f}s]")

if __name__ == "__main__":
    main()
