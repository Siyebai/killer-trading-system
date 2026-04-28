#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("lstm_data_collector")
except ImportError:
    import logging
    logger = logging.getLogger("lstm_data_collector")
"""
LSTM训练数据收集器 - V5.0 P1级
解决LSTM动态止盈模块需要训练数据的问题
核心策略：高频K线数据收集、增量训练机制、数据存储
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import numpy as np


@dataclass
class TrainingSample:
    """训练样本"""
    timestamp: int
    sequence: List[List[float]]  # 序列数据 (60 x 5)
    target_low: float  # 未来价格下限
    target_high: float  # 未来价格上限
    target_expected: float  # 未来预期价格
    atr: float  # 当前ATR值


class LSTMDataCollector:
    """LSTM训练数据收集器"""

    def __init__(self, db_path: str = "state/lstm_training_data.db", config: Optional[Dict] = None):
        """
        初始化数据收集器

        Args:
            db_path: 数据库路径
            config: 配置字典
        """
        self.db_path = db_path
        self.config = config or {}

        # 数据收集配置
        self.sequence_length = self.config.get('sequence_length', 60)  # 序列长度60根K线
        self.prediction_horizon = self.config.get('prediction_horizon', 10)  # 预测未来10根K线
        self.feature_count = 5  # 特征维度：Open/High/Low/Close/Volume

        # 数据收集配置
        self.timeframes = self.config.get('timeframes', ['1m', '5m', '15m', '1h'])
        self.min_samples = self.config.get('min_samples', 10000)  # 最小样本数
        self.max_samples = self.config.get('max_samples', 100000)  # 最大样本数

        # 创建数据库目录
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 初始化数据库
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 创建训练数据表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                timeframe TEXT NOT NULL,
                sequence BLOB NOT NULL,
                target_low REAL NOT NULL,
                target_high REAL NOT NULL,
                target_expected REAL NOT NULL,
                atr REAL NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(timestamp, timeframe)
            )
        """)

        # 创建模型性能表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                timeframe TEXT NOT NULL,
                accuracy REAL,
                mae REAL,
                rmse REAL,
                mape REAL,
                samples_count INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON training_samples(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timeframe ON training_samples(timeframe)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON training_samples(created_at)")

        conn.commit()
        conn.close()

    def collect_from_klines(self, kline_data: List[Dict], timeframe: str = '5m') -> int:
        """
        从K线数据收集训练样本

        Args:
            kline_data: K线数据列表
            timeframe: 时间周期

        Returns:
            收集的样本数
        """
        if len(kline_data) < self.sequence_length + self.prediction_horizon:
            logger.info(f"数据不足：需要至少 {self.sequence_length + self.prediction_horizon} 条K线，当前 {len(kline_data)} 条")
            return 0

        samples = []
        skipped = 0

        # 提取价格序列
        closes = np.array([k['close'] for k in kline_data])

        # 计算ATR
        atr = self._calculate_atr(kline_data)

        for i in range(len(kline_data) - self.sequence_length - self.prediction_horizon):
            try:
                # 提取序列数据
                sequence_start = i
                sequence_end = i + self.sequence_length
                prediction_end = i + self.sequence_length + self.prediction_horizon

                sequence_data = []
                for j in range(sequence_start, sequence_end):
                    kline = kline_data[j]
                    sequence_data.append([
                        kline.get('open', 0),
                        kline.get('high', 0),
                        kline.get('low', 0),
                        kline.get('close', 0),
                        kline.get('volume', 0)
                    ])

                # 归一化序列数据
                sequence_data = self._normalize_sequence(sequence_data)

                # 计算目标价格（未来10根K线）
                future_closes = closes[sequence_end:prediction_end]
                target_low = np.min(future_closes)
                target_high = np.max(future_closes)
                target_expected = np.mean(future_closes)

                # 当前ATR值
                current_atr = atr[sequence_end - 1] if len(atr) > sequence_end else 0

                # 创建训练样本
                sample = TrainingSample(
                    timestamp=kline_data[sequence_end - 1]['timestamp'],
                    sequence=sequence_data,
                    target_low=target_low,
                    target_high=target_high,
                    target_expected=target_expected,
                    atr=current_atr
                )

                samples.append(sample)

            except Exception as e:
                skipped += 1
                continue

        # 保存到数据库
        saved_count = self._save_samples(samples, timeframe)

        logger.info(f"收集完成：{saved_count} 个样本，跳过 {skipped} 个异常样本")
        return saved_count

    def _calculate_atr(self, kline_data: List[Dict], period: int = 14) -> np.ndarray:
        """
        计算ATR

        Args:
            kline_data: K线数据
            period: ATR周期

        Returns:
            ATR数组
        """
        if len(kline_data) < period:
            return np.zeros(len(kline_data))

        high = np.array([k['high'] for k in kline_data])
        low = np.array([k['low'] for k in kline_data])
        close = np.array([k['close'] for k in kline_data])

        tr = np.zeros(len(kline_data))
        tr[0] = high[0] - low[0]

        for i in range(1, len(kline_data)):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i-1])
            lc = abs(low[i] - close[i-1])
            tr[i] = max(hl, hc, lc)

        atr = np.zeros(len(kline_data))
        atr[period-1] = np.mean(tr[:period])

        for i in range(period, len(kline_data)):
            atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period

        return atr

    def _normalize_sequence(self, sequence: List[List[float]]) -> List[List[float]]:
        """
        归一化序列数据

        Args:
            sequence: 原始序列

        Returns:
            归一化后的序列
        """
        sequence = np.array(sequence)

        # 使用Z-score标准化
        mean = np.mean(sequence, axis=0)
        std = np.std(sequence, axis=0)
        std[std == 0] = 1  # 避免除零

        normalized = (sequence - mean) / std

        return normalized.tolist()

    def _save_samples(self, samples: List[TrainingSample], timeframe: str) -> int:
        """
        保存样本到数据库

        Args:
            samples: 样本列表
            timeframe: 时间周期

        Returns:
            保存的样本数
        """
        if not samples:
            return 0

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        saved_count = 0
        skipped_count = 0

        for sample in samples:
            try:
                # 序列数据转换为二进制
                sequence_blob = np.array(sample.sequence).tobytes()

                cursor.execute("""
                    INSERT OR REPLACE INTO training_samples
                    (timestamp, timeframe, sequence, target_low, target_high, target_expected, atr, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sample.timestamp,
                    timeframe,
                    sequence_blob,
                    sample.target_low,
                    sample.target_high,
                    sample.target_expected,
                    sample.atr,
                    int(time.time() * 1000)
                ))

                saved_count += 1

            except Exception as e:
                skipped_count += 1
                continue

        conn.commit()
        conn.close()

        return saved_count

    def load_samples(self, timeframe: str = '5m', limit: int = 1000) -> List[TrainingSample]:
        """
        加载训练样本

        Args:
            timeframe: 时间周期
            limit: 加载数量

        Returns:
            样本列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, sequence, target_low, target_high, target_expected, atr
            FROM training_samples
            WHERE timeframe = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (timeframe, limit))

        samples = []
        for row in cursor.fetchall():
            try:
                # 从二进制恢复序列
                sequence_data = np.frombuffer(row[1]).reshape(self.sequence_length, self.feature_count)

                sample = TrainingSample(
                    timestamp=row[0],
                    sequence=sequence_data.tolist(),
                    target_low=row[2],
                    target_high=row[3],
                    target_expected=row[4],
                    atr=row[5]
                )

                samples.append(sample)
            except Exception as e:
                continue

        conn.close()

        return samples

    def get_statistics(self) -> Dict:
        """
        获取数据统计信息

        Returns:
            统计信息字典
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 总样本数
        cursor.execute("SELECT COUNT(*) FROM training_samples")
        total_samples = cursor.fetchone()[0]

        # 按时间周期统计
        cursor.execute("""
            SELECT timeframe, COUNT(*) as count
            FROM training_samples
            GROUP BY timeframe
        """)
        timeframe_stats = {row[0]: row[1] for row in cursor.fetchall()}

        # 时间范围
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM training_samples")
        time_range = cursor.fetchone()

        conn.close()

        return {
            "total_samples": total_samples,
            "timeframe_stats": timeframe_stats,
            "time_range": {
                "start": time_range[0] if time_range[0] else None,
                "end": time_range[1] if time_range[1] else None
            },
            "min_samples_reached": total_samples >= self.min_samples,
            "ready_for_training": total_samples >= self.min_samples
        }

    def export_samples(self, filepath: str, timeframe: str = '5m', limit: int = 1000) -> int:
        """
        导出训练样本到JSON文件

        Args:
            filepath: 导出文件路径
            timeframe: 时间周期
            limit: 导出数量

        Returns:
            导出的样本数
        """
        samples = self.load_samples(timeframe, limit)

        export_data = []
        for sample in samples:
            export_data.append({
                "timestamp": sample.timestamp,
                "sequence": sample.sequence,
                "target_low": sample.target_low,
                "target_high": sample.target_high,
                "target_expected": sample.target_expected,
                "atr": sample.atr
            })

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2)

        return len(export_data)


def main():
    parser = argparse.ArgumentParser(description="LSTM训练数据收集器")
    parser.add_argument("--action", choices=["collect", "stats", "load", "export"], default="stats", help="操作类型")
    parser.add_argument("--data", help="K线数据JSON文件路径")
    parser.add_argument("--timeframe", default="5m", help="时间周期")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--limit", type=int, default=1000, help="样本数量限制")

    args = parser.parse_args()

    try:
        # 创建数据收集器
        collector = LSTMDataCollector()

        logger.info("=" * 70)
        logger.info("✅ LSTM训练数据收集器 - V5.0 P1级")
        logger.info("=" * 70)

        if args.action == "collect":
            if not args.data:
                logger.info("错误: 请提供 --data 参数")
                sys.exit(1)

            # 加载K线数据
            with open(args.data, 'r', encoding='utf-8') as f:
                kline_data = json.load(f)

            logger.info(f"\n开始收集训练数据...")
            logger.info(f"K线数量: {len(kline_data)}")
            logger.info(f"时间周期: {args.timeframe}")
            logger.info(f"序列长度: {collector.sequence_length}")
            logger.info(f"预测范围: {collector.prediction_horizon} 根K线")

            # 收集样本
            count = collector.collect_from_klines(kline_data, args.timeframe)

            logger.info(f"\n{'=' * 70}")
            logger.info(f"✅ 收集完成：{count} 个训练样本")

        elif args.action == "stats":
            # 获取统计信息
            stats = collector.get_statistics()

            logger.info(f"\n数据统计:")
            logger.info(f"  总样本数: {stats['total_samples']}")
            logger.info(f"  最小样本要求: {collector.min_samples}")
            logger.info(f"  是否达标: {'✅ 是' if stats['min_samples_reached'] else '❌ 否'}")
            logger.info(f"  是否可训练: {'✅ 是' if stats['ready_for_training'] else '❌ 否'}")

            if stats['timeframe_stats']:
                logger.info(f"\n按时间周期统计:")
                for timeframe, count in stats['timeframe_stats'].items():
                    logger.info(f"  {timeframe}: {count} 个样本")

            if stats['time_range']['start']:
                logger.info(f"\n时间范围:")
                logger.info(f"  开始: {stats['time_range']['start']}")
                logger.info(f"  结束: {stats['time_range']['end']}")

            output = {
                "status": "success",
                "statistics": stats
            }

        elif args.action == "load":
            # 加载样本
            samples = collector.load_samples(args.timeframe, args.limit)

            logger.info(f"\n加载样本:")
            logger.info(f"  时间周期: {args.timeframe}")
            logger.info(f"  样本数: {len(samples)}")
            logger.info(f"  序列长度: {len(samples[0].sequence) if samples else 0}")
            logger.info(f"  特征维度: {len(samples[0].sequence[0]) if samples and samples[0].sequence else 0}")

            if samples:
                sample = samples[0]
                logger.info(f"\n示例样本:")
                logger.info(f"  时间戳: {sample.timestamp}")
                logger.info(f"  目标价格: [{sample.target_low:.2f}, {sample.target_expected:.2f}, {sample.target_high:.2f}]")
                logger.info(f"  ATR: {sample.atr:.2f}")

            output = {
                "status": "success",
                "samples_count": len(samples),
                "sequence_length": len(samples[0].sequence) if samples else 0,
                "feature_count": len(samples[0].sequence[0]) if samples and samples[0].sequence else 0
            }

        elif args.action == "export":
            if not args.output:
                logger.info("错误: 请提供 --output 参数")
                sys.exit(1)

            # 导出样本
            count = collector.export_samples(args.output, args.timeframe, args.limit)

            logger.info(f"\n导出完成:")
            logger.info(f"  文件路径: {args.output}")
            logger.info(f"  样本数: {count}")

            output = {
                "status": "success",
                "exported_samples": count,
                "output_file": args.output
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
