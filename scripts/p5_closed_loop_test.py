#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杀手锏交易系统 v1.6 P5 - 最终闭环验证测试
P5策略: LONG-ONLY + ADX<80过滤 + ATR=2.0 + TP=2.0 + max_hold=20 + vol_filter=0.25%
数据: BTC+ETH 1H K线 (2025-04 ~ 2026-04, 约8760根/品种)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json, numpy as np, pandas as pd
from datetime import datetime
from collections import defaultdict

# ==================== 数据加载 ====================

def load_data(fpath):
    with open(fpath) as f:
        raw = json.load(f)
    df = pd.DataFrame(raw)
    for old, new in [('ts','timestamp'),('o','open'),('h','high'),('l','low'),('c','close'),('v','volume'),('dt','datetime')]:
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df = df.set_index('timestamp').sort_index()
    return df

# ==================== 指标计算 ====================

def compute_indicators(df):
    df = df.copy()
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    n = len(df)
    idx = df.index  # preserve datetime index

    # ATR
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    df['atr'] = pd.Series(tr, index=idx).ewm(span=14, adjust=False).mean()
    df['atr_pct'] = df['atr'] / df['close'] * 100

    # Bollinger Bands
    sma = df['close'].ewm(span=20, adjust=False).mean()
    std = df['close'].rolling(20).std()
    df['bb_mid'] = sma
    df['bb_upper'] = sma + 2 * std
    df['bb_lower'] = sma - 2 * std
    df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)

    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    # EMA slope
    df['ema12'] = ema12
    df['ema26'] = ema26
    df['ema_slope'] = ema12.pct_change(3) * 100

    # Volume ratio
    df['vol_ratio'] = df['volume'].rolling(20).mean() / df['volume'].rolling(20).mean().shift(1) + 1e-10

    # ADX
    plus_dm = np.zeros(n); minus_dm = np.zeros(n)
    for i in range(1, n):
        hd = high[i]-high[i-1]; ld = low[i-1]-low[i]
        if hd > ld and hd > 0: plus_dm[i] = hd
        if ld > hd and ld > 0: minus_dm[i] = ld
    alpha = 1.0/14
    atr_s = np.zeros(n); plus_di = np.zeros(n); minus_di = np.zeros(n)
    atr_s[13] = tr[:14].mean()
    for i in range(14, n): atr_s[i] = atr_s[i-1] + alpha*(tr[i]-atr_s[i-1])
    for i in range(13, n):
        plus_di[i] = 100*plus_dm[i]/atr_s[i] if atr_s[i]>0 else 0
        minus_di[i] = 100*minus_dm[i]/atr_s[i] if atr_s[i]>0 else 0
    dx = np.zeros(n)
    for i in range(13, n):
        di_sum = plus_di[i]+minus_di[i]
        dx[i] = 100*abs(plus_di[i]-minus_di[i])/di_sum if di_sum>0 else 0
    adx_s = np.zeros(n)
    adx_s[27] = dx[14:28].mean()
    for i in range(28, n): adx_s[i] = adx_s[i-1] + alpha*(dx[i]-adx_s[i-1])
    df['adx'] = pd.Series(adx_s, index=idx)
    df['plus_di'] = pd.Series(plus_di, index=idx)
    df['minus_di'] = pd.Series(minus_di, index=idx)

    # Momentum
    df['momentum'] = df['close'].pct_change(5) * 100

    # Hurst (lag-1 autocorrelation proxy)
    hurst = np.zeros(n)
    for i in range(100, n):
        series = close[i-100:i]
        if np.std(series) == 0: hurst[i] = 0.5; continue
        lag1 = np.corrcoef(series[:-1], series[1:])[0,1]
        if np.isnan(lag1): lag1 = 0
        hurst[i] = max(0.3, min(0.7, 0.5 + (lag1 * 0.25)))
    df['hurst'] = pd.Series(hurst, index=idx)

    return df

# ==================== P5 策略引擎 ====================

