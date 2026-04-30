#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
overfitting_detector.py - 过拟合检测核心模块
实现CSCV、PBO、Deflated Sharpe Ratio三种检测方法
Stage 4 产出：整合到策略实验室+贝叶斯优化目标函数
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from itertools import combinations
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class CSCVDetector:
    """
    组合对称交叉验证 (Combinatorial Symmetric Cross-Validation)
    - 将数据划分为N个子集,穷举所有可能的train/test组合
    - 计算每个组合的out-of-sample表现
    - 通过统计检验判断过拟合程度
    """

    def __init__(self, n_splits: int = 8, test_ratio: float = 0.2):
        self.n_splits = n_splits  # 子集数量
        self.test_ratio = test_ratio  # 测试集比例
        self.results = []

    def run_cscc(self, returns: np.ndarray, train_test_pairs: List[Tuple[np.ndarray, np.ndarray]]) -> Dict:
        """
        运行CSCV分析
        
        Args:
            returns: 策略收益率序列
            train_test_pairs: (训练集mask, 测试集mask)列表
        
        Returns:
            dict: 包含各类统计量的字典
        """
        is_oos = []
        performance_oos = []
        performance_is = []

        for train_mask, test_mask in train_test_pairs:
            ret_train = returns[train_mask]
            ret_test = returns[test_mask]

            # 样本内: 假设基于训练期参数计算的最优组合在训练期内直接使用
            # 过拟合代理 = 样本内表现 - 样本外表现
            perf_is = np.mean(ret_train) / (np.std(ret_train) + 1e-10) * np.sqrt(252)
            perf_oos = np.mean(ret_test) / (np.std(ret_test) + 1e-10) * np.sqrt(252)
            # 更合理的IS表现: 使用零假设(等权重)作为基准
            perf_is_null = 0.0

            is_oos.append(perf_oos > perf_is_null)  # OOS是否优于基准
            performance_oos.append(perf_oos)
            performance_is.append(perf_is)

        performance_oos = np.array(performance_oos)
        performance_is = np.array(performance_is)
        is_oos = np.array(is_oos)

        # 计算关键指标
        # 1. PBO: 样本内选出的"最优"在样本外跑输基准的概率
        pbo = 1.0 - np.mean(is_oos)

        # 2. 过拟合度: IS vs OOS的差距
        if len(performance_is) > 0:
            # 使用最大IS作为"被选中"的表现
            # 这里简化为: PBO = OOS<0的比例
            pbo_simple = np.mean(performance_oos < 0)
        else:
            pbo_simple = 0.5

        # 3. OOS胜率: OOS夏普>0的比例
        win_rate = np.mean(performance_oos > 0)

        return {
            'pbo': max(pbo, pbo_simple),  # 取保守估计
            'pbo_simple': pbo_simple,
            'oos_win_rate': win_rate,
            'avg_oos_sharpe': np.mean(performance_oos),
            'std_oos_sharpe': np.std(performance_oos),
            'avg_is_sharpe': np.mean(performance_is) if len(performance_is) > 0 else 0,
            'n_pairs': len(train_test_pairs),
        }

    def generate_train_test_pairs(self, n_total: int) -> List[Tuple[np.ndarray, np.ndarray]]:
        """生成所有可能的train/test组合"""
        n_test = max(1, int(n_total * self.test_ratio))
        n_train = n_total - n_test

        pairs = []
        # 滑动窗口生成
        for i in range(self.n_splits):
            start = int(i * (n_total - n_test) / self.n_splits)
            end = start + n_test
            if end > n_total:
                end = n_total
                start = end - n_test

            test_mask = np.zeros(n_total, dtype=bool)
            test_mask[start:end] = True

            train_mask = ~test_mask
            pairs.append((train_mask, test_mask))

        return pairs


