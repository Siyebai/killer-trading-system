"""
Phase 1: 双策略信号冲突检测 + 互斥逻辑验证
SHORT: n=6, pct=0.002, ADX>=20, TP1/SL1
LONG:  n=4, pct=0.002, ADX>=20, close>EMA200, TP0.8/SL1.0

任务:
1. 统计信号冲突率（同一根K线同时触发SHORT和LONG）
2. 验证互斥后各策略独立胜率
3. 组合策略：回测净值曲线 + 最大回撤 + 月度盈亏
4. 5折交叉验证 SHORT策略稳健性
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

def backtest_detailed(entry_idx, direction, df, tp_mult=1.0, sl_mult=1.0, tp=None, sl=None):
    if tp is not None: tp_mult = tp
    if sl is not None: sl_mult = sl
    """返回每笔交易详情"""
    at = calc_atr(df)
    c = df["close"].values; h = df["high"].values; l = df["low"].values
    ts_vals = df["ts"].values if "ts" in df.columns else None
    N = len(c)
    trades = []
    for i in entry_idx:
        if i+MAX_HOLD >= N: continue
        entry = c[i]; sl_d = at[i]*sl_mult; tp_d = at[i]*tp_mult
        if sl_d < 1e-9: continue
        sl_p = entry - direction*sl_d
        tp_p = entry + direction*tp_d
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
        pnl_r = tp_mult if outcome == "win" else -sl_mult
        ts_val = int(ts_vals[i]) if ts_vals is not None else i * 900000
        trades.append({
            "idx": i, "ts": ts_val, "direction": direction,
            "outcome": outcome, "pnl_r": pnl_r - FEE
        })
    return trades

def equity_curve(trades, capital=150.0, risk_pct=0.02):
    """模拟净值曲线"""
    eq = [capital]; cap = capital
    monthly_pnl = {}
    for t in trades:
        risk = cap * risk_pct
        pnl = t["pnl_r"] * risk
        cap += pnl; eq.append(cap)
        month = datetime.fromtimestamp(t["ts"]/1000, tz=timezone.utc).strftime("%Y-%m")
        monthly_pnl[month] = monthly_pnl.get(month, 0) + pnl
    peak = eq[0]; max_dd = 0
    for v in eq:
        if v > peak: peak = v
        dd = (peak - v) / peak
        if dd > max_dd: max_dd = dd
    total_ret = (cap - capital) / capital
    wins = sum(1 for t in trades if t["outcome"]=="win")
    n = len(trades)
    wr = wins/n if n > 0 else 0
    return cap, total_ret, max_dd, wr, n, monthly_pnl, eq

def five_fold(idx_all, direction, df, tp=1.0, sl=1.0):
    n = len(idx_all)
    if n < 50: return None
    seg = n // 5
    results = []
    for k in range(5):
        s = idx_all[k*seg:(k+1)*seg]
        if len(s) < 10: results.append((0,0,0)); continue
        trades = backtest_detailed(s, direction, df, tp, sl)
        wins = sum(1 for t in trades if t["outcome"]=="win")
        nn = len(trades)
        wr = wins/nn if nn > 0 else 0
        ev = wr*tp - (1-wr)*sl - FEE
        results.append((wr, ev, nn))
    return results

def flag(wr, ev, n):
    if n < 30: return f"⚠n={n}"
    if wr >= 0.58 and ev > 0: return "✅✅"
    if wr >= 0.55 and ev > 0: return "✅"
    if wr >= 0.50 and ev > 0: return "⬆"
    return ""

def main():
    t0 = time.time()
    fp = DATA_DIR / "BTCUSDT_15m_180d.json"
    df = load_df(fp)
    print(f"✅ BTC 15m 180d: {len(df)}根K线")

    c_vals = df["close"].values
    ema200 = ema_vec(c_vals, 200)
    adx_arr = calc_adx(df)

    # 生成信号
    short_raw = s4_short(df, n=6, min_pct=0.002)
    long_raw  = s4_long(df,  n=4, min_pct=0.002)

    # 过滤器
    short_idx = [i for i in short_raw if adx_arr[i] >= 20]
    long_idx  = [i for i in long_raw  if adx_arr[i] >= 20 and c_vals[i] > ema200[i]]

    # ══ 1. 冲突检测 ══
    print("\n" + "="*65)
    print("Phase1: 信号冲突检测")
    print("="*65)
    short_set = set(short_idx)
    long_set  = set(long_idx)
    conflict  = short_set & long_set
    print(f"  SHORT信号: {len(short_idx)} 笔")
    print(f"  LONG 信号: {len(long_idx)} 笔")
    print(f"  冲突信号:  {len(conflict)} 笔 ({len(conflict)/(len(short_idx)+len(long_idx))*100:.1f}%)")

    # 互斥策略（冲突时跳过）
    short_clean = [i for i in short_idx if i not in long_set]
    long_clean  = [i for i in long_idx  if i not in short_set]
    print(f"  互斥后SHORT: {len(short_clean)} 笔 | LONG: {len(long_clean)} 笔")

    # ══ 2. SHORT 5折验证 ══
    print("\n" + "="*65)
    print("Phase2: SHORT策略 5折交叉验证 (n=6, pct=0.002, ADX≥20, TP1/SL1)")
    print("="*65)
    folds = five_fold(short_idx, -1, df, tp=1.0, sl=1.0)
    if folds:
        fold_wrs = [f[0] for f in folds if f[2]>0]
        fold_str = " ".join([f"{f[0]:.0%}" for f in folds])
        min_wr = min(fold_wrs) if fold_wrs else 0
        total_wr = sum(1 for t in backtest_detailed(short_idx,-1,df) if t["outcome"]=="win") / max(len(short_idx),1)
        trades_all = backtest_detailed(short_idx, -1, df)
        wr = sum(1 for t in trades_all if t["outcome"]=="win") / max(len(trades_all),1)
        ev = wr*1.0 - (1-wr)*1.0 - FEE
        print(f"  整体: n={len(trades_all)} WR={wr:.1%} EV={ev:.4f}")
        print(f"  5折: [{fold_str}]  min={min_wr:.0%}  {'✅稳健' if min_wr>=0.48 else '⚠不稳'}")

    # ══ 3. 组合净值曲线 ══
    print("\n" + "="*65)
    print("Phase3: 组合策略净值回测 (SHORT+LONG, 150U, 2%风险/笔)")
    print("="*65)

    # 合并排序
    short_trades = backtest_detailed(short_clean, -1, df, tp=1.0, sl=1.0)
    long_trades  = backtest_detailed(long_clean,   1, df, tp=0.8, sl=1.0)
    all_trades   = sorted(short_trades + long_trades, key=lambda x: x["ts"])

    cap, ret, dd, wr, n, monthly, eq = equity_curve(all_trades, capital=150.0, risk_pct=0.02)
    print(f"  初始资金: 150U")
    print(f"  终值:     {cap:.2f}U  ({ret:+.1%})")
    print(f"  总笔数:   {n} 笔 ({n/6:.1f}笔/月)")
    print(f"  总胜率:   {wr:.1%}")
    print(f"  最大回撤: {dd:.1%}")
    print(f"  盈利因子: {sum(t['pnl_r'] for t in all_trades if t['pnl_r']>0) / max(abs(sum(t['pnl_r'] for t in all_trades if t['pnl_r']<0)),0.001):.2f}")

    print(f"\n  月度盈亏:")
    for month in sorted(monthly.keys()):
        pnl = monthly[month]
        pct = pnl / 150 * 100
        bar = "█" * int(abs(pct)/2) if abs(pct) >= 1 else ""
        sign = "+" if pnl >= 0 else ""
        print(f"    {month}: {sign}{pnl:.2f}U ({sign}{pct:.1f}%)  {bar}")

    # ══ 4. 单独SHORT/LONG净值 ══
    print("\n" + "="*65)
    print("Phase4: 分策略独立净值")
    print("="*65)
    for label, trades_s, tp, sl in [
        ("SHORT(n=6,TP1/SL1)", short_trades, 1.0, 1.0),
        ("LONG(n=4,EMA200,TP0.8/SL1)", long_trades, 0.8, 1.0)
    ]:
        cap2, ret2, dd2, wr2, n2, _, _ = equity_curve(trades_s, 150.0, 0.02)
        f = flag(wr2, wr2*tp-(1-wr2)*sl-FEE, n2)
        print(f"  {label}")
        print(f"    n={n2} WR={wr2:.1%} 终值={cap2:.2f}U 回撤={dd2:.1%}  {f}")

    print(f"\n[总耗时 {time.time()-t0:.1f}s]")

if __name__ == "__main__":
    main()
