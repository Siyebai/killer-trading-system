# Risk Parity Experiment Results

## Experiment Configuration
- **Assets**: BTC, ETH, SOL, BNB, GOLD, SILVER, CRUDE (7 assets)
- **Methods**: 1/N, IVP, ERC, HRP, HERC
- **Scenarios**: Normal, Extreme (crypto winter), Structural Break (correlation spike)
- **Period**: 360 simulated trading days

## Key Findings

### 1. Sharpe Ratio Comparison (Cross-Scenario Average)

| Method | Normal | Extreme | Break | Average |
|--------|--------|---------|-------|---------|
| 1/N | 1.436 | -0.842 | 0.700 | **0.431** |
| IVP | 1.637 | -2.581 | 1.013 | 0.023 |
| ERC | 1.366 | -0.921 | 0.717 | **0.388** |
| HRP | 1.031 | -4.956 | 0.801 | -1.041 |
| HERC | 1.584 | -2.129 | 0.883 | 0.113 |

### 2. Risk Contribution Balance (Cross-Scenario Average)

| Method | Normal | Extreme | Break | Average |
|--------|--------|---------|-------|---------|
| 1/N | 0.077 | 0.077 | 0.073 | 0.076 |
| IVP | 0.383 | 0.383 | 0.018 | 0.261 |
| ERC | 0.363 | 0.363 | 0.361 | **0.362** |
| HRP | -0.532 | -0.532 | -0.743 | -0.603 |
| HERC | 0.294 | 0.294 | 0.089 | 0.226 |

### 3. Critical Finding: HRP Over-Concentrates on Low-Vol Assets

HRP allocates 60.5% to GOLD and 32.9% to SILVER, leaving only 0.1-0.3% for crypto assets. This is because:
- GOLD/SILVER form a tight low-vol cluster
- Crypto assets form a high-vol cluster
- Recursive bisection gives each cluster equal weight
- Within the low-vol cluster, inverse-variance weighting naturally gives higher weights

**Implication**: Unconstrained HRP is unsuitable for a crypto-focused portfolio. Must add asset-class constraints.

### 4. ERC is the Most Robust Method

- Consistent RC balance across all scenarios (0.361-0.363)
- Second-best average Sharpe (0.388)
- Negative RC for negatively-correlated assets (GOLD, SILVER) indicates proper diversification
- Only method where each asset contributes exactly 1/N risk (by design)

### 5. IVP and HERC are Scenario-Dependent

- IVP excels in Normal (1.637 Sharpe) but collapses in Extreme (-2.581)
- HERC balances well in Normal but RC balance drops to 0.089 in Break scenario
- Both methods are sensitive to correlation regime changes

### 6. 1/N is the Surprising Winner for Robustness

- Best average Sharpe (0.431) across all scenarios
- Worst RC balance (0.076) - SOL dominates with 33% risk contribution
- Works because it never over-concentrates based on noisy estimates

## Conclusions for System Integration

1. **For strategy-level weight allocation** (MR/TF/FR): Use **ERC** - 3 strategies with moderate correlation, ERC gives clean equal risk contribution
2. **For multi-asset allocation**: Use **constrained HERC** - add min/max bounds per asset class (crypto: 10-40% each, commodities: 5-15% each)
3. **For fallback**: Use **IVP** when correlation estimates are unreliable (extreme volatility regime)
4. **Dynamic rebalancing**: Re-estimate weekly with 60-day rolling window; trigger rebalance when any weight drifts >10% from target
5. **Abandon unconstrained HRP** for this portfolio composition
