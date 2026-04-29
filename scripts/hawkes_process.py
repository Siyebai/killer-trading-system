#!/usr/bin/env python3
"""
Hawkes 过程市场冲击模型 (Hawkes Process Market Impact)
=====================================================
v5.1 P1-4: 自激点过程建模订单流与市场冲击

核心价值: 同时解释订单流的长记忆性与市场冲击的幂律衰减
可落地点: 信号评分二次校验、订单流确认、冲击函数估计

参考: A Unified Theory for Volume, Impact, and Volatility
      Hawkes model for price and trades high-frequency dynamics
"""

import argparse
import json
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')


class HawkesProcess:
    """Hawkes过程 - 自激点过程模型"""

    def __init__(self, alpha=0.6, beta=0.8, mu=0.1):
        """
        Args:
            alpha: 自激发强度(事件间相互激发)
            beta: 衰减速率(过去事件影响衰减)
            mu: 基础强度(外生事件)
        """
        self.alpha = alpha
        self.beta = beta
        self.mu = mu
        self.fitted_params = None

    def intensity(self, t, events):
        """计算时刻t的条件强度函数"""
        lambda_t = self.mu
        for t_i in events:
            if t_i < t:
                lambda_t += self.alpha * np.exp(-self.beta * (t - t_i))
        return lambda_t

    def simulate(self, T=1000, seed=42):
        """模拟Hawkes过程事件(Ogata's thinning algorithm)"""
        np.random.seed(seed)
        events = []
        t = 0
        while t < T:
            lambda_bar = self.mu + self.alpha * sum(
                np.exp(-self.beta * (t - t_i)) for t_i in events if t_i < t
            ) + self.alpha
            u = np.random.exponential(1.0 / lambda_bar)
            t += u
            if t >= T:
                break
            lambda_t = self.intensity(t, events)
            if np.random.random() < lambda_t / lambda_bar:
                events.append(t)
        return np.array(events)

    def log_likelihood(self, events, T, alpha=None, beta=None, mu=None):
        """计算对数似然"""
        alpha = alpha or self.alpha
        beta = beta or self.beta
        mu = mu or self.mu
        if len(events) == 0:
            return -np.inf

        n = len(events)
        ll = -mu * T

        # 递归计算R_i
        R = np.zeros(n)
        for i in range(1, n):
            R[i] = np.exp(-beta * (events[i] - events[i - 1])) * (1 + R[i - 1])

        for i in range(n):
            lambda_i = mu + alpha * R[i]
            if lambda_i > 0:
                ll += np.log(lambda_i)

        # 补偿项
        ll -= alpha * (1 - np.exp(-beta * (T - events[-1]))) * (1 + R[-1]) if n > 0 else 0
        for i in range(n):
            if i > 0:
                ll -= alpha / beta * (1 - np.exp(-beta * (events[i] - events[i - 1])))

        return ll

    def fit(self, events, T=None):
        """拟合Hawkes过程参数(网格搜索)"""
        if T is None:
            T = events[-1] * 1.1 if len(events) > 0 else 1.0

        best_ll = -np.inf
        best_params = (self.alpha, self.beta, self.mu)

        # 网格搜索
        alphas = np.arange(0.1, 1.5, 0.2)
        betas = np.arange(0.3, 2.0, 0.3)
        mus = np.arange(0.01, 0.5, 0.1)

        for a in alphas:
            for b in betas:
                if a >= b:  # 平稳性条件: alpha < beta
                    continue
                for m in mus:
                    try:
                        ll = self.log_likelihood(events, T, a, b, m)
                        if ll > best_ll:
                            best_ll = ll
                            best_params = (a, b, m)
                    except:
                        continue

        self.alpha, self.beta, self.mu = best_params
        self.fitted_params = {
            'alpha': float(self.alpha),
            'beta': float(self.beta),
            'mu': float(self.mu),
            'log_likelihood': float(best_ll),
            'branching_ratio': float(self.alpha / self.beta)
        }
        return self.fitted_params


