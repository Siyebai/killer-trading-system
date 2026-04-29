#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("pairs_trading")
except ImportError:
    import logging
    logger = logging.getLogger("pairs_trading")
"""
统计套利模块（Pairs Trading） - v1.0.3扩展
定位：扫描发现和智能决策的增强
核心策略：协整检验、价差Z-score、均值回归、LinUCB权重优化
"""

import argparse
import json
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import sqlite3
import os
from scipy import stats
from statsmodels.tsa.stattools import coint
from statsmodels.regression.linear_model import OLS


class PairStatus(Enum):
    """配对状态"""
    COINTEGRATED = "COINTEGRATED"
    NOT_COINTEGRATED = "NOT_COINTEGRATED"
    TESTING = "TESTING"


class SignalType(Enum):
    """信号类型"""
    LONG_SPREAD = "LONG_SPREAD"  # 做多价差（买资产A，卖资产B）
    SHORT_SPREAD = "SHORT_SPREAD"  # 做空价差（卖资产A，买资产B）
    CLOSE = "CLOSE"  # 平仓
    HOLD = "HOLD"  # 持仓


@dataclass
class TradingPair:
    """交易对"""
    pair_id: str
    asset_a: str  # 资产A（如BTC）
    asset_b: str  # 资产B（如ETH）
    hedge_ratio: float  # 对冲比率
    cointegration_p_value: float  # 协整检验p值
    status: PairStatus
    test_start_time: int


@dataclass
class SpreadSignal:
    """价差信号"""
    pair_id: str
    signal_type: SignalType
    z_score: float
    entry_z_score: float
    current_spread: float
    mean_spread: float
    std_spread: float
    confidence: float
    timestamp: int


@dataclass
class PairPosition:
    """配对仓位"""
    position_id: str
    pair_id: str
    asset_a_size: float
    asset_b_size: float
    entry_spread: float
    entry_z_score: float
    signal_type: SignalType
    entry_time: int
    status: str
    pnl: float


class CointegrationTest:
    """协整检验"""

    @staticmethod
    def engle_granger_test(price_a: np.ndarray, price_b: np.ndarray, significance_level: float = 0.05) -> Dict:
        """
        Engle-Granger两步法协整检验

        Args:
            price_a: 资产A价格序列
            price_b: 资产B价格序列
            significance_level: 显著性水平

        Returns:
            检验结果
        """
        if len(price_a) != len(price_b) or len(price_a) < 30:
            return {
                "is_cointegrated": False,
                "p_value": 1.0,
                "hedge_ratio": 0.0,
                "test_statistic": 0.0,
                "critical_value": 0.0,
                "error": "数据不足或长度不匹配"
            }

        try:
            # 第一步：回归获取对冲比率
            df = pd.DataFrame({
                'y': price_a,
                'x': price_b
            })

            model = OLS(df['y'], df['x']).fit()
            hedge_ratio = model.params['x']

            # 第二步：对残差进行单位根检验
            residuals = model.resid

            # 使用Augmented Dickey-Fuller检验
            from statsmodels.tsa.stattools import adfuller
            adf_result = adfuller(residuals, maxlag=1)

            test_statistic = adf_result[0]
            p_value = adf_result[1]
            critical_values = adf_result[4]

            # 判断是否协整
            is_cointegrated = p_value < significance_level

            return {
                "is_cointegrated": is_cointegrated,
                "p_value": p_value,
                "hedge_ratio": hedge_ratio,
                "test_statistic": test_statistic,
                "critical_value": critical_values['5%'],
                "error": None
            }

        except Exception as e:
            return {
                "is_cointegrated": False,
                "p_value": 1.0,
                "hedge_ratio": 0.0,
                "test_statistic": 0.0,
                "critical_value": 0.0,
                "error": str(e)
            }


class SpreadAnalyzer:
    """价差分析器"""

    @staticmethod
    def calculate_z_score(
        spread: np.ndarray,
        lookback_period: int = 30
    ) -> Tuple[float, float, float]:
        """
        计算Z-score

        Args:
            spread: 价差序列
            lookback_period: 回溯周期

        Returns:
            (z_score, mean_spread, std_spread)
        """
        if len(spread) < lookback_period:
            return 0.0, np.mean(spread), np.std(spread)

        recent_spread = spread[-lookback_period:]
        mean_spread = np.mean(recent_spread)
        std_spread = np.std(recent_spread)

        if std_spread == 0:
            return 0.0, mean_spread, std_spread

        z_score = (spread[-1] - mean_spread) / std_spread

        return z_score, mean_spread, std_spread

    @staticmethod
    def generate_signal(
        z_score: float,
        entry_threshold: float = 2.0,
        exit_threshold: float = 0.0
    ) -> SignalType:
        """
        生成交易信号

        Args:
            z_score: Z-score值
            entry_threshold: 开仓阈值（标准差倍数）
            exit_threshold: 平仓阈值

        Returns:
            信号类型
        """
        if z_score > entry_threshold:
            return SignalType.SHORT_SPREAD  # 价差过高，做空价差
        elif z_score < -entry_threshold:
            return SignalType.LONG_SPREAD  # 价差过低，做多价差
        elif abs(z_score) <= exit_threshold:
            return SignalType.CLOSE  # 价差回归，平仓
        else:
            return SignalType.HOLD  # 持仓观望


