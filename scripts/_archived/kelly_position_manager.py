#!/usr/bin/env python3
"""
杀手锏交易系统 v1.0.4 - 凯利仓位管理系统
核心功能：基于胜率和盈亏比动态计算最优仓位
参考：学术研究表明，凯利公式是量化交易中最有效的仓位管理工具
"""
import sys
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kelly_position_manager")


class KellyPositionManager:
    """
    凯利仓位管理器

    核心公式：f* = (bp - q) / b
    其中：
    - f* = 最优仓位比例
    - b = 赔率（盈亏比）
    - p = 胜率
    - q = 1 - p（败率）

    实践建议：
    - 使用1/2凯利或1/4凯利保守策略
    - 单笔最大回撤2.5%
    - 当日本金最大回撤5%
    """

    def __init__(self, config_path: str = None):
        """初始化仓位管理器"""
        self.project_root = Path("/workspace/projects/trading-simulator")
        self.config = self._load_config(config_path)
        self.version = "v1.0.4"

        # 保守系数（推荐1/2凯利）
        self.kelly_fraction = self.config.get('position_management', {}).get('kelly_fraction', 0.5)

        # 风险限制
        self.max_single_loss = self.config.get('position_management', {}).get('max_single_loss', 2.5)  # 单笔最大亏损2.5%
        self.max_daily_loss = self.config.get('position_management', {}).get('max_daily_loss', 5.0)  # 日亏最大5%
        self.max_position_size = self.config.get('position_management', {}).get('max_position_size', 25)  # 最大持仓25%

        # 品种仓位记录
        self.positions = {}  # {symbol: position_info}
        self.daily_trades = []  # 当日交易记录

        logger.info(f"✅ 凯利仓位管理器 {self.version} 初始化完成")
        logger.info(f"   凯利系数: {self.kelly_fraction} (1/{1/self.kelly_fraction:.0f}凯利)")
        logger.info(f"   单笔最大亏损: {self.max_single_loss}%")
        logger.info(f"   日亏最大限制: {self.max_daily_loss}%")

    def _load_config(self, config_path: str) -> Dict:
        """加载配置文件"""
        if config_path is None:
            config_path = self.project_root / "config.json"

        with open(config_path, 'r') as f:
            return json.load(f)

    def calculate_kelly_position(self, win_rate: float, profit_factor: float, account_balance: float) -> float:
        """
        计算凯利最优仓位

        参数：
        - win_rate: 胜率（0-1）
        - profit_factor: 盈亏比（盈利平均/亏损平均）
        - account_balance: 账户余额

        返回：
        - position_value: 仓位价值（美元）
        """
        # 验证参数
        if not (0 <= win_rate <= 1):
            logger.warning(f"胜率{win_rate}无效，使用默认值")
            win_rate = 0.5

        if profit_factor <= 0:
            logger.warning(f"盈亏比{profit_factor}无效，返回0仓位")
            return 0

        # 凯利公式：f* = (bp - q) / b
        b = profit_factor
        p = win_rate
        q = 1 - p

        # 计算全凯利仓位
        kelly_f = (b * p - q) / b

        # 如果赔率为负，不应开仓
        if kelly_f <= 0:
            logger.info(f"凯利仓位为负({kelly_f:.3f})，不建议开仓")
            return 0

        # 应用保守系数
        conservative_f = kelly_f * self.kelly_fraction

        # 计算仓位价值
        position_value = account_balance * conservative_f

        # 最大持仓限制
        max_position = account_balance * (self.max_position_size / 100)
        position_value = min(position_value, max_position)

        logger.info(f"凯利计算: 胜率{win_rate:.2%}, 盈亏比{profit_factor:.2f} → 全凯利{kelly_f:.2%} → {conservative_f:.2%} → ${position_value:.2f}")

        return position_value

    def calculate_batch_kelly(self, strategy_performance: Dict, account_balance: float) -> Dict:
        """
        批量计算各品种的最优仓位

        参数：
        - strategy_performance: {symbol: {'win_rate': float, 'profit_factor': float}}
        - account_balance: 账户余额

        返回：
        - {symbol: position_value}
        """
        positions = {}

        for symbol, perf in strategy_performance.items():
            win_rate = perf.get('win_rate', 0.5)
            profit_factor = perf.get('profit_factor', 1.0)

            position_value = self.calculate_kelly_position(win_rate, profit_factor, account_balance)
            positions[symbol] = position_value

        return positions

    def validate_position(self, symbol: str, position_value: float, account_balance: float) -> Tuple[bool, str]:
        """
        验证仓位是否符合风险限制

        返回：
        - (is_valid, reason)
        """
        # 检查单笔最大亏损
        max_loss = position_value * (self.max_single_loss / 100)
        if max_loss > account_balance * (self.max_single_loss / 100):
            return False, f"单笔风险敞口过大: {max_loss/account_balance*100:.2f}% > {self.max_single_loss}%"

        # 检查当日累计亏损
        daily_loss = sum([t for t in self.daily_trades if t < 0])
        if abs(daily_loss) / account_balance * 100 > self.max_daily_loss:
            return False, f"当日亏损已达限制: {abs(daily_loss)/account_balance*100:.2f}% > {self.max_daily_loss}%"

        # 检查最大持仓
        if position_value / account_balance * 100 > self.max_position_size:
            return False, f"仓位超过最大限制: {position_value/account_balance*100:.2f}% > {self.max_position_size}%"

        return True, "通过"

    def record_trade(self, profit: float):
        """记录交易结果"""
        self.daily_trades.append(profit)

        # 每日重置
        current_date = datetime.now().date()
        if not hasattr(self, '_last_trade_date'):
            self._last_trade_date = current_date
        elif current_date != self._last_trade_date:
            self.daily_trades = []
            self._last_trade_date = current_date

    def reset_daily(self):
        """手动重置当日交易记录"""
        self.daily_trades = []

    def get_daily_pnl(self) -> Dict:
        """获取当日盈亏统计"""
        if not self.daily_trades:
            return {
                'total_trades': 0,
                'total_pnl': 0,
                'winning_trades': 0,
                'losing_trades': 0
            }

        total_pnl = sum(self.daily_trades)
        winning_trades = sum(1 for t in self.daily_trades if t > 0)
        losing_trades = sum(1 for t in self.daily_trades if t < 0)

        return {
            'total_trades': len(self.daily_trades),
            'total_pnl': total_pnl,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': winning_trades / len(self.daily_trades) if self.daily_trades else 0
        }


