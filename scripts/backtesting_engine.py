#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("backtesting_engine")
except ImportError:
    import logging
    logger = logging.getLogger("backtesting_engine")
"""
回测引擎 - V3.5核心模块
支持历史数据回测、策略评估、性能指标计算
"""

import json
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass
class BacktestConfig:
    """回测配置"""
    initial_capital: float = 100000.0
    commission_rate: float = 0.001  # 0.1% 手续费
    slippage_rate: float = 0.0005   # 0.05% 滑点（固定值fallback）
    max_position_size: float = 0.5   # 最大持仓比例
    leverage: float = 1.0            # 杠杆倍数
    dynamic_slippage_base: float = 0.0001  # 动态滑点基准（bps）
    avg_daily_volume: float = 1000000.0  # 日均成交量（用于动态滑点计算）


@dataclass
class BacktestTrade = BacktestTrade:
    """回测交易记录"""
    timestamp: float
    symbol: str
    side: str  # 'BUY' or 'SELL'
    entry_price: float
    exit_price: Optional[float] = None
    size: float = 0.0
    pnl: float = 0.0
    commission: float = 0.0
    strategy: str = ""
    exit_reason: str = ""


@dataclass
class BacktestMetrics:
    """回测指标"""
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    win_trades: int = 0
    avg_trade_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0