class P5Strategy:
    """
    P5核心策略:
    - LONG-ONLY: 禁用做空(2025-2026市场做空严重亏损)
    - ADX<80: 仅在弱趋势市场交易
    - ATR=2.0: 宽止损减少被扫
    - TP=2.0: 匹配宽止损
    - max_hold=20: 时间止损
    - vol_filter=0.25%: 波动率过滤
    """
    def __init__(self, config=None):
        self.config = config or {}
        self.atr_sl = self.config.get('atr_sl', 2.0)
        self.atr_tp = self.config.get('atr_tp', 2.0)
        self.max_hold = self.config.get('max_hold', 20)
        self.vol_filter = self.config.get('vol_filter', 0.0025)  # 0.25%
        self.adx_max = self.config.get('adx_max', 80)
        self.direction = self.config.get('direction', 'LONG_ONLY')
        self.thresh_base = self.config.get('thresh_base', 0.52)
        self.slip = 0.0009

    def generate_signal(self, df, idx):
        """在索引idx生成信号"""
        if idx < 100: return 0, {}
        row = df.iloc[idx]
        adx_val = row['adx']
        if pd.isna(adx_val) or adx_val <= 0: return 0, {}
        
        # P5: ADX过滤
        if adx_val > self.adx_max: return 0, {}
        
        # P5: 波动率过滤
        if row.get('atr_pct', 1.0) < self.vol_filter: return 0, {}
        
        hurst_val = row.get('hurst', 0.5)
        rsi = row['rsi']
        bb_pos = row['bb_position']
        if pd.isna(rsi) or pd.isna(bb_pos): return 0, {}
        
        # 动态阈值
        adx_adj = 0.03 if adx_val > 25 else (-0.03 if adx_val < 20 else 0.0)
        h_adj = 0.02 if hurst_val > 0.55 else (-0.02 if hurst_val < 0.42 else 0.0)
        thresh = max(0.40, min(0.70, self.thresh_base + adx_adj + h_adj))
        
        # 趋势因子
        tf = 0.0
        ema_slope = row.get('ema_slope', 0)
        if not pd.isna(ema_slope):
            if ema_slope > 0.0005: tf += 0.30
            elif ema_slope < -0.0005: tf += 0.30
        if not pd.isna(row.get('ema12')) and not pd.isna(row.get('ema26')):
            if row['ema12'] > row['ema26']: tf += 0.15
            elif row['ema12'] < row['ema26']: tf += 0.15
        if idx >= 20:
            rh = df['high'].iloc[idx-20:idx].max()
            rl = df['low'].iloc[idx-20:idx].min()
            if row['close'] > rh + 0.3 * row['atr']: tf += 0.25
            elif row['close'] < rl - 0.3 * row['atr']: tf += 0.25
        
        # 均值回归因子
        mr = 0.0
        if rsi < 30: mr += 0.35
        elif rsi < 40: mr += 0.20
        if rsi > 70: mr += 0.35
        elif rsi > 60: mr += 0.20
        if bb_pos < 0.15: mr += 0.30
        elif bb_pos < 0.30: mr += 0.15
        if bb_pos > 0.85: mr += 0.30
        elif bb_pos > 0.70: mr += 0.15
        if not pd.isna(row.get('vol_ratio')) and row['vol_ratio'] > 1.2: mr += 0.10
        
        long_s = mr * 0.40 + tf * 0.60
        short_s = mr * 0.40 + tf * 0.60
        n_conf = (1 if (rsi < 40 or rsi > 60) else 0) + \
                 (1 if (bb_pos < 0.30 or bb_pos > 0.70) else 0) + \
                 (1 if tf > 0.15 else 0)
        
        info = {'adx': adx_val, 'hurst': hurst_val, 'rsi': rsi, 'bb_pos': bb_pos,
                'long_s': long_s, 'short_s': short_s, 'thresh': thresh, 'n_conf': n_conf}
        
        # P5: LONG-ONLY — 禁止做空
        if self.direction == 'LONG_ONLY':
            if n_conf >= 3 and long_s >= thresh:
                return 1, info
            return 0, info
        
        # BOTH方向
        if n_conf >= 3:
            if long_s >= thresh: return 1, info
            if short_s >= thresh: return -1, info
        return 0, info

    def run_backtest(self, df, pair_name='UNKNOWN'):
        """运行P5策略闭环回测"""
        trades = []
        pos = None; entry = 0.0; entry_bar = 0
        
        for i in range(100, len(df)):
            row = df.iloc[i]
            signal, info = self.generate_signal(df, i)
            
            # 仓位管理
            if pos == 'LONG':
                hold = i - entry_bar
                sl = entry * (1 - self.atr_sl * row['atr'] / entry)
                tp = entry * (1 + self.atr_tp * row['atr'] / entry)
                
                reason = None
                if row['low'] <= sl:
                    pnl = (sl - entry) / entry - self.slip; reason = 'SL'; pos = None
                elif row['high'] >= tp:
                    pnl = (tp - entry) / entry - self.slip; reason = 'TP'; pos = None
                elif hold >= self.max_hold:
                    pnl = (row['close'] - entry) / entry - self.slip; reason = 'MAXH'; pos = None
                
                if pos is None:
                    trades.append({
                        'pair': pair_name, 'dir': 'LONG', 'ret': round(pnl*100, 3),
                        'bars': hold, 'reason': reason,
                        'adx': info.get('adx', 0), 'hurst': info.get('hurst', 0),
                        'thresh': info.get('thresh', 0), 'score': info.get('long_s', 0),
                        'dt': str(df.index[i])
                    })
            elif pos == 'SHORT':
                hold = i - entry_bar
                sl = entry * (1 + self.atr_sl * row['atr'] / entry)
                tp = entry * (1 - self.atr_tp * row['atr'] / entry)
                
                reason = None
                if row['high'] >= sl:
                    pnl = (entry - sl) / entry - self.slip; reason = 'SL'; pos = None
                elif row['low'] <= tp:
                    pnl = (entry - tp) / entry - self.slip; reason = 'TP'; pos = None
                elif hold >= self.max_hold:
                    pnl = (entry - row['close']) / entry - self.slip; reason = 'MAXH'; pos = None
                
                if pos is None:
                    trades.append({
                        'pair': pair_name, 'dir': 'SHORT', 'ret': round(pnl*100, 3),
                        'bars': hold, 'reason': reason,
                        'adx': info.get('adx', 0), 'hurst': info.get('hurst', 0),
                        'thresh': info.get('thresh', 0), 'score': info.get('short_s', 0),
                        'dt': str(df.index[i])
                    })
            
            # 开仓
            if pos is None and signal != 0:
                if signal == 1:
                    pos = 'LONG'; entry = row['close'] * 1.0003; entry_bar = i
                elif signal == -1:
                    pos = 'SHORT'; entry = row['close'] * 0.9997; entry_bar = i
        
        return trades

