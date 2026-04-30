# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
数据验证器 - 数据验证和清洗
"""

import json
import time
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal


class DataValidator:
    """数据验证器"""

    # 常见交易对列表
    VALID_SYMBOLS = {
        'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'XRPUSDT',
        'SOLUSDT', 'DOGEUSDT', 'DOTUSDT', 'MATICUSDT', 'LTCUSDT'
    }

    def __init__(self):
        self.validation_stats = {
            'total_validated': 0,
            'valid_count': 0,
            'invalid_count': 0,
            'errors': []
        }

    def validate_timestamp(self, ts: Any) -> Tuple[bool, Optional[float], Optional[str]]:
        """
        验证时间戳

        Args:
            ts: 时间戳（支持int, float, str, pd.Timestamp）

        Returns:
            (是否有效, 标准化时间戳(秒), 错误信息)
        """
        try:
            # 字符串格式（ISO）
            if isinstance(ts, str):
                try:
                    ts = pd.Timestamp(ts).timestamp()
                except Exception as e:
                    return False, None, f"无法解析时间字符串: {e}"

            # 检查类型
            if not isinstance(ts, (int, float)):
                return False, None, f"时间戳类型错误: {type(ts)}"

            # 处理纳秒级时间戳
            if ts > 1e15:  # 纳秒级（16-19位）
                ts = ts / 1e9

            # 处理毫秒级时间戳
            elif ts > 1e12:  # 毫秒级（13位）
                ts = ts / 1e3

            # 秒级时间戳直接使用

            # 范围验证：2000年 ~ 2100年
            min_ts = 946684800  # 2000-01-01 00:00:00 UTC
            max_ts = 4102444800  # 2100-01-01 00:00:00 UTC

            if not (min_ts < ts < max_ts):
                return False, None, f"时间戳超出范围: {ts}"

            # 检查是否为未来时间（允许1秒偏差）
            current_ts = time.time()
            if ts > current_ts + 1:
                return False, None, f"时间戳为未来时间: {ts}"

            return True, ts, None

        except Exception as e:
            return False, None, f"时间戳验证失败: {e}"

    def validate_market_tick(self, tick: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        验证市场行情数据

        Args:
            tick: 市场行情数据

        Returns:
            (是否有效, 清洗后的数据, 错误信息)
        """
        self.validation_stats['total_validated'] += 1

        # 基础字段检查
        required_fields = ['symbol', 'price', 'timestamp']
        for field in required_fields:
            if field not in tick:
                self.validation_stats['invalid_count'] += 1
                error_msg = f"缺少必需字段: {field}"
                self.validation_stats['errors'].append(error_msg)
                return False, None, error_msg

        # 验证交易对
        symbol = tick['symbol'].upper()
        if symbol not in self.VALID_SYMBOLS:
            self.validation_stats['invalid_count'] += 1
            error_msg = f"无效的交易对: {symbol}"
            self.validation_stats['errors'].append(error_msg)
            return False, None, error_msg

        # 验证价格
        try:
            price = float(tick['price'])
        except (ValueError, TypeError):
            self.validation_stats['invalid_count'] += 1
            error_msg = f"无效的价格格式: {tick['price']}"
            self.validation_stats['errors'].append(error_msg)
            return False, None, error_msg

        if price <= 0 or price > 1_000_000:  # 价格范围验证
            self.validation_stats['invalid_count'] += 1
            error_msg = f"价格超出合理范围: {price}"
            self.validation_stats['errors'].append(error_msg)
            return False, None, error_msg

        # 验证时间戳
        is_valid_ts, normalized_ts, ts_error = self.validate_timestamp(tick['timestamp'])
        if not is_valid_ts:
            self.validation_stats['invalid_count'] += 1
            error_msg = f"无效的时间戳: {ts_error}"
            self.validation_stats['errors'].append(error_msg)
            return False, None, error_msg

        # 使用标准化后的时间戳
        timestamp = normalized_ts

        # 验证买卖价（如果存在）
        cleaned_tick = {
            'symbol': symbol,
            'price': price,
            'timestamp': timestamp
        }

        if 'bid' in tick and 'ask' in tick:
            try:
                bid = float(tick['bid'])
                ask = float(tick['ask'])

                if bid <= 0 or ask <= 0:
                    raise ValueError("买卖价必须大于0")

                if bid >= ask:
                    raise ValueError(f"买价不能大于等于卖价: bid={bid}, ask={ask}")

                # 检查点差是否合理
                spread = (ask - bid) / price
                if spread > 0.05:  # 5%点差上限
                    self.validation_stats['invalid_count'] += 1
                    error_msg = f"点差过大: {spread*100:.2f}%"
                    self.validation_stats['errors'].append(error_msg)
                    return False, None, error_msg

                cleaned_tick['bid'] = bid
                cleaned_tick['ask'] = ask
                cleaned_tick['spread'] = spread

            except (ValueError, TypeError) as e:
                self.validation_stats['invalid_count'] += 1
                error_msg = f"无效的买卖价: {e}"
                self.validation_stats['errors'].append(error_msg)
                return False, None, error_msg

        # 验证成交量（如果存在）
        if 'volume' in tick:
            try:
                volume = float(tick['volume'])
                if volume < 0 or volume > 1_000_000:
                    raise ValueError("成交量范围错误")
                cleaned_tick['volume'] = volume
            except (ValueError, TypeError) as e:
                self.validation_stats['invalid_count'] += 1
                error_msg = f"无效的成交量: {e}"
                self.validation_stats['errors'].append(error_msg)
                return False, None, error_msg

        self.validation_stats['valid_count'] += 1
        return True, cleaned_tick, None

    def validate_order(self, order: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        验证订单数据

        Args:
            order: 订单数据

        Returns:
            (是否有效, 错误信息)
        """
        # 必需字段
        required_fields = ['symbol', 'side', 'size']
        for field in required_fields:
            if field not in order:
                return False, f"缺少必需字段: {field}"

        # 验证交易对
        symbol = order['symbol'].upper()
        if symbol not in self.VALID_SYMBOLS:
            return False, f"无效的交易对: {symbol}"

        # 验证方向
        side = order['side'].upper()
        if side not in ['BUY', 'SELL']:
            return False, f"无效的订单方向: {side}"

        # 验证数量
        try:
            size = float(order['size'])
            if size <= 0 or size > 10000:
                return False, f"订单数量超出范围: {size}"
        except (ValueError, TypeError):
            return False, f"无效的订单数量: {order['size']}"

        # 验证价格（如果存在）
        if 'price' in order:
            try:
                price = float(order['price'])
                if price <= 0 or price > 1_000_000:
                    return False, f"订单价格超出范围: {price}"
            except (ValueError, TypeError):
                return False, f"无效的订单价格: {order['price']}"

        return True, None

    def validate_indicators(self, indicators: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        验证技术指标数据

        Args:
            indicators: 指标数据

        Returns:
            (是否有效, 清洗后的数据, 错误信息)
        """
        # 检查必需指标
        required_indicators = ['close', 'sma5', 'sma20', 'volatility']
        for ind in required_indicators:
            if ind not in indicators:
                return False, None, f"缺少必需指标: {ind}"

        try:
            cleaned = {}

            # 验证价格指标
            for key in ['close', 'sma5', 'sma20']:
                value = float(indicators[key])
                if value <= 0 or value > 1_000_000:
                    return False, None, f"{key}超出范围: {value}"
                cleaned[key] = value

            # 验证百分比指标
            for key in ['volatility', 'rsi']:
                if key in indicators:
                    value = float(indicators[key])
                    if key == 'rsi':
                        if not (0 <= value <= 100):
                            return False, None, f"{key}超出[0,100]范围: {value}"
                    else:
                        if value < 0 or value > 1:
                            return False, None, f"{key}超出[0,1]范围: {value}"
                    cleaned[key] = value

            # 验证ATR
            if 'atr' in indicators:
                atr = float(indicators['atr'])
                if atr < 0 or atr > 100000:
                    return False, None, f"ATR超出范围: {atr}"
                cleaned['atr'] = atr

            return True, cleaned, None

        except (ValueError, TypeError) as e:
            return False, None, f"指标数据类型错误: {e}"

    def clean_outliers(self, data: List[float], window: int = 5, sigma: float = 3.0) -> List[float]:
        """
        清洗异常值

        Args:
            data: 数据列表
            window: 移动窗口大小
            sigma: 标准差倍数

        Returns:
            清洗后的数据
        """
        if len(data) < window * 2:
            return data

        cleaned = data.copy()

        for i in range(window, len(data) - window):
            local_data = data[i-window:i+window]
            mean = np.mean(local_data)
            std = np.std(local_data)

            if std == 0:
                continue

            z_score = abs(data[i] - mean) / std
            if z_score > sigma:
                # 用中位数替换异常值
                cleaned[i] = np.median(local_data)

        return cleaned

    def get_validation_stats(self) -> Dict[str, Any]:
        """获取验证统计信息"""
        stats = self.validation_stats.copy()
        if stats['total_validated'] > 0:
            stats['valid_rate'] = stats['valid_count'] / stats['total_validated']
        else:
            stats['valid_rate'] = 0.0

        return stats

    def reset_stats(self):
        """重置统计信息"""
        self.validation_stats = {
            'total_validated': 0,
            'valid_count': 0,
            'invalid_count': 0,
            'errors': []
        }
