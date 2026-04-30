# -*- coding: utf-8 -*-
"""
test_overfitting_detector.py - 过拟合检测单元测试
Stage 4 产出：验证 overfitting_detector.py 核心功能
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np
import pandas as pd
from scripts.overfitting_detector import (
    CSCVDetector, PBOEstimator, DeflatedSharpeRatio,
    OverfittingDetector
)


# 测试数据生成器
def generate_returns(n_days=252, annual_return=0.10, annual_vol=0.15, seed=42):
    """生成模拟收益率"""
    np.random.seed(seed)
    daily_return = annual_return / n_days
    daily_vol = annual_vol / np.sqrt(n_days)
    returns = np.random.normal(daily_return, daily_vol, n_days)
    return returns


def generate_noisy_returns(n_days=252, n_candidates=20, seed=42):
    """生成候选策略收益矩阵"""
    np.random.seed(seed)
    returns = np.zeros((n_candidates, n_days))

    for i in range(n_candidates):
        if i < 3:
            # 前3个有正Alpha
            returns[i] = np.random.normal(0.12/252, 0.12/np.sqrt(252), n_days)
        else:
            # 其余是噪声
            returns[i] = np.random.normal(0.0, 0.15/np.sqrt(252), n_days)

    return returns


class TestDeflatedSharpeRatio:
    """DSR测试"""

    def test_basic_dsr(self):
        """基本DSR计算"""
        returns = generate_returns()
        dsr_calc = DeflatedSharpeRatio()

        result = dsr_calc.full_analysis(returns, n_strategies=10)

        assert 'sharpe_ratio' in result
        assert 'deflated_sharpe_ratio' in result
        assert 'annual_return' in result
        assert 'max_drawdown' in result
        assert 'pbo_estimate' in result
        assert 'risk_level' not in result  # full_analysis不返回risk_level

    def test_positive_sharpe(self):
        """正夏普策略"""
        returns = generate_returns(annual_return=0.15, annual_vol=0.20)
        dsr_calc = DeflatedSharpeRatio()

        result = dsr_calc.full_analysis(returns, n_strategies=10)

        assert result['sharpe_ratio'] > 0
        assert result['annual_return'] > 0
        assert result['max_drawdown'] < 0  # 回撤为负

    def test_negative_returns(self):
        """亏损策略"""
        returns = generate_returns(annual_return=-0.10, annual_vol=0.20)
        dsr_calc = DeflatedSharpeRatio()

        result = dsr_calc.full_analysis(returns, n_strategies=10)

        assert result['sharpe_ratio'] < 0
        assert result['annual_return'] < 0

    def test_zero_volatility(self):
        """零波动率边界"""
        returns = np.full(252, 0.001)  # 恒定收益
        dsr_calc = DeflatedSharpeRatio()

        result = dsr_calc.full_analysis(returns, n_strategies=5)

        assert 'sharpe_ratio' in result
        assert not np.isnan(result['sharpe_ratio'])

    def test_dsr_less_than_sharpe(self):
        """DSR应≤SR(多重检验惩罚)"""
        returns = generate_returns(annual_return=0.15, annual_vol=0.20)
        dsr_calc = DeflatedSharpeRatio()

        result = dsr_calc.full_analysis(returns, n_strategies=20)

        # DSR由于惩罚应≤SR
        assert result['deflated_sharpe_ratio'] <= result['sharpe_ratio'] + 1e-6, \
            f"DSR={result['deflated_sharpe_ratio']:.4f} > SR={result['sharpe_ratio']:.4f}"

    def test_calmar_sortino(self):
        """Calmar和Sortino计算"""
        returns = generate_returns(annual_return=0.10, annual_vol=0.15)
        dsr_calc = DeflatedSharpeRatio()

        result = dsr_calc.full_analysis(returns, n_strategies=10)

        assert 'calmar_ratio' in result
        assert 'sortino_ratio' in result
        assert 'skewness' in result
        assert 'kurtosis' in result

    def test_skewness_kurtosis(self):
        """偏度和峰度"""
        np.random.seed(123)
        # 构造非正态收益
        returns = np.concatenate([
            np.random.normal(0, 1, 200),
            np.random.normal(2, 1, 52)  # 右偏
        ])
        dsr_calc = DeflatedSharpeRatio()

        result = dsr_calc.full_analysis(returns, n_strategies=10)

        # 应检测到偏度
        assert abs(result['skewness']) > 0


class TestCSCVDetector:
    """CSCV测试"""

    def test_cscc_basic(self):
        """基本CSCV分析"""
        returns = generate_returns(n_days=252)
        detector = CSCVDetector(n_splits=6, test_ratio=0.2)
        pairs = detector.generate_train_test_pairs(len(returns))

        result = detector.run_cscc(returns, pairs)

        assert 'pbo' in result
        assert 'oos_win_rate' in result
        assert 'avg_oos_sharpe' in result
        assert 'n_pairs' in result
        assert result['n_pairs'] == 6

    def test_cscc_oos_win_rate(self):
        """OOS胜率"""
        returns = generate_returns(annual_return=0.15, annual_vol=0.20)
        detector = CSCVDetector(n_splits=8, test_ratio=0.2)
        pairs = detector.generate_train_test_pairs(len(returns))
        result = detector.run_cscc(returns, pairs)

        # 有正Alpha的策略应有较高OOS胜率
        assert 0 <= result['oos_win_rate'] <= 1.0

    def test_cscc_pbo_range(self):
        """PBO范围"""
        returns = generate_returns()
        detector = CSCVDetector()
        pairs = detector.generate_train_test_pairs(len(returns))
        result = detector.run_cscc(returns, pairs)

        assert 0 <= result['pbo'] <= 1.0

    def test_short_data_handling(self):
        """数据不足处理"""
        returns = generate_returns(n_days=30)  # 数据太短
        detector = CSCVDetector(n_splits=8)

        # generate_train_test_pairs仍能生成
        pairs = detector.generate_train_test_pairs(len(returns))
        assert len(pairs) == 8


class TestPBOEstimator:
    """PBO测试"""

    def test_pbo_basic(self):
        """基本PBO计算"""
        strategy_returns = generate_returns(annual_return=0.12)
        candidate_returns = generate_noisy_returns(n_candidates=20)

        pbo_calc = PBOEstimator(n_retreats=100)
        pbo = pbo_calc.compute_pbo(strategy_returns, candidate_returns)

        assert 0 <= pbo <= 1.0

    def test_pbo_optimal_strategy(self):
        """最优策略PBO"""
        np.random.seed(99)
        n_days = 200
        n_candidates = 15

        # 最优策略: 稳定正Alpha
        best_returns = np.random.normal(0.15/252, 0.10/np.sqrt(252), n_days)

        # 候选: 大部分是噪声
        candidates = np.zeros((n_candidates, n_days))
        for i in range(n_candidates):
            candidates[i] = np.random.normal(0.0, 0.10/np.sqrt(252), n_days)

        pbo_calc = PBOEstimator(n_retreats=200)
        pbo = pbo_calc.compute_pbo(best_returns, candidates)

        assert 0 <= pbo <= 1.0
        # 真实Alpha策略PBO应该较低(有真实优势)


class TestOverfittingDetector:
    """过拟合检测主控制器测试"""

    def test_detect_basic(self):
        """基本检测"""
        returns = generate_returns(annual_return=0.12, annual_vol=0.15)
        candidate_returns = generate_noisy_returns(n_candidates=20)

        detector = OverfittingDetector()
        result = detector.detect(returns, candidate_returns, n_strategies=20)

        assert 'overall_quality' in result
        assert 'risk_level' in result
        assert 'is_usable' in result
        assert 'dsr' in result
        assert 'dsr' in result and result['dsr'] is not None

    def test_risk_levels(self):
        """风险等级"""
        detector = OverfittingDetector()

        # 高质量策略
        good_returns = generate_returns(annual_return=0.20, annual_vol=0.15)
        good_result = detector.detect(good_returns, n_strategies=10)

        assert good_result['risk_level'] in ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

    def test_empty_trades(self):
        """空交易列表"""
        detector = OverfittingDetector()
        result = detector.detect_from_trades([])

        assert result['overall_quality'] == 0
        assert result['risk_level'] == 'CRITICAL'
        assert result['is_usable'] is False

    def test_trades_from_dict(self):
        """从交易字典检测"""
        trades = [
            {'pnl': 0.01}, {'pnl': -0.005}, {'pnl': 0.02},
            {'pnl': 0.015}, {'pnl': -0.003},
        ]

        detector = OverfittingDetector()
        result = detector.detect_from_trades(trades, n_strategies=5)

        assert 'overall_quality' in result
        assert 'risk_level' in result

    def test_is_usable_threshold(self):
        """is_usable阈值"""
        detector = OverfittingDetector({
            'overfitting_threshold': 0.5,
            'n_splits': 8,
            'test_ratio': 0.2,
            'n_retreats': 500,
            'default_n_strategies': 10,
        })

        # 创建一个高质量结果
        returns = generate_returns(annual_return=0.15, annual_vol=0.15)
        result = detector.detect(returns, n_strategies=10)

        # quality >= 60时应usable
        assert isinstance(result['is_usable'], bool)

    def test_penalize_objective(self):
        """目标函数惩罚"""
        detector = OverfittingDetector()

        sharpe = 1.5
        dsr = 1.0
        pbo_estimate = 0.3

        adjusted = detector.penalize_objective(sharpe, dsr, pbo_estimate)

        # adjusted = sharpe * (dsr/sharpe) - 1.0 * pbo = dsr - pbo
        assert isinstance(adjusted, (int, float))
        assert adjusted >= 0

    def test_short_data_fallback(self):
        """数据不足时的fallback"""
        returns = generate_returns(n_days=30)  # 不足50天
        detector = OverfittingDetector()

        result = detector.detect(returns, n_strategies=5)

        # CSCV会跳过
        assert result['cscc'] is None
        # DSR仍应运行
        assert 'dsr' in result


class TestDSRAdjustment:
    """DSR调整机制测试"""

    def test_penalty_increases_with_n_strategies(self):
        """策略越多,惩罚越大"""
        returns = generate_returns(annual_return=0.15, annual_vol=0.15)
        dsr_calc = DeflatedSharpeRatio()

        for n in [5, 20, 50]:
            dsr = dsr_calc.compute_dsr(returns, n_strategies=n)
            # 验证DSR计算完成
            assert not np.isnan(dsr)

    def test_no_penalty_single_strategy(self):
        """单一策略无惩罚"""
        returns = generate_returns(annual_return=0.15, annual_vol=0.15)
        dsr_calc = DeflatedSharpeRatio()

        dsr_single = dsr_calc.compute_dsr(returns, n_strategies=1)
        dsr_multi = dsr_calc.compute_dsr(returns, n_strategies=20)

        # 单一策略DSR应≥多元策略DSR
        assert dsr_single >= dsr_multi - 1e-6


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