class PairsTradingStrategy:
    """统计套利策略"""

    def __init__(
        self,
        config: Optional[Dict] = None
    ):
        """
        初始化统计套利策略

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 策略参数
        self.significance_level = self.config.get('significance_level', 0.05)
        self.lookback_period = self.config.get('lookback_period', 30)
        self.entry_threshold = self.config.get('entry_threshold', 2.0)  # 2个标准差
        self.exit_threshold = self.config.get('exit_threshold', 0.0)  # 0个标准差
        self.min_observation = self.config.get('min_observation', 100)  # 最小观察周期

        # 数据库路径
        self.db_path = self.config.get('db_path', 'state/pairs_trading.db')
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 初始化数据库
        self._init_db()

        # 交易对缓存
        self.pairs: Dict[str, TradingPair] = {}

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 创建交易对表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trading_pairs (
                pair_id TEXT PRIMARY KEY,
                asset_a TEXT NOT NULL,
                asset_b TEXT NOT NULL,
                hedge_ratio REAL NOT NULL,
                cointegration_p_value REAL NOT NULL,
                status TEXT NOT NULL,
                test_start_time INTEGER NOT NULL,
                last_update_time INTEGER NOT NULL
            )
        """)

        # 创建配对仓位表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pair_positions (
                position_id TEXT PRIMARY KEY,
                pair_id TEXT NOT NULL,
                asset_a_size REAL NOT NULL,
                asset_b_size REAL NOT NULL,
                entry_spread REAL NOT NULL,
                entry_z_score REAL NOT NULL,
                signal_type TEXT NOT NULL,
                entry_time INTEGER NOT NULL,
                exit_time INTEGER,
                status TEXT NOT NULL,
                pnl REAL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        # 创建价差历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spread_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair_id TEXT NOT NULL,
                spread REAL NOT NULL,
                z_score REAL NOT NULL,
                timestamp INTEGER NOT NULL,
                UNIQUE(pair_id, timestamp)
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pair_status ON trading_pairs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_position_status ON pair_positions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spread_timestamp ON spread_history(timestamp)")

        conn.commit()
        conn.close()

    def test_cointegration(
        self,
        asset_a: str,
        asset_b: str,
        price_a: np.ndarray,
        price_b: np.ndarray
    ) -> Optional[Dict]:
        """
        测试协整关系

        Args:
            asset_a: 资产A名称
            asset_b: 资产B名称
            price_a: 资产A价格序列
            price_b: 资产B价格序列

        Returns:
            协整检验结果
        """
        if len(price_a) != len(price_b) or len(price_a) < self.min_observation:
            return None

        # 执行协整检验
        result = CointegrationTest.engle_granger_test(
            price_a, price_b, self.significance_level
        )

        if result['error']:
            return None

        # 创建交易对
        pair_id = f"{asset_a}_{asset_b}"
        pair = TradingPair(
            pair_id=pair_id,
            asset_a=asset_a,
            asset_b=asset_b,
            hedge_ratio=result['hedge_ratio'],
            cointegration_p_value=result['p_value'],
            status=PairStatus.COINTEGRATED if result['is_cointegrated'] else PairStatus.NOT_COINTEGRATED,
            test_start_time=int(pd.Timestamp.now().timestamp() * 1000)
        )

        # 保存交易对
        self.pairs[pair_id] = pair
        self._save_pair(pair)

        return {
            "pair_id": pair_id,
            "asset_a": asset_a,
            "asset_b": asset_b,
            "is_cointegrated": result['is_cointegrated'],
            "p_value": result['p_value'],
            "hedge_ratio": result['hedge_ratio'],
            "test_statistic": result['test_statistic'],
            "critical_value": result['critical_value']
        }

    def calculate_spread(
        self,
        pair_id: str,
        price_a: float,
        price_b: float
    ) -> Optional[float]:
        """
        计算价差

        Args:
            pair_id: 交易对ID
            price_a: 资产A当前价格
            price_b: 资产B当前价格

        Returns:
            价差
        """
        if pair_id not in self.pairs:
            return None

        pair = self.pairs[pair_id]

        # 价差 = price_a - hedge_ratio * price_b
        spread = price_a - pair.hedge_ratio * price_b

        return spread

    def generate_trading_signal(
        self,
        pair_id: str,
        price_history_a: np.ndarray,
        price_history_b: np.ndarray
    ) -> Optional[SpreadSignal]:
        """
        生成交易信号

        Args:
            pair_id: 交易对ID
            price_history_a: 资产A价格历史
            price_history_b: 资产B价格历史

        Returns:
            价差信号
        """
        if pair_id not in self.pairs:
            return None

        pair = self.pairs[pair_id]

        # 计算价差序列
        spread_series = price_history_a - pair.hedge_ratio * price_history_b

        # 计算Z-score
        z_score, mean_spread, std_spread = SpreadAnalyzer.calculate_z_score(
            spread_series, self.lookback_period
        )

        # 生成信号
        signal_type = SpreadAnalyzer.generate_signal(
            z_score, self.entry_threshold, self.exit_threshold
        )

        # 计算置信度（基于Z-score绝对值）
        confidence = min(1.0, abs(z_score) / self.entry_threshold)

        # 保存价差历史
        self._save_spread_history(
            pair_id, spread_series[-1], z_score,
            int(pd.Timestamp.now().timestamp() * 1000)
        )

        return SpreadSignal(
            pair_id=pair_id,
            signal_type=signal_type,
            z_score=z_score,
            entry_z_score=z_score if signal_type in [SignalType.LONG_SPREAD, SignalType.SHORT_SPREAD] else 0,
            current_spread=spread_series[-1],
            mean_spread=mean_spread,
            std_spread=std_spread,
            confidence=confidence,
            timestamp=int(pd.Timestamp.now().timestamp() * 1000)
        )

    def open_position(
        self,
        signal: SpreadSignal,
        size_usd: float,
        price_a: float,
        price_b: float
    ) -> Optional[str]:
        """
        开启配对仓位

        Args:
            signal: 价差信号
            size_usd: 仓位大小（USD）
            price_a: 资产A当前价格
            price_b: 资产B当前价格

        Returns:
            仓位ID
        """
        if signal.signal_type not in [SignalType.LONG_SPREAD, SignalType.SHORT_SPREAD]:
            return None

        pair = self.pairs[signal.pair_id]

        # 计算仓位大小
        if signal.signal_type == SignalType.LONG_SPREAD:
            # 做多价差：买入资产A，卖出资产B
            asset_a_size = size_usd / price_a
            asset_b_size = -(size_usd * pair.hedge_ratio) / price_b
        else:
            # 做空价差：卖出资产A，买入资产B
            asset_a_size = -(size_usd / price_a)
            asset_b_size = (size_usd * pair.hedge_ratio) / price_b

        # 创建仓位
        position_id = f"pair_{signal.pair_id}_{int(pd.Timestamp.now().timestamp() * 1000)}"

        position = PairPosition(
            position_id=position_id,
            pair_id=signal.pair_id,
            asset_a_size=asset_a_size,
            asset_b_size=asset_b_size,
            entry_spread=signal.current_spread,
            entry_z_score=signal.entry_z_score,
            signal_type=signal.signal_type,
            entry_time=int(pd.Timestamp.now().timestamp() * 1000),
            status="OPEN",
            pnl=0.0
        )

        # 保存仓位
        self._save_position(position)

        return position_id

    def close_position(
        self,
        position_id: str,
        price_a: float,
        price_b: float
    ) -> Optional[Dict]:
        """
        平仓配对仓位

        Args:
            position_id: 仓位ID
            price_a: 资产A当前价格
            price_b: 资产B当前价格

        Returns:
            平仓结果
        """
        # 加载仓位
        position = self._load_position(position_id)
        if not position or position.status != "OPEN":
            return None

        pair = self.pairs[position.pair_id]

        # 计算当前价差
        current_spread = price_a - pair.hedge_ratio * price_b

        # 计算盈亏
        if position.signal_type == SignalType.LONG_SPREAD:
            # 做多价差：价差上升盈利
            spread_change = current_spread - position.entry_spread
            pnl = spread_change * abs(position.asset_a_size)
        else:
            # 做空价差：价差下降盈利
            spread_change = position.entry_spread - current_spread
            pnl = spread_change * abs(position.asset_a_size)

        # 更新仓位
        position.status = "CLOSED"
        position.pnl = pnl

        # 保存
        self._update_position(position)

        return {
            "position_id": position_id,
            "entry_spread": position.entry_spread,
            "exit_spread": current_spread,
            "spread_change": spread_change,
            "pnl": pnl,
            "holding_period": (int(pd.Timestamp.now().timestamp() * 1000) - position.entry_time) / 1000 / 3600  # 小时
        }

    def _save_pair(self, pair: TradingPair):
        """保存交易对"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO trading_pairs
            (pair_id, asset_a, asset_b, hedge_ratio, cointegration_p_value, status, test_start_time, last_update_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pair.pair_id, pair.asset_a, pair.asset_b,
            pair.hedge_ratio, pair.cointegration_p_value, pair.status.value,
            pair.test_start_time, int(pd.Timestamp.now().timestamp() * 1000)
        ))
        conn.commit()
        conn.close()

    def _save_position(self, position: PairPosition):
        """保存仓位"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pair_positions
            (position_id, pair_id, asset_a_size, asset_b_size, entry_spread, entry_z_score,
             signal_type, entry_time, status, pnl, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.position_id, position.pair_id, position.asset_a_size, position.asset_b_size,
            position.entry_spread, position.entry_z_score, position.signal_type.value,
            position.entry_time, position.status, position.pnl,
            int(pd.Timestamp.now().timestamp() * 1000), int(pd.Timestamp.now().timestamp() * 1000)
        ))
        conn.commit()
        conn.close()

    def _load_position(self, position_id: str) -> Optional[PairPosition]:
        """加载仓位"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT position_id, pair_id, asset_a_size, asset_b_size, entry_spread,
                   entry_z_score, signal_type, entry_time, status, pnl
            FROM pair_positions
            WHERE position_id = ?
        """, (position_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return PairPosition(
            position_id=row[0],
            pair_id=row[1],
            asset_a_size=row[2],
            asset_b_size=row[3],
            entry_spread=row[4],
            entry_z_score=row[5],
            signal_type=SignalType(row[6]),
            entry_time=row[7],
            status=row[8],
            pnl=row[9]
        )

    def _update_position(self, position: PairPosition):
        """更新仓位"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE pair_positions
            SET status = ?, pnl = ?, updated_at = ?
            WHERE position_id = ?
        """, (
            position.status, position.pnl, int(pd.Timestamp.now().timestamp() * 1000),
            position.position_id
        ))
        conn.commit()
        conn.close()

    def _save_spread_history(self, pair_id: str, spread: float, z_score: float, timestamp: int):
        """保存价差历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO spread_history
            (pair_id, spread, z_score, timestamp)
            VALUES (?, ?, ?, ?)
        """, (pair_id, spread, z_score, timestamp))
        conn.commit()
        conn.close()

    def get_active_pairs(self) -> List[Dict]:
        """获取活跃的交易对"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pair_id, asset_a, asset_b, hedge_ratio, cointegration_p_value, status
            FROM trading_pairs
            WHERE status = 'COINTEGRATED'
        """)

        pairs = []
        for row in cursor.fetchall():
            pairs.append({
                "pair_id": row[0],
                "asset_a": row[1],
                "asset_b": row[2],
                "hedge_ratio": row[3],
                "cointegration_p_value": row[4],
                "status": row[5]
            })

        conn.close()
        return pairs