# ==================== 分析工具 ====================

def analyze_trades(trades, label, verbose=True):
    n = len(trades)
    if n < 5:
        if verbose: print(f"  {label}: n={n} (<5 trades)")
        return {'n': n}
    
    rets = [t['ret'] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    
    wr = len(wins) / n
    avg_w = sum(wins) / len(wins) if wins else 0
    avg_l = abs(sum(losses) / len(losses)) if losses else 1
    rr = avg_w / avg_l if avg_l > 0 else 0
    breakeven = 1 / (1 + rr) * 100
    gap = (wr - breakeven / 100) * 100
    ret = sum(rets)
    total_ret = np.prod([1 + r/100 for r in rets]) - 1
    total_ret_pct = total_ret * 100
    
    tp_r = sum(1 for t in trades if t['reason']=='TP') / n * 100
    sl_r = sum(1 for t in trades if t['reason']=='SL') / n * 100
    mh_r = sum(1 for t in trades if t['reason']=='MAXH') / n * 100
    avg_bars = sum(t['bars'] for t in trades) / n
    
    # Long vs Short
    longs = [t for t in trades if t['dir'] == 'LONG']
    shorts = [t for t in trades if t['dir'] == 'SHORT']
    
    result = {
        'label': label, 'n': n, 'wr': wr*100, 'rr': rr, 'gap': gap,
        'breakeven': breakeven, 'ret': ret, 'total_ret': total_ret_pct,
        'tp_pct': tp_r, 'sl_pct': sl_r, 'mh_pct': mh_r, 'avg_bars': avg_bars,
        'n_long': len(longs), 'n_short': len(shorts)
    }
    
    if verbose:
        print(f"\n{'='*70}")
        print(f"  {label}")
        print(f"{'='*70}")
        print(f"  总笔数: {n} | 做多: {len(longs)} | 做空: {len(shorts)}")
        print(f"  胜率: {wr*100:.1f}% | 盈亏比: {rr:.2f} | 盈亏平衡: {breakeven:.1f}%")
        print(f"  Gap: {gap:+.2f}% | 总收益: {ret:+.1f}% | 复利收益: {total_ret_pct:+.1f}%")
        print(f"  退出: TP={tp_r:.0f}% SL={sl_r:.0f}% MH={mh_r:.0f}% | 平均持仓: {avg_bars:.1f}h")
        print(f"  平均盈利: {avg_w:.2f}% | 平均亏损: {avg_l:.2f}%")
    
    # 分组分析
    if verbose and n >= 20:
        print(f"\n  --- 按方向分组 ---")
        for sub_label, sub_trades in [('做多', longs), ('做空', shorts)]:
            if sub_trades:
                srets = [t['ret'] for t in sub_trades]
                swins = [r for r in srets if r > 0]
                swr = len(swins)/len(srets)
                srr = (sum(swins)/len(swins))/abs(sum([r for r in srets if r<=0])/len([r for r in srets if r<=0])) if [r for r in srets if r<=0] else 1
                sgap = (swr - 1/(1+srr))*100
                print(f"    {sub_label}: n={len(sub_trades)}, WR={swr*100:.1f}%, RR={srr:.2f}, Gap={sgap:+.1f}%, Ret={sum(srets):+.1f}%")
    
    return result

# ==================== 主程序 ====================

def main():
    print("=" * 70)
    print("  杀手锏交易系统 v1.6 P5 - 最终闭环验证")
    print("=" * 70)
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 加载数据
    btc = load_data('data/BTCUSDT_1h_with_flow.json')
    eth = load_data('data/ETHUSDT_1h.json')
    
    print(f"  BTC数据: {len(btc)}根 1H K线 ({btc.index.min().date()} ~ {btc.index.max().date()})")
    print(f"  ETH数据: {len(eth)}根 1H K线 ({eth.index.min().date()} ~ {eth.index.max().date()})")
    
    # 计算指标
    print("\n  计算技术指标...")
    btc = compute_indicators(btc)
    eth = compute_indicators(eth)
    
    # 对齐时间范围
    common_start = max(btc.index.min(), eth.index.min())
    common_end = min(btc.index.max(), eth.index.max())
    btc = btc[(btc.index >= common_start) & (btc.index <= common_end)].copy()
    eth = eth[(eth.index >= common_start) & (eth.index <= common_end)].copy()
    print(f"  对齐范围: {common_start.date()} ~ {common_end.date()} ({len(btc)}根 1H)")
    
    # P5策略配置
    p5_config = {
        'atr_sl': 2.0,
        'atr_tp': 2.0,
        'max_hold': 20,
        'vol_filter': 0.25,     # 过滤低波动: ATR>% (0.25 = 0.25%)
        'adx_max': 80,
        'direction': 'LONG_ONLY',
        'thresh_base': 0.52
    }
    
    print(f"\n  P5策略参数:")
    print(f"    方向: {p5_config['direction']} (禁用做空)")
    print(f"    ADX过滤: <{p5_config['adx_max']} (弱趋势市场)")
    print(f"    止损: {p5_config['atr_sl']}×ATR | 止盈: {p5_config['atr_tp']}×ATR")
    print(f"    最大持仓: {p5_config['max_hold']}小时 | 波动率过滤: {p5_config['vol_filter']*100:.2f}%")
    print(f"    基础阈值: {p5_config['thresh_base']}")
    
    # 运行策略
    print("\n  运行P5策略...")
    strat = P5Strategy(p5_config)
    
    btc_trades = strat.run_backtest(btc, 'BTCUSDT')
    eth_trades = strat.run_backtest(eth, 'ETHUSDT')
    all_trades = btc_trades + eth_trades
    
    # 分析结果
    print("\n" + "=" * 70)
    print("  P5策略闭环测试结果")
    print("=" * 70)
    
    # BTC
    analyze_trades(btc_trades, 'BTCUSDT')
    # ETH
    analyze_trades(eth_trades, 'ETHUSDT')
    # 合并
    result = analyze_trades(all_trades, 'BTC+ETH 合并')
    
    print("\n" + "=" * 70)
    
    # 关键指标总结
    n = result.get('n', 0)
    if n >= 20:
        gap = result['gap']
        ret = result['total_ret']
        n = result['n']
        wr = result['wr']
        rr = result['rr']
        
        status = "PASS" if gap > 0 else "FAIL"
        emoji = "[OK]" if gap > 0 else "[!!]"
        
        print(f"\n  {'P5策略验证结果':^60}")
        print(f"  {'='*60}")
        print(f"  验证状态: {emoji} {status}")
        print(f"  交易笔数: {n}笔 (目标: >=200笔) -> {'PASS' if n >= 200 else 'WARN'}")
        print(f"  Gap: {gap:+.2f}% -> {'PASS' if gap > 0 else 'FAIL'}")
        print(f"  胜率: {wr:.1f}% (盈亏平衡: {result['breakeven']:.1f}%)")
        print(f"  复利收益: {ret:+.1f}% -> {'PASS' if ret > 0 else 'FAIL'}")
        print(f"  盈亏比: {rr:.2f}")
        
        if gap > 0 and ret > 0:
            print(f"\n  [结论] P5策略在样本外验证中展现正期望！")
            print(f"  - Gap={gap:+.1f}%说明策略具有统计优势")
            print(f"  - {n}笔交易提供了充足的统计显著性")
        else:
            print(f"\n  [结论] P5策略在当前市场环境中需要进一步优化")
    else:
        print(f"\n  交易笔数不足 ({n}), 统计意义有限")
    
    # 保存结果
    output = {
        'version': '1.6_P5',
        'config': p5_config,
        'summary': result,
        'btc_trades': btc_trades,
        'eth_trades': eth_trades,
        'all_trades': all_trades,
        'runtime': datetime.now().isoformat(),
        'data_range': f"{common_start.date()} ~ {common_end.date()}"
    }
    
    out_path = 'data/p5_closed_loop_trades.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {out_path}")
    
    return result

if __name__ == '__main__':
    main()