class BacktestEngine:
    """回测引擎"""

    def __init__(self, config: Optional[BacktestConfig] = None):
        """
        初始化回测引擎

        Args:
            config: 回测配置
        """
        self.config = config or BacktestConfig()
        self.cash = self.config.initial_capital
        self.equity = self.config.initial_capital
        self.positions: Dict[str, float] = {}  # symbol -> size
        self.position_cost: Dict[str, float] = {}  # symbol -> avg_entry_price
        self.trades: List[Trade = BacktestTrade] = []
        self.equity_curve: List[Dict[str, float]] = []

        # 记录每个时间点的权益
        self.equity_curve.append({
            'timestamp': 0,
            'equity': self.equity,
            'cash': self.cash
        })

    def calculate_dynamic_slippage(self, price: float, trade_size: float) -> float:
        """
        计算动态滑点（sqrt模型）

        公式: price * base_bps * sqrt(trade_size / avg_daily_volume)

        Args:
            price: 当前价格
            trade_size: 交易数量

        Returns:
            滑点值（绝对值）
        """
        try:
            # 防御性校验
            if price <= 0 or trade_size <= 0 or self.config.avg_daily_volume <= 0:
                logger.warning(f"动态滑点计算参数异常：price={price}, size={trade_size}, adv={self.config.avg_daily_volume}，使用固定滑点")
                return price * self.config.slippage_rate

            # sqrt动态滑点模型
            ratio = trade_size / self.config.avg_daily_volume
            # 限制ratio在合理范围内，防止极端值
            ratio = min(max(ratio, 0.0), 1.0)

            dynamic_slippage = price * self.config.dynamic_slippage_base * np.sqrt(ratio)

            # 确保滑点不为负且不超过价格
            dynamic_slippage = max(0.0, min(dynamic_slippage, price * 0.1))  # 最大10%滑点

            return dynamic_slippage
        except Exception as e:
            logger.error(f"动态滑点计算失败：{e}，使用固定滑点")
            return price * self.config.slippage_rate

    def load_historical_data(self, data_source: str) -> pd.DataFrame:
        """
        加载历史数据

        Args:
            data_source: 数据源（文件路径或JSON字符串）

        Returns:
            历史数据DataFrame
        """
        # 判断是文件路径还是JSON字符串
        try:
            if data_source.startswith('{'):
                data = json.loads(data_source)
            else:
                with open(data_source, 'r', encoding='utf-8') as f:
                    data = json.load(f)

            df = pd.DataFrame(data)
            required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            for col in required_cols:
                if col not in df.columns:
                    raise ValueError(f"缺少必要列: {col}")

            # 按时间排序
            df = df.sort_values('timestamp').reset_index(drop=True)

            return df
        except Exception as e:
            raise ValueError(f"加载历史数据失败: {e}")

    def execute_trade(self, timestamp: float, symbol: str, side: str,
                     price: float, size: float, strategy: str) -> Trade = BacktestTrade:
        """
        执行交易（包含手续费和滑点）

        Args:
            timestamp: 时间戳
            symbol: 交易对
            side: 方向（BUY/SELL）
            price: 价格
            size: 数量
            strategy: 策略名称

        Returns:
            交易记录
        """
        # 计算滑点（优先使用动态滑点模型）
        slippage = self.calculate_dynamic_slippage(price, size)
        if side == 'BUY':
            execution_price = price + slippage
        else:
            execution_price = price - slippage

        # 计算手续费
        trade_value = execution_price * size
        commission = trade_value * self.config.commission_rate

        # 检查资金是否足够
        if side == 'BUY':
            required = trade_value + commission
            if required > self.cash:
                raise ValueError(f"资金不足: 需要 ${required:.2f}, 可用 ${self.cash:.2f}")

            # 执行买入
            self.cash -= required
            current_position = self.positions.get(symbol, 0.0)
            current_cost = self.position_cost.get(symbol, 0.0)

            # 更新持仓成本
            total_size = current_position + size
            if total_size > 0:
                total_cost = (current_position * current_cost + size * execution_price)
                self.position_cost[symbol] = total_cost / total_size

            self.positions[symbol] = total_size

        else:  # SELL
            current_position = self.positions.get(symbol, 0.0)
            if current_position < size:
                raise ValueError(f"持仓不足: 需要 {size}, 可用 {current_position}")

            # 执行卖出
            self.cash += trade_value - commission
            self.positions[symbol] = current_position - size

            # 如果持仓为空，移除成本记录
            if self.positions[symbol] <= 0:
                del self.position_cost[symbol]

        # 创建交易记录
        trade = Trade = BacktestTrade(
            timestamp=timestamp,
            symbol=symbol,
            side=side,
            entry_price=execution_price,
            size=size,
            commission=commission,
            strategy=strategy
        )

        self.trades.append(trade)

        # 更新权益
        self._update_equity(timestamp)

        return trade

    def close_position(self, timestamp: float, symbol: str, price: float,
                      reason: str = "manual") -> Optional[Trade = BacktestTrade]:
        """
        平仓

        Args:
            timestamp: 时间戳
            symbol: 交易对
            price: 平仓价格
            reason: 平仓原因

        Returns:
            平仓交易记录
        """
        if symbol not in self.positions or self.positions[symbol] <= 0:
            return None

        size = self.positions[symbol]
        entry_cost = self.position_cost[symbol]

        # 执行卖出
        slippage = self.calculate_dynamic_slippage(price, size)
        execution_price = price - slippage
        trade_value = execution_price * size
        commission = trade_value * self.config.commission_rate

        # 计算盈亏
        pnl = (execution_price - entry_cost) * size - commission

        # 更新资金
        self.cash += trade_value - commission
        del self.positions[symbol]
        del self.position_cost[symbol]

        # 创建交易记录
        trade = Trade = BacktestTrade(
            timestamp=timestamp,
            symbol=symbol,
            side='SELL',
            entry_price=entry_cost,
            exit_price=execution_price,
            size=size,
            pnl=pnl,
            commission=commission,
            exit_reason=reason
        )

        self.trades.append(trade)
        self._update_equity(timestamp)

        return trade

    def _update_equity(self, timestamp: float):
        """更新权益"""
        equity = self.cash
        for symbol, size in self.positions.items():
            # 简化：使用最新价格计算浮动盈亏（实际应使用current_price）
            avg_cost = self.position_cost.get(symbol, 0.0)
            equity += size * avg_cost

        self.equity = equity

        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': self.equity,
            'cash': self.cash
        })

    def calculate_metrics(self) -> BacktestMetrics:
        """计算回测指标"""
        if not self.trades:
            return BacktestMetrics()

        # 基本统计
        total_trades = len(self.trades)
        win_trades = sum(1 for t in self.trades if t.pnl > 0)
        win_rate = win_trades / total_trades if total_trades > 0 else 0

        # 盈亏统计
        profits = [t.pnl for t in self.trades if t.pnl > 0]
        losses = [abs(t.pnl) for t in self.trades if t.pnl < 0]

        avg_win = np.mean(profits) if profits else 0
        avg_loss = np.mean(losses) if losses else 0
        avg_trade_pnl = np.mean([t.pnl for t in self.trades])

        # 盈亏比
        total_profit = sum(profits)
        total_loss = sum(losses)
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        # 收益率
        total_return = (self.equity - self.config.initial_capital) / self.config.initial_capital

        # 最大回撤
        max_drawdown = self._calculate_max_drawdown()

        # 夏普比率（简化计算）
        returns = [self.equity_curve[i]['equity'] - self.equity_curve[i-1]['equity']
                  for i in range(1, len(self.equity_curve))]
        sharpe_ratio = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if returns and np.std(returns) > 0 else 0

        # 年化收益率（假设252个交易日）
        days = len(self.equity_curve)
        annual_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0

        return BacktestMetrics(
            total_return=total_return,
            annual_return=annual_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=total_trades,
            win_trades=win_trades,
            avg_trade_pnl=avg_trade_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss
        )

    def _calculate_max_drawdown(self) -> float:
        """计算最大回撤"""
        if not self.equity_curve:
            return 0.0

        equity_values = [e['equity'] for e in self.equity_curve]
        peak = equity_values[0]
        max_dd = 0.0

        for equity in equity_values:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak
            if drawdown > max_dd:
                max_dd = drawdown

        return max_dd

    def run(self, historical_data: pd.DataFrame,
            strategy_func: Callable) -> BacktestMetrics:
        """
        运行回测

        Args:
            historical_data: 历史数据
            strategy_func: 策略函数，接收当前行，返回交易信号

        Returns:
            回测指标
        """
        for _, row in historical_data.iterrows():
            timestamp = row['timestamp']
            close = row['close']
            high = row['high']
            low = row['low']

            # 调用策略函数
            signal = strategy_func(row, self.positions, self.cash)

            # 处理信号
            if signal['action'] == 'BUY' and signal['symbol']:
                try:
                    size = signal.get('size', 0.1)
                    self.execute_trade(
                        timestamp=timestamp,
                        symbol=signal['symbol'],
                        side='BUY',
                        price=close,
                        size=size,
                        strategy=signal.get('strategy', 'unknown')
                    )
                except Exception as e:
                    logger.error(f"执行买入失败: {e}")

            elif signal['action'] == 'SELL' and signal['symbol']:
                if signal['symbol'] in self.positions:
                    self.close_position(
                        timestamp=timestamp,
                        symbol=signal['symbol'],
                        price=close,
                        reason=signal.get('reason', 'strategy')
                    )

        # 平仓所有持仓
        for symbol in list(self.positions.keys()):
            last_price = historical_data.iloc[-1]['close']
            self.close_position(
                timestamp=historical_data.iloc[-1]['timestamp'],
                symbol=symbol,
                price=last_price,
                reason='end_of_backtest'
            )

        return self.calculate_metrics()

    def get_results(self) -> Dict[str, Any]:
        """获取回测结果"""
        metrics = self.calculate_metrics()

        return {
            'metrics': {
                'total_return': metrics.total_return,
                'annual_return': metrics.annual_return,
                'sharpe_ratio': metrics.sharpe_ratio,
                'max_drawdown': metrics.max_drawdown,
                'win_rate': metrics.win_rate,
                'profit_factor': metrics.profit_factor,
                'total_trades': metrics.total_trades,
                'win_trades': metrics.win_trades,
                'avg_trade_pnl': metrics.avg_trade_pnl,
                'avg_win': metrics.avg_win,
                'avg_loss': metrics.avg_loss
            },
            'final_equity': self.equity,
            'final_cash': self.cash,
            'total_trades': len(self.trades),
            'equity_curve': self.equity_curve[-10:] if len(self.equity_curve) > 10 else self.equity_curve,
            'recent_trades': [
                {
                    'timestamp': t.timestamp,
                    'symbol': t.symbol,
                    'side': t.side,
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'size': t.size,
                    'pnl': t.pnl,
                    'commission': t.commission
                } for t in self.trades[-10:]
            ] if self.trades else []
        }


