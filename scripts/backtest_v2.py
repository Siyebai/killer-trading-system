#!/usr/bin/env python3
"""
杀手锏交易系统 - 完整回测引擎 v2.0
接入 signal_engine_v2 信号，真实币安数据验证
"""
import json, sys, numpy as np
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine_v2 import generate_signal_v2

DATA_FILE = Path(__file__).parent.parent / "data" / "BTCUSDT_1h_365d.json"
FUND_FILE = Path(__file__).parent.parent / "data" / "BTCUSDT_funding_rate.json"

def load_data():
    with open(DATA_FILE) as f:
        raw = json.load(f)
    keys = ['timestamp','open','high','low','close','volume']
    d = {k: [r[k] for r in raw] for k in keys}
    d['datetime'] = [r['datetime'] for r in raw]
    return d

def load_funding():
    try:
        with open(FUND_FILE) as f:
            data = json.load(f)
        # 最新费率信号
        latest = data[-1]
        rate = float(latest['fundingRate'])
        signal = 'SHORT' if rate > 0.001 else ('LONG' if rate < -0.0005 else 'NEUTRAL')
        return {'rate': rate, 'signal': signal, 'strength': min(abs(rate)/0.001, 1.0)}
    except:
        return {'rate': 0, 'signal': 'NEUTRAL', 'strength': 0}

def backtest_segment(data, start, end, label, conf_threshold=0.62):
    closes  = data['close']
    highs   = data['high']
    lows    = data['low']
    volumes = data['volume']

    capital = 10000.0
    position = 0
    entry_price = sl = tp = 0
    direction = None
    blocked_until = -1
    consec_loss = 0

    trades = []
    equity_curve = [capital]

    for i in range(start, end):
        cur = closes[i]
        if i <= blocked_until:
            equity_curve.append(capital)
            continue

        # 出场检查
        if position != 0:
            hit = False
            if direction == 'LONG'  and (cur <= sl or cur >= tp): hit = True
            if direction == 'SHORT' and (cur >= sl or cur <= tp): hit = True
            if hit:
                slip = 0.0007
                exit_p = cur*(1-slip) if direction=='LONG' else cur*(1+slip)
                pnl = (exit_p-entry_price)/entry_price*100 if direction=='LONG' \
                      else (entry_price-exit_p)/entry_price*100
                capital *= (1 + pnl/100 * 0.02)
                trades.append({
                    'dir': direction, 'pnl': pnl, 'win': pnl > 0,
                    'entry': entry_price, 'exit': exit_p,
                    'bar': i, 'date': data['datetime'][i]
                })
                consec_loss = consec_loss + 1 if pnl < 0 else 0
                if consec_loss >= 5:
                    blocked_until = i + 24
                    consec_loss = 0
                position = 0

        # 入场信号
        if position == 0 and i >= 250:
            sig = generate_signal_v2(
                closes[:i+1], highs[:i+1], lows[:i+1], volumes[:i+1]
            )
            if sig['direction'] != 'NEUTRAL' and sig['confidence'] >= conf_threshold:
                slip = 0.0007
                ep = cur*(1+slip) if sig['direction']=='LONG' else cur*(1-slip)
                # ATR 动态止损
                atr_w = [max(highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1]))
                         for j in range(i-13, i+1)]
                atr = np.mean(atr_w)
                if sig['direction'] == 'LONG':
                    sl_p = ep - atr * 1.5
                    tp_p = ep + atr * 3.0
                else:
                    sl_p = ep + atr * 1.5
                    tp_p = ep - atr * 3.0
                # 确保盈亏比 >= 2:1
                if abs(tp_p - ep) / abs(sl_p - ep) < 1.9:
                    tp_p = ep + abs(sl_p - ep) * 2.0 if sig['direction']=='LONG' \
                           else ep - abs(sl_p - ep) * 2.0
                position = 1
                entry_price = ep; sl = sl_p; tp = tp_p
                direction = sig['direction']

        equity_curve.append(capital)

    # 统计
    total  = len(trades)
    if total == 0:
        return {'label': label, 'trades': 0, 'win_rate': 0, 'return': 0,
                'longs': 0, 'shorts': 0, 'max_consec': 0, 'rr': 0,
                'capital': capital, 'equity': equity_curve}

    wins   = sum(1 for t in trades if t['win'])
    longs  = [t for t in trades if t['dir']=='LONG']
    shorts = [t for t in trades if t['dir']=='SHORT']
    l_wr   = sum(1 for t in longs  if t['win'])/len(longs)  if longs  else 0
    s_wr   = sum(1 for t in shorts if t['win'])/len(shorts) if shorts else 0

    profits = [t['pnl'] for t in trades if t['pnl'] > 0]
    losses  = [t['pnl'] for t in trades if t['pnl'] < 0]
    avg_w   = np.mean(profits) if profits else 0
    avg_l   = np.mean(losses)  if losses  else 0
    rr      = abs(avg_w/avg_l) if avg_l else 0

    # 最大连续亏损
    mc = cc = 0
    for t in trades:
        cc = cc+1 if not t['win'] else 0
        mc = max(mc, cc)

    # 最大回撤
    peak = 10000; max_dd = 0
    for eq in equity_curve:
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak-eq)/peak*100)

    return {
        'label': label,
        'trades': total,
        'wins': wins,
        'win_rate': wins/total,
        'long_wr': l_wr,
        'short_wr': s_wr,
        'longs': len(longs),
        'shorts': len(shorts),
        'return': (capital-10000)/10000*100,
        'avg_win': avg_w,
        'avg_loss': avg_l,
        'rr': rr,
        'max_consec': mc,
        'max_drawdown': max_dd,
        'capital': capital,
        'equity': equity_curve[-50:]   # 只存最后50个点节省空间
    }

