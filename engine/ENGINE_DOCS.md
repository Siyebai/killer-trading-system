# 引擎模块说明

## ws_feeder.py - K线数据馈送
**功能**: 
- 订阅Binance WebSocket K线流 (15m)
- 维护滑动窗口 (最新250根)
- 断线自动重连 (指数退避)
- REST API预填充历史数据

**关键类**:
- `Kline`: K线数据类
- `KlineBuffer`: 线程安全滑动窗口
- `BinanceWSFeeder`: WS订阅器

**使用**:
```python
buf = KlineBuffer(maxlen=300)
await init_buffer_from_rest("BTCUSDT", "15m", buf, limit=250)
feeder = BinanceWSFeeder("btcusdt", "15m", buf, on_closed=callback)
await feeder.run()
```

## signal_engine.py - 信号引擎
**功能**:
- 计算ADX, ATR, EMA200指标
- 检测MomReversal信号 (SHORT/LONG)
- 输出Signal对象 (方向/入场/SL/TP)

**关键方法**:
- `evaluate(bars)`: 传入K线列表，返回Signal
- `_calc_adx()`, `_calc_atr()`: 指标计算

**使用**:
```python
eng = SignalEngine(symbol="BTCUSDT", n_short=7, n_long=4, adx_min=20)
sig = eng.evaluate(bars)
if sig.direction == "LONG":
    print(f"开多 entry={sig.entry_price} SL={sig.sl_price} TP={sig.tp_price}")
```

## risk_engine.py - 风控引擎
**功能**:
- 固定风险/百分比风险双模式
- 日内/月度熔断
- 连续亏损降仓
- 状态持久化

**关键方法**:
- `can_trade()`: 检查是否允许开仓
- `get_risk_amount()`: 获取当前风险金额
- `calc_position()`: 计算仓位
- `on_trade_close()`: 平仓后更新状态

**使用**:
```python
risk = RiskEngine("state.json", config)
can, reason = risk.can_trade()
if not can:
    print(f"风控阻止: {reason}")
    return
qty, notional = risk.calc_position(entry, sl)
```

## order_executor.py - 订单执行器
**功能**:
- Binance Futures REST API封装
- 市价开仓 + 条件单SL/TP
- 限流重试 (指数退避)
- 持仓恢复 (断线续单)

**关键方法**:
- `open_position()`: 开仓 + 挂SL/TP
- `close_position()`: 强制平仓
- `recover_positions()`: 恢复未平仓位

**使用**:
```python
ex = BinanceExecutor(api_key, secret, testnet=True)
pos = ex.open_position("BTCUSDT", "LONG", qty, sl_price, tp_price)
# 系统重启后
pos = ex.recover_positions("BTCUSDT")
```

## live_engine.py - 主引擎
**功能**:
- 整合4个模块
- 事件驱动循环
- 心跳日志
- 优雅退出

**运行**:
```bash
python3 engine/live_engine.py          # 测试网
python3 engine/live_engine.py --live   # 主网
```