class DynamicGridTrading:
    """
    动态网格交易策略
    2025年学术研究成果：动态网格重置形成趋势跟踪效果
    """

    def __init__(self):
        """初始化动态网格"""
        self.version = "v1.0.4"

        # 网格参数
        self.grid_count = 20  # 网格数量
        self.grid_spacing_percent = 1.0  # 网格间距（%）
        self.single_grid_percent = 1.5  # 单网格资金（%）

        logger.info(f"✅ 动态网格交易 {self.version} 初始化完成")
        logger.info(f"   网格数量: {self.grid_count}")
        logger.info(f"   网格间距: {self.grid_spacing_percent}%")
        logger.info(f"   单网格资金: {self.single_grid_percent}%")

    def calculate_grid_levels(self, base_price: float, range_percent: float) -> np.ndarray:
        """
        计算网格价位

        参数：
        - base_price: 基准价格
        - range_percent: 网格范围（%）

        返回：
        - grid_levels: 网格价位数组
        """
        lower_bound = base_price * (1 - range_percent / 2 / 100)
        upper_bound = base_price * (1 + range_percent / 2 / 100)

        # 计算网格间距
        total_range = upper_bound - lower_bound
        spacing = total_range / (self.grid_count - 1)

        # 生成网格价位
        grid_levels = np.linspace(lower_bound, upper_bound, self.grid_count)

        logger.info(f"网格范围: ${lower_bound:.2f} - ${upper_bound:.2f} (间距${spacing:.2f})")

        return grid_levels

    def adjust_grid_by_atr(self, base_price: float, atr: float, account_balance: float) -> Tuple[np.ndarray, float]:
        """
        基于ATR动态调整网格

        参数：
        - base_price: 基准价格
        - atr: ATR值
        - account_balance: 账户余额

        返回：
        - grid_levels: 调整后的网格价位
        - total_investment: 总投资金额
        """
        # 基于ATR计算范围（通常为ATR的2-3倍）
        range_percent = (atr / base_price) * 100 * 3

        # 计算网格
        grid_levels = self.calculate_grid_levels(base_price, range_percent)

        # 计算总投资
        total_investment = account_balance * (self.single_grid_percent / 100) * self.grid_count

        return grid_levels, total_investment


