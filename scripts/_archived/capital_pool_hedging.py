#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("capital_pool_hedging")
except ImportError:
    import logging
    logger = logging.getLogger("capital_pool_hedging")
"""
资金池隔离与对冲套利模块 - v1.0.3扩展
定位：开单和持仓管理环节的风险控制与套利增强
核心策略：独立资金池、永续/现货对冲、资金费率套利、价差套利
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import sqlite3
import os


class PoolType(Enum):
    """资金池类型"""
    SPOT = "SPOT"
    PERPETUAL = "PERPETUAL"
    HEDGING = "HEDGING"


class HedgeDirection(Enum):
    """对冲方向"""
    LONG_PERP_SHORT_SPOT = "LONG_PERP_SHORT_SPOT"  # 永续做多，现货做空
    SHORT_PERP_LONG_SPOT = "SHORT_PERP_LONG_SPOT"  # 永续做空，现货做多


@dataclass
class CapitalPool:
    """资金池"""
    pool_id: str
    pool_type: PoolType
    api_key: str
    api_secret: str
    total_balance: float
    available_balance: float
    locked_balance: float
    positions: Dict[str, Dict]


@dataclass
class HedgePosition:
    """对冲仓位"""
    position_id: str
    direction: HedgeDirection
    perp_symbol: str
    spot_symbol: str
    perp_size: float
    spot_size: float
    perp_entry_price: float
    spot_entry_price: float
    funding_rate: float
    price_spread: float
    open_time: int
    status: str


class CapitalPoolManager:
    """资金池管理器"""

    def __init__(self, db_path: str = "state/capital_pools.db"):
        """
        初始化资金池管理器

        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
        self.pools: Dict[str, CapitalPool] = {}

        # 创建数据库目录
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 初始化数据库
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 创建资金池表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS capital_pools (
                pool_id TEXT PRIMARY KEY,
                pool_type TEXT NOT NULL,
                api_key TEXT NOT NULL,
                api_secret TEXT NOT NULL,
                total_balance REAL NOT NULL,
                available_balance REAL NOT NULL,
                locked_balance REAL NOT NULL,
                positions TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        # 创建对冲仓位表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hedge_positions (
                position_id TEXT PRIMARY KEY,
                direction TEXT NOT NULL,
                perp_symbol TEXT NOT NULL,
                spot_symbol TEXT NOT NULL,
                perp_size REAL NOT NULL,
                spot_size REAL NOT NULL,
                perp_entry_price REAL NOT NULL,
                spot_entry_price REAL NOT NULL,
                funding_rate REAL NOT NULL,
                price_spread REAL NOT NULL,
                open_time INTEGER NOT NULL,
                close_time INTEGER,
                status TEXT NOT NULL,
                pnl REAL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pool_type ON capital_pools(pool_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_position_status ON hedge_positions(status)")

        conn.commit()
        conn.close()

    def create_pool(
        self,
        pool_id: str,
        pool_type: PoolType,
        api_key: str,
        api_secret: str,
        initial_balance: float
    ) -> bool:
        """
        创建资金池

        Args:
            pool_id: 资金池ID
            pool_type: 资金池类型
            api_key: API密钥
            api_secret: API密钥
            initial_balance: 初始余额

        Returns:
            是否成功
        """
        pool = CapitalPool(
            pool_id=pool_id,
            pool_type=pool_type,
            api_key=api_key,
            api_secret=api_secret,
            total_balance=initial_balance,
            available_balance=initial_balance,
            locked_balance=0.0,
            positions={}
        )

        self.pools[pool_id] = pool

        # 保存到数据库
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO capital_pools
            (pool_id, pool_type, api_key, api_secret, total_balance, available_balance, locked_balance, positions, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pool_id,
            pool_type.value,
            api_key,
            api_secret,
            initial_balance,
            initial_balance,
            0.0,
            json.dumps({
        ),
            int(time.time() * 1000),
            int(time.time() * 1000)
        ))
        conn.commit()
        conn.close()

        return True

    def reserve(self, pool_id: str, amount: float) -> bool:
        """
        预留资金

        Args:
            pool_id: 资金池ID
            amount: 预留金额

        Returns:
            是否成功
        """
        if pool_id not in self.pools:
            return False

        pool = self.pools[pool_id]

        if pool.available_balance < amount:
            return False

        pool.available_balance -= amount
        pool.locked_balance += amount

        # 更新数据库
        self._update_pool(pool)

        return True

    def release(self, pool_id: str, amount: float) -> bool:
        """
        释放资金

        Args:
            pool_id: 资金池ID
            amount: 释放金额

        Returns:
            是否成功
        """
        if pool_id not in self.pools:
            return False

        pool = self.pools[pool_id]

        if pool.locked_balance < amount:
            amount = pool.locked_balance

        pool.locked_balance -= amount
        pool.available_balance += amount

        # 更新数据库
        self._update_pool(pool)

        return True

    def _update_pool(self, pool: CapitalPool):
        """更新资金池数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE capital_pools
            SET total_balance = ?, available_balance = ?, locked_balance = ?, updated_at = ?
            WHERE pool_id = ?
        """, (
            pool.total_balance,
            pool.available_balance,
            pool.locked_balance,
            int(time.time() * 1000),
            pool.pool_id
        ))
        conn.commit()
        conn.close()

    def get_pool_balance(self, pool_id: str) -> Optional[Dict]:
        """获取资金池余额"""
        if pool_id not in self.pools:
            return None

        pool = self.pools[pool_id]
        return {
            "pool_id": pool_id,
            "pool_type": pool.pool_type.value,
            "total_balance": pool.total_balance,
            "available_balance": pool.available_balance,
            "locked_balance": pool.locked_balance,
            "utilization": pool.locked_balance / pool.total_balance if pool.total_balance > 0 else 0
        }


class HedgingArbitrage:
    """对冲套利策略"""

    def __init__(
        self,
        pool_manager: CapitalPoolManager,
        perp_pool_id: str,
        spot_pool_id: str,
        config: Optional[Dict] = None
    ):
        """
        初始化对冲套利

        Args:
            pool_manager: 资金池管理器
            perp_pool_id: 永续资金池ID
            spot_pool_id: 现货资金池ID
            config: 配置字典
        """
        self.pool_manager = pool_manager
        self.perp_pool_id = perp_pool_id
        self.spot_pool_id = spot_pool_id
        self.config = config or {}

        # 套利配置
        self.funding_rate_threshold = self.config.get('funding_rate_threshold', 0.01)  # 1%资金费率阈值
        self.price_spread_threshold = self.config.get('price_spread_threshold', 0.005)  # 0.5%价差阈值
        self.position_size_ratio = self.config.get('position_size_ratio', 0.3)  # 单次对冲占用30%资金
        self.max_hedge_positions = self.config.get('max_hedge_positions', 3)  # 最大对冲仓位数

        # 市场状态判断（复用market_regime_optimizer）
        self.market_regime_config = self.config.get('market_regime', {})

        # 数据库路径
        self.db_path = self.config.get('db_path', 'state/hedge_positions.db')
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def check_arbitrage_opportunity(
        self,
        perp_price: float,
        spot_price: float,
        funding_rate: float,
        market_state: Dict
    ) -> Dict:
        """
        检查套利机会

        Args:
            perp_price: 永续价格
            spot_price: 现货价格
            funding_rate: 资金费率
            market_state: 市场状态

        Returns:
            套利机会信息
        """
        # 计算价差
        price_spread = (perp_price - spot_price) / spot_price

        # 判断市场状态是否适合套利
        volatility = market_state.get('volatility', 0)
        adx = market_state.get('adx', 0)

        # 套利窗口判断：低波动 + 稳定资金费率
        market_suitable = (
            volatility < 0.02 and  # 低波动
            adx < 25 and  # 震荡市
            abs(funding_rate) > self.funding_rate_threshold  # 有利可图的资金费率
        )

        opportunity = {
            "has_opportunity": False,
            "direction": None,
            "funding_rate": funding_rate,
            "price_spread": price_spread,
            "market_suitable": market_suitable,
            "reason": ""
        }

        # 判断套利方向
        if market_suitable:
            if funding_rate > self.funding_rate_threshold:
                # 正资金费率：做多现货，做空永续（收取资金费）
                opportunity["has_opportunity"] = True
                opportunity["direction"] = "SHORT_PERP_LONG_SPOT"
                opportunity["reason"] = f"正资金费率{funding_rate*100:.2f}%，适合做空永续做多现货"
            elif funding_rate < -self.funding_rate_threshold:
                # 负资金费率：做多永续，做空现货（支付负资金费率=收取）
                opportunity["has_opportunity"] = True
                opportunity["direction"] = "LONG_PERP_SHORT_SPOT"
                opportunity["reason"] = f"负资金费率{funding_rate*100:.2f}%，适合做多永续做空现货"

        return opportunity

    def open_hedge_position(
        self,
        direction: HedgeDirection,
        perp_symbol: str,
        spot_symbol: str,
        perp_price: float,
        spot_price: float,
        funding_rate: float,
        size_usd: float
    ) -> Optional[str]:
        """
        开启对冲仓位

        Args:
            direction: 对冲方向
            perp_symbol: 永续交易对
            spot_symbol: 现货交易对
            perp_price: 永续价格
            spot_price: 现货价格
            funding_rate: 资金费率
            size_usd: 仓位大小（USD）

        Returns:
            仓位ID
        """
        # 检查资金池余额
        perp_balance = self.pool_manager.get_pool_balance(self.perp_pool_id)
        spot_balance = self.pool_manager.get_pool_balance(self.spot_pool_id)

        if not perp_balance or not spot_balance:
            return None

        # 检查可用资金
        half_size = size_usd / 2
        if perp_balance['available_balance'] < half_size or spot_balance['available_balance'] < half_size:
            return None

        # 预留资金
        if not self.pool_manager.reserve(self.perp_pool_id, half_size):
            return None
        if not self.pool_manager.reserve(self.spot_pool_id, half_size):
            # 回滚预留
            self.pool_manager.release(self.perp_pool_id, half_size)
            return None

        # 计算仓位大小
        perp_size = half_size / perp_price
        spot_size = half_size / spot_price

        # 创建对冲仓位
        position_id = f"hedge_{int(time.time() * 1000)}"

        hedge_position = HedgePosition(
            position_id=position_id,
            direction=direction,
            perp_symbol=perp_symbol,
            spot_symbol=spot_symbol,
            perp_size=perp_size,
            spot_size=spot_size,
            perp_entry_price=perp_price,
            spot_entry_price=spot_price,
            funding_rate=funding_rate,
            price_spread=(perp_price - spot_price) / spot_price,
            open_time=int(time.time() * 1000),
            status="OPEN"
        )

        # 保存到数据库
        self._save_hedge_position(hedge_position)

        return position_id

    def close_hedge_position(
        self,
        position_id: str,
        perp_price: float,
        spot_price: float
    ) -> Optional[Dict]:
        """
        平仓对冲仓位

        Args:
            position_id: 仓位ID
            perp_price: 永续平仓价格
            spot_price: 现货平仓价格

        Returns:
            平仓结果
        """
        # 从数据库加载仓位
        position = self._load_hedge_position(position_id)
        if not position or position.status != "OPEN":
            return None

        # 计算盈亏
        perp_pnl = 0
        spot_pnl = 0

        if position.direction == HedgeDirection.LONG_PERP_SHORT_SPOT:
            # 永续做多
            perp_pnl = (perp_price - position.perp_entry_price) * position.perp_size
            # 现货做空
            spot_pnl = (position.spot_entry_price - spot_price) * position.spot_size
        elif position.direction == HedgeDirection.SHORT_PERP_LONG_SPOT:
            # 永续做空
            perp_pnl = (position.perp_entry_price - perp_price) * position.perp_size
            # 现货做多
            spot_pnl = (spot_price - position.spot_entry_price) * position.spot_size

        total_pnl = perp_pnl + spot_pnl

        # 释放资金
        half_size = position.perp_size * position.perp_entry_price
        self.pool_manager.release(self.perp_pool_id, half_size)
        self.pool_manager.release(self.spot_pool_id, half_size)

        # 更新仓位状态
        position.status = "CLOSED"
        position.pnl = total_pnl

        # 更新数据库
        self._update_hedge_position(position)

        return {
            "position_id": position_id,
            "perp_pnl": perp_pnl,
            "spot_pnl": spot_pnl,
            "total_pnl": total_pnl,
            "holding_period": (int(time.time() * 1000) - position.open_time) / 1000 / 3600  # 小时
        }

    def _save_hedge_position(self, position: HedgePosition):
        """保存对冲仓位"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO hedge_positions
            (position_id, direction, perp_symbol, spot_symbol, perp_size, spot_size,
             perp_entry_price, spot_entry_price, funding_rate, price_spread,
             open_time, status, pnl, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.position_id,
            position.direction.value,
            position.perp_symbol,
            position.spot_symbol,
            position.perp_size,
            position.spot_size,
            position.perp_entry_price,
            position.spot_entry_price,
            position.funding_rate,
            position.price_spread,
            position.open_time,
            position.status,
            position.pnl,
            int(time.time() * 1000),
            int(time.time() * 1000)
        ))
        conn.commit()
        conn.close()

    def _load_hedge_position(self, position_id: str) -> Optional[HedgePosition]:
        """加载对冲仓位"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT position_id, direction, perp_symbol, spot_symbol, perp_size, spot_size,
                   perp_entry_price, spot_entry_price, funding_rate, price_spread,
                   open_time, status, pnl
            FROM hedge_positions
            WHERE position_id = ?
        """, (position_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return HedgePosition(
            position_id=row[0],
            direction=HedgeDirection(row[1]),
            perp_symbol=row[2],
            spot_symbol=row[3],
            perp_size=row[4],
            spot_size=row[5],
            perp_entry_price=row[6],
            spot_entry_price=row[7],
            funding_rate=row[8],
            price_spread=row[9],
            open_time=row[10],
            status=row[11],
            pnl=row[12] if row[12] else 0
        )

    def _update_hedge_position(self, position: HedgePosition):
        """更新对冲仓位"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE hedge_positions
            SET status = ?, pnl = ?, updated_at = ?
            WHERE position_id = ?
        """, (
            position.status,
            position.pnl,
            int(time.time() * 1000),
            position.position_id
        ))
        conn.commit()
        conn.close()

    def get_open_positions(self) -> List[Dict]:
        """获取所有开仓的对冲仓位"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT position_id, direction, perp_symbol, spot_symbol, perp_size, spot_size,
                   perp_entry_price, spot_entry_price, funding_rate, price_spread,
                   open_time, status, pnl
            FROM hedge_positions
            WHERE status = 'OPEN'
        """)

        positions = []
        for row in cursor.fetchall():
            positions.append({
                "position_id": row[0],
                "direction": row[1],
                "perp_symbol": row[2],
                "spot_symbol": row[3],
                "perp_size": row[4],
                "spot_size": row[5],
                "perp_entry_price": row[6],
                "spot_entry_price": row[7],
                "funding_rate": row[8],
                "price_spread": row[9],
                "open_time": row[10],
                "status": row[11],
                "pnl": row[12]
            })

        conn.close()
        return positions


def main():
    parser = argparse.ArgumentParser(description="资金池隔离与对冲套利")
    parser.add_argument("--action", choices=["create_pool", "check_opportunity", "open_hedge", "close_hedge", "list_positions", "pool_balance"], required=True, help="操作类型")
    parser.add_argument("--pool-id", help="资金池ID")
    parser.add_argument("--pool-type", choices=["SPOT", "PERPETUAL"], help="资金池类型")
    parser.add_argument("--api-key", help="API密钥")
    parser.add_argument("--api-secret", help="API密钥")
    parser.add_argument("--balance", type=float, help="初始余额")
    parser.add_argument("--perp-pool-id", help="永续资金池ID")
    parser.add_argument("--spot-pool-id", help="现货资金池ID")
    parser.add_argument("--perp-price", type=float, help="永续价格")
    parser.add_argument("--spot-price", type=float, help="现货价格")
    parser.add_argument("--funding-rate", type=float, help="资金费率")
    parser.add_argument("--market-state", help="市场状态JSON字符串")
    parser.add_argument("--direction", choices=["LONG_PERP_SHORT_SPOT", "SHORT_PERP_LONG_SPOT"], help="对冲方向")
    parser.add_argument("--perp-symbol", help="永续交易对")
    parser.add_argument("--spot-symbol", help="现货交易对")
    parser.add_argument("--size", type=float, help="仓位大小（USD）")
    parser.add_argument("--position-id", help="仓位ID")

    args = parser.parse_args()

    try:
        # 创建资金池管理器
        pool_manager = CapitalPoolManager()

        logger.info("=" * 70)
        logger.info("✅ 资金池隔离与对冲套利 - v1.0.3扩展")
        logger.info("=" * 70)

        if args.action == "create_pool":
            if not args.pool_id or not args.pool_type or not args.api_key or not args.api_secret:
                logger.info("错误: 请提供 --pool-id, --pool-type, --api-key, --api-secret 参数")
                sys.exit(1)

            balance = args.balance if args.balance else 100000

            success = pool_manager.create_pool(
                pool_id=args.pool_id,
                pool_type=PoolType(args.pool_type),
                api_key=args.api_key,
                api_secret=args.api_secret,
                initial_balance=balance
            )

            if success:
                logger.info(f"\n✅ 资金池创建成功")
                logger.info(f"  资金池ID: {args.pool_id}")
                logger.info(f"  资金池类型: {args.pool_type}")
                logger.info(f"  初始余额: ${balance:,.2f}")

                output = {
                    "status": "success",
                    "pool_id": args.pool_id,
                    "pool_type": args.pool_type,
                    "initial_balance": balance
                }
            else:
                logger.info(f"\n❌ 资金池创建失败")
                output = {
                    "status": "error",
                    "message": "资金池创建失败"
                }

        elif args.action == "pool_balance":
            if not args.pool_id:
                logger.info("错误: 请提供 --pool-id 参数")
                sys.exit(1)

            balance = pool_manager.get_pool_balance(args.pool_id)

            if balance:
                logger.info(f"\n资金池余额:")
                logger.info(f"  资金池ID: {balance['pool_id']}")
                logger.info(f"  资金池类型: {balance['pool_type']}")
                logger.info(f"  总余额: ${balance['total_balance']:,.2f}")
                logger.info(f"  可用余额: ${balance['available_balance']:,.2f}")
                logger.info(f"  锁定余额: ${balance['locked_balance']:,.2f}")
                logger.info(f"  利用率: {balance['utilization']*100:.1f}%")

                output = {
                    "status": "success",
                    "balance": balance
                }
            else:
                logger.info(f"\n❌ 资金池不存在")
                output = {
                    "status": "error",
                    "message": "资金池不存在"
                }

        elif args.action == "check_opportunity":
            if not args.perp_pool_id or not args.spot_pool_id or not args.perp_price or not args.spot_price or not args.funding_rate or not args.market_state:
                logger.info("错误: 请提供完整参数")
                sys.exit(1)

            # 创建对冲套利策略
            hedging = HedgingArbitrage(
                pool_manager=pool_manager,
                perp_pool_id=args.perp_pool_id,
                spot_pool_id=args.spot_pool_id
            )

            market_state = json.loads(args.market_state)

            # 检查套利机会
            opportunity = hedging.check_arbitrage_opportunity(
                perp_price=args.perp_price,
                spot_price=args.spot_price,
                funding_rate=args.funding_rate,
                market_state=market_state
            )

            logger.info(f"\n套利机会检查:")
            logger.info(f"  永续价格: ${args.perp_price:,.2f}")
            logger.info(f"  现货价格: ${args.spot_price:,.2f}")
            logger.info(f"  资金费率: {args.funding_rate*100:.2f}%")
            logger.info(f"  价差: {opportunity['price_spread']*100:.2f}%")
            logger.info(f"  市场适合: {'✅ 是' if opportunity['market_suitable'] else '❌ 否'}")
            logger.info(f"  有套利机会: {'✅ 是' if opportunity['has_opportunity'] else '❌ 否'}")

            if opportunity['has_opportunity']:
                logger.info(f"  套利方向: {opportunity['direction']}")
                logger.info(f"  套利理由: {opportunity['reason']}")

            output = {
                "status": "success",
                "opportunity": opportunity
            }

        elif args.action == "open_hedge":
            if not args.perp_pool_id or not args.spot_pool_id or not args.direction or not args.perp_symbol or not args.spot_symbol or not args.perp_price or not args.spot_price or not args.funding_rate or not args.size:
                logger.info("错误: 请提供完整参数")
                sys.exit(1)

            # 创建对冲套利策略
            hedging = HedgingArbitrage(
                pool_manager=pool_manager,
                perp_pool_id=args.perp_pool_id,
                spot_pool_id=args.spot_pool_id
            )

            # 开启对冲仓位
            position_id = hedging.open_hedge_position(
                direction=HedgeDirection(args.direction),
                perp_symbol=args.perp_symbol,
                spot_symbol=args.spot_symbol,
                perp_price=args.perp_price,
                spot_price=args.spot_price,
                funding_rate=args.funding_rate,
                size_usd=args.size
            )

            if position_id:
                logger.info(f"\n✅ 对冲仓位开启成功")
                logger.info(f"  仓位ID: {position_id}")
                logger.info(f"  对冲方向: {args.direction}")
                logger.info(f"  永续交易对: {args.perp_symbol}")
                logger.info(f"  现货交易对: {args.spot_symbol}")
                logger.info(f"  仓位大小: ${args.size:,.2f}")

                output = {
                    "status": "success",
                    "position_id": position_id,
                    "direction": args.direction,
                    "size": args.size
                }
            else:
                logger.info(f"\n❌ 对冲仓位开启失败")
                output = {
                    "status": "error",
                    "message": "对冲仓位开启失败（可能是资金不足或参数错误）"
                }

        elif args.action == "list_positions":
            if not args.perp_pool_id or not args.spot_pool_id:
                logger.info("错误: 请提供 --perp-pool-id 和 --spot-pool-id 参数")
                sys.exit(1)

            # 创建对冲套利策略
            hedging = HedgingArbitrage(
                pool_manager=pool_manager,
                perp_pool_id=args.perp_pool_id,
                spot_pool_id=args.spot_pool_id
            )

            # 获取开仓仓位
            positions = hedging.get_open_positions()

            logger.info(f"\n开仓对冲仓位 ({len(positions)}):")

            for pos in positions:
                logger.info(f"\n  仓位ID: {pos['position_id']}")
                logger.info(f"    对冲方向: {pos['direction']}")
                logger.info(f"    永续: {pos['perp_symbol']} @ ${pos['perp_entry_price']:,.2f}")
                logger.info(f"    现货: {pos['spot_symbol']} @ ${pos['spot_entry_price']:,.2f}")
                logger.info(f"    资金费率: {pos['funding_rate']*100:.2f}%")
                logger.info(f"    价差: {pos['price_spread']*100:.2f}%")

            output = {
                "status": "success",
                "positions_count": len(positions),
                "positions": positions
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