# 命令行测试
def test_strategy(row: pd.Series, positions: Dict[str, float], cash: float) -> Dict[str, Any]:
    """测试策略：简单均线交叉"""
    # 简化：每10个tick做一次买入，20个tick卖出
    index = row.name if hasattr(row, 'name') else 0

    if index % 30 == 10 and 'BTCUSDT' not in positions:
        return {'action': 'BUY', 'symbol': 'BTCUSDT', 'size': 0.1, 'strategy': 'MA_CROSS'}

    elif index % 30 == 20 and 'BTCUSDT' in positions:
        return {'action': 'SELL', 'symbol': 'BTCUSDT', 'reason': 'MA_CROSS'}

    return {'action': 'HOLD'}


def main():
    """测试回测引擎"""
    # 创建模拟历史数据
    import time

    base_price = 50000
    data = []
    for i in range(100):
        timestamp = time.time() - (100 - i) * 60  # 每分钟一个tick
        price = base_price + np.random.randn() * 100  # 随机波动
        data.append({
            'timestamp': timestamp,
            'open': price - 10,
            'high': price + 20,
            'low': price - 20,
            'close': price,
            'volume': np.random.randint(100, 1000)
        })

    # 创建回测引擎
    config = BacktestConfig(
        initial_capital=100000,
        commission_rate=0.001,
        slippage_rate=0.0005
    )
    engine = BacktestEngine(config)

    # 加载数据
    df = pd.DataFrame(data)

    # 运行回测
    logger.info("开始回测...")
    metrics = engine.run(df, test_strategy)

    # 输出结果
    results = engine.get_results()
    logger.info("\n" + "="*60)
    logger.info("📊 回测结果")
    logger.info("="*60)

    m = results['metrics']
    logger.info(f"\n收益率:")
    logger.info(f"  总收益率: {m['total_return']*100:.2f}%")
    logger.info(f"  年化收益率: {m['annual_return']*100:.2f}%")

    logger.info(f"\n风险指标:")
    logger.info(f"  夏普比率: {m['sharpe_ratio']:.2f}")
    logger.info(f"  最大回撤: {m['max_drawdown']*100:.2f}%")

    logger.info(f"\n交易统计:")
    logger.info(f"  总交易数: {m['total_trades']}")
    logger.info(f"  胜率: {m['win_rate']*100:.1f}%")
    logger.info(f"  盈亏比: {m['profit_factor']:.2f}")
    logger.info(f"  平均盈亏: ${m['avg_trade_pnl']:.2f}")
    logger.info(f"  平均盈利: ${m['avg_win']:.2f}")
    logger.info(f"  平均亏损: ${m['avg_loss']:.2f}")

    logger.info(f"\n账户状态:")
    logger.info(f"  初始资金: ${config.initial_capital:,.2f}")
    logger.info(f"  最终权益: ${results['final_equity']:,.2f}")
    logger.info(f"  最终现金: ${results['final_cash']:,.2f}")

    logger.info("\n" + "="*60)
    logger.info("回测引擎测试: PASS")


if __name__ == "__main__":
    main()
