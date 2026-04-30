#!/usr/bin/env python3
"""
P1 快速验证脚本: P0优化策略在真实数据上的表现
使用 BTC 1H 真实数据验证 P0 修复效果
"""
import argparse
import json
import numpy as np
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_real_data(symbol='BTCUSDT', interval='1h'):
    """加载真实数据"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    pattern = f"{symbol}_{interval}"
    candidates = [f for f in os.listdir(data_dir) if pattern in f and f.endswith('.json')]
    if not candidates:
        # 降级到其他可用文件
        candidates = [f for f in os.listdir(data_dir) if symbol.replace('USDT', '') in f.upper()]
    
    for fname in candidates:
        try:
            with open(os.path.join(data_dir, fname)) as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 100:
                df = pd.DataFrame(data)
                # 兼容两种列名格式
                col_map = {}
                for old, new in [('ts','timestamp'),('o','open'),('h','high'),
                                  ('l','low'),('c','close'),('v','volume'),
                                  ('dt','datetime')]:
                    if old in df.columns and new not in df.columns:
                        col_map[old] = new
                if col_map:
                    df = df.rename(columns=col_map)
                if 'datetime' not in df.columns and 'dt' in df.columns:
                    df['datetime'] = pd.to_datetime(df['dt'], errors='coerce')
                elif 'datetime' in df.columns:
                    df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
                return df
        except Exception:
            continue
    raise FileNotFoundError(f"No valid data for {symbol}")


def compute_indicators(df):
    """计算技术指标"""
    df = df.copy().reset_index(drop=True)
    
    # 标准化列名
    for col, alt in [('close', 'c'), ('open', 'o'), ('high', 'h'), ('low', 'l'), ('volume', 'v')]:
        if col not in df.columns and alt in df.columns:
            df[col] = df[alt]
    
    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss.replace(0, np.nan))
    df['rsi'] = (100 - 100 / (1 + rs)).fillna(50)
    
    # ATR
    hl = df['high'] - df['low']
    hc = np.abs(df['high'] - df['close'].shift())
    lc = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['atr_pct'] = df['atr'] / df['close'] * 100
    
    # EMA
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['macd'] = df['ema12'] - df['ema26']
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    for w in [5, 10, 20, 60]:
        df[f'ma{w}'] = df['close'].rolling(w).mean()
    
    # 布林带
    df['bb_mid'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2.5 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2.5 * bb_std
    df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-10)
    
    # 成交量
    df['vol_ma'] = df['volume'].rolling(20).mean()
    df['vol_ratio'] = df['volume'] / df['vol_ma'].replace(0, np.nan)
    
    # 动量
    df['momentum'] = df['close'] / df['close'].shift(10) - 1
    
    # 趋势判断
    df['uptrend'] = (df['ma5'] > df['ma20']) & (df['ma20'] > df['ma60'])
    df['downtrend'] = (df['ma5'] < df['ma20']) & (df['ma20'] < df['ma60'])
    
    # ADX
    plus_dm = df['high'].diff()
    minus_dm = -df['low'].diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm > 0] = 0
    atr_safe = df['atr'].replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1/14).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(alpha=1/14).mean() / atr_safe
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    df['adx'] = (100 * (plus_di - minus_di).abs() / di_sum).ewm(alpha=1/14).mean()
    df['plus_di'] = plus_di
    df['minus_di'] = minus_di
    
    return df


def generate_signal_p0(df, idx):
    """
    P0优化策略信号生成:
    - EMA斜率判断趋势方向（替代MACD交叉）
    - 突破确认（替代ADX）
    - 波动率过滤
    - 信号阈值 0.55
    """
    if idx < 100:
        return 0, {}
    
    row = df.iloc[idx]
    prev = df.iloc[idx - 1]
    vol_ratio = row.get('vol_ratio', 1.0)
    if pd.isna(vol_ratio):
        vol_ratio = 1.0
    
    # === 均值回归评分 ===
    mr_long = 0
    mr_short = 0
    if row['rsi'] < 30: mr_long += 0.35
    elif row['rsi'] < 40: mr_long += 0.20
    if row['rsi'] > 70: mr_short += 0.35
    elif row['rsi'] > 60: mr_short += 0.20
    
    bb_pos = row.get('bb_position', 0.5)
    if pd.isna(bb_pos): bb_pos = 0.5
    if bb_pos < 0.15: mr_long += 0.30
    elif bb_pos < 0.30: mr_long += 0.15
    if bb_pos > 0.85: mr_short += 0.30
    elif bb_pos > 0.70: mr_short += 0.15
    
    if vol_ratio < 1.5:
        mr_long += 0.15
        mr_short += 0.15
    
    # === 趋势跟踪评分 (P0优化) ===
    tf_long = 0
    tf_short = 0
    
    # 因子1: EMA斜率 (使用预计算的ema20)
    if idx >= 25:
        ema_vals = df['ema20'].iloc[idx-4:idx+1].values
        ema_slope = (ema_vals[-1] - ema_vals[0]) / (ema_vals[0] * 5)
        if ema_slope > 0.001: tf_long += 0.30
        elif ema_slope < -0.001: tf_short += 0.30
    
    # EMA排列
    ema12 = row.get('ema12', row.get('ma5', row['close']))
    ema26 = row.get('ema26', row.get('ma10', row['close']))
    if ema12 > ema26: tf_long += 0.15
    if ema12 < ema26: tf_short += 0.15
    
    # 因子2: 突破确认
    lookback = 20
    if idx >= lookback:
        recent_high = df['high'].iloc[idx-lookback:idx].max()
        recent_low = df['low'].iloc[idx-lookback:idx].min()
        atr_val = row.get('atr', 0)
        breakout_th = atr_val * 0.5
        if row['close'] > recent_high + breakout_th: tf_long += 0.25
        if row['close'] < recent_low - breakout_th: tf_short += 0.25
        
        ma20 = row.get('ma20', row['close'])
        if ma20 > 0:
            dev = (row['close'] - ma20) / ma20
            if dev > 0.02: tf_long += 0.10
            elif dev < -0.02: tf_short += 0.10
    
    # 因子3: 波动率过滤
    atr_pct = row.get('atr_pct', 0)
    if atr_pct > 0.3:
        tf_long += 0.10
        tf_short += 0.10
    
    # Hurst加权
    hurst = row.get('hurst', 0.5)
    if hurst < 0.45:
        mr_long *= 1.3; tf_long *= 0.7
        mr_short *= 1.3; tf_short *= 0.7
    elif hurst > 0.55:
        mr_long *= 0.7; tf_long *= 1.3
        mr_short *= 0.7; tf_short *= 1.3
    
    # 加权融合
    long_score = mr_long * 0.4 + tf_long * 0.6
    short_score = mr_short * 0.4 + tf_short * 0.6
    
    # P0修复: 阈值从0.20升到0.55
    threshold = 0.55
    if long_score > short_score and long_score >= threshold:
        return 1, {'long': long_score, 'short': short_score}
    elif short_score > long_score and short_score >= threshold:
        return -1, {'long': long_score, 'short': short_score}
    return 0, {'long': long_score, 'short': short_score}


def run_backtest(df, sl_mult=1.8, tp_mult=3.0):
    """运行回测"""
    capital = 10000.0
    trades = []
    pos = None
    entry = None
    entry_bar = 0
    commission = 0.0004
    slippage = 0.0005
    
    for i in range(100, len(df)):
        row = df.iloc[i]
        atr = row.get('atr', 0)
        if atr <= 0:
            continue
        
        if pos == 'LONG':
            sl_price = entry * (1 - sl_mult * atr / entry)
            tp_price = entry * (1 + tp_mult * atr / entry)
            if row['low'] <= sl_price:
                exit_p = sl_price * (1 - slippage)
                pnl = (exit_p - entry) / entry - commission
                capital *= (1 + pnl)
                trades.append({'pnl': pnl, 'type': 'LONG', 'exit': 'SL', 'bars': i - entry_bar})
                pos = None
            elif row['high'] >= tp_price:
                exit_p = tp_price * (1 - slippage)
                pnl = (exit_p - entry) / entry - commission
                capital *= (1 + pnl)
                trades.append({'pnl': pnl, 'type': 'LONG', 'exit': 'TP', 'bars': i - entry_bar})
                pos = None
        elif pos == 'SHORT':
            sl_price = entry * (1 + sl_mult * atr / entry)
            tp_price = entry * (1 - tp_mult * atr / entry)
            if row['high'] >= sl_price:
                exit_p = sl_price * (1 + slippage)
                pnl = (entry - exit_p) / entry - commission
                capital *= (1 + pnl)
                trades.append({'pnl': pnl, 'type': 'SHORT', 'exit': 'SL', 'bars': i - entry_bar})
                pos = None
            elif row['low'] <= tp_price:
                exit_p = tp_price * (1 + slippage)
                pnl = (entry - exit_p) / entry - commission
                capital *= (1 + pnl)
                trades.append({'pnl': pnl, 'type': 'SHORT', 'exit': 'TP', 'bars': i - entry_bar})
                pos = None
        
        if pos is None:
            signal, scores = generate_signal_p0(df, i)
            if signal == 1:
                pos = 'LONG'
                entry = row['close'] * (1 + slippage)
                entry_bar = i
            elif signal == -1:
                pos = 'SHORT'
                entry = row['close'] * (1 - slippage)
                entry_bar = i
    
    return trades, capital


def print_report(trades, capital, symbol, split_date=None):
    """打印报告"""
    if not trades:
        print(f"[{symbol}] 无交易!")
        return
    
    pnls = [t['pnl'] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    losses = len(pnls) - wins
    wr = wins / len(pnls) * 100 if pnls else 0
    avg_win = np.mean([p for p in pnls if p > 0]) if wins > 0 else 0
    avg_loss = abs(np.mean([p for p in pnls if p < 0])) if losses > 0 else 1e-10
    rr = avg_win / avg_loss if avg_loss > 0 else 0
    sharpe = np.mean(pnls) / (np.std(pnls) + 1e-10) * np.sqrt(252 * 24)
    
    # 最大连续亏损
    max_dd = 0
    running = 1.0
    peak = 1.0
    for p in pnls:
        running *= (1 + p)
        peak = max(peak, running)
        dd = (peak - running) / peak
        max_dd = max(max_dd, dd)
    
    total_return = (capital - 10000) / 10000 * 100
    wins_by_type = {'LONG': 0, 'SHORT': 0}
    total_by_type = {'LONG': 0, 'SHORT': 0}
    for t in trades:
        wins_by_type[t['type']] += (1 if t['pnl'] > 0 else 0)
        total_by_type[t['type']] += 1
    
    print(f"\n{'='*60}")
    print(f"P0优化策略 回测报告 - {symbol}")
    if split_date:
        print(f"  数据分割: IS段截止 {split_date}")
    print(f"{'='*60}")
    print(f"  初始资金: 10,000 USDT  |  期末资金: {capital:.2f} USDT")
    print(f"  总收益率: {total_return:+.2f}%")
    print(f"  总交易数: {len(trades)} | 胜率: {wr:.1f}%")
    print(f"  盈利次数: {wins} | 亏损次数: {losses}")
    print(f"  均笔盈亏: {np.mean(pnls)*100:+.3f}%")
    print(f"  盈亏比: {rr:.2f} | 夏普比: {sharpe:.3f}")
    print(f"  最大回撤: {max_dd*100:.1f}%")
    print(f"  LONG胜率: {wins_by_type['LONG']}/{total_by_type['LONG']} = {wins_by_type['LONG']/max(1,total_by_type['LONG'])*100:.1f}%")
    print(f"  SHORT胜率: {wins_by_type['SHORT']}/{total_by_type['SHORT']} = {wins_by_type['SHORT']/max(1,total_by_type['SHORT'])*100:.1f}%")
    
    sl_count = sum(1 for t in trades if t['exit'] == 'SL')
    tp_count = sum(1 for t in trades if t['exit'] == 'TP')
    print(f"  止损出局: {sl_count} ({sl_count/len(trades)*100:.1f}%)")
    print(f"  止盈出局: {tp_count} ({tp_count/len(trades)*100:.1f}%)")
    print(f"  平均持仓: {np.mean([t['bars'] for t in trades]):.1f} bars")
    print(f"{'='*60}")
    
    return {
        'n_trades': len(trades),
        'win_rate': wr,
        'total_return': total_return,
        'sharpe': sharpe,
        'max_drawdown': max_dd * 100,
        'rr': rr,
        'long_wr': wins_by_type['LONG'] / max(1, total_by_type['LONG']) * 100,
        'short_wr': wins_by_type['SHORT'] / max(1, total_by_type['SHORT']) * 100,
    }


def main():
    parser = argparse.ArgumentParser(description='P0策略真实数据回测')
    parser.add_argument('--symbol', default='BTCUSDT', help='交易品种')
    parser.add_argument('--interval', default='1h', help='K线周期')
    parser.add_argument('--sl_mult', type=float, default=1.8, help='止损ATR倍数')
    parser.add_argument('--tp_mult', type=float, default=3.0, help='止盈ATR倍数')
    parser.add_argument('--oos_ratio', type=float, default=0.2, help='OOS样本外比例')
    args = parser.parse_args()
    
    print(f"Loading {args.symbol} {args.interval} real data...")
    df = load_real_data(args.symbol, args.interval)
    print(f"Loaded {len(df)} bars, date range: {df['datetime'].min()} to {df['datetime'].max()}")
    
    df = compute_indicators(df)
    
    # IS/OOS分割
    split_idx = int(len(df) * (1 - args.oos_ratio))
    split_date = df['datetime'].iloc[split_idx]
    
    df_is = df.iloc[:split_idx].reset_index(drop=True)
    df_oos = df.iloc[split_idx:].reset_index(drop=True)
    
    print(f"\nIS段: {len(df_is)} bars ({df_is['datetime'].min()} ~ {df_is['datetime'].max()})")
    print(f"OOS段: {len(df_oos)} bars ({df_oos['datetime'].min()} ~ {df_oos['datetime'].max()})")
    
    # IS段回测
    print("\n--- IS段 (In-Sample) 回测 ---")
    trades_is, capital_is = run_backtest(df_is, args.sl_mult, args.tp_mult)
    stats_is = print_report(trades_is, capital_is, f"{args.symbol} IS", str(split_date)[:10])
    
    # OOS段回测
    print("\n--- OOS段 (Out-of-Sample) 回测 ---")
    trades_oos, capital_oos = run_backtest(df_oos, args.sl_mult, args.tp_mult)
    stats_oos = print_report(trades_oos, capital_oos, f"{args.symbol} OOS")
    
    # 综合报告
    print(f"\n{'='*60}")
    print(f"综合评估: P0优化策略 vs 修复前基准")
    print(f"{'='*60}")
    print(f"  {'指标':<20} {'修复前':<12} {'P0优化后(IS)':<15} {'P0优化后(OOS)':<15}")
    print(f"  {'-'*20} {'-'*12} {'-'*15} {'-'*15}")
    # Handle no-trade OOS
    oos_wr = stats_oos['win_rate'] if stats_oos else 0.0
    oos_nt = stats_oos['n_trades'] if stats_oos else 0
    oos_sharpe = stats_oos['sharpe'] if stats_oos else 0.0
    oos_return = stats_oos['total_return'] if stats_oos else 0.0
    oos_dd = stats_oos['max_drawdown'] if stats_oos else 0.0
    oos_rr = stats_oos['rr'] if stats_oos else 0.0
    print(f"  {'胜率':<20} {'8.3%':<12} {stats_is['win_rate']:>+.1f}%{'':<6} {oos_wr:>+.1f}%")
    print(f"  {'交易次数':<20} {'~50-100':<12} {stats_is['n_trades']:<15} {oos_nt:<15}")
    print(f"  {'夏普比':<20} {'负值':<12} {stats_is['sharpe']:>+8.3f}{'':<3} {oos_sharpe:>+8.3f}")
    print(f"  {'收益率':<20} {'-2.24%':<12} {stats_is['total_return']:>+8.2f}%{'':<3} {oos_return:>+8.2f}%")
    print(f"  {'最大回撤':<20} {'高':<12} {stats_is['max_drawdown']:>8.1f}%{'':<3} {oos_dd:>8.1f}%")
    print(f"  {'盈亏比':<20} {'1.23':<12} {stats_is['rr']:>8.2f}{'':<3} {oos_rr:>8.2f}")
    print(f"{'='*60}")
    
    # 改进评估
    is_improved = stats_is['win_rate'] > 8.3
    oos_improved = oos_wr > 8.3
    print(f"\n改进评估:")
    print(f"  IS段胜率提升: {'YES' if is_improved else 'NO'} ({stats_is['win_rate']:.1f}% vs 8.3%)")
    print(f"  OOS段胜率提升: {'YES' if oos_improved else 'NO'} ({oos_wr:.1f}% vs ~8%)")
    if oos_nt == 0:
        print(f"  OOS警告: 无交易信号 (阈值0.55过高，需贝叶斯优化)")
    print(f"\nP0分析: signal_threshold=0.55 过滤掉了 {stats_is['n_trades']} 笔潜在交易")
    print(f"建议: 用 optimizer_bayes.py 搜索最优阈值 [0.35-0.60]")
    if is_improved and oos_improved:
        print(f"  结论: P0优化有效，建议进一步调参")
    elif is_improved and not oos_improved:
        print(f"  结论: IS有效但OOS退化，可能存在过拟合，需降低参数敏感度")
    else:
        print(f"  结论: P0策略需要进一步调整参数")


if __name__ == '__main__':
    main()