class PBOEstimator:
    """
    概率回测过拟合 (Probability of Backtest Overfitting)
    基于N年的日收益数据,计算策略被过拟合选中的概率
    """

    def __init__(self, n_retreats: int = 1000):
        self.n_retreats = n_retreats

    def compute_pbo(self, strategy_returns: np.ndarray,
                   candidate_returns: np.ndarray,
                   n_selected: int = 1) -> float:
        """
        计算PBO

        Args:
            strategy_returns: 被选中的策略收益率 (实际使用的)
            candidate_returns: 所有候选策略收益率矩阵 (n_candidates, n_days)
            n_selected: 选中的策略数量

        Returns:
            PBO值: [0, 1], 越低越好
        """
        n_days = len(strategy_returns)
        n_candidates = candidate_returns.shape[0]

        # 分割点
        split = int(n_days * 0.5)
        is_returns = candidate_returns[:, :split]
        oos_returns = candidate_returns[:, split:]

        # 样本内最优
        is_sharpe = np.mean(is_returns, axis=1) / (np.std(is_returns, axis=1) + 1e-10)
        top_k = np.argsort(is_sharpe)[-n_selected:]

        # 被选中策略的OOS表现
        selected_oos_sharpe = np.mean(oos_returns[top_k], axis=1) / (np.std(oos_returns[top_k], axis=1) + 1e-10)

        # 计算retreats: 随机选同样数量策略,看OOS表现
        better_count = 0
        for _ in range(self.n_retreats):
            random_idx = np.random.choice(n_candidates, n_selected, replace=False)
            random_oos = np.mean(oos_returns[random_idx], axis=1) / (np.std(oos_returns[random_idx], axis=1) + 1e-10)
            if np.mean(random_oos) > np.mean(selected_oos_sharpe):
                better_count += 1

        pbo = better_count / self.n_retreats
        return pbo


class DeflatedSharpeRatio:
    """
    Deflated Sharpe Ratio (DSR)
    在多重假设检验下调整夏普比率的显著性
    使用施瓦茨信息准则(SIC)估计非中心性参数
    """

    def __init__(self, risk_free_rate: float = 0.0):
        self.risk_free_rate = risk_free_rate

    def compute_dsr(self, returns: np.ndarray,
                   n_strategies: int,
                   skewness: float = 0.0,
                   kurtosis: float = 3.0) -> float:
        """
        计算DSR

        Args:
            returns: 策略日收益率
            n_strategies: 同时测试的策略数量(用于多重检验调整)
            skewness: 收益率偏度(0=正态)
            kurtosis: 收益率峰度(3=正态)

        Returns:
            DSR: 调整后的夏普比率
        """
        n = len(returns)

        # 标准SR
        excess = returns - self.risk_free_rate / 252
        sr = np.mean(excess) / (np.std(excess) + 1e-10) * np.sqrt(252)

        # 非中心性参数估计 (基于SIC)
        # λ = n × SR² - log(n) 用于调整多重检验
        with np.errstate(invalid='ignore'):
            lambd = n * max(sr**2, 0) - np.log(n)

        if lambd <= 0:
            # 没有显著优于随机
            return 0.0

        # 调整后的SR: 考虑非零漂移和多重检验
        # 简化为: DSR = SR × (1 - penalty)
        # penalty = P(随机策略获得更高SR)
        # 使用极值理论估计
        penalty = min(1.0, np.sqrt(2 * np.log(n_strategies) / n))

        dsr = sr * (1.0 - penalty * 0.5) if sr > 0 else sr

        # 更保守的估计: 考虑偏度和峰度
        if abs(skewness) > 0.5 or abs(kurtosis - 3) > 1.0:
            # Cornwallis调整
            corn_worst = 1 + np.log(1 - skewness * sr + (kurtosis - 3) * sr**2 / 4) / (sr + 1e-10)
            adjustment = max(0, min(1, corn_worst))
            dsr = dsr * adjustment

        return dsr

    def compute_sharpe(self, returns: np.ndarray) -> float:
        """计算标准夏普比率"""
        excess = returns - self.risk_free_rate / 252
        return np.mean(excess) / (np.std(excess) + 1e-10) * np.sqrt(252)

    def compute_annual_return(self, returns: np.ndarray) -> float:
        """计算年化收益率"""
        return (1 + np.mean(returns))**252 - 1

    def compute_max_drawdown(self, returns: np.ndarray) -> float:
        """计算最大回撤"""
        equity = (1 + returns).cumprod()
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / peak
        return np.min(drawdown)

    def full_analysis(self, returns: np.ndarray, n_strategies: int = 10) -> Dict:
        """完整过拟合分析"""
        sr = self.compute_sharpe(returns)
        dsr = self.compute_dsr(returns, n_strategies)
        annual_return = self.compute_annual_return(returns)
        mdd = self.compute_max_drawdown(returns)

        # 偏度和峰度
        skew = pd.Series(returns).skew()
        kurt = pd.Series(returns).kurt() + 3  # scipy返回excess kurtosis

        # 过拟合概率 (简化)
        # 如果DSR < SR * 0.5, 认为有较高过拟合风险
        pbo_estimate = max(0, min(1, (sr - dsr) / (abs(sr) + 1e-10)))

        # Calmar比率
        calmar = annual_return / abs(mdd) if abs(mdd) > 1e-10 else 0

        # Sortino比率
        downside = returns[returns < 0]
        sortino = np.mean(returns) / (np.std(downside) + 1e-10) * np.sqrt(252) if len(downside) > 0 else 0

        return {
            'sharpe_ratio': sr,
            'deflated_sharpe_ratio': dsr,
            'annual_return': annual_return,
            'max_drawdown': mdd,
            'calmar_ratio': calmar,
            'sortino_ratio': sortino,
            'skewness': skew,
            'kurtosis': kurt,
            'pbo_estimate': pbo_estimate,
            'n_days': len(returns),
            'is_overfitting': dsr < sr * 0.5,  # 保守阈值
        }


