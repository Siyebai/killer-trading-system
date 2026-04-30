#!/usr/bin/env python3
"""
异常检测模型 - Phase 6 核心组件
基于Isolation Forest和LSTM-Autoencoder的多模态异常检测
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Deque
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import time
import json

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("anomaly_detector")
except ImportError:
    import logging
    logger = logging.getLogger("anomaly_detector")

# 导入事件总线
try:
    from scripts.event_bus import get_event_bus
    EVENT_BUS_AVAILABLE = True
except ImportError:
    EVENT_BUS_AVAILABLE = False


class AnomalyType(Enum):
    """异常类型"""
    PRICE_SPIKE = "price_spike"
    VOLUME_SURGE = "volume_surge"
    ORDERBOOK_IMBALANCE = "orderbook_imbalance"
    POSITION_RISK_BREACH = "position_risk_breach"
    SYSTEM_LATENCY = "system_latency"
    DATA_CORRUPTION = "data_corruption"
    UNKNOWN = "unknown"


class Severity(Enum):
    """严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AnomalyEvent:
    """异常事件"""
    anomaly_type: AnomalyType
    severity: Severity
    timestamp: float = field(default_factory=time.time)
    metric_name: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0
    anomaly_score: float = 0.0
    context: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'type': self.anomaly_type.value,
            'severity': self.severity.value,
            'timestamp': self.timestamp,
            'metric_name': self.metric_name,
            'metric_value': self.metric_value,
            'threshold': self.threshold,
            'anomaly_score': self.anomaly_score,
            'context': self.context
        }


