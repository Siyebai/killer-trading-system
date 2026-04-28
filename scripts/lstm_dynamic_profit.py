#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("lstm_dynamic_profit")
except ImportError:
    import logging
    logger = logging.getLogger("lstm_dynamic_profit")
"""
LSTM动态止盈预测模块 - v1.0.3
使用深度学习预测未来N根K线的价格区间，动态调整分批止盈点位
核心策略：LSTM时序预测 + 动态止盈调整
"""

import argparse
import json
import sys
import os
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np

# 尝试导入深度学习库
try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False


class PredictionConfidence(Enum):
    """预测置信度"""
    HIGH = "HIGH"      # 高置信度：使用激进止盈
    MEDIUM = "MEDIUM"  # 中置信度：使用标准止盈
    LOW = "LOW"        # 低置信度：使用保守止盈


@dataclass
class PricePrediction:
    """价格预测"""
    lower_bound: float  # 价格下限
    upper_bound: float  # 价格上限
    expected_price: float  # 预期价格
    confidence: PredictionConfidence  # 置信度
    time_horizon: int  # 预测时间跨度（K线数）


@dataclass
class DynamicProfitTargets:
    """动态止盈目标"""
    level_1_atr: float
    level_1_exit_pct: float
    level_2_atr: float
    level_2_exit_pct: float
    level_3_atr: float
    level_3_exit_pct: float
    trailing_activation_atr: float
    trailing_distance_atr: float


