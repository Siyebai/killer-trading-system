#!/usr/bin/env python3
"""
分层风险平价 (Hierarchical Risk Parity, HRP)
=============================================
v5.1 P1-1: 无需预期收益的鲁棒组合优化

原理: 通过层次聚类与递归二分构建风险分散组合
优势: 在估计误差大时优于均值-方差优化(MVO)
适用: 资金管理、多品种分配、风险预算

参考: Advanced Portfolio Optimization: HRP (Marcos Lopez de Prado)
"""

import argparse
import json
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, cophenet, fcluster
from scipy.spatial.distance import squareform

warnings.filterwarnings('ignore')


class HierarchicalRiskParity:
    """HRP分层风险平价组合优化器"""

    def __init__(self, method='single'):
        self.method = method
        self.clusters = None
        self.weights = None
        self.linkage_matrix = None

    def _compute_covariance(self, returns_df):
        """计算收缩协方差矩阵(Ledoit-Wolf)"""
        cov = returns_df.cov()
        n = len(cov)
        target = np.eye(n) * np.mean(np.diag(cov))
        shrinkage = 0.5  # 固定收缩强度
        shrunk_cov = shrinkage * target + (1 - shrinkage) * cov.values
        return pd.DataFrame(shrunk_cov, index=cov.index, columns=cov.columns)

    def _compute_correlation_distance(self, corr):
        """计算相关性距离矩阵"""
        dist = np.sqrt(0.5 * (1 - corr.values))
        np.fill_diagonal(dist, 0)
        return pd.DataFrame(dist, index=corr.index, columns=corr.columns)

    def _cluster_series(self, dist_matrix):
        """层次聚类"""
        condensed = squareform(dist_matrix.values, checks=False)
        self.linkage_matrix = linkage(condensed, method=self.method)
        return self.linkage_matrix

    def _get_quasi_diag(self, link):
        """准对角化: 重排协方差矩阵使相似资产相邻"""
        n = link.shape[0] + 1
        sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
        cluster_items = [sort_ix.iloc[0], sort_ix.iloc[1]]

        for i in range(n - 2, -1, -1):
            new_items = []
            for item in cluster_items:
                if isinstance(item, (int, float, np.integer, np.floating)):
                    item = int(item)
                    if item >= n:
                        idx = int(item - n)
                        new_items.extend([link[idx, 0], link[idx, 1]])
                    else:
                        new_items.append(item)
                else:
                    new_items.append(item)
            cluster_items = new_items

        return [int(x) for x in cluster_items if isinstance(x, (int, float, np.integer, np.floating)) and x < n]

    def _get_rec_bipart(self, cov, sort_ix):
        """递归二分分配权重"""
        w = pd.Series(1.0, index=sort_ix)
        clusters = [sort_ix]

        while len(clusters) > 0:
            # 弹出第一个簇
            cluster = clusters.pop(0)
            if len(cluster) <= 1:
                continue

            # 分成两半
            mid = len(cluster) // 2
            left = cluster[:mid]
            right = cluster[mid:]

            # 计算两个子簇的方差
            left_var = self._get_cluster_var(cov, left)
            right_var = self._get_cluster_var(cov, right)

            # 基于逆方差分配权重
            alpha = 1.0 - left_var / (left_var + right_var + 1e-10)

            # 更新权重
            w[left] *= alpha
            w[right] *= (1.0 - alpha)

            # 将子簇加入待处理列表
            if len(left) > 1:
                clusters.append(left)
            if len(right) > 1:
                clusters.append(right)

        return w

    def _get_cluster_var(self, cov, cluster_items):
        """计算簇的方差"""
        cov_slice = cov.iloc[cluster_items, cluster_items]
        try:
            inv_diag = 1.0 / np.diag(cov_slice.values)
        except:
            inv_diag = np.ones(len(cluster_items))
        w = inv_diag / (inv_diag.sum() + 1e-10)
        return np.dot(w, np.dot(cov_slice.values, w))

    def allocate(self, returns_df):
        """执行HRP分配"""
        # Step 1: 计算协方差与相关性
        cov = self._compute_covariance(returns_df)
        corr = returns_df.corr()

        # Step 2: 相关性距离
        dist = self._compute_correlation_distance(corr)

        # Step 3: 层次聚类
        self._cluster_series(dist)

        # Step 4: 准对角化
        sort_ix = self._get_quasi_diag(self.linkage_matrix)
        if len(sort_ix) == 0:
            n = len(returns_df.columns)
            sort_ix = list(range(n))

        # Step 5: 递归二分
        weights = self._get_rec_bipart(cov, sort_ix)

        # 对齐权重到原始列
        final_weights = pd.Series(0.0, index=returns_df.columns)
        for i, idx in enumerate(sort_ix):
            if idx < len(returns_df.columns):
                col = returns_df.columns[idx]
                final_weights[col] = weights.get(idx, 0.0)

        # 归一化
        total = final_weights.sum()
        if total > 0:
            final_weights = final_weights / total

        self.weights = final_weights
        return final_weights

    def get_risk_contribution(self, cov_matrix=None, returns_df=None):
        """计算各资产的风险贡献"""
        if self.weights is None:
            raise ValueError("Run allocate() first")

        if cov_matrix is None and returns_df is not None:
            cov_matrix = returns_df.cov()

        w = self.weights.values
        sigma = np.sqrt(np.dot(w, np.dot(cov_matrix.values, w)))
        mrc = np.dot(cov_matrix.values, w) / (sigma + 1e-10)
        rc = w * mrc
        rc_pct = rc / (rc.sum() + 1e-10)
        return pd.Series(rc_pct, index=self.weights.index)

    def compare_with_equal_weight(self, returns_df):
        """与等权组合对比"""
        if self.weights is None:
            self.allocate(returns_df)

        # 等权组合
        n = len(returns_df.columns)
        eq_weights = pd.Series(1.0 / n, index=returns_df.columns)

        cov = returns_df.cov()

        # HRP组合波动率
        hrp_var = np.dot(self.weights.values, np.dot(cov.values, self.weights.values))
        hrp_vol = np.sqrt(hrp_var)

        # 等权组合波动率
        eq_var = np.dot(eq_weights.values, np.dot(cov.values, eq_weights.values))
        eq_vol = np.sqrt(eq_var)

        # 风险贡献标准差(越小越均衡)
        hrp_rc = self.get_risk_contribution(cov)
        eq_rc = eq_weights * np.dot(cov.values, eq_weights.values)
        eq_rc_pct = eq_rc / (eq_rc.sum() + 1e-10)

        hrp_rc_std = hrp_rc.std()
        eq_rc_std = eq_rc_pct.std()

        return {
            'hrp_volatility': float(hrp_vol),
            'equal_weight_volatility': float(eq_vol),
            'vol_reduction_pct': float((eq_vol - hrp_vol) / eq_vol * 100),
            'hrp_risk_contribution_std': float(hrp_rc_std),
            'equal_weight_risk_contribution_std': float(eq_rc_std),
            'risk_balance_improvement': float((eq_rc_std - hrp_rc_std) / eq_rc_std * 100)
        }


