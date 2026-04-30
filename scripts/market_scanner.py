#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("market_scanner")
except ImportError:
    import logging
    logger = logging.getLogger("market_scanner")

# 导入事件总线（Phase 5.6新增）
try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False
"""
市场扫描器（第1层：扫描发现）
多市场、多品种、多时间帧扫描，识别交易机会
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
import pandas as pd


class OpportunityType(Enum):
    """机会类型"""
    TREND = "TREND"  # 趋势机会
    MEAN_REVERSION = "MEAN_REVERSION"  # 均值回归机会
    BREAKOUT = "BREAKOUT"  # 突破机会
    PAIRS_TRADING = "PAIRS_TRADING"  # 统计套利机会


@dataclass
class Opportunity:
    """交易机会"""
    market: str  # 市场
    symbol: str  # 品种
    timeframe: str  # 时间帧
    opportunity_type: OpportunityType  # 机会类型
    direction: str  # 方向
    strength: float  # 强度
    confidence: float  # 置信度
    timestamp: float
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'market': self.market,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'opportunity_type': self.opportunity_type.value,
            'direction': self.direction,
            'strength': self.strength,
            'confidence': self.confidence,
            'timestamp': self.timestamp,
            'details': self.details
        }


@dataclass
class ScanResult:
    """扫描结果"""
    scan_id: str
    scan_time: float
    total_opportunities: int
    opportunities: List[Opportunity]
    scan_summary: Dict[str, Any]

    def to_dict(self) -> Dict:
        return {
            'scan_id': self.scan_id,
            'scan_time': self.scan_time,
            'total_opportunities': self.total_opportunities,
            'opportunities': [op.to_dict() for op in self.opportunities],
            'scan_summary': self.scan_summary
        }


class OpportunityDetector:
    """机会检测器"""

    def __init__(self):
        pass

    def detect(self, market_data: Dict, historical_data: Optional[pd.DataFrame] = None) -> List[Opportunity]:
        """检测交易机会"""
        opportunities = []

        # 趋势机会
        if self.is_trend_opportunity(market_data, historical_data):
            trend_opportunity = self.create_trend_opportunity(market_data, historical_data)
            if trend_opportunity:
                opportunities.append(trend_opportunity)

        # 均值回归机会
        if self.is_mean_reversion_opportunity(market_data, historical_data):
            reversion_opportunity = self.create_reversion_opportunity(market_data, historical_data)
            if reversion_opportunity:
                opportunities.append(reversion_opportunity)

        # 突破机会
        if self.is_breakout_opportunity(market_data, historical_data):
            breakout_opportunity = self.create_breakout_opportunity(market_data, historical_data)
            if breakout_opportunity:
                opportunities.append(breakout_opportunity)

        # 统计套利机会（需要配对数据）
        if self.is_pairs_opportunity(market_data):
            pairs_opportunity = self.create_pairs_opportunity(market_data)
            if pairs_opportunity:
                opportunities.append(pairs_opportunity)

        return opportunities

    def is_trend_opportunity(self, market_data: Dict, historical_data: Optional[pd.DataFrame]) -> bool:
        """判断是否有趋势机会"""
        if historical_data is None or len(historical_data) < 20:
            return False

        # 简单趋势判断：EMA金叉死叉
        closes = historical_data['close'].values

        # 计算EMA
        ema_fast = self.calculate_ema(closes, 12)
        ema_slow = self.calculate_ema(closes, 26)

        # 检查金叉
        if ema_fast[-1] > ema_slow[-1] and ema_fast[-2] <= ema_slow[-2]:
            return True

        # 检查死叉
        if ema_fast[-1] < ema_slow[-1] and ema_fast[-2] >= ema_slow[-2]:
            return True

        return False

    def is_mean_reversion_opportunity(self, market_data: Dict, historical_data: Optional[pd.DataFrame]) -> bool:
        """判断是否有均值回归机会"""
        if historical_data is None or len(historical_data) < 20:
            return False

        # 使用RSI判断超买超卖
        closes = historical_data['close'].values
        rsi = self.calculate_rsi(closes, 14)

        # RSI超买（>70）或超卖（<30）
        if rsi[-1] > 70 or rsi[-1] < 30:
            return True

        return False

    def is_breakout_opportunity(self, market_data: Dict, historical_data: Optional[pd.DataFrame]) -> bool:
        """判断是否有突破机会"""
        if historical_data is None or len(historical_data) < 20:
            return False

        # 检查价格是否突破布林带
        closes = historical_data['close'].values
        bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(closes, 20, 2)

        # 突破上轨
        if closes[-1] > bb_upper[-1]:
            return True

        # 跌破下轨
        if closes[-1] < bb_lower[-1]:
            return True

        return False

    def is_pairs_opportunity(self, market_data: Dict) -> bool:
        """判断是否有统计套利机会（简化版）"""
        # 实际应该检查配对品种的价差
        return False

    def create_trend_opportunity(self, market_data: Dict, historical_data: Optional[pd.DataFrame]) -> Optional[Opportunity]:
        """创建趋势机会"""
        if historical_data is None or len(historical_data) < 20:
            return None

        closes = historical_data['close'].values
        ema_fast = self.calculate_ema(closes, 12)
        ema_slow = self.calculate_ema(closes, 26)

        # 判断方向
        if ema_fast[-1] > ema_slow[-1] and ema_fast[-2] <= ema_slow[-2]:
            direction = 'LONG'
        elif ema_fast[-1] < ema_slow[-1] and ema_fast[-2] >= ema_slow[-2]:
            direction = 'SHORT'
        else:
            return None

        # 计算强度
        strength = abs(ema_fast[-1] - ema_slow[-1]) / ema_slow[-1]

        return Opportunity(
            market=market_data.get('market', 'unknown'),
            symbol=market_data.get('symbol', 'unknown'),
            timeframe=market_data.get('timeframe', '1h'),
            opportunity_type=OpportunityType.TREND,
            direction=direction,
            strength=strength,
            confidence=min(strength * 100, 0.9),
            timestamp=time.time(),
            details={
                'ema_fast': ema_fast[-1],
                'ema_slow': ema_slow[-1],
                'price': market_data.get('close', 0)
            }
        )

    def create_reversion_opportunity(self, market_data: Dict, historical_data: Optional[pd.DataFrame]) -> Optional[Opportunity]:
        """创建均值回归机会"""
        if historical_data is None or len(historical_data) < 20:
            return None

        closes = historical_data['close'].values
        rsi = self.calculate_rsi(closes, 14)

        if rsi[-1] > 70:
            direction = 'SHORT'
            strength = (rsi[-1] - 70) / 30
        elif rsi[-1] < 30:
            direction = 'LONG'
            strength = (30 - rsi[-1]) / 30
        else:
            return None

        return Opportunity(
            market=market_data.get('market', 'unknown'),
            symbol=market_data.get('symbol', 'unknown'),
            timeframe=market_data.get('timeframe', '1h'),
            opportunity_type=OpportunityType.MEAN_REVERSION,
            direction=direction,
            strength=strength,
            confidence=min(strength * 100, 0.8),
            timestamp=time.time(),
            details={
                'rsi': rsi[-1],
                'price': market_data.get('close', 0)
            }
        )

    def create_breakout_opportunity(self, market_data: Dict, historical_data: Optional[pd.DataFrame]) -> Optional[Opportunity]:
        """创建突破机会"""
        if historical_data is None or len(historical_data) < 20:
            return None

        closes = historical_data['close'].values
        bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(closes, 20, 2)

        if closes[-1] > bb_upper[-1]:
            direction = 'LONG'
            strength = (closes[-1] - bb_upper[-1]) / bb_upper[-1]
        elif closes[-1] < bb_lower[-1]:
            direction = 'SHORT'
            strength = (bb_lower[-1] - closes[-1]) / bb_lower[-1]
        else:
            return None

        return Opportunity(
            market=market_data.get('market', 'unknown'),
            symbol=market_data.get('symbol', 'unknown'),
            timeframe=market_data.get('timeframe', '1h'),
            opportunity_type=OpportunityType.BREAKOUT,
            direction=direction,
            strength=strength,
            confidence=min(strength * 100, 0.85),
            timestamp=time.time(),
            details={
                'bb_upper': bb_upper[-1],
                'bb_lower': bb_lower[-1],
                'price': market_data.get('close', 0)
            }
        )

    def create_pairs_opportunity(self, market_data: Dict) -> Optional[Opportunity]:
        """创建统计套利机会（简化版）"""
        return None

    def calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """计算EMA"""
        alpha = 2 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]

        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]

        return ema

    def calculate_rsi(self, data: np.ndarray, period: int) -> np.ndarray:
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

            if abs(avg_loss) < 1e-10:
                rsi[i] = 100
            else:
                rs = avg_gain / avg_loss
                rsi[i] = 100 - (100 / (1 + rs))

        return rsi

    def calculate_bollinger_bands(self, data: np.ndarray, period: int, std_dev: float):
        """计算布林带"""
        sma = np.convolve(data, np.ones(period) / period, mode='valid')
        std = np.array([np.std(data[i:i+period]) for i in range(len(data) - period + 1)])

        upper = sma + std_dev * std
        middle = sma
        lower = sma - std_dev * std

        return upper, middle, lower


class SignalAggregator:
    """信号聚合器"""

    def __init__(self, confidence_threshold: float = 0.7):
        self.confidence_threshold = confidence_threshold

    def aggregate(self, opportunities: List[Opportunity]) -> ScanResult:
        """聚合信号"""
        # 按置信度过滤
        filtered_opportunities = [
            op for op in opportunities
            if op.confidence >= self.confidence_threshold
        ]

        # 按品种聚合
        aggregated = {}
        for op in filtered_opportunities:
            key = (op.market, op.symbol, op.timeframe)
            if key not in aggregated:
                aggregated[key] = []
            aggregated[key].append(op)

        # 选择最佳机会
        final_opportunities = []
        for key, ops in aggregated.items():
            if len(ops) == 1:
                final_opportunities.append(ops[0])
            else:
                # 多个机会，选择置信度最高的
                best_op = max(ops, key=lambda x: x.confidence)
                final_opportunities.append(best_op)

        # 生成扫描摘要
        summary = self.generate_summary(final_opportunities)

        scan_result = ScanResult(
            scan_id=f"scan_{int(time.time())}",
            scan_time=time.time(),
            total_opportunities=len(final_opportunities),
            opportunities=final_opportunities,
            scan_summary=summary
        )

        return scan_result

    def generate_summary(self, opportunities: List[Opportunity]) -> Dict[str, Any]:
        """生成扫描摘要"""
        summary = {
            'by_type': {},
            'by_direction': {},
            'by_symbol': {}
        }

        for op in opportunities:
            # 按类型统计
            type_name = op.opportunity_type.value
            if type_name not in summary['by_type']:
                summary['by_type'][type_name] = 0
            summary['by_type'][type_name] += 1

            # 按方向统计
            if op.direction not in summary['by_direction']:
                summary['by_direction'][op.direction] = 0
            summary['by_direction'][op.direction] += 1

            # 按品种统计
            if op.symbol not in summary['by_symbol']:
                summary['by_symbol'][op.symbol] = 0
            summary['by_symbol'][op.symbol] += 1

        return summary


class MarketScanner:
    """市场扫描器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化市场扫描器

        Args:
            config: 配置字典
        """
        self.config = config or {}
        self.markets = self.config.get('markets', ['spot', 'futures'])
        self.symbols = self.config.get('symbols', ['BTCUSDT', 'ETHUSDT'])
        self.timeframes = self.config.get('timeframes', ['5m', '15m', '1h', '4h'])
        self.confidence_threshold = self.config.get('confidence_threshold', 0.7)

        self.opportunity_detector = OpportunityDetector()
        self.signal_aggregator = SignalAggregator(self.confidence_threshold)

    def scan(self) -> ScanResult:
        """执行扫描"""
        all_opportunities = []
        scan_start_time = time.time()

        for market in self.markets:
            for symbol in self.symbols:
                for timeframe in self.timeframes:
                    # 获取市场数据（模拟）
                    market_data, historical_data = self.fetch_market_data(
                        market, symbol, timeframe
                    )

                    # 检测机会
                    opportunities = self.opportunity_detector.detect(market_data, historical_data)

                    if opportunities:
                        all_opportunities.extend(opportunities)

        # 聚合信号
        scan_result = self.signal_aggregator.aggregate(all_opportunities)

        # 广播market.scan_completed事件（Phase 5.6新增）
        if EVENT_BUS_AVAILABLE:
            self._publish_scan_completed_event(scan_result)

        return scan_result

    def _publish_scan_completed_event(self, scan_result: ScanResult):
        """
        广播市场扫描完成事件（Phase 5.6新增）

        Args:
            scan_result: 扫描结果
        """
        try:
            event_bus = get_event_bus()
            event_bus.publish(
                "market.scan_completed",
                {
                    "scan_id": scan_result.scan_id,
                    "scan_time": scan_result.scan_time,
                    "total_opportunities": scan_result.total_opportunities,
                    "opportunities_summary": {
                        "trend": sum(1 for op in scan_result.opportunities
                                   if op.opportunity_type == OpportunityType.TREND),
                        "mean_reversion": sum(1 for op in scan_result.opportunities
                                           if op.opportunity_type == OpportunityType.MEAN_REVERSION),
                        "breakout": sum(1 for op in scan_result.opportunities
                                     if op.opportunity_type == OpportunityType.BREAKOUT)
                    },
                    "scan_summary": scan_result.scan_summary,
                    "markets_scanned": len(self.markets) * len(self.symbols) * len(self.timeframes)
                },
                source="market_scanner"
            )
            logger.debug(f"市场扫描完成事件已广播: {scan_result.scan_id}")
        except Exception as e:
            logger.error(f"市场扫描事件广播失败: {e}")

    def fetch_market_data(self, market: str, symbol: str, timeframe: str) -> tuple:
        """获取市场数据（模拟）"""
        # 模拟实时市场数据
        current_price = 50000.0 if 'BTC' in symbol else 3000.0
        current_price *= (1 + np.random.uniform(-0.001, 0.001))

        market_data = {
            'market': market,
            'symbol': symbol,
            'timeframe': timeframe,
            'close': current_price,
            'high': current_price * 1.001,
            'low': current_price * 0.999,
            'volume': 1000.0
        }

        # 模拟历史数据
        historical_data = self.generate_historical_data(current_price, 50)

        return market_data, historical_data

    def generate_historical_data(self, base_price: float, count: int) -> pd.DataFrame:
        """生成历史数据（模拟）"""
        prices = [base_price]
        for _ in range(count):
            change = np.random.uniform(-0.002, 0.002)
            prices.append(prices[-1] * (1 + change))

        df = pd.DataFrame({
            'close': prices,
            'high': [p * 1.001 for p in prices],
            'low': [p * 0.999 for p in prices],
            'volume': [1000.0] * len(prices)
        })

        return df


def main():
    parser = argparse.ArgumentParser(description="市场扫描器（第1层：扫描发现）")
    parser.add_argument("--action", choices=["scan", "test"], default="scan", help="操作类型")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r') as f:
                config = json.load(f)

        # 创建市场扫描器
        scanner = MarketScanner(config)

        logger.info("=" * 70)
        logger.info("✅ 杀手锏交易系统 - 市场扫描器（第1层：扫描发现）")
        logger.info("=" * 70)

        if args.action == "scan":
            # 执行扫描
            logger.info(f"\n[扫描开始] 扫描市场: {scanner.markets}")
            logger.info(f"[扫描开始] 扫描品种: {scanner.symbols}")
            logger.info(f"[扫描开始] 扫描时间帧: {scanner.timeframes}")

            scan_result = scanner.scan()

            logger.info(f"\n[扫描完成] 扫描ID: {scan_result.scan_id}")
            logger.info(f"[扫描完成] 扫描时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(scan_result.scan_time))}")
            logger.info(f"[扫描完成] 发现机会: {scan_result.total_opportunities}个")

            if scan_result.total_opportunities > 0:
                logger.info(f"\n[机会详情]")
                for i, op in enumerate(scan_result.opportunities, 1):
                    logger.info(f"  {i}. {op.market}/{op.symbol} ({op.timeframe})")
                    logger.info(f"     类型: {op.opportunity_type.value}")
                    logger.info(f"     方向: {op.direction}")
                    logger.info(f"     强度: {op.strength:.4f}")
                    logger.info(f"     置信度: {op.confidence:.2%}")

                logger.info(f"\n[扫描摘要]")
                logger.info(f"  按类型: {json.dumps(scan_result.scan_summary['by_type'], ensure_ascii=False)}")
                logger.info(f"  按方向: {json.dumps(scan_result.scan_summary['by_direction'], ensure_ascii=False)}")
                logger.info(f"  按品种: {json.dumps(scan_result.scan_summary['by_symbol'], ensure_ascii=False)}")
            else:
                logger.info(f"\n[扫描结果] 未发现符合条件的交易机会")

            output = {
                "status": "success",
                "scan_result": scan_result.to_dict()
            }

        elif args.action == "test":
            # 测试单个品种
            scanner.config['markets'] = ['spot']
            scanner.config['symbols'] = ['BTCUSDT']
            scanner.config['timeframes'] = ['1h']

            scan_result = scanner.scan()
            output = {
                "status": "success",
                "test_result": scan_result.to_dict()
            }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error(json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
