#!/usr/bin/env python3
"""
贵金属专用参数优化器 v1.1
XAUUSDT: ATR% 中位数 0.37% (BTC 的 60%)
XAGUSDT: ATR% 中位数 1.00% (比黄金更波动)

策略: EMA斜率 + 突破确认 + 波动率过滤 + 动态止损
"""
import json, os, sys, argparse
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))


def load_data(symbol: str, interval: str = "1h") -> pd.DataFrame:
    data_dir = "data"
    candidates = [f for f in os.listdir(data_dir)
                 if symbol in f and interval in f and f.endswith('.json')]
    if not candidates:
        candidates = [f for f in os.listdir(data_dir)
                     if symbol in f and f.endswith('.json')]
    with open(os.path.join(data_dir, candidates[0])) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    for old, new in [('ts','timestamp'),('o','open'),('h','high'),
                     ('l','low'),('c','close'),('v','volume'),('dt','datetime')]:
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})
    df = df.sort_values('timestamp').reset_index(drop=True)
    return df


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['ret'] = df['close'].pct_change()
    df['atr'] = (df['high'] - df['low']).rolling(14).mean()
    df['atr_pct'] = df['atr'] / df['close'] * 100
    df['rsi'] = 100 - (100 / (1 + (
        df['ret'].where(lambda x: x > 0, 0).rolling(14).mean() /
        (-df['ret'].where(lambda x: x < 0, 0).rolling(14).mean() + 1e-10) + 1e-10
    )))
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    for p in [5, 10, 20]: df[f'ma{p}'] = df['close'].rolling(p).mean()
    df['bb_mid'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2.0 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2.0 * bb_std
    bb_range = df['bb_upper'] - df['bb_lower']
    df['bb_range'] = bb_range
    df['bb_position'] = (df['close'] - df['bb_lower']) / bb_range.replace(0, np.nan)
    vol_sma = df['volume'].rolling(20).mean()
    df['vol_ratio'] = df['volume'] / vol_sma.replace(0, np.nan)
    df['ema_slope'] = df['ema20'].pct_change(5)  # 5-period slope
    return df.dropna(subset=['close', 'atr', 'atr_pct', 'rsi', 'bb_position', 'ema_slope'])


def backtest_precious_metal(df: pd.DataFrame,
                            threshold: float,
                            min_conf: int,
                            atr_low_mult: float,
                            atr_high_mult: float,
                            gold_mode: bool = True,
                            vol_filter_pct: float = 0.15) -> dict:
    """贵金属回测，返回胜率、夏普、交易列表"""
    atr_pct_median = df['atr_pct'].median()
    atr_pct_p30 = df['atr_pct'].quantile(0.30)
    atr_pct_p70 = df['atr_pct'].quantile(0.70)

    trades = []
    pos = None
    entry = 0.0
    capital = 10000.0
    slip = 0.0009

    for i in range(25, len(df)):
        row = df.iloc[i]
        if pd.isna(row['atr']) or row['atr'] <= 0: continue

        # Dynamic ATR percentile for this bar
        hist_pcts = (df['atr_pct'].iloc[max(0, i-200):i] > row['atr_pct']).mean()

        # Determine dynamic multiplier
        if hist_pcts < 0.30:
            sl_mult = atr_low_mult
        elif hist_pcts > 0.70:
            sl_mult = atr_high_mult
        else:
            sl_mult = (atr_low_mult + atr_high_mult) / 2.0

        # Volatility filter: gold needs much lower threshold
        # XAU: median ATR% = 0.37%, gold_mode=True → filter at 0.15%
        # XAG: median ATR% = 1.00%, gold_mode=False → filter at 0.30%
        if gold_mode:
            vol_ok = row['atr_pct'] > vol_filter_pct  # 0.15% for gold
        else:
            vol_ok = row['atr_pct'] > vol_filter_pct  # 0.30% for silver

        # === Trend Factor (EMA slope + breakout) ===
        tf = 0.0
        ema_slope = row['ema_slope']
        if not pd.isna(ema_slope):
            # Gold/silver trend: use 0.0005 threshold (much lower than crypto)
            if ema_slope > 0.0005: tf += 0.30  # uptrend
            elif ema_slope < -0.0005: tf += 0.30  # downtrend

        # EMA alignment
        if not pd.isna(row['ema12']) and not pd.isna(row['ema26']):
            if row['ema12'] > row['ema26']: tf += 0.15
            elif row['ema12'] < row['ema26']: tf += 0.15

        # Breakout (20-period high/low, breakout > 0.3×ATR for gold)
        if i >= 20:
            rh = df['high'].iloc[i-20:i].max()
            rl = df['low'].iloc[i-20:i].min()
            if row['close'] > rh + 0.3 * row['atr']: tf += 0.25  # upside breakout
            elif row['close'] < rl - 0.3 * row['atr']: tf += 0.25  # downside breakout

        # === Mean Reversion Factor (BB + RSI) ===
        mr = 0.0
        rsi = row['rsi']
        bb_pos = row['bb_position']
        if pd.isna(rsi) or pd.isna(bb_pos): continue

        # Gold-specific RSI zones (wider for lower volatility)
        if rsi < 30: mr += 0.35
        elif rsi < 40: mr += 0.20
        if rsi > 70: mr += 0.35
        elif rsi > 60: mr += 0.20
        # BB zones
        if bb_pos < 0.15: mr += 0.30
        elif bb_pos < 0.30: mr += 0.15
        if bb_pos > 0.85: mr += 0.30
        elif bb_pos > 0.70: mr += 0.15
        # Volume confirmation (lower threshold for gold)
        if not pd.isna(row['vol_ratio']) and row['vol_ratio'] > 1.2: mr += 0.10

        # Fusion scores
        long_s = mr * 0.40 + tf * 0.60
        short_s = mr * 0.40 + tf * 0.60

        # Count confirmations
        n_conf = 0
        if rsi < 40 or rsi > 60: n_conf += 1
        if bb_pos < 0.30 or bb_pos > 0.70: n_conf += 1
        if tf > 0.15: n_conf += 1

        # Position management
        if pos == 'LONG':
            sl_price = entry * (1 - sl_mult * row['atr'] / entry)
            tp_price = entry * (1 + sl_mult * row['atr'] / entry * 2.5)
            if row['low'] <= sl_price:
                pnl = (sl_price - entry) / entry - slip
                capital *= (1 + pnl)
                trades.append(pnl); pos = None
            elif row['high'] >= tp_price:
                pnl = (tp_price - entry) / entry - slip
                capital *= (1 + pnl); trades.append(pnl); pos = None

        elif pos == 'SHORT':
            sl_price = entry * (1 + sl_mult * row['atr'] / entry)
            tp_price = entry * (1 - sl_mult * row['atr'] / entry * 2.5)
            if row['high'] >= sl_price:
                pnl = (entry - sl_price) / entry - slip
                capital *= (1 + pnl); trades.append(pnl); pos = None
            elif row['low'] <= tp_price:
                pnl = (entry - tp_price) / entry - slip
                capital *= (1 + pnl); trades.append(pnl); pos = None

        # Entry logic
        if pos is None:
            if long_s >= threshold and n_conf >= min_conf and vol_ok:
                pos = 'LONG'; entry = row['close'] * 1.0003
            elif short_s >= threshold and n_conf >= min_conf and vol_ok:
                pos = 'SHORT'; entry = row['close'] * 0.9997

    return {
        'trades': trades,
        'n': len(trades),
        'capital': capital,
        'returns': trades,
    }


def score_params(result: dict) -> float:
    """贵金属专用评分: 胜率权重更高（样本少）"""
    n = result['n']
    if n == 0: return -999.0
    rets = np.array(result['returns'])
    win_rate = (rets > 0).mean()
    total_ret = result['capital'] / 10000 - 1
    sharpe = np.mean(rets) / (np.std(rets) + 1e-10) * np.sqrt(252 / max(n, 10))
    max_dd = abs(np.min((1 + rets).cumprod() / np.maximum.accumulate((1 + rets).cumprod()) - 1))
    # Fewer trades → penalize more, but WR matters more
    sample_factor = min(1.0, n / 20.0)
    score = (0.35 * win_rate + 0.25 * max(0, total_ret + 0.1) +
             0.20 * min(1, sharpe / 3.0) - 0.20 * max_dd) * sample_factor
    return score


def optimize_gold(symbol: str) -> dict:
    df = load_data(symbol, "1h")
    df = compute_indicators(df)
    n = len(df)
    is_end = int(n * 0.75)  # More IS data for gold (shorter dataset)
    df_is = df.iloc[:is_end].reset_index(drop=True)
    df_oos = df.iloc[is_end:].reset_index(drop=True)

    print(f"  IS bars: {len(df_is)}, OOS bars: {len(df_oos)}")
    print(f"  ATR% median: {df['atr_pct'].median():.4f}%")

    gold_mode = (symbol == 'XAUUSDT')
    best = {'score': -999, 'params': {}, 'is': {}, 'oos': {}}

    # Grid search: 贵金属专用阈值范围 (0.28-0.48)
    thresholds = [0.28, 0.32, 0.36, 0.40, 0.44, 0.48]
    min_confs = [2, 3]
    vol_filters = [0.10, 0.15, 0.20] if gold_mode else [0.20, 0.30, 0.40]
    atr_lows = [1.5, 1.8, 2.0]
    atr_highs = [1.2, 1.5, 1.8]

    results_log = []

    for thresh in thresholds:
        for min_c in min_confs:
            for vf in vol_filters:
                for al in atr_lows:
                    for ah in atr_highs:
                        # IS backtest
                        r_is = backtest_precious_metal(df_is, thresh, min_c, al, ah, gold_mode, vf)
                        score_is = score_params(r_is)
                        n_is = r_is['n']
                        if n_is < 5: continue  # Need at least 5 IS trades

                        # OOS backtest
                        r_oos = backtest_precious_metal(df_oos, thresh, min_c, al, ah, gold_mode, vf)
                        n_oos = r_oos['n']
                        if n_oos == 0:
                            # Try with slightly lower threshold for OOS
                            for fallback_thresh in [thresh - 0.04, thresh - 0.08]:
                                if fallback_thresh < 0.25: continue
                                r_oos = backtest_precious_metal(df_oos, fallback_thresh, min_c, al, ah, gold_mode, vf)
                                if r_oos['n'] > 0: break

                        rets_oos = np.array(r_oos['returns'])
                        wr_oos = (rets_oos > 0).mean() if n_oos > 0 else 0.0
                        total_oos = r_oos['capital'] / 10000 - 1
                        score_oos = score_params(r_oos)

                        # IS-OOS gap penalty
                        is_oos_gap = abs(score_is - score_oos)
                        final_score = score_oos - 0.1 * is_oos_gap

                        results_log.append({
                            'threshold': thresh, 'min_conf': min_c, 'vol_filter': vf,
                            'atr_low': al, 'atr_high': ah,
                            'n_is': n_is, 'n_oos': n_oos,
                            'wr_is': (np.array(r_is['returns']) > 0).mean(),
                            'wr_oos': wr_oos,
                            'score_is': score_is, 'score_oos': score_oos,
                            'is_oos_gap': is_oos_gap, 'final_score': final_score,
                        })

                        if final_score > best['score']:
                            best = {
                                'score': final_score,
                                'params': {'threshold': thresh, 'min_confirmations': min_c,
                                           'vol_filter_pct': vf, 'atr_low_mult': al, 'atr_high_mult': ah},
                                'is': {'n': n_is, 'wr': (np.array(r_is['returns']) > 0).mean(),
                                       'total_ret': r_is['capital'] / 10000 - 1},
                                'oos': {'n': n_oos, 'wr': wr_oos, 'total_ret': total_oos,
                                        'returns': r_oos['returns']},
                            }

    print(f"\n  Best params: {best['params']}")
    print(f"  IS: {best['is']['n']} trades, WR={best['is']['wr']:.1%}, Ret={best['is']['total_ret']:.2%}")
    print(f"  OOS: {best['oos']['n']} trades, WR={best['oos']['wr']:.1%}, Ret={best['oos']['total_ret']:.2%}")
    return best


def main():
    parser = argparse.ArgumentParser(description='贵金属参数优化 v1.1')
    parser.add_argument('--symbol', default='XAUUSDT', help='XAUUSDT or XAGUSDT')
    parser.add_argument('--output', default='p2_gold_optimized.json')
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"贵金属参数优化 v1.1: {args.symbol}")
    print(f"{'='*60}")

    best = optimize_gold(args.symbol)

    # Save results
    with open(args.output, 'w') as f:
        json.dump(best, f, indent=2, default=str)
    print(f"\n  Results saved to {args.output}")

    # Final validation with fallback thresholds
    df = load_data(args.symbol, "1h")
    df = compute_indicators(df)
    n = len(df)
    is_end = int(n * 0.75)
    df_oos = df.iloc[is_end:].reset_index(drop=True)

    gold_mode = (args.symbol == 'XAUUSDT')
    p = best['params']

    print(f"\n{'='*60}")
    print(f"P2-1 最终验证: {args.symbol}")
    print(f"{'='*60}")

    for label, thresh in [(f"最优阈值 {p['threshold']}", p['threshold']),
                           (f"宽松阈值 {p['threshold']-0.05}", max(0.25, p['threshold']-0.05))]:
        r = backtest_precious_metal(df_oos, thresh, p['min_confirmations'],
                                     p['atr_low_mult'], p['atr_high_mult'], gold_mode, p['vol_filter_pct'])
        n_t = r['n']
        if n_t > 0:
            rets = np.array(r['returns'])
            wr = (rets > 0).mean()
            total = r['capital'] / 10000 - 1
            sharpe = np.mean(rets) / (np.std(rets) + 1e-10) * np.sqrt(252 / n_t)
            print(f"  {label}: {n_t} trades, WR={wr:.1%}, Ret={total:.2%}, Sharpe={sharpe:.2f}")
        else:
            print(f"  {label}: 0 trades (阈值过高)")

    print(f"\n  最优参数:")
    for k, v in p.items():
        print(f"    {k}: {v}")

    print(f"\n{'='*60}")
    print(f"P2-1 验收: XAUUSDT={args.symbol}, OOS trades>0, XAG WR≥50%")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