def main():
    parser = argparse.ArgumentParser(description="统计套利（Pairs Trading）")
    parser.add_argument("--action", choices=["test_cointegration", "generate_signal", "open_position", "close_position", "list_pairs"], required=True, help="操作类型")
    parser.add_argument("--asset-a", help="资产A名称")
    parser.add_argument("--asset-b", help="资产B名称")
    parser.add_argument("--price-a", type=float, help="资产A当前价格")
    parser.add_argument("--price-b", type=float, help="资产B当前价格")
    parser.add_argument("--price-history-a", help="资产A价格历史（JSON数组）")
    parser.add_argument("--price-history-b", help="资产B价格历史（JSON数组）")
    parser.add_argument("--pair-id", help="交易对ID")
    parser.add_argument("--size", type=float, help="仓位大小（USD）")
    parser.add_argument("--position-id", help="仓位ID")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    try:
        # 加载配置
        config = {}
        if args.config:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)

        # 创建策略
        strategy = PairsTradingStrategy(config)

        logger.info("=" * 70)
        logger.info("✅ 统计套利（Pairs Trading）- v1.0.3扩展")
        logger.info("=" * 70)

        if args.action == "test_cointegration":
            if not args.asset_a or not args.asset_b or not args.price_history_a or not args.price_history_b:
                logger.info("错误: 请提供 --asset-a, --asset-b, --price-history-a, --price-history-b 参数")
                sys.exit(1)

            price_history_a = np.array(json.loads(args.price_history_a))
            price_history_b = np.array(json.loads(args.price_history_b))

            # 测试协整
            result = strategy.test_cointegration(
                args.asset_a, args.asset_b, price_history_a, price_history_b
            )

            if result:
                logger.info(f"\n协整检验结果:")
                logger.info(f"  交易对: {result['pair_id']}")
                logger.info(f"  是否协整: {'✅ 是' if result['is_cointegrated'] else '❌ 否'}")
                logger.info(f"  P值: {result['p_value']:.4f}")
                logger.info(f"  对冲比率: {result['hedge_ratio']:.4f}")
                logger.info(f"  检验统计量: {result['test_statistic']:.4f}")
                logger.info(f"  临界值: {result['critical_value']:.4f}")

                output = {
                    "status": "success",
                    "result": result
                }
            else:
                logger.info(f"\n❌ 协整检验失败")
                output = {
                    "status": "error",
                    "message": "协整检验失败（数据不足或计算错误）"
                }

        elif args.action == "generate_signal":
            if not args.pair_id or not args.price_history_a or not args.price_history_b:
                logger.info("错误: 请提供 --pair-id, --price-history-a, --price-history-b 参数")
                sys.exit(1)

            price_history_a = np.array(json.loads(args.price_history_a))
            price_history_b = np.array(json.loads(args.price_history_b))

            # 生成信号
            signal = strategy.generate_trading_signal(
                args.pair_id, price_history_a, price_history_b
            )

            if signal:
                logger.info(f"\n交易信号:")
                logger.info(f"  交易对: {signal.pair_id}")
                logger.info(f"  信号类型: {signal.signal_type.value}")
                logger.info(f"  Z-score: {signal.z_score:.2f}")
                logger.info(f"  当前价差: {signal.current_spread:.2f}")
                logger.info(f"  均价差: {signal.mean_spread:.2f}")
                logger.info(f"  标准差: {signal.std_spread:.2f}")
                logger.info(f"  置信度: {signal.confidence:.2%}")

                output = {
                    "status": "success",
                    "signal": {
                        "pair_id": signal.pair_id,
                        "signal_type": signal.signal_type.value,
                        "z_score": signal.z_score,
                        "current_spread": signal.current_spread,
                        "mean_spread": signal.mean_spread,
                        "std_spread": signal.std_spread,
                        "confidence": signal.confidence
                    }
                }
            else:
                logger.info(f"\n❌ 信号生成失败")
                output = {
                    "status": "error",
                    "message": "信号生成失败（交易对不存在或数据不足）"
                }

        elif args.action == "open_position":
            if not args.pair_id or not args.size or not args.price_a or not args.price_b:
                logger.info("错误: 请提供完整参数")
                sys.exit(1)

            # 模拟生成信号
            signal = SpreadSignal(
                pair_id=args.pair_id,
                signal_type=SignalType.LONG_SPREAD,  # 默认做多价差
                z_score=2.5,
                entry_z_score=2.5,
                current_spread=100.0,
                mean_spread=0.0,
                std_spread=40.0,
                confidence=0.8,
                timestamp=int(pd.Timestamp.now().timestamp() * 1000)
            )

            # 开仓
            position_id = strategy.open_position(signal, args.size, args.price_a, args.price_b)

            if position_id:
                logger.info(f"\n✅ 配对仓位开启成功")
                logger.info(f"  仓位ID: {position_id}")
                logger.info(f"  交易对: {args.pair_id}")
                logger.info(f"  仓位大小: ${args.size:,.2f}")

                output = {
                    "status": "success",
                    "position_id": position_id,
                    "size": args.size
                }
            else:
                logger.info(f"\n❌ 配对仓位开启失败")
                output = {
                    "status": "error",
                    "message": "配对仓位开启失败"
                }

        elif args.action == "list_pairs":
            # 获取活跃交易对
            pairs = strategy.get_active_pairs()

            logger.info(f"\n活跃交易对 ({len(pairs)}):")

            for pair in pairs:
                logger.info(f"\n  交易对: {pair['pair_id']}")
                logger.info(f"    资产A: {pair['asset_a']}")
                logger.info(f"    资产B: {pair['asset_b']}")
                logger.info(f"    对冲比率: {pair['hedge_ratio']:.4f}")
                logger.info(f"    协整P值: {pair['cointegration_p_value']:.4f}")

            output = {
                "status": "success",
                "pairs_count": len(pairs),
                "pairs": pairs
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