def run():
    print("=" * 68)
    print("🚀 杀手锏 v2.0 信号引擎 × 真实币安数据 — 全量验证")
    print("=" * 68)

    data  = load_data()
    fund  = load_funding()
    total = len(data['close'])

    print(f"\n📡 数据: {total} 根K线  {data['datetime'][0][:10]} → {data['datetime'][-1][:10]}")
    print(f"💸 资金费率: {fund['rate']*100:.4f}%  信号: {fund['signal']}")

    t_end = int(total * 0.60)
    v_end = int(total * 0.80)

    print(f"\n📊 数据切分 (60/20/20):")
    print(f"   训练集: {data['datetime'][210][:10]} → {data['datetime'][t_end][:10]}  ({t_end-210}根)")
    print(f"   验证集: {data['datetime'][t_end][:10]} → {data['datetime'][v_end][:10]}  ({v_end-t_end}根)")
    print(f"   测试集: {data['datetime'][v_end][:10]} → {data['datetime'][-1][:10]}  ({total-v_end}根)")

    print("\n⏳ 回测中...")
    train = backtest_segment(data, 210,   t_end, "训练集")
    val   = backtest_segment(data, t_end, v_end, "验证集")
    test  = backtest_segment(data, v_end, total, "测试集")

    print("\n" + "=" * 68)
    print("📈 回测结果 — v2.0 信号引擎")
    print("=" * 68)
    hdr = "{:<12} {:>5} {:>7} {:>8} {:>8} {:>9} {:>7} {:>7} {:>7}"
    print(hdr.format("段", "交易", "胜率", "多/空WR", "盈亏比", "收益%", "连亏", "回撤", "资金"))
    print("-" * 68)
    for r in [train, val, test]:
        if r['trades'] == 0:
            print(f"{r['label']:<12} {'无信号':>50}")
            continue
        print(hdr.format(
            r['label'],
            r['trades'],
            f"{r['win_rate']*100:.1f}%",
            f"{r['long_wr']*100:.0f}/{r['short_wr']*100:.0f}%",
            f"{r['rr']:.2f}:1",
            f"{r['return']:+.2f}%",
            f"{r['max_consec']}笔",
            f"{r['max_drawdown']:.1f}%",
            f"${r['capital']:,.0f}"
        ))
    print("-" * 68)

    # 综合判断
    avg_wr  = np.mean([r['win_rate'] for r in [train,val,test] if r['trades']>0])
    avg_rr  = np.mean([r['rr'] for r in [train,val,test] if r['trades']>0])
    all_pos = all(r['return'] >= 0 for r in [train,val,test])
    safe_dd = all(r['max_drawdown'] < 15 for r in [train,val,test])
    safe_cl = all(r['max_consec'] < 5 for r in [train,val,test])

    # 期望值公式
    expected = avg_wr * abs(np.mean([r['avg_win'] for r in [train,val,test] if r['trades']>0])) \
             - (1-avg_wr) * abs(np.mean([r['avg_loss'] for r in [train,val,test] if r['trades']>0]))

    print(f"\n📊 综合指标:")
    print(f"   平均胜率   : {avg_wr*100:.1f}%  (目标 ≥ 50%)")
    print(f"   平均盈亏比 : {avg_rr:.2f}:1   (目标 ≥ 2:1)")
    print(f"   期望值/笔  : {expected:+.3f}%")
    print(f"   三段都盈利 : {'✅' if all_pos else '❌'}")
    print(f"   回撤安全   : {'✅ <15%' if safe_dd else '⚠️  超限'}")
    print(f"   熔断安全   : {'✅ <5笔' if safe_cl else '⚠️  超限'}")

    if avg_wr >= 0.52 and avg_rr >= 1.8 and all_pos:
        verdict = "✅ 通过验证 — 可进入 Testnet 测试"
        next_step = "接入 Binance Testnet，72小时 Paper Trading"
    elif avg_wr >= 0.48 and avg_rr >= 1.5:
        verdict = "⚠️  基本通过 — 再优化 SHORT 策略"
        next_step = "优化 SHORT 入场条件，降低假信号"
    elif avg_wr >= 0.45:
        verdict = "🔄 接近通过 — 继续迭代"
        next_step = "分析亏损交易，调整过滤条件"
    else:
        verdict = "❌ 未通过 — 策略继续优化"
        next_step = "检查信号逻辑，考虑换信号源"

    print(f"\n🎯 判断: {verdict}")
    print(f"📋 下一步: {next_step}")

    # 保存报告
    report = {
        'version': 'v2.0_signal_engine',
        'date': datetime.now().isoformat(),
        'data_source': 'Binance Real API - 8760 bars',
        'total_klines': total,
        'funding_rate': fund,
        'results': {'train': {k:v for k,v in train.items() if k!='equity'},
                    'val':   {k:v for k,v in val.items()   if k!='equity'},
                    'test':  {k:v for k,v in test.items()  if k!='equity'}},
        'summary': {
            'avg_win_rate': avg_wr,
            'avg_rr': avg_rr,
            'expected_value': expected,
            'all_positive': all_pos,
            'verdict': verdict
        }
    }
    out = Path(__file__).parent.parent / "v2_validation_report.json"
    with open(out, 'w') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n💾 报告: {out.name}")
    print("=" * 68)
    return report

if __name__ == "__main__":
    run()
