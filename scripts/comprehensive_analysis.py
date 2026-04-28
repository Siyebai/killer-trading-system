#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("comprehensive_analysis")
except ImportError:
    import logging
    logger = logging.getLogger("comprehensive_analysis")
"""
综合分析器（第2层：综合分析）
多维度分析 + 风险评估 + 预测模型集成
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import pandas as pd


class AnalysisType(Enum):
    """分析类型"""
    TECHNICAL = "TECHNICAL"  # 技术分析
    FUNDAMENTAL = "FUNDAMENTAL"  # 基本面分析
    SENTIMENT = "SENTIMENT"  # 情绪分析
    RISK = "RISK"  # 风险分析
    PREDICTION = "PREDICTION"  # 预测分析


@dataclass
class AnalysisResult:
    """分析结果"""
    analysis_type: AnalysisType
    score: float  # 分析得分（0-1）
    confidence: float  # 置信度
    direction: Optional[str]  # 方向
    risk_level: str  # 风险等级
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'analysis_type': self.analysis_type.value,
            'score': self.score,
            'confidence': self.confidence,
            'direction': self.direction,
            'risk_level': self.risk_level,
            'details': self.details
        }


@dataclass
class ComprehensiveAnalysis:
    """综合分析结果"""
    opportunity_id: str
    analysis_time: float
    overall_score: float  # 综合得分
    overall_direction: str  # 综合方向
    overall_risk: str  # 综合风险等级
    technical_analysis: Optional[AnalysisResult] = None
    fundamental_analysis: Optional[AnalysisResult] = None
    sentiment_analysis: Optional[AnalysisResult] = None
    risk_analysis: Optional[AnalysisResult] = None
    prediction_analysis: Optional[AnalysisResult] = None
    recommendation: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'opportunity_id': self.opportunity_id,
            'analysis_time': self.analysis_time,
            'overall_score': self.overall_score,
            'overall_direction': self.overall_direction,
            'overall_risk': self.overall_risk,
            'technical_analysis': self.technical_analysis.to_dict() if self.technical_analysis else None,
            'fundamental_analysis': self.fundamental_analysis.to_dict() if self.fundamental_analysis else None,
            'sentiment_analysis': self.sentiment_analysis.to_dict() if self.sentiment_analysis else None,
            'risk_analysis': self.risk_analysis.to_dict() if self.risk_analysis else None,
            'prediction_analysis': self.prediction_analysis.to_dict() if self.prediction_analysis else None,
            'recommendation': self.recommendation
        }


class TechnicalAnalyzer:
    """技术分析器"""

    def __init__(self):
        pass

    def analyze(self, market_data: Dict, historical_data: pd.DataFrame) -> AnalysisResult:
        """执行技术分析"""
        if len(historical_data) < 20:
            return AnalysisResult(
                analysis_type=AnalysisType.TECHNICAL,
                score=0.5,
                confidence=0.3,
                direction=None,
                risk_level="MEDIUM",
                details={'error': 'insufficient_data'}
            )

        # 多指标分析
        indicators = self.calculate_indicators(historical_data)

        # 综合评分
        score = self.calculate_score(indicators)

        # 判断方向
        direction = self.determine_direction(indicators)

        # 评估风险
        risk_level = self.assess_risk(indicators)

        return AnalysisResult(
            analysis_type=AnalysisType.TECHNICAL,
            score=score,
            confidence=0.8,
            direction=direction,
            risk_level=risk_level,
            details={'indicators': indicators}
        )

    def calculate_indicators(self, data: pd.DataFrame) -> Dict:
        """计算技术指标"""
        closes = data['close'].values
        highs = data['high'].values
        lows = data['low'].values
        volumes = data['volume'].values

        # 移动平均线
        ema_21 = self.ema(closes, 21)
        ema_55 = self.ema(closes, 55)

        # RSI
        rsi = self.rsi(closes, 14)

        # MACD
        macd, macd_signal, macd_hist = self.macd(closes)

        # ATR
        atr = self.atr(highs, lows, closes, 14)

        # ADX
        adx = self.adx(highs, lows, closes, 14)

        # 布林带
        bb_upper, bb_middle, bb_lower = self.bollinger_bands(closes, 20, 2)

        return {
            'ema_21': ema_21[-1],
            'ema_55': ema_55[-1],
            'rsi': rsi[-1],
            'macd': macd[-1],
            'macd_signal': macd_signal[-1],
            'macd_hist': macd_hist[-1],
            'atr': atr[-1],
            'adx': adx[-1],
            'bb_upper': bb_upper[-1],
            'bb_middle': bb_middle[-1],
            'bb_lower': bb_lower[-1],
            'current_price': closes[-1]
        }

    def calculate_score(self, indicators: Dict) -> float:
        """计算综合得分"""
        score = 0.5

        # EMA交叉（0.1）
        if indicators['ema_21'] > indicators['ema_55']:
            score += 0.1
        else:
            score -= 0.1

        # RSI（0.15）
        if 30 < indicators['rsi'] < 70:
            score += 0.05
        elif indicators['rsi'] > 70:
            score += 0.15  # 超买
        elif indicators['rsi'] < 30:
            score -= 0.15  # 超卖

        # MACD（0.15）
        if indicators['macd'] > indicators['macd_signal']:
            score += 0.1
        else:
            score -= 0.1

        # ADX（0.1）
        if indicators['adx'] > 25:
            score += 0.1  # 趋势明显

        return max(0.0, min(1.0, score))

    def determine_direction(self, indicators: Dict) -> str:
        """判断方向"""
        bullish_signals = 0
        bearish_signals = 0

        # EMA
        if indicators['ema_21'] > indicators['ema_55']:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # MACD
        if indicators['macd'] > indicators['macd_signal']:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # RSI
        if indicators['rsi'] > 50:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # 价格位置
        current_price = indicators['current_price']
        bb_upper = indicators['bb_upper']
        bb_lower = indicators['bb_lower']

        if current_price > bb_upper:
            bullish_signals += 2
        elif current_price < bb_lower:
            bearish_signals += 2

        if bullish_signals > bearish_signals:
            return 'LONG'
        elif bearish_signals > bullish_signals:
            return 'SHORT'
        else:
            return 'NEUTRAL'

    def assess_risk(self, indicators: Dict) -> str:
        """评估风险等级"""
        risk_score = 0

        # ATR波动率
        current_price = indicators['current_price']
        atr_ratio = indicators['atr'] / current_price
        if atr_ratio > 0.02:
            risk_score += 2
        elif atr_ratio > 0.01:
            risk_score += 1

        # RSI极端值
        if indicators['rsi'] > 80 or indicators['rsi'] < 20:
            risk_score += 1

        # ADX
        if indicators['adx'] > 50:
            risk_score += 1

        if risk_score >= 3:
            return 'HIGH'
        elif risk_score >= 1:
            return 'MEDIUM'
        else:
            return 'LOW'

    def ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算EMA"""
        alpha = 2 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]

        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]

        return ema

    def rsi(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算RSI"""
        delta = np.diff(data)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)

        avg_gain = np.mean(gain[:period])
        avg_loss = np.mean(loss[:period])

        rsi = np.zeros(len(data))
        rsi[:period] = 50

        for i in range(period, len(data)):
            avg_gain = (avg_gain * (period - 1) + gain[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + loss[i - 1]) / period

            if avg_loss == 0:
                rsi[i] = 100
            else:
                rs = avg_gain / avg_loss
                rsi[i] = 100 - (100 / (1 + rs))

        return rsi

    def macd(self, data: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
        """计算MACD"""
        ema_fast = self.ema(data, fast)
        ema_slow = self.ema(data, slow)

        macd = ema_fast - ema_slow
        macd_signal = self.ema(macd, signal)
        macd_hist = macd - macd_signal

        return macd, macd_signal, macd_hist

    def atr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
        """计算ATR"""
        tr = np.zeros(len(close))

        for i in range(1, len(close)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )

        atr = np.zeros_like(tr)
        atr[period] = np.mean(tr[:period])

        for i in range(period + 1, len(tr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        return atr

    def adx(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
        """计算ADX（简化版）"""
        # 简化实现
        atr = self.atr(high, low, close, period)
        atr_ratio = atr / close

        # 模拟ADX值
        adx = np.zeros(len(close))
        for i in range(len(close)):
            if atr_ratio[i] > 0.01:
                adx[i] = 20 + atr_ratio[i] * 1000
            else:
                adx[i] = 20

        return adx

    def bollinger_bands(self, data: np.ndarray, period: int, std_dev: float):
        """计算布林带"""
        sma = np.convolve(data, np.ones(period) / period, mode='valid')
        std = np.array([np.std(data[i:i+period]) for i in range(len(data) - period + 1)])

        upper = sma + std_dev * std
        middle = sma
        lower = sma - std_dev * std

        return upper, middle, lower


class FundamentalAnalyzer:
    """基本面分析器（简化版）"""

    def __init__(self):
        pass

    def analyze(self, market_data: Dict) -> AnalysisResult:
        """执行基本面分析"""
        # 模拟基本面分析
        score = 0.5 + np.random.uniform(-0.1, 0.1)

        # 简单的市值、交易量等因素
        volume = market_data.get('volume', 1000)
        price = market_data.get('close', 50000)

        # 流动性评分
        liquidity_score = min(volume / 10000, 1.0)
        score = score * 0.7 + liquidity_score * 0.3

        return AnalysisResult(
            analysis_type=AnalysisType.FUNDAMENTAL,
            score=score,
            confidence=0.6,
            direction=None,
            risk_level="LOW" if liquidity_score > 0.5 else "MEDIUM",
            details={'liquidity_score': liquidity_score}
        )


class SentimentAnalyzer:
    """情绪分析器（简化版）"""

    def __init__(self):
        pass

    def analyze(self, market_data: Dict) -> AnalysisResult:
        """执行情绪分析"""
        # 模拟情绪分析
        score = 0.5 + np.random.uniform(-0.15, 0.15)

        direction = None
        if score > 0.6:
            direction = 'LONG'
        elif score < 0.4:
            direction = 'SHORT'

        return AnalysisResult(
            analysis_type=AnalysisType.SENTIMENT,
            score=score,
            confidence=0.5,
            direction=direction,
            risk_level="MEDIUM",
            details={'market_sentiment': 'bullish' if score > 0.5 else 'bearish'}
        )


class RiskAnalyzer:
    """风险分析器"""

    def __init__(self):
        pass

    def analyze(self, market_data: Dict, historical_data: pd.DataFrame) -> AnalysisResult:
        """执行风险分析"""
        if len(historical_data) < 20:
            return AnalysisResult(
                analysis_type=AnalysisType.RISK,
                score=0.5,
                confidence=0.3,
                direction=None,
                risk_level="MEDIUM",
                details={'error': 'insufficient_data'}
            )

        closes = historical_data['close'].values

        # 计算波动率
        returns = np.diff(closes) / closes[:-1]
        volatility = np.std(returns)

        # 风险评分（波动率越大，风险越高）
        risk_score = min(volatility / 0.02, 1.0)
        score = 1.0 - risk_score  # 得分越高，风险越低

        # 风险等级
        if risk_score > 0.6:
            risk_level = "HIGH"
        elif risk_score > 0.3:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        return AnalysisResult(
            analysis_type=AnalysisType.RISK,
            score=score,
            confidence=0.9,
            direction=None,
            risk_level=risk_level,
            details={
                'volatility': volatility,
                'risk_score': risk_score
            }
        )


class PredictionAnalyzer:
    """预测分析器（简化版，集成LSTM等模型）"""

    def __init__(self):
        pass

    def analyze(self, market_data: Dict, historical_data: pd.DataFrame) -> AnalysisResult:
        """执行预测分析"""
        if len(historical_data) < 50:
            return AnalysisResult(
                analysis_type=AnalysisType.PREDICTION,
                score=0.5,
                confidence=0.3,
                direction=None,
                risk_level="MEDIUM",
                details={'error': 'insufficient_data'}
            )

        closes = historical_data['close'].values

        # 简单的线性趋势预测
        if len(closes) >= 20:
            # 使用最近20根K线
            recent_closes = closes[-20:]
            trend = np.polyfit(range(len(recent_closes)), recent_closes, 1)[0]

            score = 0.5 + trend / closes[-1] * 10
            score = max(0.0, min(1.0, score))

            direction = None
            if score > 0.6:
                direction = 'LONG'
            elif score < 0.4:
                direction = 'SHORT'
        else:
            score = 0.5
            direction = None

        return AnalysisResult(
            analysis_type=AnalysisType.PREDICTION,
            score=score,
            confidence=0.7,
            direction=direction,
            risk_level="MEDIUM",
            details={'trend_slope': trend if len(closes) >= 20 else 0}
        )


class ComprehensiveAnalyzer:
    """综合分析器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化综合分析器

        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.enable_technical = self.config.get('enable_technical', True)
        self.enable_fundamental = self.config.get('enable_fundamental', True)
        self.enable_sentiment = self.config.get('enable_sentiment', True)
        self.enable_risk = self.config.get('enable_risk', True)
        self.enable_prediction = self.config.get('enable_prediction', True)

        self.technical_analyzer = TechnicalAnalyzer()
        self.fundamental_analyzer = FundamentalAnalyzer()
        self.sentiment_analyzer = SentimentAnalyzer()
        self.risk_analyzer = RiskAnalyzer()
        self.prediction_analyzer = PredictionAnalyzer()

    def analyze(self, opportunity: Dict, historical_data: pd.DataFrame) -> ComprehensiveAnalysis:
        """执行综合分析"""
        market_data = opportunity.get('details', {})

        # 各维度分析
        results = {}

        if self.enable_technical:
            results['technical'] = self.technical_analyzer.analyze(market_data, historical_data)

        if self.enable_fundamental:
            results['fundamental'] = self.fundamental_analyzer.analyze(market_data)

        if self.enable_sentiment:
            results['sentiment'] = self.sentiment_analyzer.analyze(market_data)

        if self.enable_risk:
            results['risk'] = self.risk_analyzer.analyze(market_data, historical_data)

        if self.enable_prediction:
            results['prediction'] = self.prediction_analyzer.analyze(market_data, historical_data)

        # 综合评分
        overall_score, overall_direction, overall_risk = self.aggregate_results(results)

        # 生成建议
        recommendation = self.generate_recommendation(results, overall_score, overall_direction, overall_risk)

        comprehensive_analysis = ComprehensiveAnalysis(
            opportunity_id=opportunity.get('scan_id', f"opp_{int(time.time())}"),
            analysis_time=time.time(),
            overall_score=overall_score,
            overall_direction=overall_direction,
            overall_risk=overall_risk,
            technical_analysis=results.get('technical'),
            fundamental_analysis=results.get('fundamental'),
            sentiment_analysis=results.get('sentiment'),
            risk_analysis=results.get('risk'),
            prediction_analysis=results.get('prediction'),
            recommendation=recommendation
        )

        return comprehensive_analysis

    def aggregate_results(self, results: Dict) -> Tuple[float, str, str]:
        """聚合分析结果"""
        # 权重
        weights = {
            'technical': 0.35,
            'fundamental': 0.15,
            'sentiment': 0.15,
            'risk': 0.15,
            'prediction': 0.20
        }

        # 加权得分
        total_score = 0.0
        total_weight = 0.0

        for key, result in results.items():
            weight = weights.get(key, 0)
            total_score += result.score * weight
            total_weight += weight

        if total_weight > 0:
            overall_score = total_score / total_weight
        else:
            overall_score = 0.5

        # 综合方向
        bullish_votes = 0
        bearish_votes = 0

        for result in results.values():
            if result.direction == 'LONG':
                bullish_votes += 1
            elif result.direction == 'SHORT':
                bearish_votes += 1

        if bullish_votes > bearish_votes:
            overall_direction = 'LONG'
        elif bearish_votes > bullish_votes:
            overall_direction = 'SHORT'
        else:
            overall_direction = 'NEUTRAL'

        # 综合风险
        risk_weights = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}
        total_risk_score = 0.0
        total_risk_weight = 0.0

        for result in results.values():
            risk_weight = risk_weights.get(result.risk_level, 2)
            total_risk_score += risk_weight
            total_risk_weight += 1

        if total_risk_weight > 0:
            avg_risk_score = total_risk_score / total_risk_weight
            if avg_risk_score >= 2.5:
                overall_risk = 'HIGH'
            elif avg_risk_score >= 1.5:
                overall_risk = 'MEDIUM'
            else:
                overall_risk = 'LOW'
        else:
            overall_risk = 'MEDIUM'

        return overall_score, overall_direction, overall_risk

    def generate_recommendation(self, results: Dict, overall_score: float, overall_direction: str, overall_risk: str) -> Dict:
        """生成建议"""
        recommendation = {
            'action': 'HOLD',
            'reason': '',
            'confidence': 0.0
        }

        # 决策逻辑
        if overall_score >= 0.65 and overall_risk != 'HIGH':
            if overall_direction == 'LONG':
                recommendation['action'] = 'BUY'
            elif overall_direction == 'SHORT':
                recommendation['action'] = 'SELL'
            recommendation['reason'] = f'综合得分{overall_score:.2f}较高，方向{overall_direction}，风险{overall_risk}'
            recommendation['confidence'] = overall_score
        elif overall_score <= 0.35:
            if overall_direction == 'LONG':
                recommendation['action'] = 'SELL'
            elif overall_direction == 'SHORT':
                recommendation['action'] = 'BUY'
            recommendation['reason'] = f'综合得分{overall_score:.2f}较低，反向操作'
            recommendation['confidence'] = 1.0 - overall_score
        else:
            recommendation['reason'] = f'综合得分{overall_score:.2f}适中，建议观望'
            recommendation['confidence'] = 0.5

        return recommendation


