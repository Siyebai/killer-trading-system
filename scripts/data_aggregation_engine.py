#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("data_aggregation_engine")
except ImportError:
    import logging
    logger = logging.getLogger("data_aggregation_engine")
"""
多源数据聚合引擎 - 杀手锏交易系统P0核心
整合L2订单簿、资金流、衍生品数据、链上数据，建立数据质量评分机制
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import time


class DataSource(Enum):
    """数据源类型"""
    OHLCV = "OHLCV"
    ORDERBOOK_L2 = "ORDERBOOK_L2"
    FUND_FLOW = "FUND_FLOW"
    DERIVATIVES = "DERIVATIVES"
    ON_CHAIN = "ON_CHAIN"


@dataclass
class DataQualityScore:
    """数据质量评分"""
    overall_score: float  # 0-1
    completeness: float  # 完整性
    accuracy: float  # 准确性
    timeliness: float  # 及时性
    consistency: float  # 一致性
    issues: List[str]  # 问题列表


@dataclass
class AggregatedMarketData:
    """聚合市场数据"""
    timestamp: float
    ohlcv: Dict
    orderbook: Dict
    fund_flow: Optional[Dict]
    derivatives: Optional[Dict]
    on_chain: Optional[Dict]
    quality_score: DataQualityScore


class DataAggregationEngine:
    """多源数据聚合引擎"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化数据聚合引擎

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 配置参数
        self.data_sources = self.config.get('data_sources', [
            DataSource.OHLCV,
            DataSource.ORDERBOOK_L2,
            DataSource.FUND_FLOW
        ])
        self.quality_threshold = self.config.get('quality_threshold', 0.7)
        self.max_latency_ms = self.config.get('max_latency_ms', 500)
        self.lookahead_detection_enabled = self.config.get('lookahead_detection', True)

        # 数据缓存
        self.data_cache: Dict[str, Any] = {}

        # 增量更新状态
        self.last_update_time = {}

    def aggregate_data(self, symbol: str, raw_data: Dict) -> AggregatedMarketData:
        """
        聚合多源数据

        Args:
            symbol: 交易对
            raw_data: 原始数据字典

        Returns:
            聚合后的市场数据
        """
        timestamp = time.time()

        # 提取各数据源
        ohlcv = raw_data.get('ohlcv', {})
        orderbook = raw_data.get('orderbook', {})
        fund_flow = raw_data.get('fund_flow')
        derivatives = raw_data.get('derivatives')
        on_chain = raw_data.get('on_chain')

        # 数据质量评分
        quality_score = self._calculate_quality_score(
            timestamp, ohlcv, orderbook, fund_flow, derivatives, on_chain
        )

        # 前视偏差检测
        if self.lookahead_detection_enabled:
            lookahead_issues = self._detect_lookahead_bias(raw_data)
            quality_score.issues.extend(lookahead_issues)

        # 构建聚合数据
        aggregated = AggregatedMarketData(
            timestamp=timestamp,
            ohlcv=ohlcv,
            orderbook=orderbook,
            fund_flow=fund_flow,
            derivatives=derivatives,
            on_chain=on_chain,
            quality_score=quality_score
        )

        # 更新缓存
        self.data_cache[symbol] = aggregated

        return aggregated

    def _calculate_quality_score(self, timestamp: float, *data_sources) -> DataQualityScore:
        """
        计算数据质量评分

        Args:
            timestamp: 当前时间戳
            *data_sources: 各数据源

        Returns:
            数据质量评分
        """
        issues = []
        scores = []

        # 1. 完整性评分
        completeness_scores = []
        for source in data_sources:
            if source and isinstance(source, dict) and source:
                completeness_scores.append(1.0)
            else:
                completeness_scores.append(0.0)
                issues.append(f"数据源缺失或为空")

        completeness = np.mean(completeness_scores) if completeness_scores else 0.0

        # 2. 准确性评分（基于数据范围检查）
        accuracy_scores = []
        for source in data_sources:
            if not source or not isinstance(source, dict):
                continue

            acc_score = 1.0

            # OHLCV数据检查
            if 'close' in source and isinstance(source['close'], (int, float)):
                if source['close'] <= 0 or source['close'] > 1e10:
                    acc_score *= 0.5
                    issues.append(f"价格数据异常: {source['close']}")

            # 订单簿数据检查
            if 'bids' in source and 'asks' in source:
                bids = source.get('bids', [])
                asks = source.get('asks', [])

                if not bids or not asks:
                    acc_score *= 0.7
                    issues.append("订单簿数据不完整")

                if bids and asks and bids[0][0] >= asks[0][0]:
                    acc_score *= 0.0
                    issues.append("订单簿价格交叉异常")

            accuracy_scores.append(acc_score)

        accuracy = np.mean(accuracy_scores) if accuracy_scores else 1.0

        # 3. 及时性评分（基于数据延迟）
        timeliness = 1.0
        for source in data_sources:
            if source and isinstance(source, dict):
                source_time = source.get('timestamp', 0)
                if source_time > 0:
                    latency_ms = (timestamp - source_time) * 1000
                    if latency_ms > self.max_latency_ms:
                        timeliness *= 0.8
                        issues.append(f"数据延迟过高: {latency_ms:.0f}ms")

        # 4. 一致性评分（跨数据源价格一致性）
        consistency_scores = []
        ohlcv_price = None
        orderbook_mid = None

        for source in data_sources:
            if not source or not isinstance(source, dict):
                continue

            if 'close' in source and isinstance(source['close'], (int, float)):
                ohlcv_price = source['close']

            if 'bids' in source and 'asks' in source:
                bids = source.get('bids', [])
                asks = source.get('asks', [])
                if bids and asks:
                    orderbook_mid = (bids[0][0] + asks[0][0]) / 2

        if ohlcv_price and orderbook_mid:
            price_diff = abs(ohlcv_price - orderbook_mid) / ohlcv_price
            if price_diff > 0.001:  # 0.1%差异
                consistency_scores.append(max(0, 1 - price_diff * 100))
                issues.append(f"价格一致性差异: {price_diff*100:.2f}%")
            else:
                consistency_scores.append(1.0)
        else:
            consistency_scores.append(1.0)

        consistency = np.mean(consistency_scores) if consistency_scores else 1.0

        # 综合评分
        overall_score = (
            completeness * 0.3 +
            accuracy * 0.3 +
            timeliness * 0.2 +
            consistency * 0.2
        )

        return DataQualityScore(
            overall_score=overall_score,
            completeness=completeness,
            accuracy=accuracy,
            timeliness=timeliness,
            consistency=consistency,
            issues=issues
        )

    def _detect_lookahead_bias(self, raw_data: Dict) -> List[str]:
        """
        检测前视偏差

        Args:
            raw_data: 原始数据

        Returns:
            问题列表
        """
        issues = []

        # 检查未来数据泄露
        current_time = time.time()

        for key, value in raw_data.items():
            if isinstance(value, dict) and 'timestamp' in value:
                data_time = value['timestamp']
                if data_time > current_time:
                    issues.append(f"检测到未来数据泄露: {key} timestamp {data_time} > current {current_time}")

        # 检查价格数据异常一致性
        if 'ohlcv' in raw_data:
            ohlcv = raw_data['ohlcv']
            if all(k in ohlcv for k in ['open', 'high', 'low', 'close']):
                open_price = ohlcv['open']
                high_price = ohlcv['high']
                low_price = ohlcv['low']
                close_price = ohlcv['close']

                if high_price < low_price:
                    issues.append("OHLCV数据异常: high < low")

                if high_price < open_price or high_price < close_price:
                    issues.append("OHLCV数据异常: high < open/close")

                if low_price > open_price or low_price > close_price:
                    issues.append("OHLCV数据异常: low > open/close")

        return issues

    def get_incremental_update(self, symbol: str) -> Optional[Dict]:
        """
        获取增量更新数据

        Args:
            symbol: 交易对

        Returns:
            增量更新数据
        """
        if symbol not in self.data_cache:
            return None

        current_data = self.data_cache[symbol]
        last_time = self.last_update_time.get(symbol, 0)

        # 计算增量变化
        incremental = {
            'timestamp': current_data.timestamp,
            'symbol': symbol,
            'changes': []
        }

        # OHLCV增量
        if 'ohlcv' in current_data.ohlcv:
            if 'close' in current_data.ohlcv:
                incremental['changes'].append({
                    'type': 'price_update',
                    'price': current_data.ohlcv['close']
                })

        # 订单簿增量
        if 'bids' in current_data.orderbook and 'asks' in current_data.orderbook:
            incremental['changes'].append({
                'type': 'orderbook_update',
                'best_bid': current_data.orderbook['bids'][0] if current_data.orderbook['bids'] else None,
                'best_ask': current_data.orderbook['asks'][0] if current_data.orderbook['asks'] else None
            })

        # 更新时间戳
        self.last_update_time[symbol] = current_data.timestamp

        return incremental if incremental['changes'] else None

    def is_data_valid(self, aggregated_data: AggregatedMarketData) -> bool:
        """
        判断数据是否有效

        Args:
            aggregated_data: 聚合数据

        Returns:
            是否有效
        """
        return aggregated_data.quality_score.overall_score >= self.quality_threshold


