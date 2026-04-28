#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("database_manager")
except ImportError:
    import logging
    logger = logging.getLogger("database_manager")
"""
数据库持久层 - V3核心模块
提供高性能数据持久化和查询能力
"""

import sqlite3
import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import threading


@dataclass
class TradeRecord:
    """交易记录"""
    trade_id: str
    symbol: str
    side: str  # 'BUY' or 'SELL'
    price: float
    quantity: float
    timestamp: float
    strategy: str
    pnl: float = 0.0
    commission: float = 0.0
    signal_strength: float = 0.0


@dataclass
class MarketTick:
    """市场行情"""
    timestamp: float
    symbol: str
    bid: float
    ask: float
    mid_price: float
    volume: float
    volatility: float = 0.0


class DatabaseManager:
    """数据库管理器（v1.0.3优化：连接池管理）"""

    def __init__(self, db_path: str = "./data/trading.db"):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

        # v1.0.3优化：使用长期连接，避免频繁创建/关闭
        self._connection = None
        self._is_initialized = False

        # 初始化数据库
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接（v1.0.3优化：复用连接 + v1.0.3修复：线程安全检查）"""
        # BUG #7修复：检查连接是否已关闭
        if self._connection is not None:
            try:
                # 尝试执行简单查询检查连接是否有效
                self._connection.execute("SELECT 1")
            except sqlite3.Error:
                # 连接已关闭或无效，重新创建
                self._connection = None

        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close_connection(self):
        """关闭数据库连接（v1.0.3新增）"""
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None

    def __del__(self):
        """析构函数：确保连接关闭"""
        self.close_connection()

    def _init_database(self):
        """初始化数据库表结构"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 交易记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    strategy TEXT NOT NULL,
                    pnl REAL DEFAULT 0.0,
                    commission REAL DEFAULT 0.0,
                    signal_strength REAL DEFAULT 0.0,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)

            # 市场行情表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_ticks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    bid REAL NOT NULL,
                    ask REAL NOT NULL,
                    mid_price REAL NOT NULL,
                    volume REAL NOT NULL,
                    volatility REAL DEFAULT 0.0
                )
            """)

            # 策略性能表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_performance (
                    strategy_id TEXT PRIMARY KEY,
                    total_trades INTEGER DEFAULT 0,
                    win_trades INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0.0,
                    max_drawdown REAL DEFAULT 0.0,
                    sharpe_ratio REAL DEFAULT 0.0,
                    last_updated REAL DEFAULT (strftime('%s', 'now'))
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticks_timestamp ON market_ticks(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticks_symbol ON market_ticks(symbol)")

            conn.commit()
            # v1.0.3优化：不关闭连接，复用连接

    def save_trade(self, trade: TradeRecord) -> bool:
        """保存交易记录"""
        try:
            with self.lock:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT OR REPLACE INTO trades
                    (trade_id, symbol, side, price, quantity, timestamp, strategy, pnl, commission, signal_strength)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade.trade_id, trade.symbol, trade.side, trade.price,
                    trade.quantity, trade.timestamp, trade.strategy,
                    trade.pnl, trade.commission, trade.signal_strength
                ))

                conn.commit()
                # v1.0.3优化：不关闭连接，复用连接
                return True
        except Exception as e:
            logger.error(f"[Database] 保存交易记录失败: {e}")
            return False

    def save_market_tick(self, tick: MarketTick) -> bool:
        """保存市场行情"""
        try:
            with self.lock:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO market_ticks
                    (timestamp, symbol, bid, ask, mid_price, volume, volatility)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    tick.timestamp, tick.symbol, tick.bid, tick.ask,
                    tick.mid_price, tick.volume, tick.volatility
                ))

                conn.commit()
                conn.close()
                return True
        except Exception as e:
            logger.error(f"[Database] 保存市场行情失败: {e}")
            return False

    def get_recent_trades(self, symbol: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近交易记录"""
        try:
            with self.lock:
                conn = self._get_connection()
                cursor = conn.cursor()

                if symbol:
                    cursor.execute("""
                        SELECT * FROM trades
                        WHERE symbol = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (symbol, limit))
                else:
                    cursor.execute("""
                        SELECT * FROM trades
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (limit,))

                rows = cursor.fetchall()
                conn.close()

                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"[Database] 查询交易记录失败: {e}")
            return []

    def get_market_ticks_range(self, start_time: float, end_time: float,
                               symbol: str = None) -> List[Dict[str, Any]]:
        """获取时间范围内的市场行情"""
        try:
            with self.lock:
                conn = self._get_connection()
                cursor = conn.cursor()

                if symbol:
                    cursor.execute("""
                        SELECT * FROM market_ticks
                        WHERE timestamp BETWEEN ? AND ?
                        AND symbol = ?
                        ORDER BY timestamp ASC
                    """, (start_time, end_time, symbol))
                else:
                    cursor.execute("""
                        SELECT * FROM market_ticks
                        WHERE timestamp BETWEEN ? AND ?
                        ORDER BY timestamp ASC
                    """, (start_time, end_time))

                rows = cursor.fetchall()
                conn.close()

                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"[Database] 查询市场行情失败: {e}")
            return []

    def update_strategy_performance(self, strategy_id: str, metrics: Dict[str, float]) -> bool:
        """更新策略性能指标"""
        try:
            with self.lock:
                conn = self._get_connection()
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO strategy_performance
                    (strategy_id, total_trades, win_trades, total_pnl, max_drawdown, sharpe_ratio, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(strategy_id) DO UPDATE SET
                        total_trades = excluded.total_trades,
                        win_trades = excluded.win_trades,
                        total_pnl = excluded.total_pnl,
                        max_drawdown = excluded.max_drawdown,
                        sharpe_ratio = excluded.sharpe_ratio,
                        last_updated = excluded.last_updated
                """, (
                    strategy_id,
                    metrics.get('total_trades', 0),
                    metrics.get('win_trades', 0),
                    metrics.get('total_pnl', 0.0),
                    metrics.get('max_drawdown', 0.0),
                    metrics.get('sharpe_ratio', 0.0),
                    time.time()
                ))

                conn.commit()
                conn.close()
                return True
        except Exception as e:
            logger.error(f"[Database] 更新策略性能失败: {e}")
            return False

    def get_statistics(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        try:
            with self.lock:
                conn = self._get_connection()
                cursor = conn.cursor()

                # 交易记录数
                cursor.execute("SELECT COUNT(*) as count FROM trades")
                total_trades = cursor.fetchone()['count']

                # 市场行情数
                cursor.execute("SELECT COUNT(*) as count FROM market_ticks")
                total_ticks = cursor.fetchone()['count']

                # 策略数
                cursor.execute("SELECT COUNT(DISTINCT strategy) as count FROM trades")
                strategy_count = cursor.fetchone()['count']

                # 数据库大小
                db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

                conn.close()

                return {
                    'total_trades': total_trades,
                    'total_market_ticks': total_ticks,
                    'strategy_count': strategy_count,
                    'database_size_bytes': db_size,
                    'database_path': str(self.db_path)
                }
        except Exception as e:
            logger.error(f"[Database] 获取统计信息失败: {e}")
            return {}


# 命令行测试
def main():
    """测试数据库功能"""
    db = DatabaseManager("./data/test_trading.db")

    # 测试保存交易
    trade = TradeRecord(
        trade_id="test_001",
        symbol="BTCUSDT",
        side="BUY",
        price=50000.0,
        quantity=0.1,
        timestamp=time.time(),
        strategy="MA_CROSS",
        pnl=100.0
    )
    logger.info(f"保存交易: {db.save_trade(trade)}")

    # 测试保存行情
    tick = MarketTick(
        timestamp=time.time(),
        symbol="BTCUSDT",
        bid=49999.0,
        ask=50001.0,
        mid_price=50000.0,
        volume=1000.0,
        volatility=0.008
    )
    logger.info(f"保存行情: {db.save_market_tick(tick)}")

    # 查询交易
    trades = db.get_recent_trades(symbol="BTCUSDT", limit=10)
    logger.info(f"查询到 {len(trades)} 条交易")

    # 统计信息
    stats = db.get_statistics()
    logger.info(f"数据库统计: {json.dumps(stats, ensure_ascii=False, indent=2)}")

    logger.info("\n数据库测试: PASS")


if __name__ == "__main__":
    main()
