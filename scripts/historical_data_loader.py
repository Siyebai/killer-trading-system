#!/usr/bin/env python3
"""
历史数据加载器 - 策略实验室数据管道
从本地文件或API加载多品种、多时间段OHLCV数据
"""

import os
import json
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
import time

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("historical_data_loader")
except ImportError:
    import logging
    logger = logging.getLogger("historical_data_loader")


class DataFrequency(Enum):
    """数据频率"""
    TICK = "tick"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1w"


class DataSource(Enum):
    """数据源"""
    LOCAL_FILE = "local_file"
    BINANCE_API = "binance_api"
    CSV_FILE = "csv_file"
    PARQUET_FILE = "parquet_file"


@dataclass
class DataSpec:
    """数据规格"""
    symbol: str
    frequency: DataFrequency
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    source: DataSource
    path: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'frequency': self.frequency.value,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'source': self.source.value,
            'path': self.path
        }


class HistoricalDataLoader:
    """历史数据加载器"""

    def __init__(self, data_dir: str = "assets/data"):
        """
        初始化数据加载器

        Args:
            data_dir: 数据目录
        """
        self.data_dir = data_dir
        self.cache: Dict[str, np.ndarray] = {}

        # 第一层防御：创建数据目录
        os.makedirs(data_dir, exist_ok=True)

        logger.info(f"历史数据加载器初始化完成: data_dir={data_dir}")

    def load(self, spec: DataSpec) -> np.ndarray:
        """
        加载数据

        Args:
            spec: 数据规格

        Returns:
            OHLCV数据数组 (N x 5)
        """
        try:
            # 第一层防御：参数校验
            cache_key = f"{spec.symbol}_{spec.frequency.value}_{spec.start_date}_{spec.end_date}"

            if cache_key in self.cache:
                logger.debug(f"从缓存加载数据: {cache_key}")
                return self.cache[cache_key]

            # 第二层防御：根据数据源加载
            if spec.source == DataSource.LOCAL_FILE:
                data = self._load_from_json(spec)
            elif spec.source == DataSource.CSV_FILE:
                data = self._load_from_csv(spec)
            elif spec.source == DataSource.PARQUET_FILE:
                data = self._load_from_parquet(spec)
            elif spec.source == DataSource.BINANCE_API:
                data = self._load_from_binance_api(spec)
            else:
                raise ValueError(f"不支持的数据源: {spec.source}")

            # 第三层防御：数据验证
            data = self._validate_and_clean(data)

            # 缓存数据
            self.cache[cache_key] = data

            logger.info(f"数据加载成功: {spec.symbol}, 形状={data.shape}")
            return data

        except Exception as e:
            logger.error(f"加载数据失败: {spec.symbol}, 错误={e}")
            # 返回空数据
            return np.zeros((0, 5))

    def _load_from_json(self, spec: DataSpec) -> np.ndarray:
        """
        从JSON文件加载数据

        Args:
            spec: 数据规格

        Returns:
            OHLCV数据数组
        """
        if not spec.path:
            raise ValueError("本地文件需要指定path")

        file_path = os.path.join(self.data_dir, spec.path)

        # 第一层防御：文件存在性检查
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        with open(file_path, 'r') as f:
            raw_data = json.load(f)

        # 第二层防御：转换为numpy数组
        data = []
        for item in raw_data:
            try:
                data.append([
                    float(item['open']),
                    float(item['high']),
                    float(item['low']),
                    float(item['close']),
                    float(item['volume'])
                ])
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"跳过无效数据点: {item}, 错误={e}")
                continue

        return np.array(data)

    def _load_from_csv(self, spec: DataSpec) -> np.ndarray:
        """
        从CSV文件加载数据

        Args:
            spec: 数据规格

        Returns:
            OHLCV数据数组
        """
        if not spec.path:
            raise ValueError("CSV文件需要指定path")

        file_path = os.path.join(self.data_dir, spec.path)

        # 第一层防御：文件存在性检查
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 读取CSV
        df = pd.read_csv(file_path)

        # 第二层防御：列名校验
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"CSV缺少必需列: {col}")

        # 提取OHLCV
        data = df[required_cols].values.astype(np.float32)

        return data

    def _load_from_parquet(self, spec: DataSpec) -> np.ndarray:
        """
        从Parquet文件加载数据

        Args:
            spec: 数据规格

        Returns:
            OHLCV数据数组
        """
        if not spec.path:
            raise ValueError("Parquet文件需要指定path")

        file_path = os.path.join(self.data_dir, spec.path)

        # 第一层防御：文件存在性检查
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 读取Parquet
        df = pd.read_parquet(file_path)

        # 第二层防御：列名校验
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Parquet缺少必需列: {col}")

        # 提取OHLCV
        data = df[required_cols].values.astype(np.float32)

        return data

    def _load_from_binance_api(self, spec: DataSpec) -> np.ndarray:
        """
        从Binance API加载历史数据（模拟实现）

        Args:
            spec: 数据规格

        Returns:
            OHLCV数据数组
        """
        # 第一层防御：API密钥检查（模拟）
        # 实际实现需要使用requests库调用Binance API

        # 模拟生成数据
        start_dt = datetime.strptime(spec.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(spec.end_date, "%Y-%m-%d")
        days = (end_dt - start_dt).days

        if days <= 0:
            raise ValueError(f"无效日期范围: {spec.start_date} - {spec.end_date}")

        # 生成模拟数据
        n_samples = days * 24 * 60  # 假设1分钟频率

        np.random.seed(42)
        close_prices = 50000.0 + np.cumsum(np.random.randn(n_samples) * 50)

        open_prices = close_prices[:-1]
        open_prices = np.insert(open_prices, 0, 50000.0)

        high_prices = np.maximum(open_prices, close_prices) + np.abs(np.random.randn(n_samples) * 20)
        low_prices = np.minimum(open_prices, close_prices) - np.abs(np.random.randn(n_samples) * 20)
        volumes = np.abs(np.random.randn(n_samples) * 1000) + 500

        data = np.column_stack([
            open_prices,
            high_prices,
            low_prices,
            close_prices,
            volumes
        ])

        logger.warning(f"使用模拟数据: {spec.symbol}, 样本数={n_samples}")
        return data

    def _validate_and_clean(self, data: np.ndarray) -> np.ndarray:
        """
        验证并清理数据

        Args:
            data: 原始数据

        Returns:
            清理后的数据
        """
        try:
            # 第一层防御：形状检查
            if data.shape[1] != 5:
                raise ValueError(f"数据列数错误: {data.shape[1]}, 期望5")

            # 第二层防御：移除无效值
            mask = ~np.isnan(data).any(axis=1)
            mask = mask & ~np.isinf(data).any(axis=1)
            data = data[mask]

            # 第三层防御：价格合理性检查
            # High >= Low
            invalid_high_low = data[:, 1] < data[:, 2]
            if np.any(invalid_high_low):
                logger.warning(f"发现{np.sum(invalid_high_low)}条High<Low的无效数据，已移除")
                data = data[~invalid_high_low]

            # Volume >= 0
            invalid_volume = data[:, 4] < 0
            if np.any(invalid_volume):
                logger.warning(f"发现{np.sum(invalid_volume)}条Volume<0的无效数据，已移除")
                data = data[~invalid_volume]

            if len(data) == 0:
                logger.error("清理后无有效数据")
                return np.zeros((0, 5))

            logger.debug(f"数据清理完成: {len(data)} 条有效记录")
            return data

        except Exception as e:
            logger.error(f"数据清理失败: {e}")
            return np.zeros((0, 5))

    def generate_mock_data(self,
                          symbol: str,
                          n_samples: int = 10000,
                          frequency: DataFrequency = DataFrequency.MINUTE_1) -> np.ndarray:
        """
        生成模拟数据（用于测试）

        Args:
            symbol: 交易对
            n_samples: 样本数量
            frequency: 数据频率

        Returns:
            OHLCV数据数组
        """
        np.random.seed(42)

        # 第一层防御：生成基础价格序列
        base_price = 50000.0 if "BTC" in symbol.upper() else 3000.0
        close_prices = base_price + np.cumsum(np.random.randn(n_samples) * (base_price * 0.001))

        open_prices = np.roll(close_prices, 1)
        open_prices[0] = close_prices[0]

        # 第二层防御：生成高低价
        high_prices = np.maximum(open_prices, close_prices) * (1 + np.abs(np.random.randn(n_samples) * 0.001))
        low_prices = np.minimum(open_prices, close_prices) * (1 - np.abs(np.random.randn(n_samples) * 0.001))

        # 生成成交量
        volumes = np.abs(np.random.randn(n_samples)) * 1000 + 500

        data = np.column_stack([
            open_prices,
            high_prices,
            low_prices,
            close_prices,
            volumes
        ])

        logger.info(f"生成模拟数据: {symbol}, 样本数={n_samples}, 频率={frequency.value}")
        return data

    def save_to_csv(self, data: np.ndarray, filename: str) -> None:
        """
        保存数据到CSV文件

        Args:
            data: OHLCV数据
            filename: 文件名
        """
        try:
            file_path = os.path.join(self.data_dir, filename)

            # 第一层防御：数据校验
            if data.shape[1] != 5:
                raise ValueError(f"数据列数错误: {data.shape[1]}, 期望5")

            df = pd.DataFrame(data, columns=['open', 'high', 'low', 'close', 'volume'])
            df.to_csv(file_path, index=False)

            logger.info(f"数据已保存: {file_path}, 记录数={len(data)}")

        except Exception as e:
            logger.error(f"保存数据失败: {e}")


if __name__ == "__main__":
    # 测试代码
    loader = HistoricalDataLoader(data_dir="assets/data")

    # 测试1: 生成模拟数据
    print("测试1: 生成模拟数据")
    mock_data = loader.generate_mock_data("BTCUSDT", n_samples=1000)
    print(f"模拟数据形状: {mock_data.shape}")
    print(f"前5条:\n{mock_data[:5]}")

    # 测试2: 保存到CSV
    print("\n测试2: 保存到CSV")
    loader.save_to_csv(mock_data, "btcusdt_test.csv")

    # 测试3: 从CSV加载
    print("\n测试3: 从CSV加载")
    spec = DataSpec(
        symbol="BTCUSDT",
        frequency=DataFrequency.MINUTE_1,
        start_date="2024-01-01",
        end_date="2024-12-31",
        source=DataSource.CSV_FILE,
        path="btcusdt_test.csv"
    )
    loaded_data = loader.load(spec)
    print(f"加载的数据形状: {loaded_data.shape}")
    print(f"前5条:\n{loaded_data[:5]}")

    print("\n所有测试通过！")
