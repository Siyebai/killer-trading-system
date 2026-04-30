# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Experiment: Risk Parity Family Comparison
Compares 1/N, IVP, ERC, HRP, HERC on simulated crypto portfolio data

Tests:
  - Normal market conditions
  - Extreme volatility regime (2022-style crypto winter)
  - Structural break (correlation spike during liquidation cascade)

Usage:
  python scripts/experiment_risk_parity.py [--scenario normal|extreme|break|all]
"""
import argparse
import json
import numpy as np
import pandas as pd
from datetime import datetime
from scipy.cluster.hierarchy import linkage, fcluster, leaves_list
from scipy.spatial.distance import squareform
from scipy.optimize import minimize


# ============================================================
# Portfolio Allocation Methods
# ============================================================

class EqualWeight:
    """1/N Portfolio"""
    name = "1/N"
    def allocate(self, returns_df):
        n = len(returns_df.columns)
        return pd.Series(1.0 / n, index=returns_df.columns)


class InverseVolatility:
    """Inverse Volatility Portfolio (IVP)"""
    name = "IVP"
    def allocate(self, returns_df):
        vols = returns_df.std()
        inv_vols = 1.0 / vols.replace(0, np.nan).fillna(1e-6)
        weights = inv_vols / inv_vols.sum()
        return weights


class EqualRiskContribution:
    """Equal Risk Contribution (ERC) - Maillard et al. (2010)"""
    name = "ERC"
    def allocate(self, returns_df):
        cov = returns_df.cov().values
        n = cov.shape[0]
        cols = returns_df.columns

        # Objective: minimize sum of squared differences in risk contributions
        def objective(w):
            w = np.array(w)
            port_var = np.dot(w, np.dot(cov, w))
            if port_var <= 0:
                return 1e10
            sigma_p = np.sqrt(port_var)
            mrc = np.dot(cov, w) / sigma_p
            rc = w * mrc
            rc_pct = rc / rc.sum()
            target = 1.0 / n
            return np.sum((rc_pct - target) ** 2)

        # Constraints: sum(w) = 1, w >= 0
        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}
        bounds = [(0.01, 1.0)] * n
        x0 = np.ones(n) / n

        result = minimize(objective, x0, method='SLSQP',
                         bounds=bounds, constraints=constraints,
                         options={'maxiter': 1000, 'ftol': 1e-12})

        if result.success:
            weights = pd.Series(result.x, index=cols)
        else:
            # Fallback to IVP if optimization fails
            weights = InverseVolatility().allocate(returns_df)

        return weights / weights.sum()


class HRPPortfolio:
    """Hierarchical Risk Parity (HRP) - De Prado (2016)"""
    name = "HRP"
    def allocate(self, returns_df):
        cov = returns_df.cov()
        corr = returns_df.corr()

        # Step 1: Distance matrix
        dist = np.sqrt(0.5 * (1 - corr))
        np.fill_diagonal(dist.values, 0)

        # Step 2: Hierarchical clustering
        condensed = squareform(dist.values, checks=False)
        link = linkage(condensed, method='single')

        # Step 3: Quasi-diagonalization (seriation)
        order = leaves_list(link)
        sorted_cols = returns_df.columns[order]

        # Step 4: Recursive bisection
        weights = pd.Series(1.0, index=sorted_cols)
        clusters = [list(range(len(sorted_cols)))]

        while clusters:
            new_clusters = []
            for cluster in clusters:
                if len(cluster) <= 1:
                    continue
                mid = len(cluster) // 2
                left = cluster[:mid]
                right = cluster[mid:]

                # Calculate cluster variances
                left_cols = sorted_cols[left]
                right_cols = sorted_cols[right]

                left_var = self._cluster_variance(cov.loc[left_cols, left_cols])
                right_var = self._cluster_variance(cov.loc[right_cols, right_cols])

                # Allocate weight inversely proportional to variance
                alpha = 1.0 - left_var / (left_var + right_var + 1e-10)

                # Scale existing weights
                for i in left:
                    weights.iloc[i] *= alpha
                for i in right:
                    weights.iloc[i] *= (1 - alpha)

                new_clusters.extend([left, right])

            clusters = new_clusters

        return weights / weights.sum()

    def _cluster_variance(self, cov_sub):
        """Inverse-variance portfolio variance for a cluster"""
        n = len(cov_sub)
        if n == 1:
            return cov_sub.iloc[0, 0]
        vols = np.sqrt(np.diag(cov_sub))
        inv_var = 1.0 / (vols ** 2 + 1e-10)
        w = inv_var / inv_var.sum()
        return float(w @ cov_sub.values @ w)


class HERCPortfolio:
    """Hierarchical Equal Risk Contribution (HERC) - Raffinot (2017)"""
    name = "HERC"
    def allocate(self, returns_df):
        cov = returns_df.cov()
        corr = returns_df.corr()
        n_assets = len(returns_df.columns)
        cols = returns_df.columns

        # Step 1: Distance and clustering
        dist = np.sqrt(0.5 * (1 - corr))
        np.fill_diagonal(dist.values, 0)
        condensed = squareform(dist.values, checks=False)
        link = linkage(condensed, method='ward')

        # Step 2: Find optimal number of clusters (silhouette-like)
        best_k = self._optimal_clusters(link, n_assets)
        cluster_labels = fcluster(link, t=best_k, criterion='maxclust')

        # Step 3: Equal risk allocation across clusters
        n_clusters = best_k
        cluster_risk_budget = 1.0 / n_clusters

        # Step 4: Within-cluster allocation (inverse volatility)
        weights = pd.Series(0.0, index=cols)
        for c in range(1, n_clusters + 1):
            mask = cluster_labels == c
            cluster_cols = cols[mask]
            if len(cluster_cols) == 0:
                continue

            # Within-cluster: inverse volatility
            cluster_returns = returns_df[cluster_cols]
            cluster_vols = cluster_returns.std()
            inv_vols = 1.0 / (cluster_vols + 1e-10)
            within_weights = inv_vols / inv_vols.sum()

            # Scale by cluster risk budget
            for col in cluster_cols:
                weights[col] = within_weights[col] * cluster_risk_budget

        return weights / weights.sum()

    def _optimal_clusters(self, link, n_assets):
        """Find optimal cluster count using gap heuristic"""
        if n_assets <= 2:
            return 1
        if n_assets <= 4:
            return 2

        # Try different cluster counts and pick the one with most balanced sizes
        best_k = 2
        best_balance = 0

        for k in range(2, min(n_assets, 6)):
            labels = fcluster(link, t=k, criterion='maxclust')
            sizes = pd.Series(labels).value_counts()
            balance = sizes.min() / sizes.max()  # Higher = more balanced

            if balance > best_balance:
                best_balance = balance
                best_k = k

        return best_k


# ============================================================
# Data Generation
# ============================================================

def generate_crypto_returns(scenario='normal', n_days=360, seed=42):
    """Generate realistic crypto portfolio returns"""
    np.random.seed(seed)

    params = {
        'BTC': {'mu': 0.0005, 'sigma': 0.035, 'beta': 1.0},
        'ETH': {'mu': 0.0006, 'sigma': 0.045, 'beta': 1.2},
        'SOL': {'mu': 0.0008, 'sigma': 0.060, 'beta': 1.5},
        'BNB': {'mu': 0.0003, 'sigma': 0.032, 'beta': 0.9},
        'GOLD': {'mu': 0.0002, 'sigma': 0.010, 'beta': -0.1},
        'SILVER': {'mu': 0.0001, 'sigma': 0.015, 'beta': -0.05},
        'CRUDE': {'mu': 0.0001, 'sigma': 0.020, 'beta': 0.1},
    }

    assets = list(params.keys())

    if scenario == 'normal':
        market_factor = np.random.randn(n_days) * 0.02
    elif scenario == 'extreme':
        # Crypto winter: high vol, strong negative drift, high correlation
        market_factor = np.random.randn(n_days) * 0.05 - 0.002
        for k in params:
            params[k]['sigma'] *= 2.5
            params[k]['mu'] -= 0.003
    elif scenario == 'break':
        # Correlation spike in second half
        market_factor = np.concatenate([
            np.random.randn(n_days // 2) * 0.02,
            np.random.randn(n_days - n_days // 2) * 0.06 - 0.001
        ])
        # Increase beta (correlation) in second half for crypto assets
        for k in ['BTC', 'ETH', 'SOL', 'BNB']:
            original_beta = params[k]['beta']
            params[k]['beta'] = original_beta  # Keep original, correlation comes from market_factor

    returns = {}
    for asset, p in params.items():
        idio = np.random.randn(n_days) * p['sigma'] * 0.5
        returns[asset] = p['mu'] + p['beta'] * market_factor + idio

    return pd.DataFrame(returns, index=pd.date_range('2024-01-01', periods=n_days, freq='D'))


# ============================================================
# Evaluation Metrics
# ============================================================

def evaluate_portfolio(returns_df, weights, method_name):
    """Evaluate portfolio performance metrics"""
    w = weights.reindex(returns_df.columns).fillna(0).values
    port_returns = returns_df.values @ w

    # Basic stats
    mean_ret = np.mean(port_returns) * 252
    vol = np.std(port_returns) * np.sqrt(252)
    sharpe = mean_ret / vol if vol > 0 else 0
    max_dd = np.max(np.maximum.accumulate(port_returns) - port_returns)

    # Risk contribution balance
    cov = returns_df.cov().values
    port_var = w @ cov @ w
    if port_var > 0:
        mrc = (cov @ w) / np.sqrt(port_var)
        rc = w * mrc
        rc_pct = rc / rc.sum()
        rc_balance = 1.0 - np.std(rc_pct) / np.mean(rc_pct)  # Higher = more balanced
    else:
        rc_pct = np.zeros(len(w))
        rc_balance = 0

    # Turnover (proxy: weight concentration)
    hhi = np.sum(w ** 2)  # Herfindahl index

    # CVaR (95%)
    sorted_rets = np.sort(port_returns)
    cvar_idx = int(len(sorted_rets) * 0.05)
    cvar = -np.mean(sorted_rets[:cvar_idx]) if cvar_idx > 0 else 0

    return {
        'method': method_name,
        'annual_return': float(mean_ret),
        'annual_volatility': float(vol),
        'sharpe_ratio': float(sharpe),
        'max_drawdown': float(max_dd),
        'risk_contribution_balance': float(rc_balance),
        'weight_hhi': float(hhi),
        'cvar_95': float(cvar),
        'risk_contributions': {returns_df.columns[i]: float(rc_pct[i]) for i in range(len(returns_df.columns))},
    }


# ============================================================
# Main Experiment
# ============================================================

def run_experiment(scenario='all'):
    """Run the full comparison experiment"""
    allocators = [
        EqualWeight(),
        InverseVolatility(),
        EqualRiskContribution(),
        HRPPortfolio(),
        HERCPortfolio(),
    ]

    scenarios = ['normal', 'extreme', 'break'] if scenario == 'all' else [scenario]
    all_results = {}

    for sc in scenarios:
        print(f"\n{'='*70}")
        print(f"  SCENARIO: {sc.upper()}")
        print(f"{'='*70}")

        returns = generate_crypto_returns(scenario=sc)
        results = []

        # Display correlation matrix
        corr = returns.corr()
        print(f"\n  Correlation Matrix (crypto assets):")
        crypto_cols = ['BTC', 'ETH', 'SOL', 'BNB']
        for c1 in crypto_cols:
            row = "  " + f"{c1:>6}: "
            row += "  ".join(f"{corr.loc[c1,c2]:.2f}" for c2 in crypto_cols)
            print(row)

        print(f"\n  {'Method':<8} {'Return':>9} {'Vol':>9} {'Sharpe':>8} {'MaxDD':>8} {'RC-Bal':>8} {'CVaR95':>8}")
        print("  " + "-"*60)

        for allocator in allocators:
            try:
                weights = allocator.allocate(returns)
                metrics = evaluate_portfolio(returns, weights, allocator.name)
                results.append(metrics)

                print(f"  {allocator.name:<8} {metrics['annual_return']:>8.2%} {metrics['annual_volatility']:>8.2%} "
                      f"{metrics['sharpe_ratio']:>7.3f} {metrics['max_drawdown']:>7.4f} "
                      f"{metrics['risk_contribution_balance']:>7.3f} {metrics['cvar_95']:>7.4f}")

                # Risk contributions
                rc_str = "    RC: " + "  ".join(f"{k}={v:.1%}" for k, v in metrics['risk_contributions'].items())
                print(rc_str)

            except Exception as e:
                print(f"  {allocator.name:<8} ERROR: {e}")

        all_results[sc] = results

    # Cross-scenario comparison
    print(f"\n{'='*70}")
    print(f"  CROSS-SCENARIO COMPARISON: Sharpe Ratio")
    print(f"{'='*70}")
    print(f"  {'Method':<8} {'Normal':>10} {'Extreme':>10} {'Break':>10} {'Average':>10}")
    print("  " + "-"*50)

    for allocator in allocators:
        sharpes = []
        for sc in scenarios:
            matching = [r for r in all_results[sc] if r['method'] == allocator.name]
            if matching:
                sharpes.append(matching[0]['sharpe_ratio'])
            else:
                sharpes.append(0)
        avg_sharpe = np.mean(sharpes)
        print(f"  {allocator.name:<8} " + "  ".join(f"{s:>9.3f}" for s in sharpes) + f"  {avg_sharpe:>9.3f}")

    # RC Balance comparison
    print(f"\n  Cross-Scenario: Risk Contribution Balance (higher = more balanced)")
    print(f"  {'Method':<8} {'Normal':>10} {'Extreme':>10} {'Break':>10} {'Average':>10}")
    print("  " + "-"*50)

    for allocator in allocators:
        balances = []
        for sc in scenarios:
            matching = [r for r in all_results[sc] if r['method'] == allocator.name]
            if matching:
                balances.append(matching[0]['risk_contribution_balance'])
            else:
                balances.append.append(0)
        avg_balance = np.mean(balances)
        print(f"  {allocator.name:<8} " + "  ".join(f"{b:>9.3f}" for b in balances) + f"  {avg_balance:>9.3f}")

    # Generate structured output
    output = {
        'timestamp': datetime.now().isoformat(),
        'scenarios': {},
    }
    for sc, results in all_results.items():
        output['scenarios'][sc] = results

    return output


def main():
    parser = argparse.ArgumentParser(description='Risk Parity Family Comparison Experiment')
    parser.add_argument('--scenario', choices=['normal', 'extreme', 'break', 'all'],
                       default='all', help='Test scenario')
    parser.add_argument('--output', default=None, help='Output JSON file path')
    args = parser.parse_args()

    result = run_experiment(args.scenario)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\n  Results saved to {args.output}")
    else:
        print("\n  [Experiment Complete]")

    return result


if __name__ == "__main__":
    main()