class LSTMDynamicProfitPredictor:
    """LSTM动态止盈预测器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化LSTM动态止盈预测器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 模型配置
        self.model_path = self.config.get('model_path', None)
        self.use_pretrained = self.config.get('use_pretrained', False)
        self.sequence_length = self.config.get('sequence_length', 60)  # 输入序列长度
        self.prediction_horizon = self.config.get('prediction_horizon', 10)  # 预测未来10根K线

        # 模型结构
        self.lstm_units = self.config.get('lstm_units', 128)
        self.dropout_rate = self.config.get('dropout_rate', 0.2)
        self.learning_rate = self.config.get('learning_rate', 0.001)

        # 模型
        self.model = None

        if TF_AVAILABLE:
            self._init_model()

    def _init_model(self):
        """初始化LSTM模型"""
        if self.use_pretrained and self.model_path and os.path.exists(self.model_path):
            # 加载预训练模型
            try:
                self.model = keras.models.load_model(self.model_path)
                logger.info(f"[LSTM] 已加载预训练模型: {self.model_path}")
            except Exception as e:
                logger.error(f"[LSTM] 加载预训练模型失败: {e}")
                self._build_model()
        else:
            self._build_model()

    def _build_model(self):
        """构建LSTM模型"""
        self.model = Sequential([
            LSTM(self.lstm_units, return_sequences=True, input_shape=(self.sequence_length, 5)),
            Dropout(self.dropout_rate),
            LSTM(self.lstm_units // 2, return_sequences=False),
            Dropout(self.dropout_rate),
            Dense(64, activation='relu'),
            Dense(3)  # 输出：价格下限、价格上限、预期价格
        ])

        self.model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=self.learning_rate),
            loss='mse',
            metrics=['mae']
        )

        logger.info(f"[LSTM] 已构建新模型（{self.lstm_units} LSTM + 64 Dense）")

    def prepare_data(self, price_data: Dict) -> np.ndarray:
        """
        准备输入数据

        Args:
            price_data: 价格数据字典（包含open, high, low, close, volume）

        Returns:
            归一化后的输入数据
        """
        # 提取OHLCV数据
        opens = price_data.get('open', [])
        highs = price_data.get('high', [])
        lows = price_data.get('low', [])
        closes = price_data.get('close', [])
        volumes = price_data.get('volume', [])

        # 确保数据长度足够
        min_length = self.sequence_length
        if len(closes) < min_length:
            # 填充
            closes = [closes[0]] * (min_length - len(closes)) + closes
            highs = [highs[0]] * (min_length - len(highs)) + highs
            lows = [lows[0]] * (min_length - len(lows)) + lows
            opens = [opens[0]] * (min_length - len(opens)) + opens
            volumes = [volumes[0]] * (min_length - len(volumes)) + volumes

        # 取最后sequence_length根K线
        closes = closes[-self.sequence_length:]
        highs = highs[-self.sequence_length:]
        lows = lows[-self.sequence_length:]
        opens = opens[-self.sequence_length:]
        volumes = volumes[-self.sequence_length:]

        # 归一化（基于最后收盘价）
        last_close = closes[-1]
        opens = np.array(opens) / last_close
        highs = np.array(highs) / last_close
        lows = np.array(lows) / last_close
        closes = np.array(closes) / last_close
        volumes = np.array(volumes) / (np.mean(volumes) + 1e-6)

        # 组合成特征矩阵
        features = np.stack([opens, highs, lows, closes, volumes], axis=1)

        return features

    def predict_price_range(self, price_data: Dict, current_price: float,
                            current_atr: float, side: str) -> PricePrediction:
        """
        预测价格区间

        Args:
            price_data: 历史价格数据
            current_price: 当前价格
            current_atr: 当前ATR
            side: 方向（long/short）

        Returns:
            价格预测
        """
        if not TF_AVAILABLE or self.model is None:
            # 如果没有TensorFlow，使用统计方法
            return self._statistical_prediction(price_data, current_price, current_atr, side)

        # 准备输入数据
        X = self.prepare_data(price_data)
        X = X.reshape(1, self.sequence_length, 5)

        # 预测
        prediction = self.model.predict(X, verbose=0)[0]

        # 反归一化
        lower_bound = prediction[0] * current_price
        upper_bound = prediction[1] * current_price
        expected_price = prediction[2] * current_price

        # 确保下限 < 上限
        if lower_bound > upper_bound:
            lower_bound, upper_bound = upper_bound, lower_bound

        # 计算置信度（基于预测区间宽度）
        interval_width = abs(upper_bound - lower_bound)
        atr_ratio = interval_width / (current_atr * self.prediction_horizon)

        if atr_ratio < 1.5:
            confidence = PredictionConfidence.HIGH
        elif atr_ratio < 2.5:
            confidence = PredictionConfidence.MEDIUM
        else:
            confidence = PredictionConfidence.LOW

        return PricePrediction(
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            expected_price=expected_price,
            confidence=confidence,
            time_horizon=self.prediction_horizon
        )

    def _statistical_prediction(self, price_data: Dict, current_price: float,
                                 current_atr: float, side: str) -> PricePrediction:
        """
        统计方法预测（无TensorFlow时使用）

        Args:
            price_data: 历史价格数据
            current_price: 当前价格
            current_atr: 当前ATR
            side: 方向

        Returns:
            价格预测
        """
        closes = price_data.get('close', [])
        if len(closes) < 20:
            closes = [current_price] * 20

        # 计算统计特征
        mean_price = np.mean(closes[-20:])
        std_price = np.std(closes[-20:])

        # 基于波动率预测
        volatility = std_price / mean_price

        if side == 'long':
            lower_bound = current_price * (1 - 2 * volatility)
            upper_bound = current_price * (1 + 3 * volatility)
            expected_price = current_price * (1 + volatility)
        else:
            lower_bound = current_price * (1 - 3 * volatility)
            upper_bound = current_price * (1 + 2 * volatility)
            expected_price = current_price * (1 - volatility)

        # 置信度基于波动率
        if volatility < 0.02:
            confidence = PredictionConfidence.HIGH
        elif volatility < 0.04:
            confidence = PredictionConfidence.MEDIUM
        else:
            confidence = PredictionConfidence.LOW

        return PricePrediction(
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            expected_price=expected_price,
            confidence=confidence,
            time_horizon=10
        )

    def calculate_dynamic_profit_targets(self, prediction: PricePrediction, entry_price: float,
                                          side: str, current_atr: float) -> DynamicProfitTargets:
        """
        基于预测计算动态止盈目标

        Args:
            prediction: 价格预测
            entry_price: 入场价格
            side: 方向
            current_atr: 当前ATR

        Returns:
            动态止盈目标
        """
        # 基础ATR倍数（V4.7标准）
        base_level_1 = 2.0
        base_level_2 = 3.5
        base_level_3 = 5.5

        # 基于置信度调整
        if prediction.confidence == PredictionConfidence.HIGH:
            # 高置信度：使用激进止盈（更早锁定利润）
            level_1_atr = base_level_1 * 1.2
            level_2_atr = base_level_2 * 1.1
            level_3_atr = base_level_3 * 1.0
            level_1_exit_pct = 0.3
            level_2_exit_pct = 0.4
            level_3_exit_pct = 0.3
            trailing_activation_atr = 2.5
            trailing_distance_atr = 1.0
        elif prediction.confidence == PredictionConfidence.MEDIUM:
            # 中置信度：使用标准止盈（V4.7参数）
            level_1_atr = base_level_1
            level_2_atr = base_level_2
            level_3_atr = base_level_3
            level_1_exit_pct = 0.2
            level_2_exit_pct = 0.4
            level_3_exit_pct = 0.4
            trailing_activation_atr = 3.0
            trailing_distance_atr = 1.2
        else:
            # 低置信度：使用保守止盈（更早退出）
            level_1_atr = base_level_1 * 0.8
            level_2_atr = base_level_2 * 0.9
            level_3_atr = base_level_3 * 0.85
            level_1_exit_pct = 0.4
            level_2_exit_pct = 0.4
            level_3_exit_pct = 0.2
            trailing_activation_atr = 2.0
            trailing_distance_atr = 1.0

        # 基于预测上限调整最高止盈
        if side == 'long':
            predicted_gain_atr = (prediction.upper_bound - entry_price) / current_atr
            if predicted_gain_atr > level_3_atr:
                level_3_atr = predicted_gain_atr * 0.9  # 预测上限的90%
        else:
            predicted_gain_atr = (entry_price - prediction.lower_bound) / current_atr
            if predicted_gain_atr > level_3_atr:
                level_3_atr = predicted_gain_atr * 0.9

        return DynamicProfitTargets(
            level_1_atr=level_1_atr,
            level_1_exit_pct=level_1_exit_pct,
            level_2_atr=level_2_atr,
            level_2_exit_pct=level_2_exit_pct,
            level_3_atr=level_3_atr,
            level_3_exit_pct=level_3_exit_pct,
            trailing_activation_atr=trailing_activation_atr,
            trailing_distance_atr=trailing_distance_atr
        )


def main():
    parser = argparse.ArgumentParser(description="LSTM动态止盈预测")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--entry-price", type=float, required=True, help="入场价格")
    parser.add_argument("--side", required=True, choices=['long', 'short'], help="方向")
    parser.add_argument("--atr", type=float, required=True, help="当前ATR值")
    parser.add_argument("--closes", help="历史收盘价（逗号分隔）")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建LSTM预测器
        predictor = LSTMDynamicProfitPredictor(config)

        logger.info("=" * 70)
        logger.info("🧠 LSTM动态止盈预测 - v1.0.3")
        logger.info("=" * 70)

        status = "已启用" if TF_AVAILABLE else "已禁用（使用统计方法）"
        logger.info(f"\n状态: {status}")
        logger.info(f"模型: {'预训练' if predictor.use_pretrained else '新建'}")
        logger.info(f"序列长度: {predictor.sequence_length}")
        logger.info(f"预测跨度: {predictor.prediction_horizon} K线")

        # 准备价格数据
        if args.closes:
            closes = [float(x) for x in args.closes.split(',')]
            price_data = {
                'open': closes,
                'high': [c * 1.01 for c in closes],  # 模拟
                'low': [c * 0.99 for c in closes],  # 模拟
                'close': closes,
                'volume': [1000] * len(closes)  # 模拟
            }
        else:
            # 生成模拟数据
            base_price = args.entry_price
            closes = [base_price * (1 + 0.001 * i) for i in range(-60, 0)]
            price_data = {
                'open': closes,
                'high': [c * 1.01 for c in closes],
                'low': [c * 0.99 for c in closes],
                'close': closes,
                'volume': [1000] * len(closes)
            }

        # 预测价格区间
        prediction = predictor.predict_price_range(
            price_data, args.entry_price, args.atr, args.side
        )

        logger.info(f"\n{'=' * 70}")
        logger.info("价格预测")
        logger.info(f"{'=' * 70}")
        logger.info(f"\n入场价格: ${args.entry_price:.2f}")
        logger.info(f"方向: {args.side}")
        logger.info(f"当前ATR: ${args.atr:.2f}")
        logger.info(f"\n预测结果（未来{prediction.time_horizon}根K线）:")
        logger.info(f"  价格下限: ${prediction.lower_bound:.2f}")
        logger.info(f"  预期价格: ${prediction.expected_price:.2f}")
        logger.info(f"  价格上限: ${prediction.upper_bound:.2f}")
        logger.info(f"  预测宽度: ${(prediction.upper_bound - prediction.lower_bound):.2f}")
        logger.info(f"  置信度: {prediction.confidence.value}")

        # 计算动态止盈目标
        dynamic_targets = predictor.calculate_dynamic_profit_targets(
            prediction, args.entry_price, args.side, args.atr
        )

        logger.info(f"\n{'=' * 70}")
        logger.info("动态止盈目标")
        logger.info(f"{'=' * 70}")

        if args.side == 'long':
            target_1 = args.entry_price + dynamic_targets.level_1_atr * args.atr
            target_2 = args.entry_price + dynamic_targets.level_2_atr * args.atr
            target_3 = args.entry_price + dynamic_targets.level_3_atr * args.atr
        else:
            target_1 = args.entry_price - dynamic_targets.level_1_atr * args.atr
            target_2 = args.entry_price - dynamic_targets.level_2_atr * args.atr
            target_3 = args.entry_price - dynamic_targets.level_3_atr * args.atr

        logger.info(f"\n基于置信度{prediction.confidence.value}的动态调整:")
        logger.info(f"  第一批: ${target_1:.2f} ({dynamic_targets.level_1_atr:.1f}*ATR) - 退出{dynamic_targets.level_1_exit_pct*100:.0f}%")
        logger.info(f"  第二批: ${target_2:.2f} ({dynamic_targets.level_2_atr:.1f}*ATR) - 退出{dynamic_targets.level_2_exit_pct*100:.0f}%")
        logger.info(f"  第三批: ${target_3:.2f} ({dynamic_targets.level_3_atr:.1f}*ATR) - 退出{dynamic_targets.level_3_exit_pct*100:.0f}%")
        logger.info(f"\n跟踪止损:")
        logger.info(f"  激活距离: {dynamic_targets.trailing_activation_atr:.1f}*ATR")
        logger.info(f"  追踪距离: {dynamic_targets.trailing_distance_atr:.1f}*ATR")

        output = {
            "status": "success",
            "prediction": {
                "lower_bound": prediction.lower_bound,
                "expected_price": prediction.expected_price,
                "upper_bound": prediction.upper_bound,
                "confidence": prediction.confidence.value,
                "time_horizon": prediction.time_horizon
            },
            "dynamic_targets": {
                "level_1": {"price": target_1, "atr_multiplier": dynamic_targets.level_1_atr, "exit_pct": dynamic_targets.level_1_exit_pct},
                "level_2": {"price": target_2, "atr_multiplier": dynamic_targets.level_2_atr, "exit_pct": dynamic_targets.level_2_exit_pct},
                "level_3": {"price": target_3, "atr_multiplier": dynamic_targets.level_3_atr, "exit_pct": dynamic_targets.level_3_exit_pct},
                "trailing_stop": {
                    "activation_atr": dynamic_targets.trailing_activation_atr,
                    "distance_atr": dynamic_targets.trailing_distance_atr
                }
            }
        }

        logger.info(f"\n{'=' * 70}")
        logger.info(json.dumps(output, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error((json.dumps({)
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
