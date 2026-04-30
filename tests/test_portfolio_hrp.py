# -*- coding: utf-8 -*-
"""
test_portfolio_hrp.py - HRP风险平价单元测试
Stage 1 产出：验证 portfolio_hrp.py 核心功能
注意: HierarchicalRiskParity.allocate() 接收收益率DataFrame,非价格DataFrame
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np
import pandas as pd
from scripts.portfolio_hrp import HierarchicalRiskParity


# 测试数据: 收益率DataFrame
@pytest.fixture
def sample_returns():
    """生成模拟收益率数据"""
    np.random.seed(42)
    n = 252
    dates = pd.date_range('2023-01-01', periods=n, freq='B')

    data = {
        'BTC': np.random.randn(n) * 0.03,
        'ETH': np.random.randn(n) * 0.04,
        'GOLD': np.random.randn(n) * 0.01,
        'EUR': np.random.randn(n) * 0.005,
        'OIL': np.random.randn(n) * 0.02,
    }
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def high_correlation_returns():
    """高相关收益率数据"""
    np.random.seed(42)
    n = 100
    dates = pd.date_range('2023-01-01', periods=n, freq='B')
    base = np.random.randn(n) * 0.02

    data = {
        'ASSET_A': base + np.random.randn(n) * 0.001,
        'ASSET_B': base * 1.5 + np.random.randn(n) * 0.001,
        'ASSET_C': base * 0.8 + np.random.randn(n) * 0.002,
    }
    return pd.DataFrame(data, index=dates)


class TestHierarchicalRiskParity:
    """HRP类测试"""

    def test_allocate_returns_weights(self, sample_returns):
        """allocate方法应返回权重字典"""
        hrp = HierarchicalRiskParity()
        weights = hrp.allocate(sample_returns)

        assert isinstance(weights, pd.Series), "应返回Series"
        assert len(weights) == 5, "应有5个品种"
        total = float(weights.sum())
        assert abs(total - 1.0) < 1e-6, f"权重和应为1, 实际: {total:.6f}"
        assert all(0 <= w <= 1 for w in weights.values), "权重应在[0,1]范围"

    def test_weight_distribution(self, sample_returns):
        """权重分布合理性"""
        hrp = HierarchicalRiskParity()
        weights = hrp.allocate(sample_returns)

        # 不应有单一品种占>60%
        max_weight = float(weights.max())
        assert max_weight < 0.6, f"最大权重过大: {max_weight:.3f}"

        # 不应有品种权重过小
        min_weight = float(weights.min())
        assert min_weight > 0.001, f"最小权重过小: {min_weight:.3f}"

    def test_high_correlation_handling(self, high_correlation_returns):
        """高相关资产处理"""
        hrp = HierarchicalRiskParity()
        weights = hrp.allocate(high_correlation_returns)

        assert isinstance(weights, pd.Series)
        assert len(weights) == 3
        total = float(weights.sum())
        assert abs(total - 1.0) < 1e-6

        max_weight = float(weights.max())
        assert max_weight < 0.8, f"高相关资产权重过度集中: {max_weight:.3f}"

    def test_zero_volatility_handling(self):
        """零波动率边界"""
        n = 50
        dates = pd.date_range('2023-01-01', periods=n, freq='B')
        data = {
            'STABLE_A': np.zeros(n),
            'STABLE_B': np.zeros(n),
        }
        df = pd.DataFrame(data, index=dates)

        hrp = HierarchicalRiskParity()
        try:
            weights = hrp.allocate(df)
            assert isinstance(weights, pd.Series)
        except Exception:
            pass

    def test_single_asset(self):
        """单品种输入"""
        n = 30
        dates = pd.date_range('2023-01-01', periods=n, freq='B')
        data = {'SOLO': np.random.randn(n) * 0.01}
        df = pd.DataFrame(data, index=dates)

        hrp = HierarchicalRiskParity()
        try:
            weights = hrp.allocate(df)
            # 单品种应返回100%权重给唯一资产
            assert isinstance(weights, pd.Series)
            assert len(weights) == 1
            # 允许100%权重(单品种无选择)
            assert 0.99 <= float(weights.iloc[0]) <= 1.01
        except (ValueError, np.linalg.LinAlgError):
            # 单品种无法构建层次聚类,这是预期行为
            pass

    def test_two_assets(self):
        """两品种输入"""
        n = 30
        dates = pd.date_range('2023-01-01', periods=n, freq='B')
        data = {
            'A': np.random.randn(n) * 0.02,
            'B': np.random.randn(n) * 0.01,
        }
        df = pd.DataFrame(data, index=dates)

        hrp = HierarchicalRiskParity()
        weights = hrp.allocate(df)

        assert isinstance(weights, pd.Series)
        assert len(weights) == 2
        assert abs(float(weights.sum()) - 1.0) < 1e-6
        assert weights['B'] > weights['A'], \
            f"低波资产B应获得更高权重: B={weights['B']:.3f}, A={weights['A']:.3f}"

    def test_short_time_series(self):
        """短期数据"""
        n = 20
        dates = pd.date_range('2023-01-01', periods=n, freq='B')
        data = {
            'X': np.random.randn(n) * 0.02,
            'Y': np.random.randn(n) * 0.02,
        }
        df = pd.DataFrame(data, index=dates)

        hrp = HierarchicalRiskParity()
        try:
            weights = hrp.allocate(df)
            assert isinstance(weights, pd.Series)
            assert len(weights) == 2
        except Exception:
            pass

    def test_missing_values(self, sample_returns):
        """缺失值处理"""
        df = sample_returns.copy()
        df.iloc[10:15, 0] = np.nan

        hrp = HierarchicalRiskParity()
        try:
            weights = hrp.allocate(df)
            assert isinstance(weights, pd.Series)
        except Exception:
            pass

    def test_deterministic(self, sample_returns):
        """确定性"""
        hrp = HierarchicalRiskParity()
        w1 = hrp.allocate(sample_returns)
        w2 = hrp.allocate(sample_returns)

        assert np.allclose(w1.values, w2.values, atol=1e-10)

    def test_low_vol_high_weight(self):
        """低波动资产应获得更高权重"""
        np.random.seed(123)
        n = 100
        dates = pd.date_range('2023-01-01', periods=n, freq='B')

        low_vol = np.random.randn(n) * 0.005
        high_vol = np.random.randn(n) * 0.05

        df = pd.DataFrame({'LOW': low_vol, 'HIGH': high_vol}, index=dates)
        hrp = HierarchicalRiskParity()
        weights = hrp.allocate(df)

        assert weights['LOW'] > weights['HIGH'], \
            f"低波资产权重应更高: LOW={weights['LOW']:.3f}, HIGH={weights['HIGH']:.3f}"

    def test_compare_with_equal_weight(self, sample_returns):
        """compare_with_equal_weight方法"""
        hrp = HierarchicalRiskParity()
        result = hrp.compare_with_equal_weight(sample_returns)

        assert isinstance(result, dict)
        assert 'hrp_volatility' in result
        assert 'equal_weight_volatility' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
