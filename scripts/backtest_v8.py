#!/usr/bin/env python3
"""
v8.0 专业均值回归出场系统
出场逻辑（Connors/专业标准）：

优先级：
  1. RSI(2) 出场：LONG 当 RSI(2) > 65 平仓 / SHORT 当 RSI(2) < 35 平仓
  2. BB中轨出场：价格回到 BB20 中轨（20日SMA）即平仓
  3. 紧急时间出场：最多持仓 max_hold 根K线
  4. 极端灾难止损：ATR × 5 宽止损（仅防黑天鹅，不做常规止损）

研究依据：
  - Connors: 固定止损降低均值回归收益
  - RSI(2) > 60-70 出场，捕捉反弹峰值附近
  - 5日SMA回归出场是最简洁有效的均值回归止盈
"""
import json, sys, numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine_v8 import generate_signal_v8, calc_rsi, calc_bollinger, calc_atr


def backtest_v8(data, start, end,
                rsi2_exit_long=65,   # LONG出场：RSI(2)超过此值
                rsi2_exit_short=35,  # SHORT出场：RSI(2)低于此值
                use_bb_mid_exit=True,# 价格回到BB中轨时出场
                disaster_sl_atr=5.0, # 灾难止损（黑天鹅保护）
                max_hold=48,         # 最大持仓K线数
                risk_pct=0.02,       # 仓位风险
                conf_min=0.65):      # 最低入场置信度

    closes  = data['close']
    highs   = data['high']
    lows    = data['low']
    opens   = data['open']
    volumes = data['volume']

    capital = 10000.0
    pos = 0; entry = sl = 0.0; direction = None
    entry_bar = 0; blocked = -1; consec = 0
    trades = []; bb_mid_exit = 0.0
    peak = 10000; max_dd = 0

    for i in range(start, end):
        cur = float(closes[i])
        peak = max(peak, capital)
        max_dd = max(max_dd, (peak - capital) / peak * 100)
        if i <= blocked:
            continue

        # ── 出场检查 ─────────────────────────────
        if pos != 0:
            timeout = (i - entry_bar) >= max_hold

            # 灾难止损（唯一固定止损）
            disaster = ((direction == 'LONG'  and cur <= sl) or
                        (direction == 'SHORT' and cur >= sl))

            # RSI(2) 出场
            rsi2_now = calc_rsi(closes[:i+1], 2) if i >= 3 else 50.0
            rsi2_exit = ((direction == 'LONG'  and rsi2_now >= rsi2_exit_long) or
                         (direction == 'SHORT' and rsi2_now <= rsi2_exit_short))

            # BB 中轨回归出场
            bb_m_now, _, _, _ = calc_bollinger(closes[:i+1], 20)
            bb_mid_reached = use_bb_mid_exit and (
                (direction == 'LONG'  and cur >= bb_m_now) or
                (direction == 'SHORT' and cur <= bb_m_now)
            )

            hit = disaster or rsi2_exit or bb_mid_reached or timeout

            if hit:
                slip   = 0.0007
                exit_p = cur*(1-slip) if direction=='LONG' else cur*(1+slip)
                pnl    = (exit_p-entry)/entry*100 if direction=='LONG' \
                         else (entry-exit_p)/entry*100
                capital *= (1 + pnl/100 * risk_pct)

                if disaster:          reason = '灾难止损'
                elif rsi2_exit:       reason = f'RSI2出场({rsi2_now:.0f})'
                elif bb_mid_reached:  reason = 'BB中轨出场'
                else:                 reason = '超时出场'

                trades.append({
                    'dir': direction, 'pnl': round(pnl, 4),
                    'win': pnl > 0, 'exit': reason,
                    'hold': i - entry_bar,
                    'entry_bar': entry_bar, 'exit_bar': i,
                    'entry_px': round(entry, 2), 'exit_px': round(exit_p, 2),
                    'capital': round(capital, 2),
                })
                consec = consec + 1 if pnl < 0 else 0
                if consec >= 5:
                    blocked = i + 24
                    consec  = 0
                pos = 0

        # ── 入场检查 ─────────────────────────────
        if pos == 0 and i >= 22:
            sig = generate_signal_v8(
                closes[:i+1], highs[:i+1], lows[:i+1],
                opens[:i+1], volumes[:i+1]
            )
            if sig['direction'] != 'NEUTRAL' and sig['confidence'] >= conf_min:
                atr = calc_atr(highs[:i+1], lows[:i+1], closes[:i+1], 14)
                slip = 0.0007
                ep   = cur*(1+slip) if sig['direction']=='LONG' else cur*(1-slip)
                # 灾难止损 = 5×ATR（仅防黑天鹅）
                sl_p = (ep - atr*disaster_sl_atr if sig['direction']=='LONG'
                        else ep + atr*disaster_sl_atr)

                pos       = 1
                entry     = ep
                sl        = sl_p
                direction = sig['direction']
                entry_bar = i
                # 记录入场时的BB中轨，用于出场判断
                bb_mid_exit = sig.get('bb_mid', float(np.mean(closes[max(0,i-19):i+1])))

    if not trades:
        return {'trades': 0, 'wr': 0, 'rr': 0, 'ev': 0, 'ret': 0,
                'dd': max_dd, 'capital': capital}

    wins   = sum(1 for t in trades if t['win'])
    wr     = wins / len(trades)
    longs  = [t for t in trades if t['dir']=='LONG']
    shorts = [t for t in trades if t['dir']=='SHORT']
    l_wr   = sum(1 for t in longs  if t['win'])/len(longs)  if longs  else 0
    s_wr   = sum(1 for t in shorts if t['win'])/len(shorts) if shorts else 0
    ps     = [t['pnl'] for t in trades if t['pnl']>0]
    ls     = [t['pnl'] for t in trades if t['pnl']<0]
    rr     = abs(np.mean(ps)/np.mean(ls)) if ps and ls else 0
    ev     = wr*np.mean(ps)+(1-wr)*np.mean(ls) if ps and ls else 0
    ret    = (capital - 10000) / 10000 * 100
    mc     = cc = 0
    for t in trades:
        cc = cc+1 if not t['win'] else 0; mc = max(mc, cc)

    exit_dist = {}
    for t in trades:
        k = t['exit'].split('(')[0]
        exit_dist.setdefault(k, {'n':0,'w':0})
        exit_dist[k]['n'] += 1
        exit_dist[k]['w'] += int(t['win'])

    return {
        'trades': len(trades), 'wr': wr, 'l_wr': l_wr, 's_wr': s_wr,
        'rr': rr, 'ev': ev, 'ret': ret, 'dd': max_dd, 'capital': capital,
        'longs': len(longs), 'shorts': len(shorts),
        'max_consec': mc, 'exit_dist': exit_dist,
        'trade_list': trades,
    }