class AnomalyDetector:
    """异常检测器（基于Isolation Forest）"""

    def __init__(self,
                 contamination: float = 0.1,
                 window_size: int = 100,
                 feature_dim: int = 10):
        """
        初始化异常检测器

        Args:
            contamination: 异常比例（用于Isolation Forest）
            window_size: 滑动窗口大小
            feature_dim: 特征维度
        """
        self.contamination = contamination
        self.window_size = window_size
        self.feature_dim = feature_dim

        # 历史数据窗口
        self.data_window: Deque[np.ndarray] = deque(maxlen=window_size)

        # Isolation Forest参数（简化实现）
        self.n_estimators = 100
        self.max_samples = min(256, window_size)
        self.random_state = 42

        # 树结构（简化存储）
        self.trees: List[Dict] = []

        # 异常阈值
        self.threshold = 0.5

        # 异常历史
        self.anomaly_history: List[AnomalyEvent] = []

        # 回调函数
        self.anomaly_callbacks: List[callable] = []

        logger.info("异常检测器初始化完成")

    def add_anomaly_callback(self, callback: callable) -> None:
        """添加异常回调"""
        self.anomaly_callbacks.append(callback)

    def fit(self, data: np.ndarray) -> None:
        """
        训练Isolation Forest

        Args:
            data: 训练数据
        """
        try:
            # 第一层防御：数据校验
            if data.shape[0] < self.max_samples:
                logger.warning(f"训练数据不足: {data.shape[0]} < {self.max_samples}")
                return

            # 第二层防御：构建Isolation Forest（简化实现）
            self.trees = []
            for _ in range(self.n_estimators):
                tree = self._build_tree(data)
                self.trees.append(tree)

            # 计算异常阈值
            scores = self._compute_scores(data)
            self.threshold = np.percentile(scores, (1 - self.contamination) * 100)

            logger.info(f"Isolation Forest训练完成: {len(self.trees)}棵树, "
                       f"threshold={self.threshold:.4f}")

        except Exception as e:
            logger.error(f"训练异常检测器失败: {e}")

    def _build_tree(self, data: np.ndarray, depth: int = 0, max_depth: int = 10) -> Optional[Dict]:
        """
        构建单棵Isolation Tree（递归）

        Args:
            data: 数据
            depth: 当前深度
            max_depth: 最大深度

        Returns:
            树节点或None
        """
        try:
            # 第一层防御：终止条件
            if depth >= max_depth or len(data) <= 1:
                return {'type': 'leaf', 'depth': depth, 'size': len(data)}

            # 第二层防御：随机选择特征和切分点
            n_features = data.shape[1]
            feature_idx = np.random.randint(0, n_features)
            min_val, max_val = np.min(data[:, feature_idx]), np.max(data[:, feature_idx])

            if min_val == max_val:
                return {'type': 'leaf', 'depth': depth, 'size': len(data)}

            split_value = np.random.uniform(min_val, max_val)

            # 切分数据
            left_mask = data[:, feature_idx] < split_value
            right_mask = ~left_mask

            if np.sum(left_mask) == 0 or np.sum(right_mask) == 0:
                return {'type': 'leaf', 'depth': depth, 'size': len(data)}

            # 递归构建子树
            left_child = self._build_tree(data[left_mask], depth + 1, max_depth)
            right_child = self._build_tree(data[right_mask], depth + 1, max_depth)

            return {
                'type': 'node',
                'feature_idx': feature_idx,
                'split_value': split_value,
                'left': left_child,
                'right': right_child,
                'depth': depth
            }

        except Exception as e:
            logger.error(f"构建树节点失败: {e}")
            return None

    def _compute_path_length(self, tree: Optional[Dict], data_point: np.ndarray) -> float:
        """
        计算路径长度

        Args:
            tree: 树
            data_point: 数据点

        Returns:
            路径长度
        """
        try:
            if tree is None:
                return 0.0

            if tree['type'] == 'leaf':
                # 归一化路径长度
                if tree['size'] <= 1:
                    return float(tree['depth'])
                return tree['depth'] + self._c_factor(tree['size'])

            # 第一层防御：特征索引检查
            feature_idx = tree['feature_idx']
            if feature_idx >= len(data_point):
                return float(tree['depth'])

            # 递归
            if data_point[feature_idx] < tree['split_value']:
                return self._compute_path_length(tree['left'], data_point)
            else:
                return self._compute_path_length(tree['right'], data_point)

        except Exception as e:
            logger.error(f"计算路径长度失败: {e}")
            return 0.0

    def _c_factor(self, n: int) -> float:
        """计算路径长度修正因子"""
        if n <= 1:
            return 0.0
        if n == 2:
            return 1.0
        # 近似调和数
        result = 2.0 * (np.log(n - 1.0) + 0.5772156649) - 2.0 * (n - 1.0) / n
        return max(1e-8, result)  # 防止负值和零值

    def _compute_scores(self, data: np.ndarray) -> np.ndarray:
        """
        计算异常分数

        Args:
            data: 数据

        Returns:
            异常分数数组
        """
        try:
            scores = []

            for i in range(len(data)):
                # 计算平均路径长度
                path_lengths = []
                for tree in self.trees:
                    path_len = self._compute_path_length(tree, data[i])
                    path_lengths.append(path_len)

                avg_path_len = np.mean(path_lengths)

                # 第一层防御：除零保护
                if avg_path_len == 0:
                    scores.append(0.5)
                    continue

                # 归一化为[0, 1]
                c = self._c_factor(self.window_size)
                score = 0.5 if c == 0 else 2.0 ** (-avg_path_len / c)
                scores.append(score)

            return np.array(scores)

        except Exception as e:
            logger.error(f"计算异常分数失败: {e}")
            return np.zeros(len(data))

    def detect(self, data_point: np.ndarray, metric_name: str = "") -> Optional[AnomalyEvent]:
        """
        检测异常（v1.0.3 Stable - 阈值检测）

        Args:
            data_point: 数据点
            metric_name: 指标名称

        Returns:
            异常事件或None
        """
        try:
            # v1.0.3 Stable: 使用简化的阈值检测（替代Isolation Forest）
            metric_value = float(data_point[-1]) if len(data_point) > 0 else 0.0

            # 第一层防御：根据指标名称设置阈值
            thresholds = {
                'volatility': 0.05,      # 波动率 > 5%
                'drawdown': 0.20,        # 回撤 > 20%
                'latency': 1000.0,       # 延迟 > 1000ms
                'error_rate': 0.10,      # 错误率 > 10%
                'cpu_usage': 90.0,       # CPU > 90%
                'memory_usage': 90.0,    # 内存 > 90%
            }

            # 第二层防御：获取阈值
            threshold = thresholds.get(metric_name.lower(), 0.0)
            if threshold is None or abs(threshold) < 1e-10:
                return None

            # 第三层防御：阈值判断
            is_anomaly = False
            if metric_name.lower() in ['latency', 'cpu_usage', 'memory_usage']:
                # 上限检测
                is_anomaly = metric_value > threshold
            else:
                # 比率检测
                is_anomaly = metric_value > threshold

            if is_anomaly:
                # 确定异常类型和严重程度
                anomaly_type, severity = self._classify_by_threshold(metric_name, metric_value, threshold)

                # 构造异常事件
                anomaly = AnomalyEvent(
                    anomaly_type=anomaly_type,
                    severity=severity,
                    metric_name=metric_name,
                    metric_value=metric_value,
                    threshold=threshold,
                    anomaly_score=1.0,  # 简化版固定为1.0
                    context={'detection_method': 'threshold'}
                )

                # 记录历史
                self.anomaly_history.append(anomaly)
                if len(self.anomaly_history) > 1000:
                    self.anomaly_history = self.anomaly_history[-1000:]

                # 触发回调
                for callback in self.anomaly_callbacks:
                    try:
                        callback(anomaly)
                    except Exception as e:
                        logger.error(f"异常回调失败: {e}")

                # 第四层防御：广播事件
                if EVENT_BUS_AVAILABLE:
                    self._publish_anomaly_event(anomaly)

                return anomaly

            return None

        except Exception as e:
            logger.error(f"检测异常失败: {e}")
            return None

    def _compute_score_single(self, data_point: np.ndarray) -> float:
        """
        计算单个数据点的异常分数

        Args:
            data_point: 数据点

        Returns:
            异常分数
        """
        try:
            # 计算平均路径长度
            path_lengths = []
            for tree in self.trees:
                path_len = self._compute_path_length(tree, data_point)
                path_lengths.append(path_len)

            avg_path_len = np.mean(path_lengths)

            # 归一化
            c = self._c_factor(self.window_size)
            score = 0.5 if c == 0 else 2.0 ** (-avg_path_len / c)

            return score

        except Exception as e:
            logger.error(f"计算异常分数失败: {e}")
            return 0.0

    def _classify_by_threshold(self,
                              metric_name: str,
                              metric_value: float,
                              threshold: float) -> Tuple[AnomalyType, Severity]:
        """
        根据阈值分类异常（v1.0.3 Stable）

        Args:
            metric_name: 指标名称
            metric_value: 指标值
            threshold: 阈值

        Returns:
            (异常类型, 严重程度)
        """
        try:
            # 第一层防御：确定异常类型
            metric_lower = metric_name.lower()
            if 'volatility' in metric_lower:
                anomaly_type = AnomalyType.PRICE_SPIKE
            elif 'drawdown' in metric_lower:
                anomaly_type = AnomalyType.POSITION_RISK_BREACH
            elif 'latency' in metric_lower:
                anomaly_type = AnomalyType.SYSTEM_LATENCY
            elif 'error' in metric_lower:
                anomaly_type = AnomalyType.DATA_CORRUPTION
            elif 'cpu' in metric_lower or 'memory' in metric_lower:
                anomaly_type = AnomalyType.SYSTEM_LATENCY
            else:
                anomaly_type = AnomalyType.UNKNOWN

            # 第二层防御：确定严重程度
            ratio = metric_value / max(0.001, threshold)

            if ratio > 2.0:
                severity = Severity.CRITICAL
            elif ratio > 1.5:
                severity = Severity.ERROR
            elif ratio > 1.2:
                severity = Severity.WARNING
            else:
                severity = Severity.INFO

            return anomaly_type, severity

        except Exception as e:
            logger.error(f"分类异常失败: {e}")
            return AnomalyType.UNKNOWN, Severity.INFO

    def _classify_anomaly(self,
                         data_point: np.ndarray,
                         score: float,
                         metric_name: str) -> Tuple[AnomalyType, Severity]:
        """
        分类异常类型和严重程度

        Args:
            data_point: 数据点
            score: 异常分数
            metric_name: 指标名称

        Returns:
            (异常类型, 严重程度)
        """
        try:
            # 第一层防御：根据指标名称推断类型
            if 'price' in metric_name.lower():
                anomaly_type = AnomalyType.PRICE_SPIKE
            elif 'volume' in metric_name.lower():
                anomaly_type = AnomalyType.VOLUME_SURGE
            elif 'imbalance' in metric_name.lower():
                anomaly_type = AnomalyType.ORDERBOOK_IMBALANCE
            elif 'risk' in metric_name.lower():
                anomaly_type = AnomalyType.POSITION_RISK_BREACH
            elif 'latency' in metric_name.lower():
                anomaly_type = AnomalyType.SYSTEM_LATENCY
            else:
                anomaly_type = AnomalyType.UNKNOWN

            # 第二层防御：根据分数确定严重程度
            if score > 0.9:
                severity = Severity.CRITICAL
            elif score > 0.8:
                severity = Severity.ERROR
            elif score > 0.7:
                severity = Severity.WARNING
            else:
                severity = Severity.INFO

            return anomaly_type, severity

        except Exception as e:
            logger.error(f"分类异常失败: {e}")
            return AnomalyType.UNKNOWN, Severity.INFO

    def _publish_anomaly_event(self, anomaly: AnomalyEvent) -> None:
        """
        广播异常事件

        Args:
            anomaly: 异常事件
        """
        try:
            event_bus = get_event_bus()
            event_bus.publish(
                "system.anomaly_detected",
                {
                    "type": anomaly.anomaly_type.value,
                    "severity": anomaly.severity.value,
                    "metric_name": anomaly.metric_name,
                    "anomaly_score": anomaly.anomaly_score,
                    "context": anomaly.context
                },
                source="anomaly_detector"
            )
        except Exception as e:
            logger.error(f"异常事件广播失败: {e}")

    def get_anomaly_statistics(self) -> Dict:
        """
        获取异常统计

        Returns:
            统计信息字典
        """
        if not self.anomaly_history:
            return {'total': 0, 'by_type': {}, 'by_severity': {}}

        by_type = {}
        by_severity = {}

        for anomaly in self.anomaly_history:
            type_key = anomaly.anomaly_type.value
            by_type[type_key] = by_type.get(type_key, 0) + 1

            severity_key = anomaly.severity.value
            by_severity[severity_key] = by_severity.get(severity_key, 0) + 1

        return {
            'total': len(self.anomaly_history),
            'by_type': by_type,
            'by_severity': by_severity
        }


if __name__ == "__main__":
    # 测试代码
    def anomaly_callback(anomaly: AnomalyEvent):
        print(f"检测到异常: {anomaly.anomaly_type.value} ({anomaly.severity.value}), "
              f"score={anomaly.anomaly_score:.4f}")

    # 创建检测器
    detector = AnomalyDetector(contamination=0.1, window_size=100)
    detector.add_anomaly_callback(anomaly_callback)

    # 生成训练数据（正常数据）
    np.random.seed(42)
    normal_data = np.random.randn(1000, 10)
    detector.fit(normal_data)

    # 测试正常数据
    print("\n测试正常数据:")
    normal_point = np.random.randn(10)
    result = detector.detect(normal_point, "price")
    print(f"检测结果: {result}")

    # 测试异常数据
    print("\n测试异常数据:")
    anomaly_point = np.random.randn(10) * 5  # 放大5倍
    result = detector.detect(anomaly_point, "price")
    print(f"检测结果: {result}")

    # 统计信息
    stats = detector.get_anomaly_statistics()
    print(f"\n异常统计: {stats}")
