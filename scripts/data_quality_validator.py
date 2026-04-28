#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("data_quality_validator")
except ImportError:
    import logging
    logger = logging.getLogger("data_quality_validator")
"""
数据质量验证模块 - v1.0.2 P0级
解决数据质量验证缺失问题，增加时间戳标准化和验证逻辑
核心策略：数据完整性检查、时间戳标准化、异常值检测
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import numpy as np


class DataQuality(Enum):
    """数据质量等级"""
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    ACCEPTABLE = "ACCEPTABLE"
    POOR = "POOR"
    INVALID = "INVALID"


class ValidationIssue(Enum):
    """验证问题类型"""
    MISSING_DATA = "MISSING_DATA"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    DUPLICATE = "DUPLICATE"
    OUTLIER = "OUTLIER"
    NEGATIVE_PRICE = "NEGATIVE_PRICE"
    ZERO_VOLUME = "ZERO_VOLUME"


@dataclass
class ValidationResult:
    """验证结果"""
    quality: DataQuality
    issues: List[Tuple[ValidationIssue, str]]
    is_valid: bool
    warnings: List[str]


class DataQualityValidator:
    """数据质量验证器"""

    def __init__(self, config: Optional[Dict] = None):
        """
        初始化数据质量验证器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 时间戳配置
        self.min_timestamp = self.config.get('min_timestamp', 1609459200000)  # 2021-01-01
        self.max_timestamp = int(time.time() * 1000) + 86400000  # 当前时间+1天

        # 异常值检测配置
        self.price_change_threshold = self.config.get('price_change_threshold', 0.2)  # 20%涨跌幅
        self.outlier_std_multiplier = self.config.get('outlier_std_multiplier', 3.0)  # 3倍标准差

        # 数据完整性配置
        self.required_fields = self.config.get('required_fields', [
            'timestamp', 'open', 'high', 'low', 'close', 'volume'
        ])

    def validate_kline_data(self, kline_data: List[Dict]) -> ValidationResult:
        """
        验证K线数据

        Args:
            kline_data: K线数据列表

        Returns:
            验证结果
        """
        issues = []
        warnings = []

        if not kline_data:
            return ValidationResult(
                quality=DataQuality.INVALID,
                issues=[(ValidationIssue.MISSING_DATA, "数据为空")],
                is_valid=False,
                warnings=[]
            )

        # 检查必需字段
        for i, kline in enumerate(kline_data):
            for field in self.required_fields:
                if field not in kline:
                    issues.append((
                        ValidationIssue.MISSING_DATA,
                        f"第{i+1}条K线缺少字段: {field}"
                    ))

        # 检查时间戳
        timestamps = []
        for i, kline in enumerate(kline_data):
            ts = kline.get('timestamp')
            if ts is None:
                issues.append((
                    ValidationIssue.INVALID_TIMESTAMP,
                    f"第{i+1}条K线缺少时间戳"
                ))
                continue

            # 时间戳标准化（支持秒、毫秒、微秒）
            if ts < 1000000000000:  # 秒
                ts = ts * 1000
            elif ts > 1000000000000000:  # 微秒
                ts = ts // 1000

            # 时间戳范围检查
            if ts < self.min_timestamp or ts > self.max_timestamp:
                issues.append((
                    ValidationIssue.INVALID_TIMESTAMP,
                    f"第{i+1}条K线时间戳超出范围: {ts}"
                ))

            timestamps.append(ts)

        # 检查时间戳顺序
        if len(timestamps) > 1:
            for i in range(1, len(timestamps)):
                if timestamps[i] <= timestamps[i-1]:
                    issues.append((
                        ValidationIssue.OUT_OF_ORDER,
                        f"第{i+1}条K线时间戳不大于前一条: {timestamps[i]} <= {timestamps[i-1]}"
                    ))

        # 检查重复
        seen_timestamps = set()
        for i, ts in enumerate(timestamps):
            if ts in seen_timestamps:
                issues.append((
                    ValidationIssue.DUPLICATE,
                    f"第{i+1}条K线时间戳重复: {ts}"
                ))
            seen_timestamps.add(ts)

        # 检查价格数据（独立循环，避免缩进错误）
        for idx, kline in enumerate(kline_data):
            open_price = kline.get('open', 0)
            high = kline.get('high', 0)
            low = kline.get('low', 0)
            close = kline.get('close', 0)

            # 检查负价格
            if any(price < 0 for price in [open_price, high, low, close]):
                issues.append((
                    ValidationIssue.NEGATIVE_PRICE,
                    f"第{idx+1}条K线存在负价格: O={open_price}, H={high}, L={low}, C={close}"
                ))

            # 检查价格逻辑
            if not (low <= open_price <= high):
                issues.append((
                    ValidationIssue.OUTLIER,
                    f"第{idx+1}条K线Open价格逻辑错误: {open_price}不在[{low}, {high}]"
                ))

            if not (low <= close <= high):
                issues.append((
                    ValidationIssue.OUTLIER,
                    f"第{idx+1}条K线Close价格逻辑错误: {close}不在[{low}, {high}]"
                ))

            # 检查异常涨跌幅
            if idx > 0:
                prev_close = kline_data[idx-1].get('close', 0)
                if prev_close > 0:
                    change = abs(close - prev_close) / prev_close
                    if change > self.price_change_threshold:
                        warnings.append(
                            f"第{idx+1}条K线价格变化{change*100:.1f}%超过阈值{self.price_change_threshold*100:.0f}%"
                        )

        # 检查成交量
        for idx, kline in enumerate(kline_data):
            volume = kline.get('volume', 0)
            if volume < 0:
                issues.append((
                    ValidationIssue.ZERO_VOLUME,
                    f"第{idx+1}条K线成交量为负: {volume}"
                ))
            elif volume == 0:
                warnings.append(
                    f"第{idx+1}条K线成交量为0"
                )

        # 统计异常值
        if len(kline_data) > 10:
            closes = [kline.get('close', 0) for kline in kline_data if kline.get('close', 0) > 0]
            if closes:
                mean_price = np.mean(closes)
                std_price = np.std(closes)
                outliers = 0

                # BUG #5修复：检查std_price是否为0，避免除零错误
                if std_price > 1e-10:  # 使用小的阈值避免浮点精度问题
                    for idx, kline in enumerate(kline_data):
                        close_price = kline.get('close', 0)
                        if close_price > 0:
                            z_score = abs(close_price - mean_price) / std_price
                            if z_score > self.outlier_std_multiplier:
                                outliers += 1
                                warnings.append(
                                    f"第{idx+1}条K线价格{close_price:.2f}偏离均值{mean_price:.2f} {z_score:.1f}倍标准差"
                                )

                    if outliers > len(closes) * 0.1:
                        issues.append((
                            ValidationIssue.OUTLIER,
                            f"异常值比例过高: {outliers}/{len(closes)} ({outliers/len(closes)*100:.1f}%)"
                        ))
                else:
                    # std_price接近0，所有价格几乎相同
                    warnings.append(
                        f"所有价格几乎相同（标准差={std_price:.10f}），跳过异常值检测"
                    )

        # 计算数据质量等级
        if not issues and not warnings:
            quality = DataQuality.EXCELLENT
            is_valid = True
        elif not issues and len(warnings) <= len(kline_data) * 0.05:
            quality = DataQuality.GOOD
            is_valid = True
        elif len(issues) <= len(kline_data) * 0.01:
            quality = DataQuality.ACCEPTABLE
            is_valid = True
        elif len(issues) <= len(kline_data) * 0.05:
            quality = DataQuality.POOR
            is_valid = False
        else:
            quality = DataQuality.INVALID
            is_valid = False

        return ValidationResult(
            quality=quality,
            issues=issues,
            is_valid=is_valid,
            warnings=warnings
        )

    def normalize_timestamp(self, timestamp: int) -> int:
        """
        标准化时间戳为毫秒

        Args:
            timestamp: 原始时间戳（可能是秒、毫秒、微秒）

        Returns:
            标准化后的毫秒时间戳
        """
        if timestamp is None:
            return int(time.time() * 1000)

        if timestamp < 1000000000000:  # 秒
            return timestamp * 1000
        elif timestamp > 1000000000000000:  # 微秒
            return timestamp // 1000
        else:  # 毫秒
            return timestamp

    def clean_kline_data(self, kline_data: List[Dict]) -> List[Dict]:
        """
        清洗K线数据

        Args:
            kline_data: 原始K线数据

        Returns:
            清洗后的K线数据
        """
        cleaned_data = []

        for kline in kline_data:
            # 标准化时间戳
            kline['timestamp'] = self.normalize_timestamp(kline.get('timestamp'))

            # 填充缺失值
            if kline.get('open') is None:
                kline['open'] = kline.get('close', 0)
            if kline.get('high') is None:
                kline['high'] = max(kline.get('open', 0), kline.get('close', 0))
            if kline.get('low') is None:
                kline['low'] = min(kline.get('open', 0), kline.get('close', 0))
            if kline.get('volume') is None:
                kline['volume'] = 0

            cleaned_data.append(kline)

        # 按时间戳排序
        cleaned_data.sort(key=lambda x: x.get('timestamp', 0))

        return cleaned_data


