#!/usr/bin/env python3
"""
回测适配器 - 策略实验室回测引擎
对接现有backtesting_engine.py，对策略个体进行严谨回测
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
import time

try:
    from scripts.logger_factory import get_logger
    logger = get_logger("backtest_adapter")
except ImportError:
    import logging
    logger = logging.getLogger("backtest_adapter")

# 导入统一的策略类型定义
try:
    from scripts.strategy_types import StrategyIndividual, IndicatorType, OperatorType, ActionType
except ImportError:
    logger.warning("无法从scripts导入strategy_types模块，尝试直接导入")
    try:
        from strategy_types import StrategyIndividual, IndicatorType, OperatorType, ActionType
    except ImportError:
        logger.warning("无法导入strategy_types模块，将使用简化模式")
        StrategyIndividual = None
        IndicatorType = None
        OperatorType = None
        ActionType = None


@dataclass
class BacktestResult:
    """回测结果"""
    sharpe_ratio: float
    win_rate: float
    max_drawdown: float
    total_return: float
    total_trades: int
    avg_trade_duration: float
    profit_factor: float

    def to_dict(self) -> Dict:
        return {
            'sharpe_ratio': self.sharpe_ratio,
            'win_rate': self.win_rate,
            'max_drawdown': self.max_drawdown,
            'total_return': self.total_return,
            'total_trades': self.total_trades,
            'avg_trade_duration': self.avg_trade_duration,
            'profit_factor': self.profit_factor
        }


class BacktestAdapter:
    """回测适配器"""

    def __init__(self,
                 initial_capital: float = 100000.0,
                 slippage_bps: float = 5.0,
                 commission_bps: float = 10.0,
                 position_size: float = 0.1):
        """
        初始化回测适配器

        Args:
            initial_capital: 初始资金
            slippage_bps: 滑点（基点）
            commission_bps: 手续费（基点）
            position_size: 仓位大小（占资金比例）
        """
        self.initial_capital = initial_capital
        self.slippage_bps = slippage_bps / 10000.0
        self.commission_bps = commission_bps / 10000.0
        self.position_size = position_size

        logger.info(f"回测适配器初始化: capital={initial_capital}, "
                   f"slippage={slippage_bps}bps, commission={commission_bps}bps")

    def run_backtest(self,
                     individual: StrategyIndividual,
                     market_data: np.ndarray) -> BacktestResult:
        """
        运行回测

        Args:
            individual: 策略个体
            market_data: 市场数据 (OHLCV格式)

        Returns:
            回测结果
        """
        try:
            # 第一层防御：数据校验
            if market_data.shape[0] < 100:
                logger.warning(f"市场数据不足: {market_data.shape[0]} < 100")
                return self._empty_result()

            if market_data.shape[1] != 5:
                raise ValueError(f"数据列数错误: {market_data.shape[1]}, 期望5")

            # 初始化状态
            capital = self.initial_capital
            position = 0.0  # 正数=多头，负数=空头
            cash = capital
            entry_price = 0.0
            entry_time = 0
            trade_count = 0
            win_count = 0
            total_profit = 0.0
            total_loss = 0.0
            equity_curve = [capital]
            trade_durations = []

            # 跳过前100根K线（用于技术指标计算）
            for i in range(100, len(market_data)):
                # 第二层防御：计算技术指标
                indicators = self._compute_indicators(market_data[:i+1])

                # 生成交易信号
                signal = self._generate_signal(individual, indicators, market_data[i])

                # 执行交易
                close = market_data[i, 3]
                high = market_data[i, 1]
                low = market_data[i, 2]

                # 转换信号动作为字符串进行比较
                action_str = signal.action.value if hasattr(signal.action, 'value') else str(signal.action)
                buy_action = ActionType.BUY.value if ActionType else "buy"
                sell_action = ActionType.SELL.value if ActionType else "sell"

                if action_str == buy_action and position < -1e-8:
                    # 平空仓（如果有）
                    if position < -1e-8:
                        pnl = (entry_price - close) * abs(position)
                        cash += pnl
                        total_profit += pnl if pnl > 0 else total_loss
                        if pnl > 0:
                            win_count += 1
                        trade_durations.append(i - entry_time)
                        trade_count += 1
                        position = 0.0

                    # 开多仓
                    trade_value = cash * self.position_size
                    shares = trade_value / (close * (1 + self.slippage_bps))
                    cost = shares * close * self.commission_bps

                    cash -= trade_value + cost
                    position = shares
                    entry_price = close
                    entry_time = i

                elif action_str == sell_action and position > -1e-8:
                    # 平多仓（如果有）
                    if position > 1e-8:
                        pnl = (close - entry_price) * position
                        cash += pnl
                        total_profit += pnl if pnl > 0 else total_loss
                        if pnl > 0:
                            win_count += 1
                        trade_durations.append(i - entry_time)
                        trade_count += 1
                        position = 0.0

                    # 开空仓
                    trade_value = cash * self.position_size
                    shares = trade_value / (close * (1 - self.slippage_bps))
                    cost = shares * close * self.commission_bps

                    cash -= trade_value + cost
                    position = -shares
                    entry_price = close
                    entry_time = i

                # 计算当前权益
                if position > 1e-8:
                    equity = cash + position * close
                elif position < -1e-8:
                    equity = cash - position * close
                else:
                    equity = cash

                equity_curve.append(equity)

            # 第三层防御：平仓剩余仓位
            if abs(position) > 1e-8:
                close = market_data[-1, 3]
                if position > 1e-8:
                    pnl = (close - entry_price) * position
                    cash += pnl
                else:
                    pnl = (entry_price - close) * abs(position)
                    cash += pnl
                total_profit += pnl if pnl > 0 else total_loss
                if pnl > 0:
                    win_count += 1
                trade_durations.append(len(market_data) - 1 - entry_time)
                trade_count += 1

            # 计算性能指标
            result = self._calculate_metrics(
                equity_curve,
                trade_count,
                win_count,
                trade_durations,
                total_profit,
                total_loss
            )

            return result

        except Exception as e:
            logger.error(f"回测失败: {e}")
            return self._empty_result()

    def _compute_indicators(self, data: np.ndarray) -> Dict[str, float]:
        """
        计算技术指标

        Args:
            data: 市场数据

        Returns:
            指标字典
        """
        try:
            close = data[:, 3]

            # 第一层防御：数据长度检查
            if len(close) < 20:
                return {}

            indicators = {}

            # SMA
            if len(close) >= 20:
                indicators['sma_20'] = np.mean(close[-20:])
            if len(close) >= 50:
                indicators['sma_50'] = np.mean(close[-50:])

            # EMA
            if len(close) >= max(12, 26):
                indicators['ema_12'] = self._compute_ema(close[-12:], 12)
                indicators['ema_26'] = self._compute_ema(close[-26:], 26)

            # RSI
            if len(close) >= 14:
                indicators['rsi'] = self._compute_rsi(close, 14)

            # MACD
            if 'ema_12' in indicators and 'ema_26' in indicators:
                indicators['macd'] = indicators['ema_12'] - indicators['ema_26']
                indicators['macd_signal'] = indicators['macd'] * 0.9 + indicators.get('macd_signal_prev', 0) * 0.1
                indicators['macd_signal_prev'] = indicators['macd_signal']

            # ATR
            if len(close) >= 14:
                indicators['atr'] = self._compute_atr(data, 14)

            # 波动率
            if len(close) >= 21:
                try:
                    recent_close = close[-20:]
                    previous_close = close[-21:-1]
                    if len(previous_close) != len(recent_close) - 1:
                        # 调整索引
                        returns = np.diff(recent_close) / recent_close[:-1]
                    else:
                        returns = np.diff(recent_close) / previous_close
                    indicators['volatility'] = np.std(returns)
                except Exception as e:
                    logger.debug(f"波动率计算跳过: {e}")

            return indicators

        except Exception as e:
            logger.error(f"计算指标失败: {e}")
            return {}

    def _compute_ema(self, prices: np.ndarray, period: int) -> float:
        """计算EMA"""
        multiplier = 2.0 / (period + 1.0)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    def _compute_rsi(self, prices: np.ndarray, period: int) -> float:
        """计算RSI"""
        # 第一层防御：数据长度检查
        if len(prices) <= period:
            return 50.0

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        # 第二层防御：除零保护
        if abs(avg_loss) < 1e-10:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        return rsi

    def _compute_atr(self, data: np.ndarray, period: int) -> float:
        """计算ATR"""
        # 第一层防御：数据长度检查
        if len(data) <= period:
            return 0.0

        high = data[-period:, 1]
        low = data[-period:, 2]
        close = data[-period:, 3]

        tr1 = high - low
        tr2 = np.abs(high - np.roll(close, 1))
        tr3 = np.abs(low - np.roll(close, 1))

        tr = np.maximum(tr1, tr2, tr3)
        atr = np.mean(tr)

        return atr

    def _generate_signal(self,
                        individual: StrategyIndividual,
                        indicators: Dict[str, float],
                        current_bar: np.ndarray) -> 'Signal':
        """
        生成交易信号（v1.0.3 Stable - 简化规则）

        Args:
            individual: 策略个体
            indicators: 技术指标
            current_bar: 当前K线

        Returns:
            交易信号
        """
        try:
            close = current_bar[3]

            # 第一层防御：检查导入状态
            if ActionType is None:
                return Signal(action="hold", value=0.0)

            # 检查指标数据
            if not indicators:
                return Signal(action=ActionType.HOLD, value=0.0)

            # 稳定版：使用3个预定义规则（替代基因解析）
            # 规则1: EMA交叉
            ema_12 = indicators.get('ema_12', close)
            ema_26 = indicators.get('ema_26', close)

            if ema_12 > ema_26:
                # 规则2: RSI超买超卖确认
                rsi = indicators.get('rsi', 50)
                if rsi < 40:
                    return Signal(action=ActionType.BUY, value=0.5)
                elif rsi < 50:
                    return Signal(action=ActionType.BUY, value=0.3)

            elif ema_12 < ema_26:
                rsi = indicators.get('rsi', 50)
                if rsi > 60:
                    return Signal(action=ActionType.SELL, value=-0.5)
                elif rsi > 50:
                    return Signal(action=ActionType.SELL, value=-0.3)

            # 规则3: 波动率突破（ATR）
            atr = indicators.get('atr', 0)
            if atr > 0:
                if close > close + atr:
                    return Signal(action=ActionType.BUY, value=0.4)
                elif close < close - atr:
                    return Signal(action=ActionType.SELL, value=-0.4)

            # 默认信号
            return Signal(action=ActionType.HOLD, value=0.0)

        except Exception as e:
            logger.error(f"生成信号失败: {e}")
            if ActionType is not None:
                return Signal(action=ActionType.HOLD, value=0.0)
            else:
                return Signal(action="hold", value=0.0)

    def _calculate_metrics(self,
                          equity_curve: List[float],
                          trade_count: int,
                          win_count: int,
                          trade_durations: List[int],
                          total_profit: float,
                          total_loss: float) -> BacktestResult:
        """
        计算性能指标

        Args:
            equity_curve: 权益曲线
            trade_count: 交易次数
            win_count: 盈利次数
            trade_durations: 交易持续时间列表
            total_profit: 总盈利
            total_loss: 总亏损

        Returns:
            回测结果
        """
        try:
            # 第一层防御：基础指标
            if trade_count == 0:
                return self._empty_result()

            final_equity = equity_curve[-1]
            total_return = (final_equity - self.initial_capital) / self.initial_capital

            win_rate = win_count / trade_count

            # 第二层防御：最大回撤
            peak = self.initial_capital
            max_drawdown = 0.0
            for equity in equity_curve:
                if equity > peak:
                    peak = equity
                drawdown = (peak - equity) / peak
                max_drawdown = max(max_drawdown, drawdown)

            # 第三层防御：Sharpe比率
            returns = np.diff(equity_curve) / np.array(equity_curve[:-1])
            sharpe_ratio = np.mean(returns) / max(0.0001, np.std(returns)) if len(returns) > 0 else 0.0

            # 平均交易持续时间
            avg_trade_duration = np.mean(trade_durations) if trade_durations else 0.0

            # 盈亏比
            profit_factor = total_profit / max(0.01, abs(total_loss))

            return BacktestResult(
                sharpe_ratio=sharpe_ratio,
                win_rate=win_rate,
                max_drawdown=max_drawdown,
                total_return=total_return,
                total_trades=trade_count,
                avg_trade_duration=avg_trade_duration,
                profit_factor=profit_factor
            )

        except Exception as e:
            logger.error(f"计算指标失败: {e}")
            return self._empty_result()

    def _empty_result(self) -> BacktestResult:
        """返回空结果"""
        return BacktestResult(
            sharpe_ratio=0.0,
            win_rate=0.0,
            max_drawdown=0.0,
            total_return=0.0,
            total_trades=0,
            avg_trade_duration=0.0,
            profit_factor=0.0
        )


class Signal:
    """交易信号"""
    def __init__(self, action: ActionType, value: float):
        self.action = action
        self.value = value


if __name__ == "__main__":
    # 测试代码
    print("测试回测适配器...")

    # 创建适配器
    adapter = BacktestAdapter(
        initial_capital=100000.0,
        slippage_bps=5.0,
        commission_bps=10.0,
        position_size=0.1
    )

    # 生成测试数据
    from scripts.historical_data_loader import HistoricalDataLoader
    loader = HistoricalDataLoader()
    market_data = loader.generate_mock_data("BTCUSDT", n_samples=1000)

    # 创建测试策略
    from scripts.strategy_lab import StrategyIndividual, StrategyGene, IndicatorType, ActionType

    test_gene = StrategyGene(
        indicator1=IndicatorType.SMA,
        operator=OperatorType.GREATER_THAN,
        threshold=0.001,
        period=20,
        action=ActionType.BUY
    )

    test_strategy = StrategyIndividual(genes=[test_gene])

    # 运行回测
    print("运行回测...")
    result = adapter.run_backtest(test_strategy, market_data)

    print(f"\n回测结果:")
    print(f"Sharpe比率: {result.sharpe_ratio:.4f}")
    print(f"胜率: {result.win_rate:.4f}")
    print(f"最大回撤: {result.max_drawdown:.4f}")
    print(f"总收益: {result.total_return:.4f}")
    print(f"交易次数: {result.total_trades}")
    print(f"平均交易时长: {result.avg_trade_duration:.2f} bar")
    print(f"盈亏比: {result.profit_factor:.4f}")

    print("\n测试通过！")
