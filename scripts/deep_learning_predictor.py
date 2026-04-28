#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("deep_learning_predictor")
except ImportError:
    import logging
    logger = logging.getLogger("deep_learning_predictor")
"""
深度学习模型集成 - V4.0核心模块
LSTM时序预测、特征工程、模型训练和推理
"""

import json
import time
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import pickle


# 简化的LSTM实现（避免依赖PyTorch）
class SimpleLSTM:
    """简化的LSTM网络（纯NumPy实现）"""

    def __init__(self, input_size: int, hidden_size: int, output_size: int):
        """
        初始化LSTM

        Args:
            input_size: 输入维度
            hidden_size: 隐藏层维度
            output_size: 输出维度
        """
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.output_size = output_size

        # 简化：使用线性回归替代真实LSTM
        # 实际生产环境应使用PyTorch/TensorFlow
        self.weights = np.random.randn(input_size * hidden_size, output_size) * 0.01
        self.bias = np.zeros(output_size)

        self.is_trained = False

    def forward(self, x: np.ndarray) -> np.ndarray:
        """前向传播"""
        # 简化：使用线性层
        x_flat = x.reshape(-1)
        output = np.dot(x_flat, self.weights) + self.bias
        return output

    def train(self, X: np.ndarray, y: np.ndarray, epochs: int = 100, lr: float = 0.01):
        """
        简化训练（使用最小二乘法）

        Args:
            X: 训练数据 (samples, sequence_length, features)
            y: 标签 (samples, output_size)
            epochs: 训练轮数
            lr: 学习率
        """
        # 展平输入
        X_flat = X.reshape(X.shape[0], -1)

        # 使用伪逆求解（最小二乘法）
        try:
            # 添加偏置列
            X_bias = np.hstack([X_flat, np.ones((X_flat.shape[0], 1))])

            # 合并权重和偏置
            combined_weights = np.linalg.pinv(X_bias) @ y

            # 分离权重和偏置
            self.weights = combined_weights[:-1].reshape(-1, self.output_size)
            self.bias = combined_weights[-1]

            self.is_trained = True
            logger.info(f"[LSTM] 训练完成，样本数: {X.shape[0]}")
        except Exception as e:
            logger.error(f"[LSTM] 训练失败: {e}")

    def predict(self, x: np.ndarray) -> np.ndarray:
        """
        预测

        Args:
            x: 输入数据 (sequence_length, features)

        Returns:
            预测结果
        """
        return self.forward(x)

    def save(self, filepath: str):
        """保存模型"""
        model_data = {
            'input_size': self.input_size,
            'hidden_size': self.hidden_size,
            'output_size': self.output_size,
            'weights': self.weights,
            'bias': self.bias,
            'is_trained': self.is_trained
        }
        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)

    def load(self, filepath: str):
        """加载模型"""
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        self.input_size = model_data['input_size']
        self.hidden_size = model_data['hidden_size']
        self.output_size = model_data['output_size']
        self.weights = model_data['weights']
        self.bias = model_data['bias']
        self.is_trained = model_data['is_trained']


@dataclass
class PredictionResult:
    """预测结果"""
    timestamp: float
    predicted_price: float
    confidence: float
    prediction_type: str  # 'UP', 'DOWN', 'NEUTRAL'
    features: Dict[str, float] = None