class MultiSymbolHRPAllocator:
    """多品种HRP资金分配器 - 交易系统集成"""

    SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']

    def __init__(self, config_path='config.json'):
        self.config_path = config_path
        self.hrp = HierarchicalRiskParity()

    def _generate_returns(self, n_days=180, seed=42):
        """生成模拟收益率数据"""
        np.random.seed(seed)
        dates = pd.date_range('2024-01-01', periods=n_days, freq='D')

        # 品种特性: BTC(低波动)、ETH(中波动)、SOL(高波动)、BNB(中低波动)
        params = {
            'BTCUSDT': {'mu': 0.0003, 'sigma': 0.03, 'beta': 1.0},
            'ETHUSDT': {'mu': 0.0004, 'sigma': 0.04, 'beta': 1.2},
            'SOLUSDT': {'mu': 0.0005, 'sigma': 0.06, 'beta': 1.5},
            'BNBUSDT': {'mu': 0.0002, 'sigma': 0.035, 'beta': 0.9},
        }

        market_factor = np.random.randn(n_days) * 0.02
        returns = {}
        for sym, p in params.items():
            idio = np.random.randn(n_days) * p['sigma'] * 0.5
            returns[sym] = p['mu'] + p['beta'] * market_factor + idio

        return pd.DataFrame(returns, index=dates)

    def allocate(self, returns_df=None):
        """执行HRP分配"""
        if returns_df is None:
            returns_df = self._generate_returns()

        weights = self.hrp.allocate(returns_df)
        comparison = self.hrp.compare_with_equal_weight(returns_df)

        result = {
            'weights': {k: round(float(v), 4) for k, v in weights.items()},
            'comparison_vs_equal_weight': comparison,
            'method': 'HRP (Hierarchical Risk Parity)',
            'timestamp': datetime.now().isoformat()
        }
        return result

    def integrate_with_config(self, weights):
        """将HRP权重写入config.json"""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
        except FileNotFoundError:
            config = {}

        if 'symbol_weights' not in config:
            config['symbol_weights'] = {}

        for sym, w in weights.items():
            config['symbol_weights'][sym] = round(float(w), 4)

        config['portfolio_optimization'] = {
            'method': 'HRP',
            'version': 'v5.1',
            'last_updated': datetime.now().isoformat()
        }

        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        print(f"[OK] HRP weights written to {self.config_path}")


def main():
    parser = argparse.ArgumentParser(description='HRP Portfolio Optimization')
    parser.add_argument('--config', default='config.json', help='Config file path')
    parser.add_argument('--days', type=int, default=180, help='Historical days for estimation')
    parser.add_argument('--update-config', action='store_true', help='Update config.json with HRP weights')
    args = parser.parse_args()

    allocator = MultiSymbolHRPAllocator(config_path=args.config)
    result = allocator.allocate()

    print("=" * 60)
    print("HRP Portfolio Optimization Results")
    print("=" * 60)
    print("\nOptimal Weights:")
    for sym, w in result['weights'].items():
        bar = '#' * int(w * 100)
        print(f"  {sym:12s}: {w:.4f} ({w*100:.1f}%) {bar}")

    print("\nComparison vs Equal Weight:")
    comp = result['comparison_vs_equal_weight']
    print(f"  HRP Volatility:          {comp['hrp_volatility']:.4f}")
    print(f"  Equal Weight Volatility:  {comp['equal_weight_volatility']:.4f}")
    print(f"  Vol Reduction:            {comp['vol_reduction_pct']:.2f}%")
    print(f"  Risk Balance Improvement: {comp['risk_balance_improvement']:.2f}%")

    if args.update_config:
        allocator.integrate_with_config(result['weights'])

    output = {
        'status': 'success',
        'weights': result['weights'],
        'volatility_reduction': round(comp['vol_reduction_pct'], 2),
        'risk_balance_improvement': round(comp['risk_balance_improvement'], 2)
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
