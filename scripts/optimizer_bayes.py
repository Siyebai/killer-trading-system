#!/usr/bin/env python3
"""
贝叶斯优化参数调参框架 (Bayesian Optimization)
===============================================
v5.1 P0-4: 为关键参数引入BO调优框架

优先级: 信号引擎参数 > 市场状态机阈值 > 策略权重
方法: 高斯过程代理模型 + Expected Improvement采集函数
验证: 样本外验证(60/20/20)集成,防止过拟合

依赖: bayesian-optimization, numpy, pandas
"""

import argparse
import json
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')


class BayesianOptimizer:
    """贝叶斯优化器 - 交易系统参数自动调优"""

    def __init__(self, config_path='config.json', n_iter=30, init_points=5):
        self.config_path = config_path
        self.n_iter = n_iter
        self.init_points = init_points
        self.optimization_history = []
        self.best_params = {}
        self.best_score = -np.inf

    def _load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return self._default_config()

    def _default_config(self):
        """默认配置"""
        return {
            "system": {"version": "v5.1"},
            "strategy": {
                "v5_optimal_params": {
                    "rsi_oversold": 30, "rsi_overbought": 70,
                    "bb_std": 2.5, "bb_period": 20,
                    "sl_atr_multiplier": 1.5, "tp_atr_multiplier": 3.0
                }
            },
            "market_state_machine": {
                "adx_trend_threshold": 25,
                "adx_strong_threshold": 40,
                "vol_extreme_threshold": 0.05,
                "bb_extreme_threshold": 2.5,
                "ema_slope_threshold": 0.001
            },
            "risk_management": {
                "atr_multiplier_sl": 1.5,
                "atr_multiplier_tp": 3.0,
                "kelly_fraction": 0.5,
                "max_single_loss": 2.5
            }
        }

    def _save_config(self, config):
        """保存配置文件"""
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def _generate_backtest_data(self, n_bars=2000, seed=None):
        """生成回测数据"""
        if seed is not None:
            np.random.seed(seed)
        dates = pd.date_range('2024-01-01', periods=n_bars, freq='1h')
        noise = np.random.randn(n_bars) * 0.005
        trend = np.sin(np.arange(n_bars) / 200) * 0.002
        returns = noise + trend
        close = 100000 * np.exp(np.cumsum(returns))
        high = close * (1 + np.abs(np.random.randn(n_bars)) * 0.003)
        low = close * (1 - np.abs(np.random.randn(n_bars)) * 0.003)
        volume = np.random.randint(100, 1000, n_bars) * 1e6
        return pd.DataFrame({
            'timestamp': dates, 'open': close * 0.9999, 'high': high,
            'low': low, 'close': close, 'volume': volume
        })

    def _compute_indicators(self, df, params):
        """计算技术指标"""
        rsi_period = 14
        bb_period = int(params.get('bb_period', 20))
        bb_std = params.get('bb_std', 2.5)

        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
        rs = gain / (loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))

        df['bb_mid'] = df['close'].rolling(bb_period).mean()
        bb_vol = df['close'].rolling(bb_period).std()
        df['bb_upper'] = df['bb_mid'] + bb_std * bb_vol
        df['bb_lower'] = df['bb_mid'] - bb_std * bb_vol

        df['atr'] = (df['high'] - df['low']).rolling(14).mean()
        for p in [9, 21, 55]:
            df[f'ema_{p}'] = df['close'].ewm(span=p).mean()

        df['adx'] = self._compute_adx(df, 14)
        return df

    def _compute_adx(self, df, period=14):
        """计算ADX"""
        high_diff = df['high'].diff()
        low_diff = -df['low'].diff()
        plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
        minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - df['close'].shift()).abs(),
            (df['low'] - df['close'].shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        plus_di = 100 * pd.Series(plus_dm).rolling(period).mean() / (atr + 1e-10)
        minus_di = 100 * pd.Series(minus_dm).rolling(period).mean() / (atr + 1e-10)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
        return dx.rolling(period).mean()

    def _run_backtest(self, df, params):
        """运行单次回测"""
        rsi_os = params.get('rsi_oversold', 30)
        rsi_ob = params.get('rsi_overbought', 70)
        sl_mult = params.get('sl_atr_multiplier', 1.5)
        tp_mult = params.get('tp_atr_multiplier', 3.0)
        adx_trend = params.get('adx_trend_threshold', 25)
        bb_ext = params.get('bb_extreme_threshold', 2.5)
        commission = 0.001
        slippage = 0.0005

        trades = []
        position = None
        capital = 10000.0
        consecutive_losses = 0
        blocked_until = 0

        for i in range(100, len(df)):
            if i < blocked_until:
                continue
            row = df.iloc[i]
            if position is not None:
                if position['type'] == 'LONG':
                    sl_price = position['entry'] * (1 - sl_mult * row['atr'] / position['entry'])
                    tp_price = position['entry'] * (1 + tp_mult * row['atr'] / position['entry'])
                    if row['low'] <= sl_price:
                        exit_price = sl_price * (1 - slippage)
                        pnl = (exit_price - position['entry']) / position['entry']
                        capital *= (1 + pnl - commission)
                        if pnl < 0:
                            consecutive_losses += 1
                        else:
                            consecutive_losses = 0
                        trades.append({'pnl': pnl, 'type': 'LONG', 'exit': 'SL'})
                        position = None
                    elif row['high'] >= tp_price:
                        exit_price = tp_price * (1 - slippage)
                        pnl = (exit_price - position['entry']) / position['entry']
                        capital *= (1 + pnl - commission)
                        consecutive_losses = 0
                        trades.append({'pnl': pnl, 'type': 'LONG', 'exit': 'TP'})
                        position = None
                elif position['type'] == 'SHORT':
                    sl_price = position['entry'] * (1 + sl_mult * row['atr'] / position['entry'])
                    tp_price = position['entry'] * (1 - tp_mult * row['atr'] / position['entry'])
                    if row['high'] >= sl_price:
                        exit_price = sl_price * (1 + slippage)
                        pnl = (position['entry'] - exit_price) / position['entry']
                        capital *= (1 + pnl - commission)
                        if pnl < 0:
                            consecutive_losses += 1
                        else:
                            consecutive_losses = 0
                        trades.append({'pnl': pnl, 'type': 'SHORT', 'exit': 'SL'})
                        position = None
                    elif row['low'] <= tp_price:
                        exit_price = tp_price * (1 + slippage)
                        pnl = (position['entry'] - exit_price) / position['entry']
                        capital *= (1 + pnl - commission)
                        consecutive_losses = 0
                        trades.append({'pnl': pnl, 'type': 'SHORT', 'exit': 'TP'})
                        position = None

            if consecutive_losses >= 5:
                blocked_until = i + 24
                consecutive_losses = 0
                continue

            if position is not None:
                continue

            is_trending = row.get('adx', 20) > adx_trend
            long_signal = (row['rsi'] < rsi_os and row['close'] < row['bb_lower']
                           and row['close'] > row.get('ema_55', row['close']))
            short_signal = (row['rsi'] > rsi_ob and row['close'] > row['bb_upper']
                            and row['close'] < row.get('ema_55', row['close']))

            if is_trending:
                long_signal = (row['close'] > row.get('ema_9', row['close'])
                               and row.get('ema_9', row['close']) > row.get('ema_21', row['close']))
                short_signal = (row['close'] < row.get('ema_9', row['close'])
                                and row.get('ema_9', row['close']) < row.get('ema_21', row['close']))

            if long_signal:
                position = {'type': 'LONG', 'entry': row['close'] * (1 + slippage)}
            elif short_signal:
                position = {'type': 'SHORT', 'entry': row['close'] * (1 - slippage)}

        return trades, capital

    def _evaluate_params(self, **params):
        """目标函数: 返回夏普比率(越高越好)"""
        try:
            int_bb_period = int(params.get('bb_period', 20))
            eval_params = {
                'rsi_oversold': params.get('rsi_oversold', 30),
                'rsi_overbought': params.get('rsi_overbought', 70),
                'bb_std': params.get('bb_std', 2.5),
                'bb_period': int_bb_period,
                'sl_atr_multiplier': params.get('sl_atr_multiplier', 1.5),
                'tp_atr_multiplier': params.get('tp_atr_multiplier', 3.0),
                'adx_trend_threshold': params.get('adx_trend_threshold', 25),
                'bb_extreme_threshold': params.get('bb_extreme_threshold', 2.5),
            }

            # 训练集回测(60%)
            df_train = self._generate_backtest_data(1200, seed=42)
            df_train = self._compute_indicators(df_train, eval_params)
            trades_train, capital_train = self._run_backtest(df_train, eval_params)

            if len(trades_train) < 5:
                return -10.0

            pnls = [t['pnl'] for t in trades_train]
            mean_pnl = np.mean(pnls)
            std_pnl = np.std(pnls) + 1e-10
            sharpe = mean_pnl / std_pnl * np.sqrt(252)
            win_rate = sum(1 for p in pnls if p > 0) / len(pnls)

            # 验证集惩罚(防止过拟合)
            df_val = self._generate_backtest_data(400, seed=137)
            df_val = self._compute_indicators(df_val, eval_params)
            trades_val, _ = self._run_backtest(df_val, eval_params)
            if trades_val:
                val_pnls = [t['pnl'] for t in trades_val]
                val_sharpe = np.mean(val_pnls) / (np.std(val_pnls) + 1e-10) * np.sqrt(252)
                val_penalty = max(0, sharpe - val_sharpe) * 0.3
            else:
                val_penalty = sharpe * 0.5

            # 交易频率惩罚(太低不好)
            freq_penalty = max(0, 10 - len(trades_train)) * 0.05

            final_score = sharpe - val_penalty - freq_penalty
            self.optimization_history.append({
                'params': eval_params,
                'sharpe': sharpe,
                'win_rate': win_rate,
                'n_trades': len(trades_train),
                'capital_train': capital_train,
                'final_score': final_score
            })

            return final_score
        except Exception as e:
            return -100.0

    def optimize(self, param_space=None):
        """执行贝叶斯优化"""
        if param_space is None:
            param_space = {
                'rsi_oversold': (20, 40),
                'rsi_overbought': (60, 80),
                'bb_std': (1.5, 3.5),
                'bb_period': (15, 30),
                'sl_atr_multiplier': (1.0, 2.5),
                'tp_atr_multiplier': (2.0, 5.0),
                'adx_trend_threshold': (18, 35),
                'bb_extreme_threshold': (2.0, 3.5),
            }

        try:
            from bayes_opt import BayesianOptimization
        except ImportError:
            print("[WARN] bayesian-optimization not installed, using grid search fallback")
            return self._grid_search_fallback(param_space)

        optimizer = BayesianOptimization(
            f=self._evaluate_params,
            pbounds=param_space,
            random_state=42,
        )

        print("=" * 60)
        print("Bayesian Optimization - Parameter Tuning")
        print("=" * 60)
        print(f"Parameter Space: {len(param_space)} dimensions")
        print(f"Init Points: {self.init_points}, Iterations: {self.n_iter}")
        print("-" * 60)

        optimizer.maximize(
            init_points=self.init_points,
            n_iter=self.n_iter,
        )

        self.best_params = optimizer.max['params']
        self.best_score = optimizer.max['target']

        int_bb_period = int(self.best_params.get('bb_period', 20))
        self.best_params['bb_period'] = int_bb_period

        print("\n" + "=" * 60)
        print("OPTIMIZATION COMPLETE")
        print("=" * 60)
        print(f"Best Score (Sharpe): {self.best_score:.4f}")
        print(f"Best Parameters:")
        for k, v in sorted(self.best_params.items()):
            print(f"  {k}: {v}")

        self._update_config_with_best_params()
        self._run_out_of_sample_test()
        self._save_report()
        return self.best_params

    def _grid_search_fallback(self, param_space):
        """网格搜索回退方案"""
        print("[INFO] Using grid search fallback (no bayesian-optimization)")
        best_score = -np.inf
        best_params = {}

        keys = list(param_space.keys())
        n_samples = 20
        for _ in range(n_samples):
            sample_params = {}
            for k in keys:
                low, high = param_space[k]
                if k == 'bb_period':
                    sample_params[k] = int(np.random.randint(low, high + 1))
                else:
                    sample_params[k] = np.random.uniform(low, high)
            score = self._evaluate_params(**sample_params)
            if score > best_score:
                best_score = score
                best_params = sample_params.copy()

        self.best_params = best_params
        self.best_score = best_score
        self._update_config_with_best_params()
        self._run_out_of_sample_test()
        self._save_report()
        return best_params

    def _update_config_with_best_params(self):
        """用最优参数更新配置文件"""
        config = self._load_config()
        if 'strategy' not in config:
            config['strategy'] = {}
        if 'v5_optimal_params' not in config['strategy']:
            config['strategy']['v5_optimal_params'] = {}

        param_map = {
            'rsi_oversold': 'rsi_oversold',
            'rsi_overbought': 'rsi_overbought',
            'bb_std': 'bb_std',
            'bb_period': 'bb_period',
            'sl_atr_multiplier': 'sl_atr_multiplier',
            'tp_atr_multiplier': 'tp_atr_multiplier',
        }
        for src_key, dst_key in param_map.items():
            if src_key in self.best_params:
                config['strategy']['v5_optimal_params'][dst_key] = self.best_params[src_key]

        if 'market_state_machine' not in config:
            config['market_state_machine'] = {}
        if 'adx_trend_threshold' in self.best_params:
            config['market_state_machine']['adx_trend_threshold'] = float(self.best_params['adx_trend_threshold'])
        if 'bb_extreme_threshold' in self.best_params:
            config['market_state_machine']['bb_extreme_threshold'] = float(self.best_params['bb_extreme_threshold'])

        if 'risk_management' not in config:
            config['risk_management'] = {}
        if 'sl_atr_multiplier' in self.best_params:
            config['risk_management']['atr_multiplier_sl'] = float(self.best_params['sl_atr_multiplier'])
        if 'tp_atr_multiplier' in self.best_params:
            config['risk_management']['atr_multiplier_tp'] = float(self.best_params['tp_atr_multiplier'])

        config['system']['version'] = 'v5.1'
        self._save_config(config)
        print(f"\n[OK] Config updated with best parameters -> {self.config_path}")

    def _run_out_of_sample_test(self):
        """样本外最终测试(20% - 只测一次)"""
        df_test = self._generate_backtest_data(400, seed=999)
        test_params = dict(self.best_params)
        test_params['bb_period'] = int(test_params.get('bb_period', 20))
        df_test = self._compute_indicators(df_test, test_params)
        trades, capital = self._run_backtest(df_test, test_params)

        if trades:
            pnls = [t['pnl'] for t in trades]
            oos_win_rate = sum(1 for p in pnls if p > 0) / len(pnls)
            oos_sharpe = np.mean(pnls) / (np.std(pnls) + 1e-10) * np.sqrt(252)
        else:
            oos_win_rate = 0
            oos_sharpe = 0

        print("\n" + "-" * 60)
        print("OUT-OF-SAMPLE TEST (Final 20%, seed=999)")
        print("-" * 60)
        print(f"  OOS Win Rate:    {oos_win_rate:.2%}")
        print(f"  OOS Sharpe:      {oos_sharpe:.4f}")
        print(f"  OOS Trades:      {len(trades)}")
        print(f"  OOS Capital:     ${capital:.2f}")
        print(f"  Train-Test Gap:  {abs(self.best_score - oos_sharpe):.4f}")
        if abs(self.best_score - oos_sharpe) > self.best_score * 0.5:
            print("  [WARN] Large train-test gap! Possible overfitting.")

    def _save_report(self):
        """保存优化报告"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'version': 'v5.1',
            'method': 'Bayesian Optimization (GP + EI)',
            'best_params': {k: (int(v) if k == 'bb_period' else float(v))
                            for k, v in self.best_params.items()},
            'best_score': float(self.best_score),
            'n_iterations': self.n_iter,
            'n_init_points': self.init_points,
            'optimization_history': [
                {
                    'params': {k: (int(v) if k == 'bb_period' else float(v))
                               for k, v in h['params'].items()},
                    'sharpe': float(h['sharpe']),
                    'win_rate': float(h['win_rate']),
                    'n_trades': int(h['n_trades']),
                    'final_score': float(h['final_score'])
                }
                for h in self.optimization_history
            ]
        }
        report_path = 'bayesian_optimization_report.json'
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n[OK] Report saved -> {report_path}")


def main():
    parser = argparse.ArgumentParser(description='Bayesian Optimization for Trading System Parameters')
    parser.add_argument('--config', default='config.json', help='Config file path')
    parser.add_argument('--n-iter', type=int, default=30, help='Number of BO iterations')
    parser.add_argument('--init-points', type=int, default=5, help='Number of initial random points')
    parser.add_argument('--output', default='bayesian_optimization_report.json', help='Output report path')
    args = parser.parse_args()

    optimizer = BayesianOptimizer(
        config_path=args.config,
        n_iter=args.n_iter,
        init_points=args.init_points
    )
    best = optimizer.optimize()
    result = {
        'status': 'success',
        'best_params': {k: (int(v) if k == 'bb_period' else round(float(v), 4))
                        for k, v in best.items()},
        'best_score': round(float(optimizer.best_score), 4),
        'n_iterations': args.n_iter
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
