# -*- coding: utf-8 -*-
"""
test_impact_model.py - 市场冲击模型单元测试
Stage 2 产出：验证 impact_model.py 核心功能
注意: estimate_impact(order_size, volatility, adv, **kwargs) - price和is_buy是kwargs
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np
import pandas as pd
from scripts.impact_model import (
    SquareRootImpact, AlmgrenChrissImpact, HawkesImpact,
    ImpactModelFactory, ImpactCostEstimator
)


class TestSquareRootImpact:
    """平方根冲击模型测试"""

    def test_basic_impact(self):
        """基本冲击估算"""
        model = SquareRootImpact(eta=0.5)
        result = model.estimate_impact(
            order_size=1.0,
            volatility=0.80,
            adv=1000.0,
            price=50000.0,
            is_buy=True
        )

        assert 'total_impact' in result
        assert 'slippage_bps' in result
        assert 'participation_rate' in result
        assert result['participation_rate'] == 0.001
        assert result['slippage_bps'] > 0  # 买入推高

    def test_buy_vs_sell(self):
        """买卖方向对称"""
        model = SquareRootImpact(eta=0.5)

        buy = model.estimate_impact(1.0, 0.8, 1000.0, price=50000.0, is_buy=True)
        sell = model.estimate_impact(1.0, 0.8, 1000.0, price=50000.0, is_buy=False)

        assert abs(buy['total_impact'] - (-sell['total_impact'])) < 1e-10, \
            "买卖冲击应符号相反,绝对值相等"

    def test_participation_rate_scaling(self):
        """参与率缩放"""
        model = SquareRootImpact(eta=0.5)
        adv = 1000.0

        impact_1x = model.estimate_impact(100.0, 0.8, adv, price=50000.0, is_buy=True)
        impact_4x = model.estimate_impact(400.0, 0.8, adv, price=50000.0, is_buy=True)

        expected_ratio = np.sqrt(0.4/0.1)
        actual_ratio = abs(impact_4x['total_impact']) / abs(impact_1x['total_impact'])

        assert abs(actual_ratio - expected_ratio) < 0.01, \
            f"冲击缩放应为√(Q2/Q1): {expected_ratio:.2f}, 实际: {actual_ratio:.2f}"

    def test_zero_adv(self):
        """零ADV边界"""
        model = SquareRootImpact()
        result = model.estimate_impact(1.0, 0.8, 0.0, price=50000.0, is_buy=True)
        assert result['total_impact'] == 0

    def test_zero_order(self):
        """零订单边界"""
        model = SquareRootImpact()
        result = model.estimate_impact(0.0, 0.8, 1000.0, price=50000.0, is_buy=True)
        assert result['total_impact'] == 0

    def test_model_name(self):
        """模型名称"""
        model = SquareRootImpact(eta=0.3)
        name = model.get_model_name()
        assert 'SquareRoot' in name


class TestAlmgrenChrissImpact:
    """Almgren-Chriss冲击模型测试"""

    def test_basic_impact(self):
        """基本AC冲击"""
        model = AlmgrenChrissImpact(gamma=0.05, eta=0.5, alpha=0.6)
        result = model.estimate_impact(
            order_size=10.0, volatility=0.80, adv=1000.0,
            price=50000.0, is_buy=True, execution_time=0.5
        )

        assert 'permanent_impact' in result
        assert 'temporary_impact' in result
        assert result['total_impact'] > 0

    def test_alpha_sensitivity(self):
        """α指数影响: α越小 → (v^α)越大(当v<1时),故小α冲击更大"""
        model_low = AlmgrenChrissImpact(alpha=0.3)
        model_high = AlmgrenChrissImpact(alpha=0.9)

        low = model_low.estimate_impact(10.0, 0.8, 1000.0, price=50000.0, is_buy=True)
        high = model_high.estimate_impact(10.0, 0.8, 1000.0, price=50000.0, is_buy=True)

        # 当参与率<1时, v^0.3 > v^0.9,故低α→更高冲击
        assert abs(low['temporary_impact']) > abs(high['temporary_impact']), \
            f"低参与率时小α应产生更大冲击: low={abs(low['temporary_impact']):.4f}, high={abs(high['temporary_impact']):.4f}"

    def test_buy_sell_symmetry(self):
        """买卖对称"""
        model = AlmgrenChrissImpact()
        buy = model.estimate_impact(5.0, 0.8, 1000.0, price=50000.0, is_buy=True)
        sell = model.estimate_impact(5.0, 0.8, 1000.0, price=50000.0, is_buy=False)
        assert abs(buy['total_impact'] + sell['total_impact']) < 1e-10


class TestHawkesImpact:
    """Hawkes冲击模型测试"""

    def test_default_params(self):
        """默认参数"""
        model = HawkesImpact()
        result = model.estimate_impact(
            order_size=1.0, volatility=0.8, adv=1000.0,
            price=50000.0, is_buy=True
        )

        assert 'self_excitation_factor' in result
        assert result['self_excitation_factor'] > 1.0
        assert 'total_impact' in result

    def test_self_excitation_scales_impact(self):
        """自激因子放大冲击"""
        model_no_self = HawkesImpact(alpha=0.0)
        model_with_self = HawkesImpact(alpha=0.5)

        no_self = model_no_self.estimate_impact(1.0, 0.8, 1000.0, price=50000.0, is_buy=True)
        with_self = model_with_self.estimate_impact(1.0, 0.8, 1000.0, price=50000.0, is_buy=True)

        assert abs(with_self['total_impact']) > abs(no_self['total_impact'])

    def test_buy_sell_symmetry(self):
        """买卖对称"""
        model = HawkesImpact()
        buy = model.estimate_impact(1.0, 0.8, 1000.0, price=50000.0, is_buy=True)
        sell = model.estimate_impact(1.0, 0.8, 1000.0, price=50000.0, is_buy=False)
        assert abs(buy['total_impact'] + sell['total_impact']) < 1e-10

    def test_zero_params(self):
        """零参数处理"""
        model = HawkesImpact(alpha=0.0, beta=0.0)
        result = model.estimate_impact(1.0, 0.8, 1000.0, price=50000.0, is_buy=True)
        assert 'total_impact' in result

    def test_model_name(self):
        """模型名称"""
        model = HawkesImpact()
        name = model.get_model_name()
        assert 'Hawkes' in name


class TestImpactModelFactory:
    """工厂类测试"""

    def test_create_all_types(self):
        """创建所有模型类型"""
        for model_type in ['sqrt', 'square_root', 'ac', 'almgren_chriss', 'hawkes']:
            model = ImpactModelFactory.create(model_type)
            assert model is not None
            assert hasattr(model, 'estimate_impact')
            assert hasattr(model, 'get_model_name')

    def test_compare_all(self):
        """对比所有模型"""
        df = ImpactModelFactory.compare_all(
            order_size=10.0, volatility=0.8, adv=1000.0,
            price=50000.0, is_buy=True
        )

        assert len(df) == 3
        assert 'model' in df.columns
        assert 'total_impact' in df.columns
        assert 'slippage_bps' in df.columns
        assert any(abs(df['total_impact']) > 0)


class TestImpactCostEstimator:
    """高级估算器测试"""

    def test_estimate_order(self):
        """单个订单估算"""
        estimator = ImpactCostEstimator(model_type='sqrt')

        result = estimator.estimate_order(
            symbol='BTCUSDT',
            quantity=1.0,
            price=50000.0,
            is_buy=True
        )

        assert 'symbol' in result
        assert 'cost_amount' in result
        assert 'cost_pct' in result
        assert result['symbol'] == 'BTCUSDT'
        assert result['notional'] == 50000.0

    def test_estimate_batch(self):
        """批量估算"""
        estimator = ImpactCostEstimator(model_type='sqrt')
        orders = [
            {'symbol': 'BTCUSDT', 'quantity': 1.0, 'is_buy': True},
            {'symbol': 'ETHUSDT', 'quantity': 10.0, 'is_buy': False},
        ]
        price_dict = {'BTCUSDT': 50000.0, 'ETHUSDT': 3000.0}

        df = estimator.estimate_batch(orders, price_dict)

        assert len(df) == 2
        assert 'symbol' in df.columns

    def test_recommended_model(self):
        """推荐模型"""
        estimator = ImpactCostEstimator()

        rec = estimator.get_recommended_model('high', has_trade_data=True)
        assert rec == 'hawkes'

        rec = estimator.get_recommended_model('medium')
        assert rec == 'sqrt'


class TestImpactComparison:
    """模型对比测试"""

    def test_hawkes_self_excitation(self):
        """Hawkes自激效应"""
        hawkes = ImpactModelFactory.create('hawkes')
        result = hawkes.estimate_impact(10.0, 0.8, 1000.0, price=50000.0, is_buy=True)

        assert 'self_excitation_factor' in result
        assert result['self_excitation_factor'] > 1.0

    def test_impact_increases_with_participation(self):
        """参与率越高,冲击越大"""
        for m_type in ['sqrt', 'ac', 'hawkes']:
            model = ImpactModelFactory.create(m_type)

            small = model.estimate_impact(100.0, 0.8, 1000.0, price=50000.0, is_buy=True)
            large = model.estimate_impact(500.0, 0.8, 1000.0, price=50000.0, is_buy=True)

            assert abs(large['total_impact']) > abs(small['total_impact']), \
                f"{m_type}: 大订单冲击应更大"


class TestEdgeCases:
    """边界情况"""

    def test_negative_volatility(self):
        """负波动率"""
        model = SquareRootImpact()
        result = model.estimate_impact(1.0, -0.5, 1000.0, price=50000.0, is_buy=True)
        assert 'total_impact' in result

    def test_very_large_order(self):
        """超大订单"""
        model = SquareRootImpact()
        result = model.estimate_impact(100000.0, 0.8, 1000.0, price=50000.0, is_buy=True)
        assert 'total_impact' in result
        assert not np.isnan(result['total_impact'])

    def test_near_zero_price(self):
        """接近零价格"""
        model = SquareRootImpact()
        result = model.estimate_impact(1.0, 0.8, 1000.0, price=1e-10, is_buy=True)
        assert 'total_impact' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
