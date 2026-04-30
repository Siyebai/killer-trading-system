# Risk Parity Family: Complete Theory Learning Notes

## 1. What Problem Does Risk Parity Solve?

### The Core Dilemma
Traditional portfolio construction (Markowitz MVO, 1952) requires estimating expected returns (mu) and the covariance matrix (Sigma). In practice:
- **mu is nearly impossible to estimate** -- small errors in expected return cause extreme weight shifts (Michaud, 1998: "estimation error maximization")
- **Sigma is more stable** but still noisy when N is large relative to T
- The **inversion of Sigma** amplifies estimation errors, producing unstable portfolios

Risk parity's insight: **abandon expected returns entirely** and allocate based only on risk. If you can't predict returns, at least diversify risk properly.

### Intuition
Imagine a 60/40 stock-bond portfolio. Capital is 60% stocks / 40% bonds. But stocks are 3-4x more volatile than bonds, so stocks contribute ~90% of portfolio risk. You're not really diversified -- you have a stock portfolio with a small bond decoration.

Risk parity asks: what if each asset contributed equally to total risk? Low-vol assets get higher capital weight, high-vol assets get lower weight. The result: true risk diversification.

---

## 2. The Evolution: 5 Generations of Risk Parity

### Generation 1: Equal Weight (1/N)
- **Formula**: w_i = 1/N for all i
- **Assumption**: All assets have same risk and zero correlation
- **When optimal**: When all assets have identical Sharpe ratios and identical pairwise correlations (DeMiguel et al., 2009)
- **Weakness**: Ignores all risk information. With BTC at 5% daily vol and BNB at 3.5%, equal weight over-allocates risk to BTC

### Generation 2: Inverse Volatility (IVP)
- **Formula**: w_i proportional to 1/sigma_i
- **Assumption**: Assets are uncorrelated (rho=0)
- **When optimal**: When all assets have same Sharpe ratio and zero correlation
- **Weakness**: Ignores correlations. Two highly correlated assets (BTC, ETH) each get full inverse-vol weight, doubling exposure to the same risk factor
- **Implementation in our system**: This is essentially what Kelly position sizing does per-asset, ignoring cross-asset correlation

### Generation 3: Equal Risk Contribution (ERC)
- **Formula**: RC_i = w_i * (Sigma * w)_i / sigma_p = 1/N for all i
- **Key innovation**: Accounts for correlations via the full covariance matrix
- **When optimal**: When all assets have same Sharpe ratio (but arbitrary correlations)
- **Mathematical structure**: Minimize sum_i sum_j (RC_i - RC_j)^2 subject to sum(w) = 1, w >= 0
- **Solving**: No closed-form solution when rho != 0; requires numerical optimization (SQP, scipy minimize)
- **Weakness**: Requires inverting/optimizing with the full covariance matrix, which is itself noisy. With many correlated assets, the optimization becomes ill-conditioned
- **Key paper**: Maillard, Roncalli, Teiletche (2010) "The Properties of Equally Weighted Risk Contribution Portfolios"

### Generation 4: Hierarchical Risk Parity (HRP)
- **Author**: Marcos Lopez de Prado (2016) "Building Diversified Portfolios that Outperform Out-of-Sample"
- **Core insight**: Don't fight the covariance matrix -- restructure the problem using graph theory
- **Three-step algorithm**:
  1. **Tree clustering**: Compute correlation distance d_ij = sqrt(0.5*(1-rho_ij)), then hierarchical clustering (single/ward linkage) to build a dendrogram
  2. **Quasi-diagonalization**: Reorder the covariance matrix so correlated assets are adjacent (seriation)
  3. **Recursive bisection**: Top-down, split each cluster in half, allocate weight proportionally to inverse cluster variance
- **Why it works**: The dendrogram captures the hierarchical dependency structure. By splitting along tree branches, you never put correlated assets on opposite sides of a bisection, avoiding the instability that plagues MVO/ERC
- **Key advantage over ERC**: No matrix inversion, no optimization -- just tree traversal. Robust to estimation noise
- **Weakness**: The bisection is purely geometric (split at midpoint), not optimal. Two assets in the same branch always end up in the same sub-cluster, even if they're dissimilar