def main():
    parser = argparse.ArgumentParser(description="综合分析器（第2层：综合分析）")
    parser.add_argument("--action", choices=["analyze", "test"], default="analyze", help="操作类型")
    parser.add_argument("--opportunity", help="机会数据JSON")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r') as f:
                config = json.load(f)

        # 创建综合分析器
        analyzer = ComprehensiveAnalyzer(config)

        logger.info("=" * 70)
        logger.info("✅ 杀手锏交易系统 - 综合分析器（第2层：综合分析）")
        logger.info("=" * 70)

        if args.action == "analyze":
            # 加载机会数据
            if not args.opportunity:
                # 使用默认机会数据
                opportunity = {
                    'scan_id': f"scan_{int(time.time())}",
                    'market': 'spot',
                    'symbol': 'BTCUSDT',
                    'timeframe': '1h',
                    'opportunity_type': 'TREND',
                    'direction': 'LONG',
                    'strength': 0.75,
                    'confidence': 0.80,
                    'details': {
                        'close': 50000.0,
                        'high': 50100.0,
                        'low': 49900.0,
                        'volume': 1000.0
                    }
                }
            else:
                opportunity = json.loads(args.opportunity)

            # 生成历史数据
            historical_data = analyzer.technical_analyzer.generate_historical_data(
                opportunity['details'].get('close', 50000.0), 50
            )

            # 执行分析
            logger.info(f"\n[分析开始] 机会ID: {opportunity.get('scan_id', 'unknown')}")
            logger.info(f"[分析开始] 品种: {opportunity.get('symbol', 'unknown')}")
            logger.info(f"[分析开始] 类型: {opportunity.get('opportunity_type', 'unknown')}")

            analysis = analyzer.analyze(opportunity, historical_data)

            logger.info(f"\n[分析完成] 综合得分: {analysis.overall_score:.2f}")
            logger.info(f"[分析完成] 综合方向: {analysis.overall_direction}")
            logger.info(f"[分析完成] 综合风险: {analysis.overall_risk}")

            # 各维度结果
            logger.info(f"\n[维度分析]")
            if analysis.technical_analysis:
                ta = analysis.technical_analysis
                logger.info(f"  技术分析: 得分={ta.score:.2f}, 方向={ta.direction}, 风险={ta.risk_level}")

            if analysis.fundamental_analysis:
                fa = analysis.fundamental_analysis
                logger.info(f"  基本面分析: 得分={fa.score:.2f}, 风险={fa.risk_level}")

            if analysis.sentiment_analysis:
                sa = analysis.sentiment_analysis
                logger.info(f"  情绪分析: 得分={sa.score:.2f}, 方向={sa.direction}, 风险={sa.risk_level}")

            if analysis.risk_analysis:
                ra = analysis.risk_analysis
                logger.info(f"  风险分析: 得分={ra.score:.2f}, 风险={ra.risk_level}")

            if analysis.prediction_analysis:
                pa = analysis.prediction_analysis
                logger.info(f"  预测分析: 得分={pa.score:.2f}, 方向={pa.direction}, 风险={pa.risk_level}")

            # 建议
            logger.info(f"\n[交易建议]")
            logger.info(f"  操作: {analysis.recommendation['action']}")
            logger.info(f"  原因: {analysis.recommendation['reason']}")
            logger.info(f"  置信度: {analysis.recommendation['confidence']:.2%}")

            output = {
                "status": "success",
                "analysis": analysis.to_dict()
            }

        elif args.action == "test":
            # 测试模式
            test_opportunity = {
                'scan_id': 'test_opp',
                'market': 'spot',
                'symbol': 'BTCUSDT',
                'timeframe': '1h',
                'opportunity_type': 'TREND',
                'direction': 'LONG',
                'strength': 0.8,
                'confidence': 0.85,
                'details': {
                    'close': 50000.0,
                    'high': 50100.0,
                    'low': 49900.0,
                    'volume': 1000.0
                }
            }

            historical_data = analyzer.technical_analyzer.generate_historical_data(50000.0, 50)
            analysis = analyzer.analyze(test_opportunity, historical_data)

            output = {
                "status": "success",
                "test_analysis": analysis.to_dict()
            }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        import traceback
        logger.error(json.dumps({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
