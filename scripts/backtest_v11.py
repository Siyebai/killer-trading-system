"""
backtest_v11.py - OFI+VWAP+Wyckoff策略回测
"""
import json, sys
import numpy as np
import pandas as pd
sys.path.insert(0, '/root/.openclaw/workspace/killer-trading-system/scripts')
from signal_engine_v11_ofi_vwap import (
    calculate_vwap, calculate_vwap_bands, calculate_ofi,
    detect_wyckoff_spring, detect_wyckoff_utad, calculate_atr,
    generate_signal
)

# 加载BTC 1h数据
with open('/root/.openclaw/workspace/killer-trading-system/data/BTCUSDT_1h_futures.json') as f:
    raw = json.load(f)

df = pd.DataFrame(raw, columns=['ts','open','high','low','close','volume','close_time','qav','trades','tbav','tqav','ignore'])
df = df.astype({'open':float,'high':float,'low':float,'close':float,'volume':float})
df = df.reset_index(drop=True)
print(f'数据量: {len(df)} 根 1h K线')

# 计算所有指标
vwap = calculate_vwap(df)
vwap_upper, vwap_lower, vwap_std = calculate_vwap_bands(df, vwap)
nofi = calculate_ofi(df)
support = df['low'].rolling(20).min()
resistance = df['high'].rolling(20).max()
springs = detect_wyckoff_spring(df, support)
utads = detect_wyckoff_utad(df, resistance)
atr_series = calculate_atr(df)
vwap_dev = (df['close'] - vwap) / (vwap_std + 1e-8)

print(f'Spring信号数: {springs.sum()}')
print(f'UTAD信号数: {utads.sum()}')
print(f'VWAP超买(>1.8σ)数: {(vwap_dev > 1.8).sum()}')
print(f'VWAP超卖(<-1.8σ)数: {(vwap_dev < -1.8).sum()}')

# 回测逻辑
trades = []
in_trade = False
entry_bar = 0

for i in range(50, len(df) - 20):
    if in_trade:
        continue
    
    close = df['close'].iloc[i]
    atr = atr_series.iloc[i]
    
    # 策略1: Spring做多
    if springs.iloc[i] and nofi.iloc[i] > 0.1:
        sl = close - 2.0 * atr
        tp = close + 3.5 * atr
        # 向前查找结果
        for j in range(i+1, min(i+25, len(df))):
            p = df['close'].iloc[j]
            if p >= tp:
                trades.append({'strategy':'spring_long','result':'TP','bars':j-i,'pnl_r':3.5})
                break
            if p <= sl:
                trades.append({'strategy':'spring_long','result':'SL','bars':j-i,'pnl_r':-1.0})
                break
        else:
            trades.append({'strategy':'spring_long','result':'TIME','bars':24,'pnl_r':0.0})
    
    # 策略2: UTAD做空
    elif utads.iloc[i] and nofi.iloc[i] < -0.1:
        sl = close + 2.0 * atr
        tp = close - 3.5 * atr
        for j in range(i+1, min(i+25, len(df))):
            p = df['close'].iloc[j]
            if p <= tp:
                trades.append({'strategy':'utad_short','result':'TP','bars':j-i,'pnl_r':3.5})
                break
            if p >= sl:
                trades.append({'strategy':'utad_short','result':'SL','bars':j-i,'pnl_r':-1.0})
                break
        else:
            trades.append({'strategy':'utad_short','result':'TIME','bars':24,'pnl_r':0.0})
    
    # 策略3: VWAP超买做空
    elif vwap_dev.iloc[i] > 1.8 and nofi.iloc[i] < -0.05:
        sl = close + 1.5 * atr
        tp_price = vwap.iloc[i]
        tp_r = abs(tp_price - close) / (1.5 * atr) if atr > 0 else 1.5
        for j in range(i+1, min(i+25, len(df))):
            p = df['close'].iloc[j]
            if p <= tp_price:
                trades.append({'strategy':'vwap_short','result':'TP','bars':j-i,'pnl_r':tp_r})
                break
            if p >= sl:
                trades.append({'strategy':'vwap_short','result':'SL','bars':j-i,'pnl_r':-1.0})
                break
        else:
            trades.append({'strategy':'vwap_short','result':'TIME','bars':24,'pnl_r':0.0})
    
    # 策略4: VWAP超卖做多
    elif vwap_dev.iloc[i] < -1.8 and nofi.iloc[i] > 0.05:
        sl = close - 1.5 * atr
        tp_price = vwap.iloc[i]
        tp_r = abs(tp_price - close) / (1.5 * atr) if atr > 0 else 1.5
        for j in range(i+1, min(i+25, len(df))):
            p = df['close'].iloc[j]
            if p >= tp_price:
                trades.append({'strategy':'vwap_long','result':'TP','bars':j-i,'pnl_r':tp_r})
                break
            if p <= sl:
                trades.append({'strategy':'vwap_long','result':'SL','bars':j-i,'pnl_r':-1.0})
                break
        else:
            trades.append({'strategy':'vwap_long','result':'TIME','bars':24,'pnl_r':0.0})

# 统计
print(f'\n=== 回测结果（BTC 1H，8760根，全样本）===')
print(f'总交易: {len(trades)}')

if trades:
    tdf = pd.DataFrame(trades)
    wins = tdf[tdf['pnl_r'] > 0]
    losses = tdf[tdf['pnl_r'] < 0]
    wr = len(wins) / len(tdf) * 100
    avg_win = wins['pnl_r'].mean() if len(wins) > 0 else 0
    avg_loss = abs(losses['pnl_r'].mean()) if len(losses) > 0 else 0
    rr = avg_win / avg_loss if avg_loss > 0 else 0
    ev = wr/100 * avg_win - (1-wr/100) * avg_loss
    
    print(f'胜率: {wr:.1f}%')
    print(f'平均盈利: +{avg_win:.2f}R | 平均亏损: -{avg_loss:.2f}R')
    print(f'盈亏比: {rr:.2f}')
    print(f'期望值: {ev:+.4f}R/笔')
    
    print('\n=== 分策略统计 ===')
    for strat in tdf['strategy'].unique():
        st = tdf[tdf['strategy']==strat]
        w = len(st[st['pnl_r']>0])
        print(f'{strat}: {len(st)}笔 WR={w/len(st)*100:.1f}% EV={st["pnl_r"].mean():+.3f}R')
    
    # 保存结果
    result = {
        'strategy': 'v11_ofi_vwap_wyckoff',
        'total_trades': len(trades),
        'win_rate': wr,
        'avg_win_r': avg_win,
        'avg_loss_r': avg_loss,
        'rr': rr,
        'ev_per_trade': ev,
        'by_strategy': {
            s: {
                'count': len(tdf[tdf['strategy']==s]),
                'wr': len(tdf[(tdf['strategy']==s)&(tdf['pnl_r']>0)])/len(tdf[tdf['strategy']==s])*100 if len(tdf[tdf['strategy']==s])>0 else 0,
                'ev': tdf[tdf['strategy']==s]['pnl_r'].mean()
            }
            for s in tdf['strategy'].unique()
        }
    }
    with open('/root/.openclaw/workspace/killer-trading-system/v11_backtest.json', 'w') as f:
        json.dump(result, f, indent=2)
    print('\n结果已保存: v11_backtest.json')
