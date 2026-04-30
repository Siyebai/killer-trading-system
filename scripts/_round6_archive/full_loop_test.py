# [ARCHIVED by Round 8 Integration - 2025-04-30]
# Reason: No active callers / Superseded

#!/usr/bin/env python3
"""
杀手锏交易系统 - 完整闭环模拟测试
100 笔完整交易 + 复盘分析 + 系统自我学习更新
"""
import json, sys, numpy as np
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine_v5 import generate_signal_v5

DATA_FILE = Path(__file__).parent.parent / "data" / "BTCUSDT_1h_365d.json"


# ─────────────────────────────────────────────────────
# 1. 数据加载
# ─────────────────────────────────────────────────────
def load():
    with open(DATA_FILE) as f:
        raw = json.load(f)
    return {k: [r[k] for r in raw]
            for k in ['timestamp','open','high','low','close','volume','datetime']}


# ─────────────────────────────────────────────────────
# 2. 完整闭环回测（动态止盈）
# ─────────────────────────────────────────────────────
def full_loop(data, start, end,
              conf_min=0.74, conf_max=0.87,
              sl_atr=2.0, tp_atr=3.5, max_hold=24,
              risk_pct=0.02, target_trades=200):

    closes, highs, lows, opens = (data[k] for k in ['close','high','low','open'])
    volumes, datetimes = data['volume'], data['datetime']

    capital = 10000.0
    pos = 0; entry = sl = tp = trail_sl = 0.0
    direction = None; entry_bar = 0
    blocked = -1; consec = 0; trailing_on = False
    trades = []

    for i in range(start, end):
        if len(trades) >= target_trades:
            break
        cur = float(closes[i])
        if i <= blocked:
            continue

        # ── 出场逻辑 ────────────────────────────────
        if pos != 0:
            # 动态追踪止损（三信号触发时启用）
            if trailing_on:
                atr_now = np.mean([
                    max(highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1]))
                    for j in range(max(0,i-13), i+1)
                ])
                if direction == 'LONG':
                    new_trail = cur - atr_now * 1.2
                    if new_trail > trail_sl:
                        trail_sl = new_trail
                    sl = max(sl, trail_sl)
                else:
                    new_trail = cur + atr_now * 1.2
                    if new_trail < trail_sl:
                        trail_sl = new_trail
                    sl = min(sl, trail_sl)

            # 超时
            timeout = (i - entry_bar) >= max_hold

            hit = ((direction == 'LONG'  and (cur <= sl or cur >= tp)) or
                   (direction == 'SHORT' and (cur >= sl or cur <= tp)) or
                   timeout)

            if hit:
                slip   = 0.0007
                exit_p = cur*(1-slip) if direction=='LONG' else cur*(1+slip)
                pnl    = (exit_p-entry)/entry*100 if direction=='LONG' \
                         else (entry-exit_p)/entry*100
                capital *= (1 + pnl/100 * risk_pct)

                exit_reason = ('止盈' if
                    (direction=='LONG' and cur>=tp) or (direction=='SHORT' and cur<=tp)
                    else ('止损' if
                    (direction=='LONG' and cur<=sl) or (direction=='SHORT' and cur>=sl)
                    else '超时平仓'))

                trades.append({
                    'id':          len(trades) + 1,
                    'direction':   direction,
                    'entry_time':  datetimes[entry_bar][:16],
                    'exit_time':   datetimes[i][:16],
                    'entry_price': round(entry, 2),
                    'exit_price':  round(exit_p, 2),
                    'stop_loss':   round(sl, 2),
                    'take_profit': round(tp, 2),
                    'pnl_pct':     round(pnl, 4),
                    'pnl_usdt':    round(capital * risk_pct * pnl/100, 4),
                    'win':         pnl > 0,
                    'exit_reason': exit_reason,
                    'hold_bars':   i - entry_bar,
                    'capital_after': round(capital, 2),
                    'trailing':    trailing_on,
                })
                consec = consec + 1 if pnl < 0 else 0
                if consec >= 5:
                    blocked = i + 24
                    consec  = 0
                pos = 0; trailing_on = False

        # ── 入场逻辑 ────────────────────────────────
        if pos == 0 and i >= 50:
            sig = generate_signal_v5(
                closes[:i+1], highs[:i+1], lows[:i+1],
                opens[:i+1],  volumes[:i+1]
            )
            if sig['direction'] != 'NEUTRAL' and conf_min <= sig['confidence'] <= conf_max:
                atr_w = [
                    max(highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1]))
                    for j in range(max(0, i-13), i+1)
                ]
                atr  = float(np.mean(atr_w)) or cur * 0.01
                slip = 0.0007
                ep   = cur * (1+slip) if sig['direction']=='LONG' else cur*(1-slip)
                if sig['direction'] == 'LONG':
                    sl_p, tp_p = ep - atr*sl_atr, ep + atr*tp_atr
                else:
                    sl_p, tp_p = ep + atr*sl_atr, ep - atr*tp_atr
                # 强制盈亏比 ≥ 2:1
                if abs(tp_p-ep) / max(abs(sl_p-ep), 1e-9) < 1.95:
                    tp_p = (ep + abs(sl_p-ep)*2.0) if sig['direction']=='LONG' \
                           else (ep - abs(sl_p-ep)*2.0)

                pos = 1; entry = ep; sl = sl_p; tp = tp_p
                direction = sig['direction']
                entry_bar = i
                trailing_on = sig.get('trailing', False)
                trail_sl    = sl_p

    return trades, capital