### Generation 5: Hierarchical Equal Risk Contribution (HERC)
- **Author**: Thomas Raffinot (2017) "Hierarchical Equal Risk Contribution"
- **Key improvement over HRP**: Replace naive bisection with **cluster-based allocation**
  - HRP: Split at midpoint (geometric)
  - HERC: Split at actual cluster boundaries (topological)
- **Algorithm**:
  1. Same tree clustering as HRP
  2. Cut the dendrogram at optimal level (using gap statistic or silhouette score)
  3. Allocate risk budget equally across clusters
  4. Within each cluster, allocate using ERC or inverse-vol
- **Advantage**: More balanced risk allocation, better handles asymmetric clusters
- **Empirical finding (skfolio)**: HERC outperforms HRP on average (better Mean-CVaR ratio), but HRP is more stable (lower standard deviation of returns)

---

## 3. Mathematical Intuition for Each Method

### Risk Contribution Decomposition
For portfolio with weights w and covariance Sigma:
- Portfolio variance: sigma_p^2 = w' * Sigma * w
- Marginal risk contribution of asset i: MRC_i = (Sigma * w)_i / sigma_p
- Risk contribution of asset i: RC_i = w_i * MRC_i = w_i * (Sigma * w)_i / sigma_p
- By definition: sum(RC_i) = sigma_p

**Key insight**: RC_i depends on both w_i AND all correlations via Sigma*w. Even a small-weight asset can dominate risk if it's highly correlated with everything else.

### Why HRP Avoids Matrix Inversion
ERC requires solving: RC_i = RC_j for all i,j, which involves the inverse of Sigma (implicitly through optimization). When Sigma is ill-conditioned (high correlations), this blows up.

HRP avoids this by:
1. Replacing the full optimization with a tree structure
2. Computing only cluster variances (small sub-matrices)
3. Using only inverse-variance weighting (1/sigma^2) within each small cluster

The price: HRP is suboptimal (not on the efficient frontier). But it's robust, and in sample-out-of-sample tests, robustness beats theoretical optimality.

---

## 4. Paper Deep Dive

### Paper 1: De Prado (2016) - HRP Foundation
**Key assumptions**:
1. Correlation structure has hierarchical properties (true in most markets due to sector/country factors)
2. Ledoit-Wolf shrinkage covariance is a reasonable estimate
3. Single-linkage clustering captures the dependency structure

**Fragility points**:
1. Single-linkage suffers from "chaining" -- can create long, thin clusters that don't represent true groups
2. The quasi-diagonalization depends on the clustering quality; bad clustering = bad allocation
3. Recursive bisection at midpoint is arbitrary -- no theoretical justification for 50/50 split position
4. No consideration of tail dependencies (all based on linear correlation)

### Paper 2: Raffinot (2017) - HERC
**Key improvement**: Cuts dendrogram at optimal level using dynamic programming or gap statistic, then applies equal risk budget across identified clusters.

**Fragility points**:
1. Cluster number selection (K) is itself an estimation problem
2. Within-cluster allocation still assumes either zero correlation (IVP) or uses ERC (which has its own issues)
3. Not tested on cryptocurrency data (all empirical work on equities/bonds)

### Paper 3: Guo et al. (2025, Huaan Securities) - MST-Enhanced HRP
**Key innovation**: Use Minimum Spanning Tree (MST) peripheral nodes for asset selection before HRP allocation. Two correlation matrices tested: full cross-correlation (FC) and global motion subtracted correlation (GMSC).

**Empirical findings**:
- GMSC (which removes common market factor) outperforms FC in bear markets
- FC outperforms GMSC in bull markets
- Peripheral nodes (edge of MST) provide better diversification than central nodes

**Relevance to crypto**: The BTC-dominance factor is exactly the "global motion" that GMSC removes. This suggests using GMSC-type correlation for our multi-crypto portfolio.

---

## 5. Knowledge Map: Relationship to Current System

```
Current System Modules:
                                                   
  multi_strategy_fusion_v5.py                      
  ├── SignalAggregator (static weight 0.33 each)  ← NEEDS UPGRADE to ERC/HRP
  ├── PositionManager (Kelly sizing)              ← NEEDS cross-asset risk budget
  └── MultiStrategyFusionV5 (top-level engine)                      
                                                   
  portfolio_hrp.py                                 
  ├── HierarchicalRiskParity (HRP only)           ← NEEDS ERC + HERC variants
  └── MultiSymbolHRPAllocator (4 crypto)          ← NEEDS real data integration
                                                   
  closed_loop_engine.py                            
  ├── AdaptiveStrategyWeights (softmax)           ← NEEDS risk-based weighting
  └── RiskManager (circuit breaker only)          ← NEEDS portfolio-level risk mgmt
                                                   
  config.json                                      
  └── SYMBOL_CONFIG weights: {BTC:0.4, ETH:0.25, SOL:0.2, BNB:0.15}  ← STATIC!
```

