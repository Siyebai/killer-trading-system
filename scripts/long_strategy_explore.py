"""
任务B: 多头策略探索
思路: 镜像S4_MomReversal — 连续n根下跌后做多（超卖反弹）
+ 补充策略: ATR压缩突破 LONG / EMA趋势跟随 LONG

验证维度:
- B1: MomReversal LONG 基础扫描 (n=3~7, pct=0.002~0.008)
- B2: ATR压缩突破 LONG
- B3: EMA金叉趋势跟随 LONG
- B4: 时段 × 市场环境分析
- B5: 多品种对比
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

def calc_rsi(df, n=14):
    c = df["close"].values
    delta = np.diff(c, prepend=c[0])
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    avg_up = np.zeros(len(c)); avg_dn = np.zeros(len(c))
    avg_up[:n] = up[:n].mean(); avg_dn[:n] = dn[:n].mean()
    for i in range(n, len(c)):
        avg_up[i] = avg_up[i-1]*(n-1)/n + up[i]/n
        avg_dn[i] = avg_dn[i-1]*(n-1)/n + dn[i]/n
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(avg_dn>0, avg_up/avg_dn, 100)
    return 100 - 100/(1+rs)

# ── 策略定义 ─────────────────────────────────────

def s4_long(df, n=4, min_pct=0.003):
    """连续n根下跌后做多"""
    c = df["close"].values
    longs = []
    for i in range(n+1, len(c)-1):
        mvs = [c[i-k]-c[i-k-1] for k in range(n)]
        cum = (c[i-n]-c[i])/c[i-n]  # 跌幅
        if all(m < 0 for m in mvs) and cum >= min_pct:
            longs.append(i)
    return longs

def atr_compression_long(df, compress_n=20, breakout_mult=0.5):
    """
    ATR压缩突破 LONG:
    ATR收缩到近20根最低点 + 价格突破压缩区间上沿
    """
    c = df["close"].values
    h = df["high"].values
    atr = calc_atr(df)
    longs = []
    for i in range(compress_n+2, len(c)-1):
        atr_window = atr[i-compress_n:i]
        atr_min = atr_window.min()
        atr_max = atr_window.max()
        compressed = atr[i] <= atr_min * 1.1  # 当前ATR接近最低
        high_20 = h[i-compress_n:i].max()
        breakout = c[i] > high_20 * (1 + 0.0003)  # 突破近期高点
        if compressed and breakout:
            longs.append(i)
    return longs

def ema_golden_cross_long(df, fast=20, slow=50, adx_min=20):
    """
    EMA金叉趋势跟随 LONG:
    EMA20上穿EMA50 + ADX趋势确认
    """
    c = df["close"].values
    ema_f = ema_vec(c, fast)
    ema_s = ema_vec(c, slow)
    adx = calc_adx(df)
    longs = []
    for i in range(slow+2, len(c)-1):
        prev_above = ema_f[i-1] > ema_s[i-1]
        was_below  = ema_f[i-2] <= ema_s[i-2]
        if was_below and prev_above and adx[i] >= adx_min:
            longs.append(i)
    return longs

def ema_pullback_long(df, fast=20, slow=50, adx_min=20):
    """
    EMA趋势中的回调做多:
    处于上升趋势(EMA20>EMA50) + 价格回踩EMA20 + 反弹
    """
    c = df["close"].values
    ema_f = ema_vec(c, fast)
    ema_s = ema_vec(c, slow)
    adx = calc_adx(df)
    longs = []
    for i in range(slow+2, len(c)-1):
        trend_up = ema_f[i] > ema_s[i] and adx[i] >= adx_min
        touched_ema = abs(c[i] - ema_f[i]) / ema_f[i] < 0.003  # 距离EMA20在0.3%以内
        prev_below = c[i-1] <= ema_f[i-1] * 1.001
        if trend_up and touched_ema and prev_below:
            longs.append(i)
    return longs

def rsi_oversold_long(df, rsi_th=30, adx_min=15):
    """RSI超卖反弹 + 价格回升"""
    c = df["close"].values
    rsi = calc_rsi(df)
    adx = calc_adx(df)
    longs = []
    for i in range(20, len(c)-1):
        if rsi[i-1] <= rsi_th and rsi[i] > rsi[i-1] and adx[i] >= adx_min:
            longs.append(i)
    return longs

# ── 过滤器 ──────────────────────────────────────

def time_segment_mask(df):
    ts = df["ts"].values
    asia = np.zeros(len(ts), bool)
    euro = np.zeros(len(ts), bool)
    us   = np.zeros(len(ts), bool)
    for i in range(len(ts)):
        h = (int(ts[i]) // 3600000) % 24
        if 0 <= h < 8:    asia[i] = True
        elif 8 <= h < 16:  euro[i] = True
        else:              us[i]   = True
    return asia, euro, us

def bull_market_filter(df, lookback=96):
    """牛市: EMA20>EMA50 且 近lookback根累涨>3%"""
    c = df["close"].values
    ema20 = ema_vec(c, 20)
    ema50 = ema_vec(c, 50)
    bull = np.zeros(len(c), bool)
    for i in range(max(lookback, 50), len(c)):
        bull[i] = (ema20[i] > ema50[i]) and ((c[i]-c[i-lookback])/c[i-lookback] > 0.03)
    return bull

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
            pnl_dir = (c[i+MAX_HOLD]-entry)/entry if direction==1 else (entry-c[i+MAX_HOLD])/entry
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
    fp = DATA_DIR / "BTCUSDT_15m_180d.json"
    df = load_df(fp)
    if df is None or len(df) < 500:
        print("❌ 数据不可用"); return
    print(f"✅ BTC 15m 180d: {len(df)}根K线")
    direction = 1  # LONG

    adx_arr = calc_adx(df)
    asia_m, euro_m, us_m = time_segment_mask(df)
    bull_m = bull_market_filter(df)

    # ══ B1: MomReversal LONG 参数扫描 ══
    print("\n" + "="*70)
    print("任务B1: S4_MomReversal LONG 参数扫描 (无过滤 + ADX≥20)")
    print("="*70)
    print(f"  {'n':>3} {'pct':>6} {'raw':>6} {'adx_n':>6} {'WR_raw':>8} {'WR_adx':>8} {'EV_adx':>8}  flag")
    print("-"*70)
    best_b1 = []
    for nb in [3, 4, 5, 6, 7]:
        for mp in [0.002, 0.003, 0.005, 0.008]:
            idx_r = s4_long(df, n=nb, min_pct=mp)
            idx_a = [i for i in idx_r if i < len(adx_arr) and adx_arr[i] >= 20]
            if len(idx_r) < 20: continue
            wr_r, _, nr = backtest(idx_r, direction, df)
            wr_a, ev_a, na = backtest(idx_a, direction, df)
            f = flag(wr_a, ev_a, na)
            print(f"  n={nb} pct={mp:.3f} raw={nr:>4} adx={na:>4}  {wr_r:>7.1%}  {wr_a:>7.1%}  {ev_a:>8.4f}  {f}")
            best_b1.append((nb, mp, na, wr_a, ev_a))
    top_b1 = sorted([r for r in best_b1 if r[3]>=0.50 and r[4]>0], key=lambda x: -x[3])
    if top_b1:
        nb, mp, n, wr, ev = top_b1[0]
        print(f"\n  ★ 最优: n={nb} pct={mp:.3f} WR={wr:.1%} EV={ev:.4f} n={n}")

    # ══ B2: ATR压缩突破 LONG ══
    print("\n" + "="*70)
    print("任务B2: ATR压缩突破 LONG")
    print("="*70)
    for cn in [10, 15, 20, 30]:
        idx_atr = atr_compression_long(df, compress_n=cn)
        wr, ev, n = backtest(idx_atr, direction, df)
        f = flag(wr, ev, n)
        print(f"  compress_n={cn:<3} n={n:>4}  WR={wr:.1%}  EV={ev:.4f}  {f}")
    # 加ADX过滤
    print("  --- ADX≥20 过滤 ---")
    for cn in [10, 15, 20]:
        idx_atr = atr_compression_long(df, compress_n=cn)
        idx_f = [i for i in idx_atr if i < len(adx_arr) and adx_arr[i] >= 20]
        wr, ev, n = backtest(idx_f, direction, df)
        f = flag(wr, ev, n)
        print(f"  compress_n={cn:<3}+ADX n={n:>4}  WR={wr:.1%}  EV={ev:.4f}  {f}")

    # ══ B3: EMA策略 ══
    print("\n" + "="*70)
    print("任务B3: EMA趋势策略 LONG")
    print("="*70)
    idx_gc = ema_golden_cross_long(df, fast=20, slow=50, adx_min=20)
    wr, ev, n = backtest(idx_gc, direction, df)
    print(f"  EMA金叉(20/50)+ADX≥20: n={n}  WR={wr:.1%}  EV={ev:.4f}  {flag(wr,ev,n)}")

    idx_gc2 = ema_golden_cross_long(df, fast=10, slow=30, adx_min=20)
    wr, ev, n = backtest(idx_gc2, direction, df)
    print(f"  EMA金叉(10/30)+ADX≥20: n={n}  WR={wr:.1%}  EV={ev:.4f}  {flag(wr,ev,n)}")

    idx_pb = ema_pullback_long(df, fast=20, slow=50, adx_min=20)
    wr, ev, n = backtest(idx_pb, direction, df)
    print(f"  EMA回踩(20/50)+ADX≥20: n={n}  WR={wr:.1%}  EV={ev:.4f}  {flag(wr,ev,n)}")

    # ══ B4: RSI超卖反弹 ══
    print("\n" + "="*70)
    print("任务B4: RSI超卖反弹 LONG")
    print("="*70)
    for rsi_th in [25, 30, 35]:
        idx_rsi = rsi_oversold_long(df, rsi_th=rsi_th, adx_min=15)
        wr, ev, n = backtest(idx_rsi, direction, df)
        f = flag(wr, ev, n)
        print(f"  RSI≤{rsi_th}+反弹: n={n:>4}  WR={wr:.1%}  EV={ev:.4f}  {f}")
        # + 牛市过滤
        idx_bull = [i for i in idx_rsi if i < len(bull_m) and bull_m[i]]
        wr2, ev2, n2 = backtest(idx_bull, direction, df)
        f2 = flag(wr2, ev2, n2)
        print(f"  RSI≤{rsi_th}+反弹+牛市: n={n2:>4}  WR={wr2:.1%}  EV={ev2:.4f}  {f2}")

    # ══ B5: 最佳LONG策略 × 时段分析 ══
    # 选B1最优参数做时段分析
    print("\n" + "="*70)
    print("任务B5: 最优MomReversal LONG × 时段分析")
    print("="*70)
    best_n = top_b1[0][0] if top_b1 else 5
    best_p = top_b1[0][1] if top_b1 else 0.003
    idx_best = s4_long(df, n=best_n, min_pct=best_p)
    idx_best = [i for i in idx_best if i < len(adx_arr) and adx_arr[i] >= 20]
    print(f"  参数: n={best_n}, pct={best_p}, ADX≥20, 总n={len(idx_best)}")
    for label, mask in [("亚盘(0-8h)", asia_m), ("欧盘(8-16h)", euro_m), ("美盘(16-24h)", us_m)]:
        seg = [i for i in idx_best if i < len(mask) and mask[i]]
        wr, ev, n = backtest(seg, direction, df)
        f = flag(wr, ev, n)
        print(f"  {label}: n={n:>4}  WR={wr:.1%}  EV={ev:.4f}  {f}")
    # 牛市分段
    for label, bm in [("无市场过滤", None), ("牛市", bull_m)]:
        seg = [i for i in idx_best if bm is None or (i < len(bm) and bm[i])]
        wr, ev, n = backtest(seg, direction, df)
        f = flag(wr, ev, n)
        print(f"  {label}: n={n:>4}  WR={wr:.1%}  EV={ev:.4f}  {f}")

    # ══ B6: 多品种验证最佳策略 ══
    print("\n" + "="*70)
    print("任务B6: 多品种验证 (最优MomReversal LONG)")
    print("="*70)
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    for sym in symbols:
        fp2 = DATA_DIR / f"{sym}_15m_live.json"
        if not fp2.exists():
            fp2 = DATA_DIR / f"{sym}_15m_180d.json"
        if not fp2.exists():
            print(f"  {sym}: 无数据"); continue
        df2 = load_df(fp2)
        if df2 is None or len(df2) < 200:
            print(f"  {sym}: 数据不足"); continue
        adx2 = calc_adx(df2)
        ri2  = s4_long(df2, n=best_n, min_pct=best_p)
        idx2 = [i for i in ri2 if i < len(adx2) and adx2[i] >= 20]
        wr, ev, n = backtest(idx2, direction, df2)
        f = flag(wr, ev, n)
        print(f"  {sym}: n={n:>4}  WR={wr:.1%}  EV={ev:.4f}  {f}")

    print(f"\n[总耗时 {time.time()-t0:.1f}s]")

if __name__ == "__main__":
    main()