# ─────────────────────────────────────────────────────
# 3. 统计分析
# ─────────────────────────────────────────────────────
def analyze(trades, init_capital=10000.0):
    if not trades:
        return {}
    n       = len(trades)
    wins    = [t for t in trades if t['win']]
    losses  = [t for t in trades if not t['win']]
    longs   = [t for t in trades if t['direction']=='LONG']
    shorts  = [t for t in trades if t['direction']=='SHORT']
    l_wins  = [t for t in longs  if t['win']]
    s_wins  = [t for t in shorts if t['win']]

    pnls    = [t['pnl_pct'] for t in trades]
    w_pnls  = [t['pnl_pct'] for t in wins]
    l_pnls  = [t['pnl_pct'] for t in losses]

    avg_w   = float(np.mean(w_pnls)) if w_pnls else 0
    avg_l   = float(np.mean(l_pnls)) if l_pnls else 0
    rr      = abs(avg_w/avg_l) if avg_l else 0
    ev      = len(wins)/n * avg_w + len(losses)/n * avg_l

    # Sharpe（简化）
    daily   = [sum(t['pnl_pct'] for t in trades[i:i+6])/100
               for i in range(0, n, 6)]
    sharpe  = float(np.mean(daily)/np.std(daily)*np.sqrt(365*4)) if len(daily) > 1 and np.std(daily) > 0 else 0

    # 最大回撤
    caps   = [init_capital] + [t['capital_after'] for t in trades]
    peak   = init_capital; max_dd = 0
    for c in caps:
        peak   = max(peak, c)
        max_dd = max(max_dd, (peak-c)/peak*100)

    # 最大连续亏损
    mc = cc = 0
    for t in trades:
        cc = cc+1 if not t['win'] else 0
        mc = max(mc, cc)

    # 按出场原因
    exit_stats = {}
    for t in trades:
        r = t['exit_reason']
        exit_stats.setdefault(r, {'n':0,'wins':0})
        exit_stats[r]['n']    += 1
        exit_stats[r]['wins'] += int(t['win'])

    # 按持仓时长分组
    hold_buckets = {'<6h':{'w':0,'l':0},'6-12h':{'w':0,'l':0},
                    '12-24h':{'w':0,'l':0},'>24h':{'w':0,'l':0}}
    for t in trades:
        h = t['hold_bars']
        k = '<6h' if h<6 else ('6-12h' if h<12 else ('12-24h' if h<24 else '>24h'))
        hold_buckets[k]['w' if t['win'] else 'l'] += 1

    final_cap = trades[-1]['capital_after']
    return {
        'total': n,
        'win_count': len(wins), 'loss_count': len(losses),
        'win_rate': len(wins)/n,
        'long_count': len(longs),  'long_wr': len(l_wins)/len(longs) if longs else 0,
        'short_count': len(shorts), 'short_wr': len(s_wins)/len(shorts) if shorts else 0,
        'avg_win': avg_w, 'avg_loss': avg_l,
        'profit_factor': rr,
        'expected_value': ev,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'max_consec_loss': mc,
        'total_return': (final_cap - init_capital)/init_capital*100,
        'final_capital': final_cap,
        'exit_stats': exit_stats,
        'hold_buckets': hold_buckets,
    }


