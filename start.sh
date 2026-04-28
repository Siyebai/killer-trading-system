#!/bin/bash
# 杀手锏交易系统 v1.0.0 Stable - 一键启动脚本

set -e

echo "========================================"
echo "杀手锏交易系统 v1.0.0 Stable"
echo "========================================"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 步骤1: 健康度检查
echo -e "${YELLOW}[1/4] 运行健康度检查...${NC}"
python scripts/health_check.py
if [ $? -ne 0 ]; then
    echo -e "${RED}健康度检查失败，请修复后重试${NC}"
    exit 1
fi
echo ""

# 步骤2: 初始化事件总线
echo -e "${YELLOW}[2/4] 初始化事件总线...${NC}"
python -c "from scripts.event_bus import get_event_bus; bus = get_event_bus(); print('✓ 事件总线已初始化')"
echo ""

# 步骤3: 运行策略进化测试
echo -e "${YELLOW}[3/4] 运行策略进化测试...${NC}"
python -c "
import sys
sys.path.insert(0, '.')

from scripts.strategy_lab import StrategyLab
from scripts.historical_data_loader import HistoricalDataLoader

print('创建数据加载器...')
loader = HistoricalDataLoader()

print('生成测试数据...')
market_data = loader.generate_mock_data('BTCUSDT', n_samples=1000)

print('创建策略实验室...')
lab = StrategyLab(population_size=20, generations=5, use_backtest_adapter=True)

print('开始进化...')
best = lab.run(market_data)

print(f'\\n✓ 进化完成')
print(f'  最佳适应度: {best.fitness:.4f}')
print(f'  Sharpe比率: {best.sharpe_ratio:.4f}')
"
echo ""

# 步骤4: 运行异常检测测试
echo -e "${YELLOW}[4/4] 运行异常检测测试...${NC}"
python -c "
import sys
sys.path.insert(0, '.')

from scripts.anomaly_detector import AnomalyDetector

print('创建异常检测器...')
detector = AnomalyDetector()

print('生成测试数据...')
import numpy as np
normal_data = np.random.randn(100, 5)

print('训练检测器...')
detector.fit(normal_data)

print('检测正常数据...')
result1 = detector.detect(normal_data[0], 'volatility')
print(f'  正常数据: {\"异常\" if result1 else \"正常\"}')

print('检测异常数据...')
anomaly_data = normal_data[0] * 5
result2 = detector.detect(anomaly_data, 'volatility')
print(f'  异常数据: {\"异常\" if result2 else \"正常\"}')

print('\\n✓ 异常检测测试完成')
"
echo ""

# 完成
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ 系统启动完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "下一步："
echo "  1. 运行快速测试: python scripts/quick_test.py"
echo "  2. 查看配置文件: cat config.yaml"
echo "  3. 启动交易系统: python scripts/main.py"
echo ""
