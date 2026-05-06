"""
短线策略扫描器 v1.0
扫描 3m/5m/10m/15m × BTC/ETH/SOL/BNB × 多策略
目标胜率 >=58%，EV >0（扣手续费 0.18% 双边）

策略库：
  S1: 市场结构突破（HH+HL / LL+LH）
  S2: EMA多头排列+回调入场
  S3: ATR压缩+突破
  S4: 价格动量（N根连续方向后反转）
  S5: 支撑/阻力位反弹
"""
import json, os, sys
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path("/root/.openclaw/workspace/killer-trading-system/data")
FEE = 0.0018  # 双边手续费 0.18%

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
TIMEFRAMES = ["3m", "5m", "10m", "15m"]


# ─── 数据加载 ───────────────────────────────────────────────
def load_data(symbol, tf):
    for fname in [f"{symbol}_{tf}_90d.json", f"{symbol}_{tf}.json", f"{symbol}_{tf}_live.json"]:
        p = DATA_DIR / fname
        if p.exists():
            raw = json.load(open(p))
            if isinstance(raw, list):
                data = raw
            elif isinstance(raw, dict) and "data" in raw:
                data = raw["data"]
            else:
                continue
            df = pd.DataFrame(data)
            # 统一列名：支持数组格式和字典格式
            if isinstance(data[0], (list, tuple)):
                # 数组格式
                base_cols = ["ts","open","high","low","close","volume"]
                extra = [f"c{i}" for i in range(6, len(df.columns))]
                df.columns = base_cols[:len(df.columns)] + extra
            else:
                # 字典格式，映射常见缩写
                col_map = {}
                for col in df.columns:
                    cl = col.lower()
                    if cl in ("ts","time","timestamp","open_time"): col_map[col] = "ts"
                    elif cl in ("o","open"): col_map[col] = "open"
                    elif cl in ("h","high"): col_map[col] = "high"
                    elif cl in ("l","low"):  col_map[col] = "low"
                    elif cl in ("c","close"): col_map[col] = "close"
                    elif cl in ("v","volume","vol"): col_map[col] = "volume"
                df = df.rename(columns=col_map)
                # 若无open列，用close代替
                if "open" not in df.columns: df["open"] = df["close"]
                if "volume" not in df.columns: df["volume"] = 0
            for c in ["open","high","low","close","volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.dropna(subset=["open","high","low","close"]).reset_index(drop=True)
            return df
    return None


# ─── 指标 ───────────────────────────────────────────────────
def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()
def rsi(s, n=14):
    d = s.diff(); g = d.clip(lower=0); ls = (-d).clip(lower=0)
    return 100 - 100/(1 + g.rolling(n).mean()/ls.rolling(n).mean().replace(0, 1e-9))


# ─── 回测核心 ───────────────────────────────────────────────
def backtest(signals, df, sl_atr_mult=1.5, tp_atr_mult=2.5, max_hold=20):
    """
    signals: list of (idx, direction) direction=1 long / -1 short
    返回: trades list, win_rate, ev
    """
    at = atr(df, 14).values
    c  = df["close"].values
    trades = []
    for idx, direction in signals:
        if idx + max_hold >= len(c): continue
        entry = c[idx]
        sl_dist = at[idx] * sl_atr_mult
        tp_dist = at[idx] * tp_atr_mult
        if sl_dist < 1e-9: continue
        sl = entry - direction * sl_dist
        tp = entry + direction * tp_dist
        result = "max_hold"
        for i in range(1, max_hold+1):
            bar_h = df["high"].values[idx+i]
            bar_l = df["low"].values[idx+i]
            if direction == 1:
                if bar_l <= sl:  result="loss"; break
                if bar_h >= tp:  result="win";  break
            else:
                if bar_h >= sl:  result="loss"; break
                if bar_l <= tp:  result="win";  break
        if result == "win":
            pnl = tp_atr_mult - FEE
            trades.append(1)
        elif result == "loss":
            pnl = -sl_atr_mult - FEE
            trades.append(0)
        else:
            pnl = (c[idx+max_hold] - entry) * direction / entry - FEE
            trades.append(1 if pnl > 0 else 0)
    if not trades: return trades, 0, 0
    wr = sum(trades)/len(trades)
    ev = wr * tp_atr_mult - (1-wr) * sl_atr_mult - FEE
    return trades, wr, ev


# ─── 策略 S1: 市场结构突破 ──────────────────────────────────
def strategy_s1_structure_break(df, lookback=10):
    """
    多头：最近 lookback 根创新高（突破前高）→ 做多
    空头：最近 lookback 根创新低（突破前低）→ 做空
    """
    signals = []
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    for i in range(lookback+1, len(df)-1):
        prev_h = h[i-lookback:i].max()
        prev_l = l[i-lookback:i].min()
        # 突破前高做多
        if c[i] > prev_h and c[i-1] <= prev_h:
            signals.append((i, 1))
        # 跌破前低做空
        elif c[i] < prev_l and c[i-1] >= prev_l:
            signals.append((i, -1))
    return signals


# ─── 策略 S2: EMA回调入场 ──────────────────────────────────
def strategy_s2_ema_pullback(df):
    """
    EMA9 > EMA21 > EMA55 多头排列，价格回调到EMA21做多
    反之做空
    """
    signals = []
    e9  = ema(df["close"], 9).values
    e21 = ema(df["close"], 21).values
    e55 = ema(df["close"], 55).values
    c   = df["close"].values
    for i in range(60, len(df)-1):
        # 多头排列 + 回调触 EMA21
        if e9[i] > e21[i] > e55[i]:
            if c[i-1] > e21[i-1] and c[i] <= e21[i]:  # 下穿EMA21
                signals.append((i, 1))
        # 空头排列
        elif e9[i] < e21[i] < e55[i]:
            if c[i-1] < e21[i-1] and c[i] >= e21[i]:  # 上穿EMA21
                signals.append((i, -1))
    return signals


# ─── 策略 S3: ATR压缩突破 ──────────────────────────────────
def strategy_s3_atr_squeeze(df, compress_period=20, break_period=5):
    """
    ATR压缩（近期ATR < 历史中位ATR * 0.6）后价格突破
    """
    signals = []
    at = atr(df, 14).values
    c  = df["close"].values
    h  = df["high"].values
    l  = df["low"].values
    for i in range(compress_period+break_period, len(df)-1):
        hist_atr = np.median(at[i-compress_period:i])
        curr_atr = at[i]
        if curr_atr > hist_atr * 0.6: continue  # 未压缩
        # 突破近期高点做多
        recent_h = h[i-break_period:i].max()
        recent_l = l[i-break_period:i].min()
        if c[i] > recent_h and c[i-1] <= recent_h:
            signals.append((i, 1))
        elif c[i] < recent_l and c[i-1] >= recent_l:
            signals.append((i, -1))
    return signals


# ─── 策略 S4: 动量反转 ────────────────────────────────────
def strategy_s4_momentum_reversal(df, n=4, min_move_pct=0.003):
    """
    连续 n 根同向K线（累计涨幅>=min_move_pct）后反转
    """
    signals = []
    c = df["close"].values
    for i in range(n+1, len(df)-1):
        moves = [c[i-k] - c[i-k-1] for k in range(n)]
        cum = (c[i] - c[i-n]) / c[i-n]
        if all(m > 0 for m in moves) and cum >= min_move_pct:
            signals.append((i, -1))  # 做空反转
        elif all(m < 0 for m in moves) and abs(cum) >= min_move_pct:
            signals.append((i, 1))   # 做多反转
    return signals


# ─── 策略 S5: 支撑阻力反弹 ────────────────────────────────
def strategy_s5_sr_bounce(df, lookback=50, tolerance=0.002):
    """
    识别近期 pivot high/low → 价格回测后反弹入场
    """
    signals = []
    c = df["close"].values
    h = df["high"].values
    l = df["low"].values
    for i in range(lookback+2, len(df)-1):
        # 找支撑（近期低点）
        window_l = l[i-lookback:i-2]
        sr_support = np.percentile(window_l, 15)
        sr_resist  = np.percentile(h[i-lookback:i-2], 85)
        # 触及支撑 + 当根收涨
        if abs(l[i] - sr_support)/sr_support < tolerance and c[i] > c[i-1]:
            signals.append((i, 1))
        # 触及阻力 + 当根收跌
        elif abs(h[i] - sr_resist)/sr_resist < tolerance and c[i] < c[i-1]:
            signals.append((i, -1))
    return signals


# ─── 三段验证 ─────────────────────────────────────────────
def three_fold_validate(signals, df):
    n = len(signals)
    if n < 30: return None
    t1 = signals[:n//3]
    t2 = signals[n//3:2*n//3]
    t3 = signals[2*n//3:]
    results = []
    for seg in [t1, t2, t3]:
        _, wr, ev = backtest(seg, df)
        results.append((len(seg), round(wr,3), round(ev,4)))
    return results


# ─── 主扫描 ───────────────────────────────────────────────
def main():
    strategies = {
        "S1_StructureBreak": strategy_s1_structure_break,
        "S2_EMAPullback":    strategy_s2_ema_pullback,
        "S3_ATRSqueeze":     strategy_s3_atr_squeeze,
        "S4_MomReversal":    strategy_s4_momentum_reversal,
        "S5_SRBounce":       strategy_s5_sr_bounce,
    }
    results = []
    print(f"{'Symbol':<10} {'TF':<5} {'Strategy':<22} {'Sigs':>5} {'WR':>6} {'EV':>7} {'3-fold'}")
    print("-"*85)
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            df = load_data(sym, tf)
            if df is None or len(df) < 200:
                print(f"{sym:<10} {tf:<5} NO DATA")
                continue
            for sname, sfunc in strategies.items():
                try:
                    sigs = sfunc(df)
                    if len(sigs) < 20:
                        continue
                    _, wr, ev = backtest(sigs, df)
                    fold = three_fold_validate(sigs, df)
                    fold_str = ""
                    if fold:
                        fold_str = " | ".join([f"WR{r[1]:.0%}" for r in fold])
                    flag = " ✅" if wr >= 0.57 and ev > 0 else (" ⚠️" if wr >= 0.53 and ev > 0 else "")
                    print(f"{sym:<10} {tf:<5} {sname:<22} {len(sigs):>5} {wr:>6.1%} {ev:>7.4f}  [{fold_str}]{flag}")
                    results.append({
                        "symbol": sym, "tf": tf, "strategy": sname,
                        "signals": len(sigs), "wr": wr, "ev": ev,
                        "three_fold": fold
                    })
                except Exception as e:
                    print(f"{sym:<10} {tf:<5} {sname:<22} ERROR: {e}")
    # 汇总最优
    print("\n" + "="*85)
    print("TOP CANDIDATES (WR≥53%, EV>0):")
    top = sorted([r for r in results if r["wr"]>=0.53 and r["ev"]>0],
                 key=lambda x: -x["ev"])
    if not top:
        print("  无候选项，降低门槛到 WR≥50%:")
        top = sorted([r for r in results if r["wr"]>=0.50 and r["ev"]>0],
                     key=lambda x: -x["ev"])[:10]
    for r in top[:15]:
        print(f"  {r['symbol']} {r['tf']} {r['strategy']}: WR={r['wr']:.1%} EV={r['ev']:.4f} n={r['signals']}")
    return results

if __name__ == "__main__":
    main()