# ─────────────────────────────────────────────────────
# 4. 复盘分析 + 自学习规则更新
# ─────────────────────────────────────────────────────
def retrospective(trades, stats):
    lessons = []
    rules_update = {}

    wr = stats['win_rate']
    rr = stats['profit_factor']
    ev = stats['expected_value']

    # ── 胜率分析 ──────────────────────────────────
    if wr >= 0.55:
        lessons.append(f"✅ 胜率{wr*100:.1f}% 超过55%目标，信号质量良好")
    elif wr >= 0.50:
        lessons.append(f"⚠️  胜率{wr*100:.1f}% 刚过50%，期望值为正但需提升")
    else:
        lessons.append(f"❌ 胜率{wr*100:.1f}% 低于50%，信号质量需改善")

    # ── 方向分析 ──────────────────────────────────
    l_wr = stats['long_wr']; s_wr = stats['short_wr']
    if abs(l_wr - s_wr) > 0.12:
        weak = 'LONG' if l_wr < s_wr else 'SHORT'
        lessons.append(f"⚠️  {weak}方向胜率明显偏低({min(l_wr,s_wr)*100:.0f}%)，建议提高该方向信号阈值")
        rules_update['weak_direction'] = weak
        rules_update['direction_conf_boost'] = 0.03

    # ── 盈亏比分析 ────────────────────────────────
    if rr >= 2.0:
        lessons.append(f"✅ 盈亏比{rr:.2f}:1 优秀，止盈设置合理")
    elif rr >= 1.5:
        lessons.append(f"⚠️  盈亏比{rr:.2f}:1 合格，可尝试扩大止盈到4×ATR")
        rules_update['tp_atr_suggestion'] = 4.0
    else:
        lessons.append(f"❌ 盈亏比{rr:.2f}:1 不足，止盈过早或止损过宽")
        rules_update['tp_atr_suggestion'] = 4.5
        rules_update['sl_atr_suggestion'] = 1.5

    # ── 出场原因分析 ──────────────────────────────
    es = stats['exit_stats']
    for reason, v in es.items():
        n = v['n']; w = v['wins']
        wr_r = w/n if n > 0 else 0
        if reason == '超时平仓' and n >= 5:
            if wr_r < 0.35:
                lessons.append(f"💡 超时平仓胜率仅{wr_r*100:.0f}%({n}笔)，持仓时间上限可缩短到16根K线")
                rules_update['max_hold_suggestion'] = 16
            elif wr_r > 0.55:
                lessons.append(f"💡 超时平仓胜率{wr_r*100:.0f}%({n}笔)，可延长持仓到32根K线")
                rules_update['max_hold_suggestion'] = 32
        if reason == '止损' and n >= 10:
            lessons.append(f"📊 止损触发{n}笔(胜率{wr_r*100:.0f}%)，止损设置{'合理' if wr_r<0.3 else '可能过紧'}")

    # ── 持仓时长分析 ──────────────────────────────
    hb = stats['hold_buckets']
    best_bucket = max(hb.items(), key=lambda x: x[1]['w']/(x[1]['w']+x[1]['l']) if (x[1]['w']+x[1]['l'])>3 else 0)
    bt, bv = best_bucket
    total_b = bv['w'] + bv['l']
    if total_b >= 5:
        bwr = bv['w'] / total_b
        lessons.append(f"💡 最优持仓时长: {bt}  胜率{bwr*100:.0f}%({total_b}笔)")
        rules_update['best_hold_window'] = bt

    # ── 连续亏损分析 ──────────────────────────────
    mc = stats['max_consec_loss']
    if mc >= 5:
        lessons.append(f"⚠️  出现{mc}笔连续亏损，熔断机制已触发，需检查该时段市场环境")
    elif mc <= 3:
        lessons.append(f"✅ 最大连续亏损仅{mc}笔，风控健康")

    # ── 期望值 ────────────────────────────────────
    if ev > 0:
        lessons.append(f"✅ 期望值{ev:+.3f}%/笔，系统长期运行可持续盈利")
    else:
        lessons.append(f"❌ 期望值{ev:+.3f}%/笔，负期望需调整信号参数")

    return lessons, rules_update


