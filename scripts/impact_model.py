#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
impact_model.py - 市场冲击模型统一接口
Stage 2 产出：整合backtest_adapter滑点计算

支持三种冲击模型:
1. AlmgrenChrissImpact: AC框架, 冲击-方差权衡
2. SquareRootImpact: 平方根法则, 实证支持最强
3. HawkesImpact: 自激过程, 捕捉订单流聚集性
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from typing import Dict, Optional, Literal
from abc import ABC, abstractmethod
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


# ===================== 抽象基类 =====================

class BaseImpactModel(ABC):
    """市场冲击模型基类"""

    def _zero_result(self) -> Dict[str, float]:
        """零结果工厂方法"""
        return {
            'permanent_impact': 0.0,
            'temporary_impact': 0.0,
            'total_impact': 0.0,
            'impact_pct': 0.0,
            'slippage_bps': 0.0,
        }

    @abstractmethod
    def estimate_impact(self, order_size: float, volatility: float,
                      adv: float, **kwargs) -> Dict[str, float]:
        """
        估算订单冲击成本

        Args:
            order_size: 订单数量
            volatility: 资产波动率 (年化)
            adv: 平均日成交量

        Returns:
            dict: {
                'permanent_impact': 永久冲击成本,
                'temporary_impact': 临时冲击成本,
                'total_impact': 总冲击成本,
                'impact_pct': 冲击占订单金额比例,
                'slippage_bps': 滑点(基点)
            }
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        pass


# ===================== 平方根冲击模型 =====================

class SquareRootImpact(BaseImpactModel):
    """
    平方根冲击模型 (Almgren, Thum, Hauptmann, 2005)

    核心公式:
        impact = σ × √(Q / ADV) × η

    其中:
        σ = 年化波动率
        Q = 订单数量
        ADV = 平均日成交量
        η = 流动性系数 (通常 0.1-1.0, 取决于市场深度)

    实证支持:
        - Almgren, Thum, Hauptmann (2005): 德国股票数据验证
        - Torre & Ferrari (1999): 纳斯达克数据支持
        - 平方根法则在大多数资产类别成立

    局限性:
        - 忽略交易方向的不对称性
        - 假设流动性参数η恒定
        - 不考虑市场状态
    """

    def __init__(self, eta: float = 0.5, permanent_ratio: float = 0.1):
        """
        Args:
            eta: 流动性系数, 0.1(流动性好)到1.0(流动性差)
            permanent_ratio: 永久冲击占比, 通常0.1-0.2
        """
        self.eta = eta
        self.permanent_ratio = permanent_ratio

    def estimate_impact(self, order_size: float, volatility: float,
                       adv: float, **kwargs) -> Dict[str, float]:
        """估算平方根冲击"""
        if adv <= 0 or order_size <= 0:
            return self._zero_result()

        price = kwargs.get('price', 1.0)
        is_buy = kwargs.get('is_buy', True)

        # 参与率 (订单量占日均成交量的比例)
        participation_rate = order_size / adv

        # 波动率缩放因子 (年化 → 日内)
        daily_vol = volatility / np.sqrt(252)

        # 平方根冲击
        sqrt_impact = daily_vol * self.eta * np.sqrt(max(0, participation_rate))

        # 永久冲击 vs 临时冲击
        permanent_impact = sqrt_impact * self.permanent_ratio
        temporary_impact = sqrt_impact * (1 - self.permanent_ratio)

        total_impact = permanent_impact + temporary_impact

        # 方向调整: 买入推高价格(正冲击), 卖出压低价格(负冲击)
        direction = 1 if is_buy else -1

        result = {
            'permanent_impact': direction * permanent_impact * price,
            'temporary_impact': direction * temporary_impact * price,
            'total_impact': direction * total_impact * price,
            'impact_pct': direction * total_impact,
            'slippage_bps': direction * total_impact / price * 10000,
            'participation_rate': participation_rate,
            'model': 'square_root',
        }

        logger.debug(f"SquareRoot impact: order={order_size}, adv={adv:.2f}, "
                    f"participation={participation_rate:.3f}, total={total_impact:.6f}")

        return result

    def get_model_name(self) -> str:
        return f"SquareRoot(eta={self.eta})"


# ===================== Almgren-Chriss 模型 =====================

class AlmgrenChrissImpact(BaseImpactModel):
    """
    Almgren-Chriss 冲击模型 (2001)

    核心框架:
        永久冲击 (线性): γ × v
        临时冲击 (非线性): η × v^α / ADV

    其中:
        v = 交易速率 (数量/时间)
        γ = 永久冲击系数
        η = 临时冲击系数
        α = 临时冲击指数 (通常接近0.6)
        ADV = 平均日成交量

    数学性质:
        - AC模型提供了冲击-方差权衡的解析边界
        - 最优执行时间由: η/(γ + η × T/ADV) 决定
        - α<1 时存在最优执行策略

    局限性:
        - 永久冲击线性假设在现实中不严格成立
        - 参数需要从历史数据拟合
        - 不考虑市场微观结构效应
    """

    def __init__(self, gamma: float = 0.05, eta: float = 0.5,
                 alpha: float = 0.6, permanent_ratio: float = 0.1):
        """
        Args:
            gamma: 永久冲击系数
            eta: 临时冲击系数
            alpha: 临时冲击指数 (0.5-0.7 经验值)
            permanent_ratio: 永久冲击占总冲击比例
        """
        self.gamma = gamma
        self.eta = eta
        self.alpha = alpha
        self.permanent_ratio = permanent_ratio

    def estimate_impact(self, order_size: float, volatility: float,
                       adv: float, **kwargs) -> Dict[str, float]:
        """估算AC冲击"""
        if adv <= 0 or order_size <= 0:
            return self._zero_result()

        price = kwargs.get('price', 1.0)
        is_buy = kwargs.get('is_buy', True)
        execution_time = kwargs.get('execution_time', 1.0)  # 执行时间(天)
        n_periods = kwargs.get('n_periods', 10)  # 分多少批执行

        direction = 1 if is_buy else -1

        # 日内波动率
        daily_vol = volatility / np.sqrt(252)

        # 交易速率
        avg_rate = order_size / max(execution_time, 1e-10)  # 数量/天
        avg_velocity = avg_rate / max(adv, 1e-10)  # 相对ADV的速率

        # AC临时冲击: η × v^α
        # 注意: 原始公式用v(绝对速率),这里用相对速率
        temp_impact = self.eta * (avg_velocity ** self.alpha) * daily_vol

        # AC永久冲击: γ × v
        perm_impact = self.gamma * avg_velocity * daily_vol

        # 总冲击
        total_impact = perm_impact + temp_impact

        result = {
            'permanent_impact': direction * perm_impact * price,
            'temporary_impact': direction * temp_impact * price,
            'total_impact': direction * total_impact * price,
            'impact_pct': direction * total_impact,
            'slippage_bps': direction * total_impact / price * 10000,
            'execution_time': execution_time,
            'n_periods': n_periods,
            'avg_velocity': avg_velocity,
            'model': 'almgren_chriss',
        }

        logger.debug(f"AC impact: order={order_size}, velocity={avg_velocity:.3f}, "
                    f"total={total_impact:.6f}")

        return result

    def get_model_name(self) -> str:
        return f"AlmgrenChriss(gamma={self.gamma},eta={self.eta},alpha={self.alpha})"


# ===================== Hawkes 冲击模型 =====================

class HawkesImpact(BaseImpactModel):
    """
    Hawkes 冲击模型 (2013+)

    基于自激点过程的市场冲击:
        λ(t) = μ + ∫ α e^(-β(t-s)) dN(s)

    冲击传播机制:
        - 每次交易触发后续订单流的瞬时增加
        - 冲击以指数速率衰减
        - 订单聚集性由自激系数α决定

    核心公式:
        E[ΔP | order at t] = σ × η × (1 + α/β)

    优点:
        - 捕捉订单流聚集性
        - 冲击衰减由数据驱动
        - 可用于高频数据

    局限性:
        - 参数估计复杂(需要足够高频数据)
        - 对市场状态变化敏感
        - 计算成本高
    """

    def __init__(self, mu: float = 0.5, alpha: float = 0.3, beta: float = 1.0,
                 eta: float = 0.1, permanent_ratio: float = 0.1):
        """
        Args:
            mu: 基准事件强度 (背景订单流)
            alpha: 自激系数 (0=无自激, 0.5=强自激)
            beta: 衰减速率 (越大衰减越快)
            eta: 冲击系数
            permanent_ratio: 永久冲击比例
        """
        self.mu = mu
        self.alpha = alpha
        self.beta = beta
        self.eta = eta
        self.permanent_ratio = permanent_ratio

        # 从系统已有的hawkes_process模块估计的参数
        self._fitted = False

    def fit(self, trade_data: pd.DataFrame, price_data: Optional[pd.DataFrame] = None) -> 'HawkesImpact':
        """
        从历史数据拟合Hawkes参数

        Args:
            trade_data: 交易数据 (需要包含timestamp列)
            price_data: 价格数据 (可选)

        Returns:
            self
        """
        if len(trade_data) < 100:
            logger.warning("Insufficient trade data for Hawkes fitting, using defaults")
            return self

        try:
            # 计算事件时间间隔
            timestamps = pd.to_datetime(trade_data.get('timestamp', trade_data.index))
            inter_arrival = timestamps.diff().dropna().dt.total_seconds()

            if len(inter_arrival) < 10:
                logger.warning("Too few inter-arrival times, using defaults")
                return self

            # 简化参数估计
            mean_dt = inter_arrival.mean()
            std_dt = inter_arrival.std()

            # 经验公式估计 μ, α, β
            # μ ≈ 1/E[Δt] (背景强度)
            # α ≈ CV² - 1 (自激强度, CV=变异系数)
            cv = std_dt / (mean_dt + 1e-10)
            self.mu = 1.0 / max(mean_dt, 1)  # 归一化
            self.alpha = max(0, min(0.9, cv**2 - 1))  # 限制在[0, 0.9]
            self.beta = 1.0 / max(mean_dt * 0.5, 0.1)  # 衰减速率

            # 从价格数据估计η (如果有)
            if price_data is not None and len(price_data) > 50:
                returns = price_data['close'].pct_change().dropna()
                vol = returns.std() * np.sqrt(252 * 24)  # 小时波动率→年化
                # η与波动率正相关
                self.eta = min(1.0, vol * 10)

            self._fitted = True
            logger.info(f"Hawkes fitted: mu={self.mu:.3f}, alpha={self.alpha:.3f}, "
                       f"beta={self.beta:.3f}, eta={self.eta:.3f}")

        except Exception as e:
            logger.warning(f"Hawkes fitting failed: {e}, using defaults")

        return self

    def estimate_impact(self, order_size: float, volatility: float,
                       adv: float, **kwargs) -> Dict[str, float]:
        """估算Hawkes冲击"""
        if adv <= 0 or order_size <= 0:
            return self._zero_result()

        price = kwargs.get('price', 1.0)
        is_buy = kwargs.get('is_buy', True)
        n_periods = kwargs.get('n_periods', 10)

        direction = 1 if is_buy else -1
        daily_vol = volatility / np.sqrt(252)
        participation = order_size / adv

        # Hawkes自激因子: (1 + α × n_periods / β)
        # 替代公式: 基于自激强度调整的冲击
        if self._fitted:
            # 使用拟合参数
            self_excitation_factor = 1.0 + (self.alpha / max(self.beta, 0.1))
        else:
            # 使用默认参数
            self_excitation_factor = 1.0 + (self.alpha / max(self.beta, 0.1))

        # 基础平方根冲击
        base_impact = daily_vol * self.eta * np.sqrt(max(0, participation))

        # Hawkes调整: 自激增加冲击
        hawkes_impact = base_impact * self_excitation_factor

        # 永久 vs 临时
        perm_impact = hawkes_impact * self.permanent_ratio
        temp_impact = hawkes_impact * (1 - self.permanent_ratio)

        result = {
            'permanent_impact': direction * perm_impact * price,
            'temporary_impact': direction * temp_impact * price,
            'total_impact': direction * hawkes_impact * price,
            'impact_pct': direction * hawkes_impact,
            'slippage_bps': direction * hawkes_impact / price * 10000,
            'self_excitation_factor': self_excitation_factor,
            'n_periods': n_periods,
            'participation_rate': participation,
            'fitted': self._fitted,
            'model': 'hawkes',
        }

        logger.debug(f"Hawkes impact: order={order_size}, self_exc={self_excitation_factor:.2f}, "
                    f"total={hawkes_impact:.6f}, fitted={self._fitted}")

        return result

    def get_model_name(self) -> str:
        status = "fitted" if self._fitted else "default"
        return f"Hawkes({status},α={self.alpha:.2f},β={self.beta:.2f})"


# ===================== 统一接口 =====================

class ImpactModelFactory:
    """
    冲击模型工厂
    提供统一接口选择和管理多种冲击模型
    """

    @staticmethod
    def create(model_type: Literal['sqrt', 'square_root', 'ac', 'almgren_chriss', 'hawkes'],
               **kwargs) -> BaseImpactModel:
        """创建冲击模型实例"""
        model_map = {
            'sqrt': SquareRootImpact,
            'square_root': SquareRootImpact,
            'ac': AlmgrenChrissImpact,
            'almgren_chriss': AlmgrenChrissImpact,
            'hawkes': HawkesImpact,
        }

        if model_type not in model_map:
            logger.warning(f"Unknown model {model_type}, using SquareRoot")
            model_type = 'square_root'

        return model_map[model_type](**kwargs)

    @staticmethod
    def estimate(model_type: Literal['sqrt', 'ac', 'hawkes'],
               order_size: float, volatility: float, adv: float,
               price: float = 1.0, is_buy: bool = True, **kwargs) -> Dict[str, float]:
        """一行调用估算冲击"""
        model = ImpactModelFactory.create(model_type)
        return model.estimate_impact(order_size, volatility, adv,
                                     price=price, is_buy=is_buy, **kwargs)

    @staticmethod
    def compare_all(order_size: float, volatility: float, adv: float,
                   price: float = 1.0, is_buy: bool = True) -> pd.DataFrame:
        """对比所有模型的冲击估算"""
        models = ['sqrt', 'ac', 'hawkes']
        results = []

        for m_type in models:
            result = ImpactModelFactory.estimate(
                m_type, order_size, volatility, adv, price, is_buy
            )
            results.append({
                'model': result.get('model', m_type),
                'total_impact': result['total_impact'],
                'impact_pct': result['impact_pct'],
                'slippage_bps': result['slippage_bps'],
            })

        df = pd.DataFrame(results)
        return df


class ImpactCostEstimator:
    """
    冲击成本估算器
    提供高级接口,自动处理常见场景
    """

    def __init__(self, model_type: Literal['sqrt', 'ac', 'hawkes'] = 'sqrt',
                 default_eta: float = 0.5):
        self.model = ImpactModelFactory.create(model_type, eta=default_eta)
        self.model_type = model_type

    def estimate_order(self, symbol: str, quantity: float, price: float,
                      volatility: Optional[float] = None,
                      adv: Optional[float] = None,
                      is_buy: bool = True) -> Dict[str, float]:
        """
        估算单个订单的冲击成本

        Args:
            symbol: 品种代码
            quantity: 订单数量
            price: 当前价格
            volatility: 年化波动率 (如果为None, 从历史数据估计)
            adv: 平均日成交量 (如果为None, 估算)
            is_buy: 是否买入

        Returns:
            dict: 冲击成本报告
        """
        # 如果没有提供波动率,使用保守估计
        if volatility is None:
            # 加密货币: 60-100%年化
            if 'USDT' in symbol or 'BTC' in symbol or 'ETH' in symbol:
                volatility = 0.80
            else:
                volatility = 0.20

        # 如果没有提供ADV,估算
        if adv is None:
            # 假设ADV约为日成交额的0.01-0.1%
            adv = quantity * 20  # 保守: 订单量的20倍作为日均量

        result = self.model.estimate_impact(
            order_size=quantity,
            volatility=volatility,
            adv=adv,
            price=price,
            is_buy=is_buy,
        )

        # 计算实际成本(金额)
        notional = quantity * price
        result['notional'] = notional
        result['cost_amount'] = abs(result['total_impact'] * notional)
        result['cost_pct'] = result['impact_pct'] * 100  # 转为百分比
        result['symbol'] = symbol
        result['quantity'] = quantity
        result['price'] = price
        result['model_type'] = self.model_type

        return result

    def estimate_batch(self, orders: list, price_dict: dict,
                      vol_dict: Optional[dict] = None) -> pd.DataFrame:
        """
        批量估算多个订单的冲击成本

        Args:
            orders: 订单列表 [{'symbol': str, 'quantity': float, 'is_buy': bool}]
            price_dict: {symbol: price}
            vol_dict: {symbol: volatility} (可选)

        Returns:
            DataFrame: 所有订单的冲击成本
        """
        results = []
        for order in orders:
            sym = order['symbol']
            price = price_dict.get(sym, 1.0)
            vol = vol_dict.get(sym) if vol_dict else None
            adv = order.get('adv')

            result = self.estimate_order(
                symbol=sym,
                quantity=order['quantity'],
                price=price,
                volatility=vol,
                adv=adv,
                is_buy=order.get('is_buy', True),
            )
            results.append(result)

        return pd.DataFrame(results)

    def get_recommended_model(self, frequency: Literal['high', 'medium', 'low'] = 'medium',
                            has_trade_data: bool = False) -> str:
        """
        根据交易频率推荐冲击模型

        Args:
            frequency: 交易频率
            has_trade_data: 是否有高频交易数据用于拟合Hawkes

        Returns:
            str: 推荐模型类型
        """
        if frequency == 'high' and has_trade_data:
            return 'hawkes'
        elif frequency == 'high':
            return 'ac'
        elif frequency == 'medium':
            return 'sqrt'
        else:
            return 'sqrt'


# ===================== 命令行入口 =====================

def main():
    """命令行测试"""
    import argparse

    parser = argparse.ArgumentParser(description='市场冲击成本估算')
    parser.add_argument('--model', choices=['sqrt', 'ac', 'hawkes', 'compare'],
                       default='compare', help='冲击模型')
    parser.add_argument('--quantity', type=float, default=1.0,
                       help='订单数量(BTC)')
    parser.add_argument('--price', type=float, default=50000.0,
                       help='当前价格')
    parser.add_argument('--volatility', type=float, default=0.80,
                       help='年化波动率')
    parser.add_argument('--adv', type=float, default=1000.0,
                       help='平均日成交量(ADV)')
    parser.add_argument('--buy', action='store_true', help='买入(否则卖出)')

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"MARKET IMPACT COST ESTIMATION")
    print(f"{'='*60}")
    print(f"Order: {args.quantity} BTC @ ${args.price:,.0f}")
    print(f"Volatility: {args.volatility:.0%} annual")
    print(f"ADV: {args.adv:.1f} BTC")
    print(f"Direction: {'BUY' if args.buy else 'SELL'}")
    print()

    if args.model == 'compare':
        print(f"{'Model':<20} {'Total Impact':>15} {'Impact %':>10} {'Slippage(bps)':>15}")
        print("-"*65)
        df = ImpactModelFactory.compare_all(
            args.quantity, args.volatility, args.adv, args.price, args.buy
        )
        for _, row in df.iterrows():
            print(f"{row['model']:<20} {row['total_impact']:>15.6f} "
                  f"{row['impact_pct']*100:>9.4f}% {row['slippage_bps']:>15.2f}")

        print()
        print("Key insight: Compare how each model scales with participation rate")
        print(f"  Participation rate: {args.quantity/args.adv:.2%}")

    else:
        result = ImpactModelFactory.estimate(
            args.model, args.quantity, args.volatility, args.adv,
            args.price, args.buy
        )

        print(f"Model: {result['model']}")
        print(f"  Permanent impact:  {result['permanent_impact']:.6f}")
        print(f"  Temporary impact:   {result['temporary_impact']:.6f}")
        print(f"  Total impact:       {result['total_impact']:.6f}")
        print(f"  Impact %:           {result['impact_pct']*100:.4f}%")
        print(f"  Slippage:           {result['slippage_bps']:.2f} bps")

        # 成本金额
        notional = args.quantity * args.price
        cost = abs(result['total_impact']) * notional
        print(f"\n  Notional:           ${notional:,.2f}")
        print(f"  Estimated cost:     ${cost:,.2f} ({cost/notional*100:.4f}%)")

        if args.model == 'hawkes':
            print(f"  Fitted:             {result.get('fitted', False)}")
            print(f"  Self-excitation:    {result.get('self_excitation_factor', 1.0):.2f}")

    print(f"{'='*60}")


if __name__ == '__main__':
    main()
