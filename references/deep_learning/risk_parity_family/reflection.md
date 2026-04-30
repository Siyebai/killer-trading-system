# Risk Parity Deep Learning Reflection

## What I Truly Understood

1. **Risk parity is not about "equal weights" -- it's about equal pain contribution.** Each asset should hurt the portfolio equally when it moves against you. This reframes the entire allocation problem from "how much to allocate" to "how much risk am I taking."

2. **The progression 1/N → IVP → ERC → HRP → HERC is really a progression of what information you're willing to use and trust.**
   - 1/N: Use nothing (pure ignorance)
   - IVP: Use only volatility (trust variances, ignore correlations)
   - ERC: Use covariance matrix (trust both variances and correlations)
   - HRP: Use covariance + hierarchy (distrust matrix inversion, trust clustering)
   - HERC: Use covariance + optimal clustering (distrust geometric splitting, trust topology)

3. **More information ≠ better results.** My experiment showed that 1/N had the best cross-scenario average Sharpe (0.431). Using more estimated inputs (covariance, clusters) can help in specific regimes but hurts in others because estimation error dominates.

## What I Had Wrong Before

1. **I assumed HRP was always better than ERC.** The experiment proved this wrong. HRP's tree-based bisection can create extreme allocations (60% GOLD) that are theoretically "risk-balanced" at the cluster level but practically dangerous for a crypto-focused portfolio.

2. **I thought correlation was always useful.** In extreme volatility regimes, correlations spike to 1.0 across all risky assets, making the correlation matrix nearly singular. At that point, using correlation actually hurts -- IVP (which ignores it) becomes safer.

3. **I didn't appreciate the importance of constraints.** Pure risk parity without asset-class bounds can produce legally correct but practically absurd allocations. For our system (which is fundamentally a crypto trading system), we must constrain crypto exposure to remain dominant.

## The Biggest Fragility in Real Markets

**Correlation instability** is the Achilles heel of all risk parity methods.

The theory assumes the covariance matrix estimated from past data is representative of future risk. In reality:
- Crypto correlations are regime-dependent: 0.3 in normal markets, 0.9 during liquidations
- The transition happens faster than the estimation window (60-day lookback lags 1-day correlation spikes)
- Negative correlations (BTC vs GOLD) can flip positive during global risk-off events

The 2022 Terra/Luna/FTX cascades demonstrated that "diversification" in crypto is a mirage -- all crypto assets move together during stress, and even commodities initially correlated positively before decoupling.

**The practical implication**: Any risk parity method must have a **regime detection** front-end that switches to IVP (or even equal weight) when correlations become unreliable.

## What the Experiment Revealed That Contradicts Theory

1. **ERC's negative risk contributions for GOLD/SILVER** (-1.6%, -0.1%) indicate these assets are diversifiers, not risk sources. Standard risk parity theory treats negative RC as a numerical artifact, but in practice, it's the most valuable feature -- it tells you which assets reduce portfolio risk.

2. **HRP's extreme allocation to GOLD/SILVER** happens because the dendrogram's binary split separates crypto from commodities, then equal-variance-weights commodities much higher. This is mathematically correct but practically wrong for a crypto trading system. Theory doesn't account for investor mandates or asset-class constraints.

3. **1/N's robustness** contradicts the common belief that sophisticated allocation always beats naive. DeMiguel et al. (2009) showed this for equity portfolios, and my experiment confirms it for crypto+commodity portfolios. The lesson: estimation error is the dominant factor, and simplicity is a feature.

## What to Study Next

1. **Dynamic Conditional Correlation (DCC-GARCH)**: Time-varying correlation estimation that adapts faster than rolling-window approaches. This directly addresses the biggest weakness identified above.

2. **CVaR-based risk parity**: Replace variance with Conditional Value-at-Risk as the risk measure. Crypto's fat tails make variance-based risk parity underestimate tail risk.

3. **Minimum Spanning Tree (MST) asset selection**: Before allocating, use MST to identify which assets provide true diversification (peripheral nodes) vs. redundant exposure (central nodes). The Guo et al. (2025) paper on GMSC-enhanced HRP is directly relevant.

4. **Online risk parity**: Incremental algorithms that update weights without full recomputation, suitable for real-time trading systems.
