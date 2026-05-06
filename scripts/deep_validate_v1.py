"""
BTCUSDT 15m S4_MomReversal SHORT 深度验证
任务1: 180d数据扩大样本（抗过拟合）
任务2: ADX阈值扫描 15~35（稳健性）
任务3: MomReversal参数扫描 n=3~6, min_pct=0.002~0.005
任务4: 时段分析（亚盘/欧盘/美盘）
"""
import json, time
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path("/root/.openclaw/workspace/killer-trading-system/data")
FEE      = 0.0018
MAX_HOLD = 20
TARGET   = {"tp": 1.0, "sl": 1.0}  # 已验证最优


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


def s4_momentum_reversal(df, n=4, min_pct=0.003):
    c = df["close"].values
    shorts = []
    for i in range(n+1, len(c)-1):
        mvs = [c[i-k]-c[i-k-1] for k in range(n)]
        cum = (c[i]-c[i-n])/c[i-n]
        if all(m > 0 for m in mvs) and cum >= min_pct:
            shorts.append(i)
    return shorts


def apply_adx_filter(idx, df, adx_min):
    adx = calc_adx(df)
    return [i for i in idx if i < len(adx) and adx[i] >= adx_min]


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
        # SHORT(direction=-1): sl在entry上方, tp在entry下方
        # LONG (direction=+1): sl在entry下方, tp在entry上方
        sl = entry - direction*sl_d
        tp = entry + direction*tp_d
        outcome = 2
        for j in range(i+1, min(i+MAX_HOLD+1, N)):
            if direction == -1:   # SHORT
                if h[j] >= sl: outcome = 0; break   # 止损：价格上穿sl
                if l[j] <= tp: outcome = 1; break   # 止盈：价格下穿tp
            else:                 # LONG
                if l[j] <= sl: outcome = 0; break   # 止损：价格下穿sl
                if h[j] >= tp: outcome = 1; break   # 止盈：价格上穿tp
        if outcome == 1: wins += 1
        elif outcome == 0: losses += 1
        else:
            pnl = (entry - c[i+MAX_HOLD]) / entry  # SHORT pnl
            if pnl > FEE: wins += 1
            else: losses += 1
    n = wins + losses
    if n == 0: return 0, 0, 0
    wr = wins / n
    ev = wr*tp_mult - (1-wr)*sl_mult - FEE
    return wr, ev, n


def five_fold(idx_all, direction, df):
    n = len(idx_all)
    if n < 50: return None
    seg_size = n // 5
    segs = [idx_all[i*seg_size:(i+1)*seg_size] for i in range(5)]
    results = []
    for s in segs:
        if len(s) < 10: results.append((0,0,0)); continue
        results.append(backtest(s, direction, df))
    return results