class MarketImpactModel:
    """市场冲击模型 - 基于Hawkes过程"""

    def __init__(self):
        self.buy_hawkes = HawkesProcess(alpha=0.6, beta=0.8, mu=0.1)
        self.sell_hawkes = HawkesProcess(alpha=0.6, beta=0.8, mu=0.1)
        self.impact_coeff = None

    def _extract_events(self, df, side='buy'):
        """从K线数据提取买入/卖出事件"""
        price_change = df['close'].diff()
        volume = df['volume']

        if side == 'buy':
            mask = price_change > 0
        else:
            mask = price_change < 0

        events = []
        for i, (idx, row) in enumerate(df.iterrows()):
            if mask.iloc[i] if i < len(mask) else False:
                # 事件强度 = 量加权
                n_events = max(1, int(volume.iloc[i] / volume.median()))
                events.extend([float(i)] * min(n_events, 5))

        return np.array(events) if events else np.array([0.0])

    def estimate_impact_function(self, df):
        """估计市场冲击函数"""
        buy_events = self._extract_events(df, 'buy')
        sell_events = self._extract_events(df, 'sell')

        # 拟合双过程Hawkes
        T = float(len(df))
        buy_params = self.buy_hawkes.fit(buy_events, T)
        sell_params = self.sell_hawkes.fit(sell_events, T)

        # 市场冲击 = 自激发强度 / 衰减速率 (branching ratio)
        buy_impact = buy_params['branching_ratio']
        sell_impact = sell_params['branching_ratio']

        # 冲击函数: I(V) = sigma * V^gamma
        # 其中gamma通常在0.3-0.7之间(Square-Root Law)
        volumes = df['volume'].values
        price_changes = df['close'].pct_change().abs().values[1:]
        vol_changes = volumes[1:]

        valid = (vol_changes > 0) & (price_changes > 0)
        if valid.sum() > 10:
            log_v = np.log(vol_changes[valid] + 1)
            log_p = np.log(price_changes[valid] + 1e-10)
            gamma = np.polyfit(log_v, log_p, 1)[0]
            gamma = np.clip(gamma, 0.3, 0.7)
        else:
            gamma = 0.5  # Square-Root Law默认值

        sigma = np.median(price_changes[valid]) / (np.median(vol_changes[valid]) ** gamma + 1e-10)

        self.impact_coeff = {
            'sigma': float(sigma),
            'gamma': float(gamma),
            'buy_branching_ratio': float(buy_impact),
            'sell_branching_ratio': float(sell_impact),
            'buy_params': buy_params,
            'sell_params': sell_params
        }

        return self.impact_coeff

    def predict_impact(self, order_volume, side='buy'):
        """预测订单的市场冲击"""
        if self.impact_coeff is None:
            raise ValueError("Run estimate_impact_function() first")

        sigma = self.impact_coeff['sigma']
        gamma = self.impact_coeff['gamma']
        impact = sigma * (order_volume ** gamma)

        if side == 'buy':
            impact *= (1 + self.impact_coeff['buy_branching_ratio'])
        else:
            impact *= (1 + self.impact_coeff['sell_branching_ratio'])

        return float(impact)

    def generate_signal_confirmation(self, df, signal_type='LONG'):
        """生成Hawkes过程信号确认"""
        buy_events = self._extract_events(df, 'buy')
        sell_events = self._extract_events(df, 'sell')

        T = float(len(df))
        current_t = T - 1

        # 当前时刻的条件强度
        buy_intensity = self.buy_hawkes.intensity(current_t, buy_events)
        sell_intensity = self.sell_hawkes.intensity(current_t, sell_events)

        # 信号确认逻辑（分级确认）
        ratio = buy_intensity / (sell_intensity + 1e-10)
        sell_ratio = sell_intensity / (buy_intensity + 1e-10)
        
        if signal_type == 'LONG':
            if ratio > 1.5:
                confidence = min(ratio / 3, 1.0)
                return {'confirmed': True, 'confidence': float(confidence),
                        'buy_intensity': float(buy_intensity), 'sell_intensity': float(sell_intensity)}
            elif ratio > 1.1:
                confidence = min((ratio - 1.0) / 2, 0.5)
                return {'confirmed': True, 'confidence': float(confidence),
                        'buy_intensity': float(buy_intensity), 'sell_intensity': float(sell_intensity)}
            else:
                return {'confirmed': False, 'confidence': 0.0,
                        'buy_intensity': float(buy_intensity), 'sell_intensity': float(sell_intensity)}
        else:  # SHORT
            if sell_ratio > 1.5:
                confidence = min(sell_ratio / 3, 1.0)
                return {'confirmed': True, 'confidence': float(confidence),
                        'buy_intensity': float(buy_intensity), 'sell_intensity': float(sell_intensity)}
            elif sell_ratio > 1.1:
                confidence = min((sell_ratio - 1.0) / 2, 0.5)
                return {'confirmed': True, 'confidence': float(confidence),
                        'buy_intensity': float(buy_intensity), 'sell_intensity': float(sell_intensity)}
            else:
                return {'confirmed': False, 'confidence': 0.0,
                        'buy_intensity': float(buy_intensity), 'sell_intensity': float(sell_intensity)}