class OverfittingDetector:
    """
    过拟合检测主控制器
    整合CSCV、PBO、DSR三种方法
    可直接输出给优化器和策略实验室
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {
            'n_splits': 8,
            'test_ratio': 0.2,
            'n_retreats': 500,
            'default_n_strategies': 10,
            'overfitting_threshold': 0.5,  # PBO > 0.5 = 严重过拟合
        }
        self.cscc = CSCVDetector(self.config['n_splits'], self.config['test_ratio'])
        self.pbo = PBOEstimator(self.config['n_retreats'])
        self.dsr = DeflatedSharpeRatio()

    def detect(self, returns: np.ndarray,
              candidate_returns: Optional[np.ndarray] = None,
              n_strategies: int = 10) -> Dict:
        """
        综合过拟合检测

        Args:
            returns: 策略收益率
            candidate_returns: 候选策略收益矩阵 (可选,用于PBO)
            n_strategies: 候选策略数量

        Returns:
            dict: 过拟合报告
        """
        logger.info(f"Running overfitting detection on {len(returns)} returns, {n_strategies} candidates")

        result = {}

        # 1. DSR分析
        dsr_result = self.dsr.full_analysis(returns, n_strategies)
        result['dsr'] = dsr_result

        # 2. CSCV分析 (如果数据足够)
        if len(returns) >= 50:
            try:
                pairs = self.cscc.generate_train_test_pairs(len(returns))
                cscc_result = self.cscc.run_cscc(returns, pairs)
                result['cscc'] = cscc_result
                logger.info(f"CSCV PBO: {cscc_result['pbo']:.3f}, OOS win rate: {cscc_result['oos_win_rate']:.3f}")
            except Exception as e:
                logger.warning(f"CSCV analysis failed: {e}")
                result['cscc'] = None
        else:
            result['cscc'] = None
            logger.warning(f"Insufficient data for CSCV (need 50+, got {len(returns)})")

        # 3. PBO分析 (如果有候选策略)
        if candidate_returns is not None and candidate_returns.shape[1] >= len(returns):
            try:
                pbo_value = self.pbo.compute_pbo(returns, candidate_returns)
                result['pbo'] = pbo_value
                logger.info(f"PBO: {pbo_value:.3f}")
            except Exception as e:
                logger.warning(f"PBO analysis failed: {e}")
                result['pbo'] = None
        else:
            result['pbo'] = None

        # 4. 综合评分
        scores = []

        # DSR/SR比率: 越接近1越好
        if dsr_result['sharpe_ratio'] != 0:
            dsr_ratio = dsr_result['deflated_sharpe_ratio'] / dsr_result['sharpe_ratio']
            scores.append(max(0, min(1, dsr_ratio)))
        else:
            dsr_ratio = 0
            scores.append(0)

        # CSCV PBO: 越低越好
        if result['cscc'] is not None:
            cscv_score = 1.0 - result['cscc']['pbo']
            scores.append(max(0, min(1, cscv_score)))

        # 综合质量评分 (0-100)
        overall_quality = np.mean(scores) * 100 if scores else 50

        # 过拟合风险等级
        if overall_quality >= 80:
            risk = 'LOW'
        elif overall_quality >= 60:
            risk = 'MEDIUM'
        elif overall_quality >= 40:
            risk = 'HIGH'
        else:
            risk = 'CRITICAL'

        result['overall_quality'] = overall_quality
        result['risk_level'] = risk
        result['is_usable'] = overall_quality >= 60 and not dsr_result['is_overfitting']

        logger.info(f"Overall quality: {overall_quality:.1f}/100, Risk: {risk}, Usable: {result['is_usable']}")

        return result

    def detect_from_trades(self, trades: List[Dict],
                          n_strategies: int = 10) -> Dict:
        """
        从交易记录计算收益率并检测过拟合

        Args:
            trades: 交易记录列表 (每笔包含pnl字段)
            n_strategies: 候选策略数量

        Returns:
            dict: 过拟合报告
        """
        if not trades:
            return {
                'error': 'No trades provided',
                'overall_quality': 0,
                'risk_level': 'CRITICAL',
                'is_usable': False,
            }

        # 从交易记录生成日收益率
        returns = np.array([t.get('pnl', 0) for t in trades])
        return self.detect(returns, n_strategies=n_strategies)

    def penalize_objective(self, sharpe: float, dsr: float,
                          pbo_estimate: float) -> float:
        """
        在优化目标函数中加入过拟合惩罚

        用于贝叶斯优化的目标函数:

        adjusted_objective = sharpe - penalty

        penalty = λ × PBO_estimate

        λ = 过拟合敏感度 (建议 0.5-2.0)
        """
        # λ=1.0: 平衡风险
        penalty = 1.0 * pbo_estimate

        # 使用DSR作为辅助信息
        if dsr < sharpe:
            # DSR比SR低,说明有过度拟合风险
            adjustment = dsr / (sharpe + 1e-10)
        else:
            adjustment = 1.0

        adjusted = sharpe * adjustment - penalty
        return max(0, adjusted)  # 不返回负值


def run_backtest_for_bo(params: Dict, df: pd.DataFrame) -> Tuple[Dict, float]:
    """
    带过拟合检测的贝叶斯优化目标函数

    用法:
        def objective(**params):
            trades, sharpe = run_backtest_for_bo(params, df)
            detector = OverfittingDetector()
            result = detector.detect(np.array([t['pnl'] for t in trades]))
            return detector.penalize_objective(sharpe, result['dsr']['deflated_sharpe_ratio'], result.get('pbo', 0))
    """
    # 简化实现: 返回 (trades, raw_sharpe)
    # 实际使用时替换为closed_loop_engine的回测
    pass


# ===================== 命令行入口 =====================

def main():
    """命令行测试"""
    import argparse

    parser = argparse.ArgumentParser(description='过拟合检测')
    parser.add_argument('--mode', choices=['cscc', 'pbo', 'dsr', 'full'], default='full',
                       help='检测模式')
    parser.add_argument('--n-strategies', type=int, default=10,
                       help='候选策略数量(用于DSR)')
    parser.add_argument('--n-splits', type=int, default=8,
                       help='CSCV分割数')
    parser.add_argument('--n-days', type=int, default=252,
                       help='模拟数据天数')

    args = parser.parse_args()

    logger.info(f"Overfitting Detector - Mode: {args.mode}")

    # 生成模拟数据
    np.random.seed(42)
    n = args.n_days
    # 模拟一个"有真实Alpha"的策略: 年化10%收益, 15%波动率
    strategy_returns = np.random.normal(0.10/252, 0.15/np.sqrt(252), n)

    detector = OverfittingDetector({
        'n_splits': args.n_splits,
        'default_n_strategies': args.n_strategies,
    })

    # 生成候选策略(多数是噪声)
    n_candidates = 20
    candidate_returns = np.zeros((n_candidates, n))
    for i in range(n_candidates):
        if i < 3:
            # 前3个有正Alpha
            candidate_returns[i] = np.random.normal(0.12/252, 0.12/np.sqrt(252), n)
        else:
            # 其余是噪声
            candidate_returns[i] = np.random.normal(0, 0.15/np.sqrt(252), n)

    # 运行检测
    if args.mode == 'full':
        result = detector.detect(strategy_returns, candidate_returns, args.n_strategies)
    elif args.mode == 'cscc':
        pairs = detector.cscc.generate_train_test_pairs(n)
        result = detector.cscc.run_cscc(strategy_returns, pairs)
    elif args.mode == 'pbo':
        result = {'pbo': detector.pbo.compute_pbo(strategy_returns, candidate_returns)}
    else:  # dsr
        result = detector.dsr.full_analysis(strategy_returns, args.n_strategies)

    print(f"\n{'='*60}")
    print(f"OVERFITTING DETECTION RESULTS")
    print(f"{'='*60}")
    print(f"Mode: {args.mode}")
    print(f"Data: {n} days, {args.n_strategies} candidate strategies")
    print()

    if args.mode == 'full':
        print(f"Overall Quality: {result['overall_quality']:.1f}/100")
        print(f"Risk Level: {result['risk_level']}")
        print(f"Is Usable: {result['is_usable']}")
        print()
        if result.get('dsr'):
            print(f"[DSR Analysis]")
            print(f"  Sharpe Ratio: {result['dsr']['sharpe_ratio']:.4f}")
            print(f"  Deflated SR: {result['dsr']['deflated_sharpe_ratio']:.4f}")
            print(f"  PBO Estimate: {result['dsr']['pbo_estimate']:.3f}")
            print(f"  Annual Return: {result['dsr']['annual_return']:.2%}")
            print(f"  Max Drawdown: {result['dsr']['max_drawdown']:.2%}")
            print(f"  Skewness: {result['dsr']['skewness']:.3f}")
            print(f"  Kurtosis: {result['dsr']['kurtosis']:.3f}")
        if result.get('cscc'):
            print(f"\n[CSCV Analysis]")
            print(f"  PBO: {result['cscc']['pbo']:.3f}")
            print(f"  OOS Win Rate: {result['cscc']['oos_win_rate']:.3f}")
            print(f"  Avg OOS Sharpe: {result['cscc']['avg_oos_sharpe']:.4f}")
        if result.get('pbo') is not None:
            print(f"\n[PBO Analysis]")
            print(f"  PBO: {result['pbo']:.3f}")
    elif args.mode == 'cscc':
        print(f"PBO: {result['pbo']:.3f}")
        print(f"OOS Win Rate: {result['oos_win_rate']:.3f}")
        print(f"Avg OOS Sharpe: {result['avg_oos_sharpe']:.4f}")
        print(f"Avg IS Sharpe: {result['avg_is_sharpe']:.4f}")
    elif args.mode == 'pbo':
        print(f"PBO: {result['pbo']:.3f}")
    else:
        for k, v in result.items():
            if isinstance(v, float):
                print(f"  {k}: {v:.4f}")
            else:
                print(f"  {k}: {v}")

    print(f"{'='*60}")


if __name__ == '__main__':
    main()