def time_segment(idx_all, df):
    """按UTC时间分段：亚盘0-8h / 欧盘8-16h / 美盘16-24h"""
    ts_col = "ts" if "ts" in df.columns else df.columns[0]
    ts_vals = df[ts_col].values
    asia, euro, us = [], [], []
    for i in idx_all:
        if i >= len(ts_vals): continue
        hour = (int(ts_vals[i]) // 3600000) % 24
        if 0 <= hour < 8:   asia.append(i)
        elif 8 <= hour < 16: euro.append(i)
        else:                us.append(i)
    return asia, euro, us


# ═══════════════════════════════════════════════════
def main():
    t0 = time.time()

    # ── 找可用数据文件 ──────────────────────────
    candidates = [
        DATA_DIR / "BTCUSDT_15m_180d.json",
        DATA_DIR / "BTCUSDT_15m_90d.json",
    ]
    df = None
    used_file = None
    for fp in candidates:
        if fp.exists():
            df = load_df(fp)
            if df is not None and len(df) > 500:
                used_file = fp
                break

    if df is None:
        print("❌ 无可用数据文件")
        return

    print(f"✅ 数据: {used_file.name}  共{len(df)}根K线")
    ts_col = "ts" if "ts" in df.columns else df.columns[0]
    if "ts" in df.columns:
        from datetime import datetime, timezone
        t_start = datetime.fromtimestamp(df["ts"].iloc[0]/1000, tz=timezone.utc).strftime("%Y-%m-%d")
        t_end   = datetime.fromtimestamp(df["ts"].iloc[-1]/1000, tz=timezone.utc).strftime("%Y-%m-%d")
        print(f"   范围: {t_start} → {t_end}")

    direction = -1  # SHORT
    BASE_N    = 4
    BASE_PCT  = 0.003

    # ═══ 任务1：ADX阈值扫描 15~35 step=2 ════════
    print("\n" + "="*80)
    print("任务1: ADX阈值扫描 (S4_MomReversal SHORT, TP1/SL1)")
    print("="*80)
    print(f"{'ADX≥':>6} {'n':>5} {'WR':>7} {'EV':>8}  5-fold(WR)  min_fold  flag")
    print("-"*70)

    raw_idx = s4_momentum_reversal(df, n=BASE_N, min_pct=BASE_PCT)
    adx_results = []
    for adx_th in range(0, 38, 2):
        idx = apply_adx_filter(raw_idx, df, adx_th) if adx_th > 0 else raw_idx
        if len(idx) < 20: continue
        wr, ev, n = backtest(idx, direction, df)
        fold5 = five_fold(idx, direction, df)
        if fold5:
            fold_wrs = [r[0] for r in fold5 if r[2] > 0]
            min_wr   = min(fold_wrs) if fold_wrs else 0
            fold_s   = " ".join([f"{r[0]:.0%}" for r in fold5])
        else:
            min_wr = 0; fold_s = "N/A"
        flag = "✅✅" if wr>=0.58 and min_wr>=0.50 else ("✅" if wr>=0.55 and min_wr>=0.45 else ("⬆" if wr>=0.50 and ev>0 else ("+" if ev>0 else "")))
        print(f"  {adx_th:>4}  {n:>5} {wr:>7.1%} {ev:>8.4f}  [{fold_s}]  min={min_wr:.0%}  {flag}")
        adx_results.append((adx_th, n, wr, ev, min_wr, fold_s))

    # 找最优ADX区间
    best_adx = sorted([r for r in adx_results if r[3]>0 and r[2]>=0.50], key=lambda x: -x[2])
    if best_adx:
        print(f"\n  ★ 最优ADX: {best_adx[0][0]}  WR={best_adx[0][2]:.1%}  EV={best_adx[0][3]:.4f}")

    # ═══ 任务2：MomReversal参数扫描 ══════════════
    print("\n" + "="*80)
    print("任务2: S4_MomReversal 参数扫描 (ADX≥20, TP1/SL1)")
    print("="*80)
    print(f"{'n_bars':>7} {'min_pct':>8} {'raw_n':>6} {'filt_n':>7} {'WR':>7} {'EV':>8}  flag")
    print("-"*65)

    param_results = []
    for nb in [3, 4, 5, 6]:
        for mp in [0.002, 0.003, 0.004, 0.005]:
            idx_r = s4_momentum_reversal(df, n=nb, min_pct=mp)
            idx_f = apply_adx_filter(idx_r, df, adx_min=20)
            if len(idx_f) < 20: continue
            wr, ev, n = backtest(idx_f, direction, df)
            flag = "✅✅" if wr>=0.58 and ev>0.1 else ("✅" if wr>=0.55 and ev>0 else ("⬆" if wr>=0.50 and ev>0 else ("+" if ev>0 else "")))
            print(f"  n={nb}  pct={mp:.3f}  raw={len(idx_r):>5}  filt={n:>5}  {wr:>7.1%}  {ev:>8.4f}  {flag}")
            param_results.append((nb, mp, n, wr, ev))

    best_params = sorted([r for r in param_results if r[4]>0 and r[3]>=0.50], key=lambda x: -x[3])
    if best_params:
        nb, mp, n, wr, ev = best_params[0]
        print(f"\n  ★ 最优参数: n={nb} pct={mp:.3f}  WR={wr:.1%}  EV={ev:.4f}  n={n}")

    # ═══ 任务3：时段分析 ═════════════════════════
    print("\n" + "="*80)
    print("任务3: 时段分析 (ADX≥20, 默认参数, TP1/SL1)")
    print("="*80)
    idx_base = s4_momentum_reversal(df, n=BASE_N, min_pct=BASE_PCT)
    idx_filt = apply_adx_filter(idx_base, df, adx_min=20)
    asia, euro, us = time_segment(idx_filt, df)
    for label, seg in [("亚盘 0-8h UTC", asia), ("欧盘 8-16h UTC", euro), ("美盘16-24h UTC", us)]:
        if len(seg) < 5:
            print(f"  {label}: n<5 跳过")
            continue
        wr, ev, n = backtest(seg, direction, df)
        flag = "✅" if wr>=0.55 else ("⬆" if wr>=0.50 else "")
        print(f"  {label}: n={n:>4}  WR={wr:.1%}  EV={ev:.4f}  {flag}")

    # ═══ 任务4：走势期分析（牛/熊/震荡）═══════
    print("\n" + "="*80)
    print("任务4: 市场分段分析（按价格走势分3等段）")
    print("="*80)
    c = df["close"].values
    n_total = len(c)
    seg_size = n_total // 3
    segs_market = [
        ("早段", 0, seg_size),
        ("中段", seg_size, 2*seg_size),
        ("近段", 2*seg_size, n_total),
    ]
    idx_full = s4_momentum_reversal(df, n=BASE_N, min_pct=BASE_PCT)
    idx_full = apply_adx_filter(idx_full, df, adx_min=20)
    for label, start, end in segs_market:
        seg = [i for i in idx_full if start <= i < end]
        if len(seg) < 5:
            print(f"  {label}: n<5")
            continue
        wr, ev, n = backtest(seg, direction, df)
        price_chg = (c[end-1]-c[start])/c[start]*100
        flag = "✅" if wr>=0.55 else ("⬆" if wr>=0.50 else "")
        print(f"  {label}(idx {start}-{end})  价格变化:{price_chg:+.1f}%  n={n}  WR={wr:.1%}  EV={ev:.4f}  {flag}")

    print(f"\n[总耗时 {time.time()-t0:.1f}s]")
    print("\n" + "="*80)
    print("综合判断:")

    # 汇总
    all_ok = [r for r in adx_results if r[2]>=0.58 and r[4]>=0.50]
    if all_ok:
        print(f"  ✅✅ ADX扫描发现WR≥58%+min_fold≥50%: {[r[0] for r in all_ok]}")
    elif [r for r in adx_results if r[2]>=0.55]:
        print(f"  ✅  ADX扫描发现WR≥55%: {[(r[0],f'{r[2]:.1%}') for r in adx_results if r[2]>=0.55]}")
    else:
        best = max(adx_results, key=lambda x: x[2]) if adx_results else None
        if best:
            print(f"  ⚠️  最高WR={best[2]:.1%}(ADX≥{best[0]})，未达58%目标")

    param_ok = [r for r in param_results if r[3]>=0.58 and r[4]>0]
    if param_ok:
        nb, mp, n, wr, ev = param_ok[0]
        print(f"  ✅✅ 参数扫描发现WR≥58%: n={nb} pct={mp:.3f} WR={wr:.1%}")


if __name__ == "__main__":
    main()
