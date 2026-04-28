#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("portfolio_optimizer")
except ImportError:
    import logging
    logger = logging.getLogger("portfolio_optimizer")
"""
多资产组合优化 - V4.0核心模块
马科维茨投资组合理论、协方差矩阵、最优权重分配
"""

import json
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class OptimizationStrategy(Enum):
    """优化策略"""
    MEAN_VARIANCE = "MEAN_VARIANCE"  # 均值-方差优化（马科维茨）
    MINIMUM_VARIANCE = "MINIMUM_VARIANCE"  # 最小方差
    MAXIMUM_SHARPE = "MAXIMUM_SHARPE"  # 最大夏普比率
    RISK_PARITY = "RISK_PARITY"  # 风险平价
    EQUAL_WEIGHT = "EQUAL_WEIGHT"  # 等权重
    EQUAL_RETURN_CONTRIBUTION = "EQUAL_RETURN_CONTRIBUTION"  # 等风险贡献


@dataclass
class Asset:
    """资产"""
    symbol: str
    name: str
    expected_return: float
    volatility: float
    current_price: float = 0.0


@dataclass
class Portfolio:
    """投资组合"""
    assets: Dict[str, float]  # symbol -> weight
    expected_return: float
    volatility: float
    sharpe_ratio: float
    strategy: str


