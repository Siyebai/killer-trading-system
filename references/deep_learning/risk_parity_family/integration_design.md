# Risk Parity Integration Design

## 1. Current System Architecture (Problem)

```
multi_strategy_fusion_v5.py
  └── SignalAggregator: static weight 0.333 per strategy (MR/TF/FR)
  └── No correlation consideration between strategies

closed_loop_engine.py
  └── AdaptiveStrategyWeights: softmax + no-trade penalty
  └── Weights update by win/loss, not by risk contribution

portfolio_hrp.py
  └── HierarchicalRiskParity: standalone, not connected to trading loop
  └── No constraints, over-concentrates on low-vol assets

config.json
  └── SYMBOL_CONFIG: static capital weights (BTC:0.4, ETH:0.25, SOL:0.2, BNB:0.15)
```

## 2. Target Architecture

```
                    ┌────────────────────────────────┐
                    │   RiskParityAllocator           │
                    │   (new unified module)          │
                    ├────────────────────────────────┤
                    │ - ERC (strategy-level)          │
                    │ - Constrained HERC (asset-level)│
                    │ - IVP (fallback in extreme)     │
                    │ - Dynamic rebalance engine      │
                    │ - Risk contribution monitor     │
                    └──────────┬─────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
     Strategy Weights    Asset Weights    Risk Monitor
     (MR/TF/FR)         (7 assets)       (deviation alert)
              │                │                │
              ▼                ▼                ▼
     closed_loop_engine  position_sizer   circuit_breaker
```

## 3. Module Changes

### New Module: `scripts/risk_parity_allocator.py`
**Purpose**: Unified risk parity allocation engine replacing static weights

**Key classes**:
- `RiskParityAllocator`: Main interface
  - `allocate_strategies(returns_df)`: ERC for 3 strategies
  - `allocate_assets(returns_df, constraints)`: Constrained HERC for 7 assets
  - `get_risk_contributions()`: Monitor actual RC vs target
  - `needs_rebalance(current_weights, threshold=0.10)`: Rebalance trigger

**Constraints format**:
```json
{
  "crypto_min": 0.10,
  "crypto_max": 0.40,
  "commodity_min": 0.05,
  "commodity_max": 0.15,
  "per_asset_max": 0.35
}
```

### Modify: `scripts/closed_loop_engine.py`
**Changes**:
1. Replace `AdaptiveStrategyWeights` with `RiskParityAllocator.allocate_strategies()`
2. Add `_update_risk_parity_weights()` method called on each bar
3. Add risk contribution monitoring in `_update_metrics()`
4. Trigger rebalance when RC deviation > 15%

**Functions modified**:
- `_initialize_position_manager()`: Use risk parity for initial allocation
- `_process_signal()`: Apply risk-parity-weighted position sizing
- `_update_metrics()`: Log risk contributions

### Modify: `scripts/portfolio_hrp.py`
**Changes**:
1. Add `EqualRiskContribution` class (from experiment)
2. Add `ConstrainedHERC` class with asset bounds
3. Add `RiskParityAllocator` that selects method based on market state
4. Deprecate standalone `HierarchicalRiskParity` (keep for backward compat)

### Modify: `config.json`
**Changes**:
1. Add `risk_parity` section:
```json
{
  "risk_parity": {
    "strategy_method": "erc",
    "asset_method": "constrained_herc",
    "fallback_method": "ivp",
    "rebalance_frequency_days": 7,
    "rebalance_threshold": 0.10,
    "lookback_days": 60,
    "constraints": {
      "crypto_min_pct": 0.10,
      "crypto_max_pct": 0.40,
      "commodity_min_pct": 0.05,
      "commodity_max_pct": 0.15
    }
  }
}
```

### Modify: `SKILL.md`
**Changes**:
1. Add risk parity to operation steps
2. Update resource index
3. Add usage examples for risk parity allocator

## 4. Data Flow Change

**Before (static)**:
```
Signal → Kelly position → Execute
         (no cross-asset consideration)
```

**After (dynamic)**:
```
Signal → RiskParityAllocator → Kelly position × RC weight → Execute
         (correlation-aware)    (equalized risk contribution)
```

**Example**:
- Old: BTC gets 40% capital regardless of correlation regime
- New: When BTC-ETH correlation spikes to 0.85, ERC reduces BTC to 18% and ETH to 22%, allocating more to uncorrelated BNB and commodities

## 5. Expected Benefits

| Aspect | Before | After |
|--------|--------|-------|
| Strategy weights | Static 0.333 | Dynamic ERC (correlation-aware) |
| Asset allocation | Static config.json | Dynamic constrained HERC |
| Risk monitoring | Win rate only | RC deviation tracking |
| Rebalance | Manual | Automatic (weekly or threshold) |
| Extreme regime handling | None | IVP fallback + reduced exposure |

## 6. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| ERC optimization fails | Fallback to IVP (no optimization needed) |
| Correlation estimate noisy | Use Ledoit-Wolf shrinkage; 60-day lookback |
| Over-rebalancing (high turnover) | Weekly frequency + 10% threshold |
| Constraint violation | Cap per-asset weight at 35% |
| GMSC removes too much signal | Only use in extreme regime, normal uses standard correlation |

## 7. Implementation Priority

- **P0 (immediate)**: Create `risk_parity_allocator.py` with ERC + constrained HERC
- **P1 (this sprint)**: Integrate into `closed_loop_engine.py` for strategy weights
- **P2 (next sprint)**: Integrate into asset-level position sizing
- **P3 (future)**: Add dynamic regime-switching between ERC/HERC/IVP

## 8. Changes Requiring User Confirmation

- Replacing static strategy weights (0.333) with dynamic ERC weights
- Adding asset class constraints (crypto: 10-40%, commodity: 5-15%)
- Weekly rebalancing frequency and 10% threshold

## 9. Changes That Can Be Self-Executed

- Adding ERC class to portfolio_hrp.py
- Adding constrained HERC implementation
- Adding risk contribution monitoring
- Adding IVP fallback logic
- Unit tests for all new allocation methods