def run_three_segment(data):
    total = len(data['close'])
    t_end = int(total * 0.60)
    v_end = int(total * 0.80)
    segs  = [(22, t_end,'训练集'), (t_end, v_end,'验证集'), (v_end, total,'测试集')]
    results = []
    for s, e, lbl in segs:
        r = backtest_v8(data, s, e)
        r['label'] = lbl
        results.append(r)
    return results


if __name__ == '__main__':
    with open(Path(__file__).parent.parent/'data'/'BTCUSDT_1h_futures.json') as f:
        raw = json.load(f)
    data = {k: [d[k] for d in raw] for k in ['close','high','low','open','volume']}

    results = run_three_segment(data)
    print("="*72)
    print("v8.0 专业均值回归（RSI2出场+BB中轨出场）三段验证")
    print("="*72)
    for r in results:
        if r['trades'] == 0:
            print(f"{r['label']}: 无信号"); continue
        print(f"\n{r['label']}: {r['trades']}笔  胜率{r['wr']*100:.2f}%  "
              f"多{r['l_wr']*100:.0f}%/空{r['s_wr']*100:.0f}%  "
              f"盈亏比{r['rr']:.2f}  EV{r['ev']:+.4f}%  "
              f"收益{r['ret']:+.3f}%  回撤{r['dd']:.2f}%  连亏{r['max_consec']}笔")
        for k,v in r['exit_dist'].items():
            print(f"  {k}: {v['n']}次 胜率{v['w']/v['n']*100:.0f}%")

    valid = [r for r in results if r['trades']>0]
    avg_wr = np.mean([r['wr'] for r in valid])
    avg_rr = np.mean([r['rr'] for r in valid])
    avg_ev = np.mean([r['ev'] for r in valid])
    all_pos = all(r['ret']>=0 for r in valid)
    max_dd  = max(r['dd'] for r in valid)
    max_cl  = max(r['max_consec'] for r in valid)
    print(f"\n{'='*72}")
    print(f"综合: 胜率{avg_wr*100:.2f}%  盈亏比{avg_rr:.2f}  EV{avg_ev:+.4f}%  "
          f"三段盈利{'✅' if all_pos else '❌'}  回撤{max_dd:.2f}%  连亏{max_cl}笔")
    print()
    targets = [
        ('胜率≥55%', avg_wr>=0.55), ('胜率≥50%', avg_wr>=0.50),
        ('盈亏比≥2.0', avg_rr>=2.0), ('盈亏比≥1.5', avg_rr>=1.5),
        ('三段正收益', all_pos), ('回撤<15%', max_dd<15), ('连亏<5', max_cl<5),
    ]
    for name, ok in targets:
        print(f"  {'✅' if ok else '❌'} {name}")
