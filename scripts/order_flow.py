#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("order_flow")
except ImportError:
    import logging
    logger = logging.getLogger("order_flow")
"""
订单流分析脚本
识别买卖压力和订单流特征
"""

import argparse
import json
import sys
import numpy as np
from collections import deque
from typing import Dict, List


class OrderFlowAnalyzer:
    """订单流分析器"""

    def __init__(self, window_size: int = 50, cvd_window: int = 20):
        """
        初始化订单流分析器

        Args:
            window_size: 交易窗口大小
            cvd_window: CVD（累积成交量差额）窗口大小
        """
        self.window_size = window_size
        self.cvd_window = cvd_window
        self.trades = deque(maxlen=window_size)
        self.cvd = 0.0
        self.cvd_history = deque(maxlen=cvd_window)
        self._cvd_slope_cache = None
        self._cache_timestamp = 0

    def add_trade(self, price: float, volume: float, is_buyer_maker: bool):
        """
        添加一笔交易

        Args:
            price: 成交价格
            volume: 成交量
            is_buyer_maker: 是否为主动卖单
        """
        # 计算CVD增量：主动买入为正，主动卖出为负
        delta = -volume if is_buyer_maker else volume
        self.cvd += delta
        self.cvd_history.append(self.cvd)
        self.trades.append({
            'price': price,
            'volume': volume,
            'delta': delta,
            'is_buyer_maker': is_buyer_maker
        })

    def get_cvd_slope(self) -> float:
        """
        计算CVD斜率，反映买卖力量变化趋势

        Returns:
            CVD斜率
        """
        if len(self.cvd_history) < 5:
            return 0.0

        y = np.array(self.cvd_history, dtype=np.float64)
        x = np.arange(len(y), dtype=np.float64)

        # 线性回归计算斜率
        slope = np.polyfit(x, y, 1)[0]
        return slope

    def get_imbalance(self) -> float:
        """
        计算买卖不平衡度

        Returns:
            不平衡度（-1到1，正值表示买方主导）
        """
        if not self.trades:
            return 0.0

        total_delta = sum(t['delta'] for t in self.trades)
        total_volume = sum(t['volume'] for t in self.trades)

        if total_volume == 0:
            return 0.0

        return total_delta / total_volume

    def get_pressure(self, lookback: int = 10) -> float:
        """
        计算近期买卖压力

        Args:
            lookback: 回看交易数量

        Returns:
            买卖压力（-1到1）
        """
        if len(self.trades) < lookback:
            lookback = len(self.trades)

        recent = list(self.trades)[-lookback:]
        recent_delta = sum(t['delta'] for t in recent)
        recent_volume = sum(t['volume'] for t in recent)

        if recent_volume == 0:
            return 0.0

        return recent_delta / recent_volume

    def get_features(self) -> Dict:
        """
        获取完整的订单流特征

        Returns:
            特征字典
        """
        if len(self.trades) < 10:
            return {
                'imbalance': 0.0,
                'pressure': 0.0,
                'cvd': self.cvd,
                'cvd_slope': 0.0,
                'trade_count': len(self.trades),
                'status': 'insufficient_data'
            }

        return {
            'imbalance': self.get_imbalance(),
            'pressure': self.get_pressure(10),
            'cvd': self.cvd,
            'cvd_slope': self.get_cvd_slope(),
            'trade_count': len(self.trades),
            'status': 'ready'
        }

    def analyze_signal(self, imbalance_threshold: float = 0.3,
                      cvd_trend_threshold: float = 0.2) -> Dict:
        """
        分析交易信号

        Args:
            imbalance_threshold: 不平衡度阈值
            cvd_trend_threshold: CVD趋势阈值

        Returns:
            信号分析结果
        """
        features = self.get_features()

        if features['status'] == 'insufficient_data':
            return {
                'signal': 'hold',
                'strength': 0.0,
                'reason': '数据不足',
                'features': features
            }

        imbalance = features['imbalance']
        cvd_slope = features['cvd_slope']

        # 判断买卖信号
        if imbalance > imbalance_threshold and cvd_slope > cvd_trend_threshold:
            return {
                'signal': 'buy',
                'strength': min(imbalance * 2, 1.0),
                'reason': f'买方主导: 不平衡度={imbalance:.3f}, CVD斜率={cvd_slope:.3f}',
                'features': features
            }
        elif imbalance < -imbalance_threshold and cvd_slope < -cvd_trend_threshold:
            return {
                'signal': 'sell',
                'strength': min(abs(imbalance) * 2, 1.0),
                'reason': f'卖方主导: 不平衡度={imbalance:.3f}, CVD斜率={cvd_slope:.3f}',
                'features': features
            }
        else:
            return {
                'signal': 'hold',
                'strength': 0.0,
                'reason': '买卖力量平衡',
                'features': features
            }


def main():
    parser = argparse.ArgumentParser(description="订单流分析")
    parser.add_argument("--trades", help="交易记录JSON文件路径")
    parser.add_argument("--imbalance_threshold", type=float, default=0.3,
                       help="不平衡度阈值")
    parser.add_argument("--cvd_trend_threshold", type=float, default=0.2,
                       help="CVD趋势阈值")

    args = parser.parse_args()

    try:
        analyzer = OrderFlowAnalyzer(window_size=50, cvd_window=20)

        if args.trades:
            # 从文件加载交易数据
            with open(args.trades, 'r', encoding='utf-8') as f:
                trade_data = json.load(f)

            if not isinstance(trade_data, list):
                logger.info((json.dumps({)
                    "status": "error",
                    "message": "交易数据必须是列表格式"
                }, ensure_ascii=False))
                sys.exit(1)

            for trade in trade_data:
                analyzer.add_trade(
                    price=trade.get('price', 0),
                    volume=trade.get('volume', 0),
                    is_buyer_maker=trade.get('is_buyer_maker', False)
                )
        else:
            # 使用示例数据
            logger.info((json.dumps({)
                "status": "warning",
                "message": "未提供交易数据，使用示例数据"
            }, ensure_ascii=False))

            # 生成示例交易数据
            for i in range(30):
                price = 50000 + np.random.normal(0, 100)
                volume = np.random.uniform(0.5, 5.0)
                is_buyer_maker = i % 3 == 0  # 1/3概率为主动卖单
                analyzer.add_trade(price, volume, is_buyer_maker)

        # 获取特征
        features = analyzer.get_features()

        # 分析信号
        signal = analyzer.analyze_signal(
            imbalance_threshold=args.imbalance_threshold,
            cvd_trend_threshold=args.cvd_trend_threshold
        )

        output = {
            "status": "success",
            "features": features,
            "signal_analysis": signal
        }

        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except FileNotFoundError:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"交易数据文件未找到: {args.trades}"
        }, ensure_ascii=False))
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"JSON解析失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": f"分析失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
