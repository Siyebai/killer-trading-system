#!/usr/bin/env python3
"""
EV过滤模块测试套件 — V6.3
覆盖: 正常计算/边界条件/错误处理/批量过滤/统计

运行: PYTHONPATH=. python -m pytest tests/test_ev_filter.py -v
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.ev_filter import EVFilter, EVFilterInput, EVFilterResult, TradeDirection


class TestEVFilterInput:
    def test_valid_input_no_errors(self):
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.LONG,
            confidence=0.7, entry_price=50000, tp_price=51000, sl_price=49500
        )
        assert inp.validate() == []

    def test_zero_entry_price(self):
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.LONG,
            confidence=0.7, entry_price=0, tp_price=51000, sl_price=49500
        )
        errors = inp.validate()
        assert any("entry_price" in e for e in errors)

    def test_negative_entry_price(self):
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.LONG,
            confidence=0.7, entry_price=-100, tp_price=51000, sl_price=49500
        )
        errors = inp.validate()
        assert any("entry_price" in e for e in errors)

    def test_confidence_out_of_range(self):
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.LONG,
            confidence=1.5, entry_price=50000, tp_price=51000, sl_price=49500
        )
        errors = inp.validate()
        assert any("confidence" in e for e in errors)

    def test_empty_symbol(self):
        inp = EVFilterInput(
            symbol="", direction=TradeDirection.LONG,
            confidence=0.7, entry_price=50000, tp_price=51000, sl_price=49500
        )
        errors = inp.validate()
        assert any("symbol" in e for e in errors)

    def test_zero_tp_price(self):
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.LONG,
            confidence=0.7, entry_price=50000, tp_price=0, sl_price=49500
        )
        errors = inp.validate()
        assert any("tp_price" in e for e in errors)


class TestEVFilterCalculation:
    def setup_method(self):
        self.f = EVFilter()

    def test_long_profitable_trade(self):
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.LONG,
            confidence=0.7, entry_price=50000, tp_price=51000, sl_price=49500
        )
        result = self.f.calculate_ev(inp)
        assert result.passed is True
        assert result.ev > 0
        assert result.error == ""

    def test_short_profitable_trade(self):
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.SHORT,
            confidence=0.7, entry_price=50000, tp_price=49000, sl_price=50500
        )
        result = self.f.calculate_ev(inp)
        assert result.passed is True
        assert result.ev > 0

    def test_low_confidence_rejected(self):
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.LONG,
            confidence=0.2, entry_price=50000, tp_price=50500, sl_price=49000
        )
        result = self.f.calculate_ev(inp)
        assert result.passed is False
        assert result.recommendation == "SKIP"

    def test_high_cost_rejected(self):
        """交易成本吞噬全部利润"""
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.LONG,
            confidence=0.6, entry_price=50000, tp_price=50050, sl_price=49950,
            taker_fee=0.01, slippage=0.01, spread=0.01
        )
        result = self.f.calculate_ev(inp)
        assert result.passed is False

    def test_zero_entry_price_safe_return(self):
        """入口价格为0时应安全返回(不崩溃)"""
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.LONG,
            confidence=0.7, entry_price=0, tp_price=51000, sl_price=49500
        )
        result = self.f.calculate_ev(inp)
        assert result.passed is False
        assert result.error != ""
        assert "entry_price" in result.error or "Invalid input" in result.reason

    def test_wrong_sl_direction_long(self):
        """LONG订单但sl_price > entry_price → 方向错误"""
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.LONG,
            confidence=0.7, entry_price=50000, tp_price=51000, sl_price=52000
        )
        result = self.f.calculate_ev(inp)
        assert result.passed is False
        assert "direction" in result.reason.lower() or result.error != ""

    def test_wrong_tp_direction_short(self):
        """SHORT订单但tp_price > entry_price → 方向错误"""
        inp = EVFilterInput(
            symbol="BTCUSDT", direction=TradeDirection.SHORT,
            confidence=0.7, entry_price=50000, tp_price=51000, sl_price=49000
        )
        result = self.f.calculate_ev(inp)
        assert result.passed is False


class TestEVFilterBatch:
    def test_batch_normal(self):
        f = EVFilter()
        inputs = [
            EVFilterInput(symbol="BTCUSDT", direction=TradeDirection.LONG,
                         confidence=0.7, entry_price=50000, tp_price=51000, sl_price=49500),
            EVFilterInput(symbol="ETHUSDT", direction=TradeDirection.LONG,
                         confidence=0.3, entry_price=3000, tp_price=3050, sl_price=2900),
        ]
        results = f.batch_filter(inputs)
        assert len(results) == 2
        assert results[0].passed is True
        assert results[1].passed is False

    def test_batch_error_doesnt_affect_others(self):
        """单条异常不影响批量处理"""
        f = EVFilter()
        inputs = [
            EVFilterInput(symbol="BTCUSDT", direction=TradeDirection.LONG,
                         confidence=0.7, entry_price=0, tp_price=51000, sl_price=49500),  # 错误
            EVFilterInput(symbol="ETHUSDT", direction=TradeDirection.LONG,
                         confidence=0.7, entry_price=3000, tp_price=3100, sl_price=2900),  # 正常
        ]
        results = f.batch_filter(inputs)
        assert len(results) == 2
        assert results[0].passed is False  # 错误输入被安全处理
        assert results[1].passed is True   # 正常输入不受影响


class TestEVFilterStats:
    def test_stats_tracked(self):
        f = EVFilter()
        inp1 = EVFilterInput(symbol="BTCUSDT", direction=TradeDirection.LONG,
                             confidence=0.7, entry_price=50000, tp_price=51000, sl_price=49500)
        inp2 = EVFilterInput(symbol="ETHUSDT", direction=TradeDirection.LONG,
                             confidence=0.3, entry_price=3000, tp_price=3050, sl_price=2900)
        f.calculate_ev(inp1)
        f.calculate_ev(inp2)
        stats = f.get_stats()
        assert stats['total_checks'] == 2
        assert stats['total_passed'] == 1
        assert stats['total_rejected'] == 1
        assert 0 < stats['pass_rate'] < 1

    def test_stats_reset(self):
        f = EVFilter()
        inp = EVFilterInput(symbol="BTCUSDT", direction=TradeDirection.LONG,
                            confidence=0.7, entry_price=50000, tp_price=51000, sl_price=49500)
        f.calculate_ev(inp)
        f.reset_stats()
        assert f.stats['total_checks'] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