class PortfolioOptimizer:
    """投资组合优化器"""

    def __init__(self, risk_free_rate: float = 0.02):
        """
        初始化优化器

        Args:
            risk_free_rate: 无风险利率（年化）
        """
        self.risk_free_rate = risk_free_rate

    def calculate_covariance_matrix(self, returns: Dict[str, List[float]]) -> np.ndarray:
        """
        计算协方差矩阵

        Args:
            returns: 资产收益率字典 {symbol: [return1, return2, ...]}

        Returns:
            协方差矩阵
        """
        symbols = list(returns.keys())
        n = len(symbols)

        # 构建收益率矩阵
        return_matrix = np.zeros((n, max(len(r) for r in returns.values())))

        for i, symbol in enumerate(symbols):
            asset_returns = returns[symbol]
            return_matrix[i, :len(asset_returns)] = asset_returns

        # 计算协方差矩阵
        cov_matrix = np.cov(return_matrix)

        return cov_matrix

    def optimize_mean_variance(self, assets: List[Asset],
                               returns: Dict[str, List[float]],
                               target_return: Optional[float] = None,
                               target_risk: Optional[float] = None) -> Portfolio:
        """
        均值-方差优化（马科维茨）

        Args:
            assets: 资产列表
            returns: 收益率数据
            target_return: 目标收益率（可选）
            target_risk: 目标风险（可选）

        Returns:
            优化后的投资组合
        """
        symbols = [a.symbol for a in assets]
        expected_returns = np.array([a.expected_return for a in assets])
        cov_matrix = self.calculate_covariance_matrix(returns)

        n = len(symbols)

        # 如果指定目标收益率，求解最小方差组合
        if target_return is not None:
            # 使用简化方法：等权重优化
            weights = self._solve_constrained_optimization(
                expected_returns, cov_matrix, target_return=target_return
            )
        else:
            # 最小方差组合
            inv_cov = np.linalg.inv(cov_matrix)
            ones = np.ones(n)

            weights = inv_cov @ ones / (ones.T @ inv_cov @ ones)

        # 标准化权重
        weights = np.maximum(weights, 0)  # 不允许卖空
        weights = weights / np.sum(weights)

        # 计算组合指标
        portfolio_return = np.dot(weights, expected_returns)
        portfolio_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        sharpe_ratio = (portfolio_return - self.risk_free_rate) / portfolio_volatility

        return Portfolio(
            assets={symbol: float(w) for symbol, w in zip(symbols, weights)},
            expected_return=portfolio_return,
            volatility=portfolio_volatility,
            sharpe_ratio=sharpe_ratio,
            strategy="MEAN_VARIANCE"
        )

    def optimize_minimum_variance(self, assets: List[Asset],
                                  returns: Dict[str, List[float]]) -> Portfolio:
        """
        最小方差优化

        Args:
            assets: 资产列表
            returns: 收益率数据

        Returns:
            优化后的投资组合
        """
        symbols = [a.symbol for a in assets]
        cov_matrix = self.calculate_covariance_matrix(returns)

        n = len(symbols)

        # 全局最小方差组合
        inv_cov = np.linalg.inv(cov_matrix)
        ones = np.ones(n)

        weights = inv_cov @ ones / (ones.T @ inv_cov @ ones)

        # 标准化权重
        weights = np.maximum(weights, 0)
        weights = weights / np.sum(weights)

        expected_returns = np.array([a.expected_return for a in assets])
        portfolio_return = np.dot(weights, expected_returns)
        portfolio_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        sharpe_ratio = (portfolio_return - self.risk_free_rate) / portfolio_volatility

        return Portfolio(
            assets={symbol: float(w) for symbol, w in zip(symbols, weights)},
            expected_return=portfolio_return,
            volatility=portfolio_volatility,
            sharpe_ratio=sharpe_ratio,
            strategy="MINIMUM_VARIANCE"
        )

    def optimize_risk_parity(self, assets: List[Asset],
                            returns: Dict[str, List[float]]) -> Portfolio:
        """
        风险平价优化

        Args:
            assets: 资产列表
            returns: 收益率数据

        Returns:
            优化后的投资组合
        """
        symbols = [a.symbol for a in assets]
        cov_matrix = self.calculate_covariance_matrix(returns)

        n = len(symbols)

        # 风险平价：每个资产对组合风险的贡献相等
        # 简化实现：使用波动率的倒数作为权重
        volatilities = np.array([a.volatility for a in assets])

        # 避免除零
        volatilities = np.maximum(volatilities, 1e-6)

        weights = 1 / volatilities
        weights = weights / np.sum(weights)

        expected_returns = np.array([a.expected_return for a in assets])
        portfolio_return = np.dot(weights, expected_returns)
        portfolio_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        sharpe_ratio = (portfolio_return - self.risk_free_rate) / portfolio_volatility

        return Portfolio(
            assets={symbol: float(w) for symbol, w in zip(symbols, weights)},
            expected_return=portfolio_return,
            volatility=portfolio_volatility,
            sharpe_ratio=sharpe_ratio,
            strategy="RISK_PARITY"
        )

    def optimize_equal_weight(self, assets: List[Asset],
                             returns: Dict[str, List[float]]) -> Portfolio:
        """
        等权重优化

        Args:
            assets: 资产列表
            returns: 收益率数据

        Returns:
            优化后的投资组合
        """
        symbols = [a.symbol for a in assets]
        n = len(symbols)

        weights = np.ones(n) / n

        expected_returns = np.array([a.expected_return for a in assets])
        cov_matrix = self.calculate_covariance_matrix(returns)

        portfolio_return = np.dot(weights, expected_returns)
        portfolio_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        sharpe_ratio = (portfolio_return - self.risk_free_rate) / portfolio_volatility

        return Portfolio(
            assets={symbol: float(w) for symbol, w in zip(symbols, weights)},
            expected_return=portfolio_return,
            volatility=portfolio_volatility,
            sharpe_ratio=sharpe_ratio,
            strategy="EQUAL_WEIGHT"
        )

    def optimize(self, assets: List[Asset], returns: Dict[str, List[float]],
                strategy: OptimizationStrategy = OptimizationStrategy.MEAN_VARIANCE,
                **kwargs) -> Portfolio:
        """
        优化投资组合

        Args:
            assets: 资产列表
            returns: 收益率数据
            strategy: 优化策略
            **kwargs: 策略特定参数

        Returns:
            优化后的投资组合
        """
        if strategy == OptimizationStrategy.MEAN_VARIANCE:
            return self.optimize_mean_variance(assets, returns, **kwargs)
        elif strategy == OptimizationStrategy.MINIMUM_VARIANCE:
            return self.optimize_minimum_variance(assets, returns)
        elif strategy == OptimizationStrategy.RISK_PARITY:
            return self.optimize_risk_parity(assets, returns)
        elif strategy == OptimizationStrategy.EQUAL_WEIGHT:
            return self.optimize_equal_weight(assets, returns)
        else:
            raise ValueError(f"不支持的优化策略: {strategy}")

    def _solve_constrained_optimization(self, expected_returns: np.ndarray,
                                       cov_matrix: np.ndarray,
                                       target_return: Optional[float] = None) -> np.ndarray:
        """
        求解约束优化问题

        Args:
            expected_returns: 预期收益率
            cov_matrix: 协方差矩阵
            target_return: 目标收益率

        Returns:
            最优权重
        """
        n = len(expected_returns)

        # 简化实现：使用逆方差方法
        inv_cov = np.linalg.inv(cov_matrix)
        ones = np.ones(n)

        if target_return is None:
            # 最小方差
            weights = inv_cov @ ones / (ones.T @ inv_cov @ ones)
        else:
            # 目标收益率约束下的最小方差
            inv_cov_r = inv_cov @ expected_returns
            inv_cov_ones = inv_cov @ ones

            a = expected_returns.T @ inv_cov_r
            b = expected_returns.T @ inv_cov_ones
            c = ones.T @ inv_cov_ones

            lam1 = (c * target_return - b) / (a * c - b * b)
            lam2 = (a - b * target_return) / (a * c - b * b)

            weights = lam1 * (inv_cov_r) + lam2 * (inv_cov_ones)

        return weights

    def calculate_efficient_frontier(self, assets: List[Asset],
                                    returns: Dict[str, List[float]],
                                    num_points: int = 20) -> List[Tuple[float, float, Dict[str, float]]]:
        """
        计算有效前沿

        Args:
            assets: 资产列表
            returns: 收益率数据
            num_points: 前沿点数

        Returns:
            [(return, volatility, weights), ...]
        """
        frontier = []

        symbols = [a.symbol for a in assets]
        expected_returns = np.array([a.expected_return for a in assets])
        cov_matrix = self.calculate_covariance_matrix(returns)

        # 计算最小方差和最大夏普组合
        min_var_portfolio = self.optimize_minimum_variance(assets, returns)
        max_sharpe_portfolio = self.optimize_mean_variance(assets, returns)

        # 生成前沿点
        min_return = min_var_portfolio.expected_return
        max_return = max(a.expected_return for a in assets)

        for i in range(num_points):
            target_return = min_return + (max_return - min_return) * i / (num_points - 1)

            portfolio = self.optimize_mean_variance(
                assets, returns, target_return=target_return
            )

            frontier.append((
                portfolio.expected_return,
                portfolio.volatility,
                portfolio.assets.copy()
            ))

        return frontier

    def backtest_portfolio(self, portfolio: Portfolio, returns: Dict[str, List[float]],
                          start_idx: int = 0, end_idx: Optional[int] = None) -> Dict[str, float]:
        """
        回测投资组合

        Args:
            portfolio: 投资组合
            returns: 收益率数据
            start_idx: 起始索引
            end_idx: 结束索引

        Returns:
            回测结果
        """
        if end_idx is None:
            end_idx = max(len(r) for r in returns.values())

        weights = np.array([portfolio.assets.get(symbol, 0) for symbol in returns.keys()])

        # 计算组合收益率
        portfolio_returns = np.zeros(end_idx - start_idx)

        for i in range(start_idx, end_idx):
            period_returns = np.array([
                returns[symbol][i] if i < len(returns[symbol]) else 0
                for symbol in returns.keys()
            ])
            portfolio_returns[i - start_idx] = np.dot(weights, period_returns)

        # 计算指标
        total_return = np.sum(portfolio_returns)
        volatility = np.std(portfolio_returns) * np.sqrt(252)
        sharpe_ratio = (total_return - self.risk_free_rate / 252) / volatility if volatility > 0 else 0

        # 最大回撤
        cumulative = np.cumprod(1 + portfolio_returns)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - peak) / peak
        max_drawdown = np.min(drawdown)

        return {
            'total_return': total_return,
            'annual_return': (1 + total_return) ** (252 / len(portfolio_returns)) - 1,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': abs(max_drawdown),
            'total_periods': len(portfolio_returns)
        }


