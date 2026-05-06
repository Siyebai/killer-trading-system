# 部署指南

## 前置准备

### 1. Binance API配置
1. 注册 Binance 账户
2. 开通 Futures 合约权限
3. 创建 API Key:
   - ✅ Enable Reading
   - ✅ Enable Futures
   - ❌ **Disable Withdrawals** (安全!)
4. 记录 API Key 和 Secret

### 2. 测试网配置 (推荐先测)
1. 访问 https://testnet.binancefuture.com
2. 用GitHub账号登录
3. 生成测试网API Key
4. 获得 10,000 USDT 测试金

## 部署步骤

### Step 1: 克隆/更新代码
```bash
cd /root/.openclaw/workspace
# 如果是首次: git clone ...
# 如果已有: git pull
```

### Step 2: 配置密钥
编辑 `engine/live_engine.py`:
```python
# 测试网
TESTNET_KEY = "你的测试网Key"
TESTNET_SECRET = "你的测试网Secret"

# 主网 (实盘用)
MAINNET_KEY = "你的主网Key"
MAINNET_SECRET = "你的主网Secret"
```

### Step 3: 选择策略配置
```bash
# v1.4优化版 (推荐)
cp config/strategy_v14_optimized.json config/strategy_active.json

# 或 v1.3高频版
# cp config/strategy_v13_multi.json config/strategy_active.json
```

### Step 4: 安装依赖
```bash
pip install websockets aiohttp requests numpy pandas
```

### Step 5: 测试运行 (模拟)
```bash
python3 deploy_testnet.py
# 检查输出:
# ✅ 初始化完成: 4品种
# ✅ BTCUSDT: 250根K线
# ...
```

### Step 6: 实盘部署
```bash
# 测试网
python3 engine/live_engine.py

# 主网 (谨慎!)
python3 engine/live_engine.py --live
# 会提示确认: 输入 "YES" 继续
```

## 监控与维护

### 查看日志
```bash
tail -f logs/live_engine.log
```

### 查看状态
```bash
cat engine/state/multi_state.json
```

### 紧急停止
```bash
# Ctrl+C 或
kill $(pgrep -f live_engine.py)
```

### 取消所有挂单
```bash
python3 -c "
from engine.order_executor import BinanceExecutor
ex = BinanceExecutor('KEY','SECRET',testnet=True)
for sym in ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT']:
    ex.cancel_all_orders(sym)
"
```

## 常见问题

### Q: 429限流错误
A: 测试网限流严格，等待5-10分钟重试，或减少请求频率

### Q: 仓位计算为0
A: 检查SL距离是否太小，或资金不足

### Q: 连续触发熔断
A: 降低risk_per_trade_u (3U→2U→1.5U)

### Q: 实盘还是测试网？
A: **至少测试网7天正收益后再考虑实盘**

## 安全检查清单
- [ ] API已禁用提现
- [ ] 测试网验证≥7天
- [ ] 最大回撤<20%
- [ ] 日熔断未触发
- [ ] 日志无异常错误
- [ ] 起始资金≥150U
