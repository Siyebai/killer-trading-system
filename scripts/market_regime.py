#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("market_regime")
except ImportError:
    import logging
    logger = logging.getLogger("market_regime")
"""
市场状态识别脚本
识别趋势、震荡、高波动、流动性差等市场状态
"""

import argparse
import json
import sys
import numpy as np
from typing import Dict, Optional, Any


# 市场状态常量
BAD_LIQUIDITY = "BAD_LIQUIDITY"
HIGH_VOLATILITY = "HIGH_VOLATILITY"
TREND = "TREND"
RANGE = "RANGE"
NOISE = "NOISE"


class MarketRegimeDetector:
    """市场状态识别器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化市场状态识别器

        Args:
            config: 配置参数
        """
        self.config = config if config is not None else {}

        # 默认配置（使用统一配置获取方法）
        self.max_spread_pct = self._get_config('max_spread_pct', 0.0004)
        self.volatility_halt_threshold = self._get_config('volatility_halt_threshold', 0.012)
        self.trend_strength_threshold = self._get_config('trend_strength_threshold', 0.0008)
        self.flow_strength_threshold = self._get_config('flow_strength_threshold', 0.20)
        self.range_trend_threshold = self._get_config('range_trend_threshold', 0.0003)
        self.range_volatility_threshold = self._get_config('range_volatility_threshold', 0.004)

    def _get_config(self, key: str, default: Any = None) -> Any:
        """统一配置获取方法"""
        return self.config.get(key, default)

    def calculate_adx(self, high_prices: list, low_prices: list, close_prices: list, period: int = 14) -> float:
        """
        计算ADX（平均趋向指数）

        Args:
            high_prices: 最高价列表
            low_prices: 最低价列表
            close_prices: 收盘价列表
            period: 计算周期（默认14）

        Returns:
            ADX值
        """
        if len(high_prices) < period + 1:
            return 0.0

        high_prices = np.array(high_prices[-period-1:])
        low_prices = np.array(low_prices[-period-1:])
        close_prices = np.array(close_prices[-period-1:])

        # 计算TR
        tr = np.zeros(period)
        for i in range(1, period + 1):
            hl = high_prices[i] - low_prices[i]
            hpc = abs(high_prices[i] - close_prices[i-1])
            lpc = abs(low_prices[i] - close_prices[i-1])
            tr[i-1] = max(hl, hpc, lpc)

        # 计算+DM和-DM
        plus_dm = np.zeros(period)
        minus_dm = np.zeros(period)
        for i in range(1, period + 1):
            up = high_prices[i] - high_prices[i-1]
            down = low_prices[i-1] - low_prices[i]

            if up > down and up > 0:
                plus_dm[i-1] = up
            if down > up and down > 0:
                minus_dm[i-1] = down

        # 平滑+DM, -DM, TR
        smoothed_plus_dm = np.zeros(period)
        smoothed_minus_dm = np.zeros(period)
        smoothed_tr = np.zeros(period)

        if period > 0:
            smoothed_plus_dm[0] = plus_dm[0]
            smoothed_minus_dm[0] = minus_dm[0]
            smoothed_tr[0] = tr[0]

            for i in range(1, period):
                smoothed_plus_dm[i] = smoothed_plus_dm[i-1] - smoothed_plus_dm[i-1] / period + plus_dm[i]
                smoothed_minus_dm[i] = smoothed_minus_dm[i-1] - smoothed_minus_dm[i-1] / period + minus_dm[i]
                smoothed_tr[i] = smoothed_tr[i-1] - smoothed_tr[i-1] / period + tr[i]

        # 计算DI+
        plus_di = np.zeros(period)
        minus_di = np.zeros(period)
        for i in range(period):
            if smoothed_tr[i] > 0:
                plus_di[i] = (smoothed_plus_dm[i] / smoothed_tr[i]) * 100
                minus_di[i] = (smoothed_minus_dm[i] / smoothed_tr[i]) * 100

        # 计算DX
        dx = np.zeros(period)
        for i in range(period):
            di_sum = plus_di[i] + minus_di[i]
            if di_sum > 0:
                dx[i] = abs(plus_di[i] - minus_di[i]) / di_sum * 100

        # 计算ADX
        if period > 0:
            adx = np.mean(dx)
        else:
            adx = 0.0

        return adx

    def detect_with_adx_filtering(self, indicators: Dict, orderflow: Dict, market_tick: Dict,
                                   price_history: Dict) -> Dict:
        """
        使用ADX五级分层过滤的市场状态识别

        Args:
            indicators: 技术指标
            orderflow: 订单流特征
            market_tick: 市场行情
            price_history: 价格历史 {'high': [...], 'low': [...], 'close': [...]}

        Returns:
            识别结果（包含ADX过滤建议）
        """
        # 先进行基础检测
        base_result = self.detect(indicators, orderflow, market_tick)

        # 提取价格历史用于ADX计算
        highs = price_history.get('high', [])
        lows = price_history.get('low', [])
        closes = price_history.get('close', [])

        if len(highs) < 15 or len(lows) < 15 or len(closes) < 15:
            base_result['adx_filter'] = {
                'adx': 0.0,
                'filter_level': 'NO_DATA',
                'should_trade': True,
                'reason': '价格历史数据不足，无法计算ADX'
            }
            return base_result

        # 计算ADX
        adx = self.calculate_adx(highs, lows, closes, period=14)

        # ADX五级分层过滤
        filter_result = {
            'adx': adx,
            'filter_level': '',
            'should_trade': True,
            'min_confidence': 0.0,
            'reason': ''
        }

        if adx < 20:
            # 无趋势市，完全暂停交易
            filter_result['filter_level'] = 'NO_TREND'
            filter_result['should_trade'] = False
            filter_result['reason'] = f'ADX({adx:.1f}) < 20，无趋势市，暂停所有交易'

        elif adx < 25:
            # 弱趋势市，只接受高置信度信号
            filter_result['filter_level'] = 'WEAK_TREND'
            filter_result['should_trade'] = True
            filter_result['min_confidence'] = 0.8
            filter_result['reason'] = f'ADX({adx:.1f}) < 25，弱趋势市，只接受高置信度信号(>0.8)'

        elif adx <= 45:
            # 强趋势市，正常执行
            filter_result['filter_level'] = 'STRONG_TREND'
            filter_result['should_trade'] = True
            filter_result['min_confidence'] = 0.5
            filter_result['reason'] = f'ADX({adx:.1f}) 25-45，强趋势市，正常执行信号'

        else:
            # 趋势过热，暂停开新仓
            filter_result['filter_level'] = 'OVERHEATED'
            filter_result['should_trade'] = False
            filter_result['reason'] = f'ADX({adx:.1f}) > 45，趋势过热，暂停开新仓'

        base_result['adx_filter'] = filter_result

        # 如果ADX建议不交易，覆盖原有决策
        if not filter_result['should_trade']:
            base_result['regime'] = 'NO_TREND_PAUSE'
            base_result['confidence'] = 0.0
            base_result['reason'] = filter_result['reason']

        return base_result

    def is_favorable_for_signal(self, signal: str, adx_value: float) -> bool:
        """
        判断当前市场环境是否适合该信号

        Args:
            signal: 信号类型（BUY/SELL/HOLD）
            adx_value: ADX值

        Returns:
            是否适合交易
        """
        if adx_value < 20:
            return False  # 无趋势市

        if adx_value > 45:
            return False  # 趋势过热

        return True  # 适合交易

    def detect(self, indicators: Dict, orderflow: Dict, market_tick: Dict) -> Dict:
        """
        识别市场状态

        Args:
            indicators: 技术指标
            orderflow: 订单流特征
            market_tick: 市场行情

        Returns:
            识别结果
        """
        if not indicators or not orderflow or not market_tick:
            return {
                'regime': NOISE,
                'reason': '输入数据为空',
                'confidence': 0.0,
                'details': {}
            }

        price = market_tick.get('price', 0)

        if price is None or abs(price) < 1e-8:
            return {
                'regime': NOISE,
                'reason': '无效价格',
                'confidence': 0.0,
                'details': {}
            }

        # 提取关键指标
        sma5 = indicators.get('sma5', 0)
        sma20 = indicators.get('sma20', 0)
        volatility = indicators.get('volatility', 0)
        rsi = indicators.get('rsi', 50)

        bid = market_tick.get('bid', price)
        ask = market_tick.get('ask', price)

        # 计算买卖价差
        spread = (ask - bid) / price if price > 0 else 0

        # 计算趋势强度
        trend_strength = abs(sma5 - sma20) / price if sma20 > 0 else 0

        # 订单流强度
        flow_strength = abs(orderflow.get('pressure', 0))

        details = {
            'trend_strength': trend_strength,
            'volatility': volatility,
            'spread': spread,
            'rsi': rsi,
            'flow_strength': flow_strength
        }

        # 检查流动性
        if spread > self.max_spread_pct:
            return {
                'regime': BAD_LIQUIDITY,
                'reason': f'价差过大: {spread:.4%}',
                'confidence': 0.9,
                'details': details
            }

        # 检查高波动
        if volatility > self.volatility_halt_threshold:
            return {
                'regime': HIGH_VOLATILITY,
                'reason': f'波动率过高: {volatility:.4%}',
                'confidence': 0.85,
                'details': details
            }

        # 识别趋势
        if trend_strength > self.trend_strength_threshold:
            direction = "BULL" if sma5 > sma20 else "BEAR"
            return {
                'regime': f"{direction}_{TREND}",
                'reason': f'趋势强度: {trend_strength:.4%}',
                'confidence': min(0.95, 0.7 + trend_strength * 10),
                'details': details
            }

        # 识别震荡
        if (trend_strength < self.range_trend_threshold and
            volatility < self.range_volatility_threshold):
            return {
                'regime': RANGE,
                'reason': f'震荡区间: 趋势={trend_strength:.4%}, 波动={volatility:.4%}',
                'confidence': 0.75,
                'details': details
            }

        # 默认噪声
        return {
            'regime': NOISE,
            'reason': f'市场噪声: 趋势={trend_strength:.4%}',
            'confidence': 0.5,
            'details': details
        }


# 命令行入口
def main():
    parser = argparse.ArgumentParser(description='市场状态识别')
    parser.add_argument('--config', help='配置文件路径')

    args = parser.parse_args()

    # 加载配置
    config = {}
    if args.config:
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            logger.error(f"加载配置失败: {e}", file=sys.stderr)
            sys.exit(1)

    # 创建识别器
    detector = MarketRegimeDetector(config)

    # 示例数据
    indicators = {
        'sma5': 50000.0,
        'sma20': 49500.0,
        'volatility': 0.008,
        'rsi': 65
    }

    orderflow = {
        'pressure': 0.15,
        'cvd_slope': 0.05
    }

    market_tick = {
        'price': 50100.0,
        'bid': 50099.0,
        'ask': 50101.0,
        'volume': 1000
    }

    # 检测
    result = detector.detect(indicators, orderflow, market_tick)

    # 输出
    logger.info(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