def main():
    parser = argparse.ArgumentParser(description='Hawkes Process Market Impact Model')
    parser.add_argument('--bars', type=int, default=1000, help='Number of bars to simulate')
    parser.add_argument('--alpha', type=float, default=0.6, help='Self-excitation parameter')
    parser.add_argument('--beta', type=float, default=0.8, help='Decay rate')
    parser.add_argument('--mu', type=float, default=0.1, help='Base intensity')
    args = parser.parse_args()

    # 生成模拟数据
    np.random.seed(42)
    n = args.bars
    dates = pd.date_range('2024-01-01', periods=n, freq='1h')
    returns = np.random.randn(n) * 0.01
    close = 100000 * np.exp(np.cumsum(returns))
    volume = np.random.randint(100, 5000, n) * 1e6

    df = pd.DataFrame({
        'timestamp': dates, 'close': close, 'volume': volume
    })

    print("=" * 60)
    print("Hawkes Process Market Impact Model")
    print("=" * 60)

    # Step 1: Hawkes过程模拟与拟合
    hawkes = HawkesProcess(alpha=args.alpha, beta=args.beta, mu=args.mu)
    events = hawkes.simulate(T=n, seed=42)
    print(f"\nSimulated {len(events)} events from Hawkes process")
    print(f"  alpha={args.alpha}, beta={args.beta}, mu={args.mu}")
    print(f"  Branching ratio (alpha/beta): {args.alpha / args.beta:.4f}")

    fitted = hawkes.fit(events, T=n)
    print(f"\nFitted parameters:")
    print(f"  alpha={fitted['alpha']:.4f}, beta={fitted['beta']:.4f}, mu={fitted['mu']:.4f}")
    print(f"  Log-likelihood: {fitted['log_likelihood']:.2f}")
    print(f"  Branching ratio: {fitted['branching_ratio']:.4f}")

    # Step 2: 市场冲击估计
    model = MarketImpactModel()
    impact = model.estimate_impact_function(df)
    print(f"\nMarket Impact Function:")
    print(f"  I(V) = {impact['sigma']:.6f} * V^{impact['gamma']:.4f}")
    print(f"  Buy branching ratio: {impact['buy_branching_ratio']:.4f}")
    print(f"  Sell branching ratio: {impact['sell_branching_ratio']:.4f}")

    # Step 3: 信号确认示例
    long_confirm = model.generate_signal_confirmation(df, 'LONG')
    short_confirm = model.generate_signal_confirmation(df, 'SHORT')
    print(f"\nSignal Confirmation:")
    print(f"  LONG:  confirmed={long_confirm['confirmed']}, confidence={long_confirm['confidence']:.4f}")
    print(f"  SHORT: confirmed={short_confirm['confirmed']}, confidence={short_confirm['confidence']:.4f}")

    result = {
        'status': 'success',
        'fitted_params': fitted,
        'impact_function': {
            'sigma': impact['sigma'],
            'gamma': impact['gamma'],
            'buy_branching_ratio': impact['buy_branching_ratio'],
            'sell_branching_ratio': impact['sell_branching_ratio']
        },
        'long_confirmation': long_confirm,
        'short_confirmation': short_confirm
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