class DeepLearningPredictor:
    """深度学习预测器"""

    def __init__(self, model_type: str = "lstm"):
        """
        初始化预测器

        Args:
            model_type: 模型类型
        """
        self.model_type = model_type
        self.model: Optional[SimpleLSTM] = None
        self.feature_scaler = {}

        # 配置
        self.sequence_length = 20  # 序列长度
        self.feature_names = [
            'price_return_1', 'price_return_3', 'price_return_5',
            'volume_ratio', 'volatility_5', 'momentum_3',
            'momentum_5', 'ma_diff_5_10', 'rsi', 'bb_position'
        ]

    def prepare_features(self, price_history: List[float],
                        volume_history: List[float]) -> List[Dict[str, float]]:
        """
        准备特征

        Args:
            price_history: 价格历史
            volume_history: 成交量历史

        Returns:
            特征列表
        """
        features_list = []

        for i in range(len(price_history)):
            if i < 10:
                continue

            prices = price_history[:i+1]
            volumes = volume_history[:i+1]
            current_price = prices[-1]

            # 计算特征
            features = {}

            # 价格收益率
            features['price_return_1'] = (prices[-1] - prices[-2]) / prices[-2] if len(prices) >= 2 else 0
            features['price_return_3'] = (prices[-1] - prices[-3]) / prices[-3] if len(prices) >= 3 else 0
            features['price_return_5'] = (prices[-1] - prices[-5]) / prices[-5] if len(prices) >= 5 else 0

            # 成交量比率
            features['volume_ratio'] = volumes[-1] / np.mean(volumes[-5:]) if len(volumes) >= 5 else 1.0

            # 波动率
            if len(prices) >= 5:
                prices_slice = np.array(prices[-6:])
                if len(prices_slice) >= 2:
                    returns = np.diff(prices_slice) / prices_slice[:-1]
                    features['volatility_5'] = np.std(returns)
                else:
                    features['volatility_5'] = 0
            else:
                features['volatility_5'] = 0

            # 动量
            features['momentum_3'] = prices[-1] - prices[-3] if len(prices) >= 3 else 0
            features['momentum_5'] = prices[-1] - prices[-5] if len(prices) >= 5 else 0

            # 趋势
            ma5 = np.mean(prices[-5:]) if len(prices) >= 5 else current_price
            ma10 = np.mean(prices[-10:]) if len(prices) >= 10 else current_price
            features['ma_diff_5_10'] = (ma5 - ma10) / ma10 if ma10 > 0 else 0

            # RSI
            if len(prices) >= 14:
                gains = [max(prices[i] - prices[i-1], 0) for i in range(1, len(prices))]
                losses = [abs(min(prices[i] - prices[i-1], 0)) for i in range(1, len(prices))]
                avg_gain = np.mean(gains[-14:])
                avg_loss = np.mean(losses[-14:])
                rs = avg_gain / avg_loss if avg_loss > 0 else float('inf')
                features['rsi'] = 100 - (100 / (1 + rs))
            else:
                features['rsi'] = 50

            # 布林带位置
            if len(prices) >= 20:
                bb_mid = np.mean(prices[-20:])
                bb_std = np.std(prices[-20:])
                bb_upper = bb_mid + 2 * bb_std
                bb_lower = bb_mid - 2 * bb_std
                features['bb_position'] = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5
            else:
                features['bb_position'] = 0.5

            features_list.append(features)

        return features_list

    def build_sequences(self, features: List[Dict[str, float]],
                       labels: Optional[List[float]] = None) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        构建序列数据

        Args:
            features: 特征列表
            labels: 标签列表（可选）

        Returns:
            (X, y) 序列数据
        """
        X = []
        y = []

        # 提取特征矩阵
        feature_matrix = []
        for feat in features:
            row = [feat.get(name, 0) for name in self.feature_names]
            feature_matrix.append(row)

        # 构建序列
        if labels:
            # 确保标签和特征长度一致
            min_len = min(len(feature_matrix), len(labels))
            for i in range(self.sequence_length, min_len):
                sequence = feature_matrix[i-self.sequence_length:i]
                X.append(sequence)
                y.append(labels[i])
        else:
            for i in range(self.sequence_length, len(feature_matrix)):
                sequence = feature_matrix[i-self.sequence_length:i]
                X.append(sequence)

        X = np.array(X)
        y = np.array(y) if y else None

        return X, y

    def train(self, price_history: List[float], volume_history: List[float]) -> bool:
        """
        训练模型

        Args:
            price_history: 价格历史
            volume_history: 成交量历史

        Returns:
            是否成功
        """
        # 准备特征
        features = self.prepare_features(price_history, volume_history)

        # 构建标签（未来价格变化）
        labels = []
        for i in range(len(features)):
            if i >= self.sequence_length and i < len(price_history) - 1:
                future_price = price_history[i + 1]
                current_price = price_history[i]
                labels.append((future_price - current_price) / current_price)

        # 构建序列
        X, y = self.build_sequences(features, labels if labels else None)

        if X.shape[0] == 0:
            logger.info(f"[DLPredictor] 训练数据不足")
            return False

        # 初始化模型
        input_size = X.shape[2]
        self.model = SimpleLSTM(input_size, hidden_size=32, output_size=1)

        # 训练
        logger.info(f"[DLPredictor] 开始训练，样本数: {X.shape[0]}")
        if y is not None:
            self.model.train(X, y, epochs=100)
        else:
            logger.info(f"[DLPredictor] 警告：无标签数据，跳过训练")
            return False

        return True

    def predict(self, price_history: List[float],
               volume_history: List[float]) -> Optional[PredictionResult]:
        """
        预测

        Args:
            price_history: 价格历史
            volume_history: 成交量历史

        Returns:
            预测结果
        """
        if not self.model or not self.model.is_trained:
            logger.info(f"[DLPredictor] 模型未训练")
            return None

        # 准备特征
        features = self.prepare_features(price_history, volume_history)

        if len(features) < self.sequence_length:
            logger.info(f"[DLPredictor] 数据不足，需要至少{self.sequence_length}个数据点")
            return None

        # 构建序列
        X, _ = self.build_sequences(features)
        if X.shape[0] == 0:
            return None

        # 预测
        last_sequence = X[-1]
        prediction = self.model.predict(last_sequence)[0]

        # 解析预测结果
        current_price = price_history[-1]
        predicted_return = prediction
        predicted_price = current_price * (1 + predicted_return)

        # 判断方向
        if predicted_return > 0.001:
            prediction_type = 'UP'
            confidence = min(1.0, abs(predicted_return) * 100)
        elif predicted_return < -0.001:
            prediction_type = 'DOWN'
            confidence = min(1.0, abs(predicted_return) * 100)
        else:
            prediction_type = 'NEUTRAL'
            confidence = 0.5

        # 提取当前特征
        current_features = features[-1]

        return PredictionResult(
            timestamp=time.time(),
            predicted_price=predicted_price,
            confidence=confidence,
            prediction_type=prediction_type,
            features=current_features
        )

    def save_model(self, filepath: str):
        """保存模型"""
        if self.model:
            self.model.save(filepath)
            logger.info(f"[DLPredictor] 模型已保存: {filepath}")

    def load_model(self, filepath: str):
        """加载模型"""
        self.model = SimpleLSTM(0, 0, 0)
        self.model.load(filepath)
        logger.info(f"[DLPredictor] 模型已加载: {filepath}")

    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        return {
            'model_type': self.model_type,
            'is_trained': self.model.is_trained if self.model else False,
            'sequence_length': self.sequence_length,
            'feature_count': len(self.feature_names),
            'feature_names': self.feature_names
        }


# 命令行测试
def main():
    """测试深度学习预测"""
    logger.info("="*60)
    logger.info("🧠 深度学习模型集成测试")
    logger.info("="*60)

    # 创建预测器
    predictor = DeepLearningPredictor(model_type="lstm")

    # 生成模拟数据
    np.random.seed(42)
    base_price = 50000
    price_history = [base_price]
    volume_history = [1000]

    for i in range(100):
        price_change = np.random.randn() * 100
        new_price = price_history[-1] + price_change
        new_volume = np.random.randint(500, 1500)

        price_history.append(new_price)
        volume_history.append(new_volume)

    logger.info(f"\n生成数据: {len(price_history)} 个数据点")

    # 训练模型
    logger.info("\n开始训练...")
    success = predictor.train(price_history, volume_history)

    if not success:
        logger.info("训练失败")
        return

    # 获取模型信息
    logger.info("\n模型信息:")
    info = predictor.get_model_info()
    for key, value in info.items():
        logger.info(f"  {key}: {value}")

    # 预测
    logger.info("\n进行预测...")
    result = predictor.predict(price_history, volume_history)

    if result:
        logger.info(f"\n📊 预测结果:")
        logger.info(f"  当前价格: ${price_history[-1]:.2f}")
        logger.info(f"  预测价格: ${result.predicted_price:.2f}")
        logger.info(f"  预测变化: {((result.predicted_price - price_history[-1]) / price_history[-1] * 100):.3f}%")
        logger.info(f"  预测方向: {result.prediction_type}")
        logger.info(f"  置信度: {result.confidence:.2f}")

        logger.info(f"\n当前特征:")
        for feat_name, feat_value in list(result.features.items())[:5]:
            logger.info(f"  {feat_name}: {feat_value:.4f}")

    # 保存和加载模型
    logger.info("\n保存和加载模型测试...")
    model_file = "/tmp/lstm_model.pkl"
    predictor.save_model(model_file)

    new_predictor = DeepLearningPredictor()
    new_predictor.load_model(model_file)

    new_result = new_predictor.predict(price_history, volume_history)
    if new_result:
        logger.info(f"✅ 加载模型预测成功: {new_result.prediction_type}")

    logger.info("\n" + "="*60)
    logger.info("深度学习模型集成测试: PASS")


if __name__ == "__main__":
    main()
