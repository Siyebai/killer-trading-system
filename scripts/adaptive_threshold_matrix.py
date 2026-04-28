#!/usr/bin/env python3
"""
市场状态自适应阈值矩阵 — 杀手锏交易系统 V6.3
解决信号致盲问题: 静态阈值导致135个信号全部被过滤为HOLD(胜率16.7%)

核心设计:
1. MarketRegimeClassifier — 基于波动率锥+ADX的市场状态分类器
2. AdaptiveThresholdMatrix — 三区独立阈值向量(趋势/震荡/高波动)
3. AntiFilterGuard — 反过滤器保护: 连续N根K线无开仓信号时强制最小交易
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("adaptive_threshold")
except ImportError:
    import logging
    logger = logging.getLogger("adaptive_threshold")


# ============================================================
# 1. 市场状态枚举
# ============================================================

class MarketRegime(Enum):
    TRENDING = "TRENDING"           # 趋势市: ADX>25, 波动率正常
    RANGING = "RANGING"             # 震荡市: ADX<20, 波动率低
    HIGH_VOLATILITY = "HIGH_VOL"    # 高波动市: 波动率>2sigma


# ============================================================
# 2. 市场状态分类器
# ============================================================

@dataclass
class VolatilityCone:
    """波动率锥(基于历史分位数)"""
    lookback: int = 30
    percentiles: Dict[str, float] = field(default_factory=lambda: {
        "p10": 0.005, "p25": 0.008, "p50": 0.012, "p75": 0.018, "p90": 0.025
    })


class MarketRegimeClassifier:
    """
    基于波动率锥 + ADX 的市场状态分类器

    分类逻辑:
    - 波动率 > p90 且 ADX > 25 → HIGH_VOLATILITY (大趋势+剧烈波动)
    - ADX > 25 → TRENDING (明确趋势)
    - ADX < 20 → RANGING (震荡)
    - 20 <= ADX <= 25 → 取波动率判断: > p75 → HIGH_VOLATILITY, 否则 TRENDING
    """

    def __init__(self, cone: Optional[VolatilityCone] = None):
        self.cone = cone or VolatilityCone()
        self._history: List[Dict] = []

    def classify(self, adx: float, realized_vol: float,
                 volatility_p90: Optional[float] = None) -> MarketRegime:
        """
        分类当前市场状态。

        Args:
            adx: ADX指标值(0-100)
            realized_vol: 已实现波动率(如ATR/close)
            volatility_p90: 波动率锥P90分位数(可选,默认用cone内置值)

        Returns:
            MarketRegime
        """
        p90 = volatility_p90 or self.cone.percentiles["p90"]
        p75 = self.cone.percentiles["p75"]

        if realized_vol > p90 and adx > 25:
            regime = MarketRegime.HIGH_VOLATILITY
        elif adx > 25:
            regime = MarketRegime.HIGH_VOLATILITY if realized_vol > p75 else MarketRegime.TRENDING
        elif adx < 20:
            regime = MarketRegime.RANGING
        else:
            # ADX在20-25之间的过渡区
            regime = MarketRegime.TRENDING if realized_vol > p75 else MarketRegime.RANGING

        self._history.append({
            "adx": adx, "vol": realized_vol, "regime": regime.value
        })

        logger.info("Market regime classified", extra={"extra_data": {
            "adx": adx, "vol": realized_vol, "regime": regime.value
        }})
        return regime

    def classify_from_klines(self, klines: List[Dict]) -> MarketRegime:
        """
        从K线数据直接分类(计算ADX和波动率)。

        Args:
            klines: K线列表,每条含 high/low/close 字段

        Returns:
            MarketRegime
        """
        if len(klines) < 14:
            return MarketRegime.RANGING  # 数据不足,默认震荡

        closes = [float(k["close"]) for k in klines]
        highs = [float(k["high"]) for k in klines]
        lows = [float(k["low"]) for k in klines]

        # 计算已实现波动率
        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                returns.append(math.log(closes[i] / closes[i - 1]))
        realized_vol = math.sqrt(sum(r ** 2 for r in returns) / len(returns)) if returns else 0.01

        # 简化ADX计算
        adx = self._calc_adx(highs, lows, closes, period=14)

        return self.classify(adx, realized_vol)

    @staticmethod
    def _calc_adx(highs: List[float], lows: List[float], closes: List[float],
                  period: int = 14) -> float:
        """简化ADX计算"""
        if len(highs) < period + 1:
            return 20.0  # 默认值

        tr_list = []
        plus_dm = []
        minus_dm = []

        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            tr_list.append(tr)

            up = highs[i] - highs[i - 1]
            down = lows[i - 1] - lows[i]

            plus_dm.append(up if up > down and up > 0 else 0)
            minus_dm.append(down if down > up and down > 0 else 0)

        if not tr_list or sum(tr_list[:period]) == 0:
            return 20.0

        atr = sum(tr_list[:period]) / period
        if atr == 0:
            return 20.0

        smooth_plus = sum(plus_dm[:period]) / period
        smooth_minus = sum(minus_dm[:period]) / period

        dx = abs(smooth_plus - smooth_minus) / (smooth_plus + smooth_minus) * 100 if (smooth_plus + smooth_minus) > 0 else 0
        return min(max(dx, 0), 100)

    def get_history(self) -> List[Dict]:
        return self._history[-50:]


# ============================================================
# 3. 自适应阈值矩阵
# ============================================================

@dataclass
class ThresholdVector:
    """单区阈值向量"""
    mtf_score: float = 0.4        # 多时间帧对齐分数阈值
    signal_score: float = 0.6      # 信号质量分数阈值
    confidence_min: float = 0.55   # 最低置信度
    ev_min: float = 0.00035        # 最低预期价值
    position_pct_max: float = 0.10 # 最大仓位比例


# 默认三区阈值向量
DEFAULT_THRESHOLDS: Dict[MarketRegime, ThresholdVector] = {
    MarketRegime.TRENDING: ThresholdVector(
        mtf_score=0.3, signal_score=0.5, confidence_min=0.50,
        ev_min=0.00025, position_pct_max=0.12
    ),
    MarketRegime.RANGING: ThresholdVector(
        mtf_score=0.45, signal_score=0.65, confidence_min=0.60,
        ev_min=0.00025, position_pct_max=0.08
    ),
    MarketRegime.HIGH_VOLATILITY: ThresholdVector(
        mtf_score=0.4, signal_score=0.6, confidence_min=0.55,
        ev_min=0.00035, position_pct_max=0.08
    ),
}


class AdaptiveThresholdMatrix:
    """
    自适应阈值矩阵

    根据市场状态自动切换阈值向量:
    - 趋势市: 放宽阈值,增加交易机会
    - 震荡市: 收紧阈值,过滤假信号
    - 高波动市: 中等阈值,控制仓位

    解决问题: 静态阈值在震荡市过于宽松,在趋势市过于严格
    """

    def __init__(self, custom_thresholds: Optional[Dict[MarketRegime, ThresholdVector]] = None):
        self.thresholds = custom_thresholds or DEFAULT_THRESHOLDS
        self.classifier = MarketRegimeClassifier()
        self._current_regime = MarketRegime.RANGING
        self._current_vector = self.thresholds[MarketRegime.RANGING]
        self._filter_suppression_count = 0  # 连续信号抑制计数
        self._min_trade_mode = False         # 最小交易单元模式

    def update(self, adx: float, realized_vol: float,
               volatility_p90: Optional[float] = None) -> ThresholdVector:
        """
        根据市场指标更新阈值。

        Args:
            adx: ADX值
            realized_vol: 已实现波动率
            volatility_p90: P90分位数

        Returns:
            当前生效的阈值向量
        """
        self._current_regime = self.classifier.classify(adx, realized_vol, volatility_p90)
        self._current_vector = self.thresholds[self._current_regime]
        return self._current_vector

    def update_from_klines(self, klines: List[Dict]) -> ThresholdVector:
        """从K线数据更新阈值"""
        self._current_regime = self.classifier.classify_from_klines(klines)
        self._current_vector = self.thresholds[self._current_regime]
        return self._current_vector

    def get_current(self) -> ThresholdVector:
        """获取当前阈值向量"""
        return self._current_vector

    def get_regime(self) -> MarketRegime:
        """获取当前市场状态"""
        return self._current_regime

    def check_signal(self, mtf_score: float, signal_score: float,
                     confidence: float, ev: float) -> Dict:
        """
        检查信号是否通过当前阈值过滤。

        Args:
            mtf_score: 多时间帧对齐分数
            signal_score: 信号质量分数
            confidence: 策略置信度
            ev: 预期价值

        Returns:
            过滤结果字典 {passed, reason, thresholds_used, effective_thresholds}
        """
        vec = self._current_vector

        # 反过滤器保护: 若已连续抑制,启用最小交易模式
        if self._min_trade_mode:
            vec = ThresholdVector(
                mtf_score=vec.mtf_score * 0.7,
                signal_score=vec.signal_score * 0.7,
                confidence_min=vec.confidence_min * 0.85,
                ev_min=vec.ev_min * 0.5,
                position_pct_max=vec.position_pct_max * 0.5
            )

        checks = {
            "mtf": mtf_score >= vec.mtf_score,
            "signal": signal_score >= vec.signal_score,
            "confidence": confidence >= vec.confidence_min,
            "ev": ev >= vec.ev_min,
        }

        passed = all(checks.values())

        if not passed:
            self._filter_suppression_count += 1
            reason = f"Failed: {', '.join(k for k, v in checks.items() if not v)}"
        else:
            self._filter_suppression_count = 0
            self._min_trade_mode = False
            reason = "All checks passed"

        # 连续抑制超过阈值 → 启用反过滤器保护
        if self._filter_suppression_count >= 10:
            self._min_trade_mode = True
            logger.warning("Anti-filter guard activated", extra={"extra_data": {
                "suppression_count": self._filter_suppression_count,
                "regime": self._current_regime.value
            }})

        result = {
            "passed": passed,
            "reason": reason,
            "regime": self._current_regime.value,
            "min_trade_mode": self._min_trade_mode,
            "suppression_count": self._filter_suppression_count,
            "checks": checks,
            "thresholds": {
                "mtf": vec.mtf_score,
                "signal": vec.signal_score,
                "confidence": vec.confidence_min,
                "ev": vec.ev_min,
            }
        }

        logger.info("Signal check", extra={"extra_data": result})
        return result

    def get_stats(self) -> Dict:
        """获取阈值矩阵统计"""
        return {
            "current_regime": self._current_regime.value,
            "suppression_count": self._filter_suppression_count,
            "min_trade_mode": self._min_trade_mode,
            "thresholds": {
                r.value: {
                    "mtf": t.mtf_score, "signal": t.signal_score,
                    "confidence": t.confidence_min, "ev": t.ev_min,
                    "position_max": t.position_pct_max
                }
                for r, t in self.thresholds.items()
            }
        }


# ============================================================
# 命令行接口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="市场状态自适应阈值矩阵")
    parser.add_argument("--adx", type=float, required=True, help="ADX指标值")
    parser.add_argument("--vol", type=float, required=True, help="已实现波动率")
    parser.add_argument("--vol-p90", type=float, default=None, help="波动率P90分位数")
    parser.add_argument("--mtf-score", type=float, default=None, help="多时间帧分数(用于信号检查)")
    parser.add_argument("--signal-score", type=float, default=None, help="信号质量分数")
    parser.add_argument("--confidence", type=float, default=None, help="策略置信度")
    parser.add_argument("--ev", type=float, default=None, help="预期价值")
    parser.add_argument("--stats", action="store_true", help="输出矩阵统计")
    args = parser.parse_args()

    matrix = AdaptiveThresholdMatrix()
    vec = matrix.update(args.adx, args.vol, args.vol_p90)

    result = {
        "regime": matrix.get_regime().value,
        "thresholds": {
            "mtf": vec.mtf_score,
            "signal": vec.signal_score,
            "confidence": vec.confidence_min,
            "ev": vec.ev_min,
            "position_max": vec.position_pct_max,
        }
    }

    # 信号检查(若提供完整参数)
    if all(v is not None for v in [args.mtf_score, args.signal_score, args.confidence, args.ev]):
        check = matrix.check_signal(args.mtf_score, args.signal_score, args.confidence, args.ev)
        result["signal_check"] = check

    if args.stats:
        result["matrix_stats"] = matrix.get_stats()

    logger.info(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
