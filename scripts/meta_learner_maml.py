#!/usr/bin/env python3
"""
元学习 MAML 框架 (Model-Agnostic Meta-Learning)
================================================
v5.1 P1-2: 非平稳市场的策略快速适应

原理: 通过"学会学习"实现少样本快速适应
优势: 在新市场环境下显著缩短适应周期
适用: 多市场/多品种策略迁移、市场状态切换后快速适应

参考: Trading in Fast-Changing Markets with Meta-Reinforcement Learning
"""

import argparse
import json
import warnings
from copy import deepcopy
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')


class MAMLMetaLearner:
    """MAML元学习器 - 交易策略快速适应"""

    def __init__(self, inner_lr=0.01, outer_lr=0.001, n_inner_steps=5, n_meta_tasks=10):
        self.inner_lr = inner_lr
        self.outer_lr = outer_lr
        self.n_inner_steps = n_inner_steps
        self.n_meta_tasks = n_meta_tasks
        self.meta_params = None
        self.task_history = []

    def _init_params(self, n_features=10):
        """初始化元参数"""
        self.meta_params = {
            'w_signal': np.random.randn(n_features) * 0.1,
            'b_signal': 0.0,
            'w_risk': np.array([1.5, 3.0, 0.5]),  # SL, TP, Kelly
            'threshold': 0.5
        }
        return self.meta_params

    def _generate_task(self, task_id, n_bars=1500):
        """生成元学习任务(不同市场环境)"""
        np.random.seed(task_id * 100)
        env_types = ['bull', 'bear', 'ranging', 'crash', 'recovery']
        env = env_types[task_id % len(env_types)]

        dates = pd.date_range('2024-01-01', periods=n_bars, freq='1h')
        noise = np.random.randn(n_bars) * 0.005

        if env == 'bull':
            trend = 0.003 + np.random.randn(n_bars) * 0.001
        elif env == 'bear':
            trend = -0.002 + np.random.randn(n_bars) * 0.001
        elif env == 'ranging':
            trend = np.sin(np.arange(n_bars) / 50) * 0.002
        elif env == 'crash':
            trend = -0.005 + np.random.randn(n_bars) * 0.003
        else:  # recovery
            trend = np.concatenate([
                np.linspace(-0.002, 0.001, n_bars // 2),
                np.linspace(0.001, 0.003, n_bars - n_bars // 2)
            ])

        returns = noise + trend
        close = 100000 * np.exp(np.cumsum(returns))
        high = close * (1 + np.abs(np.random.randn(n_bars)) * 0.003)
        low = close * (1 - np.abs(np.random.randn(n_bars)) * 0.003)
        volume = np.random.randint(100, 1000, n_bars) * 1e6

        df = pd.DataFrame({
            'timestamp': dates, 'open': close * 0.9999, 'high': high,
            'low': low, 'close': close, 'volume': volume
        })

        # 计算特征
        df['return_1'] = df['close'].pct_change()
        df['return_5'] = df['close'].pct_change(5)
        df['rsi'] = self._compute_rsi(df['close'], 14)
        df['bb_pct'] = self._compute_bb_pct(df['close'], 20)
        df['atr_pct'] = (df['high'] - df['low']) / df['close']
        df['vol_ma'] = df['volume'].rolling(20).mean() / df['volume'].rolling(60).mean()
        df['ema_diff'] = (df['close'].ewm(9).mean() - df['close'].ewm(21).mean()) / df['close']
        df['adx'] = self._compute_adx(df, 14)
        df['skew'] = df['return_1'].rolling(20).skew()

        feature_cols = ['return_1', 'return_5', 'rsi', 'bb_pct', 'atr_pct',
                        'vol_ma', 'ema_diff', 'adx', 'skew']
        df = df.dropna()

        # 分割支持集/查询集(60/40)
        n = len(df)
        split = int(n * 0.6)
        support = df.iloc[:split]
        query = df.iloc[split:]

        return {
            'task_id': task_id,
            'environment': env,
            'support': support,
            'query': query,
            'feature_cols': feature_cols
        }

    def _compute_rsi(self, close, period=14):
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    def _compute_bb_pct(self, close, period=20):
        mid = close.rolling(period).mean()
        std = close.rolling(period).std()
        return (close - mid) / (2 * std + 1e-10)

    def _compute_adx(self, df, period=14):
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

    def _forward(self, features, params):
        """前向传播: 信号评分"""
        w = params['w_signal'][:len(features)]
        b = params['b_signal']
        score = np.dot(features, w) + b
        return 1.0 / (1.0 + np.exp(-np.clip(score, -500, 500)))  # numerically stable sigmoid

    def _compute_loss(self, data, params, feature_cols):
        """计算任务损失(负夏普比率)"""
        features = data[feature_cols].values
        forward_returns = data['return_1'].shift(-1).values

        valid = ~np.isnan(forward_returns) & ~np.isnan(features).any(axis=1)
        features = features[valid]
        forward_returns = forward_returns[valid]

        if len(features) < 10:
            return 0.0

        signals = np.array([self._forward(f, params) for f in features])
        positions = np.where(signals > params['threshold'], 1.0,
                             np.where(signals < (1 - params['threshold']), -1.0, 0.0))

        strategy_returns = positions * forward_returns
        if len(strategy_returns) < 5:
            return 0.0

        mean_ret = np.mean(strategy_returns)
        std_ret = np.std(strategy_returns) + 1e-10
        sharpe = mean_ret / std_ret * np.sqrt(252 * 24)

        return -sharpe  # 最大化夏普 = 最小化负夏普

    def _inner_update(self, task, params):
        """内循环: 在支持集上适应"""
        adapted = deepcopy(params)
        support = task['support']
        feature_cols = task['feature_cols']

        for _ in range(self.n_inner_steps):
            loss = self._compute_loss(support, adapted, feature_cols)

            # 数值梯度(简化版,避免autograd依赖)
            eps = 1e-4
            grad_w = np.zeros_like(adapted['w_signal'])
            for i in range(len(grad_w)):
                params_plus = deepcopy(adapted)
                params_plus['w_signal'][i] += eps
                loss_plus = self._compute_loss(support, params_plus, feature_cols)
                grad_w[i] = (loss_plus - loss) / eps

            grad_b = 0.0
            params_b_plus = deepcopy(adapted)
            params_b_plus['b_signal'] += eps
            loss_b_plus = self._compute_loss(support, params_b_plus, feature_cols)
            grad_b = (loss_b_plus - loss) / eps

            adapted['w_signal'] -= self.inner_lr * grad_w
            adapted['b_signal'] -= self.inner_lr * grad_b

            # 梯度裁剪
            grad_norm = np.linalg.norm(grad_w)
            if grad_norm > 5.0:
                adapted['w_signal'] = adapted['w_signal'] * 5.0 / (grad_norm + 1e-10)

        return adapted

    def meta_train(self, n_iterations=20):
        """元训练循环"""
        if self.meta_params is None:
            self._init_params(n_features=9)

        print("=" * 60)
        print("MAML Meta-Learning for Trading Strategy Adaptation")
        print("=" * 60)
        print(f"Inner LR: {self.inner_lr}, Outer LR: {self.outer_lr}")
        print(f"Inner Steps: {self.n_inner_steps}, Meta Tasks: {self.n_meta_tasks}")
        print(f"Meta Iterations: {n_iterations}")
        print("-" * 60)

        best_meta_loss = np.inf

        for iteration in range(n_iterations):
            meta_loss = 0.0
            n_valid_tasks = 0

            for task_id in range(self.n_meta_tasks):
                task = self._generate_task(task_id)

                # 内循环适应
                adapted_params = self._inner_update(task, self.meta_params)

                # 查询集评估
                query_loss = self._compute_loss(
                    task['query'], adapted_params, task['feature_cols']
                )

                if not np.isnan(query_loss) and not np.isinf(query_loss):
                    meta_loss += query_loss
                    n_valid_tasks += 1

            if n_valid_tasks > 0:
                meta_loss /= n_valid_tasks

                # 外循环更新(简化版: 数值梯度)
                eps = 1e-3
                for key in ['w_signal', 'b_signal']:
                    if key == 'w_signal':
                        original = self.meta_params[key].copy()
                        grad = np.zeros_like(original)
                        for i in range(min(len(grad), 5)):  # 只更新前5个维度(效率)
                            self.meta_params[key][i] = original[i] + eps
                            loss_plus = self._meta_loss_sample(3)
                            self.meta_params[key][i] = original[i] - eps
                            loss_minus = self._meta_loss_sample(3)
                            grad[i] = (loss_plus - loss_minus) / (2 * eps)
                            self.meta_params[key][i] = original[i]

                        self.meta_params[key] -= self.outer_lr * grad
                    elif key == 'b_signal':
                        original = self.meta_params[key]
                        self.meta_params[key] = original + eps
                        loss_plus = self._meta_loss_sample(3)
                        self.meta_params[key] = original - eps
                        loss_minus = self._meta_loss_sample(3)
                        grad = (loss_plus - loss_minus) / (2 * eps)
                        self.meta_params[key] = original - self.outer_lr * grad

                if meta_loss < best_meta_loss:
                    best_meta_loss = meta_loss

                if (iteration + 1) % 5 == 0:
                    print(f"  Iteration {iteration + 1}/{n_iterations} | "
                          f"Meta Loss: {meta_loss:.4f} | Best: {best_meta_loss:.4f}")

            self.task_history.append({
                'iteration': iteration,
                'meta_loss': float(meta_loss),
                'best_meta_loss': float(best_meta_loss)
            })

        print(f"\nMeta-training complete. Best meta loss: {best_meta_loss:.4f}")
        return self.meta_params

    def _meta_loss_sample(self, n_tasks):
        """采样计算元损失"""
        total_loss = 0.0
        for task_id in range(n_tasks):
            task = self._generate_task(task_id + 100)  # 不同seed
            adapted = self._inner_update(task, self.meta_params)
            loss = self._compute_loss(task['query'], adapted, task['feature_cols'])
            if not np.isnan(loss) and not np.isinf(loss):
                total_loss += loss
        return total_loss / max(n_tasks, 1)

    def adapt_to_new_environment(self, new_data, n_steps=10):
        """在新市场环境下快速适应"""
        if self.meta_params is None:
            self._init_params(n_features=9)

        adapted = deepcopy(self.meta_params)
        feature_cols = [c for c in new_data.columns if c in
                        ['return_1', 'return_5', 'rsi', 'bb_pct', 'atr_pct',
                         'vol_ma', 'ema_diff', 'adx', 'skew']]

        if not feature_cols:
            print("[WARN] No valid features found for adaptation")
            return adapted

        print(f"Adapting to new environment ({n_steps} steps)...")
        for step in range(n_steps):
            loss = self._compute_loss(new_data, adapted, feature_cols)
            eps = 1e-4
            for i in range(min(len(adapted['w_signal']), 9)):
                params_plus = deepcopy(adapted)
                params_plus['w_signal'][i] += eps
                loss_plus = self._compute_loss(new_data, params_plus, feature_cols)
                adapted['w_signal'][i] -= self.inner_lr * (loss_plus - loss) / eps

        return adapted

    def save_meta_params(self, path='meta_params.json'):
        """保存元参数"""
        if self.meta_params is None:
            return
        data = {
            'w_signal': self.meta_params['w_signal'].tolist(),
            'b_signal': float(self.meta_params['b_signal']),
            'w_risk': self.meta_params['w_risk'].tolist(),
            'threshold': float(self.meta_params['threshold']),
            'config': {
                'inner_lr': self.inner_lr,
                'outer_lr': self.outer_lr,
                'n_inner_steps': self.n_inner_steps,
                'n_meta_tasks': self.n_meta_tasks
            },
            'timestamp': datetime.now().isoformat()
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"[OK] Meta params saved -> {path}")

    def load_meta_params(self, path='meta_params.json'):
        """加载元参数"""
        with open(path, 'r') as f:
            data = json.load(f)
        self.meta_params = {
            'w_signal': np.array(data['w_signal']),
            'b_signal': data['b_signal'],
            'w_risk': np.array(data['w_risk']),
            'threshold': data['threshold']
        }
        print(f"[OK] Meta params loaded from {path}")


def main():
    parser = argparse.ArgumentParser(description='MAML Meta-Learning for Trading Strategies')
    parser.add_argument('--n-iterations', type=int, default=20, help='Number of meta-training iterations')
    parser.add_argument('--n-tasks', type=int, default=10, help='Number of meta-learning tasks')
    parser.add_argument('--inner-lr', type=float, default=0.01, help='Inner loop learning rate')
    parser.add_argument('--outer-lr', type=float, default=0.001, help='Outer loop learning rate')
    parser.add_argument('--save', default='meta_params.json', help='Save meta params path')
    args = parser.parse_args()

    learner = MAMLMetaLearner(
        inner_lr=args.inner_lr,
        outer_lr=args.outer_lr,
        n_meta_tasks=args.n_tasks
    )
    meta_params = learner.meta_train(n_iterations=args.n_iterations)
    learner.save_meta_params(args.save)

    result = {
        'status': 'success',
        'n_iterations': args.n_iterations,
        'n_tasks': args.n_tasks,
        'best_meta_loss': float(learner.task_history[-1]['best_meta_loss']) if learner.task_history else 0,
        'save_path': args.save
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