**Current gaps**:
1. **Strategy weights are static** (0.33 each in fusion engine, fixed in config.json)
2. **No ERC implementation** -- the system jumps from IVP (Kelly) to HRP, skipping the most practical method
3. **HRP is disconnected** from the main trading loop -- it exists as a standalone module but isn't called during position allocation
4. **No risk contribution monitoring** -- the system tracks PnL but not how much risk each asset/strategy contributes
5. **No dynamic rebalancing** -- weights should update as correlations change

---

## 6. Data Flow Diagram for Integrated Risk Parity

```
Market Data (OHLCV for N assets)
        │
        ▼
  Returns Calculator (pct_change)
        │
        ▼
  ┌─────────────────────────────────────────┐
  │   Correlation Estimator                 │
  │   ├── Standard Pearson (FC)             │
  │   ├── DCC-GARCH (time-varying)          │
  │   └── GMSC (remove market factor)       │
  └──────────────┬──────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
  Asset Clustering    Risk Budget
  (dendrogram)        (target RC%)
        │                 │
        ▼                 ▼
  ┌─────────────────────────────────────┐
  │  Portfolio Allocator                │
  │  ├── 1/N (baseline)                │
  │  ├── IVP (inverse volatility)       │
  │  ├── ERC (equal risk contribution)  │
  │  ├── HRP (hierarchical RP)         │
  │  └── HERC (hierarchical ERC)       │
  └──────────────┬──────────────────────┘
                 │
                 ▼
  Position Weights (w_1, w_2, ..., w_N)
        │
        ▼
  ┌─────────────────────────────────────┐
  │  Risk Monitor                       │
  │  ├── Actual risk contribution       │
  │  ├── Deviation from target          │
  │  └── Rebalance trigger              │
  └─────────────────────────────────────┘
```

---

## 7. Key Formulas (Quick Reference)

| Method | Weight Formula | Input | Matrix Inversion |
|--------|---------------|-------|-----------------|
| 1/N | w_i = 1/N | None | No |
| IVP | w_i = (1/sigma_i) / sum(1/sigma_j) | sigma only | No |
| ERC | min sum(RC_i - RC_j)^2, s.t. RC_i = 1/N | Sigma (full) | Yes (implicit) |
| HRP | Recursive bisection on dendrogram | Sigma + dendrogram | No |
| HERC | Cluster-level ERC + within-cluster IVP/ERC | Sigma + clusters | Partial (within cluster) |

### Distance Metric for Clustering
d_ij = sqrt(0.5 * (1 - rho_ij))

This maps correlation [-1, 1] to distance [0, 1]:
- rho = 1 → d = 0 (identical)
- rho = 0 → d = 0.707 (uncorrelated)
- rho = -1 → d = 1 (perfectly anti-correlated)

### Cluster Variance (used in HRP bisection)
V_cluster = w' * Sigma_cluster * w, where w_i = (1/sigma_i^2) / sum(1/sigma_j^2)

This is the minimum-variance portfolio within the cluster (under zero-correlation assumption).

---

## 8. Practical Guidelines for Crypto Portfolios

1. **Use GMSC-type correlation**: Remove BTC common factor before clustering, so ETH/SOL/BNB's idiosyncratic risks are visible
2. **Shorter lookback for correlation**: Crypto correlations change fast. Use 30-60 day rolling windows (not 180+ like equities)
3. **HERC over HRP for 4-7 assets**: With few assets, the cluster structure matters more. HERC's explicit clustering handles this better
4. **IVP as fallback**: When correlation estimation is unreliable (extreme volatility), fall back to IVP which only needs volatilities
5. **Rebalance weekly**: Daily rebalancing creates excessive turnover; monthly is too slow for crypto
6. **Tail risk consideration**: Use CVaR-based risk contribution instead of variance-based, especially for crypto with fat tails