def main():
    parser = argparse.ArgumentParser(description="数据质量验证")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--data", help="K线数据JSON文件路径")
    parser.add_argument("--generate-sample", action="store_true", help="生成示例数据")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建数据质量验证器
        validator = DataQualityValidator(config)

        logger.info("=" * 70)
        logger.info("✅ 数据质量验证 - v1.0.2 P0级")
        logger.info("=" * 70)

        # 生成示例数据
        if args.generate_sample:
            logger.info("\n生成示例数据...")
            base_time = int(time.time() * 1000)
            sample_data = []

            for i in range(100):
                ts = base_time - (100 - i) * 60000  # 每分钟
                base_price = 50000 + i * 10

                sample_data.append({
                    'timestamp': ts,
                    'open': base_price,
                    'high': base_price * 1.01,
                    'low': base_price * 0.99,
                    'close': base_price * (1 + np.random.randn() * 0.001),
                    'volume': 1000 + np.random.randn() * 100
                })

            logger.info(f"已生成 {len(sample_data)} 条示例K线数据")

            # 保存示例数据
            with open('sample_kline_data.json', 'w') as f:
                json.dump(sample_data, f, indent=2)

            logger.info("示例数据已保存到 sample_kline_data.json")

            kline_data = sample_data
        else:
            # 加载数据
            if not args.data:
                logger.info("错误: 请提供 --data 参数或使用 --generate-sample")
                sys.exit(1)

            with open(args.data, 'r', encoding='utf-8') as f:
                kline_data = json.load(f)

        logger.info(f"\n数据概况:")
        logger.info(f"  K线数量: {len(kline_data)}")
        logger.info(f"  时间范围: {kline_data[0].get('timestamp')} - {kline_data[-1].get('timestamp')}")

        # 验证数据
        logger.info(f"\n{'=' * 70}")
        logger.info("开始验证...")
        logger.info(f"{'=' * 70}")

        result = validator.validate_kline_data(kline_data)

        logger.info(f"\n数据质量: {result.quality.value}")
        logger.info(f"是否有效: {'✅ 是' if result.is_valid else '❌ 否'}")

        if result.issues:
            logger.info(f"\n问题 ({len(result.issues)}):")
            for issue, desc in result.issues:
                logger.info(f"  [{issue.value}] {desc}")
        else:
            logger.info(f"\n✅ 未发现问题")

        if result.warnings:
            logger.info(f"\n警告 ({len(result.warnings)}):")
            for warning in result.warnings[:10]:  # 只显示前10个
                logger.info(f"  ⚠️ {warning}")
            if len(result.warnings) > 10:
                logger.info(f"  ... 还有 {len(result.warnings) - 10} 个警告")

        # 清洗数据
        if not result.is_valid:
            logger.info(f"\n{'=' * 70}")
            logger.info("数据清洗...")
            logger.info(f"{'=' * 70}")

            cleaned_data = validator.clean_kline_data(kline_data)
            logger.info(f"\n清洗后数据: {len(cleaned_data)} 条")

            # 重新验证
            cleaned_result = validator.validate_kline_data(cleaned_data)
            logger.info(f"清洗后质量: {cleaned_result.quality.value}")
            logger.info(f"清洗后有效: {'✅ 是' if cleaned_result.is_valid else '❌ 否'}")

        output = {
            "status": "success",
            "quality": result.quality.value,
            "is_valid": result.is_valid,
            "issue_count": len(result.issues),
            "warning_count": len(result.warnings),
            "issues": [{"type": issue.value, "description": desc} for issue, desc in result.issues[:10]],
            "warnings": result.warnings[:10]
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