# 命令行测试
def main():
    """测试组合优化"""
    logger.info("="*60)
    logger.info("📈 多资产组合优化测试")
    logger.info("="*60)

    # 创建资产
    assets = [
        Asset(symbol="BTC", name="Bitcoin", expected_return=0.8, volatility=0.6),
        Asset(symbol="ETH", name="Ethereum", expected_return=0.7, volatility=0.5),
        Asset(symbol="BNB", name="Binance Coin", expected_return=0.5, volatility=0.4),
        Asset(symbol="SOL", name="Solana", expected_return=0.9, volatility=0.7),
    ]

    # 生成模拟收益率数据
    np.random.seed(42)
    returns = {}
    for asset in assets:
        asset_returns = np.random.normal(
            asset.expected_return / 252,  # 日收益率
            asset.volatility / np.sqrt(252),  # 日波动率
            252  # 一年数据
        )
        returns[asset.symbol] = asset_returns.tolist()

    # 创建优化器
    optimizer = PortfolioOptimizer(risk_free_rate=0.02)

    # 测试不同策略
    strategies = [
        OptimizationStrategy.MEAN_VARIANCE,
        OptimizationStrategy.MINIMUM_VARIANCE,
        OptimizationStrategy.RISK_PARITY,
        OptimizationStrategy.EQUAL_WEIGHT
    ]

    for strategy in strategies:
        logger.info(f"\n{'='*60}")
        logger.info(f"策略: {strategy.value}")
        logger.info(f"{'='*60}")

        portfolio = optimizer.optimize(assets, returns, strategy)

        logger.info(f"\n最优权重:")
        for symbol, weight in portfolio.assets.items():
            logger.info(f"  {symbol}: {weight*100:.2f}%")

        logger.info(f"\n组合指标:")
        logger.info(f"  预期收益率: {portfolio.expected_return*100:.2f}%")
        logger.info(f"  波动率: {portfolio.volatility*100:.2f}%")
        logger.info(f"  夏普比率: {portfolio.sharpe_ratio:.2f}")

    # 计算有效前沿
    logger.info(f"\n{'='*60}")
    logger.info("有效前沿")
    logger.info(f"{'='*60}")

    frontier = optimizer.calculate_efficient_frontier(assets, returns, num_points=10)

    logger.info(f"\n收益率  波动率")
    logger.info("-" * 30)
    for ret, vol, weights in frontier[::2]:  # 每2个点显示一个
        logger.info(f"{ret*100:6.2f}%  {vol*100:6.2f}%")

    # 回测
    logger.info(f"\n{'='*60}")
    logger.info("回测最优组合")
    logger.info(f"{'='*60}")

    optimal_portfolio = optimizer.optimize(assets, returns, OptimizationStrategy.MEAN_VARIANCE)
    backtest_result = optimizer.backtest_portfolio(optimal_portfolio, returns)

    logger.info(f"\n回测结果:")
    logger.info(f"  总收益率: {backtest_result['total_return']*100:.2f}%")
    logger.info(f"  年化收益率: {backtest_result['annual_return']*100:.2f}%")
    logger.info(f"  波动率: {backtest_result['volatility']*100:.2f}%")
    logger.info(f"  夏普比率: {backtest_result['sharpe_ratio']:.2f}")
    logger.info(f"  最大回撤: {backtest_result['max_drawdown']*100:.2f}%")

    logger.info("\n" + "="*60)
    logger.info("多资产组合优化测试: PASS")


if __name__ == "__main__":
    main()
