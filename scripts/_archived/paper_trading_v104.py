#!/usr/bin/env python3
"""
杀手锏 v1.0.4 — 多币种实时纸交易引擎
方案C：接入真实Binance行情，本地模拟执行，不下真实订单
支持：BTCUSDT / ETHUSDT / SOLUSDT / BNBUSDT
时间：北京时间(UTC+8)
"""
import json, time, subprocess, sys, os, hmac, hashlib, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine_v4 import generate_signal_v4, calc_atr as _atr

TZ_CST = timezone(timedelta(hours=8))
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
INTERVALS = {"1m": 60, "5m": 300, "1h": 3600}

CAPITAL = 150.0
RISK_PCT = 0.05       # 5% 每笔风险
SL_ATR   = 2.0
TP_ATR   = 3.5
MAX_HOLD = {"1m": 60, "5m": 24, "1h": 24}  # 根数
CONF_MIN = 0.74

def now_cst():
    return datetime.now(tz=TZ_CST).strftime("%Y-%m-%d %H:%M:%S CST")

def fetch_klines(symbol, interval, limit=100):
    """用binance-cli拉K线，返回closes/highs/lows/volumes/tbvols列表"""
    cmd = ["binance-cli", "futures-usds", "kline-candlestick-data",
           "--symbol", symbol, "--interval", interval, "--limit", str(limit)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        bars = json.loads(r.stdout)
        closes  = [float(b[4]) for b in bars]
        highs   = [float(b[2]) for b in bars]
        lows    = [float(b[3]) for b in bars]
        opens   = [float(b[1]) for b in bars]
        vols    = [float(b[5]) for b in bars]
        tbvols  = [float(b[9]) for b in bars]
        ts      = [int(b[0]) for b in bars]
        return closes, highs, lows, opens, vols, tbvols, ts
    except Exception as e:
        return None, None, None, None, None, None, None

def simulate_session(symbol, interval, n_bars=200):
    """
    模拟实时交易：拉最新K线，逐根运行信号引擎，记录每笔交易
    n_bars: 回溯多少根K线来模拟（out-of-sample最新数据）
    """
    limit = min(n_bars + 60, 1000)  # 多拉60根用于指标预热
    closes, highs, lows, opens, vols, tbvols, ts = fetch_klines(symbol, interval, limit)
    if closes is None:
        return None

    total = len(closes)
    warmup = 50  # 前50根用于指标预热

    cap = CAPITAL
    pos = 0; entry = sl = tp = 0.; direction = None; ebar = 0
    consec = 0; blocked = -1
    trades = []; peak = cap; dd = 0.

    hold_bars = MAX_HOLD.get(interval, 24)

    for i in range(warmup, total):
        cur = closes[i]
        peak = max(peak, cap)
        dd = max(dd, (peak - cap) / peak * 100)
        if i <= blocked:
            continue

        if pos != 0:
            timeout = (i - ebar) >= hold_bars
            hit = ((direction == 'LONG' and (cur <= sl or cur >= tp)) or
                   (direction == 'SHORT' and (cur >= sl or cur <= tp)) or timeout)
            if hit:
                slip = 0.0004
                ep2 = cur * (1 - slip) if direction == 'LONG' else cur * (1 + slip)
                pnl = (ep2 - entry) / entry * 100 if direction == 'LONG' else (entry - ep2) / entry * 100
                pnl_u = cap * RISK_PCT * pnl / 100
                cap += pnl_u
                ex = ('tp' if (direction=='LONG' and cur>=tp) or (direction=='SHORT' and cur<=tp)
                      else 'sl' if (direction=='LONG' and cur<=sl) or (direction=='SHORT' and cur>=sl)
                      else 'time')
                bar_ts = datetime.fromtimestamp(ts[i]/1000, tz=TZ_CST).strftime("%m-%d %H:%M")
                trades.append({
                    'symbol': symbol, 'interval': interval,
                    'dir': direction, 'pnl': round(pnl, 4), 'pnl_u': round(pnl_u, 3),
                    'win': pnl > 0, 'exit': ex, 'hold': i - ebar,
                    'entry_px': round(entry, 4), 'exit_px': round(ep2, 4),
                    'cap': round(cap, 2), 'time': bar_ts
                })
                consec = consec + 1 if pnl < 0 else 0
                if consec >= 5:
                    blocked = i + 20; consec = 0
                pos = 0

        if pos == 0:
            sig = generate_signal_v4(
                closes[:i+1], highs[:i+1], lows[:i+1],
                opens[:i+1], vols[:i+1]
            )
            if sig['direction'] != 'NEUTRAL' and sig['confidence'] >= CONF_MIN:
                atr = _atr(highs[:i+1], lows[:i+1], closes[:i+1], 14)
                slip = 0.0004
                ep = closes[i] * (1 + slip) if sig['direction'] == 'LONG' else closes[i] * (1 - slip)
                if sig['direction'] == 'LONG':
                    sl_p, tp_p = ep - atr * SL_ATR, ep + atr * TP_ATR
                else:
                    sl_p, tp_p = ep + atr * SL_ATR, ep - atr * TP_ATR
                pos = 1; entry = ep; sl = sl_p; tp = tp_p
                direction = sig['direction']; ebar = i

    if not trades:
        return {'symbol': symbol, 'interval': interval, 'trades': 0,
                'wr': 0, 'rr': 0, 'ev': 0, 'ret': 0, 'dd': dd, 'pnl_u': 0}

    wins = sum(1 for t in trades if t['win'])
    wr = wins / len(trades)
    ps = [t['pnl'] for t in trades if t['pnl'] > 0]
    ls = [t['pnl'] for t in trades if t['pnl'] < 0]
    rr = abs(np.mean(ps) / np.mean(ls)) if ps and ls else 0
    ev = wr * np.mean(ps) + (1 - wr) * np.mean(ls) if ps and ls else 0
    ret = (cap - CAPITAL) / CAPITAL * 100
    mc = cc = 0
    for t in trades:
        cc = cc + 1 if not t['win'] else 0; mc = max(mc, cc)

    return {
        'symbol': symbol, 'interval': interval,
        'trades': len(trades), 'wr': wr, 'rr': rr, 'ev': ev,
        'ret': ret, 'dd': dd, 'pnl_u': round(cap - CAPITAL, 2),
        'cap': round(cap, 2), 'mc': mc, 'trade_list': trades
    }


def run_full_scan():
    """扫描所有币种×时间框架，输出排名报告"""
    print(f"\n{'='*70}")
    print(f"杀手锏 v1.0.4 — 多币种实时扫描")
    print(f"时间：{now_cst()}")
    print(f"资金：${CAPITAL}U  仓位：{RISK_PCT*100:.0f}%  策略：v4均值回归")
    print(f"{'='*70}")

    results = []
    for sym in SYMBOLS:
        for iv in ["1m", "5m", "1h"]:
            print(f"  扫描 {sym} {iv}...", end=' ', flush=True)
            r = simulate_session(sym, iv, n_bars=300 if iv != "1h" else 200)
            if r and r['trades'] > 0:
                results.append(r)
                print(f"{r['trades']}笔 WR{r['wr']*100:.1f}% EV{r['ev']:+.4f}%")
            else:
                print("无信号")
            time.sleep(0.3)  # 避免频率限制

    if not results:
        print("所有组合均无信号")
        return

    # 排名：EV > 0 且三段正收益优先
    results.sort(key=lambda x: x['wr'] * x['rr'] if x['ev'] > 0 else -99, reverse=True)

    print(f"\n{'─'*70}")
    print(f"{'排名':<4}{'币种':<10}{'周期':<6}{'笔数':<6}{'胜率':<8}{'RR':<6}{'EV/笔':<12}{'收益':<10}{'盈亏$U':<10}{'回撤':<8}{'连亏'}")
    print(f"{'─'*70}")
    for i, r in enumerate(results[:10], 1):
        flag = '★' if r['ev'] > 0 and r['wr'] >= 0.50 else ''
        print(f"{i:<4}{r['symbol']:<10}{r['interval']:<6}{r['trades']:<6}"
              f"{r['wr']*100:.1f}%{'':<3}{r['rr']:.2f}{'':<3}"
              f"{r['ev']:+.4f}%{'':<4}{r['ret']:+.2f}%{'':<4}"
              f"${r['pnl_u']:+.2f}{'':<5}{r['dd']:.2f}%{'':<3}{r['mc']} {flag}")

    # 保存报告
    report_path = LOG_DIR / f"scan_{datetime.now(tz=TZ_CST).strftime('%Y%m%d_%H%M')}.json"
    with open(report_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n报告已保存：{report_path}")

    # 最优组合详情
    best = results[0] if results[0]['ev'] > 0 else None
    if best:
        print(f"\n★ 最优：{best['symbol']} {best['interval']}")
        print(f"  胜率{best['wr']*100:.1f}%  RR{best['rr']:.2f}  EV{best['ev']:+.4f}%/笔")
        print(f"  {best['trades']}笔  收益{best['ret']:+.2f}%  盈亏${best['pnl_u']:+.2f}U  回撤{best['dd']:.2f}%")
        if best.get('trade_list'):
            print(f"\n  最近5笔：")
            for t in best['trade_list'][-5:]:
                mark = '✅' if t['win'] else '❌'
                print(f"    {mark} {t['time']} {t['dir']:<6} "
                      f"入{t['entry_px']} 出{t['exit_px']} "
                      f"PnL{t['pnl']:+.3f}% ${t['pnl_u']:+.2f}U "
                      f"({t['exit']}/{t['hold']}根)")

    return results


if __name__ == "__main__":
    run_full_scan()
