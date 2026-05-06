#!/usr/bin/env python3
"""
orderflow_strategy.py — 订单流策略 v1.0
核心逻辑：taker_buy/sell 净量判断资金方向 + 价格突破确认 + 成交量放大
字段格式: [ts, open, high, low, close, vol, taker_buy_vol]
"""
import json, os, sys, time
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")

# ──────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────
def load_data(path: str) -> dict:
    with open(path) as f:
        raw = json.load(f)
    arr = np.array(raw, dtype=np.float64)
    ts   = arr[:, 0]
    o    = arr[:, 1]
    h    = arr[:, 2]
    l    = arr[:, 3]
    c    = arr[:, 4]
    vol  = arr[:, 5]
    tb   = arr[:, 6]          # taker_buy_base_vol
    ts_  = arr[:, 5]          # taker_sell = vol - taker_buy
    net  = tb - (vol - tb)    # net = taker_buy - taker_sell
    return {'ts': ts, 'open': o, 'high': h, 'low': l, 'close': c,
            'vol': vol, 'taker_buy': tb, 'net_flow': net}

# ──────────────────────────────────────────────
# 指标预计算
# ──────────────────────────────────────────────
def precompute(d: dict, p: int = 20) -> dict:
    c   = pd.Series(d['close'])
    h   = pd.Series(d['high'])
    l   = pd.Series(d['low'])
    vol = pd.Series(d['vol'])
    net = pd.Series(d['net_flow'])

    # 价格高低点（突破用）
    roll_h = h.rolling(p).max().shift(1)   # 前p根最高点
    roll_l = l.rolling(p).min().shift(1)   # 前p根最低点

    # 成交量均值
    vol_ma = vol.rolling(p).mean()

    # 净主动量均值 + 标准差（z-score）
    net_ma  = net.rolling(p).mean()
    net_std = net.rolling(p).std()
    net_z   = (net - net_ma) / (net_std + 1e-9)

    # ATR
    tr = pd.concat([
        h - l,
        (h - c.shift(1)).abs(),
        (l - c.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()

    # EMA趋势
    e50  = c.ewm(span=50,  adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False).mean()

    d.update({
        'roll_h':  roll_h.values,
        'roll_l':  roll_l.values,
        'vol_ma':  vol_ma.values,
        'net_z':   net_z.values,
        'net_ma':  net_ma.values,
        'atr':     atr.values,
        'e50':     e50.values,
        'e200':    e200.values,
    })
    return d

# ──────────────────────────────────────────────
# 回测核心
# ──────────────────────────────────────────────
def backtest(d: dict, params: dict, capital: float = 150.0, fee: float = 0.0009) -> dict:
    c      = d['close'];    h = d['high'];   l = d['low']
    vol    = d['vol'];      atr = d['atr']
    roll_h = d['roll_h'];   roll_l = d['roll_l']
    vol_ma = d['vol_ma'];   net_z  = d['net_z']
    e50    = d['e50'];      e200   = d['e200']
    n      = len(c)

    net_z_thresh = params.get('net_z',    1.5)   # 净量z-score阈值
    vol_mult     = params.get('vol_mult', 1.5)   # 成交量倍数
    tp_r         = params.get('tp_r',     2.0)   # 盈亏比
    sl_atr       = params.get('sl_atr',   1.0)   # SL = sl_atr × ATR
    max_hold     = params.get('max_hold', 10)    # 最大持仓根数
    warmup       = params.get('warmup',   220)
    trend_filter = params.get('trend',    True)
    risk_pct     = params.get('risk_pct', 0.02)
    break_pct    = params.get('break_pct', 0.0)  # 突破确认幅度（0=刚好穿越）

    eq = capital; max_eq = capital; max_dd = 0.0
    trades = []; last_exit = -1

    for i in range(warmup, n - max_hold - 1):
        if i <= last_exit:
            continue
        if np.isnan(atr[i]) or atr[i] == 0:
            continue
        if np.isnan(roll_h[i]) or np.isnan(roll_l[i]):
            continue

        vol_ok  = vol_ma[i] > 0 and (vol[i] / vol_ma[i]) >= vol_mult
        ci = c[i]; oi = d['open'][i]

        # 做多信号：净买量z-score > 阈值 + 突破前N高点 + 成交量放大
        long_sig = (
            net_z[i] >= net_z_thresh and
            ci > roll_h[i] * (1 + break_pct) and
            vol_ok and
            ci > oi  # 阳线
        )
        # 做空信号
        short_sig = (
            net_z[i] <= -net_z_thresh and
            ci < roll_l[i] * (1 - break_pct) and
            vol_ok and
            ci < oi  # 阴线
        )

        # 趋势过滤
        if trend_filter:
            long_sig  = long_sig  and e50[i] >= e200[i] * 0.995
            short_sig = short_sig and e50[i] <= e200[i] * 1.005

        if not long_sig and not short_sig:
            continue

        direction = 1 if long_sig else -1
        entry = ci
        sl_dist = atr[i] * sl_atr
        sl_p = entry - direction * sl_dist
        tp_p = entry + direction * sl_dist * tp_r
        sl_pct = sl_dist / entry
        if sl_pct <= 0:
            continue

        size = min(eq * risk_pct / sl_pct, eq * 0.5)

        # 搜索出场
        exit_price = None; exit_reason = 'TIMEOUT'; exit_i = i + max_hold
        for j in range(i + 1, min(i + max_hold + 1, n)):
            hj = h[j]; lj = l[j]
            if direction == 1:
                if lj <= sl_p:
                    exit_price = sl_p; exit_reason = 'SL'; exit_i = j; break
                if hj >= tp_p:
                    exit_price = tp_p; exit_reason = 'TP'; exit_i = j; break
            else:
                if hj >= sl_p:
                    exit_price = sl_p; exit_reason = 'SL'; exit_i = j; break
                if lj <= tp_p:
                    exit_price = tp_p; exit_reason = 'TP'; exit_i = j; break

        if exit_price is None:
            exit_price = c[exit_i]

        gross = size * direction * (exit_price - entry) / entry
        cost  = size * fee * 2
        pnl   = gross - cost

        eq += pnl
        if eq > max_eq:
            max_eq = eq
        dd = (max_eq - eq) / max_eq * 100
        if dd > max_dd:
            max_dd = dd

        trades.append({
            'i': i, 'j': exit_i, 'd': 'L' if direction == 1 else 'S',
            'er': exit_reason, 'u': pnl
        })
        last_exit = exit_i

    total = len(trades)
    if total == 0:
        return {'n': 0, 'wr': 0, 'pnl': 0, 'dd': 0, 'pf': 0,
                'aw': 0, 'al': 0, 'tp': 0, 'sl': 0}

    wins   = [t for t in trades if t['u'] > 0]
    losses = [t for t in trades if t['u'] <= 0]
    gw = sum(t['u'] for t in wins)
    gl = sum(t['u'] for t in losses)

    return {
        'n':   total,
        'wr':  len(wins) / total * 100,
        'pnl': eq - capital,
        'dd':  max_dd,
        'pf':  gw / abs(gl) if gl < 0 else 999,
        'aw':  np.mean([t['u'] for t in wins])   if wins   else 0,
        'al':  np.mean([t['u'] for t in losses]) if losses else 0,
        'tp':  sum(1 for t in trades if t['er'] == 'TP'),
        'sl':  sum(1 for t in trades if t['er'] == 'SL'),
    }


# ──────────────────────────────────────────────
# 主程序
# ──────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 70)
    print("  订单流策略 v1.0 — 真实数据回测")
    print("=" * 70)

    DATASETS = {
        'BTC_3m':  'BTCUSDT_3m_live.json',
        'BTC_5m':  'BTCUSDT_5m_live.json',
        'BTC_15m': 'BTCUSDT_15m_live.json',
        'ETH_3m':  'ETHUSDT_3m_live.json',
        'ETH_5m':  'ETHUSDT_5m_live.json',
        'SOL_3m':  'SOLUSDT_3m_live.json',
        'SOL_5m':  'SOLUSDT_5m_live.json',
        'BNB_3m':  'BNBUSDT_3m_live.json',
        'BNB_5m':  'BNBUSDT_5m_live.json',
    }

    # ── 阶段1：参数网格搜索（BTC_3m基准）──
    print("\n【阶段1】参数网格搜索（BTC 3m，90天）\n")
    d_btc3 = precompute(load_data(os.path.join(DATA_DIR, 'BTCUSDT_3m_live.json')))

    configs = [
        (nz, vm, tp, sl, mh, tr)
        for nz  in [1.0, 1.5, 2.0, 2.5]
        for vm  in [1.2, 1.5, 2.0]
        for tp  in [1.5, 2.0, 3.0]
        for sl  in [0.8, 1.2]
        for mh  in [6, 10, 15]
        for tr  in [True, False]
    ]
    print(f"共 {len(configs)} 组参数...")

    t0 = time.time()
    results = []
    for (nz, vm, tp, sl, mh, tr) in configs:
        r = backtest(d_btc3, {
            'net_z': nz, 'vol_mult': vm, 'tp_r': tp,
            'sl_atr': sl, 'max_hold': mh, 'trend': tr
        })
        if r['n'] >= 15:
            results.append({'net_z': nz, 'vol_mult': vm, 'tp_r': tp,
                            'sl_atr': sl, 'max_hold': mh, 'trend': tr, **r})

    results.sort(key=lambda x: (x['pnl'], x['wr']), reverse=True)
    elapsed = time.time() - t0
    print(f"耗时 {elapsed:.1f}s | 有效结果: {len(results)} 组\n")

    positive = [r for r in results if r['pnl'] > 0]
    print(f"{'#':<4}{'nz':<5}{'vm':<5}{'TP':<5}{'SL':<5}{'H':<4}{'tr':<4}"
          f"{'笔':<5}{'胜率':<8}{'盈U':<9}{'DD':<7}{'PF':<6}{'AvgW':<8}{'AvgL'}")
    print("─" * 80)

    for i, r in enumerate(results[:20]):
        ta = '✓' if r.get('trend') else '✗'
        flag = '✅' if r['pnl'] > 0 and r['wr'] >= 50 else ('⚠️' if r['pnl'] > 0 else '  ')
        print(f"{flag}#{i+1:<2} {r['net_z']:<4} {r['vol_mult']:<4} {r['tp_r']:<4} "
              f"{r['sl_atr']:<4} {r['max_hold']:<3} {ta:<3} "
              f"{r['n']:<5}{r['wr']:>5.1f}%  {r['pnl']:>+7.2f}U  "
              f"{r['dd']:>4.1f}%  {r['pf']:>4.2f}  {r['aw']:>+5.2f}U  {r['al']:>+5.2f}U")

    print(f"\n正期望组合: {len(positive)} / {len(results)}")

    if not positive:
        print("\n❌ BTC 3m 无正期望，检查阈值过严...")
        # 放宽：n>=5
        loose = [r for r in results if r['pnl'] > 0]
        if not loose:
            print("所有参数均亏损，策略方向需调整")
            sys.exit(1)

    # ── 阶段2：最优参数跨品种验证 ──
    print("\n\n【阶段2】最优参数跨品种验证\n")

    # 选正期望且胜率最高的
    best_candidates = [r for r in results if r['pnl'] > 0]
    if not best_candidates:
        best_candidates = results[:3]
    best_candidates.sort(key=lambda x: (x['wr'], x['pnl']), reverse=True)
    best = best_candidates[0]
    best_p = {k: best[k] for k in ['net_z', 'vol_mult', 'tp_r', 'sl_atr', 'max_hold', 'trend']}

    print(f"最优参数: nz={best_p['net_z']} vm={best_p['vol_mult']} "
          f"TP={best_p['tp_r']}R SL={best_p['sl_atr']}ATR "
          f"H={best_p['max_hold']} trend={'ON' if best_p['trend'] else 'OFF'}\n")
    print(f"{'品种':<12}{'笔':>5}{'胜率':>7}{'盈U':>10}{'DD':>7}{'PF':>6}{'AvgW':>7}{'AvgL':>7}")
    print("─" * 65)

    total_pnl = 0; total_n = 0; all_ok = True
    for label, fname in DATASETS.items():
        fpath = os.path.join(DATA_DIR, fname)
        if not os.path.exists(fpath):
            print(f"  {label:<12} 数据缺失，跳过")
            continue
        d2 = precompute(load_data(fpath))
        r2 = backtest(d2, best_p)
        total_pnl += r2['pnl']; total_n += r2['n']
        ok = '✅' if r2['pnl'] > 0 and r2['wr'] >= 50 else ('⚠️ ' if r2['pnl'] > 0 else '❌ ')
        if r2['pnl'] <= 0: all_ok = False
        print(f"{ok}{label:<11}{r2['n']:>5}{r2['wr']:>6.1f}%"
              f"{r2['pnl']:>+9.2f}U{r2['dd']:>6.1f}%{r2['pf']:>5.2f}"
              f"{r2['aw']:>+6.2f}U{r2['al']:>+6.2f}U")

    print(f"{'合计':>14}{total_n:>5}{'':>7}{total_pnl:>+9.2f}U")
    print("\n" + "=" * 65)

    if total_pnl > 10 and all_ok:
        verdict = "✅ 正期望！可进入实盘验证"
    elif total_pnl > 0:
        verdict = "⚠️  部分正期望，需继续优化"
    else:
        verdict = "❌ 仍亏损，策略需调整"

    print(f"结论: {verdict}")
    print(f"最优参数: {best_p}")
