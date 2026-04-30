# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("orderbook_analyzer")
except ImportError:
    import logging
    logger = logging.getLogger("orderbook_analyzer")
"""
订单簿斜率与冰山订单检测 - 杀手锏交易系统V4.5
市场微观结构深度挖掘，捕捉机构吸筹/派发痕迹，规避假突破
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import time


class IcebergType(Enum):
    """冰山订单类型"""
    BID_ICEBERG = "BID_ICEBERG"  # 买单冰山
    ASK_ICEBERG = "ASK_ICEBERG"  # 卖单冰山


@dataclass
class OrderbookAnalysis:
    """订单簿分析结果"""
    imbalance_slope: float  # 不平衡斜率
    bid_slope: float  # 买单斜率
    ask_slope: float  # 卖单斜率
    iceberg_detected: bool
    iceberg_type: Optional[IcebergType]
    iceberg_price: Optional[float]
    iceberg_strength: float  # 冰山订单强度 0-1
    absorption_detected: bool  # 吸筹/派发检测
    reasons: List[str]


class OrderbookAnalyzer:
    """订单簿分析器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化订单簿分析器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 配置参数
        self.depth_levels = self.config.get('depth_levels', 10)
        self.slope_threshold = self.config.get('slope_threshold', 0.3)
        self.iceberg_detection_window = self.config.get('iceberg_detection_window', 30)
        self.min_iceberg_strength = self.config.get('min_iceberg_strength', 0.6)

        # 历史订单簿（用于检测冰山订单）
        self.orderbook_history: List[Dict] = []
        self.orderbook_timestamps: List[float] = []

    def calculate_slope(self, prices: List[float], volumes: List[float]) -> float:
        """
        计算订单簿斜率

        Args:
            prices: 价格列表
            volumes: 成交量列表

        Returns:
            斜率
        """
        if len(prices) < 2 or len(volumes) < 2:
            return 0.0

        # 计算价格变化
        price_changes = np.diff(prices)
        volume_changes = np.diff(volumes)

        # 计算斜率（成交量变化/价格变化）
        slopes = []
        for i in range(len(price_changes)):
            if abs(price_changes[i]) > 1e-6:
                slope = volume_changes[i] / price_changes[i]
                slopes.append(slope)

        return np.mean(slopes) if slopes else 0.0

    def analyze_orderbook(self, bids: List[Tuple], asks: List[Tuple]) -> OrderbookAnalysis:
        """
        分析订单簿

        Args:
            bids: 买单列表 [(price, size), ...]
            asks: 卖单列表 [(price, size), ...]

        Returns:
            订单簿分析结果
        """
        reasons = []

        # 提取价格和成交量
        bid_prices = [b[0] for b in bids[:self.depth_levels]]
        bid_volumes = [b[1] for b in bids[:self.depth_levels]]
        ask_prices = [a[0] for a in asks[:self.depth_levels]]
        ask_volumes = [a[1] for a in asks[:self.depth_levels]]

        # 计算斜率
        bid_slope = self.calculate_slope(bid_prices, bid_volumes)
        ask_slope = self.calculate_slope(ask_prices, ask_volumes)

        # 不平衡斜率
        imbalance_slope = bid_slope - ask_slope

        if imbalance_slope > self.slope_threshold:
            reasons.append(f"买单斜率({bid_slope:.2f})明显高于卖单斜率({ask_slope:.2f})，买方力量强")
        elif imbalance_slope < -self.slope_threshold:
            reasons.append(f"卖单斜率({ask_slope:.2f})明显高于买单斜率({bid_slope:.2f})，卖方压力大")
        else:
            reasons.append(f"买卖斜率平衡，bid_slope={bid_slope:.2f}, ask_slope={ask_slope:.2f}")

        # 检测冰山订单
        iceberg_detected, iceberg_type, iceberg_price, iceberg_strength = self._detect_iceberg(bids, asks)

        if iceberg_detected:
            reasons.append(f"检测到冰山订单: {iceberg_type.value} @ ${iceberg_price:.2f}, 强度{iceberg_strength:.2f}")

        # 检测吸筹/派发
        absorption_detected = self._detect_absorption(bid_slope, ask_slope, imbalance_slope)

        if absorption_detected == "ACCUMULATION":
            reasons.append("检测到吸筹模式：买单斜率陡峭，可能机构在支撑位吸筹")
        elif absorption_detected == "DISTRIBUTION":
            reasons.append("检测到派发模式：卖单斜率陡峭，可能机构在阻力位出货")

        # 保存历史
        self._save_history(bids, asks)

        return OrderbookAnalysis(
            imbalance_slope=imbalance_slope,
            bid_slope=bid_slope,
            ask_slope=ask_slope,
            iceberg_detected=iceberg_detected,
            iceberg_type=iceberg_type,
            iceberg_price=iceberg_price,
            iceberg_strength=iceberg_strength,
            absorption_detected=absorption_detected != "NEUTRAL",
            reasons=reasons
        )

    def _detect_iceberg(self, bids: List[Tuple], asks: List[Tuple]) -> Tuple[bool, Optional[IcebergType], Optional[float], float]:
        """
        检测冰山订单

        Args:
            bids: 买单列表
            asks: 卖单列表

        Returns:
            (是否检测到, 冰山类型, 冰山价格, 强度)
        """
        if len(self.orderbook_history) < 5:
            return False, None, None, 0.0

        current_time = time.time()

        # 检测买单冰山
        for i, (price, size) in enumerate(bids[:5]):
            # 检查该价格水平是否有反复补充行为
            refill_count = 0
            total_refill_size = 0

            for history in self.orderbook_history[-self.iceberg_detection_window:]:
                history_bids = history.get('bids', [])
                for h_price, h_size in history_bids:
                    if abs(h_price - price) < 0.01:  # 同一价格水平
                        if h_size > 0:
                            refill_count += 1
                            total_refill_size += h_size

            # 如果补充次数多，可能是冰山订单
            if refill_count >= 3:
                strength = min(1.0, refill_count / 10.0)
                return True, IcebergType.BID_ICEBERG, price, strength

        # 检测卖单冰山
        for i, (price, size) in enumerate(asks[:5]):
            refill_count = 0
            total_refill_size = 0

            for history in self.orderbook_history[-self.iceberg_detection_window:]:
                history_asks = history.get('asks', [])
                for h_price, h_size in history_asks:
                    if abs(h_price - price) < 0.01:
                        if h_size > 0:
                            refill_count += 1
                            total_refill_size += h_size

            if refill_count >= 3:
                strength = min(1.0, refill_count / 10.0)
                return True, IcebergType.ASK_ICEBERG, price, strength

        return False, None, None, 0.0

    def _detect_absorption(self, bid_slope: float, ask_slope: float, imbalance_slope: float) -> str:
        """
        检测吸筹/派发

        Args:
            bid_slope: 买单斜率
            ask_slope: 卖单斜率
            imbalance_slope: 不平衡斜率

        Returns:
            ACCUMULATION/DISTRIBUTION/NEUTRAL
        """
        # 吸筹：买单斜率陡峭，不平衡为正
        if bid_slope > ask_slope * 2 and imbalance_slope > self.slope_threshold:
            return "ACCUMULATION"

        # 派发：卖单斜率陡峭，不平衡为负
        if ask_slope > bid_slope * 2 and imbalance_slope < -self.slope_threshold:
            return "DISTRIBUTION"

        return "NEUTRAL"

    def _save_history(self, bids: List[Tuple], asks: List[Tuple]):
        """
        保存订单簿历史

        Args:
            bids: 买单列表
            asks: 卖单列表
        """
        self.orderbook_history.append({
            'bids': bids,
            'asks': asks,
            'timestamp': time.time()
        })
        self.orderbook_timestamps.append(time.time())

        # 限制历史长度
        max_history = 100
        if len(self.orderbook_history) > max_history:
            self.orderbook_history = self.orderbook_history[-max_history:]
            self.orderbook_timestamps = self.orderbook_timestamps[-max_history:]

    def get_accumulated_absorption(self, window_minutes: int = 5) -> Dict:
        """
        获取累积吸筹/派发

        Args:
            window_minutes: 时间窗口（分钟）

        Returns:
            累积分析结果
        """
        current_time = time.time()
        cutoff_time = current_time - window_minutes * 60

        recent_history = [
            h for h in self.orderbook_history
            if h['timestamp'] >= cutoff_time
        ]

        if not recent_history:
            return {
                'accumulation_score': 0.0,
                'distribution_score': 0.0,
                'net_score': 0.0
            }

        # 计算累积吸筹/派发
        accumulation_signals = 0
        distribution_signals = 0

        for h in recent_history:
            bids = h.get('bids', [])
            asks = h.get('asks', [])

            if len(bids) >= 2 and len(asks) >= 2:
                # 计算斜率
                bid_slope = self.calculate_slope([b[0] for b in bids[:3]], [b[1] for b in bids[:3]])
                ask_slope = self.calculate_slope([a[0] for a in asks[:3]], [a[1] for a in asks[:3]])

                if bid_slope > ask_slope * 1.5:
                    accumulation_signals += 1
                elif ask_slope > bid_slope * 1.5:
                    distribution_signals += 1

        total_signals = accumulation_signals + distribution_signals
        accumulation_score = accumulation_signals / total_signals if total_signals > 0 else 0
        distribution_score = distribution_signals / total_signals if total_signals > 0 else 0
        net_score = accumulation_score - distribution_score

        return {
            'accumulation_score': accumulation_score,
            'distribution_score': distribution_score,
            'net_score': net_score,
            'sample_count': total_signals
        }


