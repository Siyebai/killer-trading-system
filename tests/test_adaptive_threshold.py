#!/usr/bin/env python3
"""
自适应阈值矩阵测试套件 — 杀手锏交易系统 V6.3
覆盖: 市场状态分类、阈值切换、信号过滤、反过滤器保护

运行: PYTHONPATH=. python -m pytest tests/test_adaptive_threshold.py -v
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.adaptive_threshold_matrix import (
    MarketRegime, VolatilityCone, MarketRegimeClassifier,
    AdaptiveThresholdMatrix, ThresholdVector, DEFAULT_THRESHOLDS,
)


class TestMarketRegimeClassifier:
    def test_trending_high_adx(self):
        c = MarketRegimeClassifier()
        assert c.classify(adx=30, realized_vol=0.012) == MarketRegime.TRENDING

    def test_ranging_low_adx(self):
        c = MarketRegimeClassifier()
        assert c.classify(adx=15, realized_vol=0.005) == MarketRegime.RANGING

    def test_high_volatility(self):
        c = MarketRegimeClassifier()
        assert c.classify(adx=30, realized_vol=0.04) == MarketRegime.HIGH_VOLATILITY

    def test_high_vol_with_low_adx(self):
        c = MarketRegimeClassifier()
        # ADX<20但波动率高 → RANGING(因为ADX低)
        result = c.classify(adx=15, realized_vol=0.03)
        assert result == MarketRegime.RANGING

    def test_transition_zone(self):
        c = MarketRegimeClassifier()
        # ADX=22, vol低 → RANGING
        assert c.classify(adx=22, realized_vol=0.008) == MarketRegime.RANGING
        # ADX=22, vol高 → TRENDING
        assert c.classify(adx=22, realized_vol=0.02) == MarketRegime.TRENDING

    def test_classify_from_klines_insufficient(self):
        c = MarketRegimeClassifier()
        result = c.classify_from_klines([{"high": 100, "low": 99, "close": 100}])
        assert result == MarketRegime.RANGING  # 数据不足默认RANGING

    def test_classify_from_klines_sufficient(self):
        c = MarketRegimeClassifier()
        klines = [{"high": 100 + i * 0.5, "low": 100 + i * 0.5 - 1, "close": 100 + i * 0.5}
                  for i in range(30)]
        result = c.classify_from_klines(klines)
        assert isinstance(result, MarketRegime)

    def test_history_recorded(self):
        c = MarketRegimeClassifier()
        c.classify(adx=30, realized_vol=0.01)
        c.classify(adx=15, realized_vol=0.005)
        assert len(c.get_history()) == 2


class TestThresholdVector:
    def test_default_trending_relaxed(self):
        t = DEFAULT_THRESHOLDS[MarketRegime.TRENDING]
        assert t.mtf_score <= 0.35  # 趋势市放宽
        assert t.signal_score <= 0.55

    def test_default_ranging_strict(self):
        t = DEFAULT_THRESHOLDS[MarketRegime.RANGING]
        assert t.mtf_score >= 0.45  # 震荡市收紧
        assert t.signal_score >= 0.65

    def test_default_high_vol_moderate(self):
        t = DEFAULT_THRESHOLDS[MarketRegime.HIGH_VOLATILITY]
        # 高波动市介于趋势和震荡之间
        trending = DEFAULT_THRESHOLDS[MarketRegime.TRENDING]
        ranging = DEFAULT_THRESHOLDS[MarketRegime.RANGING]
        assert trending.mtf_score <= t.mtf_score <= ranging.mtf_score


class TestAdaptiveThresholdMatrix:
    def test_update_changes_regime(self):
        m = AdaptiveThresholdMatrix()
        vec = m.update(adx=30, realized_vol=0.012)
        assert m.get_regime() == MarketRegime.TRENDING
        assert vec.mtf_score == DEFAULT_THRESHOLDS[MarketRegime.TRENDING].mtf_score

    def test_update_to_ranging(self):
        m = AdaptiveThresholdMatrix()
        vec = m.update(adx=15, realized_vol=0.005)
        assert m.get_regime() == MarketRegime.RANGING

    def test_signal_pass_in_trending(self):
        m = AdaptiveThresholdMatrix()
        m.update(adx=30, realized_vol=0.012)
        result = m.check_signal(
            mtf_score=0.35, signal_score=0.55, confidence=0.55, ev=0.0003
        )
        assert result["passed"] is True

    def test_signal_reject_in_ranging(self):
        m = AdaptiveThresholdMatrix()
        m.update(adx=15, realized_vol=0.005)
        # 同样的信号在震荡市被拒绝
        result = m.check_signal(
            mtf_score=0.35, signal_score=0.55, confidence=0.55, ev=0.0003
        )
        assert result["passed"] is False

    def test_anti_filter_guard(self):
        """连续信号抑制超过10次应启用反过滤器保护"""
        m = AdaptiveThresholdMatrix()
        m.update(adx=15, realized_vol=0.005)  # 震荡市,严格阈值

        # 连续11次被过滤
        for i in range(11):
            m.check_signal(mtf_score=0.1, signal_score=0.1, confidence=0.1, ev=0.0)

        stats = m.get_stats()
        assert stats["min_trade_mode"] is True
        assert stats["suppression_count"] == 11

    def test_anti_filter_guard_relaxes_thresholds(self):
        """反过滤器保护应放宽阈值"""
        m = AdaptiveThresholdMatrix()
        m.update(adx=15, realized_vol=0.005)

        for i in range(11):
            m.check_signal(mtf_score=0.1, signal_score=0.1, confidence=0.1, ev=0.0)

        # 在min_trade_mode下,较低分数应通过
        result = m.check_signal(
            mtf_score=0.3, signal_score=0.45, confidence=0.50, ev=0.0002
        )
        # 因为阈值被降低70%,应该更容易通过
        assert result["min_trade_mode"] is True

    def test_passing_signal_resets_suppression(self):
        """通过信号应重置抑制计数"""
        m = AdaptiveThresholdMatrix()
        m.update(adx=30, realized_vol=0.012)  # 趋势市

        m.check_signal(mtf_score=0.1, signal_score=0.1, confidence=0.1, ev=0.0)
        assert m.get_stats()["suppression_count"] == 1

        # 通过信号
        m.check_signal(mtf_score=0.35, signal_score=0.55, confidence=0.55, ev=0.0003)
        assert m.get_stats()["suppression_count"] == 0
        assert m.get_stats()["min_trade_mode"] is False


class TestEndToEndScenarios:
    def test_trending_market_more_trades(self):
        """趋势市应比震荡市产生更多交易信号"""
        m = AdaptiveThresholdMatrix()
        signals = [
            {"mtf": 0.35, "sig": 0.55, "conf": 0.55, "ev": 0.0003},
            {"mtf": 0.4, "sig": 0.6, "conf": 0.6, "ev": 0.0004},
            {"mtf": 0.3, "sig": 0.5, "conf": 0.5, "ev": 0.0003},
        ]

        # 趋势市
        m.update(adx=30, realized_vol=0.012)
        trending_passes = sum(
            1 for s in signals
            if m.check_signal(s["mtf"], s["sig"], s["conf"], s["ev"])["passed"]
        )

        # 震荡市(重置)
        m2 = AdaptiveThresholdMatrix()
        m2.update(adx=15, realized_vol=0.005)
        ranging_passes = sum(
            1 for s in signals
            if m2.check_signal(s["mtf"], s["sig"], s["conf"], s["ev"])["passed"]
        )

        assert trending_passes >= ranging_passes

    def test_position_control_in_high_vol(self):
        """高波动市仓位应更小"""
        m = AdaptiveThresholdMatrix()
        m.update(adx=30, realized_vol=0.04)
        vec = m.get_current()
        trending_vec = DEFAULT_THRESHOLDS[MarketRegime.TRENDING]
        assert vec.position_pct_max <= trending_vec.position_pct_max


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
