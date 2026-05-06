#!/usr/bin/env python3
import json, numpy as np, pandas as pd
from datetime import datetime
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

@dataclass
class Signal:
    dir: str
    tf: str
    price: float
    sl: float
    tp: float
    conf: float

class Indicators:
    @staticmethod
    def ema(s, n): return s.ewm(span=n, adjust=False).mean()
    @staticmethod
    def rsi(s, n=14):
        delta = s.diff()
        up, down = delta.clip(lower=0), -delta.clip(upper=0)
        gain, loss = up.rolling(n).mean(), down.rolling(n).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))
    @staticmethod
    def bb(close, n=20, k=2):
        mid = close.rolling(n).mean()
        std = close.rolling(n).std()
        return (close - (mid - k*std)) / (2*k*std)
    @staticmethod
    def macd_hist(close):
        ema_f = close.ewm(span=12, adjust=False).mean()
        ema_s = close.ewm(span=26, adjust=False).mean()
        macd = ema_f - ema_s
        signal = macd.ewm(span=9, adjust=False).mean()
        return macd - signal

class Scanner:
    CFG = {
        'rsi_os': 30, 'rsi_ob': 70, 'rsi_exit': 40,
        'bb_long': 0.3, 'bb_short': 0.7,
        'vol_spike': 2.0, 'conf_th': 0.60,
        'sl_pct': 0.008, 'tp_pct': 0.004,
        'timeout_sec': 600,
        'ema_trend_filter': True,
    }
    def _features(self, df):
        df = df.copy()
        df['ema_f'] = Indicators.ema(df['close'], 20)
        df['ema_s'] = Indicators.ema(df['close'], 50)
        df['rsi'] = Indicators.rsi(df['close'], 14)
        df['bb_pct'] = Indicators.bb(df['close'], 20, 2)
        df['vol_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
        df['macd_h'] = Indicators.macd_hist(df['close'])
        return df
    def get_signal(self, df, tf):
        if len(df) < 50: return Signal('HOLD', tf, 0, 0, 0, 0)
        feat = self._features(df)
        last, prev = feat.iloc[-1], feat.iloc[-2]
        price = last['close']
        # EMA 趋势过滤
        ema_up = last['ema_f'] > last['ema_s']
        ema_down = last['ema_f'] < last['ema_s']
        long = 0.0
        if last['rsi'] < self.CFG['rsi_os']: long += 0.25
        elif last['rsi'] < self.CFG['rsi_exit']: long += 0.15
        if last['bb_pct'] < self.CFG['bb_long']: long += 0.25
        if last['vol_ratio'] > self.CFG['vol_spike']: long += 0.20
        if prev['macd_h'] < 0 and last['macd_h'] > 0: long += 0.20
        if self.CFG.get('ema_trend_filter') and not ema_up: long = 0
        short = 0.0
        if last['rsi'] > self.CFG['rsi_ob']: short += 0.25
        elif last['rsi'] > 100 - self.CFG['rsi_exit']: short += 0.15
        if last['bb_pct'] > self.CFG['bb_short']: short += 0.25
        if last['vol_ratio'] > self.CFG['vol_spike']: short += 0.20
        if prev['macd_h'] > 0 and last['macd_h'] < 0: short += 0.20
        if self.CFG.get('ema_trend_filter') and not ema_down: short = 0
        if long >= self.CFG['conf_th'] and long >= short:
            return Signal('LONG', tf, price, price*(1-self.CFG['sl_pct']), price*(1+self.CFG['tp_pct']), long)
        if short >= self.CFG['conf_th']:
            return Signal('SHORT', tf, price, price*(1+self.CFG['sl_pct']), price*(1-self.CFG['tp_pct']), short)
        return Signal('HOLD', tf, 0, 0, 0, 0)

def backtest(df_1m, scanner, capital=10000.0):
    pos, trades, equity = None, [], [capital]
    tf_data = {}
    for tf in ['3m','5m','10m','15m','30m']:
        minutes = int(tf[:-1])
        tf_data[tf] = df_1m.resample(f'{minutes}min').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    all_times = sorted(set().union(*[tf_data[tf].index for tf in tf_data]))
    for t in all_times:
        best_sig = None
        for tf, df_tf in tf_data.items():
            if t not in df_tf.index: continue
            loc = df_tf.index.get_loc(t)
            if loc >= 20:
                sig = scanner.get_signal(df_tf.iloc[:loc+1], tf)
                if sig.dir != 'HOLD' and (best_sig is None or sig.conf > best_sig.conf):
                    best_sig = sig
        if pos:
            price = df_1m.loc[t]['close'] if t in df_1m.index else None
            if price:
                exit_reason = None
                if pos['dir']=='LONG':
                    if price <= pos['sl']: exit_reason='SL'
                    elif price >= pos['tp']: exit_reason='TP'
                else:
                    if price >= pos['sl']: exit_reason='SL'
                    elif price <= pos['tp']: exit_reason='TP'
                if not exit_reason and (t-pos['time']).total_seconds()>scanner.CFG.get('timeout_sec',600): exit_reason='TIMEOUT'
                if exit_reason:
                    pnl = (price-pos['entry'])/pos['entry']*100 if pos['dir']=='LONG' else (pos['entry']-price)/pos['entry']*100
                    capital *= (1+pnl/100)
                    trades.append({'dir':pos['dir'],'pnl':pnl,'exit':exit_reason,'tf':pos['tf']})
                    pos = None
                    equity.append(capital)
        if not pos and best_sig:
            pos = {'dir':best_sig.dir,'entry':best_sig.price,'sl':best_sig.sl,'tp':best_sig.tp,'time':t,'tf':best_sig.tf}
        capital -= capital * 0.0009
        equity.append(capital)
    if pos:
        final_price = df_1m['close'].iloc[-1]
        pnl = (final_price-pos['entry'])/pos['entry']*100 if pos['dir']=='LONG' else (pos['entry']-final_price)/pos['entry']*100
        capital *= (1+pnl/100)
        trades.append({'dir':pos['dir'],'pnl':pnl,'exit':'FORCED','tf':pos['tf']})
        equity.append(capital)
    wr = len([t for t in trades if t['pnl']>0])/len(trades)*100 if trades else 0
    returns = pd.Series(equity).pct_change().dropna()
    sharpe = np.sqrt(365*1440)*returns.mean()/returns.std() if returns.std() else 0
    dd = (np.maximum.accumulate(equity)-equity).max()/max(equity)*100 if max(equity)>0 else 0
    avg_win = np.mean([t['pnl'] for t in trades if t['pnl']>0]) if [t for t in trades if t['pnl']>0] else 0
    avg_loss = np.mean([t['pnl'] for t in trades if t['pnl']<=0]) if [t for t in trades if t['pnl']<=0] else 0
    return {'trades':len(trades),'win_rate':wr,'return':(capital-10000)/10000*100,'max_dd':dd,'sharpe':sharpe,'avg_win':avg_win,'avg_loss':avg_loss,'trades_detail':trades}

if __name__ == '__main__':
    print("加载 BTC 真实数据...")
    with open('btc_1m.json') as f: data = json.load(f)
    df = pd.DataFrame(data, columns=['ts','open','high','low','close','volume','close_time','quote_vol','trades','taker_buy_vol','taker_buy_quote','ignore'])
    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
    df.index = pd.to_datetime(df['ts'], unit='ms')
    print(f"数据范围：{df.index[0]} ~ {df.index[-1]} | K 线数：{len(df)}")
    scanner = Scanner()
    result = backtest(df, scanner)
    print(f"\n【回测结果】")
    print(f"交易次数：{result['trades']}")
    print(f"胜率：{result['win_rate']:.1f}%")
    print(f"总收益：{result['return']:.2f}%")
    print(f"最大回撤：{result['max_dd']:.2f}%")
    print(f"平均盈利：{result['avg_win']:.3f}%")
    print(f"平均亏损：{result['avg_loss']:.3f}%")
    print(f"盈亏比：{abs(result['avg_win']/result['avg_loss']):.2f}" if result['avg_loss']!=0 else "N/A")
    exit_dist = {}
    for t in result['trades_detail']: exit_dist[t['exit']] = exit_dist.get(t['exit'],0)+1
    print(f"【出场原因】{exit_dist}")