class StatisticalArbitrage:
    """
    统计套利策略
    用于ETH等方向性策略失效的品种
    """

    def __init__(self):
        """初始化统计套利"""
        self.version = "v1.0.4"

        # Z-score阈值
        self.z_entry = 2.0  # 入场阈值
        self.z_exit = 0.5   # 出场阈值
        self.lookback = 20  # 回望窗口

        logger.info(f"✅ 统计套利 {self.version} 初始化完成")
        logger.info(f"   入场Z-score: {self.z_entry}")
        logger.info(f"   出场Z-score: {self.z_exit}")

    def calculate_spread_zscore(self, asset1_prices: pd.Series, asset2_prices: pd.Series) -> float:
        """
        计算价差的Z-score

        参数：
        - asset1_prices: 资产1价格序列
        - asset2_prices: 资产2价格序列

        返回：
        - z_score: Z-score值
        """
        # 计算价差
        spread = asset1_prices - asset2_prices

        # 计算统计量
        spread_mean = spread.tail(self.lookback).mean()
        spread_std = spread.tail(self.lookback).std()

        # Z-score
        z_score = (spread.iloc[-1] - spread_mean) / spread_std if spread_std > 0 else 0

        return z_score

    def generate_arbitrage_signal(self, z_score: float) -> Optional[Dict]:
        """
        生成套利信号

        参数：
        - z_score: Z-score值

        返回：
        - signal_dict: 信号字典或None
        """
        if z_score > self.z_entry:
            return {
                'direction': 'SHORT_SPREAD',
                'action': '做多资产2，做空资产1',
                'z_score': z_score,
                'reason': f'价差过高(Z={z_score:.2f})'
            }
        elif z_score < -self.z_entry:
            return {
                'direction': 'LONG_SPREAD',
                'action': '做多资产1，做空资产2',
                'z_score': z_score,
                'reason': f'价差过低(Z={z_score:.2f})'
            }
        elif abs(z_score) < self.z_exit:
            return {
                'direction': 'CLOSE',
                'action': '平仓套利',
                'z_score': z_score,
                'reason': f'价差回归(Z={z_score:.2f})'
            }

        return None


if __name__ == "__main__":
    print("=" * 80)
    print("🧪 v1.0.4 凯利仓位管理系统测试")
    print("=" * 80)

    # 测试1：凯利仓位计算
    print("\n📊 测试1：凯利仓位计算")
    print("-" * 80)

    kelly_manager = KellyPositionManager()

    # 测试数据（来自诊断报告）
    test_cases = [
        {'symbol': 'SOLUSDT 1H', 'win_rate': 0.444, 'profit_factor': 2.26},
        {'symbol': 'BNBUSDT 1H', 'win_rate': 0.545, 'profit_factor': 1.41},
        {'symbol': 'BTCUSDT 5m', 'win_rate': 0.529, 'profit_factor': 1.17},
        {'symbol': 'BTCUSDT 1H', 'win_rate': 0.429, 'profit_factor': 1.53},
    ]

    account_balance = 10000

    for case in test_cases:
        print(f"\n{case['symbol']}:")
        print(f"  胜率: {case['win_rate']:.2%}")
        print(f"  盈亏比: {case['profit_factor']:.2f}")

        position_value = kelly_manager.calculate_kelly_position(
            case['win_rate'],
            case['profit_factor'],
            account_balance
        )

        print(f"  建议仓位: ${position_value:.2f} ({position_value/account_balance*100:.2f}%)")

    # 测试2：动态网格交易
    print("\n" + "=" * 80)
    print("📊 测试2：动态网格交易")
    print("=" * 80)

    grid_trading = DynamicGridTrading()

    base_price = 100000  # BTC价格
    atr = 2000

    grid_levels, total_investment = grid_trading.adjust_grid_by_atr(base_price, atr, account_balance)

    print(f"\n基准价格: ${base_price}")
    print(f"ATR: ${atr}")
    print(f"网格数量: {len(grid_levels)}")
    print(f"总投资: ${total_investment:.2f} ({total_investment/account_balance*100:.2f}%)")

    # 测试3：统计套利
    print("\n" + "=" * 80)
    print("📊 测试3：统计套利")
    print("=" * 80)

    arb = StatisticalArbitrage()

    # 生成模拟价差数据
    dates = pd.date_range(start='2024-01-01', periods=50, freq='h')
    btc_prices = pd.Series(np.linspace(50000, 55000, 50) + np.random.randn(50) * 200, index=dates)
    eth_prices = btc_prices * 0.03 + np.random.randn(50) * 50  # ETH跟随BTC但有偏差

    z_score = arb.calculate_spread_zscore(btc_prices, eth_prices)
    signal = arb.generate_arbitrage_signal(z_score)

    print(f"\nBTC/ETH价差Z-score: {z_score:.2f}")
    if signal:
        print(f"套利信号: {signal['direction']}")
        print(f"操作: {signal['action']}")
    else:
        print("无套利机会")

    print("\n✅ 测试完成")
