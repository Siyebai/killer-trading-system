# MLOps for Quant Trading: Closed-Loop Integration

## Date: 2026-04-29
## Topic: MLOps闭环架构在量化交易中的应用

## Core Concepts

### 1. MLOps Closed-Loop Pipeline
- Training -> Deployment -> Monitoring -> Feedback -> Retrain
- Metadata management > dashboards
- Most "model problems" are actually data problems
- Feature Store ensures train/serving consistency

### 2. Signal-to-Asset Incubation
- Signal Pool -> Strategy Generator -> Incubator -> Screener -> Asset Registry
- Incubation and portfolio construction linkage
- Systematic, engineered, automated

### 3. Adaptive Strategy Weighting
- Multi-Step DQN: annualized return 64.9% -> 79.4%
- Risk-aware RL reward function
- DDPG multi-scale features
- Strategy weights adjusted by market regime

## Key Formulas

### Feedback Loop Drift Detection
```
drift = recent_win_rate - baseline_win_rate
if |drift| > threshold:
    trigger_weight_rebalance()
```

### Adaptive Weight Update
```
new_weight = old_weight * decay + performance_adjustment
normalize(all_weights)  # sum to 1.0
```

### Kelly Position with Feedback
```
kelly_f = (b*p - q) / b
position_ratio = min(half_kelly_f, max_position)
actual_pnl = signal_pnl * position_ratio  # not full equity
```

## Application to Current System

| Theory Point | System Module | Integration |
|-------------|---------------|-------------|
| Closed-loop pipeline | closed_loop_engine.py | DataPipeline -> SignalPipeline -> StrategyOrchestrator -> PortfolioAllocator -> RiskManager -> FeedbackLoop |
| Signal incubation | SignalConfirmationPipeline | Multi-level confirmation with scoring |
| Adaptive weighting | AdaptiveStrategyWeights | Performance-based decay + drift detection |
| Feature Store consistency | ConfigManager | Single config.json for all modules |

## Critical Bugs Found During Integration

### BUG #1: Circuit Breaker Time Reference
- **Problem**: `datetime.now()` in backtest uses system time, not backtest time
- **Impact**: Circuit breaker permanently triggered after first loss
- **Fix**: Pass `current_time` from DataFrame index to all circuit breaker methods

### BUG #2: Kelly Position Not Applied
- **Problem**: `position_size` calculated but `equity *= (1 + pnl)` uses full equity
- **Impact**: Unrealistic drawdowns, negative equity possible
- **Fix**: `actual_pnl = pnl * kelly_ratio; equity *= (1 + actual_pnl)`

### BUG #3: Strict AND Signal Logic
- **Problem**: RSI<30 AND Close<BB_lower never triggers simultaneously with 2.5σ BB
- **Impact**: Zero trades in backtest
- **Fix**: Scoring-based signal generation with independent condition evaluation

## Limitations & Caveats

1. Random walk data inherently unsuitable for directional strategies
2. Scoring thresholds need real market data calibration
3. Drift detection may overreact in high-volatility regimes
4. Adaptive weights need minimum trade history to be meaningful

## References

- MLOps for Quantitative Trading (CSDN, 2025)
- Signal-to-Asset Incubation Framework (36Kr, 2025)
- Multi-Step DQN for Adaptive Strategy Weighting (arXiv, 2025)
