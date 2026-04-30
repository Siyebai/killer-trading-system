# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("dynamic_position")
except ImportError:
    import logging
    logger = logging.getLogger("dynamic_position")
"""
动态仓位管理模块 - 杀手锏交易系统核心
凯利公式优化版仓位计算、波动率自适应、最大仓位限制
专业交易员推荐的仓位计算：仓位 = (胜率 × 盈亏比 — 1) / 盈亏比 × 0.5
"""

import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class PositionSizing:
    """仓位大小"""
    position_size: float  # 仓位大小（USDT）
    position_percent: float  # 仓位百分比（0-1）
    risk_amount: float  # 风险金额（USDT）
    kelly_fraction: float  # 凯利分数
    method: str  # 计算方法


class DynamicPositionSizer:
    """动态仓位管理器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化仓位管理器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 配置参数
        self.account_balance = self.config.get('account_balance', 100000)
        self.max_position_percent = self.config.get('max_position_percent', 0.5)  # 最大50%
        self.min_position_percent = self.config.get('min_position_percent', 0.1)  # 最小10%
        self.risk_per_trade = self.config.get('risk_per_trade', 0.02)  # 单笔风险2%
        self.kelly_fraction = self.config.get('kelly_fraction', 0.25)  # 凯利分数25%（保守）

        # 历史胜率
        self.historical_winrate = 0.5
        self.historical_avg_win = 0.02
        self.historical_avg_loss = -0.02

    def calculate_kelly_position(self, winrate: float, avg_win: float, avg_loss: float) -> float:
        """
        计算凯利公式仓位

        Args:
            winrate: 历史胜率
            avg_win: 平均收益率（正数）
            avg_loss: 平均亏损率（负数）

        Returns:
            凯利仓位百分比
        """
        if avg_loss >= 0 or winrate <= 0 or winrate >= 1:
            return self.min_position_percent

        # 凯利公式: f* = p - q/b
        # p = 胜率, q = 败率, b = 盈亏比
        b = avg_win / abs(avg_loss)
        q = 1 - winrate

        kelly = winrate - (q / b)

        # 限制凯利值
        kelly = max(0, min(1, kelly))

        # 应用保守分数
        kelly = kelly * self.kelly_fraction

        return kelly

    def calculate_kelly_optimized(self, winrate: float, avg_win: float, avg_loss: float) -> float:
        """
        计算凯利公式优化版仓位（专业交易员推荐）
        公式：仓位 = (胜率 × 盈亏比 — 1) / 盈亏比 × 0.5

        Args:
            winrate: 历史胜率
            avg_win: 平均收益率（正数）
            avg_loss: 平均亏损率（负数）

        Returns:
            凯利优化版仓位百分比
        """
        if avg_loss >= 0 or winrate <= 0 or winrate >= 1:
            return self.min_position_percent

        # 盈亏比
        win_loss_ratio = avg_win / abs(avg_loss)

        # 凯利优化版公式
        kelly_optimized = (winrate * win_loss_ratio - 1) / win_loss_ratio

        # 应用50%保守系数
        kelly_optimized = kelly_optimized * 0.5

        # 限制凯利值
        kelly_optimized = max(0, min(1, kelly_optimized))

        return kelly_optimized

    def calculate_position(self, volatility: Optional[float] = None,
                          stop_loss_percent: Optional[float] = None,
                          method: str = "KELLY_OPTIMIZED") -> PositionSizing:
        """
        计算仓位大小

        Args:
            volatility: 市场波动率（年化）
            stop_loss_percent: 止损百分比
            method: 计算方法（KELLY/RISK_PER_TRADE/VOLATILITY）

        Returns:
            仓位大小
        """
        position_percent = 0.0

        if method == "KELLY_OPTIMIZED":
            # 使用凯利公式优化版
            kelly = self.calculate_kelly_optimized(
                self.historical_winrate,
                self.historical_avg_win,
                self.historical_avg_loss
            )

            # 波动率调整
            if volatility:
                # 波动率越高，仓位越小
                vol_adjustment = min(1.0, 0.02 / volatility)
                kelly = kelly * vol_adjustment

            position_percent = max(self.min_position_percent, kelly)
            position_percent = min(self.max_position_percent, position_percent)

        elif method == "KELLY":
            # 使用凯利公式
            kelly = self.calculate_kelly_position(
                self.historical_winrate,
                self.historical_avg_win,
                self.historical_avg_loss
            )

            # 波动率调整
            if volatility:
                # 波动率越高，仓位越小
                vol_adjustment = min(1.0, 0.02 / volatility)
                kelly = kelly * vol_adjustment

            position_percent = max(self.min_position_percent, kelly)
            position_percent = min(self.max_position_percent, position_percent)

        elif method == "RISK_PER_TRADE":
            # 基于固定风险比例
            if stop_loss_percent and stop_loss_percent > 0:
                position_percent = self.risk_per_trade / stop_loss_percent
            else:
                position_percent = 0.3

            position_percent = max(self.min_position_percent, position_percent)
            position_percent = min(self.max_position_percent, position_percent)

        elif method == "VOLATILITY":
            # 基于波动率调整
            if volatility:
                # 目标波动率2%
                target_vol = 0.02
                position_percent = target_vol / volatility
            else:
                position_percent = 0.3

            position_percent = max(self.min_position_percent, position_percent)
            position_percent = min(self.max_position_percent, position_percent)

        else:
            position_percent = 0.3

        # 计算绝对值
        position_size = self.account_balance * position_percent
        risk_amount = position_size * (stop_loss_percent if stop_loss_percent else 0.05)

        return PositionSizing(
            position_size=position_size,
            position_percent=position_percent,
            risk_amount=risk_amount,
            kelly_fraction=self.kelly_fraction,
            method=method
        )

    def update_statistics(self, winrate: float, avg_win: float, avg_loss: float):
        """
        更新统计信息

        Args:
            winrate: 历史胜率
            avg_win: 平均收益率
            avg_loss: 平均亏损率
        """
        self.historical_winrate = winrate
        self.historical_avg_win = avg_win
        self.historical_avg_loss = avg_loss

    def get_account_balance(self) -> float:
        """获取账户余额"""
        return self.account_balance

    def set_account_balance(self, balance: float):
        """设置账户余额"""
        self.account_balance = balance


# 命令行测试
def main():
    """测试动态仓位管理"""
    logger.info("="*60)
    logger.info("💰 动态仓位管理测试")
    logger.info("="*60)

    # 创建仓位管理器
    sizer = DynamicPositionSizer({
        'account_balance': 100000,
        'max_position_percent': 0.5,
        'min_position_percent': 0.1,
        'risk_per_trade': 0.02,
        'kelly_fraction': 0.25
    })

    logger.info(f"\n配置:")
    logger.info(f"  账户余额: ${sizer.get_account_balance():,.2f}")
    logger.info(f"  最大仓位: {sizer.max_position_percent * 100}%")
    logger.info(f"  最小仓位: {sizer.min_position_percent * 100}%")
    logger.info(f"  单笔风险: {sizer.risk_per_trade * 100}%")
    logger.info(f"  凯利分数: {sizer.kelly_fraction * 100}%")

    # 更新历史统计（假设历史胜率60%，盈亏比2:1）
    sizer.update_statistics(winrate=0.6, avg_win=0.03, avg_loss=-0.015)
    logger.info(f"\n历史统计:")
    logger.info(f"  胜率: {sizer.historical_winrate * 100}%")
    logger.info(f"  平均盈利: {sizer.historical_avg_win * 100}%")
    logger.info(f"  平均亏损: {sizer.historical_avg_loss * 100}%")

    # 测试1: 凯利公式
    logger.info(f"\n测试1: 凯利公式")
    result1 = sizer.calculate_position(method="KELLY")
    logger.info(f"  仓位大小: ${result1.position_size:,.2f}")
    logger.info(f"  仓位百分比: {result1.position_percent * 100:.2f}%")
    logger.info(f"  风险金额: ${result1.risk_amount:,.2f}")

    # 测试2: 凯利公式 + 高波动率
    logger.info(f"\n测试2: 凯利公式 + 高波动率 (5%)")
    result2 = sizer.calculate_position(volatility=0.05, method="KELLY")
    logger.info(f"  仓位大小: ${result2.position_size:,.2f}")
    logger.info(f"  仓位百分比: {result2.position_percent * 100:.2f}%")
    logger.info(f"  波动率调整后减少: {(1 - result2.position_percent / result1.position_percent) * 100:.1f}%")

    # 测试3: 风险比例方法
    logger.info(f"\n测试3: 风险比例方法 (止损5%)")
    result3 = sizer.calculate_position(stop_loss_percent=0.05, method="RISK_PER_TRADE")
    logger.info(f"  仓位大小: ${result3.position_size:,.2f}")
    logger.info(f"  仓位百分比: {result3.position_percent * 100:.2f}%")
    logger.info(f"  风险金额: ${result3.risk_amount:,.2f}")

    # 测试4: 风险比例方法 (止损3%)
    logger.info(f"\n测试4: 风险比例方法 (止损3%)")
    result4 = sizer.calculate_position(stop_loss_percent=0.03, method="RISK_PER_TRADE")
    logger.info(f"  仓位大小: ${result4.position_size:,.2f}")
    logger.info(f"  仓位百分比: {result4.position_percent * 100:.2f}%")

    # 测试5: 不同胜率下的凯利
    logger.info(f"\n测试5: 不同胜率下的凯利仓位")
    winrates = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    for wr in winrates:
        sizer.update_statistics(winrate=wr, avg_win=0.03, avg_loss=-0.015)
        result = sizer.calculate_position(method="KELLY")
        logger.info(f"  胜率{wr*100:3.0f}%: {result.position_percent*100:5.2f}%  (${result.position_size:,.2f})")

    # 测试6: 最小/最大仓位限制
    logger.info(f"\n测试6: 仓位限制")
    sizer.update_statistics(winrate=0.9, avg_win=0.05, avg_loss=-0.01)  # 高胜率
    result = sizer.calculate_position(method="KELLY")
    logger.info(f"  高胜率(90%)场景:")
    logger.info(f"    凯利计算: {result.position_percent * 100:.2f}%")
    logger.info(f"    是否触发最大限制: {'是' if result.position_percent >= sizer.max_position_percent else '否'}")

    sizer.update_statistics(winrate=0.3, avg_win=0.015, avg_loss=-0.02)  # 低胜率
    result = sizer.calculate_position(method="KELLY")
    logger.info(f"  低胜率(30%)场景:")
    logger.info(f"    凯利计算: {result.position_percent * 100:.2f}%")
    logger.info(f"    是否触发最小限制: {'是' if result.position_percent <= sizer.min_position_percent else '否'}")

    logger.info("\n" + "="*60)
    logger.info("动态仓位管理测试: PASS")


if __name__ == "__main__":
    main()