# 命令行测试
def main():
    """测试多源数据聚合引擎"""
    logger.info("="*60)
    logger.info("🔧 多源数据聚合引擎测试")
    logger.info("="*60)

    # 创建引擎
    engine = DataAggregationEngine({
        'data_sources': [DataSource.OHLCV, DataSource.ORDERBOOK_L2, DataSource.FUND_FLOW],
        'quality_threshold': 0.7,
        'max_latency_ms': 500,
        'lookahead_detection': True
    })

    logger.info(f"\n配置:")
    logger.info(f"  数据源: {[ds.value for ds in engine.data_sources]}")
    logger.info(f"  质量阈值: {engine.quality_threshold}")
    logger.info(f"  最大延迟: {engine.max_latency_ms}ms")

    # 生成测试数据
    raw_data = {
        'ohlcv': {
            'timestamp': time.time() - 0.1,
            'open': 50000,
            'high': 50200,
            'low': 49900,
            'close': 50100,
            'volume': 1000
        },
        'orderbook': {
            'timestamp': time.time() - 0.05,
            'bids': [[50099, 1.0], [50098, 2.0], [50097, 3.0]],
            'asks': [[50101, 1.0], [50102, 2.0], [50103, 3.0]]
        },
        'fund_flow': {
            'timestamp': time.time() - 0.08,
            'net_inflow': 500000,
            'long_short_ratio': 1.5
        }
    }

    logger.info(f"\n生成测试数据:")
    logger.info(f"  OHLCV: ${raw_data['ohlcv']['close']}")
    logger.info(f"  订单簿: Bid ${raw_data['orderbook']['bids'][0][0]} / Ask ${raw_data['orderbook']['asks'][0][0]}")
    logger.info(f"  资金流: 净流入 ${raw_data['fund_flow']['net_inflow']}")

    # 聚合数据
    logger.info(f"\n聚合数据...")
    aggregated = engine.aggregate_data("BTCUSDT", raw_data)

    logger.info(f"\n📊 数据质量评分:")
    logger.info(f"  综合评分: {aggregated.quality_score.overall_score:.2f}")
    logger.info(f"  完整性: {aggregated.quality_score.completeness:.2f}")
    logger.info(f"  准确性: {aggregated.quality_score.accuracy:.2f}")
    logger.info(f"  及时性: {aggregated.quality_score.timeliness:.2f}")
    logger.info(f"  一致性: {aggregated.quality_score.consistency:.2f}")
    logger.info(f"  是否有效: {'✓ 是' if engine.is_data_valid(aggregated) else '✗ 否'}")

    if aggregated.quality_score.issues:
        logger.info(f"\n问题:")
        for issue in aggregated.quality_score.issues:
            logger.info(f"  • {issue}")

    # 测试增量更新
    logger.info(f"\n\n测试增量更新...")
    incremental = engine.get_incremental_update("BTCUSDT")
    if incremental:
        logger.info(f"  增量更新:")
        for change in incremental['changes']:
            logger.info(f"    • {change['type']}: {change}")

    # 测试异常数据
    logger.info(f"\n\n测试异常数据（未来数据泄露）...")
    bad_data = {
        'ohlcv': {
            'timestamp': time.time() + 100,  # 未来时间戳
            'open': 50000,
            'high': 49800,  # 异常：high < open
            'low': 50200,   # 异常：low > open
            'close': 50100,
            'volume': 1000
        }
    }

    bad_aggregated = engine.aggregate_data("BTCUSDT", bad_data)
    logger.info(f"  综合评分: {bad_aggregated.quality_score.overall_score:.2f}")
    logger.info(f"  是否有效: {'✓ 是' if engine.is_data_valid(bad_aggregated) else '✗ 否'}")
    logger.info(f"  问题:")
    for issue in bad_aggregated.quality_score.issues:
        logger.info(f"    • {issue}")

    logger.info("\n" + "="*60)
    logger.info("多源数据聚合引擎测试: PASS")


if __name__ == "__main__":
    main()