# ─────────────────────────────────────────────────────
# 5. 主程序
# ─────────────────────────────────────────────────────
def run():
    print("=" * 72)
    print("🚀 杀手锏 v5.0 — 完整闭环模拟测试 (目标100笔)")
    print("=" * 72)

    data  = load()
    total = len(data['close'])

    # 用后40%数据（样本外）跑100笔
    start = int(total * 0.60)
    print(f"\n📡 真实BTC数据: {data['datetime'][start][:10]} → {data['datetime'][-1][:10]}")
    print(f"   价格: ${data['close'][start]:,.0f} → ${data['close'][-1]:,.0f}")
    print(f"\n⏳ 模拟交易中...")

    trades, final_cap = full_loop(data, start, total, target_trades=150)
    trades = trades[:100]  # 取前100笔

    stats = analyze(trades)

    # ── 打印摘要 ──────────────────────────────────
    print(f"\n{'='*72}")
    print(f"📊 100笔完整闭环测试结果")
    print(f"{'='*72}")
    print(f"  总交易: {stats['total']}笔")
    print(f"  胜/负:  {stats['win_count']}/{stats['loss_count']}")
    print(f"  胜率:   {stats['win_rate']*100:.2f}%")
    print(f"  LONG:   {stats['long_count']}笔  胜率{stats['long_wr']*100:.1f}%")
    print(f"  SHORT:  {stats['short_count']}笔  胜率{stats['short_wr']*100:.1f}%")
    print(f"  平均盈利: {stats['avg_win']:+.3f}%  平均亏损: {stats['avg_loss']:+.3f}%")
    print(f"  盈亏比:   {stats['profit_factor']:.2f}:1")
    print(f"  期望值:   {stats['expected_value']:+.4f}%/笔")
    print(f"  夏普比:   {stats['sharpe']:.2f}")
    print(f"  最大回撤: {stats['max_drawdown']:.2f}%")
    print(f"  最大连亏: {stats['max_consec_loss']}笔")
    print(f"  总收益:   {stats['total_return']:+.3f}%")
    print(f"  最终资金: ${stats['final_capital']:,.2f}")

    # ── 出场原因 ──────────────────────────────────
    print(f"\n出场原因分布:")
    for r, v in stats['exit_stats'].items():
        n = v['n']; wr = v['wins']/n*100 if n else 0
        print(f"  {r:<8}: {n:>3}笔  胜率{wr:.0f}%")

    # ── 持仓时长 ──────────────────────────────────
    print(f"\n持仓时长胜率:")
    for bucket, v in stats['hold_buckets'].items():
        t = v['w']+v['l']
        if t: print(f"  {bucket:<8}: {t:>3}笔  胜率{v['w']/t*100:.0f}%")

    # ── 交易流水（每10笔一行）─────────────────────
    print(f"\n📋 交易流水 (每行10笔):")
    for i in range(0, len(trades), 10):
        row = trades[i:i+10]
        icons = ''.join(['✅' if t['win'] else '❌' for t in row])
        pnls  = [t['pnl_pct'] for t in row]
        total_row = sum(pnls)
        print(f"  {i+1:>3}-{i+len(row):<3}: {icons}  合计{total_row:+.2f}%")

    # ── 阶段性资金曲线 ───────────────────────────
    print(f"\n📈 资金曲线(每25笔):")
    caps = [10000.0]
    for t in trades:
        caps.append(t['capital_after'])
    for milestone in [25, 50, 75, 100]:
        if milestone <= len(trades):
            c = caps[milestone]
            ret = (c-10000)/10000*100
            bar = '█' * int(abs(ret)*20) if abs(ret) < 5 else '█'*20
            print(f"  第{milestone:>3}笔: ${c:>10,.2f}  {ret:+.3f}%  {bar}")

    # ── 复盘分析 ──────────────────────────────────
    print(f"\n{'='*72}")
    print(f"🔍 复盘分析 & 系统自学习")
    print(f"{'='*72}")
    lessons, rules = retrospective(trades, stats)
    for i, lesson in enumerate(lessons, 1):
        print(f"  {i}. {lesson}")

    if rules:
        print(f"\n📝 系统参数建议更新:")
        for k, v in rules.items():
            print(f"  {k}: {v}")

    # ── 保存完整报告 ─────────────────────────────
    report = {
        'version': 'v5.0',
        'test_date': datetime.now().isoformat(),
        'data_range': f"{data['datetime'][int(total*0.6)][:10]} → {data['datetime'][-1][:10]}",
        'stats': stats,
        'lessons': lessons,
        'rules_update': rules,
        'trades': trades
    }
    out = Path(__file__).parent.parent / "v5_100trade_report.json"
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n💾 完整报告已保存: {out.name}")
    print("=" * 72)
    return report


if __name__ == "__main__":
    run()