# 命令行测试
def main():
    """测试订单簿分析器"""
    logger.info("="*60)
    logger.info("📊 订单簿斜率与冰山订单检测测试")
    logger.info("="*60)

    # 创建分析器
    analyzer = OrderbookAnalyzer({
        'depth_levels': 10,
        'slope_threshold': 0.3,
        'iceberg_detection_window': 30
    })

    logger.info(f"\n配置:")
    logger.info(f"  深度层级: {analyzer.depth_levels}")
    logger.info(f"  斜率阈值: {analyzer.slope_threshold}")

    # 测试1：正常订单簿
    logger.info(f"\n测试1: 正常订单簿")
    bids = [(50000 - i * 10, 1.0 + i * 0.2) for i in range(10)]
    asks = [(50000 + i * 10, 1.0 + i * 0.2) for i in range(10)]

    result1 = analyzer.analyze_orderbook(bids, asks)
    logger.info(f"  买单斜率: {result1.bid_slope:.2f}")
    logger.info(f"  卖单斜率: {result1.ask_slope:.2f}")
    logger.info(f"  不平衡斜率: {result1.imbalance_slope:.2f}")
    logger.info(f"  冰山订单: {'是' if result1.iceberg_detected else '否'}")
    logger.info(f"  原因: {result1.reasons}")

    # 测试2：买方力量强（斜率陡峭）
    logger.info(f"\n测试2: 买方力量强")
    bids_strong = [(50000 - i * 5, 5.0 + i * 2.0) for i in range(10)]  # 买单量大且递增快
    asks_weak = [(50000 + i * 10, 1.0 + i * 0.1) for i in range(10)]

    result2 = analyzer.analyze_orderbook(bids_strong, asks_weak)
    logger.info(f"  不平衡斜率: {result2.imbalance_slope:.2f}")
    logger.info(f"  检测到吸筹: {'是' if result2.absorption_detected else '否'}")
    logger.info(f"  原因: {result2.reasons}")

    # 测试3：模拟冰山订单（反复补充）
    logger.info(f"\n测试3: 模拟冰山订单")
    # 模拟多次更新同一价格水平
    iceberg_price = 50000
    for _ in range(15):
        bids_ice = [(iceberg_price - i * 10, 0.5 if i > 0 else 5.0) for i in range(10)]
        asks_ice = [(50000 + i * 10, 1.0) for i in range(10)]
        analyzer.analyze_orderbook(bids_ice, asks_ice)

    result3 = analyzer.analyze_orderbook(bids_ice, asks_ice)
    logger.info(f"  冰山订单检测: {'是' if result3.iceberg_detected else '否'}")
    if result3.iceberg_detected:
        logger.info(f"  冰山类型: {result3.iceberg_type.value}")
        logger.info(f"  冰山价格: ${result3.iceberg_price:.2f}")
        logger.info(f"  冰山强度: {result3.iceberg_strength:.2f}")

    # 测试4：累积吸筹/派发
    logger.info(f"\n测试4: 累积吸筹分析")
    cumulative = analyzer.get_accumulated_absorption(window_minutes=5)
    logger.info(f"  吸筹得分: {cumulative['accumulation_score']:.2f}")
    logger.info(f"  派发得分: {cumulative['distribution_score']:.2f}")
    logger.info(f"  净得分: {cumulative['net_score']:.2f}")
    logger.info(f"  样本数: {cumulative['sample_count']}")

    logger.info("\n" + "="*60)
    logger.info("订单簿斜率与冰山订单检测测试: PASS")


if __name__ == "__main__":
    main()
