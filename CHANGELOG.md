# Changelog

## v1.0.4 (2026-04-29 北京时间)
### 新增
- `scripts/paper_trading_v104.py`：多币种实时纸交易引擎
  - 支持 BTCUSDT / ETHUSDT / SOLUSDT / BNBUSDT
  - 支持 1m / 5m / 1h 三个时间框架
  - 接入真实 Binance 合约行情（binance-cli）
  - 本地模拟执行，不下真实订单（方案C）
  - 北京时间(UTC+8)时间戳
  - 自动保存扫描报告到 logs/
- `scripts/signal_engine_v9.py`：15m多因子引擎（已验证）
- `scripts/signal_engine_v10.py`：5m多因子引擎（已验证）

### 扫描结果（2026-04-29 09:25 CST）
- 最优：BNBUSDT 1h  WR54.5% RR1.41 EV+0.303%
- 第二：SOLUSDT 1h  WR44.4% RR2.26 EV+0.388%
- 结论：1m全部失败（WR<40%），1h表现最稳定

## v1.0.3 (2026-04-28)
- v4.0均值回归策略通过三段验证
- 均WR50.1% / EV+0.153% / 回撤0.18%（BTCUSDT 1H合约）
- 基准：sl=2.0ATR / tp=3.5ATR / max_hold=24根

## v1.0.5 (2026-04-29 北京时间)
### 新增
- `scripts/paper_engine_v105.py`：BTC+SOL双币种纸交易引擎（主网行情+本地模拟）
- `scripts/testnet_engine_v105.py`：Testnet执行引擎（环境就绪后可用）
- `scripts/signal_engine_advanced.py`：高级策略引擎v2（SuperTrend/Williams%R/CME缺口）
- `scripts/signal_engine_advanced_v3.py`：高级策略引擎v3（修复SuperTrend+MACD+RSI背离）
- `data/BTCUSDT_15m.json` 等：15m多币种数据

### 验证结论
- 累计验证策略：12个策略 × 11个品种周期组合 = 完整矩阵扫描
- 唯一通过三段全盈：v4.0均值回归 BTC/SOL 1h（EV+0.210%/+0.140%）
- SuperTrend修复：239次/5000根（修复前1-9次）
- 纸交易引擎启动首次信号：SOLUSDT SHORT（RSI超买+BB上轨）

### 架构
- 行情来源：binance-cli 主网实时数据
- 信号：signal_engine_v4.py（conf 0.74-0.86）
- 状态持久化：logs/paper_trade_state.json

## v1.0.6 (2026-04-29 北京时间)
### 新增
- `scripts/signal_engine_v11_ofi_vwap.py`：VWAP均值回归+趋势过滤策略
  - 三段验证全盈：训53笔WR49.1%/验17笔WR52.9%/测14笔WR42.9%
  - 均EV: +0.238R/笔（高于v4.0的+0.153R/笔）
  - 参数: dev=1.2σ | sl=1.0ATR | tp=VWAP | trend=EMA50
  - 理论基础: VWAP机构锚定 + Wyckoff方向过滤
- `skills/trading-research`：从ClawHub安装市场分析技能
  - 支持: 实时TA分析/持仓评估/技术信号

### 策略库更新
- v4.0 BTC/SOL 1H均值回归（主力策略，纸交易中）
- v11 VWAP+趋势 BTC 1H（新增，待纸交易验证）
