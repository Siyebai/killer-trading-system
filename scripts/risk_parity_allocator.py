#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified Risk Parity Allocator
Integrates ERC, constrained HERC, and IVP with dynamic regime switching

Based on deep learning findings:
- ERC: best for strategy-level allocation (consistent RC balance)
- Constrained HERC: best for multi-asset allocation (respects asset bounds)
- IVP: fallback when correlation is unreliable (extreme regime)

Usage:
  python scripts/risk_parity_allocator.py --method erc --lookback 60
  python scripts/risk_parity_allocator.py --method herc --constraints crypto_min=0.10,crypto_max=0.40
"""
import argparse
import json
import numpy as np
import pandas as pd
from datetime import datetime
from scipy.cluster.hierarchy import linkage, fcluster, leaves_list
from scipy.spatial.distance import squareform
from scipy.optimize import minimize
from typing import Dict, Optional, Tuple


class ERCAllocator:
    """Equal Risk Contribution (ERC) - Maillard, Roncalli, Teiletche (2010)"""

    def allocate(self, returns_df: pd.DataFrame, target_rc: Optional[Dict] = None) -> pd.Series:
        """
        Allocate weights so each asset contributes equally to portfolio risk.

        Args:
            returns_df: DataFrame of asset returns (T x N)
            target_rc: Optional dict of {asset: target_rc_fraction}. Default: 1/N each.

        Returns:
            pd.Series of weights indexed by asset names
        """
        cov = returns_df.cov().values
        n = cov.shape[0]
        cols = returns_df.columns

        if target_rc is None:
            target = np.ones(n) / n
        else:
            target = np.array([target_rc.get(c, 1.0/n) for c in cols])
            target = target / target.sum()

        def objective(w):
            w = np.array(w)
            port_var = w @ cov @ w
            if port_var <= 1e-15:
                return 1e10
            sigma_p = np.sqrt(port_var)
            mrc = (cov @ w) / sigma_p
            rc = w * mrc
            rc_sum = rc.sum()
            if rc_sum <= 1e-15:
                return 1e10
            rc_pct = rc / rc_sum
            return np.sum((rc_pct - target) ** 2)

        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}
        bounds = [(0.01, 1.0)] * n
        x0 = np.ones(n) / n

        result = minimize(objective, x0, method='SLSQP',
                         bounds=bounds, constraints=constraints,
                         options={'maxiter': 2000, 'ftol': 1e-14})

        if result.success:
            weights = pd.Series(result.x, index=cols)
        else:
            # Fallback to IVP
            weights = IVPAllocator().allocate(returns_df)

        return weights / weights.sum()


class IVPAllocator:
    """Inverse Volatility Portfolio (IVP)"""

    def allocate(self, returns_df: pd.DataFrame) -> pd.Series:
        vols = returns_df.std()
        inv_vols = 1.0 / vols.replace(0, np.nan).fillna(1e-6)
        weights = inv_vols / inv_vols.sum()
        return weights


class ConstrainedHERCAllocator:
    """Hierarchical Equal Risk Contribution with Asset-Class Constraints - Raffinot (2017)"""

    def __init__(self, constraints: Optional[Dict] = None):
        """
        Args:
            constraints: Dict with optional keys:
                - crypto_assets: list of crypto asset names
                - commodity_assets: list of commodity asset names
                - crypto_min_pct: minimum total crypto weight (default 0.10)
                - crypto_max_pct: maximum total crypto weight (default 0.80)
                - commodity_min_pct: minimum total commodity weight (default 0.05)
                - commodity_max_pct: maximum total commodity weight (default 0.40)
                - per_asset_max: maximum single asset weight (default 0.35)
        """
        self.constraints = constraints or {}

    def allocate(self, returns_df: pd.DataFrame) -> pd.Series:
        cols = returns_df.columns
        n_assets = len(cols)
        cov = returns_df.cov()
        corr = returns_df.corr()

        # Step 1: Hierarchical clustering
        dist = np.sqrt(0.5 * (1 - corr.clip(-1, 1)))
        np.fill_diagonal(dist.values, 0)
        condensed = squareform(dist.values, checks=False)
        link = linkage(condensed, method='ward')

        # Step 2: Find optimal clusters
        n_clusters = self._optimal_clusters(link, n_assets)
        cluster_labels = fcluster(link, t=n_clusters, criterion='maxclust')

        # Step 3: Allocate within clusters using inverse volatility
        raw_weights = pd.Series(0.0, index=cols)
        for c in range(1, n_clusters + 1):
            mask = cluster_labels == c
            cluster_cols = cols[mask]
            if len(cluster_cols) == 0:
                continue

            cluster_vols = returns_df[cluster_cols].std()
            inv_vols = 1.0 / (cluster_vols + 1e-10)
            within_weights = inv_vols / inv_vols.sum()

            cluster_budget = 1.0 / n_clusters
            for col in cluster_cols:
                raw_weights[col] = within_weights[col] * cluster_budget

        raw_weights = raw_weights / raw_weights.sum()

        # Step 4: Apply constraints
        weights = self._apply_constraints(raw_weights, returns_df)

        return weights / weights.sum()

    def _optimal_clusters(self, link, n_assets):
        if n_assets <= 2:
            return 1
        if n_assets <= 4:
            return 2
        best_k = 2
        best_balance = 0
        for k in range(2, min(n_assets, 6)):
            labels = fcluster(link, t=k, criterion='maxclust')
            sizes = pd.Series(labels).value_counts()
            balance = sizes.min() / sizes.max()
            if balance > best_balance:
                best_balance = balance
                best_k = k
        return best_k

    def _apply_constraints(self, weights, returns_df):
        """Apply asset-class constraints to weights"""
        crypto_assets = self.constraints.get('crypto_assets',
            [c for c in weights.index if any(x in c.upper() for x in ['BTC', 'ETH', 'SOL', 'BNB', 'USDT'])])
        commodity_assets = self.constraints.get('commodity_assets',
            [c for c in weights.index if any(x in c.upper() for x in ['GOLD', 'SILVER', 'CRUDE', 'OIL'])])

        crypto_min = self.constraints.get('crypto_min_pct', 0.10)
        crypto_max = self.constraints.get('crypto_max_pct', 0.80)
        commodity_min = self.constraints.get('commodity_min_pct', 0.05)
        commodity_max = self.constraints.get('commodity_max_pct', 0.40)
        per_asset_max = self.constraints.get('per_asset_max', 0.35)

        w = weights.copy()

        # Enforce per-asset max
        for col in w.index:
            w[col] = min(w[col], per_asset_max)

        # Enforce crypto bounds
        if crypto_assets:
            crypto_total = w[w.index.isin(crypto_assets)].sum()
            if crypto_total < crypto_min:
                # Scale up crypto, scale down non-crypto
                scale_up = crypto_min / (crypto_total + 1e-10)
                for col in crypto_assets:
                    if col in w.index:
                        w[col] *= scale_up
                non_crypto = w[~w.index.isin(crypto_assets)]
                non_crypto_total = non_crypto.sum()
                if non_crypto_total > 0:
                    scale_down = (1.0 - crypto_min) / non_crypto_total
                    for col in non_crypto.index:
                        w[col] *= scale_down
            elif crypto_total > crypto_max:
                scale_down = crypto_max / crypto_total
                for col in crypto_assets:
                    if col in w.index:
                        w[col] *= scale_down
                freed = 1.0 - w.sum()
                non_crypto = w[~w.index.isin(crypto_assets)]
                non_crypto_total = non_crypto.sum()
                if non_crypto_total > 0:
                    for col in non_crypto.index:
                        w[col] += freed * (w[col] / non_crypto_total)

        # Final normalization
        w = w / w.sum()
        return w


class RiskParityAllocator:
    """Unified Risk Parity Allocator with regime-aware method selection"""

    # Correlation threshold for regime detection
    HIGH_CORR_THRESHOLD = 0.75

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.erc = ERCAllocator()
        self.ivp = IVPAllocator()
        self.herc = ConstrainedHERCAllocator(self.config.get('constraints', {}))
        self.last_weights = None
        self.last_rebalance_time = None

    def allocate(self, returns_df: pd.DataFrame,
                 method: str = 'auto',
                 constraints: Optional[Dict] = None) -> pd.Series:
        """
        Allocate portfolio weights using the specified method.

        Args:
            returns_df: DataFrame of returns (T x N)
            method: 'erc', 'herc', 'ivp', or 'auto' (regime-aware)
            constraints: Optional constraints for HERC

        Returns:
            pd.Series of weights
        """
        if method == 'auto':
            method = self._detect_regime(returns_df)

        if method == 'erc':
            weights = self.erc.allocate(returns_df)
        elif method == 'herc':
            if constraints:
                self.herc = ConstrainedHERCAllocator(constraints)
            weights = self.herc.allocate(returns_df)
        elif method == 'ivp':
            weights = self.ivp.allocate(returns_df)
        else:
            weights = self.erc.allocate(returns_df)

        self.last_weights = weights
        return weights

    def _detect_regime(self, returns_df: pd.DataFrame) -> str:
        """Detect market regime and select appropriate allocation method"""
        corr = returns_df.corr()

        # Check average pairwise correlation
        n = len(corr)
        if n <= 1:
            return 'ivp'

        # Extract upper triangle correlations
        mask = np.triu(np.ones((n, n), dtype=bool), k=1)
        avg_corr = corr.values[mask].mean()

        # Check maximum correlation
        max_corr = corr.values[mask].max()

        # In high-correlation regime, correlation matrix is unreliable
        if avg_corr > self.HIGH_CORR_THRESHOLD or max_corr > 0.95:
            return 'ivp'  # Fall back to volatility-only
        else:
            return 'erc'  # Use full covariance information

    def get_risk_contributions(self, returns_df: pd.DataFrame,
                                weights: Optional[pd.Series] = None) -> pd.Series:
        """Calculate actual risk contributions for current weights"""
        if weights is None:
            weights = self.last_weights
        if weights is None:
            raise ValueError("No weights available. Run allocate() first.")

        cov = returns_df.cov().values
        w = weights.reindex(returns_df.columns).fillna(0).values

        port_var = w @ cov @ w
        if port_var <= 1e-15:
            return pd.Series(0.0, index=returns_df.columns)

        sigma_p = np.sqrt(port_var)
        mrc = (cov @ w) / sigma_p
        rc = w * mrc
        rc_pct = rc / rc.sum()

        return pd.Series(rc_pct, index=returns_df.columns)

    def needs_rebalance(self, current_weights: pd.Series,
                        target_weights: pd.Series,
                        threshold: float = 0.10) -> Tuple[bool, float]:
        """
        Check if portfolio needs rebalancing.

        Returns:
            (needs_rebalance, max_deviation)
        """
        aligned = current_weights.reindex(target_weights.index).fillna(0)
        deviations = (aligned - target_weights).abs() / (target_weights + 1e-10)
        max_dev = deviations.max()
        return max_dev > threshold, float(max_dev)

    def allocate_strategies(self, strategy_returns: pd.DataFrame) -> pd.Series:
        """
        Allocate weights across trading strategies (MR/TF/FR).
        Uses ERC by default for equal risk contribution.
        """
        return self.erc.allocate(strategy_returns)

    def allocate_assets(self, asset_returns: pd.DataFrame,
                         constraints: Optional[Dict] = None) -> pd.Series:
        """
        Allocate weights across assets (BTC/ETH/SOL/BNB/GOLD/SILVER/CRUDE).
        Uses constrained HERC with asset-class bounds.
        """
        method = self._detect_regime(asset_returns)
        if method == 'ivp':
            return self.ivp.allocate(asset_returns)
        else:
            if constraints:
                self.herc = ConstrainedHERCAllocator(constraints)
            return self.herc.allocate(asset_returns)


# ============================================================
# CLI Interface
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Risk Parity Allocator')
    parser.add_argument('--method', choices=['erc', 'herc', 'ivp', 'auto'], default='auto')
    parser.add_argument('--lookback', type=int, default=60, help='Lookback window in days')
    parser.add_argument('--constraints', type=str, default=None,
                       help='Constraints as key=value pairs, comma-separated')
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()

    # Generate test data
    np.random.seed(args.seed)
    n = args.lookback * 2

    params = {
        'BTC': {'mu': 0.0005, 'sigma': 0.035, 'beta': 1.0},
        'ETH': {'mu': 0.0006, 'sigma': 0.045, 'beta': 1.2},
        'SOL': {'mu': 0.0008, 'sigma': 0.060, 'beta': 1.5},
        'BNB': {'mu': 0.0003, 'sigma': 0.032, 'beta': 0.9},
        'GOLD': {'mu': 0.0002, 'sigma': 0.010, 'beta': -0.1},
        'SILVER': {'mu': 0.0001, 'sigma': 0.015, 'beta': -0.05},
        'CRUDE': {'mu': 0.0001, 'sigma': 0.020, 'beta': 0.1},
    }

    market_factor = np.random.randn(n) * 0.02
    returns_data = {}
    for asset, p in params.items():
        idio = np.random.randn(n) * p['sigma'] * 0.5
        returns_data[asset] = p['mu'] + p['beta'] * market_factor + idio

    returns_df = pd.DataFrame(returns_data,
                              index=pd.date_range('2024-01-01', periods=n, freq='D'))

    # Parse constraints
    constraints = {
        'crypto_assets': ['BTC', 'ETH', 'SOL', 'BNB'],
        'commodity_assets': ['GOLD', 'SILVER', 'CRUDE'],
        'crypto_min_pct': 0.10,
        'crypto_max_pct': 0.80,
        'commodity_min_pct': 0.05,
        'commodity_max_pct': 0.40,
        'per_asset_max': 0.35,
    }

    if args.constraints:
        for pair in args.constraints.split(','):
            if '=' in pair:
                k, v = pair.split('=', 1)
                try:
                    constraints[k] = float(v)
                except ValueError:
                    constraints[k] = v

    # Allocate
    allocator = RiskParityAllocator({'constraints': constraints})

    print(f"\n{'='*60}")
    print(f"  Risk Parity Allocator - Method: {args.method.upper()}")
    print(f"  Lookback: {args.lookback} days")
    print(f"{'='*60}")

    weights = allocator.allocate(returns_df, method=args.method, constraints=constraints)

    print(f"\n  Weights:")
    for asset, w in weights.sort_values(ascending=False).items():
        print(f"    {asset:>8}: {w:.4f} ({w*100:.1f}%)")

    # Risk contributions
    rc = allocator.get_risk_contributions(returns_df, weights)
    print(f"\n  Risk Contributions:")
    for asset, r in rc.sort_values(ascending=False).items():
        print(f"    {asset:>8}: {r:.4f} ({r*100:.1f}%)")

    # Regime detection
    regime = allocator._detect_regime(returns_df)
    print(f"\n  Detected Regime: {regime}")

    # Portfolio stats
    port_ret = (returns_df * weights).sum(axis=1)
    ann_ret = port_ret.mean() * 252
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    print(f"\n  Portfolio Stats:")
    print(f"    Annual Return:  {ann_ret:.2%}")
    print(f"    Annual Vol:     {ann_vol:.2%}")
    print(f"    Sharpe Ratio:   {sharpe:.3f}")

    # Output JSON
    result = {
        'method': args.method,
        'regime': regime,
        'weights': {k: float(v) for k, v in weights.items()},
        'risk_contributions': {k: float(v) for k, v in rc.items()},
        'portfolio_stats': {
            'annual_return': float(ann_ret),
            'annual_volatility': float(ann_vol),
            'sharpe_ratio': float(sharpe),
        },
    }

    print(f"\n  {json.dumps(result, indent=2)}")
    return result


if __name__ == "__main__":
    main()
