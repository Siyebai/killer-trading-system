# 配置文件说明

## strategy_v14_optimized.json (推荐)
v1.4优化版配置，WR=62.6%，适合追求高胜率。

```json
{
  "version": "v1.4-optimized",
  "mode": "FIXED_RISK",
  "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
  "strategies": {
    "SHORT": {
      "n_bars": 7,          // 7连涨触发
      "min_pct": 0.002,     // 累计涨0.2%
      "adx_min": 20,        // ADX阈值
      "tp_atr_mult": 1.0,   // TP=1×ATR
      "sl_atr_mult": 1.0,   // SL=1×ATR
      "expected_wr": 0.626  // 预期胜率62.6%
    },
    "LONG": {
      "n_bars": 4,          // 4连跌触发
      "min_pct": 0.002,
      "adx_min": 20,
      "ema_trend": 200,     // EMA200趋势过滤
      "tp_atr_mult": 0.8,   // TP=0.8×ATR (快速止盈)
      "sl_atr_mult": 1.0,
      "expected_wr": 0.626
    }
  },
  "risk_control": {
    "mode": "FIXED",        // 固定风险金额 (非复利)
    "risk_per_trade_u": 3.0,    // 每笔风险3U
    "max_daily_loss_u": 15.0,   // 日熔断15U
    "max_monthly_loss_u": 45.0, // 月熔断45U
    "consecutive_loss_reduce": 3,  // 连亏3笔降仓
    "reduced_risk_u": 1.5     // 降仓后1.5U/笔
  }
}
```

## strategy_v13_multi.json
v1.3多品种版，信号频率更高 (~100笔/月/品种)。

**区别**: n=6 (vs v1.4的n=7)，WR=59% (vs 62.6%)

## 选择建议
| 需求 | 推荐配置 |
|------|---------|
| 高胜率优先 | v1.4 (WR=62.6%) |
| 高频率优先 | v1.3 (100笔/月) |
| 保守实盘 | v1.4 + 单品种BTC |
| 激进实盘 | v1.4 + 4品种 |
